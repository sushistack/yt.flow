"""scenario_node — the LLM-Director stage (Story 1.5, multi-stage redesign 2026-07-03).

Runs the 6-stage chain (research -> structure -> writing -> visual_breakdown
xN -> review + critic_agent, bounded to one retry) documented in
docs/superpowers/specs/2026-07-03-scenario-multistage-design.md, and maps the
result onto ``PipelineState.scenes``. Pure function of state: reads a few
fields, returns only the changed ones (``scenes``, ``current_stage``, and
``error`` on failure). No DB / SSE / gate writes and no ``interrupt()`` — gate
behaviour stays in ``gates.py``. [AD-4, AD-3]

DeepSeek is OpenAI-compatible, so we POST to ``/chat/completions`` with the
already-installed ``httpx`` client instead of adding the ``openai`` SDK. Gemini
exposes the same OpenAI-compatible shape, so Story 12.2's model split needed a
second base URL + key, not a second transport or an SDK.

Story 12.2 provider ownership (``_GEMINI_STAGES`` below is the single source of
truth): Gemini writes and judges prose — ``writing``, ``writing_scene_repair``,
``review``, ``critic_agent``. DeepSeek keeps planning, visual metadata and the
Qwen-tuned pronunciation pass — ``research``, ``structure``, ``cast_decision``,
``visual_breakdown``, ``tts_normalize``. There is deliberately NO fallback
between them: a provider outage is a visible failure, because a run that quietly
completed on the wrong provider would look compliant with the split while
invalidating every quality attribution drawn from it [AD-10].
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
    compute_rule_metrics,
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
from yt_flow.domain.state import (
    REVIEW_ISSUE_TYPES,
    STORY_ARCHETYPE_FALLBACK,
    PipelineState,
    normalize_critic_issue_type,
)
from yt_flow.services.prompt_service import get_prompt, get_prompt_with_fallback

logger = logging.getLogger(__name__)


def _settings() -> Settings:
    # ponytail: one seam so unit tests can inject fake settings without a real .env.
    return Settings()


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


_USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")


def _usage_totals(usage_list: list[dict]) -> dict[str, int]:
    """Sum provider `usage` dicts collected for one stage. A missing/absent/
    non-numeric field degrades to 0 rather than raising [AD-10].

    Gemini reports only prompt/completion tokens, so the two DeepSeek
    context-cache fields stay 0 on a Gemini-owned stage — absent, never
    fabricated (Story 12.2 AC4)."""
    totals: dict[str, int] = dict.fromkeys(_USAGE_FIELDS, 0)
    for usage in usage_list:
        if not isinstance(usage, dict):
            continue
        for field in _USAGE_FIELDS:
            value = usage.get(field)
            if type(value) is int and value >= 0:
                totals[field] += value
    return totals


# One mechanism per value, never both fields: reasoning_effort for a depth,
# `thinking` only for off (the only form that probed reasoning_tokens=0), and
# nothing at all for "default" so that value keeps the pre-2026-08-06 request
# byte-identical. See config.deepseek_reasoning for the probe numbers.
_REASONING_BODY: dict[str, dict] = {
    "low": {"reasoning_effort": "low"},
    "medium": {"reasoning_effort": "medium"},
    "high": {"reasoning_effort": "high"},
    "disabled": {"thinking": {"type": "disabled"}},
    "default": {},
}


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
                **_REASONING_BODY[s.deepseek_reasoning],
            },
        )
    resp.raise_for_status()
    data = resp.json()
    choice = data["choices"][0]
    message = choice["message"]
    content = message.get("content") or ""
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length" and not content:
        # A reasoning model spends its token budget in `reasoning_content`, so a
        # completion cut off mid-reasoning carries an EMPTY `content`. Returning
        # only `content` is why every truncation dump from the 2026-08-05 runs was
        # 0 bytes — the evidence was in the field we threw away. Safe to substitute:
        # `_call_stage` raises TruncationError on finish_reason=length before any
        # parser sees this string, so it is read only by the diagnostic dump.
        content = message.get("reasoning_content") or ""
    return content, data.get("usage", {}), finish_reason


# Gemini's OpenAI-compatibility layer reports a token-limit stop as "length", but
# has also been observed passing the native MAX_TOKENS reason through. Both mean
# the same thing to us: map them onto the one signal `_call_stage` turns into a
# TruncationError, so the chain's bounded re-roll keeps working (Story 12.2).
_GEMINI_TRUNCATION_REASONS = frozenset({"length", "MAX_TOKENS", "max_tokens"})


async def _call_gemini(rendered: str, s: Settings) -> tuple[str, dict, str | None]:
    """Return (content, usage, finish_reason) — same tuple contract as
    ``_call_deepseek``, so ``scenario_chain._call_stage`` stays provider-agnostic
    and no HTTP/SDK object leaks past this function (Story 12.2 AC3).

    Never falls back to DeepSeek: every error propagates to the caller.
    """
    if not s.gemini_api_key:
        raise RuntimeError("YTFLOW_GEMINI_API_KEY is not configured")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        resp = await client.post(
            f"{s.gemini_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {s.gemini_api_key}"},
            json={
                "model": s.gemini_writing_model,
                "messages": [{"role": "user", "content": rendered}],
                "max_tokens": s.gemini_writing_max_tokens,
            },
        )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        # A blocked prompt can come back 200-with-no-choices; parsing "" as YAML
        # downstream would read as a content failure of the wrong stage.
        raise RuntimeError(f"gemini: response carried no choices (model={s.gemini_writing_model})")
    choice = choices[0]
    content = (choice.get("message") or {}).get("content") or ""
    finish_reason = choice.get("finish_reason")
    if finish_reason in _GEMINI_TRUNCATION_REASONS:
        # NOTE for the next person debugging a truncated Gemini stage: `content` is
        # normally "" here, and unlike `_call_deepseek` there is no
        # `reasoning_content` to substitute — Gemini's compatibility layer does not
        # return its thoughts, so the diagnostic dump for a Gemini truncation IS
        # 0 bytes and that is not a bug in the dump. Diagnose from `usage`
        # (completion_tokens vs total_tokens shows the thinking spend, measured at
        # ~2-5k/call on 2026-08-06) and from the max-tokens setting instead.
        return content, data.get("usage") or {}, "length"
    if not content:
        # Safety-filtered / recitation-blocked / otherwise empty. Loud failure,
        # never an empty-success that masquerades as unparseable model output.
        raise RuntimeError(
            f"gemini: empty content (model={s.gemini_writing_model}, finish_reason={finish_reason!r})"
        )
    return content, data.get("usage") or {}, finish_reason


# The ownership table, as code. Keyed by the stage names used in `stages` trace
# entries; `_provider_fields` and the routing helper both read it, so a stage can
# never be traced as one provider while being called on another.
_GEMINI_STAGES = frozenset({"writing", "writing_scene_repair", "review", "critic_agent"})


def _provider_fields(stage: str, s: Settings) -> dict:
    """Trace fields naming the provider + configured model that served a stage
    (AC8). Credentials are never included."""
    if stage in _GEMINI_STAGES:
        return {"provider": "gemini", "model": s.gemini_writing_model}
    return {"provider": "deepseek", "model": s.deepseek_model}


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


# ── Story 12.3: the final review/critic verdict, kept for the human gate ──────
#
# The defect: pass-2's recomputed `review`/`critic` overwrote pass-1's locals and
# were then never read — `tts_normalize` ran next and the stage returned only
# `scenes`. A script that was still "retry" after its one repair pass reached the
# human gate looking identical to a clean one, which is exactly the silent
# degradation AD-10 forbids. The fix is visibility, NOT a third pass: Story 6.5's
# one-retry limit is deliberate.
_UNRESOLVED_PASS2_MESSAGE = (
    "재검토 후에도 품질 문제가 남아 있습니다. 아래 근거를 확인한 뒤 승인 또는 반려하세요."
)
_MAX_FEEDBACK_CHARS = 2000
_MAX_QUALITY_TEXT = 600
_MAX_QUALITY_ITEMS = 20
_ISSUE_KEYS = ("type", "severity", "description", "correction")
# Story 12.6: `issue_type` first — it is the whitelisted key that makes a critic note
# actionable, and `critic_step.parse` has already coerced it into CRITIC_ISSUE_TYPES.
_CRITIC_NOTE_KEYS = ("issue_type", "issue", "suggestion")
_CONTRADICTION_KEYS = (
    "narration_quote", "grounding_source", "grounding_quote", "explanation", "correction",
)


def _clip(value: object, limit: int) -> str:
    """Whitespace-collapsed, length-bounded text. The gate payload travels through
    a checkpoint, an interrupt value and an SSE frame, so an unbounded model
    string is a real cost — but it must never be silently *empty*."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clip_lines(value: object, limit: int) -> str:
    """Same bound, but line structure survives. ``_aggregate_critic`` joins its
    per-scene feedback with newlines ("Scene 1: …\\nScene 2: …"); collapsing those
    into one paragraph would hand the operator a wall of text at the exact moment
    they have to read it — and the UI renders this field ``whitespace-pre-wrap``."""
    lines = [" ".join(line.split()) for line in str(value or "").splitlines()]
    text = "\n".join(line for line in lines if line)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _bounded(items: object, keys: tuple[str, ...], what: str) -> list[dict]:
    """Whitelist + clip + cap a list of model-authored evidence entries.

    Whitelisted keys only: whatever else the prompt emitted is not part of the
    contract and would ride along into the checkpoint unbounded. A cap that drops
    entries is LOGGED — a silently truncated list reads as "that was everything".
    """
    if items is not None and not isinstance(items, list):
        # A mapping or scalar here yields [] and every typed finding vanishes from
        # the gate with no trace — the same silent-degradation shape AD-10 forbids.
        # Warn rather than raise: the evidence list is not what the run turns on.
        logger.warning(
            "scenario: %s arrived as %s, not a list — no entries reach the gate payload",
            what, type(items).__name__,
        )
    entries = [item for item in (items if isinstance(items, list) else []) if isinstance(item, dict)]
    if len(entries) > _MAX_QUALITY_ITEMS:
        logger.warning(
            "scenario: %s bounded for the gate payload — keeping %d of %d entries",
            what, _MAX_QUALITY_ITEMS, len(entries),
        )
        entries = entries[:_MAX_QUALITY_ITEMS]
    out: list[dict] = []
    for entry in entries:
        scene_num = entry.get("scene_num")
        row: dict = {"scene_num": scene_num if type(scene_num) is int else 0}
        row.update({key: _clip(entry.get(key), _MAX_QUALITY_TEXT) for key in keys})
        out.append(row)
    return out


