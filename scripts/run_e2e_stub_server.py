"""Boot the real FastAPI app with all 5 external seams stubbed, for Playwright E2E only.

pytest's ``stub_profile`` fixture (tests/conftest.py) monkeypatches DeepSeek/Qwen/
ComfyUI/ffmpeg/Langfuse-Prompt-Hub, but that only works in-process — Playwright
drives a real browser against a real server process, so in-process monkeypatch
doesn't reach it. This script applies the exact same monkeypatch (reusing
``tests/stubs/fakes.py``, zero duplication) as plain attribute assignment, then
boots uvicorn. The patch happens from outside, before the ASGI app ever runs —
no new stub flag or branch added to ``src/yt_flow/``.

NEVER use this for production. E2E/local testing only — zero real network or
subprocess calls (DeepSeek/Qwen/ComfyUI/ffmpeg all stubbed).

Usage:
    uv run python scripts/run_e2e_stub_server.py             # http://127.0.0.1:8000
    uv run python scripts/run_e2e_stub_server.py --port 8001

Point Playwright/the frontend at this instead of the real backend by swapping
``playwright.config.ts``'s ``webServer.command`` (or just running this manually
and setting ``BASE_URL``) — same host/port convention, so no other config changes.

Running this end-to-end (real HTTP, not pytest's decoupled test DBs) surfaced a
genuine pre-existing bug: db.py/graph.py/run_service.py open two separate SQLite
connections to the same file (AD-7) with synchronous writes inline in async code,
which reliably deadlocked into "database is locked" within 1-2 gate approvals.
Fixed alongside this script (WAL + busy_timeout, and asyncio.to_thread around the
blocking writes) since the stub server can't demonstrate anything without it —
see the two E2E runs in the review notes.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root, for `tests.stubs.fakes`

from tests.stubs import fakes  # noqa: E402


def apply_stub_profile() -> None:
    """Same 5 seams as tests/conftest.py::stub_profile, applied without pytest."""
    import yt_flow.pipeline.nodes.scenario as scenario
    import yt_flow.pipeline.nodes.tts as tts
    import yt_flow.pipeline.nodes.video as video
    import yt_flow.services.comfyui_client as comfyui_client

    scenario.get_prompt = fakes.fake_get_prompt
    scenario._call_deepseek = fakes.deepseek_from_cassette()
    tts._synthesize = fakes.fake_synthesize
    comfyui_client.submit_and_fetch = fakes.fake_submit_and_fetch
    comfyui_client.submit_and_fetch_outputs = fakes.fake_submit_and_fetch_outputs
    video._run_ffmpeg = fakes.fake_run_ffmpeg


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    apply_stub_profile()

    import uvicorn

    from yt_flow.api.main import app

    uvicorn.run(app, host=args.host, port=args.port)
