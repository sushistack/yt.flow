"""Unit tests for src/yt_flow/pipeline/nodes/tts.py (Story 1.7).

No live Qwen / Langfuse: settings, the synthesis call, and the trace sink are
monkeypatched. Mock mode writes real local WAV files (via stdlib ``wave``) so
file-existence and duration checks are meaningful without a network. Tests
assert the PipelineState contract (audio_path/audio_duration/word_timings,
field preservation, purity), error handling, and the observability boundary.
"""

import json
import os
import wave
from types import SimpleNamespace

import pytest

# Import the submodule explicitly: nodes/__init__.py binds a stub `tts` attribute
# (Story 1.4) that `from ... import tts` would return instead of this module. The
# real graph wiring stays on the stub for now, same as scenario (Story 1.5). [Story 1.7]
import yt_flow.pipeline.nodes.tts as tts


# ── Fakes / helpers ─────────────────────────────────────────────────────────

def _settings(tmp_path, *, mock=True, api_key="sk-test"):
    return SimpleNamespace(
        qwen_tts_api_key=api_key,
        qwen_tts_endpoint="https://dashscope-intl.aliyuncs.com",
        qwen_tts_model="qwen3-tts-flash",
        qwen_tts_voice="Cherry",
        qwen_tts_mock=mock,
        workspace_path=str(tmp_path),
    )


def _scene(scene_num, narration, **over):
    base = {
        "scene_num": scene_num,
        "narration": narration,
        "shots": [{"shot_id": f"S{scene_num:03d}", "sentence_indices": [0],
                   "image_prompt": "p", "negative_prompt": "n",
                   "camera_angle": None, "camera_movement": None, "image_path": None}],
        "audio_path": None,
        "audio_duration": None,
        "word_timings": [],
        "subtitle_path": None,
    }
    base.update(over)
    return base


def _state(scenes, run_id="run-123", **over):
    base = {
        "run_id": run_id,
        "scp_text": "SCP-173 is a concrete statue.",
        "scenes": scenes,
        "video_path": None,
        "current_stage": "image",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _silent_trace(monkeypatch):
    monkeypatch.setattr(tts, "_record_trace", lambda **kw: None)


# ── AC1: mock mode populates audio_path, audio_duration, word_timings ────────

async def test_mock_populates_audio_and_timings(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path))
    scenes = [_scene(1, "격리 절차 시작"), _scene(2, "요원들이 진입한다 지금")]
    out = await tts.tts_node(_state(scenes))

    assert out["current_stage"] == "tts"
    assert out.get("error") is None
    for scene in out["scenes"]:
        from pathlib import Path
        assert scene["audio_path"] and Path(scene["audio_path"]).exists()
        assert scene["audio_duration"] and scene["audio_duration"] > 0
        assert scene["word_timings"], "word_timings must be non-empty"
        for wt in scene["word_timings"]:
            assert set(wt) == {"word", "start_sec", "end_sec"}


async def test_upstream_scene_fields_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path))
    scenes = [_scene(1, "hello world foo")]
    out = await tts.tts_node(_state(scenes))
    scene = out["scenes"][0]
    # audio fields added...
    assert scene["audio_path"] and scene["audio_duration"] and scene["word_timings"]
    # ...upstream fields carried through untouched.
    assert scene["shots"] == scenes[0]["shots"]
    assert scene["narration"] == "hello world foo"
    assert scene["subtitle_path"] is None


async def test_scenes_written_in_scene_num_order(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path))
    # deliberately out of order
    scenes = [_scene(2, "second scene here"), _scene(1, "first scene here")]
    out = await tts.tts_node(_state(scenes))
    nums = [s["scene_num"] for s in out["scenes"]]
    assert nums == [1, 2]
    assert out["scenes"][0]["audio_path"].endswith("scene_001.wav")
    assert out["scenes"][1]["audio_path"].endswith("scene_002.wav")


async def test_input_state_not_mutated(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path))
    state = _state([_scene(1, "hello world")])
    snapshot = json.loads(json.dumps(state))
    await tts.tts_node(state)
    assert state == snapshot  # AD-4 purity: node returns new scenes, never mutates input


# ── AC1: honest provisional word timings ────────────────────────────────────

async def test_word_timings_monotonic_and_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path))
    out = await tts.tts_node(_state([_scene(1, "one two three four five")]))
    scene = out["scenes"][0]
    timings, duration = scene["word_timings"], scene["audio_duration"]
    assert len(timings) == 5
    prev_end = 0.0
    for wt in timings:
        assert wt["start_sec"] >= 0
        assert wt["end_sec"] > wt["start_sec"]
        assert wt["start_sec"] >= prev_end - 1e-6  # monotonic, no overlap
        prev_end = wt["end_sec"]
    assert timings[-1]["end_sec"] <= duration + 1e-3  # final within audio bounds


