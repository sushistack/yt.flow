"""Story 2.3 — gate node interrupts + conditional approved/rejected routing. [AD-3]

Exercises the compiled graph directly with an AsyncSqliteSaver checkpointer:
  - approved advances to the next stage's gate,
  - scenario reject routes to END (terminate),
  - non-scenario reject loops back to the same stage and re-interrupts (retry).
"""

import uuid

import pytest
from langgraph.types import Command

from yt_flow.config import Settings
from yt_flow.pipeline import gates
from yt_flow.pipeline.graph import build_graph

_ALL = ("scenario", "image", "tts", "subtitle", "video")


def _settings(tmp_path) -> Settings:
    return Settings(
        langfuse_host="http://localhost",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        db_path=str(tmp_path / "gate.db"),
    )


def _state(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "scp_text": "SCP text",
        "scenes": [],
        "video_path": None,
        "current_stage": "scenario",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }


# ── Gate node isolation ────────────────────────────────────────────────────

def test_gate_node_calls_interrupt():
    # A gate node's first act is interrupt(), which needs a runnable context —
    # calling it bare proves the interrupt() call is on the gate's happy path.
    with pytest.raises(RuntimeError, match="runnable context"):
        gates.gate_scenario(_state(str(uuid.uuid4())))


def test_all_five_gate_nodes_registered():
    assert set(gates.GATE_NODES) == {f"gate_{s}" for s in _ALL}


# ── Conditional routing (integration) ───────────────────────────────────────

async def test_first_gate_interrupts_after_scenario(tmp_path):
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        result = await graph.ainvoke(_state(run_id), config)
        assert "__interrupt__" in result  # paused at gate_scenario
        assert result["__interrupt__"][0].value == {"stage": "scenario"}
    finally:
        await saver.conn.close()


async def test_approved_advances_to_next_gate(tmp_path):
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke(_state(run_id), config)              # pause at scenario
        result = await graph.ainvoke(Command(resume="approved"), config)
        assert result["gate_states"]["scenario"] == "approved"
        assert "__interrupt__" in result                          # now paused at gate_image
        assert result["__interrupt__"][0].value == {"stage": "image"}
    finally:
        await saver.conn.close()


async def test_scenario_reject_routes_to_end(tmp_path):
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke(_state(run_id), config)              # pause at scenario
        result = await graph.ainvoke(Command(resume="rejected"), config)
        assert result["gate_states"]["scenario"] == "rejected"
        assert "__interrupt__" not in result                      # terminated at END
    finally:
        await saver.conn.close()


async def test_image_reject_loops_back_and_reinterrupts(tmp_path):
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke(_state(run_id), config)              # pause at scenario
        await graph.ainvoke(Command(resume="approved"), config)  # pause at image
        result = await graph.ainvoke(Command(resume="rejected"), config)
        # rejected image → route back to image node → gate_image interrupts again
        assert "__interrupt__" in result
        assert result["__interrupt__"][0].value == {"stage": "image"}
    finally:
        await saver.conn.close()


async def test_all_approved_reaches_end(tmp_path):
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke(_state(run_id), config)              # pause at scenario
        result = None
        for _ in _ALL:                                            # approve all 5 gates
            result = await graph.ainvoke(Command(resume="approved"), config)
        assert "__interrupt__" not in result                      # reached END
        assert all(result["gate_states"][s] == "approved" for s in _ALL)
    finally:
        await saver.conn.close()
