"""subtitle_node — static sentence-cue subtitle stage (Story 1.8, typography-first Story 5.18).

Generates one UTF-8 .ass file per scene from known narration text and per-scene audio.
Reuses SceneState.word_timings when populated by tts_node; falls back to YTFLOW_ALIGNER
otherwise. Cues render the scene's display_narration (original writing text) timed
against the spoken narration track — see sentence_cues(). Layer rule: imports domain
and config only; no db/, api/, services/. [AD-1]
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Protocol, TypedDict

from yt_flow.observability import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState, WordTiming
from yt_flow.pipeline.nodes.scenario_chain import split_sentences

logger = logging.getLogger(__name__)


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

    def __init__(self, model: str, device: str, compute_type: str, language: str) -> None:
        self._model, self._device, self._compute_type = model, device, compute_type
        self._language = language

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
        align_model, meta = whisperx.load_align_model(language_code=self._language, device=self._device)
        # ponytail: len(audio)/16000 gives actual duration; 999.0 sentinel caused garbage alignment on short clips
        last_end = result["segments"][-1]["end"] if result.get("segments") else len(audio) / 16000
        aligned = whisperx.align(
            [{"text": transcript, "start": 0.0, "end": last_end}],
            align_model, meta, audio, self._device,
        )
        return _words_or_segments(aligned)


def _words_or_segments(aligned: dict) -> list[AlignmentSegment]:
    """Prefer word-level timing; fall back to segment-level if no word has usable start/end."""
    usable = [{"start_sec": w["start"], "end_sec": w["end"], "text": w["word"]}
              for w in aligned.get("word_segments", []) if "start" in w and "end" in w]
    if usable:
        return usable
    return [{"start_sec": s["start"], "end_sec": s["end"], "text": s["text"]}
            for s in aligned.get("segments", [])]


def _get_aligner(s: Settings) -> SubtitleAligner:
    if s.aligner == "whisperx":
        return WhisperXAligner(s.aligner_model, s.aligner_device, s.aligner_compute_type, s.content_language)
    raise ValueError(f"Unsupported YTFLOW_ALIGNER: {s.aligner!r}; supported: ['whisperx']")


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


# ── Static ASS typography (Story 5.18) ─────────────────────────────────────────

SUBTITLE_FONT_FAMILY = "Pretendard SemiBold"  # pinned via `fc-scan`; see data/fonts/README.md
SUBTITLE_FONT_SIZE = 60
SUBTITLE_OUTLINE_WIDTH = 3
SUBTITLE_SHADOW = 1
SUBTITLE_MARGIN_V = 54

# ponytail: must match video.COMP_W/COMP_H (compositor resolution) — kept local
# to avoid importing video.py (would pull ffmpeg/subprocess into this layer).
PLAY_RES_X = 1920
PLAY_RES_Y = 1080

# Korean subtitle norms (Dev Notes): guidance, not hard limits — 60px burn-in
# type would over-fragment at a strict 16-char/line cap.
_LINE_CHAR_GUIDANCE = 16   # wrap to 2 lines once a cue's text exceeds this
_CUE_CHAR_SOFT_CAP = 44    # sentence text beyond this splits into multiple cues


def _escape_ass_text(text: str) -> str:
    """Strip characters that would break out of a plain Dialogue text field.

    Must run BEFORE `wrap_cue_text` injects `\\N` — escaping afterward would
    strip the line-break backslash we just added.
    """
    return text.replace("\\", "").replace("{", "").replace("}", "")


def wrap_cue_text(text: str) -> str:
    """Wrap cue text to at most 2 lines (`\\N`), breaking at the word boundary
    nearest the character midpoint. [AC:4]"""
    words = text.split()
    if len(words) <= 1 or len(text) <= _LINE_CHAR_GUIDANCE:
        return text
    mid = len(text) / 2
    best_i, best_dist, cursor = 0, None, 0
    for i, w in enumerate(words[:-1]):  # never break after the last word
        cursor += len(w) + 1  # +1 for the following space
        dist = abs(cursor - mid)
        if best_dist is None or dist < best_dist:
            best_dist, best_i = dist, i
    line1 = " ".join(words[: best_i + 1])
    line2 = " ".join(words[best_i + 1:])
    return f"{line1}\\N{line2}"


def _chunk_words(words: list[str], cap: int) -> list[str]:
    """Greedily batch words into pieces of at most `cap` characters each."""
    chunks: list[str] = []
    current: list[str] = []
    for w in words:
        candidate = " ".join(current + [w])
        if current and len(candidate) > cap:
            chunks.append(" ".join(current))
            current = [w]
        else:
            current.append(w)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _apportion(lengths: list[int], start: float, end: float) -> list[tuple[float, float]]:
    """Split [start, end] into windows proportional to `lengths` (character counts)."""
    total_chars = sum(lengths) or len(lengths) or 1
    total_dur = end - start
    windows: list[tuple[float, float]] = []
    cursor = start
    n = len(lengths)
    for i, length in enumerate(lengths):
        if i == n - 1:
            windows.append((cursor, end))
        else:
            nxt = cursor + total_dur * (length / total_chars)
            windows.append((cursor, nxt))
            cursor = nxt
    return windows


def _sentence_to_cues(sentence: str, start: float, end: float) -> list[AlignmentSegment]:
    """One sentence's window -> one cue, or several proportionally-timed cues
    when the sentence text exceeds the soft cap. [AC:4]"""
    escaped = _escape_ass_text(sentence)
    if len(escaped) <= _CUE_CHAR_SOFT_CAP:
        return [{"start_sec": start, "end_sec": end, "text": wrap_cue_text(escaped)}]
    chunks = _chunk_words(escaped.split(), _CUE_CHAR_SOFT_CAP)
    windows = _apportion([len(c) for c in chunks], start, end)
    return [
        {"start_sec": s, "end_sec": e, "text": wrap_cue_text(c)}
        for (s, e), c in zip(windows, chunks)
    ]


def sentence_windows(timings: list[WordTiming], spoken_text: str) -> list[tuple[float, float]]:
    """Per-sentence (start, end) windows from the spoken track's word timings.

    The unit `sentence_cues` builds its cues from and Story 8.11's per-shot cut
    assembly derives its clip boundaries from — one implementation, so cuts
    and subtitles can never drift apart. Degrades to apportioning windows by
    character length when the word-timings count doesn't match the spoken
    word count (or there are none). [AC:1,7]
    """
    spoken_sentences = split_sentences(spoken_text)
    if not spoken_sentences or not timings:
        return []

    spoken_word_counts = [len(s.split()) for s in spoken_sentences]
    if sum(spoken_word_counts) != len(timings):
        logger.warning(
            "sentence_cues: word_timings count (%d) != spoken word count (%d); "
            "apportioning sentence windows by character length, falling back to spoken text",
            len(timings), sum(spoken_word_counts),
        )
        start, end = timings[0]["start_sec"], timings[-1]["end_sec"]
        return _apportion([len(s) for s in spoken_sentences], start, end)

    windows: list[tuple[float, float]] = []
    idx = 0
    for wc in spoken_word_counts:
        group = timings[idx: idx + wc]
        windows.append((group[0]["start_sec"], group[-1]["end_sec"]))
        idx += wc
    return windows


def sentence_cues(
    timings: list[WordTiming], spoken_text: str, display_text: str
) -> list[AlignmentSegment]:
    """Sentence-level cues: windows from the spoken track's word timings, text
    from the matching display-track sentence. [AC:4]

    Guards degrade to spoken-track-only cues, warning only for genuine count
    mismatches (not for an absent/identical display track — that's the
    expected single-track case). [AC:7]
    """
    spoken_sentences = split_sentences(spoken_text)
    if not spoken_sentences or not timings:
        return []

    display_sentences = split_sentences(display_text) if display_text else []
    if len(display_sentences) != len(spoken_sentences):
        if display_text and display_text != spoken_text:
            logger.warning(
                "sentence_cues: display/spoken sentence-count mismatch (display=%d, spoken=%d); "
                "falling back to spoken text",
                len(display_sentences), len(spoken_sentences),
            )
        display_sentences = spoken_sentences

    spoken_word_counts = [len(s.split()) for s in spoken_sentences]
    if sum(spoken_word_counts) != len(timings):
        # AC:7 — a word_timings/text mismatch is exactly the "degrade to spoken track"
        # case, not just a re-apportioning case; display_sentences must fall back too.
        display_sentences = spoken_sentences

    windows = sentence_windows(timings, spoken_text)

    cues: list[AlignmentSegment] = []
    for (start, end), sentence in zip(windows, display_sentences):
        cues.extend(_sentence_to_cues(sentence, start, end))
    return cues


def _ass_time(sec: float) -> str:
    """ASS timestamp: H:MM:SS.cc (centiseconds)."""
    total_cs = round(max(sec, 0.0) * 100)
    cs, total_s = total_cs % 100, total_cs // 100
    s, total_m = total_s % 60, total_s // 60
    m, h = total_m % 60, total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_header() -> str:
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {PLAY_RES_X}\n"
        f"PlayResY: {PLAY_RES_Y}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{SUBTITLE_FONT_FAMILY},{SUBTITLE_FONT_SIZE},&H00FFFFFF,&H00FFFFFF,"
        f"&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{SUBTITLE_OUTLINE_WIDTH},{SUBTITLE_SHADOW},"
        f"2,10,10,{SUBTITLE_MARGIN_V},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def format_ass(cues: list[AlignmentSegment]) -> str:
    """Full .ass file: header + plain Dialogue events (no `\\k` karaoke). [AC:4,5]"""
    lines = [
        f"Dialogue: 0,{_ass_time(c['start_sec'])},{_ass_time(c['end_sec'])},Default,,0,0,0,,{c['text']}"
        for c in cues
    ]
    return _ass_header() + ("\n".join(lines) + "\n" if lines else "")


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
        if s.content_language != "ko":
            raise NotImplementedError(
                f"content_language={s.content_language!r} not supported yet; scenario prompts, "
                "TTS naturalization, and subtitle typography are Korean-only (YTFLOW_CONTENT_LANGUAGE)"
            )
        aligner = _get_aligner(s)  # validate config upfront; fail fast on bad YTFLOW_ALIGNER
        subtitle_dir = Path(s.workspace_path) / run_id / "subtitles"
        subtitle_dir.mkdir(parents=True, exist_ok=True)

        new_scenes: list[SceneState] = []
        for scene in sorted(state["scenes"], key=lambda sc: sc["scene_num"]):
            n = scene["scene_num"]
            narration = scene.get("narration")
            if not narration:
                raise ValueError(f"scene {n}: narration is empty")
            audio = scene.get("audio_path")
            if not audio or not Path(audio).exists():
                raise FileNotFoundError(f"scene {n}: audio_path missing or not found: {audio!r}")

            # Reuse word_timings from tts_node when populated; display_narration
            # absent (old checkpoints) falls back to the spoken track. [AC:1,7]
            timings: list[WordTiming] = scene.get("word_timings") or []
            display = scene.get("display_narration") or narration
            cues: list[AlignmentSegment]
            if timings:
                cues = sentence_cues(timings, narration, display)
            else:
                # Aligner-fallback: segment-level only, so display mapping has no
                # sentence anchor here — cues carry the spoken transcript. [AC:7, Saved Questions]
                segments = await aligner.align(audio, narration)
                cues = [
                    {"start_sec": seg["start_sec"], "end_sec": seg["end_sec"],
                     "text": wrap_cue_text(_escape_ass_text(seg["text"]))}
                    for seg in segments
                ]

            if not cues:
                raise ValueError(f"scene {n}: no subtitle cues produced for non-empty narration")
            _validate_segments(cues, scene.get("audio_duration"), n)

            path = subtitle_dir / f"scene_{n:03d}.ass"
            path.write_text(format_ass(cues), encoding="utf-8")
            new_scenes.append({**scene, "subtitle_path": str(path)})

        _record_trace(run_id=run_id, scene_count=len(new_scenes), latency_ms=_ms(t0))
        return {"scenes": new_scenes, "current_stage": "subtitle", "error": None}
    except Exception as exc:  # noqa: BLE001
        _record_trace(run_id=run_id, scene_count=len(state.get("scenes", [])),
                      latency_ms=_ms(t0), error=exc)
        return {"current_stage": "subtitle", "error": f"stage=subtitle run_id={run_id}: {exc}"}
