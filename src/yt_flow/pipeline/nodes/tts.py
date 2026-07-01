"""tts_node — the speech-synthesis stage (Story 1.7).

Synthesizes each ``SceneState.narration`` into a per-scene ``.wav`` via Qwen TTS
(Alibaba DashScope, international endpoint) and attaches provisional word timings.
Pure function of ``PipelineState``: reads ``scenes`` + ``run_id``, writes audio
files under ``workspace/{run_id}/audio/`` and returns only the changed fields
(``scenes``, ``current_stage``, and ``error`` on failure). No DB / SSE / gate
writes and no ``interrupt()``. [AD-1, AD-2, AD-4]

Qwen TTS returns an audio URL, not word-level timestamps (per the DashScope
docs), so timings here are *provisional*: derived from the measured audio
duration and whitespace tokenization. Story 1.8 owns forced alignment and must
not treat these as alignment-quality.
"""

import contextlib
import time
import wave
from pathlib import Path

import httpx
from langfuse import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState, WordTiming

# DashScope multimodal-generation path; base host comes from config. [Qwen TTS API]
_GENERATION_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
_MOCK_SECONDS_PER_WORD = 0.1  # deterministic mock audio length; keeps timings meaningful


def _settings() -> Settings:
    # ponytail: one seam so unit tests can inject fake settings without a real .env.
    return Settings()


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _wav_duration(path: Path) -> float:
    """Measure duration from the written file, not guessed from text. [Story 1.7]"""
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError) as exc:
        # Real Qwen output is documented as WAV but unverified against a live key;
        # a format drift (e.g. MP3) gives a clear error, not a cryptic wave.Error. [review]
        raise ValueError(f"audio at {path} is not a readable WAV (unexpected format?): {exc}") from exc


def _write_mock_wav(path: Path, narration: str) -> None:
    """Write a deterministic silent WAV whose length scales with word count.

    Mock mode still produces a real, readable file so downstream file-existence
    and duration checks are meaningful without a network. Mirrors Story 1.6's
    image mock, which copies real files into the workspace.
    """
    words = max(len(narration.split()), 1)
    framerate = 8000
    nframes = max(int(framerate * _MOCK_SECONDS_PER_WORD * words), 1)
    with contextlib.closing(wave.open(str(path), "wb")) as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(b"\x00\x00" * nframes)


async def _synthesize(text: str, s: Settings, path: Path) -> None:
    """Call Qwen TTS and download the resulting audio to ``path``.

    The response carries a pre-signed audio URL (``output.audio.url``) that
    expires ~24h after generation, so we fetch it immediately. [Qwen TTS API]

    ponytail: the response contract is documented but not verified against a
    live key here; guard the shape and fail with a readable error if it drifts.
    """
    if not s.qwen_tts_api_key:
        raise RuntimeError("YTFLOW_QWEN_TTS_API_KEY is not configured")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        resp = await client.post(
            f"{s.qwen_tts_endpoint.rstrip('/')}{_GENERATION_PATH}",
            headers={"Authorization": f"Bearer {s.qwen_tts_api_key}"},
            json={"model": s.qwen_tts_model,
                  "input": {"text": text, "voice": s.qwen_tts_voice}},
        )
        resp.raise_for_status()
        audio = resp.json().get("output", {}).get("audio", {})
        url = audio.get("url")
        if not url:
            raise RuntimeError(f"Qwen TTS response missing output.audio.url: {audio!r}")
        downloaded = await client.get(url)
        downloaded.raise_for_status()
        path.write_bytes(downloaded.content)


def _provisional_timings(narration: str, duration: float) -> list[WordTiming]:
    """Distribute ``duration`` evenly across whitespace tokens.

    Guarantees ``start_sec >= 0``, ``end_sec > start_sec``, monotonic order, and
    final ``end_sec == duration``. If the narration has no whitespace, fall back
    to a single segment for the whole string rather than an empty list. [Story 1.7]
    """
    words = narration.split()
    if not words:
        return [WordTiming(word=narration, start_sec=0.0, end_sec=duration)] if narration else []
    step = duration / len(words)
    timings = [
        WordTiming(word=w, start_sec=round(i * step, 3), end_sec=round((i + 1) * step, 3))
        for i, w in enumerate(words)
    ]
    timings[-1]["end_sec"] = round(duration, 3)  # pin final edge exactly to measured duration
    return timings


def _record_trace(*, run_id, model, voice, scene_count, latency_ms, per_scene=None, error=None) -> None:
    """Best-effort enrich the current ``tts`` span. [AD-10 — tracing is non-fatal]

    Never logs the API key or raw audio bytes — only metrics and identifiers.
    Qwen TTS responses carry no token/usage field, so latency (total + per-scene)
    is the recorded usage metric — this is the "documented usage metrics" AC3 allows.
    """
    try:
        get_client().update_current_span(
            metadata={
                "run_id": run_id,
                "model": model,
                "voice": voice,
                "scene_count": scene_count,
                "latency_ms": latency_ms,
                **({"per_scene_ms": per_scene} if per_scene is not None else {}),
                **({"error": repr(error)} if error is not None else {}),
            },
        )
    except Exception:  # noqa: BLE001 — a tracing failure must never break the pipeline
        pass


@observe(name="tts")
async def tts_node(state: PipelineState) -> dict:
    run_id = state.get("run_id", "?")
    t0 = time.perf_counter()
    s: Settings | None = None
    try:
        s = _settings()  # inside try: a config/env failure surfaces as PipelineState.error too
        audio_dir = Path(s.workspace_path) / run_id / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        new_scenes: list[SceneState] = []
        per_scene_ms: list[int] = []
        for scene in sorted(state["scenes"], key=lambda sc: sc["scene_num"]):
            t_scene = time.perf_counter()
            path = audio_dir / f"scene_{scene['scene_num']:03d}.wav"
            if s.qwen_tts_mock:
                _write_mock_wav(path, scene["narration"])
            else:
                # A mid-scene failure fails the whole stage — no partial checkpoint. [NFR-8]
                await _synthesize(scene["narration"], s, path)
            duration = _wav_duration(path)
            new_scenes.append({
                **scene,
                "audio_path": str(path),
                "audio_duration": duration,
                "word_timings": _provisional_timings(scene["narration"], duration),
            })
            per_scene_ms.append(_ms(t_scene))

        _record_trace(run_id=run_id, model=s.qwen_tts_model, voice=s.qwen_tts_voice,
                      scene_count=len(new_scenes), latency_ms=_ms(t0), per_scene=per_scene_ms)
        return {"scenes": new_scenes, "current_stage": "tts"}
    except Exception as exc:  # noqa: BLE001 — surfaced as PipelineState.error, never raised past the node
        _record_trace(run_id=run_id, model=s.qwen_tts_model if s else "?",
                      voice=s.qwen_tts_voice if s else "?",
                      scene_count=len(state.get("scenes", [])), latency_ms=_ms(t0), error=exc)
        return {"current_stage": "tts", "error": f"stage=tts run_id={run_id}: {exc}"}
