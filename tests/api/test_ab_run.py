"""Tests for POST /runs/{id}/ab — A/B Variant B creation (Story 4.1)."""
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from yt_flow import db
from yt_flow.api.main import ScpEntry, app
from yt_flow.db.models import Run
from yt_flow.services import run_service

_SAMPLE_SCPS = [ScpEntry(id="SCP-096", nickname="Shy Guy", object_class="Euclid", rating=4.8)]


@asynccontextmanager
async def _noop_lifespan(application):
    yield


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init("sqlite://")
    app.state.scps = _SAMPLE_SCPS
    app.state.workspace_path = "./workspace"
    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    yield
    db._engine = None


@pytest.fixture
def client(_setup):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _seed_run(**kwargs) -> str:
    run_id = kwargs.pop("id", str(uuid.uuid4()))
    fields = dict(scp_id="SCP-096", status="complete")
    fields.update(kwargs)
    with Session(db._engine) as session:
        session.add(Run(id=run_id, **fields))
        session.commit()
    return run_id


# ── AC 5: 404 unknown source ───────────────────────────────────────────────
def test_ab_404_unknown_run(client):
    resp = client.post("/runs/does-not-exist/ab")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Run not found"}


# ── AC 3: 409 when source not complete ──────────────────────────────────────
@pytest.mark.parametrize("status", ["running", "awaiting_approval"])
def test_ab_409_source_not_complete(client, status):
    src = _seed_run(status=status)
    resp = client.post(f"/runs/{src}/ab")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Cannot create A/B run: source run is not complete"}


# ── AC 4: 409 when an A/B pair already exists ───────────────────────────────
def test_ab_409_pair_exists(client):
    src = _seed_run(status="complete")
    _seed_run(status="running", prompt_variant="B", ab_pair_id=src)
    resp = client.post(f"/runs/{src}/ab")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "A/B pair already exists for this run"}


def test_ab_409_source_is_variant_b(client):
    src = _seed_run(status="complete")
    variant = _seed_run(status="complete", prompt_variant="B", ab_pair_id=src)
    resp = client.post(f"/runs/{variant}/ab")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Cannot create A/B run from a variant run"}


# ── AC 1, 6, 7, 8: 201 creates a linked Variant B run ───────────────────────
def test_ab_201_creates_variant_b(client):
    src = _seed_run(status="complete")

    async def fake_create(source_id, sse_registry=None):
        new_id = str(uuid.uuid4())
        with Session(db._engine) as s:
            s.add(Run(id=new_id, scp_id="SCP-096", status="running",
                      prompt_variant="B", ab_pair_id=source_id))
            s.commit()
        return new_id

    with patch.object(run_service, "create_ab_run", new=AsyncMock(side_effect=fake_create)) as m:
        resp = client.post(f"/runs/{src}/ab")
        m.assert_awaited_once_with(src, None)

    assert resp.status_code == 201
    body = resp.json()
    assert body["prompt_variant"] == "B"
    assert body["ab_pair_id"] == src
    assert body["status"] == "running"
    assert len(body["id"]) == 36  # UUID v4

    # AC 6: both runs appear in GET /runs, linked by ab_pair_id
    runs = client.get("/runs").json()
    assert {r["id"] for r in runs} >= {src, body["id"]}
    variant = next(r for r in runs if r["ab_pair_id"] == src)
    assert variant["id"] == body["id"]


# ── Service unit: create_ab_run copies scp_text from source state (AC 1, 2, 8) ──
async def test_create_ab_run_copies_state(_setup):
    src = _seed_run(status="complete", scp_id="SCP-096")

    fake_graph = SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(values={"scp_text": "SOURCE TEXT"})),
    )
    run_service.configure(fake_graph)

    def _fake_spawn(coro):
        coro.close()  # discard the scheduled start_run coroutine without a warning

    with patch.object(run_service, "start_run", new=AsyncMock()) as mstart, \
         patch.object(run_service, "spawn", side_effect=_fake_spawn):
        new_id = await run_service.create_ab_run(src)

    with Session(db._engine) as s:
        new = s.get(Run, new_id)
    assert new is not None
    assert new.prompt_variant == "B"
    assert new.ab_pair_id == src
    assert new.scp_id == "SCP-096"
    assert new.status == "running"
    # AC 2/8: launched via the standard start_run driver with Variant B's scp_text
    mstart.assert_called_once_with(new_id, "SOURCE TEXT", None, prompt_variant="B")


async def test_create_ab_run_missing_scp_text_raises(_setup):
    src = _seed_run(status="complete")
    fake_graph = SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(values={})),
    )
    run_service.configure(fake_graph)
    with pytest.raises(ValueError):
        await run_service.create_ab_run(src)


async def test_create_ab_run_duplicate_raises_before_checkpoint_read(_setup):
    src = _seed_run(status="complete")
    _seed_run(status="running", prompt_variant="B", ab_pair_id=src)
    fake_graph = SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(values={"scp_text": "SOURCE TEXT"})),
    )
    run_service.configure(fake_graph)

    with pytest.raises(run_service.ABRunConflictError, match="A/B pair already exists"):
        await run_service.create_ab_run(src)
    fake_graph.aget_state.assert_not_awaited()
