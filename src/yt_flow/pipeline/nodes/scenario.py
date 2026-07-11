"""scenario_node — the LLM-Director stage (Story 1.5, multi-stage redesign 2026-07-03).

Runs the 6-stage chain (research -> structure -> writing -> visual_breakdown
xN -> review + critic_agent, bounded to one retry) documented in
docs/superpowers/specs/2026-07-03-scenario-multistage-design.md, and maps the
result onto ``PipelineState.scenes``. Pure function of state: reads a few
fields, returns only the changed ones (``scenes``, ``current_stage``, and
``error`` on failure). No DB / SSE / gate writes and no ``interrupt()`` — gate
behaviour stays in ``gates.py``. [AD-4, AD-3]

DeepSeek is OpenAI-compatible, so we POST to ``/chat/completions`` with the
already-installed ``httpx`` client instead of adding the ``openai`` SDK.
"""

import asyncio
import logging
import time

import httpx
from yt_flow.observability import get_client, observe

from yt_flow.config import Settings
from yt_flow.pipeline.nodes.scenario_chain import (
    SceneCoverageError,
    TruncationError,
    build_scenes,
    cast_decision_step,
    critic_step,
    research_step,
    review_step,
    split_sentences,
    structure_step,
    tts_normalize_step,
    visual_breakdown_step,
    writing_scene_repair_step,
    writing_step,
)
from yt_flow.domain.state import PipelineState
from yt_flow.services.prompt_service import get_prompt, get_prompt_with_fallback

logger = logging.getLogger(__name__)


def _settings() -> Settings:
    # ponytail: one seam so unit tests can inject fake settings without a real .env.
    return Settings()


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


_USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")


def _usage_totals(usage_list: list[dict]) -> dict[str, int]:
    """Sum DeepSeek `usage` dicts collected for one stage. A missing/absent/
    non-numeric field degrades to 0 rather than raising [AD-10]."""
    totals: dict[str, int] = dict.fromkeys(_USAGE_FIELDS, 0)
    for usage in usage_list:
        if not isinstance(usage, dict):
            continue
        for field in _USAGE_FIELDS:
            value = usage.get(field)
            if type(value) is int and value >= 0:
                totals[field] += value
    return totals


