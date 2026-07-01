"""services/run_service.py — owns graph.astream(), DB sync, and SSE fan-out (AD-4).

The pipeline graph is injected once at app startup via ``configure()``. This layer
is the sole caller of ``graph.astream()``; ``api/routes/`` never touches LangGraph
directly. All ``runs``-table writes mirror LangGraph state *after* the corresponding
stream event — never before. [AD-1, AD-3, AD-4]
"""
import asyncio
import json
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException
from langfuse import get_client
from langgraph.graph import START
from langgraph.types import Command
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Run
from yt_flow.domain.state import PipelineState
from yt_flow.pipeline.graph import build_graph

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from yt_flow.api.sse import SSEQueueRegistry

_STAGES = ("scenario", "image", "tts", "subtitle", "video")
_ACTION_TO_DECISION = {"approve": "approved", "reject": "rejected"}
_RETRYABLE = frozenset({"approved", "rejected", "failed"})  # AC1 — retry preconditions
_EDITABLE = ("scenario", "subtitle")  # AD-8 — only these stages carry editable text
# Retry entry point (AD-9): to actually RE-RUN a stage node, aupdate_state must attribute
# the update to the stage's *predecessor* (START, else the prior gate). Using as_node=stage
# would resume at gate_<stage> and skip re-execution. Verified against the real graph.
_RETRY_ENTRY = {s: f"gate_{_STAGES[i - 1]}" for i, s in enumerate(_STAGES)}
_RETRY_ENTRY["scenario"] = START


def _settings() -> Settings:
    # ponytail: one seam so tests inject a fake workspace without a real .env.
    return Settings()


async def get_stage_artifacts(run_id: str, stage: str) -> dict:
    """Read per-stage artifact data from the LangGraph checkpoint (AD-2, AD-7).

    Read-only: only ``aget_state()``, never ``update_state()``/``astream()``.
    Raises ``ValueError`` for an unknown stage (→ 422) and ``LookupError`` when
    the run has no checkpoint or the stage has not been reached (→ 404).

    ponytail: restored verbatim during the 2.3↔2.5 parallel-branch reconciliation —
    Story 2.5's runs.py route depends on it; 2.3's run_service rewrite dropped it.
    """
    if stage not in _STAGES:
        raise ValueError(f"Unknown stage: {stage}")

    # ponytail: build a throwaway read-only graph per request; Story 2.3 will hold
    # a persistent graph in app.state once astream() execution is wired.
    graph, saver = await build_graph(Settings())
    try:
        state = await graph.aget_state({"configurable": {"thread_id": run_id}})
    finally:
        await saver.conn.close()

    values = state.values
    if not values:
        raise LookupError("Run not found")

    scenes = values.get("scenes") or []

    if stage == "scenario":
        if not scenes:
            raise LookupError("Stage not reached")
        return {"stage": "scenario", "scenes": [
            {
                "scene_num": s["scene_num"],
                "narration": s["narration"],
                "shots": [
                    {
                        "shot_id": sh["shot_id"],
                        "sentence_indices": sh["sentence_indices"],
                        "image_prompt": sh["image_prompt"],
                        "negative_prompt": sh["negative_prompt"],
                        "camera_angle": sh["camera_angle"],
                        "camera_movement": sh["camera_movement"],
                    }
                    for sh in s["shots"]
                ],
            }
            for s in scenes
        ]}

    if stage == "image":
        shots = [(s["scene_num"], sh) for s in scenes for sh in s["shots"]]
        if not shots or any(sh["image_path"] is None for _, sh in shots):
            raise LookupError("Stage not reached")
        return {"stage": "image", "images": [
            {"scene_num": n, "shot_id": sh["shot_id"], "image_path": sh["image_path"]}
            for n, sh in shots
        ]}

    if stage == "tts":
        if not scenes or any(s["audio_path"] is None for s in scenes):
            raise LookupError("Stage not reached")
        return {"stage": "tts", "audio": [
            {"scene_num": s["scene_num"], "audio_path": s["audio_path"],
             "duration_sec": s.get("audio_duration")}
            for s in scenes
        ]}

    if stage == "subtitle":
        if not scenes or any(s["subtitle_path"] is None for s in scenes):
            raise LookupError("Stage not reached")
        return {"stage": "subtitle", "subtitles": [
            {"scene_num": s["scene_num"], "subtitle_path": s["subtitle_path"]}
            for s in scenes
        ]}

    # stage == "video"
    video_path = values.get("video_path")
    if video_path is None:
        raise LookupError("Stage not reached")
    return {"stage": "video", "video_path": video_path}

