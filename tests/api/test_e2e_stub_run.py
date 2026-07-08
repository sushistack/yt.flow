"""SYS-E2E-001: stub-profile full run driven entirely through the HTTP API.

Upgrades tests/pipeline/test_stub_profile_smoke.py (B-2 seam smoke — drives
run_service directly) to the actual product contract: POST /runs -> observe SSE
events -> approve all 5 gates via the gate endpoint -> assert completion, SSE
event order, and the final artifact on disk. Zero real network/subprocess calls
(stub_profile fakes DeepSeek/Qwen/ComfyUI/ffmpeg).
"""
import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlmodel import Session

from yt_flow import db
from yt_flow.api.main import ScpEntry, app
from yt_flow.config import Settings
from yt_flow.db.models import Run
from yt_flow.services import run_service


class _RecordingRegistry:
    """Records published SSE events in publish order — the same order clients see."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, run_id: str, event: dict) -> None:
        self.events.append(event)


@asynccontextmanager
async def _noop_lifespan(application):
    yield


@pytest.fixture
async def api_env(tmp_path, monkeypatch, stub_profile):
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "ws"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(tmp_path / "assets"))
    db.init("sqlite://")
    app.state.scps = [ScpEntry(id="SCP-096", nickname="Shy Guy", object_class="Euclid", rating=4.8)]
    app.state.workspace_path = str(tmp_path / "ws")
    app.state.sse_registry = _RecordingRegistry()
    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)

    settings = Settings(
        langfuse_host="http://localhost", langfuse_public_key="pk", langfuse_secret_key="sk",
        db_path=str(tmp_path / "cp.db"),
    )
    saver = await run_service.init(settings)
    yield tmp_path
    await saver.conn.close()
    run_service.configure(None)
    run_service._configs.clear()
    db._engine = None


async def _drain_bg_tasks(timeout: float = 10) -> None:
    """Await whatever run_service.spawn() just scheduled before making assertions."""
    tasks = list(run_service._bg_tasks)
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)


def _asgi_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk(api_env):
    registry: _RecordingRegistry = app.state.sse_registry

    async with _asgi_client() as c:
        resp = await c.post("/runs", json={"scp_id": "SCP-096", "scp_text": "stub SCP article text"})
        assert resp.status_code == 201
        run_id = resp.json()["id"]
        await _drain_bg_tasks()

        for stage in ("scenario", "image", "tts", "subtitle", "video"):
            run = (await c.get(f"/runs/{run_id}")).json()
            assert run["status"] == "awaiting_approval"
            assert run["current_stage"] == stage

            resp = await c.post(f"/runs/{run_id}/stages/{stage}/gate", json={"action": "approve"})
            assert resp.status_code == 202
            await _drain_bg_tasks()

        final = (await c.get(f"/runs/{run_id}")).json()
        assert final["status"] == "complete"

        artifact_resp = await c.get(f"/runs/{run_id}/artifact")
        assert artifact_resp.status_code == 200
        assert artifact_resp.headers["content-type"] == "video/mp4"

    # SSE order: each stage's entry/exit brackets its gate_pending, in stage order (AD-3/AD-4).
    kinds_and_stages = [(e["event"], e["data"]["stage"]) for e in registry.events
                        if e["event"] in ("stage_entry", "stage_exit", "gate_pending")]
    expected = [
        ev for stage in ("scenario", "image", "tts", "subtitle", "video")
        for ev in ((("stage_entry", stage), ("stage_exit", stage), ("gate_pending", stage)))
    ]
    assert kinds_and_stages == expected

    # Artifacts on disk: the real video seam wrote the workspace tree end to end.
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
    assert run.status == "complete"
    ws = api_env / "ws" / run_id
    assert (ws / "video.mp4").is_file()
    assert (ws / "video.mp4").stat().st_size > 0
