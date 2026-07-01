"""Story 1.4 — LangGraph graph topology + AsyncSqliteSaver checkpointing.

Covers AC1 (DB file created), AC2 (10 nodes in fixed order), AC3 (checkpoint
persisted after a stub stage). No real external calls are exercised. [AD-2, AD-7]
"""

import uuid

import pytest

from yt_flow.config import Settings
from yt_flow.pipeline import nodes
from yt_flow.pipeline.graph import STAGES, build_graph, build_state_graph

EXPECTED_NODES = [
    "scenario",
    "gate_scenario",
    "image",
    "gate_image",
    "tts",
    "gate_tts",
    "subtitle",
    "gate_subtitle",
    "video",
    "gate_video",
]


def _settings(tmp_path) -> Settings:
    # Explicit values so the test never depends on a real .env being present.
    return Settings(
        langfuse_host="http://localhost",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        db_path=str(tmp_path / "yt_flow.db"),
    )


def _minimal_state(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "scp_text": "SCP test text",
        "scenes": [],
        "video_path": None,
        "current_stage": "",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }


async def test_build_graph_creates_sqlite_file(tmp_path):
    settings = _settings(tmp_path)
    db_file = tmp_path / "yt_flow.db"
    assert not db_file.exists()

    graph, saver = await build_graph(settings)
    try:
        assert db_file.exists()  # AC1: real file, not :memory:
    finally:
        await saver.conn.close()


def test_graph_contains_expected_nodes():
    # AC2: inspect compiled graph node set (no checkpointer needed for topology).
    graph = build_state_graph().compile()
    node_names = set(graph.get_graph().nodes)
    for name in EXPECTED_NODES:
        assert name in node_names, f"missing node: {name}"
    assert len([n for n in EXPECTED_NODES if n in node_names]) == 10


def test_graph_edges_follow_fixed_topology():
    # AC2: edges wire scenario -> gate_scenario -> image -> ... -> gate_video.
    drawable = build_state_graph().compile().get_graph()
    edge_pairs = {(e.source, e.target) for e in drawable.edges}
    for a, b in zip(EXPECTED_NODES, EXPECTED_NODES[1:]):
        assert (a, b) in edge_pairs, f"missing edge {a} -> {b}"


async def test_stub_stage_persists_checkpoint(tmp_path):
    # AC3 / FR-36: after the first stub stage runs, a checkpoint exists.
    settings = _settings(tmp_path)
    graph, saver = await build_graph(settings)
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        # scenario runs, then gate_scenario interrupts — execution pauses with state saved.
        result = await graph.ainvoke(_minimal_state(run_id), config)
        assert "__interrupt__" in result  # paused at first gate
        checkpoint = await saver.aget_tuple(config)
        assert checkpoint is not None
        assert checkpoint.checkpoint["channel_values"]["current_stage"] == "scenario"
    finally:
        await saver.conn.close()


async def test_gate_resume_records_decision(tmp_path):
    from langgraph.types import Command

    settings = _settings(tmp_path)
    graph, saver = await build_graph(settings)
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke(_minimal_state(run_id), config)  # pause at gate_scenario
        await graph.ainvoke(Command(resume="approved"), config)  # advances to gate_image
        checkpoint = await saver.aget_tuple(config)
        gate_states = checkpoint.checkpoint["channel_values"]["gate_states"]
        assert gate_states["scenario"] == "approved"
    finally:
        await saver.conn.close()


async def test_gate_rejects_invalid_decision(tmp_path):
    # Gate accepts only approved/rejected; resuming with anything else is a hard error.
    from langgraph.types import Command

    settings = _settings(tmp_path)
    graph, saver = await build_graph(settings)
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke(_minimal_state(run_id), config)  # pause at gate_scenario
        with pytest.raises(ValueError, match="approved"):
            await graph.ainvoke(Command(resume="maybe"), config)
    finally:
        await saver.conn.close()


def test_stage_nodes_return_current_stage_without_mutating_input():
    for stage in STAGES:
        state = _minimal_state(str(uuid.uuid4()))
        snapshot = dict(state)
        update = nodes.STAGE_NODES[stage](state)
        assert update == {"current_stage": stage}
        assert state == snapshot  # input not mutated in place [AD-4]