# Injected compiled pipeline graph + per-run RunnableConfig (thread_id) for resume.
_graph: Any = None
_configs: dict[str, dict] = {}
# Strong refs to fire-and-forget background tasks — the event loop only keeps a weak
# ref, so without this a running resume/retry can be GC'd and silently cancelled.
_bg_tasks: set = set()


def spawn(coro) -> "asyncio.Task":
    """Schedule a background task and retain a strong reference until it finishes."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


class ABRunNotFoundError(ValueError):
    """The source run for Variant B creation does not exist."""


class ABRunConflictError(ValueError):
    """The source run cannot accept another Variant B run."""


def configure(graph: Any) -> None:
    """Inject a pre-built compiled pipeline graph (used by tests)."""
    global _graph
    _graph = graph


async def init(settings: "Settings") -> "AsyncSqliteSaver":
    """Build + store the long-lived pipeline graph; return its saver for lifespan cleanup.

    Called from the app lifespan. Keeps ``pipeline`` imports inside ``services`` so the
    ``api`` layer never depends on ``pipeline`` directly. [AD-1, AD-4]
    """
    graph, saver = await build_graph(settings)
    configure(graph)
    return saver


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _write_run(run_id: str, **fields: Any) -> None:
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)
        run.updated_at = _now()
        session.add(run)
        session.commit()


def _mirror_gate_state(run_id: str, stage: str, value: str) -> None:
    """Merge one stage's gate state into the runs-table JSON projection. [AD-2]"""
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        states = json.loads(run.gate_states) if run.gate_states else {}
        states[stage] = value
        run.gate_states = json.dumps(states)
        run.updated_at = _now()
        session.add(run)
        session.commit()


def _initial_state(run_id: str, scp_text: str, prompt_variant: Any = None) -> PipelineState:
    return {
        "run_id": run_id,
        "scp_text": scp_text,
        "scenes": [],
        "video_path": None,
        "current_stage": "scenario",
        "gate_states": {},
        "prompt_variant": prompt_variant,
        "error": None,
    }


_Event = Literal["stage_entry", "stage_exit", "gate_pending", "run_failed"]


async def _publish(sse_registry: "SSEQueueRegistry | None", run_id: str, event: _Event, data: dict) -> None:
    if sse_registry is not None:
        await sse_registry.publish(run_id, {"event": event, "data": data})


async def _consume(run_id: str, stream: Any, sse_registry: "SSEQueueRegistry | None") -> str:
    """Drive one astream() run to its next barrier.

    Returns ``"awaiting"`` (paused at a gate), ``"failed"`` (scenario gate rejected
    → END), or ``"completed"`` (stream reached END after final approval).
    """
    terminal_failed = False
    async for event in stream:  # stream_mode="updates": {node: update} | {"__interrupt__": (...)}
        if "__interrupt__" in event:
            stage = event["__interrupt__"][0].value["stage"]
            _write_run(run_id, status="awaiting_approval", current_stage=stage)
            _mirror_gate_state(run_id, stage, "pending")
            await _publish(sse_registry, run_id, "gate_pending", {"run_id": run_id, "stage": stage})
            return "awaiting"
        for node, update in event.items():
            if node in _STAGES:
                _write_run(run_id, status="running", current_stage=node)
                await _publish(sse_registry, run_id, "stage_entry", {"run_id": run_id, "stage": node})
                await _publish(sse_registry, run_id, "stage_exit", {"run_id": run_id, "stage": node})
            elif node.startswith("gate_"):
                stage = node[len("gate_"):]
                decision = (update or {}).get("gate_states", {}).get(stage)
                if decision:
                    _mirror_gate_state(run_id, stage, decision)
                    # Only the scenario gate routes to END on reject → terminal failure.
                    # Other gates loop back to their stage node and re-interrupt (retry).
                    if decision == "rejected" and stage == "scenario":
                        _write_run(run_id, status="failed", error="rejected at scenario gate")
                        await _publish(sse_registry, run_id, "run_failed",
                                       {"run_id": run_id, "stage": stage, "error": "rejected at scenario gate"})
                        terminal_failed = True
    if terminal_failed:
        _configs.pop(run_id, None)
        return "failed"
    _write_run(run_id, status="complete")
    _configs.pop(run_id, None)
    return "completed"


