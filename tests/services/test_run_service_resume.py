"""Story 1.10 — resume from failure, explicit full restart, and Langfuse trace
continuity. [AC1-AC4, FR-7, FR-8, FR-12]

Orchestration semantics only: a spy graph (real AsyncSqliteSaver on a temp file)
with mock ``scenario``/``video`` nodes stands in for the media stages, so the
tests prove *what LangGraph re-runs*, not media generation. A ``video`` node that
fails once forces the ``scenario -> checkpoint -> failure -> resume -> complete``
path. Langfuse is mocked — no homelab dependency.
"""

import uuid
from contextlib import nullcontext

import aiosqlite
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlmodel import Session

from yt_flow import db
from yt_flow.db.models import Run
from yt_flow.domain.state import PipelineState
from yt_flow.services import run_service


class _Spy:
    def __init__(self) -> None:
        self.scenario_calls = 0
        self.video_calls = 0
        self.fail_next_video = False


def _build_spy_graph(spy: _Spy, saver: AsyncSqliteSaver):
    async def scenario(state: PipelineState) -> dict:
        spy.scenario_calls += 1
        return {"scenes": [{"scene_num": 1, "narration": "n", "shots": [],
                            "audio_path": None, "audio_duration": None,
                            "word_timings": [], "subtitle_path": None}],
                "current_stage": "scenario"}

    async def video(state: PipelineState) -> dict:
        spy.video_calls += 1
        if spy.fail_next_video:
            spy.fail_next_video = False
            raise RuntimeError("boom")
        return {"video_path": "out.mp4", "current_stage": "video"}

    g = StateGraph(PipelineState)
    g.add_node("scenario", scenario)
    g.add_node("video", video)
    g.add_edge(START, "scenario")
    g.add_edge("scenario", "video")
    g.add_edge("video", END)
    return g.compile(checkpointer=saver)


def _seed(run_id: str) -> None:
    with Session(db._engine) as session:
        session.add(Run(id=run_id, scp_id="SCP-173", status="running"))
        session.commit()


def _load(run_id: str) -> Run:
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        return run


@pytest_asyncio.fixture
async def spy(tmp_path):
    _spy = _Spy()
    db.init("sqlite://")
    conn = await aiosqlite.connect(str(tmp_path / "cp.db"))
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    run_service.configure(_build_spy_graph(_spy, saver))
    yield _spy
    await conn.close()
    run_service._graph = None
    run_service._configs.clear()
    db._engine = None


async def test_resume_from_failure_does_not_rerun_scenario(spy):
    # AC1/FR-7: run fails after scenario; resume continues at the failed node,
    # scenario is NOT re-executed.
    run_id = str(uuid.uuid4())
    _seed(run_id)
    spy.fail_next_video = True

    await run_service.start_run(run_id, "SCP-173", "scp text", None)
    assert spy.scenario_calls == 1
    assert spy.video_calls == 1
    assert _load(run_id).status == "failed"

    await run_service.resume_run_from_failure(run_id)

    assert spy.scenario_calls == 1          # AC1: scenario not re-run
    assert spy.video_calls == 2             # video retried and succeeded
    run = _load(run_id)
    assert run.status == "complete"
    assert run_id not in run_service._configs


async def test_full_restart_reenters_scenario(spy):
    # AC2/FR-8: even with a completed checkpoint, full restart re-runs scenario.
    run_id = str(uuid.uuid4())
    _seed(run_id)

    await run_service.start_run(run_id, "SCP-173", "scp text", None)
    assert spy.scenario_calls == 1
    assert _load(run_id).status == "complete"

    await run_service.full_restart_run(run_id)

    assert spy.scenario_calls == 2          # AC2: scenario re-entered despite prior checkpoint
    assert spy.video_calls == 2
    assert _load(run_id).status == "complete"


async def test_full_restart_resets_stale_state(spy):
    # AC2 guardrail: restart streams a fresh _initial_state, so no stale artifacts
    # accumulate — the post-restart checkpoint holds exactly one freshly-produced run.
    run_id = str(uuid.uuid4())
    _seed(run_id)
    await run_service.start_run(run_id, "SCP-173", "scp text", None)

    await run_service.full_restart_run(run_id)
    snap = await run_service._graph.aget_state({"configurable": {"thread_id": run_id}})
    # scp_text preserved, error cleared, and outputs are the single fresh run's —
    # not the prior run merged in (proves the thread wipe + initial-state reset took).
    assert snap.values["scp_text"] == "scp text"
    assert snap.values["error"] is None
    assert len(snap.values["scenes"]) == 1 and snap.values["scenes"][0]["scene_num"] == 1
    assert snap.values["video_path"] == "out.mp4"


async def test_trace_id_deterministic_and_reused_on_resume(spy, monkeypatch):
    # AC3/AC4/FR-12: every execution roots its spans under one trace deterministically
    # derived from run_id — initial and resumed runs share the same trace_id.
    run_id = str(uuid.uuid4())
    _seed(run_id)
    rec: dict[str, list] = {"seeds": [], "contexts": []}

    class _FakeClient:
        def create_trace_id(self, *, seed=None):
            rec["seeds"].append(seed)
            return f"trace-{seed}"

        def start_as_current_observation(self, *, name, as_type, trace_context):
            rec["contexts"].append(trace_context)
            return nullcontext()

    monkeypatch.setattr(run_service, "get_client", lambda: _FakeClient())

    spy.fail_next_video = True
    await run_service.start_run(run_id, "SCP-173", "scp text", None)
    await run_service.resume_run_from_failure(run_id)

    assert rec["seeds"] == [run_id, run_id]                       # AC3: seed is always run_id
    trace_ids = {c["trace_id"] for c in rec["contexts"]}
    assert trace_ids == {f"trace-{run_id}"}                       # AC4: one shared trace, no new root


async def test_tracing_enter_failure_is_non_fatal(spy, monkeypatch):
    # AD-10: a Langfuse span that blows up on __enter__ must NOT fail the run.
    run_id = str(uuid.uuid4())
    _seed(run_id)

    class _Boom:
        def __enter__(self):
            raise RuntimeError("langfuse down")

        def __exit__(self, *a):
            return False

    class _FakeClient:
        def create_trace_id(self, *, seed=None):
            return f"trace-{seed}"

        def start_as_current_observation(self, **_):
            return _Boom()

    monkeypatch.setattr(run_service, "get_client", lambda: _FakeClient())

    await run_service.start_run(run_id, "SCP-173", "scp text", None)

    assert spy.scenario_calls == 1
    assert _load(run_id).status == "complete"   # pipeline unaffected by tracing failure


def test_create_trace_id_is_deterministic():
    # FR-12: the underlying id generation is a pure function of the seed.
    from langfuse import Langfuse

    assert Langfuse.create_trace_id(seed="r") == Langfuse.create_trace_id(seed="r")
    assert Langfuse.create_trace_id(seed="r") != Langfuse.create_trace_id(seed="q")
