"""subtitle_node — forced-alignment subtitle stage (Story 1.8).

Generates one UTF-8 .srt file per scene from known narration text and per-scene audio.
Reuses SceneState.word_timings when populated by tts_node; falls back to YTFLOW_ALIGNER
otherwise. Layer rule: imports domain and config only; no db/, api/, services/. [AD-1]
"""

import asyncio
import time
from pathlib import Path
from typing import Protocol, TypedDict

from langfuse import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState, WordTiming


# ── Aligner contract ──────────────────────────────────────────────────────────


class AlignmentSegment(TypedDict):
    start_sec: float
    end_sec: float
    text: str


class SubtitleAligner(Protocol):
    async def align(self, audio_path: str, transcript: str) -> list[AlignmentSegment]: ...


class WhisperXAligner:
    """WhisperX forced-alignment backend.

    whisperx is not in pyproject.toml; install it separately.
    Lazy import keeps this module loadable without whisperx present.
    """

    def __init__(self, model: str, device: str, compute_type: str) -> None:
        self._model, self._device, self._compute_type = model, device, compute_type

    async def align(self, audio_path: str, transcript: str) -> list[AlignmentSegment]:
        # ponytail: get_running_loop() is safe inside a coroutine; get_event_loop() is deprecated in 3.10+
        return await asyncio.get_running_loop().run_in_executor(
            None, self._align_sync, audio_path, transcript
        )

    def _align_sync(self, audio_path: str, transcript: str) -> list[AlignmentSegment]:
        try:
            import whisperx
        except ImportError as exc:
            raise ImportError(
                "whisperx not installed; pip install whisperx to use YTFLOW_ALIGNER=whisperx"
            ) from exc
        model = whisperx.load_model(self._model, self._device, compute_type=self._compute_type)
        audio = whisperx.load_audio(audio_path)
        result = model.transcribe(audio)
        align_model, meta = whisperx.load_align_model(language_code="ko", device=self._device)
        # ponytail: len(audio)/16000 gives actual duration; 999.0 sentinel caused garbage alignment on short clips
        last_end = result["segments"][-1]["end"] if result.get("segments") else len(audio) / 16000
        aligned = whisperx.align(
            [{"text": transcript, "start": 0.0, "end": last_end}],
            align_model, meta, audio, self._device,
        )
        words = aligned.get("word_segments", [])
        if words:
            return [{"start_sec": w["start"], "end_sec": w["end"], "text": w["word"]}
                    for w in words if "start" in w and "end" in w]
        return [{"start_sec": s["start"], "end_sec": s["end"], "text": s["text"]}
                for s in aligned.get("segments", [])]


def _get_aligner(s: Settings) -> SubtitleAligner:
    if s.aligner == "whisperx":
        return WhisperXAligner(s.aligner_model, s.aligner_device, s.aligner_compute_type)
    raise ValueError(f"Unsupported YTFLOW_ALIGNER: {s.aligner!r}; supported: ['whisperx']")


# ── SRT utilities ─────────────────────────────────────────────────────────────


