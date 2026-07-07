"""Story 2.3 — run_service gate-aware event loop: interrupt detection, DB sync,
SSE fan-out, and resume routing. [AD-3, AD-4]

Uses a real compiled graph (AsyncSqliteSaver on a temp file) + in-memory SQLModel
runs table. A fake SSE registry records fan-out without needing a live subscriber.
"""

import asyncio
import json
import uuid

import pytest_asyncio
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Run
from yt_flow.services import run_service

from tests.stubs import fakes


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


def _seed(run_id: str, status: str = "running", prompt_variant: str | None = None,
          ab_pair_id: str | None = None) -> None:
    with Session(db._engine) as session:
        session.add(Run(id=run_id, scp_id="SCP-096", status=status,
                         prompt_variant=prompt_variant, ab_pair_id=ab_pair_id))
        session.commit()


def _load(run_id: str) -> Run:
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        return run


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch, stub_stage_nodes):
    # Real graph on a temp checkpointer + in-memory runs table. Stage nodes are
    # stubbed to instant successes: these tests exercise gate/status mechanics,
    # and a genuinely failing stage no longer reaches its gate (error routes to END).
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "ws"))
    # Story 5.8: start_run now auto-triggers character reference search/generation
    # for a never-before-seen scp_id — keep these gate/status-mechanics tests offline (B-2).
    fakes.patch_character_reference_seams(monkeypatch)
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

    await run_service.start_run(run_id, "SCP-096", "scp text", reg)

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
    await run_service.start_run(run_id, "SCP-096", "t", reg)
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
    await run_service.start_run(run_id, "SCP-096", "t", reg)
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
    await run_service.start_run(run_id, "SCP-096", "t", reg)
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
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    for stage in ("scenario", "image", "tts", "subtitle", "video"):
        await run_service.resume_run(run_id, stage, "approve", reg)

    run = _load(run_id)
    assert run.status == "complete"                  # AC4: reaches END → complete
    assert "video" in _stages(reg, "stage_exit")     # AC4: stage_exit for video
    assert run_id not in run_service._configs


# ── A/B eval trigger on Variant B completion (eval-ab-trigger-wiring) ──────────


async def test_regular_run_completion_does_not_trigger_ab_eval(env, monkeypatch):
    called = {"count": 0}

    async def boom(*a, **k):
        called["count"] += 1
        raise AssertionError("evaluate_ab must not run for a non-A/B run")

    monkeypatch.setattr(run_service.eval_service, "evaluate_ab", boom)
    run_id = str(uuid.uuid4())
    _seed(run_id)  # prompt_variant=None, ab_pair_id=None — plain run
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    for stage in ("scenario", "image", "tts", "subtitle", "video"):
        await run_service.resume_run(run_id, stage, "approve", reg)
    await asyncio.gather(*run_service._bg_tasks)

    assert _load(run_id).status == "complete"
    assert called["count"] == 0


async def test_variant_b_completion_triggers_ab_eval(env, monkeypatch):
    calls = []

    async def fake_evaluate_ab(run_a_id, run_b_id):
        calls.append((run_a_id, run_b_id))

    monkeypatch.setattr(run_service.eval_service, "evaluate_ab", fake_evaluate_ab)
    source_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _seed(source_id, status="complete")
    _seed(run_id, prompt_variant="B", ab_pair_id=source_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    for stage in ("scenario", "image", "tts", "subtitle", "video"):
        await run_service.resume_run(run_id, stage, "approve", reg)
    await asyncio.gather(*run_service._bg_tasks)

    assert _load(run_id).status == "complete"
    assert calls == [(source_id, run_id)]


async def test_ab_eval_failure_does_not_affect_run_status(env, monkeypatch, caplog):
    async def boom(run_a_id, run_b_id):
        raise RuntimeError("YTFLOW_DEEPSEEK_API_KEY is not configured")

    monkeypatch.setattr(run_service.eval_service, "evaluate_ab", boom)
    source_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _seed(source_id, status="complete")
    _seed(run_id, prompt_variant="B", ab_pair_id=source_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)

    with caplog.at_level("WARNING", logger="yt_flow.services.run_service"):
        for stage in ("scenario", "image", "tts", "subtitle", "video"):
            await run_service.resume_run(run_id, stage, "approve", reg)
        await asyncio.gather(*run_service._bg_tasks)

    assert _load(run_id).status == "complete"        # AD-10: eval failure is non-fatal
    assert any("A/B evaluation failed" in r.message for r in caplog.records)


async def test_astream_failure_marks_failed(env, monkeypatch):
    # AD-4: services catches an astream() error during iteration, sets failed, fans out.
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()

    async def _boom(*args, **kwargs):
        raise RuntimeError("kaboom")
        yield  # unreachable — makes this an async generator

    monkeypatch.setattr(run_service._graph, "astream", _boom)
    await run_service.start_run(run_id, "SCP-096", "t", reg)

    run = _load(run_id)
    assert run.status == "failed"
    assert run.error == "kaboom"
    assert _kinds(reg, "run_failed")


async def test_node_failure_surfaces_failing_stage_in_trace_payload(env, monkeypatch):
    # SYS-INT-008 / FR-13: a failed node's stage (not just its exception) must be
    # surfaced — LangGraph attaches "During task with name '<node>'" as an exception
    # note (PEP 678); _stage_from_exception parses it instead of hardcoding "unknown".
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)  # pauses at gate_scenario
    reg.events.clear()

    exc = ValueError("image node exploded")
    exc.add_note("During task with name 'image' and id 'deadbeef'")

    async def _boom(*args, **kwargs):
        raise exc
        yield  # unreachable — makes this an async generator

    monkeypatch.setattr(run_service._graph, "astream", _boom)
    await run_service.resume_run(run_id, "scenario", "approve", reg)

    run = _load(run_id)
    assert run.status == "failed"
    assert run.error == "image node exploded"
    assert run.current_stage == "image"  # not "unknown" — the actual failing node
    [event] = _kinds(reg, "run_failed")
    assert event["data"]["stage"] == "image"
    assert event["data"]["error"] == "image node exploded"


