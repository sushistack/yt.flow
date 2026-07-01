"""Tests for SSE queue registry and /runs/{id}/progress endpoint (Story 2.2 AC: 1-5)."""
import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from yt_flow import db
from yt_flow.api.main import ScpEntry, app
from yt_flow.api.sse import SSEQueueRegistry
from yt_flow.db.models import Run


@asynccontextmanager
async def _noop_lifespan(application):
    yield


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init("sqlite://")
    app.state.scps = [ScpEntry(id="SCP-096", nickname="Shy Guy", object_class="Euclid", rating=4.8)]
    app.state.workspace_path = "./workspace"
    app.state.sse_registry = SSEQueueRegistry()
    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    yield
    db._engine = None


@pytest.fixture
def client(_setup):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _seed_run(run_id: str = "test-run-id") -> str:
    with Session(db._engine) as session:
        session.add(Run(id=run_id, scp_id="SCP-096", status="running"))
        session.commit()
    return run_id


def _asgi_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _drain(run_id: str, registry: SSEQueueRegistry) -> None:
    """End SSE stream via run_failed so the generator exits cleanly in tests."""
    await asyncio.sleep(0.02)
    await registry.publish(run_id, {"event": "run_failed", "data": {"run_id": run_id, "stage": "unknown", "error": "test-end"}})


# ── AC 1: /runs/{id}/progress returns text/event-stream with correct headers ─

async def test_sse_headers():
    run_id = _seed_run()
    registry: SSEQueueRegistry = app.state.sse_registry
    async with _asgi_client() as c:
        asyncio.create_task(_drain(run_id, registry))
        async with c.stream("GET", f"/runs/{run_id}/progress") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            assert resp.headers.get("cache-control") == "no-cache"
            assert resp.headers.get("x-accel-buffering") == "no"
            async for _ in resp.aiter_lines():
                pass


# ── AC 1: 404 for unknown run_id ─────────────────────────────────────────────

def test_progress_404_unknown_run(client):
    resp = client.get("/runs/does-not-exist/progress")
    assert resp.status_code == 404


# ── AC 2: stage_entry + stage_exit received over SSE ─────────────────────────

async def test_sse_stage_entry_exit():
    run_id = _seed_run()
    registry: SSEQueueRegistry = app.state.sse_registry

    async def _publish():
        await asyncio.sleep(0.02)
        await registry.publish(run_id, {"event": "stage_entry", "data": {"run_id": run_id, "stage": "scenario"}})
        await registry.publish(run_id, {"event": "stage_exit", "data": {"run_id": run_id, "stage": "scenario"}})
        await registry.publish(run_id, {"event": "run_failed", "data": {"run_id": run_id, "stage": "unknown", "error": "done"}})

    received_events = []
    async with _asgi_client() as c:
        asyncio.create_task(_publish())
        async with c.stream("GET", f"/runs/{run_id}/progress") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    received_events.append(line.split(":", 1)[1].strip())

    assert "stage_entry" in received_events
    assert "stage_exit" in received_events


# ── AC 3: gate_pending received over SSE ─────────────────────────────────────

async def test_sse_gate_pending():
    run_id = _seed_run()
    registry: SSEQueueRegistry = app.state.sse_registry

    async def _publish():
        await asyncio.sleep(0.02)
        await registry.publish(run_id, {"event": "gate_pending", "data": {"run_id": run_id, "stage": "scenario"}})
        await registry.publish(run_id, {"event": "run_failed", "data": {"run_id": run_id, "stage": "unknown", "error": "done"}})

    received_events = []
    async with _asgi_client() as c:
        asyncio.create_task(_publish())
        async with c.stream("GET", f"/runs/{run_id}/progress") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    received_events.append(line.split(":", 1)[1].strip())

    assert "gate_pending" in received_events


# ── AC 4: run_failed received and stream closes ───────────────────────────────