async def test_no_whitespace_narration_single_segment(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path))
    out = await tts.tts_node(_state([_scene(1, "격리절차시작")]))  # no spaces
    timings = out["scenes"][0]["word_timings"]
    assert len(timings) == 1
    assert timings[0]["word"] == "격리절차시작"
    assert timings[0]["start_sec"] == 0.0
    assert timings[0]["end_sec"] == out["scenes"][0]["audio_duration"]


# ── AC2: provider / config errors surface as stage=tts error, no partial output

async def test_missing_api_key_sets_error(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path, mock=False, api_key=""))
    out = await tts.tts_node(_state([_scene(1, "hello world")]))
    assert "scenes" not in out or not out.get("scenes")
    assert out["error"] and "stage=tts" in out["error"] and "run-123" in out["error"]
    assert out["current_stage"] == "tts"


async def test_provider_failure_sets_error_no_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path, mock=False))

    async def boom(text, s, path):
        raise RuntimeError("Qwen 500 Internal Error")
    monkeypatch.setattr(tts, "_synthesize", boom)

    out = await tts.tts_node(_state([_scene(1, "a b"), _scene(2, "c d")]))
    # mid-stage failure fails the whole stage; no partial scenes update. [NFR-8]
    assert "scenes" not in out or not out.get("scenes")
    assert out["error"] and "stage=tts" in out["error"] and "run-123" in out["error"]


# ── AC3 / AD-10: observability boundary ─────────────────────────────────────

async def test_trace_receives_metrics(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(tts, "_record_trace", lambda **kw: captured.update(kw))
    await tts.tts_node(_state([_scene(1, "one two"), _scene(2, "three four")]))
    assert captured["model"] == "qwen3-tts-flash"
    assert captured["voice"] == "Cherry"
    assert captured["run_id"] == "run-123"
    assert captured["scene_count"] == 2
    assert isinstance(captured["latency_ms"], int)
    assert captured.get("error") is None


async def test_trace_captures_error(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path, mock=False, api_key=""))
    monkeypatch.setattr(tts, "_record_trace", lambda **kw: captured.update(kw))
    await tts.tts_node(_state([_scene(1, "hello")]))
    assert captured.get("error") is not None


def test_record_trace_is_non_fatal(monkeypatch):
    # AD-10: a Langfuse transport failure must never break the node.
    monkeypatch.setattr(tts, "get_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("langfuse down")))
    tts._record_trace(run_id="r", model="m", voice="v", scene_count=1, latency_ms=1)


# ── Mock WAV is a real, readable file with a positive duration ──────────────

def test_wav_duration_rejects_non_wav(tmp_path):
    # A format drift on the unverified real path (e.g. MP3 bytes) must raise a
    # clear ValueError, not a cryptic wave.Error. [review]
    from pathlib import Path
    bad = tmp_path / "not.wav"
    bad.write_bytes(b"ID3\x03\x00 not a wav at all")
    with pytest.raises(ValueError, match="not a readable WAV"):
        tts._wav_duration(Path(bad))


async def test_mock_writes_real_readable_wav(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "_settings", lambda: _settings(tmp_path))
    out = await tts.tts_node(_state([_scene(1, "alpha beta")]))
    path = out["scenes"][0]["audio_path"]
    with wave.open(path, "rb") as w:  # raises if not a valid WAV
        assert w.getnframes() > 0


# ── Real-provider smoke test (skipped by default) ───────────────────────────
# Manual run:  YTFLOW_QWEN_TTS_SMOKE=1 uv run pytest tests/pipeline/nodes/test_tts.py -k smoke
# Requires a real YTFLOW_QWEN_TTS_API_KEY in the environment / .env.

@pytest.mark.skipif(os.getenv("YTFLOW_QWEN_TTS_SMOKE") != "1",
                    reason="real Qwen TTS smoke test; set YTFLOW_QWEN_TTS_SMOKE=1 to run")
async def test_smoke_real_qwen(tmp_path):
    from yt_flow.config import Settings
    s = Settings()  # real key + endpoint from env/.env
    if not s.qwen_tts_api_key:
        pytest.skip("YTFLOW_QWEN_TTS_API_KEY not set")
    path = tmp_path / "smoke.wav"
    await tts._synthesize("This is a Qwen TTS smoke test.", s, path)
    assert path.exists() and tts._wav_duration(path) > 0
