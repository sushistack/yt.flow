"""Story 2.3 — run_service gate-aware event loop: interrupt detection, DB sync,
SSE fan-out, and resume routing. [AD-3, AD-4]

Uses a real compiled graph (AsyncSqliteSaver on a temp file) + in-memory SQLModel
runs table. A fake SSE registry records fan-out without needing a live subscriber.
"""

import json
import uuid

import pytest_asyncio
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Run
from yt_flow.services import run_service


class _FakeRegistry:
    """Records published events; publish() matches SSEQueueRegistry's signature."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, run_id: str, event: dict) -> None:
        self.events.append(event)


def _kinds(reg: _FakeRegistry, name: str) -> list[dict]:
    return [e for e in reg.events if e["event"] == name]


def _stages(reg: _FakeRegistry, name: str) -> list[str]:
    return [e["data"]["stage"] for e in _kinds(reg, name)]


def _seed(run_id: str, status: str = "running") -> None:
    with Session(db._engine) as session:
        session.add(Run(id=run_id, scp_id="SCP-096", status=status))
        session.commit()


def _load(run_id: str) -> Run:
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        return run


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    # Real graph on a temp checkpointer + in-memory runs table.
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "ws"))
    db.init("sqlite://")
    settings = Settings(
        langfuse_host="http://localhost",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        db_path=str(tmp_path / "cp.db"),
    )
    saver = await run_service.init(settings)
    yield
    await saver.conn.close()
    run_service._graph = None
    run_service._configs.clear()
    db._engine = None


async def test_start_run_pauses_at_scenario_gate(env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()

    await run_service.start_run(run_id, "scp text", reg)

    run = _load(run_id)
    assert run.status == "awaiting_approval"
    assert run.current_stage == "scenario"
    assert json.loads(run.gate_states)["scenario"] == "pending"
    assert _stages(reg, "gate_pending") == ["scenario"]
    assert "scenario" in _stages(reg, "stage_entry")
    assert "scenario" in _stages(reg, "stage_exit")


async def test_approve_advances_to_next_gate(env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "t", reg)
    reg.events.clear()

    await run_service.resume_run(run_id, "scenario", "approve", reg)

    run = _load(run_id)
    states = json.loads(run.gate_states)
    assert states["scenario"] == "approved"
    assert states["image"] == "pending"
    assert run.status == "awaiting_approval"
    assert "image" in _stages(reg, "stage_entry")   # AC2: stage_entry for image
    assert _stages(reg, "gate_pending") == ["image"]


async def test_reject_scenario_fails_and_terminates(env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "t", reg)
    reg.events.clear()

    await run_service.resume_run(run_id, "scenario", "reject", reg)

    run = _load(run_id)
    assert run.status == "failed"                    # AC3: scenario reject → failed
    assert json.loads(run.gate_states)["scenario"] == "rejected"
    assert _kinds(reg, "run_failed")                 # AC3: run_failed emitted
    assert run_id not in run_service._configs        # config cleaned up


async def test_reject_image_loops_back_to_pending(env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "t", reg)
    await run_service.resume_run(run_id, "scenario", "approve", reg)  # pause at image
    reg.events.clear()

    await run_service.resume_run(run_id, "image", "reject", reg)

    run = _load(run_id)
    # non-scenario reject loops back → image reruns → gate_image re-interrupts (retry)
    assert run.status == "awaiting_approval"
    assert json.loads(run.gate_states)["image"] == "pending"
    assert _stages(reg, "gate_pending") == ["image"]


async def test_full_approval_completes(env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "t", reg)
    for stage in ("scenario", "image", "tts", "subtitle", "video"):
        await run_service.resume_run(run_id, stage, "approve", reg)

    run = _load(run_id)
    assert run.status == "complete"                  # AC4: reaches END → complete
    assert "video" in _stages(reg, "stage_exit")     # AC4: stage_exit for video
    assert run_id not in run_service._configs


async def test_astream_failure_marks_failed(env, monkeypatch):
    # AD-4: services catches an astream() error during iteration, sets failed, fans out.
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()

    async def _boom(*args, **kwargs):
        raise RuntimeError("kaboom")
        yield  # unreachable — makes this an async generator

    monkeypatch.setattr(run_service._graph, "astream", _boom)
    await run_service.start_run(run_id, "t", reg)

    run = _load(run_id)
    assert run.status == "failed"
    assert run.error == "kaboom"
    assert _kinds(reg, "run_failed")