@contextmanager
def _trace_cm(run_id: str):
    """Enclosing span so every node ``@observe`` span nests under one Langfuse trace
    keyed by ``run_id`` (AC3). The trace id is deterministic via
    ``create_trace_id(seed=run_id)``, so initial, resumed, and restarted executions
    all attach to the same trace tree — no new root trace on resume (AC4).

    ponytail: the seed IS the storage — no ``trace_id`` field on PipelineState or the
    runs table; both pipeline and service recompute it from ``run_id``. Tracing is
    non-fatal (AD-10): setup *and* span enter/exit are guarded, so a Langfuse failure
    degrades to a no-op instead of escaping into the run's failure handler.
    """
    span = None
    try:
        client = get_client()
        span = client.start_as_current_observation(
            name="pipeline",
            as_type="chain",
            trace_context={"trace_id": client.create_trace_id(seed=run_id)},
        )
        span.__enter__()
    except Exception:  # noqa: BLE001 — tracing must never break the pipeline
        span = None
    try:
        yield
    finally:
        if span is not None:
            try:
                span.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 — nor on teardown
                pass


async def _run(run_id: str, stream: Any, sse_registry: "SSEQueueRegistry | None") -> None:
    try:
        with _trace_cm(run_id):
            await _consume(run_id, stream, sse_registry)
    except Exception as exc:  # AD-4: services catches astream() failures, marks failed, fans out.
        _configs.pop(run_id, None)
        _write_run(run_id, status="failed", error=str(exc))
        await _publish(sse_registry, run_id, "run_failed", {"run_id": run_id, "stage": "unknown", "error": str(exc)})


async def start_run(run_id: str, scp_text: str, sse_registry: "SSEQueueRegistry | None" = None,
                    prompt_variant: Any = None) -> None:
    """Kick off the pipeline: stream until the first gate interrupt (or terminal state).

    ``prompt_variant`` seeds the run's PipelineState — ``"B"`` for an A/B Variant B run
    (Story 4.1), ``None`` for a standard run.
    """
    config = {"configurable": {"thread_id": run_id}}
    _configs[run_id] = config
    await _run(run_id, _graph.astream(_initial_state(run_id, scp_text, prompt_variant), config,
                                      stream_mode="updates"), sse_registry)


async def create_ab_run(source_run_id: str, sse_registry: "SSEQueueRegistry | None" = None) -> str:
    """Create Variant B: a second independent run sharing the source's SCP input (AD-6).

    The runs table stores only ``scp_id``, so the full ``scp_text`` is recovered from the
    source run's LangGraph checkpoint. Inserts a linked ``Run`` row (``prompt_variant="B"``,
    ``ab_pair_id=source_run_id``) and launches it through the standard ``start_run`` driver —
    no graph-level branching. The source run's existence/completeness is validated by the
    route before this is called. Returns the new run id.
    """
    new_id = str(uuid.uuid4())
    with Session(db._engine) as session:
        source = session.get(Run, source_run_id)
        if source is None:
            raise ABRunNotFoundError("Run not found")
        if source.status != "complete":
            raise ABRunConflictError("Cannot create A/B run: source run is not complete")
        if source.ab_pair_id is not None or source.prompt_variant == "B":
            raise ABRunConflictError("Cannot create A/B run from a variant run")
        if session.exec(select(Run).where(Run.ab_pair_id == source_run_id)).first() is not None:
            raise ABRunConflictError("A/B pair already exists for this run")
    snap = await _graph.aget_state({"configurable": {"thread_id": source_run_id}})
    scp_text = (snap.values or {}).get("scp_text")
    if not scp_text:
        raise ValueError(f"Source run {source_run_id} has no scp_text in its checkpoint")
    with Session(db._engine) as session:
        try:
            session.add(Run(id=new_id, scp_id=source.scp_id, status="running",
                            prompt_variant="B", ab_pair_id=source_run_id))
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ABRunConflictError("A/B pair already exists for this run") from exc
    spawn(start_run(new_id, scp_text, sse_registry, prompt_variant="B"))
    return new_id


