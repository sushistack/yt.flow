"""services/run_service.py — owns graph.astream(), DB sync, and SSE fan-out (AD-4).

The pipeline graph is injected once at app startup via ``configure()``. This layer
is the sole caller of ``graph.astream()``; ``api/routes/`` never touches LangGraph
directly. All ``runs``-table writes mirror LangGraph state *after* the corresponding
stream event — never before. [AD-1, AD-3, AD-4]
"""
import asyncio
import json
import logging
import re
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException
from yt_flow.observability import get_client
from langgraph.graph import START
from langgraph.types import Command
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Run
from yt_flow.domain.state import PipelineState
from yt_flow.pipeline.graph import build_graph
from yt_flow.services import comfyui_client, eval_service
from yt_flow.services.asset_service import AssetService
from yt_flow.services.character_service import CANONICAL_ANGLES, CharacterService, pose_hint_key

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from yt_flow.api.sse import SSEQueueRegistry

logger = logging.getLogger(__name__)

_STAGES = ("scenario", "image", "tts", "subtitle", "video")
_ACTION_TO_DECISION = {"approve": "approved", "reject": "rejected"}
_RETRYABLE = frozenset({"approved", "rejected", "failed"})  # AC1 — retry preconditions
# B-1: retry/edit may mutate the checkpoint only from a settled run status; a live
# ("running"/"pending") run's checkpoint must not be touched (R-009 concurrency guard).
_MUTABLE_STATES = frozenset({"awaiting_approval", "failed", "complete"})
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

    Reuses the long-lived graph injected by ``init()`` (AD-7) — no per-request
    graph/connection churn.
    """
    if stage not in _STAGES:
        raise ValueError(f"Unknown stage: {stage}")

    state = await _graph.aget_state({"configurable": {"thread_id": run_id}})
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
                "display_narration": s.get("display_narration") or s["narration"],
                "mood": s.get("mood"),
                "title": s.get("title", ""),
                "kicker": s.get("kicker", ""),
                "shots": [
                    {
                        "shot_id": sh["shot_id"],
                        "sentence_indices": sh["sentence_indices"],
                        "image_prompt": sh["image_prompt"],
                        "negative_prompt": sh["negative_prompt"],
                        "camera_angle": sh["camera_angle"],
                        "camera_movement": sh["camera_movement"],
                        "cast": sh.get("cast", []),
                        "location_key": sh.get("location_key"),
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
    result: dict = {"stage": "video", "video_path": video_path}
    # ending_credit_error is only present in the checkpoint when cc_attribution
    # was on for this run (Story 5.20 AC:6) — its presence, not its value, is
    # the attempted/not-attempted signal.
    if "ending_credit_error" in values:
        result["ending_credit"] = values["ending_credit_error"] is None
        result["ending_credit_error"] = values["ending_credit_error"]
        result["description_txt_path"] = str(Path(_settings().workspace_path) / run_id / "description.txt")
    return result

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


def _initial_state(run_id: str, scp_id: str, scp_text: str, prompt_variant: Any = None) -> PipelineState:
    return {
        "run_id": run_id,
        "scp_id": scp_id,
        "scp_text": scp_text,
        "scenes": [],
        "video_path": None,
        "current_stage": "scenario",
        "gate_states": {},
        "prompt_variant": prompt_variant,
        "error": None,
    }


_Event = Literal["stage_entry", "stage_exit", "gate_pending", "run_failed"]

# LangGraph attaches `During task with name '<node>' and id '<uuid>'` as an exception
# note (PEP 678) when a node raises inside astream(). This is the only place the
# failing node's identity survives past the generic astream() exception (FR-13).
_TASK_NAME_RE = re.compile(r"During task with name '([^']+)'")


def _stage_from_exception(exc: BaseException) -> str:
    for note in getattr(exc, "__notes__", None) or ():
        if m := _TASK_NAME_RE.search(note):
            return m.group(1)
    return "unknown"


async def _publish(sse_registry: "SSEQueueRegistry | None", run_id: str, event: _Event, data: dict) -> None:
    if sse_registry is not None:
        await sse_registry.publish(run_id, {"event": event, "data": data})


async def _consume(run_id: str, stream: Any, sse_registry: "SSEQueueRegistry | None") -> str:
    """Drive one astream() run to its next barrier.

    Returns ``"awaiting"`` (paused at a gate), ``"failed"`` (scenario gate rejected
    → END), or ``"completed"`` (stream reached END after final approval).

    ``_write_run``/``_mirror_gate_state`` run via ``asyncio.to_thread``: they're
    synchronous sqlite3 writes to the same file the checkpointer's async connection
    writes to (AD-7); calling them inline blocked the event loop while holding the
    write lock, starving the checkpointer's writes into "database is locked" (found
    running the real app end-to-end — pytest's decoupled test DBs never hit this).
    Every ``_write_run`` call that precedes/follows an ``astream()`` invocation
    (here, plus ``resume_run_from_failure``, ``full_restart_run``, ``retry_stage``)
    needs the same wrapping — an unwrapped one anywhere still blocks the loop.
    """
    terminal_failed = False
    async for event in stream:  # stream_mode="updates": {node: update} | {"__interrupt__": (...)}
        if "__interrupt__" in event:
            stage = event["__interrupt__"][0].value["stage"]
            await asyncio.to_thread(_write_run, run_id, status="awaiting_approval", current_stage=stage)
            await asyncio.to_thread(_mirror_gate_state, run_id, stage, "pending")
            await _publish(sse_registry, run_id, "gate_pending", {"run_id": run_id, "stage": stage})
            return "awaiting"
        for node, update in event.items():
            if node in _STAGES:
                stage_error = (update or {}).get("error")
                if stage_error:
                    # Stage node caught its own failure and set state["error"] (AD-4);
                    # the graph routes it to END, so mark failed + retryable here —
                    # never leave the run looking like a normal pending gate. [live bug 2026-07-03]
                    await asyncio.to_thread(_write_run, run_id, status="failed",
                                            error=stage_error, current_stage=node)
                    await asyncio.to_thread(_mirror_gate_state, run_id, node, "failed")
                    await _publish(sse_registry, run_id, "run_failed",
                                   {"run_id": run_id, "stage": node, "error": stage_error})
                    terminal_failed = True
                    continue
                await asyncio.to_thread(_write_run, run_id, status="running", current_stage=node)
                await _publish(sse_registry, run_id, "stage_entry", {"run_id": run_id, "stage": node})
                await _publish(sse_registry, run_id, "stage_exit", {"run_id": run_id, "stage": node})
            elif node.startswith("gate_"):
                stage = node[len("gate_"):]
                decision = (update or {}).get("gate_states", {}).get(stage)
                if decision:
                    await asyncio.to_thread(_mirror_gate_state, run_id, stage, decision)
                    # Only the scenario gate routes to END on reject → terminal failure.
                    # Other gates loop back to their stage node and re-interrupt (retry).
                    if decision == "rejected" and stage == "scenario":
                        await asyncio.to_thread(_write_run, run_id, status="failed", error="rejected at scenario gate")
                        await _publish(sse_registry, run_id, "run_failed",
                                       {"run_id": run_id, "stage": stage, "error": "rejected at scenario gate"})
                        terminal_failed = True
    if terminal_failed:
        _configs.pop(run_id, None)
        return "failed"
    await asyncio.to_thread(_write_run, run_id, status="complete")
    await _trigger_ab_eval_if_variant_b(run_id)
    _configs.pop(run_id, None)
    return "completed"


def _get_run_ab_fields(run_id: str) -> "tuple[str | None, str | None]":
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        return (run.prompt_variant, run.ab_pair_id) if run is not None else (None, None)


async def _trigger_ab_eval_if_variant_b(run_id: str) -> None:
    """Fire ``evaluate_ab()`` once a Variant B run completes (Story 4.2/4.3 wiring).

    Variant B is the second half of an A/B pair (``ab_pair_id`` = source run's id,
    Story 4.1's ``create_ab_run``), so its completion is the moment the pair is
    whole. Fire-and-forget via ``spawn`` — evaluation can take up to 5 minutes
    (AC5) and must not block ``_consume``. Failures (e.g. no API key) are logged
    and swallowed so the run's own ``status="complete"`` is never affected (AD-10).
    """
    variant, pair_id = await asyncio.to_thread(_get_run_ab_fields, run_id)
    if variant != "B" or not pair_id:
        return
    spawn(_run_ab_eval(pair_id, run_id))


async def _run_ab_eval(source_run_id: str, completed_run_id: str) -> None:
    try:
        await eval_service.evaluate_ab(source_run_id, completed_run_id)
    except Exception:
        logger.warning("A/B evaluation failed for pair (%s, %s)",
                        source_run_id, completed_run_id, exc_info=True)


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
        logger.warning("Langfuse span start failed for run %s — tracing disabled for this run", run_id, exc_info=True)
    try:
        yield
    finally:
        if span is not None:
            try:
                span.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 — nor on teardown
                logger.warning("Langfuse span teardown failed for run %s", run_id, exc_info=True)


async def _run(run_id: str, stream: Any, sse_registry: "SSEQueueRegistry | None") -> None:
    try:
        with _trace_cm(run_id):
            await _consume(run_id, stream, sse_registry)
    except Exception as exc:  # AD-4: services catches astream() failures, marks failed, fans out.
        stage = _stage_from_exception(exc)  # FR-13: surface which node actually failed
        _configs.pop(run_id, None)
        await asyncio.to_thread(_write_run, run_id, status="failed", error=str(exc), current_stage=stage)
        await _publish(sse_registry, run_id, "run_failed", {"run_id": run_id, "stage": stage, "error": str(exc)})


async def _ensure_character_reference(scp_id: str) -> None:
    """Auto-provision search-based character references before the graph starts (Story 5.8).

    Reuses ``CharacterService.search_references``/``generate_candidates_from_reference``
    exactly as the Character Management UI (Story 3.7) does — the only difference is this
    runs unattended, once per never-before-seen ``scp_id``. Skips entirely if a
    ``CharacterModel`` already exists (AC2/AC4 — no duplicate work). Best-effort and
    non-fatal (AD-10): any failure here is logged and swallowed — a ``CharacterModel``
    with no angle paths set makes ``resolve_cast_cards`` (Story 8.3) skip every cast member referencing it, so
    downstream video_node degrades to a background-only render exactly like the
    pre-Story-5.8 no-character case.

    After search succeeds, also calls ``CharacterService.enrich_descriptor_from_references``
    (Story 5.12) to populate ``visual_descriptor`` before generation runs, so the generation
    prompt is identity-described rather than relying on IPAdapter image-conditioning alone.
    Enrichment failure is its own non-fatal branch, separate from the search/generation
    try/except below — it must never trigger the total-failure rollback.

    A totally failed attempt (no search results, or every angle generation fails)
    deletes the ``CharacterModel`` it just created rather than leaving a permanent
    empty row behind — otherwise ``check_existing_character`` would skip this SCP
    forever, even after a transient failure (e.g. a rate limit) clears up.

    ponytail: two concurrent first-time runs for the same ``scp_id`` (e.g. an A/B
    pair, Story 4.1) can both pass the existence check before either commits; the
    loser's ``create_character`` hits the DB's ``unique=True`` constraint on
    ``scp_id`` and is treated as "another run is already handling this" rather than
    a failure. No distributed lock — add one if duplicate-provisioning races become
    frequent enough to matter.
    """
    try:
        settings = _settings()
        with Session(db._engine) as session:
            svc = CharacterService(session, settings=settings)
            if svc.check_existing_character(scp_id) is not None:
                return
            try:
                character = svc.create_character(scp_id, scp_id)  # memorization, same as select_candidate
            except IntegrityError:
                logger.info("auto character reference: %s already being provisioned by another run", scp_id)
                return
            try:
                refs = await svc.search_references(scp_id, workspace_path=settings.workspace_path)
                if not refs:
                    raise LookupError(f"no search results for {scp_id}")
                try:
                    descriptor = await svc.enrich_descriptor_from_references(
                        scp_id, ref_image_paths=[r.local_path for r in refs],
                    )
                    if descriptor is not None:
                        svc.update_character(character.id, visual_descriptor=descriptor)
                except Exception:  # noqa: BLE001 — enrichment is enrichment, not a hard requirement (AD-10)
                    logger.warning("auto character reference: vision descriptor enrichment or persistence failed for %s",
                                   scp_id, exc_info=True)
                angle_paths: dict[str, str] = {}
                for angle in CANONICAL_ANGLES:
                    saved = await svc.generate_candidates_from_reference(
                        scp_id, ref_image_path=refs[0].local_path, angles=[angle],
                    )
                    if saved:
                        angle_paths[angle] = saved[0]
                if not angle_paths:
                    raise LookupError(f"all angle generations failed for {scp_id}")
                updates: dict[str, str] = {f"angle_{angle}_path": path for angle, path in angle_paths.items()}
                if "front" in angle_paths:
                    updates["selected_image_path"] = angle_paths["front"]
                svc.update_character(character.id, **updates)
                logger.info("auto character reference: provisioned %d/%d angles for %s",
                            len(angle_paths), len(CANONICAL_ANGLES), scp_id)
            except Exception:
                # Total failure — roll back the row so a future run (after e.g. a
                # transient rate limit clears) retries instead of skipping forever.
                svc.delete_character(character.id)
                raise
    except Exception:  # noqa: BLE001 — auxiliary enrichment must never fail the run (AD-10)
        logger.warning("auto character reference provisioning failed for %s", scp_id, exc_info=True)


async def _ensure_special_pose_cards(scp_id: str, scenes: list[dict]) -> None:
    """Best-effort post-scenario provisioning for Story 8.4 pose_hint cards.

    Mirrors ``_ensure_character_reference``'s AD-10 envelope: every miss or
    generation failure degrades to base-pose resolution later, never run failure.
    """
    try:
        settings = _settings()
        if settings.comfyui_mock:
            return
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for scene in scenes or []:
            for shot in scene.get("shots", []):
                for member in shot.get("cast", []) or []:
                    if not isinstance(member, dict):
                        continue
                    card_key = member.get("card_key")
                    pose_hint = member.get("pose_hint")
                    if not isinstance(card_key, str) or not isinstance(pose_hint, str) or not pose_hint.strip():
                        continue
                    pair = (card_key, pose_hint.strip())
                    if pair not in seen:
                        seen.add(pair)
                        pairs.append(pair)
        if not pairs:
            return

        with Session(db._engine) as session:
            svc = CharacterService(session, settings=settings)
            to_generate: list[tuple[str, str]] = []
            for card_key, hint in pairs:
                if svc.get_card(card_key, pose_hint_key(hint), "front") is None:
                    to_generate.append((card_key, hint))
            cap = max(0, settings.special_pose_max_per_run)
            skipped = to_generate[cap:]
            if skipped:
                logger.warning(
                    "special pose provisioning for %s capped at %d; skipped %s",
                    scp_id, cap, [f"{card_key}:{hint}" for card_key, hint in skipped],
                )
            for card_key, hint in to_generate[:cap]:
                try:
                    await svc.generate_special_pose_card(card_key, hint)
                except Exception:  # noqa: BLE001 — one special pose must not block a run
                    logger.warning(
                        "special pose provisioning failed for %s pose_hint=%r",
                        card_key, hint, exc_info=True,
                    )
    except Exception:  # noqa: BLE001 — auxiliary provisioning must never fail the run
        logger.warning("special pose provisioning failed for %s", scp_id, exc_info=True)


async def _ensure_derived_entity_cards(scp_id: str, scenes: list[dict]) -> None:
    """Best-effort post-scenario provisioning for Story 8.13 derived-entity cards.

    ``cast_decision.md`` teaches the LLM a ``<scp_id>-<n>`` vocabulary for a
    duplicate/offshoot of the run's own entity (e.g. "SCP-049-2"), but nothing
    ever generated a card for that key — ``resolve_cast_cards`` silently skips
    every shot referencing it. Mirrors ``_ensure_special_pose_cards``'s AD-10
    envelope: any miss or generation failure degrades to that existing skip
    behavior, never run failure.
    """
    try:
        settings = _settings()
        if settings.comfyui_mock:
            return
        prefix = f"{scp_id}-"
        keys: list[str] = []
        seen: set[str] = set()
        for scene in scenes or []:
            for shot in scene.get("shots", []):
                for member in shot.get("cast", []) or []:
                    if not isinstance(member, dict):
                        continue
                    card_key = member.get("card_key")
                    if not isinstance(card_key, str) or not card_key.startswith(prefix):
                        continue
                    if not card_key[len(prefix):].isdigit():
                        continue
                    if card_key not in seen:
                        seen.add(card_key)
                        keys.append(card_key)
        if not keys:
            return

        with Session(db._engine) as session:
            svc = CharacterService(session, settings=settings)
            to_generate = [key for key in keys if svc.check_existing_character(key) is None]
            if not to_generate:
                return
            cap = max(0, settings.derived_entity_max_per_run)
            skipped = to_generate[cap:]
            if skipped:
                logger.warning(
                    "derived entity provisioning for %s capped at %d; skipped %s",
                    scp_id, cap, skipped,
                )

            base = svc.check_existing_character(scp_id)
            anchor_path: str | None = None
            if base is not None and base.angle_front_path:
                anchor_path = str(Path(settings.assets_path) / base.angle_front_path)
            else:
                logger.warning(
                    "derived entity provisioning for %s: base entity has no front card, "
                    "generating without a family-resemblance anchor", scp_id,
                )
            base_descriptor = (base.visual_descriptor if base is not None else "") or (
                f"{scp_id}, an SCP Foundation anomaly"
            )
            descriptor = f"{base_descriptor}\nA reclassified/duplicate instance of {scp_id}."

            for card_key in to_generate[:cap]:
                try:
                    await svc.generate_cards_from_descriptor(
                        card_key, descriptor, pose="standing", anchor_path=anchor_path,
                    )
                except Exception:  # noqa: BLE001 — one derived entity must not block a run
                    logger.warning(
                        "derived entity card generation failed for %s", card_key, exc_info=True,
                    )
    except Exception:  # noqa: BLE001 — auxiliary provisioning must never fail the run
        logger.warning("derived entity provisioning failed for %s", scp_id, exc_info=True)


async def start_run(run_id: str, scp_id: str, scp_text: str, sse_registry: "SSEQueueRegistry | None" = None,
                    prompt_variant: Any = None) -> None:
    """Kick off the pipeline: stream until the first gate interrupt (or terminal state).

    ``prompt_variant`` seeds the run's PipelineState — ``"B"`` for an A/B Variant B run
    (Story 4.1), ``None`` for a standard run.
    """
    await _ensure_character_reference(scp_id)  # Story 5.8 — pre-graph, non-fatal
    config = {"configurable": {"thread_id": run_id}}
    _configs[run_id] = config
    await _run(run_id, _graph.astream(_initial_state(run_id, scp_id, scp_text, prompt_variant), config,
                                      stream_mode="updates"), sse_registry)


async def create_ab_run(source_run_id: str, sse_registry: "SSEQueueRegistry | None" = None) -> str:
    """Create Variant B: a second independent run sharing the source's SCP input (AD-6).

    The runs table stores only ``scp_id``, so the full ``scp_text`` is recovered from the
    source run's LangGraph checkpoint. Inserts a linked ``Run`` row (``prompt_variant="B"``,
    ``ab_pair_id=source_run_id``) and launches it through the standard ``start_run`` driver —
    no graph-level branching. The source run's existence/completeness is validated by the
    route before this is called. Returns the new run id.
    """
    snap = await _graph.aget_state({"configurable": {"thread_id": source_run_id}})
    scp_text = (snap.values or {}).get("scp_text")
    if not scp_text:
        raise ValueError(f"Source run {source_run_id} has no scp_text in its checkpoint")
    new_id = str(uuid.uuid4())
    with Session(db._engine) as session:
        source = session.get(Run, source_run_id)
        if source is None:
            raise ValueError(f"Source run {source_run_id} not found")
        scp_id = source.scp_id  # read inside the session — `source` is detached once it closes
        session.add(Run(id=new_id, scp_id=scp_id, status="running",
                        prompt_variant="B", ab_pair_id=source_run_id))
        session.commit()
    spawn(start_run(new_id, scp_id, scp_text, sse_registry, prompt_variant="B"))
    return new_id


async def resume_run(run_id: str, stage: str, action: str, sse_registry: "SSEQueueRegistry | None" = None) -> None:
    """Resume a gated run with an approve/reject decision. [AD-3, AD-4]

    ``stage`` identifies which gate the client acted on; LangGraph resumes the single
    pending interrupt on this run's thread, so it is carried for traceability only.
    """
    config = _configs.get(run_id, {"configurable": {"thread_id": run_id}})
    decision = _ACTION_TO_DECISION.get(action, action)
    await asyncio.to_thread(_write_run, run_id, status="running")
    if stage == "scenario" and decision == "approved":
        snap = await _graph.aget_state(config)
        values = snap.values or {}
        await _ensure_special_pose_cards(values.get("scp_id", ""), values.get("scenes") or [])
        await _ensure_derived_entity_cards(values.get("scp_id", ""), values.get("scenes") or [])
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
    await asyncio.to_thread(_write_run, run_id, status="running", error=None)
    await _run(run_id, _graph.astream(None, config, stream_mode="updates"), sse_registry)


async def full_restart_run(run_id: str, sse_registry: "SSEQueueRegistry | None" = None) -> None:
    """Restart a run from ``scenario``, disregarding any existing checkpoint. [AC2, FR-8]

    Explicit at the service boundary so no caller can silently get resume behavior.
    Strategy: wipe the thread's checkpoints, then stream a fresh initial state on the
    *same* ``run_id`` thread — the operator-facing run id stays stable and its trace
    (deterministic from ``run_id``) stays coherent. The fresh initial state resets
    ``scenes``, ``video_path``, per-stage artifact paths, ``error``, and ``gate_states``,
    so no stale paths survive. ``scp_id`` and ``scp_text`` are recovered from the prior
    checkpoint (preferred) or fall back to the runs table.
    """
    config = {"configurable": {"thread_id": run_id}}
    snap = await _graph.aget_state(config)
    scp_id = (snap.values or {}).get("scp_id", "")
    scp_text = (snap.values or {}).get("scp_text", "")
    # Fall back to runs table if checkpoint lacks scp_id (pre-1.13 checkpoints)
    if not scp_id:
        with Session(db._engine) as session:
            run = session.get(Run, run_id)
            if run is not None:
                scp_id = run.scp_id
    ckpt = _graph.checkpointer
    if ckpt is not None:
        await ckpt.adelete_thread(run_id)  # drop prior successful checkpoints → START from scenario
    _configs[run_id] = config
    await asyncio.to_thread(_write_run, run_id, status="running", current_stage="scenario",
                             error=None, gate_states="{}")
    await _run(run_id, _graph.astream(_initial_state(run_id, scp_id, scp_text), config, stream_mode="updates"), sse_registry)


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
                shot["image_path"] = None
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
        if run.status not in _MUTABLE_STATES:  # B-1: don't touch a live run's checkpoint
            raise HTTPException(
                status_code=409,
                detail=f"Cannot retry: run status is {run.status!r} (must be settled, not in progress)",
            )
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
    await asyncio.to_thread(_write_run, run_id, status="running", current_stage=stage, error=None,
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
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.status not in _MUTABLE_STATES:  # B-1: no file write / aupdate_state on a live run
            raise HTTPException(
                status_code=409,
                detail=f"Cannot edit artifact: run status is {run.status!r} (must be settled, not in progress)",
            )
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


async def precompute_relights_for_run(
    scenes: list, cast_cards: dict, session: Session, settings: Settings,
) -> tuple[dict, dict]:
    """Story 8.7 Tier 3: glue AssetService/comfyui_client to
    composite_harmonization.precompute_relights for video_node's injection seam.

    Lives here (not a dedicated services/ module) because run_service.py is the
    one services file allowed to import pipeline/ (AD-1/AD-3/AD-4 — see
    tests/services/test_character_service.py::test_services_does_not_import_api_or_pipeline).
    """
    from yt_flow.pipeline.nodes.composite_harmonization import precompute_relights

    asset_service = AssetService(settings.assets_path, session)
    return await precompute_relights(
        scenes, cast_cards, asset_service, comfyui_client,
        settings.iclight_comfyui_workflow_path,
        Path(settings.assets_path), settings.comfyui_url,
    )
