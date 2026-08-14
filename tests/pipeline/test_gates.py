"""Story 2.3 — gate node interrupts + conditional approved/rejected routing. [AD-3]

Exercises the compiled graph directly with an AsyncSqliteSaver checkpointer:
  - approved advances to the next stage's gate,
  - scenario reject routes to END (terminate),
  - non-scenario reject loops back to the same stage and re-interrupts (retry).
"""

import json
import uuid

import pytest
from langgraph.types import Command

from yt_flow.config import Settings
from yt_flow.pipeline import gates, nodes
from yt_flow.pipeline.graph import build_graph
from yt_flow.services import run_service

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

async def test_first_gate_interrupts_after_scenario(tmp_path, stub_stage_nodes):
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        result = await graph.ainvoke(_state(run_id), config)
        assert "__interrupt__" in result  # paused at gate_scenario
        assert result["__interrupt__"][0].value == {"stage": "scenario"}
    finally:
        await saver.conn.close()


async def test_approved_advances_to_next_gate(tmp_path, stub_stage_nodes):
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


async def test_scenario_reject_routes_to_end(tmp_path, stub_stage_nodes):
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


async def test_image_reject_loops_back_and_reinterrupts(tmp_path, stub_stage_nodes):
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


async def test_all_approved_reaches_end(tmp_path, stub_stage_nodes):
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


async def test_retry_reruns_stage_node(tmp_path, monkeypatch, stub_stage_nodes):
    """AD-9 regression: retry must RE-RUN the stage node, not just re-hit its gate.

    Attributing the checkpoint update to the stage itself (as_node=stage) would resume
    at gate_<stage> and skip re-execution. run_service uses _RETRY_ENTRY (the stage's
    predecessor) precisely so the node runs again. Instrument the real image node and
    prove it executes a second time after a retry.
    """
    ran: list[str] = []

    def counting_image(state):
        ran.append("image")
        return {"current_stage": "image"}

    monkeypatch.setitem(nodes.STAGE_NODES, "image", counting_image)

    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke(_state(run_id), config)              # pause at scenario
        await graph.ainvoke(Command(resume="approved"), config)  # run image, pause at gate_image
        assert ran == ["image"]                                   # image ran once

        # Simulate run_service.retry_stage's checkpoint rewind for "image".
        snap = await graph.aget_state(config)
        update = {"scenes": [], "video_path": None,
                  "gate_states": {**snap.values["gate_states"], "image": "pending"}}
        await graph.aupdate_state(config, update, as_node=run_service._RETRY_ENTRY["image"])
        result = await graph.ainvoke(None, config)               # resume from predecessor

        assert ran == ["image", "image"]                          # image RE-RAN (the fix)
        assert "__interrupt__" in result
        assert result["__interrupt__"][0].value == {"stage": "image"}  # paused at gate_image again
    finally:
        await saver.conn.close()


# ── Story 12.3: scenario gate carries the pass-2 quality verdict ──────────────

_QUALITY = {
    "final_pass_index": 2,
    "retry_scope": "scene",
    "review_overall_pass": False,
    "critic_verdict": "retry",
    "critic_feedback": "장면 2가 아직 늘어집니다",
    "rule_metrics": {
        "aggregate": {"character_count": 120, "sentence_count": 8,
                      "duplicate_sentence_count": 1, "repeated_4gram_count": 0},
        "scenes": [], "repeated_ngrams": [], "slop_phrase_hits": [], "slop_vocabulary_version": 1,
    },
    "grounded_contradictions": [],
    "review_issues": [],
    "warning": {"code": "unresolved_pass2", "message": "확인 후 승인하세요"},
}


async def test_scenario_gate_interrupt_carries_quality(tmp_path, stub_stage_nodes):
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        result = await graph.ainvoke({**_state(run_id), "scenario_quality": _QUALITY}, config)
        value = result["__interrupt__"][0].value
        assert value["stage"] == "scenario"
        assert value["scenario_quality"]["warning"]["code"] == "unresolved_pass2"
    finally:
        await saver.conn.close()


async def test_other_gates_stay_stage_only_even_with_quality_in_state(tmp_path, stub_stage_nodes):
    """Backward compatibility: only the scenario interrupt value grew (AC6)."""
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke({**_state(run_id), "scenario_quality": _QUALITY}, config)
        result = await graph.ainvoke(Command(resume="approved"), config)
        assert result["__interrupt__"][0].value == {"stage": "image"}
    finally:
        await saver.conn.close()