async def _call_deepseek(rendered: str, s: Settings) -> tuple[str, dict, str | None]:
    """Return (content, usage, finish_reason) from a JSON-mode chat completion."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        resp = await client.post(
            f"{s.deepseek_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {s.deepseek_api_key}"},
            json={
                "model": s.deepseek_model,
                "messages": [{"role": "user", "content": rendered}],
                "max_tokens": s.deepseek_max_tokens,
            },
        )
    resp.raise_for_status()
    data = resp.json()
    choice = data["choices"][0]
    return choice["message"]["content"], data.get("usage", {}), choice.get("finish_reason")


def _record_trace(*, stages: list[dict], total_latency_ms: int, error: Exception | None = None) -> None:
    """Best-effort enrich the current ``scenario`` span. [AD-10 — tracing is non-fatal]"""
    try:
        get_client().update_current_span(
            input={"stage_count": len(stages)},
            output=None if error is not None else {"stages": [s["name"] for s in stages]},
            metadata={
                "stages": stages,
                "total_latency_ms": total_latency_ms,
                **({"error": str(error)} if error is not None else {}),
            },
            **({"level": "ERROR", "status_message": str(error)} if error is not None else {}),
        )
    except Exception:  # noqa: BLE001 — a tracing failure must never break the pipeline
        pass


def _format_feedback(review: dict, critic: dict) -> str:
    lines = [critic.get("feedback", "")]
    for issue in review.get("issues", []):
        lines.append(f"- Scene {issue.get('scene_num')}: {issue.get('description')} -> {issue.get('correction')}")
    return "\n".join(line for line in lines if line)


def _retry_scope(review: dict, critic: dict, scenes: list[dict]) -> tuple[list[int], list[dict]]:
    """Return ordered positional indexes and evidence for rejected identifiers."""
    indexes: list[int] = []
    rejected: list[dict] = []
    scene_count = len(scenes)
    sources = (
        ("review", review.get("issues", [])),
        ("critic", critic.get("scene_notes", [])),
    )
    for source, entries in sources:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            raw = entry.get("scene_num") if isinstance(entry, dict) else None
            if type(raw) is not int:
                reason = "boolean" if type(raw) is bool else "not-integer"
                rejected.append({"source": source, "scene_num": raw, "reason": reason})
                continue
            if raw < 1:
                rejected.append({"source": source, "scene_num": raw, "reason": "non-positive"})
                continue
            if raw > scene_count:
                rejected.append({"source": source, "scene_num": raw, "reason": "out-of-range"})
                continue
            idx = raw - 1
            # Never trust the LLM-reported scene_num as a position without confirming it
            # matches the scene actually at that index — same rule _breakdown_for applies
            # to visual_by_scene keys; duplicate/out-of-order model scene_num is a tested
            # failure mode elsewhere in this chain.
            if scenes[idx].get("scene_num") != raw:
                rejected.append({"source": source, "scene_num": raw, "reason": "scene_num-mismatch"})
                continue
            if idx in indexes:
                rejected.append({"source": source, "scene_num": raw, "reason": "duplicate"})
                continue
            indexes.append(idx)
    return indexes, rejected


def _format_scene_feedback(review: dict, critic: dict, indexes: list[int]) -> str:
    target_nums = {idx + 1 for idx in indexes}
    lines: list[str] = []
    for issue in review.get("issues", []):
        if isinstance(issue, dict) and issue.get("scene_num") in target_nums:
            lines.append(
                f"Review scene {issue['scene_num']}: {issue.get('description', '')} -> {issue.get('correction', '')}"
            )
    for note in critic.get("scene_notes", []):
        if isinstance(note, dict) and note.get("scene_num") in target_nums:
            # `critic_step` doesn't schema-validate `scene_notes` entries, so a key can be
            # present but explicitly None — `or` falls through that, plain dict.get default
            # would not (its default only applies when the key is absent).
            detail = note.get("feedback") or note.get("note") or note.get("description") or ""
            lines.append(f"Critic scene {note['scene_num']}: {detail}")
    return "\n".join(lines)


def _trace_fields(pass_index: int, retry_scope: str, indexes: list[int], rejected: list[dict] | None = None) -> dict:
    fields = {
        "pass_index": pass_index,
        "retry_scope": retry_scope,
        "target_scene_count": len(indexes),
        "target_scene_indexes": indexes,
    }
    if rejected:
        fields["rejected_scene_identifiers"] = rejected
    return fields


async def _write_and_review(
    scp_id: str,
    scp_text: str,
    structure: list[dict],
    frozen_descriptor: str,
    entity_sheet: str,
    story_logline: str,
    format_guide: str,
    quality_feedback: str,
    s: Settings,
    stages: list[dict],
    *,
    label: str | None = None,
    pass_index: int = 1,
    retry_scope: str = "none",
    rejected: list[dict] | None = None,
) -> tuple[dict, dict, dict, dict]:
    target_indexes = list(range(len(structure)))
    trace = _trace_fields(pass_index, retry_scope, target_indexes, rejected)
    t0 = time.perf_counter()
    usage: list[dict] = []
    writing = await writing_step(
        scp_id, structure, frozen_descriptor, format_guide, quality_feedback, s, _call_deepseek,
        label=label, usage_sink=usage,
    )
    stages.append({"name": "writing", "latency_ms": _ms(t0), **trace, **_usage_totals(usage)})

    t0 = time.perf_counter()
    breakdown_usage: list[dict] = []

    async def _breakdown_for(idx: int, scene: dict) -> tuple[int, list[dict]]:
        sentences = split_sentences(scene["narration"])
        # positional — writing_step's scenes correspond 1:1 to structure's scenes, same rule as build_scenes.
        if idx < len(structure):
            scene_role = structure[idx]
        else:
            logger.warning(
                "scenario: writing produced more scenes (%d) than structure (%d); scene %d has no narrative role",
                len(writing["scenes"]), len(structure), idx + 1,
            )
            scene_role = {}
        cast_by_sentence = await cast_decision_step(
            scp_id, scene, sentences, s, _call_deepseek, label=label, usage_sink=breakdown_usage,
        )
        shots = await visual_breakdown_step(
            scp_id, scene, sentences, cast_by_sentence, frozen_descriptor, entity_sheet, story_logline, scene_role,
            s, _call_deepseek, label=label, usage_sink=breakdown_usage,
        )
        return idx, shots  # positional key — never trust the LLM's own scene_num for lookups

    results = await asyncio.gather(*(_breakdown_for(idx, scene) for idx, scene in enumerate(writing["scenes"])))
    visual_by_scene = dict(results)
    stages.append({
        "name": "visual_breakdown", "latency_ms": _ms(t0), "scene_count": len(visual_by_scene),
        **trace, **_usage_totals(breakdown_usage),
    })

    t0 = time.perf_counter()
    usage = []
    review = await review_step(
        scp_text, writing, visual_by_scene, frozen_descriptor, format_guide, s, _call_deepseek,
        label=label, usage_sink=usage,
    )
    stages.append({"name": "review", "latency_ms": _ms(t0), **trace, **_usage_totals(usage)})

    t0 = time.perf_counter()
    usage = []
    critic = await critic_step(writing, visual_by_scene, format_guide, s, _call_deepseek, label=label, usage_sink=usage)
    stages.append({"name": "critic_agent", "latency_ms": _ms(t0), **trace, **_usage_totals(usage)})

    return writing, visual_by_scene, review, critic


async def _repair_and_review(
    scp_id: str, scp_text: str, structure: list[dict], frozen_descriptor: str,
    entity_sheet: str, story_logline: str, format_guide: str, writing: dict,
    visual_by_scene: dict, review: dict, critic: dict, indexes: list[int],
    rejected: list[dict], s: Settings, stages: list[dict], *, label: str | None = None,
) -> tuple[dict, dict, dict, dict]:
    trace = _trace_fields(2, "scene", indexes, rejected)
    originals = [writing["scenes"][idx] for idx in indexes]
    t0 = time.perf_counter()
    usage: list[dict] = []
    repaired = await writing_scene_repair_step(
        scp_id, originals, _format_scene_feedback(review, critic, indexes), frozen_descriptor,
        format_guide, s, _call_deepseek, label=label, usage_sink=usage,
    )
    stages.append({"name": "writing_scene_repair", "latency_ms": _ms(t0), **trace, **_usage_totals(usage)})

    merged_scenes = list(writing["scenes"])
    for idx, scene in zip(indexes, repaired, strict=True):
        merged_scenes[idx] = scene
    merged_writing = {**writing, "scenes": merged_scenes}

    t0 = time.perf_counter()
    breakdown_usage: list[dict] = []
    async def _breakdown_for(idx: int) -> tuple[int, list[dict]]:
        scene = merged_scenes[idx]
        sentences = split_sentences(scene["narration"])
        role = structure[idx] if idx < len(structure) else {}
        cast = await cast_decision_step(
            scp_id, scene, sentences, s, _call_deepseek, label=label, usage_sink=breakdown_usage,
        )
        shots = await visual_breakdown_step(
            scp_id, scene, sentences, cast, frozen_descriptor, entity_sheet, story_logline, role,
            s, _call_deepseek, label=label, usage_sink=breakdown_usage,
        )
        return idx, shots
    repaired_visuals = await asyncio.gather(*(_breakdown_for(idx) for idx in indexes))
    merged_visuals = dict(visual_by_scene)
    merged_visuals.update(repaired_visuals)
    stages.append({"name": "visual_breakdown", "latency_ms": _ms(t0), "scene_count": len(indexes), **trace, **_usage_totals(breakdown_usage)})

    t0 = time.perf_counter()
    usage = []
    next_review = await review_step(
        scp_text, merged_writing, merged_visuals, frozen_descriptor, format_guide, s, _call_deepseek,
        label=label, usage_sink=usage,
    )
    stages.append({"name": "review", "latency_ms": _ms(t0), **trace, **_usage_totals(usage)})
    t0 = time.perf_counter()
    usage = []
    next_critic = await critic_step(
        merged_writing, merged_visuals, format_guide, s, _call_deepseek, label=label, usage_sink=usage,
    )
    stages.append({"name": "critic_agent", "latency_ms": _ms(t0), **trace, **_usage_totals(usage)})
    return merged_writing, merged_visuals, next_review, next_critic


@observe(name="scenario")
async def scenario_node(state: PipelineState, *, trace_sink: list[dict] | None = None) -> dict:
    run_id = state.get("run_id", "?")
    t0_total = time.perf_counter()
    stages: list[dict] = []
    try:
        s = _settings()
        if not s.deepseek_api_key:
            raise RuntimeError("YTFLOW_DEEPSEEK_API_KEY is not configured")
        if s.content_language != "ko":
            raise NotImplementedError(
                f"content_language={s.content_language!r} not supported yet; scenario prompts, "
                "TTS naturalization, and subtitle typography are Korean-only (YTFLOW_CONTENT_LANGUAGE)"
            )

        label = "candidate" if state.get("prompt_variant") == "B" else None
        format_guide = (
            get_prompt_with_fallback("scenario/format_guide", label=label) if label else get_prompt("scenario/format_guide")
        ).compile()

        t0 = time.perf_counter()
        usage: list[dict] = []
        research = await research_step(
            state["scp_id"], state["scp_text"], format_guide, s, _call_deepseek, label=label, usage_sink=usage,
        )
        stages.append({"name": "research", "latency_ms": _ms(t0), **_trace_fields(1, "none", []), **_usage_totals(usage)})

        t0 = time.perf_counter()
        usage = []
        structure = await structure_step(
            state["scp_id"], research, format_guide, s, _call_deepseek, label=label, usage_sink=usage,
        )
        stages.append({"name": "structure", "latency_ms": _ms(t0), **_trace_fields(1, "none", []), **_usage_totals(usage)})

        writing, visual_by_scene, review, critic = await _write_and_review(
            state["scp_id"], state["scp_text"], structure, research["frozen_descriptor"],
            research.get("entity_sheet", ""), research.get("story_logline", ""),
            format_guide, "", s, stages, label=label,
        )

        final_pass_index = 1
        final_retry_scope = "none"
        final_indexes: list[int] = []

        async def _full_rewrite(scope: str, rejected: list[dict]):
            # Regenerate every scene from scratch with feedback — the proven,
            # non-truncating path (Story 6.9: full 8-scene writing ~2.8k tokens).
            return await _write_and_review(
                state["scp_id"], state["scp_text"], structure, research["frozen_descriptor"],
                research.get("entity_sheet", ""), research.get("story_logline", ""),
                format_guide, _format_feedback(review, critic), s, stages, label=label,
                pass_index=2, retry_scope=scope, rejected=rejected,
            )

        if critic["verdict"] == "retry" or not review["overall_pass"]:
            indexes, rejected = _retry_scope(review, critic, writing["scenes"])
            final_pass_index = 2
            final_indexes = indexes
            if indexes:
                try:
                    writing, visual_by_scene, review, critic = await _repair_and_review(
                        state["scp_id"], state["scp_text"], structure, research["frozen_descriptor"],
                        research.get("entity_sheet", ""), research.get("story_logline", ""), format_guide,
                        writing, visual_by_scene, review, critic, indexes, rejected, s, stages, label=label,
                    )
                    final_retry_scope = "scene"
                except TruncationError as exc:
                    if exc.prompt_name != "scenario/writing_scene_repair":
                        # Only the scoped-repair write is recoverable via a full
                        # rewrite. A truncation in the repair pass's downstream
                        # review/critic/visual/cast stages (all raise TruncationError
                        # too, since it subclasses ValueError) is a real failure —
                        # re-raise so the run fails, keeping recovery narrow
                        # (Story 6.9 review).
                        raise
                    # Scene-scoped repair ran away past max_tokens even though a full
                    # rewrite of every scene fits comfortably (Story 6.9: 8-scene
                    # writing ~2.8k tokens vs repair truncating at 16k). It's a
                    # degenerate scoped-repair generation, not a batch-volume
                    # problem, so a batch cap wouldn't help — route to the proven
                    # full-rewrite path instead of failing the whole run.
                    logger.warning(
                        "scenario: writing_scene_repair truncated (completion_tokens=%s, len(indexes)=%d); "
                        "falling back to full rewrite. runaway preview: %r",
                        exc.completion_tokens, len(indexes), (exc.raw or "")[:300],
                    )
                    final_retry_scope = "scene-repair-truncated-fallback"
                    # The fallback rewrote every scene, so the flagged subset no
                    # longer describes the change scope — clear it to keep the
                    # tts_normalize trace consistent with the full-fallback branch.
                    final_indexes = []
                    writing, visual_by_scene, review, critic = await _full_rewrite(
                        final_retry_scope,
                        [{"reason": "scene-repair-truncated",
                          "completion_tokens": exc.completion_tokens, "flagged_scene_count": len(indexes)}],
                    )
                except SceneCoverageError as exc:
                    # Story 6.10: the scoped repair returned a scene set that
                    # can't be mapped back to the flagged subset (a genuine
                    # coverage mismatch, distinct from a mere reorder — those
                    # recover inside writing_scene_repair_step and never reach
                    # here). Like truncation, route to the proven full-rewrite
                    # path so the item stays scoreable instead of failing the
                    # whole run. Recovery stays narrow: only this class and
                    # truncation fall back; every other repair error re-raises.
                    logger.warning(
                        "scenario: writing_scene_repair returned an unmappable scene set (%s); "
                        "falling back to full rewrite.", exc,
                    )
                    final_retry_scope = "scene-repair-coverage-fallback"
                    final_indexes = []
                    writing, visual_by_scene, review, critic = await _full_rewrite(
                        final_retry_scope, [{"reason": "scene-repair-coverage-mismatch"}],
                    )
            else:
                final_retry_scope = "full-fallback"
                writing, visual_by_scene, review, critic = await _full_rewrite(
                    "full-fallback", [{"reason": "no-valid-scene", "rejected": rejected}]
                )

        t0 = time.perf_counter()
        usage = []
        writing = await tts_normalize_step(writing, format_guide, s, _call_deepseek, label=label, usage_sink=usage)
        stages.append({
            "name": "tts_normalize", "latency_ms": _ms(t0),
            **_trace_fields(final_pass_index, final_retry_scope, final_indexes), **_usage_totals(usage),
        })

        scenes = build_scenes(writing, visual_by_scene, structure)
        _record_trace(stages=stages, total_latency_ms=_ms(t0_total))
        return {"scenes": scenes, "current_stage": "scenario", "error": None}
    except Exception as exc:  # noqa: BLE001 — surfaced as PipelineState.error, never raised past the node
        _record_trace(stages=stages, total_latency_ms=_ms(t0_total), error=exc)
        return {"current_stage": "scenario", "error": f"stage=scenario run_id={run_id}: {exc}"}
    finally:
        if trace_sink is not None:
            trace_sink.extend(stages)
