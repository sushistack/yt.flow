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
from yt_flow.domain.state import PipelineState
from yt_flow.pipeline import gates, nodes
from yt_flow.pipeline.nodes import STAGES


def build_state_graph() -> StateGraph:
    """Build the uncompiled StateGraph with the fixed stage/gate topology."""
    graph = StateGraph(PipelineState)

    # Interleave stage and gate nodes: scenario, gate_scenario, image, gate_image, ...
    sequence: list[str] = []
    for stage in STAGES:
        gate = f"gate_{stage}"
        graph.add_node(stage, nodes.STAGE_NODES[stage])
        graph.add_node(gate, gates.GATE_NODES[gate])
        sequence += [stage, gate]

    graph.add_edge(START, sequence[0])
    for src, dst in zip(sequence, sequence[1:]):
        graph.add_edge(src, dst)
    graph.add_edge(sequence[-1], END)
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