def test_stage_from_exception_falls_back_to_unknown_without_notes():
    assert run_service._stage_from_exception(RuntimeError("no notes here")) == "unknown"


# ── Story 3.8 D7: status is "running" (not stale "awaiting_approval") while the
#    resumed stage is still executing ────────────────────────────────────────


async def test_resume_run_reports_running_while_stage_in_flight(tmp_path, monkeypatch):
    from yt_flow.pipeline import nodes

    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "ws"))
    fakes.patch_character_reference_seams(monkeypatch)
    db.init("sqlite://")

    def _instant(stage):
        async def node(state):
            return {"current_stage": stage, "error": None}
        return node

    for s in nodes.STAGES:
        monkeypatch.setitem(nodes.STAGE_NODES, s, _instant(s))
    gate = asyncio.Event()

    async def blocking_image(state):
        await gate.wait()
        return {"current_stage": "image", "error": None}

    monkeypatch.setitem(nodes.STAGE_NODES, "image", blocking_image)

    settings = Settings(
        langfuse_host="http://localhost", langfuse_public_key="pk",
        langfuse_secret_key="sk", db_path=str(tmp_path / "cp-d7.db"),
    )
    saver = await run_service.init(settings)  # rebuild graph with the blocking image node
    try:
        run_id = str(uuid.uuid4())
        _seed(run_id)
        reg = _FakeRegistry()
        await run_service.start_run(run_id, "SCP-096", "t", reg)  # pauses at scenario gate

        task = asyncio.create_task(run_service.resume_run(run_id, "scenario", "approve", reg))
        for _ in range(200):
            if _load(run_id).status == "running":
                break
            await asyncio.sleep(0.005)
        # AC6: truthful "running" while image (the next stage) is still executing —
        # not the stale "awaiting_approval" that resume_run used to leave behind.
        assert _load(run_id).status == "running"

        gate.set()
        await task
        assert _load(run_id).status == "awaiting_approval"  # settles at the image gate as before
    finally:
        await saver.conn.close()
        run_service._graph = None
        run_service._configs.clear()
        db._engine = None


# ── SYS-INT-007 / AD-10: Langfuse client raises → stage completes, error logged ──


class _RaisingClient:
    """Stands in for get_client() when the real Langfuse client can't reach the server."""

    def start_as_current_observation(self, *a, **k):
        raise ConnectionError("langfuse host unreachable")

    def create_trace_id(self, *, seed=None):
        return seed or ""


async def test_trace_setup_failure_is_non_fatal_and_logged(env, monkeypatch, caplog):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    monkeypatch.setattr(run_service, "get_client", lambda: _RaisingClient())

    with caplog.at_level("WARNING", logger="yt_flow.services.run_service"):
        await run_service.start_run(run_id, "SCP-096", "t", reg)

    run = _load(run_id)
    assert run.status == "awaiting_approval"  # pipeline unaffected by the tracing failure
    assert any("Langfuse" in r.message for r in caplog.records)  # AD-10: error is logged


async def test_trace_teardown_failure_is_non_fatal_and_logged(env, monkeypatch, caplog):
    class _RaisingExitSpan:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            raise ConnectionError("flush failed")

    class _RaisingExitClient:
        def start_as_current_observation(self, *a, **k):
            return _RaisingExitSpan()

        def create_trace_id(self, *, seed=None):
            return seed or ""

    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    monkeypatch.setattr(run_service, "get_client", lambda: _RaisingExitClient())

    with caplog.at_level("WARNING", logger="yt_flow.services.run_service"):
        await run_service.start_run(run_id, "SCP-096", "t", reg)

    run = _load(run_id)
    assert run.status == "awaiting_approval"  # pipeline unaffected by the tracing failure
    assert any("Langfuse" in r.message for r in caplog.records)  # AD-10: error is logged


async def test_stage_failure_marks_run_failed(env, monkeypatch, tmp_path):
    # The silent-failure bug (live 2026-07-03): a stage that sets state["error"]
    # must mark the run failed + gate_states[stage]="failed" (retryable via the
    # existing retry endpoint), publish run_failed, and never offer a gate.
    from yt_flow.pipeline import nodes

    async def failing_scenario(state):
        return {"current_stage": "scenario", "error": "stage=scenario run_id=r: boom"}

    monkeypatch.setitem(nodes.STAGE_NODES, "scenario", failing_scenario)
    settings = Settings(
        langfuse_host="http://localhost", langfuse_public_key="pk",
        langfuse_secret_key="sk", db_path=str(tmp_path / "cp-fail.db"),
    )
    saver = await run_service.init(settings)  # rebuild graph with the failing node
    try:
        run_id = str(uuid.uuid4())
        _seed(run_id)
        reg = _FakeRegistry()

        await run_service.start_run(run_id, "SCP-096", "t", reg)

        run = _load(run_id)
        assert run.status == "failed"
        assert "boom" in (run.error or "")
        assert json.loads(run.gate_states)["scenario"] == "failed"
        failed = _kinds(reg, "run_failed")
        assert failed and failed[0]["data"]["stage"] == "scenario"
        assert _stages(reg, "gate_pending") == []  # no gate for a failed stage
        assert run_id not in run_service._configs
    finally:
        await saver.conn.close()
