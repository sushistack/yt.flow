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
        _, scp_id, scp_text, *_ = mock_start.call_args.args
        assert scp_id == "SCP-096"
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
        _, scp_id, scp_text, *_ = mock_start.call_args.args
        assert scp_id == "SCP-096"
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


# ══════════════════════════════════════════════════════════════════════════════
# Story 4.3 — GET /runs/{id} ab_result enrichment
# ══════════════════════════════════════════════════════════════════════════════

_SAMPLE_AB_RESULT = {
    "axis_scores": {
        "A": {"atmosphere": 4.0, "narrative_coherence": 3.7, "article_fidelity": 4.3},
        "B": {"atmosphere": 3.3, "narrative_coherence": 4.0, "article_fidelity": 3.7},
    },
    "pairwise_winner": {"majority_winner": "A", "majority_count": 3, "total_runs": 3},
    "rule_based_scores": {
        "A": {"scene_count_match_rate": 1.0, "subtitle_sync_error": 0.12, "audio_duration_variance": 0.08},
        "B": {"scene_count_match_rate": 0.8, "subtitle_sync_error": 0.15, "audio_duration_variance": 0.11},
    },
    "winner": "A",
    "reason": None,
    "langfuse_eval_trace_url": "https://langfuse.example.com/trace/trace-id",
    "evaluated_at": "2026-07-01T12:00:00.000Z",
}


def test_get_run_returns_ab_result_as_dict(client):
    """GET /runs/{id} returns ab_result as a parsed dict when evaluation complete."""
    from sqlmodel import Session

    run_id = client.post("/runs", json={"scp_id": "SCP-096", "scp_text": "x"}).json()["id"]
    # Simulate completed A/B evaluation by writing ab_result directly
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        run.ab_result = json.dumps(_SAMPLE_AB_RESULT)
        session.commit()

    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert "ab_result" in body
    assert body["ab_result"] == _SAMPLE_AB_RESULT
    assert body["ab_result"]["winner"] == "A"
    assert body["ab_result"]["axis_scores"]["A"]["atmosphere"] == 4.0


def test_get_run_ab_result_null_for_non_ab_run(client):
    """GET /runs/{id} returns ab_result: null when run is not part of A/B pair."""
    run_id = client.post("/runs", json={"scp_id": "SCP-096", "scp_text": "x"}).json()["id"]
    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ab_result"] is None


def test_get_run_ab_result_null_when_evaluation_not_done(client):
    """GET /runs/{id} returns ab_result: null when A/B pair exists but not evaluated."""
    from sqlmodel import Session

    run_id = client.post("/runs", json={"scp_id": "SCP-096", "scp_text": "x"}).json()["id"]
    # Set ab_pair_id but leave ab_result as None
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        run.ab_pair_id = "pair-1"
        session.commit()

    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ab_pair_id"] == "pair-1"
    assert body["ab_result"] is None


def test_list_runs_includes_ab_result(client):
    """GET /runs returns ab_result for all runs (null or dict)."""
    from sqlmodel import Session

    # Run with ab_result
    run_a = client.post("/runs", json={"scp_id": "SCP-096", "scp_text": "x"}).json()["id"]
    with Session(db._engine) as session:
        run = session.get(Run, run_a)
        run.ab_result = json.dumps(_SAMPLE_AB_RESULT)
        session.commit()

    # Run without ab_result
    run_b = client.post("/runs", json={"scp_id": "SCP-096", "scp_text": "y"}).json()["id"]

    resp = client.get("/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 2

    run_a_resp = next(r for r in runs if r["id"] == run_a)
    run_b_resp = next(r for r in runs if r["id"] == run_b)

    assert run_a_resp["ab_result"] == _SAMPLE_AB_RESULT
    assert run_b_resp["ab_result"] is None
