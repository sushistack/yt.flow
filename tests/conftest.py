"""Root test configuration (B-2).

- Ensures dummy Langfuse env so ``Settings()`` constructs everywhere (mirrors
  ``tests/api/conftest.py`` for the non-API test tree).
- Provides the reusable ``stub_profile`` fixture that monkeypatches all four
  external seams to the deterministic fakes in ``tests/stubs/fakes.py``.
"""
import os

os.environ.setdefault("YTFLOW_LANGFUSE_HOST", "http://localhost:3000")
os.environ.setdefault("YTFLOW_LANGFUSE_PUBLIC_KEY", "test-pub")
os.environ.setdefault("YTFLOW_LANGFUSE_SECRET_KEY", "test-secret")
# Default tracing OFF in the suite: keeps the stub-profile smoke test genuinely
# offline (no real langfuse span export to a dead host) and silences shutdown
# connection-error noise. Override with YTFLOW_LANGFUSE_ENABLED=true to exercise
# the real @observe path. setdefault so an explicit ambient value still wins.
os.environ.setdefault("YTFLOW_LANGFUSE_ENABLED", "false")

import pytest

from tests.stubs import fakes


@pytest.fixture
def stub_profile(monkeypatch):
    """Wire the four external seams to offline fakes (zero network/subprocess).

    Patches: DeepSeek (`scenario._call_deepseek`), Qwen TTS (`tts._synthesize`),
    ComfyUI (`comfyui_client.submit_and_fetch*`), and ffmpeg (`video._run_ffmpeg`).
    Yields the fakes module so a test can inspect the tiny artifacts it emits.
    """
    import yt_flow.pipeline.nodes.scenario as scenario
    import yt_flow.pipeline.nodes.tts as tts
    import yt_flow.pipeline.nodes.video as video
    import yt_flow.services.comfyui_client as comfyui_client

    monkeypatch.setattr(scenario, "_call_deepseek", fakes.deepseek_from_cassette())
    monkeypatch.setattr(tts, "_synthesize", fakes.fake_synthesize)
    monkeypatch.setattr(comfyui_client, "submit_and_fetch", fakes.fake_submit_and_fetch)
    monkeypatch.setattr(comfyui_client, "submit_and_fetch_outputs", fakes.fake_submit_and_fetch_outputs)
    monkeypatch.setattr(video, "_run_ffmpeg", fakes.fake_run_ffmpeg)
    return fakes
