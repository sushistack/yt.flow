"""Tests for /runs endpoints (Story 2.1 AC: 1-7)."""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from yt_flow import db
from yt_flow.api.main import ScpEntry, app
from yt_flow.db.models import Run

_SAMPLE_SCPS = [ScpEntry(id="SCP-096", nickname="Shy Guy", object_class="Euclid", rating=4.8)]


@asynccontextmanager
async def _noop_lifespan(application):
    """Bypass the real lifespan in tests — DB and state are configured by fixtures."""
    yield


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    """In-memory DB + test lifespan + app state for every test."""
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


# ── AC 1: app.state.scps populated ─────────────────────────────────────────

def test_scps_populated(client):
    assert len(app.state.scps) == 1
    assert app.state.scps[0].id == "SCP-096"


# ── AC 2: POST /runs creates row, returns 201 ───────────────────────────────

def test_post_runs_returns_201(client):
    resp = client.post("/runs", json={"scp_id": "SCP-096", "scp_text": "test text"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "running"
    assert body["scp_id"] == "SCP-096"
    assert len(body["id"]) == 36  # UUID v4


def test_post_runs_inserts_row(client):
    resp = client.post("/runs", json={"scp_id": "SCP-096", "scp_text": "text"})
    run_id = resp.json()["id"]
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
    assert run is not None
    assert run.scp_id == "SCP-096"


def test_post_runs_extra_field_roundtrip(client):
    resp = client.post(
        "/runs",
        json={"scp_id": "SCP-096", "scp_text": "t", "extra": {"foo": "bar"}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert json.loads(body["extra"]) == {"foo": "bar"}


# ── AC 3: GET /runs returns list sorted by started_at desc ──────────────────

def test_get_runs_sorted(client):
    now = datetime.now(timezone.utc)
    with Session(db._engine) as session:
        session.add(Run(id="id-old", scp_id="SCP-001", status="running",
                        started_at=(now - timedelta(seconds=10)).isoformat(),
                        updated_at=now.isoformat()))
        session.add(Run(id="id-new", scp_id="SCP-002", status="running",
                        started_at=now.isoformat(), updated_at=now.isoformat()))
        session.commit()
    resp = client.get("/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 2
    assert runs[0]["id"] == "id-new"


# ── AC 4: GET /runs/{id} returns run with langfuse_trace_url field ──────────

def test_get_run_by_id(client):
    run_id = client.post("/runs", json={"scp_id": "SCP-096", "scp_text": "x"}).json()["id"]
    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == run_id
    assert "langfuse_trace_url" in body


# ── AC 5: GET /runs/{id}/artifact 404 on non-complete run ───────────────────

def test_artifact_404_when_not_complete(client):
    run_id = client.post("/runs", json={"scp_id": "SCP-096", "scp_text": "x"}).json()["id"]
    resp = client.get(f"/runs/{run_id}/artifact")
    assert resp.status_code == 404


# ── AC 6: POST /runs launches background task with scp_text ─────────────────

def test_post_runs_launches_background_task(client):
    with patch("yt_flow.api.routes.runs.run_service.start_run", new_callable=AsyncMock) as mock_start:
        resp = client.post("/runs", json={"scp_id": "SCP-096", "scp_text": "hello"})
        assert resp.status_code == 201
        # AsyncMock.__call__ is tracked at coroutine-creation time (before task executes)
        mock_start.assert_called_once()
        _, scp_text, *_ = mock_start.call_args.args
        assert scp_text == "hello"


# ── Story 3.3: POST /runs resolves scp_text server-side by scp_id ───────────

def test_post_runs_resolves_scp_text_from_state(client):
    """When the body omits scp_text, the server looks it up in app.state.scps."""
    app.state.scps = [
        ScpEntry(id="SCP-096", nickname="Shy Guy", object_class="Euclid", rating=4.8,
                 scp_text="resolved article text"),
    ]
    with patch("yt_flow.api.routes.runs.run_service.start_run", new_callable=AsyncMock) as mock_start:
        resp = client.post("/runs", json={"scp_id": "SCP-096"})
        assert resp.status_code == 201
        _, scp_text, *_ = mock_start.call_args.args
        assert scp_text == "resolved article text"


def test_post_runs_422_when_no_scp_text_available(client):
    """Unknown scp_id (or entry without text) and no body text → visible 422, no run."""
    resp = client.post("/runs", json={"scp_id": "SCP-000"})
    assert resp.status_code == 422
    assert "SCP-000" in resp.json()["detail"]


# ── AC 7: GET /runs/{id} with unknown id → 404 ──────────────────────────────

def test_get_run_unknown_id(client):
    resp = client.get("/runs/does-not-exist")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Run not found"}