async def resume_run(run_id: str, stage: str, action: str, sse_registry: "SSEQueueRegistry | None" = None) -> None:
    """Resume a gated run with an approve/reject decision. [AD-3, AD-4]

    ``stage`` identifies which gate the client acted on; LangGraph resumes the single
    pending interrupt on this run's thread, so it is carried for traceability only.
    """
    config = _configs.get(run_id, {"configurable": {"thread_id": run_id}})
    decision = _ACTION_TO_DECISION.get(action, action)
    await _run(run_id, _graph.astream(Command(resume=decision), config, stream_mode="updates"), sse_registry)


# ── Failure recovery: resume from checkpoint & explicit full restart (Story 1.10) ──


async def resume_run_from_failure(run_id: str, sse_registry: "SSEQueueRegistry | None" = None) -> None:
    """Resume a failed run from its last checkpoint without re-running completed nodes.

    LangGraph replays from the latest checkpoint for this thread when invoked with a
    ``None`` input, so a run that failed after ``scenario`` resumes at ``image`` and
    ``scenario`` is not re-executed. [AC1, FR-7] Distinct from ``resume_run``, which
    feeds an approve/reject decision into a pending gate interrupt.
    """
    config = _configs.get(run_id) or {"configurable": {"thread_id": run_id}}
    _configs[run_id] = config
    _write_run(run_id, status="running", error=None)
    await _run(run_id, _graph.astream(None, config, stream_mode="updates"), sse_registry)


async def full_restart_run(run_id: str, sse_registry: "SSEQueueRegistry | None" = None) -> None:
    """Restart a run from ``scenario``, disregarding any existing checkpoint. [AC2, FR-8]

    Explicit at the service boundary so no caller can silently get resume behavior.
    Strategy: wipe the thread's checkpoints, then stream a fresh initial state on the
    *same* ``run_id`` thread — the operator-facing run id stays stable and its trace
    (deterministic from ``run_id``) stays coherent. The fresh initial state resets
    ``scenes``, ``video_path``, per-stage artifact paths, ``error``, and ``gate_states``,
    so no stale paths survive. ``scp_text`` is recovered from the prior checkpoint.
    """
    config = {"configurable": {"thread_id": run_id}}
    snap = await _graph.aget_state(config)
    scp_text = (snap.values or {}).get("scp_text", "")
    ckpt = _graph.checkpointer
    if ckpt is not None:
        await ckpt.adelete_thread(run_id)  # drop prior successful checkpoints → START from scenario
    _configs[run_id] = config
    _write_run(run_id, status="running", current_stage="scenario", error=None, gate_states="{}")
    await _run(run_id, _graph.astream(_initial_state(run_id, scp_text), config, stream_mode="updates"), sse_registry)


# ── Stage control: retry & inline artifact edit (Story 2.4) ────────────────────


def _nullify(stage: str, scenes: list) -> dict:
    """Checkpoint update that zeroes `stage` + all downstream outputs (AD-9 cascade)."""
    i = _STAGES.index(stage)
    if stage == "scenario":  # scenes carry every downstream artifact → wipe wholesale
        return {"scenes": [], "video_path": None}
    new = deepcopy(scenes)
    for scene in new:
        if i <= 1:  # image + downstream
            for shot in scene.get("shots", []):
                shot["image_path"] = shot["background_path"] = shot["character_path"] = None
        if i <= 2:  # tts + downstream
            scene["audio_path"] = None
            scene["audio_duration"] = None
            scene["word_timings"] = []
        if i <= 3:  # subtitle + downstream
            scene["subtitle_path"] = None
    return {"scenes": new, "video_path": None}


