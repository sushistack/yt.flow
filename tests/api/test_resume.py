"""POST /runs/{id}/resume — rescue a run whose API process died mid-generation.

The endpoint returns 202 immediately and drives run_service.resume_run_from_failure
in the background; that function is mocked here (its replay behavior is covered by
tests/services/).
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
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


def _seed(run_id: str, *, status: str) -> None:
    with Session(db._engine) as session:
        session.add(Run(id=run_id, scp_id="SCP-096", status=status))
        session.commit()


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


def test_finished_task_is_removed_from_registry():
    """spawn's done-callback clears the entry, so the dict does not grow stale."""

    async def _go():
        task = run_service.spawn(asyncio.sleep(0), run_id="r6")
        assert run_service.is_executing("r6")
        await task
        assert "r6" not in run_service._run_tasks
        assert not run_service.is_executing("r6")

    asyncio.run(_go())