async def test_sse_run_failed_closes_stream():
    run_id = _seed_run()
    registry: SSEQueueRegistry = app.state.sse_registry

    async def _publish():
        await asyncio.sleep(0.02)
        await registry.publish(run_id, {
            "event": "run_failed",
            "data": {"run_id": run_id, "stage": "scenario", "error": "boom"},
        })

    events = []
    data_payloads = []
    async with _asgi_client() as c:
        asyncio.create_task(_publish())
        async with c.stream("GET", f"/runs/{run_id}/progress") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
                elif line.startswith("data:"):
                    data_payloads.append(json.loads(line.split(":", 1)[1].strip()))

    assert events == ["run_failed"]
    assert data_payloads[0] == {"run_id": run_id, "stage": "scenario", "error": "boom"}


# ── AC 5: queue cleanup when stream ends ─────────────────────────────────────

async def test_sse_queue_cleanup_on_stream_end():
    run_id = _seed_run()
    registry: SSEQueueRegistry = app.state.sse_registry

    async with _asgi_client() as c:
        asyncio.create_task(_drain(run_id, registry))
        async with c.stream("GET", f"/runs/{run_id}/progress") as resp:
            async for _ in resp.aiter_lines():
                pass

    assert not registry.has_subscriber(run_id)


# ── Unit tests for SSEQueueRegistry ──────────────────────────────────────────

async def test_registry_has_subscriber():
    registry = SSEQueueRegistry()
    assert not registry.has_subscriber("r1")

    gen = registry.subscribe("r1")
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    assert registry.has_subscriber("r1")

    await registry.publish("r1", {"event": "stage_exit", "data": {"run_id": "r1", "stage": "video"}})
    chunk = await task
    assert "stage_exit" in chunk

    # still subscribed after one event
    assert registry.has_subscriber("r1")

    await gen.aclose()
    assert not registry.has_subscriber("r1")


async def test_registry_unsubscribe_cleanup():
    registry = SSEQueueRegistry()
    gen = registry.subscribe("r1")
    # advance to queue.get()
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    assert registry.has_subscriber("r1")

    # unsubscribe sends sentinel → immediately False
    registry.unsubscribe("r1")
    assert not registry.has_subscriber("r1")

    # generator gets sentinel and exits
    with pytest.raises(StopAsyncIteration):
        await task


async def test_registry_publish_no_subscriber_is_noop():
    registry = SSEQueueRegistry()
    # Must not raise
    await registry.publish("nonexistent", {"event": "stage_entry", "data": {"run_id": "x", "stage": "tts"}})


async def test_registry_event_data_json_valid():
    registry = SSEQueueRegistry()
    gen = registry.subscribe("r1")
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    await registry.publish("r1", {"event": "stage_entry", "data": {"run_id": "r1", "stage": "image"}})
    chunk = await task
    lines = [ln for ln in chunk.strip().split("\n") if ln]
    event_line = next(ln for ln in lines if ln.startswith("event:"))
    data_line = next(ln for ln in lines if ln.startswith("data:"))
    assert event_line == "event: stage_entry"
    payload = json.loads(data_line[len("data: "):])
    assert payload == {"run_id": "r1", "stage": "image"}
    await gen.aclose()


async def test_registry_multiple_concurrent_runs_isolated():
    registry = SSEQueueRegistry()

    async def collect_a() -> str:
        gen = registry.subscribe("run-a")
        task = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0)
        await registry.publish("run-a", {"event": "stage_entry", "data": {"run_id": "run-a", "stage": "scenario"}})
        chunk = await task
        await gen.aclose()
        return chunk

    async def collect_b() -> str:
        gen = registry.subscribe("run-b")
        task = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0)
        await registry.publish("run-b", {"event": "stage_exit", "data": {"run_id": "run-b", "stage": "scenario"}})
        chunk = await task
        await gen.aclose()
        return chunk

    r1, r2 = await asyncio.gather(collect_a(), collect_b())
    assert "stage_entry" in r1 and "run-a" in r1
    assert "stage_exit" in r2 and "run-b" in r2


async def test_registry_run_failed_ends_stream():
    registry = SSEQueueRegistry()

    chunks = []

    async def consume():
        async for chunk in registry.subscribe("r1"):
            chunks.append(chunk)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await registry.publish("r1", {"event": "run_failed", "data": {"run_id": "r1", "stage": "tts", "error": "oops"}})
    await asyncio.sleep(0.01)
    await task

    assert len(chunks) == 1
    assert "run_failed" in chunks[0]
    assert not registry.has_subscriber("r1")


