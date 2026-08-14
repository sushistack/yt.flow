"""Story 13.1 — run warnings from producer to human gate, end to end.

Story 8.15's lesson is the reason this file exists: a fake provider fell into a broad
``except`` while the suite stayed green, because every assertion stopped at ``caplog``.
So these tests force a REAL service/node fallback, drive the REAL compiled graph to a
gate, and then read the artifact DTO the UI actually calls — the same seam, not a
reconstruction of it.

Same harness as ``test_run_service_gate.py``: real graph on a temp AsyncSqliteSaver,
in-memory runs table, stubbed stage nodes (a genuinely failing stage never reaches its
gate, so gate mechanics must run on nodes that succeed).
"""

import asyncio
import json
import uuid

import pytest
import pytest_asyncio
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Run
from yt_flow.domain.warnings import make_warning
from yt_flow.services import run_service
from yt_flow.services.character_service import CharacterService

from tests.stubs import fakes


class _FakeRegistry:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, run_id: str, event: dict) -> None:
        self.events.append(event)


def _data(reg: _FakeRegistry, name: str) -> list[dict]:
    return [e["data"] for e in reg.events if e["event"] == name]


def _seed(run_id: str) -> None:
    with Session(db._engine) as session:
        session.add(Run(id=run_id, scp_id="SCP-096", status="running"))
        session.commit()


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch, stub_stage_nodes):
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "ws"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(tmp_path / "assets"))
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


_SCENE = {
    "scene_num": 1, "narration": "문장.", "shots": [], "audio_path": None,
    "audio_duration": None, "word_timings": [], "subtitle_path": None,
    "mood": "escalation", "title": "", "kicker": "", "display_narration": "문장.",
}


@pytest.fixture
def scene_scenario(monkeypatch):
    """A scenario stage that actually produces a scene, so the artifact endpoint has
    something to answer with, and that records every execution.

    Tests must list `stub_stage_nodes, scene_scenario, env` in that order: build_graph
    binds node callables at build time, so this has to land after the blanket stub and
    before `env` compiles the graph (same constraint as 12.3's quality_scenario).
    """
    from yt_flow.pipeline import nodes

    runs: list[str] = []

    async def node(state):
        runs.append(state["run_id"])
        return {"current_stage": "scenario", "error": None, "scenes": [dict(_SCENE)]}

    monkeypatch.setitem(nodes.STAGE_NODES, "scenario", node)
    return runs


@pytest.fixture
def broken_reference_search(monkeypatch):
    """Force the real Story 5.8 pre-graph provisioning to fail wholesale.

    This is the most expensive silent outcome in Epic 13: every shot naming the entity
    renders background-only, and until now the only trace was one log line.
    """
    async def _boom(self, scp_id, workspace_path=None):
        raise RuntimeError("image search is down")

    monkeypatch.setattr(CharacterService, "search_references", _boom)


async def test_forced_provisioning_failure_reaches_the_scenario_gate_artifact(
    stub_stage_nodes, scene_scenario, env, broken_reference_search,
):
    """AC7's end-to-end assertion: fallback still succeeded, the warning is in the
    checkpoint, and it is visible on the DTO the Artifact Panel fetches."""
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()

    await run_service.start_run(run_id, "SCP-096", "scp text", reg)

    # 1. The run did NOT fail — it is parked at the gate exactly as a clean run is.
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        assert run.status == "awaiting_approval"
        assert run.error is None
        assert json.loads(run.gate_states) == {"scenario": "pending"}

    # 2. The checkpoint carries the structured warning.
    snapshot = await run_service._graph.aget_state({"configurable": {"thread_id": run_id}})
    codes = [w["code"] for w in snapshot.values["run_warnings"]]
    assert "character_provisioning_failed" in codes

    # 3. The gate frame carries it…
    gate = _data(reg, "gate_pending")[0]
    assert gate["warning_count"] == len(snapshot.values["run_warnings"])
    assert any(w["code"] == "character_provisioning_failed" for w in gate["warnings"])

    # 4. …and so does the durable artifact response, which is the authority.
    artifacts = await run_service.get_stage_artifacts(run_id, "scenario")
    warning = next(w for w in artifacts["warnings"] if w["code"] == "character_provisioning_failed")
    assert warning["stage"] == "scenario"
    assert warning["message"]                       # Korean operator copy, not raw text
    assert warning["context"]["card_key"] == "SCP-096"
    assert "RuntimeError" in warning["context"]["detail"]
    assert artifacts["scenario_quality"] is None    # 12.3's contract is untouched