def _reset_gates(gate_states: dict, stage: str) -> dict:
    """Reset the retried stage + downstream gates to 'pending' (AD-9)."""
    out = dict(gate_states or {})
    for s in _STAGES[_STAGES.index(stage):]:
        out[s] = "pending"
    return out


async def retry_stage(run_id: str, stage: str, sse_registry: "SSEQueueRegistry | None" = None) -> dict:
    """Re-execute one stage: nullify its (+downstream) outputs, then re-invoke the graph (AD-9).

    Returns the 202 body; astream re-execution runs in the background via ``_run``.
    """
    if stage not in _STAGES:
        raise HTTPException(status_code=404, detail="Unknown stage")
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        gate_states = json.loads(run.gate_states) if run.gate_states else {}
    current = gate_states.get(stage)
    if current not in _RETRYABLE:
        raise HTTPException(
            status_code=409,
            detail=(f"Cannot retry stage {stage!r}: gate state is {current!r}. "
                    "Stage must be approved, rejected, or failed to retry."),
        )
    config = _configs.get(run_id, {"configurable": {"thread_id": run_id}})
    snap = await _graph.aget_state(config)
    values = snap.values or {}
    update = _nullify(stage, values.get("scenes") or [])
    update["gate_states"] = _reset_gates(values.get("gate_states") or {}, stage)
    # Attribute the update to the stage's predecessor so astream(None) re-runs the stage
    # node itself, not just its gate (AD-9). See _RETRY_ENTRY.
    await _graph.aupdate_state(config, update, as_node=_RETRY_ENTRY[stage])
    _write_run(run_id, status="running", current_stage=stage, error=None,
               gate_states=json.dumps(_reset_gates(gate_states, stage)))
    await _publish(sse_registry, run_id, "stage_entry", {"run_id": run_id, "stage": stage})
    _configs[run_id] = config
    spawn(_run(run_id, _graph.astream(None, config, stream_mode="updates"), sse_registry))
    return {
        "run_id": run_id, "stage": stage, "status": "retrying",
        "message": "Stage retry initiated — stage_entry SSE event will confirm execution start",
    }


async def edit_artifact(run_id: str, stage: str, body: str, scene_num: int = 1) -> dict:
    """Edit a text artifact for scenario/subtitle: persist to checkpoint + rewrite file (AD-8).

    Does NOT re-run the stage. ``scene_num`` (1-based) selects which scene's artifact to
    edit; defaults to the first scene.
    """
    if stage not in _EDITABLE:
        raise HTTPException(
            status_code=422,
            detail="Artifact editing is only supported for scenario and subtitle stages",
        )
    with Session(db._engine) as session:
        if session.get(Run, run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")
    config = _configs.get(run_id, {"configurable": {"thread_id": run_id}})
    snap = await _graph.aget_state(config)
    scenes = deepcopy((snap.values or {}).get("scenes") or [])
    target = next((sc for sc in scenes if sc.get("scene_num") == scene_num), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Stage artifact not found (stage not yet run)")
    if stage == "scenario":
        target["narration"] = body
        path = Path(_settings().workspace_path) / run_id / "scenario" / f"scene_{scene_num:03d}.txt"
    else:  # subtitle — the SRT text lives on disk; state only holds subtitle_path
        sp = target.get("subtitle_path")
        if not sp:
            raise HTTPException(status_code=404, detail="Stage artifact not found (stage not yet run)")
        path = Path(sp)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    if stage == "subtitle":
        target["subtitle_path"] = str(path)
    await _graph.aupdate_state(config, {"scenes": scenes}, as_node=stage)
    return {
        "run_id": run_id, "stage": stage, "updated": True,
        "message": "Artifact updated in checkpoint and on disk",
    }
