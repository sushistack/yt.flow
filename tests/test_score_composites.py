"""Tests for scripts/score_composites.py (Story 8.16 composite QA).

Fully offline: the DashScope vision call is faked at the httpx seam. The scorer's
exit code gates a live-verification task, so the decision rule is asserted directly
— a chatty reply or a missing field must never read as a pass.
"""

import asyncio
import importlib.util
import subprocess
import types

import pytest

import httpx

PASS = {
    "grounded": 5, "scale_plausible": 4, "lighting_consistent": 4,
    "feet_visible": True, "confidence": 0.9, "notes": "stands on the floor",
}


def _load_script():
    spec = importlib.util.spec_from_file_location("score_composites", "scripts/score_composites.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


def _fake_httpx(module, monkeypatch, *, reply=None, error=None):
    payloads: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            if error:
                raise httpx.HTTPStatusError(error, request=None, response=None)  # type: ignore[arg-type]

        def json(self):
            return {"choices": [{"message": {"content": reply}}]}

    class FakeClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            payloads.append(json)
            return FakeResponse()

    monkeypatch.setattr(module, "httpx", types.SimpleNamespace(
        AsyncClient=FakeClient, Timeout=httpx.Timeout, HTTPStatusError=httpx.HTTPStatusError,
    ))
    return payloads


# ── decision rule ────────────────────────────────────────────────────────────


def test_clear_pass_has_no_fail_reason(script):
    assert script.fail_reason(PASS) is None


@pytest.mark.parametrize("field", ["grounded", "scale_plausible", "lighting_consistent"])
def test_any_field_below_the_threshold_fails(script, field):
    assert script.fail_reason({**PASS, field: 2}) == f"{field}=2"


@pytest.mark.parametrize("bad", [None, "5", True, {}])
def test_a_non_numeric_score_fails_rather_than_passing(script, bad):
    """A missing or wrong-typed field is a fail, never a pass — `True` included,
    since bool is an int subclass and would otherwise read as 1."""
    assert script.fail_reason({**PASS, "grounded": bad}) is not None


def test_low_confidence_fails(script):
    assert script.fail_reason({**PASS, "confidence": 0.2}) == "confidence=0.2"
    assert script.fail_reason({**PASS, "confidence": True}) is not None


# ── reply parsing ────────────────────────────────────────────────────────────


def test_fenced_json_is_parsed(script):
    verdict = script._parse('Sure!\n```json\n{"grounded": 5}\n```\n')
    assert verdict == {"grounded": 5}


@pytest.mark.parametrize("reply", ["no json here", "{not json}", "[1,2]"])
def test_unparsable_replies_raise(script, reply):
    with pytest.raises(Exception):
        script._parse(reply)


# ── the vision call ──────────────────────────────────────────────────────────


def test_score_frame_sends_the_frame_and_the_configured_token_cap(script, monkeypatch, tmp_path):
    from yt_flow.config import Settings

    frame = tmp_path / "f.png"
    frame.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    payloads = _fake_httpx(script, monkeypatch, reply='{"grounded": 5}')
    monkeypatch.setenv("YTFLOW_CHARACTER_VISION_API_KEY", "k")
    settings = Settings()  # type: ignore[call-arg]

    verdict = asyncio.run(script.score_frame(settings, frame))
    assert verdict == {"grounded": 5}
    sent = payloads[0]
    # The 2026-07-12 regression: qwen-vl-plus caps at 8192 but the code reused
    # deepseek_max_tokens (env 16384) and every call 400'd for a month.
    assert sent["max_tokens"] == settings.character_vision_max_tokens
    assert sent["max_tokens"] <= 8192
    assert "data:image/png;base64," in sent["messages"][0]["content"][1]["image_url"]["url"]


def test_frames_are_sampled_across_the_whole_clip(script, monkeypatch, tmp_path):
    """A static-anchor regression only shows in the second half of a moving shot,
    so sampling the head of the clip would score it as a pass."""
    calls: list[float] = []

    def fake_run(cmd, **kw):
        if cmd[0] == "ffprobe":
            return types.SimpleNamespace(stdout="8.0\n", returncode=0)
        calls.append(float(cmd[cmd.index("-ss") + 1]))
        out = cmd[-1]
        with open(out, "wb") as fh:
            fh.write(b"png")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(script.subprocess, "run", fake_run)
    frames = script.extract_frames(tmp_path / "clip.mp4", 3, tmp_path)

    assert len(frames) == 3
    assert calls == pytest.approx([8.0 * 0.5 / 3, 8.0 * 1.5 / 3, 8.0 * 2.5 / 3], abs=0.001)
    assert max(calls) > 8.0 / 2  # reaches the second half


def test_a_failed_vision_call_counts_as_a_failure_not_a_crash(script, monkeypatch, tmp_path):
    frame = tmp_path / "f.png"
    frame.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    _fake_httpx(script, monkeypatch, reply="", error="boom")
    monkeypatch.setenv("YTFLOW_CHARACTER_VISION_API_KEY", "k")

    args = types.SimpleNamespace(targets=[str(frame)], frames=3, json=None)
    assert asyncio.run(script.run(args)) == 1