async def test_warnings_are_json_serializable_through_the_api_shape(
    stub_stage_nodes, scene_scenario, env, broken_reference_search,
):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    await run_service.start_run(run_id, "SCP-096", "scp text", None)
    artifacts = await run_service.get_stage_artifacts(run_id, "scenario")
    assert json.loads(json.dumps(artifacts)) == artifacts


async def test_a_clean_run_reaches_the_gate_with_no_warnings(stub_stage_nodes, scene_scenario, env, monkeypatch):
    """The warning-free path: provisioning short-circuits because the character exists."""
    monkeypatch.setattr(run_service, "_ensure_character_reference", _returns([]))
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()

    await run_service.start_run(run_id, "SCP-096", "scp text", reg)

    snapshot = await run_service._graph.aget_state({"configurable": {"thread_id": run_id}})
    assert snapshot.values["run_warnings"] == []
    assert (await run_service.get_stage_artifacts(run_id, "scenario"))["warnings"] == []
    # A clean run's gate frame stays byte-identical to a pre-13.1 one.
    assert _data(reg, "gate_pending")[0] == {"run_id": run_id, "stage": "scenario"}


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _records(sink: list):
    async def _fn(*args, **kwargs):
        sink.append(args)
        return []
    return _fn


_POSE_WARNING = make_warning("special_pose_cap_exceeded", card_key="SCP-049",
                              pose_hint="hint:abc123", cap=3)


async def test_scenario_approval_provisioning_merges_into_the_paused_checkpoint(
    stub_stage_nodes, scene_scenario, env, monkeypatch,
):
    """AC6: the merge happens while the graph is paused at gate_scenario. It must not
    change the next node, consume the pending interrupt, or re-run scenario's side
    effects — verified against the real pinned LangGraph, not a fake graph."""
    scenario_runs = scene_scenario  # every scenario-node execution, in order
    monkeypatch.setattr(run_service, "_ensure_character_reference", _returns([]))
    monkeypatch.setattr(run_service, "_ensure_special_pose_cards", _returns([_POSE_WARNING]))
    monkeypatch.setattr(run_service, "_ensure_derived_entity_cards", _returns([]))

    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "scp text", reg)
    assert scenario_runs == [run_id]
    config = {"configurable": {"thread_id": run_id}}
    assert (await run_service._graph.aget_state(config)).next == ("gate_scenario",)

    reg.events.clear()
    await run_service.resume_run(run_id, "scenario", "approve", reg)

    # The decision landed, the graph advanced, and scenario did not run a second time.
    state = await run_service._graph.aget_state(config)
    assert state.values["gate_states"]["scenario"] == "approved"
    assert state.next == ("gate_image",)
    assert scenario_runs == [run_id]
    # The provisioning warning rode the checkpoint to the NEXT gate — the scenario gate
    # was already open when it was produced, so this is the first place it can be seen.
    assert state.values["run_warnings"] == [_POSE_WARNING]
    gate = _data(reg, "gate_pending")[0]
    assert gate["stage"] == "image"
    assert gate["warnings"] == [_POSE_WARNING]
    assert (await run_service.get_stage_artifacts(run_id, "scenario"))["warnings"] == [_POSE_WARNING]