def _srt_time(sec: float) -> str:
    sec = max(sec, 0.0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    ms = round((s % 1) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


def format_srt(segments: list[AlignmentSegment]) -> str:
    """Produce a UTF-8 SRT string; empty list returns empty string."""
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines += [str(i), f"{_srt_time(seg['start_sec'])} --> {_srt_time(seg['end_sec'])}", seg["text"], ""]
    # ponytail: trailing \n ensures each cue block ends with a blank line as required by the SRT spec
    return "\n".join(lines) + "\n" if lines else ""


def _word_timings_to_segments(timings: list[WordTiming], max_chars: int = 40) -> list[AlignmentSegment]:
    """Group word-level timings into readable SRT cues (≤ max_chars per cue)."""
    if not timings:
        return []
    segments: list[AlignmentSegment] = []
    batch: list[WordTiming] = []
    for wt in timings:
        candidate = (" ".join(t["word"] for t in batch) + " " + wt["word"]).strip()
        if batch and len(candidate) > max_chars:
            segments.append({
                "start_sec": batch[0]["start_sec"],
                "end_sec": batch[-1]["end_sec"],
                "text": " ".join(t["word"] for t in batch),
            })
            batch = [wt]
        else:
            batch.append(wt)
    if batch:
        segments.append({
            "start_sec": batch[0]["start_sec"],
            "end_sec": batch[-1]["end_sec"],
            "text": " ".join(t["word"] for t in batch),
        })
    return segments


def _validate_segments(segments: list[AlignmentSegment], audio_duration: float | None, scene_num: int) -> None:
    """Assert monotonic, non-negative, non-overlapping cue timings."""
    prev_end = 0.0
    for seg in segments:
        if seg["start_sec"] < -0.001:
            raise ValueError(f"scene {scene_num}: negative cue start {seg['start_sec']:.3f}")
        if seg["end_sec"] <= seg["start_sec"]:
            raise ValueError(f"scene {scene_num}: end_sec ≤ start_sec in cue {seg!r}")
        if seg["start_sec"] < prev_end - 1e-6:
            raise ValueError(f"scene {scene_num}: overlapping cues at start={seg['start_sec']:.3f}")
        prev_end = seg["end_sec"]
    # ponytail: `is not None` instead of truthiness check — audio_duration=0.0 is a valid boundary
    if audio_duration is not None and prev_end > audio_duration + 0.1:
        raise ValueError(
            f"scene {scene_num}: last cue end {prev_end:.3f} exceeds audio duration {audio_duration:.3f}"
        )


# ── Observability ─────────────────────────────────────────────────────────────


def _settings() -> Settings:
    # ponytail: one seam so unit tests can inject fake settings without a real .env.
    return Settings()


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _record_trace(*, run_id: str, scene_count: int, latency_ms: int, error=None) -> None:
    """Best-effort Langfuse span enrichment. [AD-10 — tracing is non-fatal]"""
    try:
        get_client().update_current_span(
            metadata={
                "run_id": run_id,
                "scene_count": scene_count,
                "latency_ms": latency_ms,
                **({"error": repr(error)} if error is not None else {}),
            }
        )
    except Exception:  # noqa: BLE001
        pass


# ── Node ──────────────────────────────────────────────────────────────────────


@observe(name="subtitle")
async def subtitle_node(state: PipelineState) -> dict:
    run_id = state.get("run_id", "?")
    t0 = time.perf_counter()
    try:
        s = _settings()
        aligner = _get_aligner(s)  # validate config upfront; fail fast on bad YTFLOW_ALIGNER
        subtitle_dir = Path(s.workspace_path) / run_id / "subtitles"
        subtitle_dir.mkdir(parents=True, exist_ok=True)

        new_scenes: list[SceneState] = []
        for scene in sorted(state["scenes"], key=lambda sc: sc["scene_num"]):
            n = scene["scene_num"]
            if not scene.get("narration"):
                raise ValueError(f"scene {n}: narration is empty")
            audio = scene.get("audio_path")
            if not audio or not Path(audio).exists():
                raise FileNotFoundError(f"scene {n}: audio_path missing or not found: {audio!r}")

            # Reuse word_timings from tts_node when populated [Story 1.8 SRT rules]
            timings: list[WordTiming] = scene.get("word_timings") or []
            if timings:
                segments = _word_timings_to_segments(timings)
            else:
                segments = await aligner.align(audio, scene["narration"])

            if not segments:
                raise ValueError(f"scene {n}: aligner returned no segments for non-empty narration")
            _validate_segments(segments, scene.get("audio_duration"), n)

            path = subtitle_dir / f"scene_{n:03d}.srt"
            path.write_text(format_srt(segments), encoding="utf-8")
            new_scenes.append({**scene, "subtitle_path": str(path)})

        _record_trace(run_id=run_id, scene_count=len(new_scenes), latency_ms=_ms(t0))
        return {"scenes": new_scenes, "current_stage": "subtitle"}
    except Exception as exc:  # noqa: BLE001
        _record_trace(run_id=run_id, scene_count=len(state.get("scenes", [])),
                      latency_ms=_ms(t0), error=exc)
        return {"current_stage": "subtitle", "error": f"stage=subtitle run_id={run_id}: {exc}"}
