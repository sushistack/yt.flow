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
    build_scenes,
    critic_step,
    research_step,
    review_step,
    split_sentences,
    structure_step,
    tts_normalize_step,
    visual_breakdown_step,
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


async def _call_deepseek(rendered: str, s: Settings) -> tuple[str, dict, str | None]:
    """Return (content, usage, finish_reason) from a JSON-mode chat completion."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        resp = await client.post(
            f"{s.deepseek_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {s.deepseek_api_key}"},
            json={
                "model": s.deepseek_model,
                "messages": [{"role": "user", "content": rendered}],
                "response_format": {"type": "json_object"},
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
                **({"error": repr(error)} if error is not None else {}),
            },
        )
    except Exception:  # noqa: BLE001 — a tracing failure must never break the pipeline
        pass


def _format_feedback(review: dict, critic: dict) -> str:
    lines = [critic.get("feedback", "")]
    for issue in review.get("issues", []):
        lines.append(f"- Scene {issue.get('scene_num')}: {issue.get('description')} -> {issue.get('correction')}")
    return "\n".join(line for line in lines if line)


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
) -> tuple[dict, dict, dict, dict]:
    t0 = time.perf_counter()
    writing = await writing_step(scp_id, structure, frozen_descriptor, format_guide, quality_feedback, s, _call_deepseek, label=label)
    stages.append({"name": "writing", "latency_ms": _ms(t0)})

    t0 = time.perf_counter()

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
        shots = await visual_breakdown_step(
            scene, sentences, frozen_descriptor, entity_sheet, story_logline, scene_role, s, _call_deepseek, label=label
        )
        return idx, shots  # positional key — never trust the LLM's own scene_num for lookups

    results = await asyncio.gather(*(_breakdown_for(idx, scene) for idx, scene in enumerate(writing["scenes"])))
    visual_by_scene = dict(results)
    stages.append({"name": "visual_breakdown", "latency_ms": _ms(t0), "scene_count": len(visual_by_scene)})

    t0 = time.perf_counter()
    review = await review_step(scp_text, writing, visual_by_scene, frozen_descriptor, format_guide, s, _call_deepseek, label=label)
    stages.append({"name": "review", "latency_ms": _ms(t0)})

    t0 = time.perf_counter()
    critic = await critic_step(writing, visual_by_scene, format_guide, s, _call_deepseek, label=label)
    stages.append({"name": "critic_agent", "latency_ms": _ms(t0)})

    return writing, visual_by_scene, review, critic


@observe(name="scenario")
async def scenario_node(state: PipelineState) -> dict:
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
        research = await research_step(state["scp_id"], state["scp_text"], format_guide, s, _call_deepseek, label=label)
        stages.append({"name": "research", "latency_ms": _ms(t0)})

        t0 = time.perf_counter()
        structure = await structure_step(state["scp_id"], research, format_guide, s, _call_deepseek, label=label)
        stages.append({"name": "structure", "latency_ms": _ms(t0)})

        writing, visual_by_scene, review, critic = await _write_and_review(
            state["scp_id"], state["scp_text"], structure, research["frozen_descriptor"],
            research.get("entity_sheet", ""), research.get("story_logline", ""),
            format_guide, "", s, stages, label=label,
        )

        if critic["verdict"] == "retry" or not review["overall_pass"]:
            feedback = _format_feedback(review, critic)
            writing, visual_by_scene, review, critic = await _write_and_review(
                state["scp_id"], state["scp_text"], structure, research["frozen_descriptor"],
                research.get("entity_sheet", ""), research.get("story_logline", ""),
                format_guide, feedback, s, stages, label=label,
            )

        t0 = time.perf_counter()
        writing = await tts_normalize_step(writing, format_guide, s, _call_deepseek, label=label)
        stages.append({"name": "tts_normalize", "latency_ms": _ms(t0)})

        scenes = build_scenes(writing, visual_by_scene, structure)
        _record_trace(stages=stages, total_latency_ms=_ms(t0_total))
        return {"scenes": scenes, "current_stage": "scenario", "error": None}
    except Exception as exc:  # noqa: BLE001 — surfaced as PipelineState.error, never raised past the node
        _record_trace(stages=stages, total_latency_ms=_ms(t0_total), error=exc)
        return {"current_stage": "scenario", "error": f"stage=scenario run_id={run_id}: {exc}"}