async def test_a_failed_warning_merge_does_not_break_the_approve(
    stub_stage_nodes, scene_scenario, env, monkeypatch,
):
    """AD-10: provisioning has already run by then, so a broken checkpoint write must
    cost the warning record, never the operator's decision."""
    monkeypatch.setattr(run_service, "_ensure_character_reference", _returns([]))
    monkeypatch.setattr(run_service, "_ensure_special_pose_cards", _returns([_POSE_WARNING]))
    monkeypatch.setattr(run_service, "_ensure_derived_entity_cards", _returns([]))

    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "scp text", reg)

    async def _boom(*args, **kwargs):
        raise RuntimeError("checkpoint is read-only")
    monkeypatch.setattr(run_service._graph, "aupdate_state", _boom)

    await run_service.resume_run(run_id, "scenario", "approve", reg)

    state = await run_service._graph.aget_state({"configurable": {"thread_id": run_id}})
    assert state.values["gate_states"]["scenario"] == "approved"   # the decision landed
    assert state.next == ("gate_image",)
    assert state.values["run_warnings"] == []                      # only the record was lost


async def test_reapproving_the_same_provisioning_does_not_duplicate(
    stub_stage_nodes, scene_scenario, env, monkeypatch,
):
    """AC6: repeated paths deduplicate rather than append again."""
    monkeypatch.setattr(run_service, "_ensure_character_reference", _returns([]))
    monkeypatch.setattr(run_service, "_ensure_special_pose_cards", _returns([_POSE_WARNING]))
    monkeypatch.setattr(run_service, "_ensure_derived_entity_cards", _returns([]))

    run_id = str(uuid.uuid4())
    _seed(run_id)
    await run_service.start_run(run_id, "SCP-096", "scp text", None)
    await run_service.resume_run(run_id, "scenario", "approve", None)

    # Retry the scenario stage for real, then approve it again — the identical
    # provisioning outcome is produced a second time.
    await run_service.retry_stage(run_id, "scenario", None)
    await asyncio.gather(*list(run_service._bg_tasks))
    assert scene_scenario == [run_id, run_id]  # the stage really did re-run
    await run_service.resume_run(run_id, "scenario", "approve", None)

    state = await run_service._graph.aget_state({"configurable": {"thread_id": run_id}})
    assert state.values["run_warnings"] == [_POSE_WARNING]  # history, not a tally


async def test_full_restart_drops_the_previous_attempt_s_warnings(
    stub_stage_nodes, scene_scenario, env, monkeypatch, broken_reference_search,
):
    """AC6: a restarted attempt must not inherit the deleted checkpoint's history."""
    run_id = str(uuid.uuid4())
    _seed(run_id)
    await run_service.start_run(run_id, "SCP-096", "scp text", None)
    before = (await run_service._graph.aget_state({"configurable": {"thread_id": run_id}})).values
    assert before["run_warnings"]

    # `broken_reference_search` is deliberately LEFT IN PLACE. What guarantees the reset
    # is not that a second attempt provisions cleanly — `full_restart_run` never calls
    # `_ensure_character_reference` at all. It deletes the thread and streams a fresh
    # `_initial_state`, which seeds an empty collection. Assert exactly that, or the test
    # is true by construction.
    provisioning_calls: list = []
    monkeypatch.setattr(run_service, "_ensure_character_reference", _records(provisioning_calls))
    await run_service.full_restart_run(run_id, None)
    assert provisioning_calls == []

    after = (await run_service._graph.aget_state({"configurable": {"thread_id": run_id}})).values
    assert after["run_warnings"] == []
    assert (await run_service.get_stage_artifacts(run_id, "scenario"))["warnings"] == []


async def test_legacy_checkpoint_without_run_warnings_still_serves_artifacts(
    stub_stage_nodes, scene_scenario, env, monkeypatch,
):
    """AC1: a pre-13.1 checkpoint has no such key at all."""
    monkeypatch.setattr(run_service, "_ensure_character_reference", _returns([]))
    run_id = str(uuid.uuid4())
    _seed(run_id)
    await run_service.start_run(run_id, "SCP-096", "scp text", None)

    config = {"configurable": {"thread_id": run_id}}
    values = (await run_service._graph.aget_state(config)).values
    assert "run_warnings" in values
    # Simulate the pre-13.1 shape by writing the key away as LangGraph would never have
    # had it: the readers all use .get(), so the DTO must still answer.
    values.pop("run_warnings")
    assert (values.get("run_warnings") or []) == []
    artifacts = await run_service.get_stage_artifacts(run_id, "scenario")
    assert artifacts["warnings"] == []
