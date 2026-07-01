"""Unit tests for src/yt_flow/pipeline/nodes/subtitle.py (Story 1.8).

No live WhisperX / Langfuse: settings and the aligner are monkeypatched.
Tests cover SRT formatting, word-timing grouping, strategy resolver,
subtitle_node happy path (word_timings reuse + aligner fallback),
error handling, and purity. No GPU, no network, no model downloads required.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import yt_flow.pipeline.nodes.subtitle as subtitle
from yt_flow.pipeline.nodes.subtitle import (
    AlignmentSegment,
    _get_aligner,
    _word_timings_to_segments,
    format_srt,
    subtitle_node,
)


# ── Fakes / helpers ───────────────────────────────────────────────────────────


def _settings_ns(tmp_path, aligner="whisperx"):
    return SimpleNamespace(
        aligner=aligner,
        aligner_model="base",
        aligner_device="cpu",
        aligner_compute_type="int8",
        workspace_path=str(tmp_path),
    )


class _FakeAligner:
    def __init__(self, segments: list[AlignmentSegment] | None = None):
        self._segs = segments if segments is not None else [{"start_sec": 0.0, "end_sec": 1.5, "text": "hello world"}]
        self.calls: list[tuple[str, str]] = []

    async def align(self, audio_path: str, transcript: str) -> list[AlignmentSegment]:
        self.calls.append((audio_path, transcript))
        return self._segs


def _timings(words: list[str], duration: float = 2.0) -> list[dict]:
    step = duration / len(words) if words else duration
    return [{"word": w, "start_sec": round(i * step, 3), "end_sec": round((i + 1) * step, 3)}
            for i, w in enumerate(words)]


def _scene(scene_num: int, narration: str, *, audio_path: str | None = None,
           word_timings=None, audio_duration: float | None = 2.0, **over) -> dict:
    base = {
        "scene_num": scene_num,
        "narration": narration,
        "shots": [],
        "audio_path": audio_path,
        "audio_duration": audio_duration if audio_path else None,
        "word_timings": word_timings if word_timings is not None else [],
        "subtitle_path": None,
    }
    base.update(over)
    return base


def _state(scenes: list, run_id: str = "run-001", **over) -> dict:
    base = {
        "run_id": run_id,
        "scp_text": "SCP-173 is a concrete statue.",
        "scenes": scenes,
        "video_path": None,
        "current_stage": "tts",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }
    base.update(over)
    return base


@pytest.fixture
def audio_file(tmp_path) -> str:
    """Dummy audio file; subtitle_node only checks existence, not format."""
    p = tmp_path / "audio.wav"
    p.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    return str(p)


@pytest.fixture(autouse=True)
def _silent_trace(monkeypatch):
    monkeypatch.setattr(subtitle, "_record_trace", lambda **kw: None)


# ── format_srt ───────────────────────────────────────────────────────────────


def test_format_srt_single_cue():
    segs = [{"start_sec": 1.25, "end_sec": 3.5, "text": "격리 절차 시작"}]
    out = format_srt(segs)
    assert out.startswith("1\n")
    assert "00:00:01,250 --> 00:00:03,500" in out
    assert "격리 절차 시작" in out


def test_format_srt_multiple_cues():
    segs = [
        {"start_sec": 0.0, "end_sec": 1.0, "text": "첫 번째"},
        {"start_sec": 1.2, "end_sec": 2.5, "text": "두 번째"},
    ]
    out = format_srt(segs)
    assert "1\n" in out
    assert "2\n" in out
    assert "00:00:00,000 --> 00:00:01,000" in out
    assert "00:00:01,200 --> 00:00:02,500" in out


def test_format_srt_empty_returns_empty():
    assert format_srt([]) == ""


def test_format_srt_korean_utf8():
    segs = [{"start_sec": 0.0, "end_sec": 2.0, "text": "SCP재단 격리 절차"}]
    out = format_srt(segs)
    assert "SCP재단 격리 절차" in out


def test_format_srt_hour_boundary():
    segs = [{"start_sec": 3661.5, "end_sec": 3663.0, "text": "test"}]
    out = format_srt(segs)
    assert "01:01:01,500 --> 01:01:03,000" in out


def test_format_srt_cue_separation():
    segs = [
        {"start_sec": 0.0, "end_sec": 1.0, "text": "A"},
        {"start_sec": 1.5, "end_sec": 2.5, "text": "B"},
    ]
    out = format_srt(segs)
    # Blank line separates cues
    assert "\n\n" in out


# ── _word_timings_to_segments ─────────────────────────────────────────────────


def test_word_timings_to_segments_empty():
    assert _word_timings_to_segments([]) == []


def test_word_timings_to_segments_single_short():
    t = _timings(["격리절차시작"])
    segs = _word_timings_to_segments(t, max_chars=40)
    assert len(segs) == 1
    assert segs[0]["text"] == "격리절차시작"
    assert segs[0]["start_sec"] == 0.0


def test_word_timings_to_segments_splits_long_lines():
    # 5 long words should split into ≥2 cues when max_chars=20
    words = ["longword1", "longword2", "longword3", "longword4", "longword5"]
    t = _timings(words, duration=5.0)
    segs = _word_timings_to_segments(t, max_chars=20)
    assert len(segs) >= 2
    for seg in segs:
        assert len(seg["text"]) <= 30  # allows one word slightly over limit


def test_word_timings_to_segments_monotonic():
    words = ["a", "b", "c", "d", "e"]
    t = _timings(words, duration=5.0)
    segs = _word_timings_to_segments(t)
    prev_end = 0.0
    for s in segs:
        assert s["start_sec"] >= prev_end - 1e-6
        assert s["end_sec"] > s["start_sec"]
        prev_end = s["end_sec"]


# ── _get_aligner ─────────────────────────────────────────────────────────────


def test_get_aligner_whisperx_returns_instance():
    s = SimpleNamespace(aligner="whisperx", aligner_model="base",
                        aligner_device="cpu", aligner_compute_type="int8")
    from yt_flow.pipeline.nodes.subtitle import WhisperXAligner
    aligner = _get_aligner(s)
    assert isinstance(aligner, WhisperXAligner)


def test_get_aligner_unknown_raises_value_error():
    s = SimpleNamespace(aligner="fake_unknown", aligner_model="x",
                        aligner_device="cpu", aligner_compute_type="int8")
    with pytest.raises(ValueError, match="Unsupported YTFLOW_ALIGNER"):
        _get_aligner(s)


# ── subtitle_node: happy path ─────────────────────────────────────────────────


async def test_subtitle_node_uses_word_timings_not_aligner(monkeypatch, tmp_path, audio_file):
    fake = _FakeAligner()
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: fake)

    wt = _timings(["격리", "절차", "시작"])
    scenes = [_scene(1, "격리 절차 시작", audio_path=audio_file, word_timings=wt)]
    out = await subtitle_node(_state(scenes))

    assert out["current_stage"] == "subtitle"
    assert out.get("error") is None
    # word_timings present → aligner.align should NOT be called
    assert len(fake.calls) == 0
    assert out["scenes"][0]["subtitle_path"]


async def test_subtitle_node_calls_aligner_when_no_timings(monkeypatch, tmp_path, audio_file):
    fake = _FakeAligner()
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: fake)

    scenes = [_scene(1, "격리 절차", audio_path=audio_file, word_timings=[])]
    out = await subtitle_node(_state(scenes))

    assert out["current_stage"] == "subtitle"
    assert out.get("error") is None
    assert len(fake.calls) == 1
    assert fake.calls[0] == (audio_file, "격리 절차")


async def test_subtitle_node_creates_srt_files(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [_scene(1, "test narration", audio_path=audio_file)]
    out = await subtitle_node(_state(scenes, run_id="run-abc"))

    srt_path = Path(out["scenes"][0]["subtitle_path"])
    assert srt_path.exists()
    assert srt_path.suffix == ".srt"
    assert "subtitles" in str(srt_path)
    assert "run-abc" in str(srt_path)
    text = srt_path.read_text(encoding="utf-8")
    assert "00:" in text  # has timestamps


async def test_subtitle_node_updates_subtitle_path(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [
        _scene(1, "narration one", audio_path=audio_file),
        _scene(2, "narration two", audio_path=audio_file),
    ]
    out = await subtitle_node(_state(scenes))

    assert out.get("error") is None
    for sc in out["scenes"]:
        assert sc["subtitle_path"] and Path(sc["subtitle_path"]).exists()


async def test_subtitle_node_scenes_in_order(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    # Intentionally out of order
    scenes = [_scene(2, "two", audio_path=audio_file), _scene(1, "one", audio_path=audio_file)]
    out = await subtitle_node(_state(scenes))

    nums = [s["scene_num"] for s in out["scenes"]]
    assert nums == [1, 2]
    assert out["scenes"][0]["subtitle_path"].endswith("scene_001.srt")
    assert out["scenes"][1]["subtitle_path"].endswith("scene_002.srt")


async def test_subtitle_node_input_not_mutated(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    state = _state([_scene(1, "hello", audio_path=audio_file)])
    snapshot = json.loads(json.dumps(state))
    await subtitle_node(state)
    assert state == snapshot  # AD-4 purity


async def test_subtitle_node_preserves_upstream_fields(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    shot = {"shot_id": "S001", "sentence_indices": [0], "image_prompt": "p",
            "negative_prompt": "n", "camera_angle": None, "camera_movement": None, "image_path": None}
    scenes = [_scene(1, "hello", audio_path=audio_file, word_timings=[])]
    scenes[0]["shots"] = [shot]
    out = await subtitle_node(_state(scenes))

    assert out["scenes"][0]["shots"] == [shot]
    assert out["scenes"][0]["narration"] == "hello"


# ── subtitle_node: error paths ────────────────────────────────────────────────


async def test_subtitle_node_missing_audio_path(monkeypatch, tmp_path):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [_scene(1, "test", audio_path=None)]
    out = await subtitle_node(_state(scenes))

    assert out["current_stage"] == "subtitle"
    assert out["error"]
    assert "stage=subtitle" in out["error"]
    assert "run-001" in out["error"]
    assert "scenes" not in out or not out.get("scenes")


async def test_subtitle_node_audio_file_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [_scene(1, "test", audio_path="/nonexistent/audio.wav")]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]


async def test_subtitle_node_empty_narration(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())

    scenes = [_scene(1, "", audio_path=audio_file)]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert "narration" in out["error"]


async def test_subtitle_node_bad_aligner_config(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path, aligner="bad_aligner"))

    scenes = [_scene(1, "test", audio_path=audio_file)]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert "Unsupported" in out["error"] or "bad_aligner" in out["error"]


async def test_subtitle_node_aligner_returns_no_segments(monkeypatch, tmp_path, audio_file):
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner(segments=[]))

    scenes = [_scene(1, "test narration", audio_path=audio_file, word_timings=[])]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert "no segments" in out["error"]


async def test_subtitle_node_aligner_exception(monkeypatch, tmp_path, audio_file):
    class _BoomAligner:
        async def align(self, audio_path, transcript):
            raise RuntimeError("aligner crashed")

    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _BoomAligner())

    scenes = [_scene(1, "test", audio_path=audio_file, word_timings=[])]
    out = await subtitle_node(_state(scenes))

    assert out["error"] and "stage=subtitle" in out["error"]
    assert "aligner crashed" in out["error"]


# ── observability ─────────────────────────────────────────────────────────────


async def test_trace_receives_metrics(monkeypatch, tmp_path, audio_file):
    captured = {}
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())
    monkeypatch.setattr(subtitle, "_record_trace", lambda **kw: captured.update(kw))

    await subtitle_node(_state([_scene(1, "hello", audio_path=audio_file)]))

    assert captured["run_id"] == "run-001"
    assert captured["scene_count"] == 1
    assert isinstance(captured["latency_ms"], int)
    assert captured.get("error") is None


async def test_trace_captures_error_on_failure(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(subtitle, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(subtitle, "_get_aligner", lambda s: _FakeAligner())
    monkeypatch.setattr(subtitle, "_record_trace", lambda **kw: captured.update(kw))

    scenes = [_scene(1, "test", audio_path=None)]
    await subtitle_node(_state(scenes))
    assert captured.get("error") is not None


def test_record_trace_is_non_fatal(monkeypatch):
    monkeypatch.setattr(
        subtitle, "get_client",
        lambda: (_ for _ in ()).throw(RuntimeError("langfuse down"))
    )
    subtitle._record_trace(run_id="r", scene_count=1, latency_ms=10)


# ── layering guard ────────────────────────────────────────────────────────────


def test_no_db_api_service_imports():
    """AD-1: subtitle.py must not import db, api, or services layers."""
    import yt_flow.pipeline.nodes.subtitle as mod
    import sys
    for name in ("yt_flow.db", "yt_flow.api", "yt_flow.services"):
        assert name not in sys.modules or mod.__name__ != name, (
            f"subtitle module must not depend on {name}"
        )
    # Check source imports directly
    import importlib
    source = Path(mod.__file__).read_text()
    for forbidden in ("from yt_flow.db", "from yt_flow.api", "from yt_flow.services",
                      "import yt_flow.db", "import yt_flow.api", "import yt_flow.services"):
        assert forbidden not in source, f"subtitle.py must not import {forbidden}"