def _build_quality(
    pass_index: int, retry_scope: str, review: dict, critic: dict, writing: dict
) -> dict:
    """The scenario stage's quality verdict, JSON/checkpoint-safe by construction.

    ``warning`` is present ONLY when the FINAL pass is negative and that pass was
    the retry — a pass-1 failure that the repair fixed is a success story, and
    ``accept_with_notes`` is not a failure at all (AC3).
    """
    verdict = str(critic.get("verdict") or "")
    overall_pass = bool(review.get("overall_pass"))
    quality: dict = {
        "final_pass_index": pass_index,
        "retry_scope": retry_scope,
        "review_overall_pass": overall_pass,
        "critic_verdict": verdict,
        "critic_feedback": _clip_lines(critic.get("feedback"), _MAX_FEEDBACK_CHARS),
        # Computed here, from the writing the review actually judged, and merged
        # AFTER review parsing — so a model reporting its own flattering metrics
        # cannot overwrite them (AC5).
        "rule_metrics": compute_rule_metrics(writing),
        "grounded_contradictions": _bounded(
            review.get("grounded_contradictions"), _CONTRADICTION_KEYS, "grounded contradictions",
        ),
        "review_issues": _bounded(review.get("issues"), _ISSUE_KEYS, "review issues"),
        "critic_scene_notes": _bounded(critic.get("scene_notes"), _CRITIC_NOTE_KEYS, "critic scene notes"),
    }
    if pass_index == 2 and (verdict == "retry" or not overall_pass):
        # Story 12.6: same `code` (the UI and its tests key on it), plus the distinct
        # categories behind it. Both judges contribute — the critic's typed
        # `issue_type` and the review's own `issues[].type` enum — because a fact
        # violation and a craft violation call for different operator actions and
        # one warning string could not tell them apart. Sorted + distinct so the
        # line is stable across runs.
        #
        # The critic side reads the RAW `scene_notes`, not the `_MAX_QUALITY_ITEMS`-
        # capped copy: `_aggregate_critic` concatenates every scene's notes, so a
        # 12-scene run with 20 `pacing` notes ahead of one `ungrounded_claim` in
        # scene 11 would drop the fact violation out of `categories` entirely —
        # defeating the whole point of typing the field. Safe to read unbounded
        # because this is a SET over a 7-value closed vocabulary; it cannot grow
        # past 7 entries however many notes arrive.
        #
        # The review side is a membership filter, not a normalization: `issues[].type`
        # is unvalidated model text clipped to 600 chars, so without REVIEW_ISSUE_TYPES
        # a 600-character sentence renders at the gate as a "category". It reads the
        # RAW `issues` for the same reason the critic side does — a fact-typed issue
        # sitting past entry 20 must not be capped out of the summary line.
        raw_notes = critic.get("scene_notes")
        raw_issues = review.get("issues")
        categories = sorted(
            {
                normalize_critic_issue_type(note.get("issue_type"))
                for note in (raw_notes if isinstance(raw_notes, list) else [])
                if isinstance(note, dict)
            }
            | {
                issue["type"]
                for issue in (raw_issues if isinstance(raw_issues, list) else [])
                if isinstance(issue, dict) and issue.get("type") in REVIEW_ISSUE_TYPES
            }
        )
        warning: dict = {"code": "unresolved_pass2", "message": _UNRESOLVED_PASS2_MESSAGE}
        if categories:
            warning["categories"] = categories
        quality["warning"] = warning
    return quality


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
        scp_id, structure, frozen_descriptor, format_guide, quality_feedback, s, _call_gemini,
        label=label, usage_sink=usage,
    )
    stages.append({
        "name": "writing", "latency_ms": _ms(t0),
        **_provider_fields("writing", s), **trace, **_usage_totals(usage),
    })

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
        **_provider_fields("visual_breakdown", s), **trace, **_usage_totals(breakdown_usage),
    })

    t0 = time.perf_counter()
    usage = []
    review = await review_step(
        scp_text, writing, visual_by_scene, frozen_descriptor, format_guide, s, _call_gemini,
        entity_sheet=entity_sheet, label=label, usage_sink=usage,
    )
    stages.append({
        "name": "review", "latency_ms": _ms(t0),
        **_provider_fields("review", s), **trace, **_usage_totals(usage),
    })

    t0 = time.perf_counter()
    usage = []
    critic = await critic_step(
        scp_text, writing, visual_by_scene, format_guide, s, _call_gemini, label=label, usage_sink=usage,
    )
    stages.append({
        "name": "critic_agent", "latency_ms": _ms(t0),
        **_provider_fields("critic_agent", s), **trace, **_usage_totals(usage),
    })

    return writing, visual_by_scene, review, critic


