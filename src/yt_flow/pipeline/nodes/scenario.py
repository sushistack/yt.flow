"""scenario_node — the LLM-Director stage (Story 1.5).

Turns ``PipelineState.scp_text`` into a typed ``list[SceneState]`` by asking
DeepSeek V4 for a structured scene/shot breakdown. Pure function of state:
reads a few fields, returns only the changed ones (``scenes``, ``current_stage``,
and ``error`` on failure). No DB / SSE / gate writes and no ``interrupt()`` —
gate behaviour stays in ``gates.py``. [AD-4, AD-3]

DeepSeek is OpenAI-compatible, so we POST to ``/chat/completions`` with the
already-installed ``httpx`` client instead of adding the ``openai`` SDK.
"""

import json
import time

import httpx
from langfuse import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState, ShotData
from yt_flow.services.prompt_service import get_prompt

PROMPT_NAME = "scenario"


def _settings() -> Settings:
    # ponytail: one seam so unit tests can inject fake settings without a real .env.
    return Settings()


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


async def _call_deepseek(rendered: str, s: Settings) -> tuple[str, dict, str | None]:
    """Return (content, usage, finish_reason) from a JSON-mode chat completion.

    ``response_format=json_object`` plus the prompt's own JSON instruction keep
    the model from emitting prose; see DeepSeek JSON-mode docs.
    """
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


def _require_text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} must be a non-empty string")
    return value


def _opt_text(value: object) -> str | None:
    # Normalize optional str fields: anything non-str becomes None so a stray
    # number/list from the LLM can't violate ShotData's `str | None` contract.
    return value if isinstance(value, str) else None


def _parse_indices(raw: object, sentence_count: int | None, shot_id: str) -> list[int]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"shot {shot_id}: sentence_indices must be a non-empty list")
    for i in raw:
        # bool is an int subclass; reject it explicitly so True/False can't pose as an index.
        if not isinstance(i, int) or isinstance(i, bool) or i < 0:
            raise ValueError(f"shot {shot_id}: sentence_indices must be non-negative ints, got {i!r}")
        if sentence_count is not None and i >= sentence_count:
            raise ValueError(
                f"shot {shot_id}: sentence_index {i} out of range (0..{sentence_count - 1})"
            )
    return raw


def _parse_scenes(raw: str) -> list[SceneState]:
    """Deterministically map the DeepSeek JSON payload to ``list[SceneState]``.

    Raises ``ValueError`` on any contract violation so the node converts it into
    ``PipelineState.error`` rather than emitting partial output.
    """
    data = json.loads(raw)  # JSONDecodeError is a ValueError subclass → caught by the node
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list) or not data["scenes"]:
        raise ValueError("payload must contain a non-empty 'scenes' list")

    scenes: list[SceneState] = []
    for idx, raw_scene in enumerate(data["scenes"]):
        if not isinstance(raw_scene, dict):
            raise ValueError(f"scene[{idx}] must be an object")
        narration = _require_text(raw_scene.get("narration"), f"scene[{idx}].narration")
        raw_shots = raw_scene.get("shots")
        if not isinstance(raw_shots, list) or not raw_shots:
            raise ValueError(f"scene[{idx}].shots must be a non-empty list")

        # 'sentences' is an optional validation aid; when present it bounds the indices.
        sentences = raw_scene.get("sentences")
        sentence_count = len(sentences) if isinstance(sentences, list) else None

        shots: list[ShotData] = []
        for raw_shot in raw_shots:
            if not isinstance(raw_shot, dict):
                raise ValueError(f"scene[{idx}] has a non-object shot")
            shot_id = _require_text(raw_shot.get("shot_id"), f"scene[{idx}] shot_id")
            shots.append(ShotData(
                shot_id=shot_id,
                sentence_indices=_parse_indices(raw_shot.get("sentence_indices"), sentence_count, shot_id),
                image_prompt=_require_text(raw_shot.get("image_prompt"), f"shot {shot_id}.image_prompt"),
                negative_prompt=_require_text(raw_shot.get("negative_prompt"), f"shot {shot_id}.negative_prompt"),
                camera_angle=_opt_text(raw_shot.get("camera_angle")),
                camera_movement=_opt_text(raw_shot.get("camera_movement")),
                image_path=None,
                background_path=None,
                character_path=None,
            ))

        # scene_num is assigned positionally (idx+1), not taken from the LLM: this
        # guarantees unique, ordered numbers so downstream file naming
        # (scene_{n:03d} in tts/image) can't collide/overwrite on duplicate values.
        scenes.append(SceneState(
            scene_num=idx + 1,
            narration=narration,
            shots=shots,
            audio_path=None,
            audio_duration=None,
            word_timings=[],
            subtitle_path=None,
        ))
    return scenes


def _record_trace(*, rendered, raw, usage, model, latency_ms, error=None) -> None:
    """Best-effort enrich the current ``scenario`` span. [AD-10 — tracing is non-fatal]"""
    try:
        get_client().update_current_span(
            input=rendered,
            output=None if error is not None else raw,
            metadata={
                "model": model,
                "latency_ms": latency_ms,
                "usage": usage,
                **({"error": repr(error)} if error is not None else {}),
            },
        )
    except Exception:  # noqa: BLE001 — a tracing failure must never break the pipeline
        pass


@observe(name="scenario")
async def scenario_node(state: PipelineState) -> dict:
    run_id = state.get("run_id", "?")
    t0 = time.perf_counter()
    s: Settings | None = None
    rendered: str | None = None
    raw: str | None = None
    usage: dict = {}
    try:
        s = _settings()  # inside try: a config/env failure surfaces as PipelineState.error too
        if not s.deepseek_api_key:
            raise RuntimeError("YTFLOW_DEEPSEEK_API_KEY is not configured")
        # Prompt Hub is the single source of prompt text (FR-16); variant A/B label
        # mapping is deferred to Epic 4 — no A/B labels exist yet. ponytail.
        rendered = get_prompt(PROMPT_NAME).compile(scp_text=state["scp_text"])
        raw, usage, finish_reason = await _call_deepseek(rendered, s)
        if finish_reason == "length":
            raise ValueError("DeepSeek response truncated (finish_reason=length); raise max_tokens")
        scenes = _parse_scenes(raw)
        _record_trace(rendered=rendered, raw=raw, usage=usage, model=s.deepseek_model, latency_ms=_ms(t0))
        return {"scenes": scenes, "current_stage": "scenario"}
    except Exception as exc:  # noqa: BLE001 — surfaced as PipelineState.error, never raised past the node
        _record_trace(rendered=rendered, raw=raw, usage=usage,
                      model=s.deepseek_model if s else "?", latency_ms=_ms(t0), error=exc)
        return {"current_stage": "scenario", "error": f"stage=scenario run_id={run_id}: {exc}"}
