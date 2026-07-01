"""Gate nodes — human-in-the-loop approval via LangGraph interrupts. [AD-3]

Gate nodes are separate StateGraph nodes from the stage nodes. Each calls
``interrupt({"stage": stage})`` to pause the graph (state is persisted by the
checkpointer) and, on resume, records the decision in a flat ``gate_states``
dict. Gates never touch DB, queues, or service state. [AD-3, AD-4]
"""

from langgraph.types import interrupt

from yt_flow.domain.state import GateState, PipelineState, StageName

GATE_DECISIONS: tuple[GateState, ...] = ("approved", "rejected")


def _gate(stage: StageName):
    def node(state: PipelineState) -> dict:
        # ponytail: AD-3 also asks for a `pending` gate_states write on interrupt entry,
        # but LangGraph discards a node's return when interrupt() pauses (the node re-runs
        # from the top on resume), so a single gate node cannot both pause AND persist
        # `pending`. Making `pending` observable requires a pre-gate writer (e.g. the stage
        # node) — an architecture reconciliation deferred to the story that consumes
        # gate_states. No consumer exists in this stub. [see deferred-work.md]
        decision = interrupt({"stage": stage})
        if decision not in GATE_DECISIONS:
            raise ValueError(
                f"gate {stage}: expected one of {GATE_DECISIONS}, got {decision!r}"
            )
        # Merge manually: gate_states has no reducer, so return the full updated dict.
        return {"gate_states": {**state["gate_states"], stage: decision}}

    node.__name__ = f"gate_{stage}"
    return node


gate_scenario = _gate("scenario")
gate_image = _gate("image")
gate_tts = _gate("tts")
gate_subtitle = _gate("subtitle")
gate_video = _gate("video")

GATE_NODES = {f"gate_{s}": globals()[f"gate_{s}"] for s in ("scenario", "image", "tts", "subtitle", "video")}