async def test_scenario_gate_omits_quality_key_when_absent(tmp_path, stub_stage_nodes):
    """A pre-12.3 checkpoint has no such field — the payload must stay byte-identical."""
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        result = await graph.ainvoke(_state(run_id), config)
        assert result["__interrupt__"][0].value == {"stage": "scenario"}
    finally:
        await saver.conn.close()


async def test_scenario_gate_omits_quality_key_when_cleared(tmp_path, stub_stage_nodes):
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        result = await graph.ainvoke({**_state(run_id), "scenario_quality": None}, config)
        assert result["__interrupt__"][0].value == {"stage": "scenario"}
    finally:
        await saver.conn.close()


async def test_quality_does_not_change_decision_validation(tmp_path, stub_stage_nodes):
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke({**_state(run_id), "scenario_quality": _QUALITY}, config)
        with pytest.raises(ValueError, match="expected one of"):
            await graph.ainvoke(Command(resume="maybe"), config)
    finally:
        await saver.conn.close()


# ── Story 13.1: every gate carries the run's degradation history ──────────────

_WARNINGS = [
    {"code": "stock_plate_missing", "stage": "image",
     "message": "승인된 스톡 배경이 없어 배경을 생성했습니다",
     "context": {"scene_num": 3, "shot_id": "S002", "location_key": "corridor"}},
    {"code": "subtitle_alignment_fallback", "stage": "subtitle",
     "message": "WhisperX 정렬에 실패해 임시 단어 타이밍으로 자막을 만들었습니다",
     "context": {"scene_num": 1}},
]


async def test_gate_interrupt_carries_warnings_and_count(tmp_path, stub_stage_nodes):
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        result = await graph.ainvoke({**_state(run_id), "run_warnings": _WARNINGS}, config)
        value = result["__interrupt__"][0].value
        assert value["stage"] == "scenario"
        assert value["warning_count"] == 2
        assert value["warnings"] == _WARNINGS          # order preserved, contexts intact
        json.dumps(value)                               # interrupt payloads must serialize
    finally:
        await saver.conn.close()


async def test_downstream_gates_carry_warnings_too(tmp_path, stub_stage_nodes):
    """Provisioning warnings are written AFTER the scenario gate resumes, so the image
    gate is the first place an operator can see them — run-wide, not stage-filtered."""
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke({**_state(run_id), "run_warnings": _WARNINGS}, config)
        result = await graph.ainvoke(Command(resume="approved"), config)
        value = result["__interrupt__"][0].value
        assert value["stage"] == "image"
        assert value["warning_count"] == 2
    finally:
        await saver.conn.close()


async def test_scenario_gate_carries_quality_and_warnings_together(tmp_path, stub_stage_nodes):
    """Additive, not exclusive: 12.3's contract and 13.1's are parallel (AC4)."""
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        result = await graph.ainvoke(
            {**_state(run_id), "scenario_quality": _QUALITY, "run_warnings": _WARNINGS}, config,
        )
        value = result["__interrupt__"][0].value
        assert value["scenario_quality"]["warning"]["code"] == "unresolved_pass2"
        assert value["warning_count"] == 2
    finally:
        await saver.conn.close()


@pytest.mark.parametrize("warnings", [None, []])
async def test_clean_run_gate_payload_is_byte_identical(tmp_path, stub_stage_nodes, warnings):
    """A pre-13.1 checkpoint (no key) and a clean run (empty list) both stay unchanged."""
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    state = _state(run_id) if warnings is None else {**_state(run_id), "run_warnings": warnings}
    try:
        result = await graph.ainvoke(state, config)
        assert result["__interrupt__"][0].value == {"stage": "scenario"}
    finally:
        await saver.conn.close()


async def test_gate_does_not_write_warnings(tmp_path, stub_stage_nodes):
    """The gate only READS persisted warnings — it re-runs from the top on resume, so a
    write here would double every record (AC4)."""
    graph, saver = await build_graph(_settings(tmp_path))
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    try:
        await graph.ainvoke({**_state(run_id), "run_warnings": _WARNINGS}, config)
        result = await graph.ainvoke(Command(resume="approved"), config)
        assert result["run_warnings"] == _WARNINGS
    finally:
        await saver.conn.close()