async def _repair_and_review(
    scp_id: str, scp_text: str, structure: list[dict], frozen_descriptor: str,
    entity_sheet: str, story_logline: str, format_guide: str, writing: dict,
    visual_by_scene: dict, review: dict, critic: dict, indexes: list[int],
    rejected: list[dict], s: Settings, stages: list[dict], *, label: str | None = None,
) -> tuple[dict, dict, dict, dict]:
    trace = _trace_fields(2, "scene", indexes, rejected)
    originals = [writing["scenes"][idx] for idx in indexes]
    # Positional pairing, same rule as `_breakdown_for` below: the repair prompt
    # gets structure[idx] for each flagged index, never a model-reported
    # scene_num lookup (Story 12.1 AC9). An index past structure (writing
    # over-produced) degrades to {} exactly as the visual path already does.
    subset_structure = [structure[idx] if idx < len(structure) else {} for idx in indexes]
    t0 = time.perf_counter()
    usage: list[dict] = []
    repaired = await writing_scene_repair_step(
        scp_id, originals, subset_structure, _format_scene_feedback(review, critic, indexes), frozen_descriptor,
        format_guide, s, _call_gemini, label=label, usage_sink=usage,
    )
    stages.append({
        "name": "writing_scene_repair", "latency_ms": _ms(t0),
        **_provider_fields("writing_scene_repair", s), **trace, **_usage_totals(usage),
    })

    merged_scenes = list(writing["scenes"])
    for idx, scene in zip(indexes, repaired, strict=True):
        merged_scenes[idx] = {**merged_scenes[idx], **scene}
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
    stages.append({
        "name": "visual_breakdown", "latency_ms": _ms(t0), "scene_count": len(indexes),
        **_provider_fields("visual_breakdown", s), **trace, **_usage_totals(breakdown_usage),
    })

    t0 = time.perf_counter()
    usage = []
    next_review = await review_step(
        scp_text, merged_writing, merged_visuals, frozen_descriptor, format_guide, s, _call_gemini,
        entity_sheet=entity_sheet, label=label, usage_sink=usage,
    )
    stages.append({
        "name": "review", "latency_ms": _ms(t0),
        **_provider_fields("review", s), **trace, **_usage_totals(usage),
    })
    t0 = time.perf_counter()
    usage = []
    next_critic = await critic_step(
        scp_text, merged_writing, merged_visuals, format_guide, s, _call_gemini, label=label, usage_sink=usage,
    )
    stages.append({
        "name": "critic_agent", "latency_ms": _ms(t0),
        **_provider_fields("critic_agent", s), **trace, **_usage_totals(usage),
    })
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
        # Every scenario path reaches a Gemini-owned stage (writing), so check the
        # key up front rather than burning the DeepSeek research/structure calls
        # first (Story 12.2 AC2).
        if not s.gemini_api_key:
            raise RuntimeError("YTFLOW_GEMINI_API_KEY is not configured")
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
        # Resolved exactly once, here, and reused unchanged by structure, pass 1,
        # scene-scoped repair and the full-rewrite fallback — none of which
        # re-select (Story 12.4 AC2). `.get` rather than `[...]`: research_step
        # always resolves the key, but a stubbed/older research seam must degrade
        # to production's pre-12.4 template, not crash the stage. A seam that stops
        # selecting IS a selector failure, so it sets the flag too — otherwise the
        # one signal AC6 added to expose that drift reads clean while it happens.
        story_archetype = research.get("story_archetype") or STORY_ARCHETYPE_FALLBACK
        archetype_fallback_used = (
            bool(research.get("story_archetype_fallback_used")) or not research.get("story_archetype")
        )
        stages.append({
            "name": "research", "latency_ms": _ms(t0),
            "story_archetype": story_archetype,
            "story_archetype_fallback_used": archetype_fallback_used,
            **_provider_fields("research", s), **_trace_fields(1, "none", []), **_usage_totals(usage),
        })

        t0 = time.perf_counter()
        usage = []
        # Truncation here killed 6 of 6 live runs on 2026-08-05; structure_step's
        # single `_call_stage_with_retry` call re-rolls it whole, which is where
        # every stage's re-roll now lives (see reroll_on_truncation).
        structure = await structure_step(
            state["scp_id"], research, format_guide, s, _call_deepseek,
            story_archetype=story_archetype, label=label, usage_sink=usage,
        )
        stages.append({
            "name": "structure", "latency_ms": _ms(t0),
            "story_archetype": story_archetype,
            **_provider_fields("structure", s), **_trace_fields(1, "none", []), **_usage_totals(usage),
        })

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

        # Read the FINAL review/critic here, before tts_normalize rewrites
        # `writing` and both locals go out of scope unread (Story 12.3). Metrics
        # describe the text the judge saw, not the pronunciation rewrite.
        quality = _build_quality(final_pass_index, final_retry_scope, review, critic, writing)
        if warning := quality.get("warning"):
            logger.warning(
                "scenario: %s after pass %d (retry_scope=%s, critic=%s, review_pass=%s) — "
                "surfacing at the human gate, not failing the run",
                warning["code"], final_pass_index, final_retry_scope,
                quality["critic_verdict"], quality["review_overall_pass"],
            )

        t0 = time.perf_counter()
        usage = []
        writing = await tts_normalize_step(writing, format_guide, s, _call_deepseek, label=label, usage_sink=usage)
        stages.append({
            "name": "tts_normalize", "latency_ms": _ms(t0), **_provider_fields("tts_normalize", s),
            **_trace_fields(final_pass_index, final_retry_scope, final_indexes), **_usage_totals(usage),
        })

        scenes = build_scenes(writing, visual_by_scene, structure)
        _record_trace(stages=stages, total_latency_ms=_ms(t0_total))
        return {
            "scenes": scenes, "current_stage": "scenario", "error": None,
            "scenario_quality": quality,
            "story_archetype": story_archetype,
            "story_archetype_fallback_used": archetype_fallback_used,
        }
    except Exception as exc:  # noqa: BLE001 — surfaced as PipelineState.error, never raised past the node
        _record_trace(stages=stages, total_latency_ms=_ms(t0_total), error=exc)
        return {"current_stage": "scenario", "error": f"stage=scenario run_id={run_id}: {exc}"}
    finally:
        if trace_sink is not None:
            trace_sink.extend(stages)
