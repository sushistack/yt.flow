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
# Sound design (Story 7.1) defaults ON in Settings, but the data/audio CC0 asset
# library is a human sourcing/licensing step not yet done (see story Saved
# Questions #2) — off by default in the suite so real-Settings() smoke/e2e tests
# stay offline instead of hitting validate_mood_assets' fail-fast FileNotFoundError.
os.environ.setdefault("YTFLOW_SOUND_DESIGN_ENABLED", "false")

import pytest

from tests.stubs import fakes


@pytest.fixture
def stub_profile(monkeypatch, tmp_path):
    """Wire the external seams to offline fakes (zero network/subprocess).

    Patches: Langfuse Prompt Hub (`scenario.get_prompt`), DeepSeek (`scenario._call_deepseek`),
    Qwen TTS (`tts._synthesize`), ComfyUI (`comfyui_client.submit_and_fetch*`), ffmpeg
    (`video._run_ffmpeg`), and the character-reference search/generation seams (Story 5.8's
    `run_service._ensure_character_reference`, which now fires from every `start_run` for a
    never-before-seen `scp_id`): DuckDuckGo search, reference download, and multi-angle
    generation. Yields the fakes module so a test can inspect the tiny artifacts it emits.

    ponytail: get_prompt was missing from the original four-seam B-2 design — scenario_node
    calls it before ever reaching the (already-stubbed) DeepSeek call, so any test driving the
    real scenario_node without a reachable Langfuse Prompt Hub failed silently into
    PipelineState.error (AD-10 swallows it) with zero scenes, never a loud test failure.
    """
    import yt_flow.pipeline.nodes.scenario as scenario
    import yt_flow.pipeline.nodes.tts as tts
    import yt_flow.pipeline.nodes.video as video
    import yt_flow.services.comfyui_client as comfyui_client
    import yt_flow.services.prompt_service as prompt_service
    from yt_flow.config import Settings
    from yt_flow.services import run_service

    # scenario.py's own one format_guide fetch uses the bare imported name...
    monkeypatch.setattr(scenario, "get_prompt", fakes.fake_get_prompt_for_chain)
    # ...but every scenario_chain.py step fetches via the module-qualified
    # attribute (`from yt_flow.services import prompt_service`), which needs
    # its own patch target.
    monkeypatch.setattr(prompt_service, "get_prompt", fakes.fake_get_prompt_for_chain)
    monkeypatch.setattr(scenario, "_call_deepseek", fakes.deepseek_stage_aware())
    monkeypatch.setattr(tts, "_synthesize", fakes.fake_synthesize)
    monkeypatch.setattr(comfyui_client, "submit_and_fetch", fakes.fake_submit_and_fetch)
    monkeypatch.setattr(comfyui_client, "submit_and_fetch_outputs", fakes.fake_submit_and_fetch_outputs)
    monkeypatch.setattr(comfyui_client, "check_health", fakes.fake_check_health)
    monkeypatch.setattr(video, "_run_ffmpeg", fakes.fake_run_ffmpeg)
    fakes.patch_character_reference_seams(monkeypatch)
    # Story 8.6: _ensure_character_reference/_ensure_special_pose_cards resolve paths
    # via run_service._settings() — without this override the (now-successful, thanks
    # to the fakes above) generation writes real files into the repo's ./workspace and
    # ./assets instead of tmp_path.
    monkeypatch.setattr(
        run_service, "_settings",
        lambda: Settings(workspace_path=str(tmp_path / "ws"), assets_path=str(tmp_path / "assets")),
    )
    return fakes

@pytest.fixture
def stub_stage_nodes(monkeypatch):
    """Replace all five stage nodes with instant no-op successes.

    For graph/service tests that exercise gate/topology mechanics only. The real
    nodes need live LLM/ComfyUI seams, and (since the error-routing fix) a failed
    stage routes to END instead of its gate — so tests that assert gate behaviour
    must run on nodes that genuinely succeed.
    """
    from yt_flow.pipeline import nodes

    def _make(stage):
        async def node(state):
            return {"current_stage": stage, "error": None}
        node.__name__ = f"stub_{stage}_node"
        return node

    for s in nodes.STAGES:
        monkeypatch.setitem(nodes.STAGE_NODES, s, _make(s))
