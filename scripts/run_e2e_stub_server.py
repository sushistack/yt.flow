"""Boot the real FastAPI app with all 5 external seams stubbed, for Playwright E2E only.

pytest's ``stub_profile`` fixture (tests/conftest.py) monkeypatches DeepSeek/Qwen/
ComfyUI/ffmpeg/Langfuse-Prompt-Hub, but that only works in-process — Playwright
drives a real browser against a real server process, so in-process monkeypatch
doesn't reach it. This script applies the exact same monkeypatch (reusing
``tests/stubs/fakes.py``, zero duplication) as plain attribute assignment, then
boots uvicorn. The patch happens from outside, before the ASGI app ever runs —
no new stub flag or branch added to ``src/yt_flow/``.

NEVER use this for production. E2E/local testing only — zero real network or
subprocess calls (DeepSeek/Qwen/ComfyUI/ffmpeg all stubbed; the A/B evaluation
judge has no stub seam, so its API key is force-cleared below instead).

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

``tests/stubs/fakes.py``'s ComfyUI fake does zero I/O, so a stage retry (B-1
concurrency guard) can complete faster than two sequential real HTTP round-trips
from Playwright — the ``run.status == "running"`` window is unobservable over
real HTTP even though it exists. Only this script adds a small artificial delay
to the image seam so that window is wide enough for a Playwright test to land a
probe request inside it; ``tests/stubs/fakes.py`` itself is untouched, so pytest
(in-process, no such race) stays fast.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root, for `tests.stubs.fakes`

from tests.stubs import fakes  # noqa: E402

# E2E-only: widens the run.status=="running" window past a real HTTP round-trip.
_CONCURRENCY_PROBE_DELAY_SEC = 0.5


async def _delayed_submit_and_fetch(*args, **kwargs):
    await asyncio.sleep(_CONCURRENCY_PROBE_DELAY_SEC)
    return await fakes.fake_submit_and_fetch(*args, **kwargs)


async def _delayed_submit_and_fetch_outputs(*args, **kwargs):
    await asyncio.sleep(_CONCURRENCY_PROBE_DELAY_SEC)
    return await fakes.fake_submit_and_fetch_outputs(*args, **kwargs)


def apply_stub_profile() -> None:
    """Same 5 seams as tests/conftest.py::stub_profile, applied without pytest.

    Plus 2 more seams for the character management flow (Story 1.11/3.7):
    DuckDuckGo image search and its download step both do real HTTP otherwise —
    unlike the 5 pipeline seams, pytest never covers this path with non-empty
    results (see deferred-work.md), so there's no existing fixture to mirror.
    """
    import yt_flow.pipeline.nodes.scenario as scenario
    import yt_flow.pipeline.nodes.tts as tts
    import yt_flow.pipeline.nodes.video as video
    import yt_flow.services.character_service as character_service
    import yt_flow.services.comfyui_client as comfyui_client
    import yt_flow.services.image_search as image_search

    scenario.get_prompt = fakes.fake_get_prompt
    scenario._call_deepseek = fakes.deepseek_from_cassette()
    tts._synthesize = fakes.fake_synthesize
    comfyui_client.submit_and_fetch = _delayed_submit_and_fetch
    comfyui_client.submit_and_fetch_outputs = _delayed_submit_and_fetch_outputs
    video._run_ffmpeg = fakes.fake_run_ffmpeg
    image_search.DuckDuckGoImageSearch.search = fakes.fake_image_search
    character_service.CharacterService._download_reference_image = fakes.fake_download_reference_image


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # eval_service.evaluate_ab() (Story 4.2/4.3) is not stubbed above — its DeepSeek
    # judge calls go through raw httpx, not a seam fakes.py can monkeypatch cleanly.
    # A real YTFLOW_DEEPSEEK_API_KEY in .env would otherwise make the A/B-completion
    # trigger (run_service._trigger_ab_eval_if_variant_b) hit the live API during
    # Playwright runs. Env vars win over .env in pydantic-settings, so this override
    # forces the same "no key configured" RuntimeError the trigger already treats as
    # non-fatal (AD-10) — deterministic, zero network, matches this script's promise.
    os.environ["YTFLOW_DEEPSEEK_API_KEY"] = ""

    apply_stub_profile()

    import uvicorn

    from yt_flow.api.main import app

    uvicorn.run(app, host=args.host, port=args.port)
