"""POST /runs/{id}/resume — rescue a run whose API process died mid-generation.

The endpoint returns 202 immediately and drives run_service.resume_run_from_failure
in the background; that function is mocked here (its replay behavior is covered by
tests/services/).

The route picks its mechanism from the run's gate states: a stage marked ``failed``
must be RE-EXECUTED via retry_stage, because AD-10 nodes return their error instead
of raising and LangGraph therefore checkpoints the broken node as successful — a
checkpoint replay walks past it and finishes ``complete`` with no artifacts.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

from yt_flow import db
from yt_flow.api.main import ScpEntry, app
from yt_flow.api.sse import SSEQueueRegistry
from yt_flow.db.models import Run
from yt_flow.services import run_service


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
    run_service._run_tasks.clear()
    yield
    run_service._run_tasks.clear()
    db._engine = None


@pytest.fixture
def client(_setup):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _seed(run_id: str, *, status: str, gate_states: dict | str | None = None) -> None:
    gs = gate_states if gate_states is None or isinstance(gate_states, str) else json.dumps(gate_states)
    with Session(db._engine) as session:
        session.add(Run(id=run_id, scp_id="SCP-096", status=status, gate_states=gs))
        session.commit()


def _status(run_id: str) -> str:
    with Session(db._engine) as session:
        return session.get(Run, run_id).status


class _StubTask:
    """Stands in for an asyncio.Task in _run_tasks; only .done() is consulted."""

    def __init__(self, done: bool):
        self._done = done

    def done(self) -> bool:
        return self._done


def test_resume_failed_run_returns_202_and_spawns(client):
    _seed("r1", status="failed")
    with patch("yt_flow.api.routes.runs.run_service.resume_run_from_failure",
               new_callable=AsyncMock) as mock_resume:
        resp = client.post("/runs/r1/resume")
    assert resp.status_code == 202
    assert resp.json() == {"status": "accepted", "run_id": "r1"}
    mock_resume.assert_called_once()
    assert mock_resume.call_args.args[0] == "r1"


def test_resume_orphaned_running_run_returns_202(client):
    """API restarted mid-run: row says running, no task owns it."""
    _seed("r2", status="running")
    with patch("yt_flow.api.routes.runs.run_service.resume_run_from_failure",
               new_callable=AsyncMock) as mock_resume:
        resp = client.post("/runs/r2/resume")
    assert resp.status_code == 202
    mock_resume.assert_called_once()


def test_resume_unknown_run_returns_404(client):
    resp = client.post("/runs/nope/resume")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Run not found"}


def test_resume_complete_run_returns_409(client):
    _seed("r3", status="complete")
    with patch("yt_flow.api.routes.runs.run_service.resume_run_from_failure",
               new_callable=AsyncMock) as mock_resume:
        resp = client.post("/runs/r3/resume")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Cannot resume a run with status 'complete'"}
    mock_resume.assert_not_called()


def test_resume_while_executing_in_process_returns_409(client):
    """A live in-process driver must not be joined by a second graph execution."""
    _seed("r4", status="running")
    hang = asyncio.Event()

    async def _never_finishes(run_id, sse_registry=None):
        await hang.wait()

    with patch("yt_flow.api.routes.runs.run_service.resume_run_from_failure", new=_never_finishes):
        assert client.post("/runs/r4/resume").status_code == 202
        resp = client.post("/runs/r4/resume")
        assert resp.status_code == 409
        assert resp.json() == {"detail": "Run is already executing in this process"}
        task = run_service._run_tasks["r4"]
        task.get_loop().call_soon_threadsafe(task.cancel)


def test_stale_task_entry_does_not_block_resume(client):
    _seed("r5", status="running")
    # a finished or cancelled task — both report done()
    run_service._run_tasks["r5"] = _StubTask(done=True)  # type: ignore[assignment]
    with patch("yt_flow.api.routes.runs.run_service.resume_run_from_failure",
               new_callable=AsyncMock) as mock_resume:
        resp = client.post("/runs/r5/resume")
    assert resp.status_code == 202
    mock_resume.assert_called_once()


# ── Mechanism selection: failed stage → retry_stage, orphan → checkpoint replay ──


def _retry_ok(stage="image"):
    return {"run_id": "x", "stage": stage, "status": "retrying", "message": "..."}


def test_failed_stage_reruns_the_stage_instead_of_replaying_past_it(client):
    """THE REGRESSION: replaying a failed-stage run forward returns 'complete' with no video.

    gate_states says image failed, so image (and everything downstream) must be
    re-executed — resume_run_from_failure must not be reached at all.
    """
    _seed("r10", status="failed", gate_states={"scenario": "approved", "image": "failed"})

    async def _would_falsely_complete(run_id, sse_registry=None):
        with Session(db._engine) as session:  # what the old route did: graph runs to the end
            run = session.get(Run, run_id)
            run.status = "complete"
            session.add(run)
            session.commit()

    with patch("yt_flow.api.routes.runs.run_service.resume_run_from_failure",
               new=_would_falsely_complete), \
         patch("yt_flow.api.routes.runs.run_service.retry_stage",
               new_callable=AsyncMock, return_value=_retry_ok()) as mock_retry:
        resp = client.post("/runs/r10/resume")

    assert resp.status_code == 202
    mock_retry.assert_called_once()
    assert mock_retry.call_args.args[:2] == ("r10", "image")
    assert _status("r10") != "complete"


def test_earliest_failed_stage_wins(client):
    _seed("r11", status="failed", gate_states={"tts": "failed", "image": "failed"})
    with patch("yt_flow.api.routes.runs.run_service.retry_stage",
               new_callable=AsyncMock, return_value=_retry_ok()) as mock_retry:
        assert client.post("/runs/r11/resume").status_code == 202
    assert mock_retry.call_args.args[1] == "image"


def test_orphaned_running_with_failed_stage_is_settled_so_retry_is_allowed(client):
    """retry_stage refuses a 'running' run — the orphan row must be settled first."""
    _seed("r12", status="running", gate_states={"image": "failed"})
    seen = {}

    async def _record(run_id, stage, sse_registry=None):
        seen["status"] = _status(run_id)  # what retry_stage's own guard would read
        return _retry_ok(stage)

    with patch("yt_flow.api.routes.runs.run_service.retry_stage", new=_record):
        assert client.post("/runs/r12/resume").status_code == 202
    assert seen["status"] in run_service._MUTABLE_STATES


def test_orphaned_running_without_failed_stage_still_replays_checkpoint(client):
    """Killed mid-node: nothing is marked failed, so the last checkpoint is valid."""
    _seed("r13", status="running", gate_states={"scenario": "approved", "image": "pending"})
    with patch("yt_flow.api.routes.runs.run_service.resume_run_from_failure",
               new_callable=AsyncMock) as mock_resume, \
         patch("yt_flow.api.routes.runs.run_service.retry_stage", new_callable=AsyncMock) as mock_retry:
        assert client.post("/runs/r13/resume").status_code == 202
    mock_resume.assert_called_once()
    mock_retry.assert_not_called()


@pytest.mark.parametrize("gate_states", [
    {"bogus_stage": "failed"},   # unknown key must not be handed to retry_stage
    "not json at all",           # corrupt blob
    "[1, 2, 3]",                 # valid JSON, wrong shape
    {},
])
def test_unnameable_failed_stage_falls_back_to_replay(client, gate_states):
    _seed("r14", status="failed", gate_states=gate_states)
    with patch("yt_flow.api.routes.runs.run_service.resume_run_from_failure",
               new_callable=AsyncMock) as mock_resume:
        assert client.post("/runs/r14/resume").status_code == 202
    mock_resume.assert_called_once()


def test_retry_stage_errors_are_surfaced_not_masked(client):
    """retry_stage owns _MUTABLE_STATES / _RETRYABLE — the route must not swallow it."""
    _seed("r15", status="failed", gate_states={"image": "failed"})
    with patch("yt_flow.api.routes.runs.run_service.retry_stage",
               new=AsyncMock(side_effect=HTTPException(status_code=409, detail="boom"))):
        resp = client.post("/runs/r15/resume")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "boom"}


def test_resume_awaiting_approval_returns_409(client):
    _seed("r16", status="awaiting_approval", gate_states={"image": "failed"})
    with patch("yt_flow.api.routes.runs.run_service.resume_run_from_failure",
               new_callable=AsyncMock) as mock_resume, \
         patch("yt_flow.api.routes.runs.run_service.retry_stage", new_callable=AsyncMock) as mock_retry:
        resp = client.post("/runs/r16/resume")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Cannot resume a run with status 'awaiting_approval'"}
    mock_resume.assert_not_called()
    mock_retry.assert_not_called()


def test_finished_task_is_removed_from_registry():
    """spawn's done-callback clears the entry, so the dict does not grow stale."""

    async def _go():
        task = run_service.spawn(asyncio.sleep(0), run_id="r6")
        assert run_service.is_executing("r6")
        await task
        assert "r6" not in run_service._run_tasks
        assert not run_service.is_executing("r6")

    asyncio.run(_go())
