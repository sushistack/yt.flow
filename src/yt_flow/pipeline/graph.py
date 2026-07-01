"""Compile the pipeline StateGraph with AsyncSqliteSaver. [AD-2, AD-7]

Fixed topology (Story 1.4 stub graph)::

    START -> scenario -> gate_scenario -> image -> gate_image -> tts
          -> gate_tts -> subtitle -> gate_subtitle -> video -> gate_video -> END

This module may import ``domain`` and sibling ``pipeline`` modules only; it must
never import ``db``, ``api``, or ``services``. [AD-1]
"""

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, StageName
from yt_flow.pipeline import gates, nodes
from yt_flow.pipeline.nodes import STAGES


# Gate routing after resume (AD-3): approved advances to the next stage; rejected
# terminates at the scenario gate, else loops back to the same stage node (retry).
_APPROVE_TARGET: dict[str, str] = dict(zip(STAGES, STAGES[1:])) | {STAGES[-1]: END}
_REJECT_TARGET: dict[str, str] = {STAGES[0]: END} | {s: s for s in STAGES[1:]}


def _route_after_gate(stage: StageName):
    def route(state: PipelineState) -> str:
        # gate node writes gate_states[stage] before this runs; map to a path-map key.
        return state["gate_states"].get(stage, "rejected")

    return route


def build_state_graph() -> StateGraph:
    """Build the uncompiled StateGraph with the fixed stage/gate topology.

    Each stage flows into its gate; the gate's conditional edges route on the
    resumed decision — ``approved`` → next stage, ``rejected`` → END (scenario)
    or the same stage node (retry loop). All 10 nodes are always present. [AD-3]
    """
    graph = StateGraph(PipelineState)
    for stage in STAGES:
        graph.add_node(stage, nodes.STAGE_NODES[stage])
        graph.add_node(f"gate_{stage}", gates.GATE_NODES[f"gate_{stage}"])

    graph.add_edge(START, STAGES[0])
    for stage in STAGES:
        graph.add_edge(stage, f"gate_{stage}")
        graph.add_conditional_edges(
            f"gate_{stage}",
            _route_after_gate(stage),
            {"approved": _APPROVE_TARGET[stage], "rejected": _REJECT_TARGET[stage]},
        )
    return graph


async def build_graph(settings: Settings) -> tuple[CompiledStateGraph, AsyncSqliteSaver]:
    """Compile the pipeline graph with an AsyncSqliteSaver on ``settings.db_path``.

    Returns the compiled graph and the saver. The caller owns the saver's SQLite
    connection lifetime and must ``await saver.conn.close()`` when done.
    """
    conn = await aiosqlite.connect(settings.db_path)
    try:
        saver = AsyncSqliteSaver(conn)
        await saver.setup()  # create checkpoint tables before first invocation
        graph = build_state_graph().compile(checkpointer=saver)
    except BaseException:
        await conn.close()  # don't leak the connection if setup/compile fails
        raise
    return graph, saver
