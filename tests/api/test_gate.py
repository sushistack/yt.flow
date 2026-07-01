"""Story 2.3 — POST /runs/{id}/stages/{stage}/gate endpoint (AC: 2, 3, 5, 6, 7, 8).

The endpoint validates and returns 202 immediately, launching run_service.resume_run
in the background (AD-4). resume_run is mocked here; its behavior is covered by
tests/services/test_run_service_gate.py.
"""
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

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


def _seed(run_id: str, *, status: str, gate_states: dict | None = None) -> None:
    with Session(db._engine) as session:
        session.add(Run(
            id=run_id, scp_id="SCP-096", status=status,
            gate_states=json.dumps(gate_states) if gate_states is not None else None,
        ))
        session.commit()


# ── AC2: approve → 202 + resume_run launched ────────────────────────────────

def test_gate_approve_returns_202_and_launches_resume(client):
    _seed("r1", status="awaiting_approval", gate_states={"scenario": "pending"})
    with patch("yt_flow.api.routes.runs.run_service.resume_run", new_callable=AsyncMock) as mock_resume:
        resp = client.post("/runs/r1/stages/scenario/gate", json={"action": "approve"})
        assert resp.status_code == 202
        mock_resume.assert_called_once()
        run_id, stage, action, *_ = mock_resume.call_args.args
        assert (run_id, stage, action) == ("r1", "scenario", "approve")


# ── AC3: reject → 202 + resume_run launched with reject ─────────────────────

def test_gate_reject_returns_202(client):
    _seed("r2", status="awaiting_approval", gate_states={"scenario": "pending"})
    with patch("yt_flow.api.routes.runs.run_service.resume_run", new_callable=AsyncMock) as mock_resume:
        resp = client.post("/runs/r2/stages/scenario/gate", json={"action": "reject"})
        assert resp.status_code == 202
        assert mock_resume.call_args.args[2] == "reject"


# ── AC5: gate on non-awaiting run (or non-pending gate) → 409 ───────────────

def test_gate_not_pending_returns_409(client):
    _seed("r3", status="running", gate_states={"scenario": "approved"})
    resp = client.post("/runs/r3/stages/scenario/gate", json={"action": "approve"})
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Gate not pending for stage 'scenario'"}


def test_gate_pending_missing_returns_409(client):
    _seed("r3b", status="awaiting_approval", gate_states={"image": "pending"})
    resp = client.post("/runs/r3b/stages/scenario/gate", json={"action": "approve"})
    assert resp.status_code == 409


# ── AC6: invalid action → 422 with exact detail ─────────────────────────────

def test_gate_invalid_action_returns_422(client):
    _seed("r4", status="awaiting_approval", gate_states={"scenario": "pending"})
    resp = client.post("/runs/r4/stages/scenario/gate", json={"action": "maybe"})
    assert resp.status_code == 422
    assert resp.json() == {"detail": "action must be 'approve' or 'reject'"}


# ── AC7: unknown run_id → 404 ───────────────────────────────────────────────

def test_gate_unknown_run_returns_404(client):
    resp = client.post("/runs/nope/stages/scenario/gate", json={"action": "approve"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Run not found"}


# ── AC8: invalid stage → 404 ────────────────────────────────────────────────

def test_gate_invalid_stage_returns_404(client):
    _seed("r5", status="awaiting_approval", gate_states={"scenario": "pending"})
    resp = client.post("/runs/r5/stages/bogus/gate", json={"action": "approve"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Stage 'bogus' not found"}
