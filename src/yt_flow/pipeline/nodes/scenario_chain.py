"""Multi-stage LLM chain for scenario_node.

See docs/superpowers/specs/2026-07-03-scenario-multistage-design.md for the
design this implements. Each ``*_step`` function fetches its Langfuse prompt,
compiles it, calls DeepSeek via the caller-supplied ``call_deepseek`` seam
(the same ``_call_deepseek`` from ``scenario.py`` — injected as a parameter so
tests can fake it per stage), and returns a parsed+validated payload. No
exception handling here: every failure propagates to ``scenario_node``, which
converts it into ``PipelineState.error`` exactly as before.
"""

import json
import re

from yt_flow.services import prompt_service

# ponytail: fixed per the design spec — this never varies, so it's a constant,
# not a Settings field.
TARGET_DURATION_MINUTES = 3

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split narration into sentences on '.'/'?'/'!' + whitespace.

    ponytail: regex heuristic tuned to writing_step's own output style (short
    TTS-friendly sentences ending in standard punctuation), not a general
    tokenizer.
    """
    text = text.strip()
    if not text:
        return []
    return [p.strip() for p in _SENTENCE_BOUNDARY.split(text) if p.strip()]


async def _call_stage(prompt_name: str, variables: dict, s, call_deepseek) -> str:
    """Fetch + compile a Langfuse prompt, call DeepSeek, return raw JSON text.

    Raises on truncation (finish_reason == "length") so a caller never has to
    special-case a partial payload — json.loads on it would fail anyway, but
    this gives a clearer error message.
    """
    rendered = prompt_service.get_prompt(prompt_name).compile(**variables)
    raw, _usage, finish_reason = await call_deepseek(rendered, s)
    if finish_reason == "length":
        raise ValueError(f"{prompt_name} response truncated (finish_reason=length); raise max_tokens")
    return raw


async def research_step(scp_id: str, scp_text: str, format_guide: str, s, call_deepseek) -> dict:
    raw = await _call_stage(
        "scenario/research",
        {
            "scp_id": scp_id,
            "scp_fact_sheet": scp_text,
            "main_text": scp_text,
            "format_guide": format_guide,
            "glossary_section": "",
        },
        s,
        call_deepseek,
    )
    data = json.loads(raw)
    if not isinstance(data, dict) or not str(data.get("frozen_descriptor") or "").strip():
        raise ValueError("research: payload missing non-empty 'frozen_descriptor'")
    return data


async def structure_step(scp_id: str, research: dict, format_guide: str, s, call_deepseek) -> list[dict]:
    raw = await _call_stage(
        "scenario/structure",
        {
            "scp_id": scp_id,
            "research_packet": json.dumps(research, ensure_ascii=False),
            "scp_visual_reference": research["frozen_descriptor"],
            "target_duration": TARGET_DURATION_MINUTES,
            "format_guide": format_guide,
            "glossary_section": "",
        },
        s,
        call_deepseek,
    )
    data = json.loads(raw)
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("structure: payload must contain a non-empty 'scenes' list")
    return scenes
