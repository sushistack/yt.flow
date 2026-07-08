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
import logging
import re
from typing import cast

from yt_flow.domain.state import (
    CastDepth,
    CastMember,
    CastPose,
    CastPosition,
    CharacterMotionEnergy,
    CharacterMotionStyle,
    LOCATION_KEYS,
    LocationKey,
    STOCK_CAST_KEYS,
    SceneState,
    ShotData,
)
from yt_flow.pipeline.nodes.sound_design import MOOD_VALUES, resolve_mood
from yt_flow.services import prompt_service

logger = logging.getLogger(__name__)

# ponytail: fixed per the design spec — this never varies, so it's a constant,
# not a Settings field.
TARGET_DURATION_MINUTES = 3

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_SCP_PREFIX_RE = re.compile(r"^scp-", re.IGNORECASE)
_STOCK_CANONICAL = {key.lower(): key for key in STOCK_CAST_KEYS}
_VALID_POSITIONS = {"left", "center", "right"}
_VALID_DEPTHS = {"near", "mid", "far"}
_VALID_POSES = {"standing", "sitting"}
_POSE_HINT_MAX_CHARS = 80
_VALID_MOTION_STYLES = {"hold", "breath", "sway", "tremble", "pulse", "glitch"}
_VALID_MOTION_ENERGIES = {"low", "medium", "high"}
_VALID_LOCATION_KEYS = set(LOCATION_KEYS)


def _normalize_card_key(card_key: str) -> str:
    """Epic 8 Interfaces rule 5: normalize case on known key shapes; anything
    else passes through as-is for downstream DB resolution."""
    card_key = card_key.strip()
    canonical_stock = _STOCK_CANONICAL.get(card_key.lower())
    if canonical_stock:
        return canonical_stock
    if _SCP_PREFIX_RE.match(card_key):
        return "SCP-" + card_key[4:]
    return card_key


def _parse_pose_hint(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    hint = raw.strip()
    return hint if 0 < len(hint) <= _POSE_HINT_MAX_CHARS else None


def _normalize_enum(raw: object, valid: set[str], fallback: str) -> str:
    if not isinstance(raw, str):
        return fallback
    value = raw.strip().lower()
    return value if value in valid else fallback


def _parse_motion_field(entry: dict, key: str, valid: set[str], default: str) -> str | None:
    """Story 8.8 leniency rule, distinct from pose_hint's omit-on-invalid: a key
    ABSENT from the raw payload stays absent (downstream default applies at
    render time); a key PRESENT but invalid is normalized and included
    explicitly so behavior is never implicit."""
    if key not in entry:
        return None
    raw = entry.get(key)
    value = raw.strip().lower() if isinstance(raw, str) else ""
    return value if value in valid else default


def parse_cast(raw: object) -> list[CastMember]:
    """Normalize a visual_breakdown shot's raw ``cast`` payload (Epic 8
    Interfaces rules 4-6). Never raises — a taxonomy violation degrades
    (drop the entry / fall back to a default), it never fails the scenario
    stage (D1 lesson, same philosophy as ``resolve_mood``).
    """
    if not isinstance(raw, list):
        return []
    members: list[CastMember] = []
    for entry in raw:
        if not isinstance(entry, dict):
            logger.warning("parse_cast: dropping non-dict cast entry %r", entry)
            continue
        card_key = entry.get("card_key")
        if not isinstance(card_key, str) or not card_key.strip():
            logger.warning("parse_cast: dropping cast entry with unusable card_key %r", entry)
            continue
        position = cast(CastPosition, _normalize_enum(entry.get("position"), _VALID_POSITIONS, "center"))
        depth = cast(CastDepth, _normalize_enum(entry.get("depth"), _VALID_DEPTHS, "mid"))
        pose = cast(CastPose, _normalize_enum(entry.get("pose"), _VALID_POSES, "standing"))
        member = CastMember(card_key=_normalize_card_key(card_key), position=position, depth=depth, pose=pose)
        pose_hint = _parse_pose_hint(entry.get("pose_hint"))
        if pose_hint is not None:
            member["pose_hint"] = pose_hint
        motion_style = _parse_motion_field(entry, "motion_style", _VALID_MOTION_STYLES, "breath")
        if motion_style is not None:
            member["motion_style"] = cast(CharacterMotionStyle, motion_style)
        motion_energy = _parse_motion_field(entry, "motion_energy", _VALID_MOTION_ENERGIES, "medium")
        if motion_energy is not None:
            member["motion_energy"] = cast(CharacterMotionEnergy, motion_energy)
        members.append(member)
    return members


def parse_location_key(raw: object) -> LocationKey | None:
    """Story 8.5 leniency rule: a taxonomy violation degrades to generation,
    it never fails the scenario stage (same philosophy as ``parse_cast``).

    Non-string / ``None`` / missing -> ``None`` with no warning (absence is
    normal — most shots are entity-specific and never emit this field).
    A string outside the closed vocabulary -> ``None`` with a warning.
    """
    if not isinstance(raw, str):
        return None
    if raw not in _VALID_LOCATION_KEYS:
        logger.warning("visual_breakdown emitted unknown location_key %r, falling back to generation", raw)
        return None
    return cast(LocationKey, raw)


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


async def _call_stage(prompt_name: str, variables: dict, s, call_deepseek, *, label: str | None = None) -> str:
    """Fetch + compile a Langfuse prompt, call DeepSeek, return raw JSON text.

    Raises on truncation (finish_reason == "length") so a caller never has to
    special-case a partial payload — json.loads on it would fail anyway, but
    this gives a clearer error message.

    `label` is the A/B variant's Langfuse label (Story 6.1) — `None` (variant
    A / no variant) must go through `prompt_service.get_prompt` unchanged, not
    `get_prompt_with_fallback`, so existing tests that monkeypatch
    `prompt_service.get_prompt` keep working.
    """
    prompt = (
        prompt_service.get_prompt_with_fallback(prompt_name, label=label)
        if label
        else prompt_service.get_prompt(prompt_name)
    )
    rendered = prompt.compile(**variables)
    raw, _usage, finish_reason = await call_deepseek(rendered, s)
    if finish_reason == "length":
        raise ValueError(f"{prompt_name} response truncated (finish_reason=length); raise max_tokens")
    return raw


async def research_step(scp_id: str, scp_text: str, format_guide: str, s, call_deepseek, *, label: str | None = None) -> dict:
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
        label=label,
    )
    data = json.loads(raw)
    if not isinstance(data, dict) or not str(data.get("frozen_descriptor") or "").strip():
        raise ValueError("research: payload missing non-empty 'frozen_descriptor'")
    # entity_sheet/story_logline are new fields (this story). A prompt version still
    # running under the pre-existing production label (label=None) simply omits the
    # key, and that must not break variant A/None (AC5) — absence is only checked
    # when we're intentionally using the candidate prompt that promises these fields.
    for key in ("entity_sheet", "story_logline"):
        if key not in data:
            if label:
                raise ValueError(f"research: payload missing non-empty '{key}'")
            continue
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"research: payload missing non-empty '{key}'")
    return data


async def structure_step(scp_id: str, research: dict, format_guide: str, s, call_deepseek, *, label: str | None = None) -> list[dict]:
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
        label=label,
    )
    data = json.loads(raw)
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("structure: payload must contain a non-empty 'scenes' list")
    # title (Story 5.17 chapter-card text) is promised by the candidate prompt only;
    # variant A/None keeps running the pre-promotion prompt, which doesn't emit it yet
    # — absence there is backward-compat noise, not a regression (mirrors research_step).
    if label:
        for scene in scenes:
            if not isinstance(scene, dict) or not str(scene.get("title") or "").strip():
                num = scene.get("scene_num") if isinstance(scene, dict) else "?"
                raise ValueError(f"structure: scene[{num}] missing non-empty 'title'")
    return scenes


async def writing_step(
    scp_id: str,
    structure: list[dict],
    frozen_descriptor: str,
    format_guide: str,
    quality_feedback: str,
    s,
    call_deepseek,
    *,
    label: str | None = None,
) -> dict:
    raw = await _call_stage(
        "scenario/writing",
        {
            "scp_id": scp_id,
            "scene_structure": json.dumps(structure, ensure_ascii=False),
            "scp_visual_reference": frozen_descriptor,
            "format_guide": format_guide,
            "glossary_section": "",
            "quality_feedback": quality_feedback,
        },
        s,
        call_deepseek,
        label=label,
    )
    data = json.loads(raw)
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("writing: payload must contain a non-empty 'scenes' list")
    for scene in scenes:
        if not str(scene.get("narration") or "").strip():
            raise ValueError(f"writing: scene[{scene.get('scene_num')}] has empty narration")
    return data


def _scene_role_text(scene_role: object) -> str:
    """Compact 'act / emotional_beat: synopsis' string from a structure_step scene entry.

    ``scene_role`` is a raw structure_step list element (LLM-derived JSON) indexed
    positionally by the caller — guard against it not being a dict at all.
    """
    if not isinstance(scene_role, dict):
        return ""
    parts = [
        str(scene_role.get("act") or ""),
        str(scene_role.get("emotional_beat") or ""),
    ]
    role = " / ".join(p for p in parts if p)
    synopsis = str(scene_role.get("synopsis") or "")
    return f"{role}: {synopsis}" if role and synopsis else role or synopsis


async def cast_decision_step(
    scp_id: str,
    scene: dict,
    sentences: list[str],
    s,
    call_deepseek,
    *,
    label: str | None = None,
) -> dict[int, list]:
    """Decide per-sentence cast in its own focused call, isolated from the
    much larger cinematography task (Story 8.10).

    Root cause this exists to fix: asking the LLM to *simultaneously* compose
    an 8-slot background prompt AND decide+emit a `cast` array in the same
    call reliably failed — deepseek-v4-flash reverted to the pre-8.1
    `entity_visible` boolean schema and wrote full character prose into
    `image_prompt` regardless of prompt strengthening (0/125 shots in 8.1's
    own hand inspection; reproduced live here against the exact production
    call shape, with and without `thinking` disabled). The same model
    reliably emits correct `cast` JSON when the ONLY thing it's asked to do
    is decide cast. Splitting the call is the fix — not more prompt text on
    the combined call.

    Returns ``{sentence_number: cast_list}`` (1-based, raw/unvalidated member
    dicts — ``parse_cast`` in ``build_scenes`` does the actual leniency
    validation once merged onto a shot).
    """
    numbered = "\n".join(f"{i + 1}. {sent}" for i, sent in enumerate(sentences))
    raw = await _call_stage(
        "scenario/cast_decision",
        {
            "scene_num": scene["scene_num"],
            "scp_id": scp_id,
            "stock_cast_keys": ", ".join(STOCK_CAST_KEYS),
            "characters_present": json.dumps(scene.get("characters_present", []), ensure_ascii=False),
            "numbered_sentences": numbered,
            "sentence_count": len(sentences),
        },
        s,
        call_deepseek,
        label=label,
    )
    data = json.loads(raw)
    entries = data.get("shots") if isinstance(data, dict) else None
    if not isinstance(entries, list) or len(entries) != len(sentences):
        raise ValueError(
            f"cast_decision: expected 1:1 sentence-to-entry mapping "
            f"({len(sentences)} sentences), got {len(entries) if isinstance(entries, list) else 'non-list'}"
        )
    result: dict[int, list] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"cast_decision: malformed entry {entry!r}")
        sentence_num = entry.get("sentence")
        if not isinstance(sentence_num, int):
            raise ValueError(f"cast_decision: malformed sentence number {sentence_num!r}")
        if sentence_num in result:
            raise ValueError(f"cast_decision: duplicate sentence {sentence_num}")
        cast = entry.get("cast")
        if not isinstance(cast, list):
            raise ValueError(f"cast_decision: sentence {sentence_num} cast must be a list")
        result[sentence_num] = cast
    expected = set(range(1, len(sentences) + 1))
    if set(result) != expected:
        raise ValueError(
            f"cast_decision: sentence coverage mismatch; expected {sorted(expected)}, got {sorted(result)}"
        )
    return result


async def visual_breakdown_step(
    scp_id: str,
    scene: dict,
    sentences: list[str],
    cast_by_sentence: dict[int, list],
    frozen_descriptor: str,
    entity_sheet: str,
    story_logline: str,
    scene_role: object,
    s,
    call_deepseek,
    *,
    label: str | None = None,
) -> list[dict]:
    numbered = "\n".join(f"{i + 1}. {sent}" for i, sent in enumerate(sentences))
    raw = await _call_stage(
        "scenario/visual_breakdown",
        {
            "scene_num": scene["scene_num"],
            "location": scene["location"],
            "characters_present": json.dumps(scene.get("characters_present", []), ensure_ascii=False),
            "color_palette": scene["color_palette"],
            "atmosphere": scene["atmosphere"],
            "scp_visual_reference": frozen_descriptor,
            "entity_sheet": entity_sheet,
            "story_logline": story_logline,
            "scene_role": _scene_role_text(scene_role),
            "character_visual_context": "",
            "scp_id": scp_id,
            "narration": scene.get("narration", ""),
            "numbered_sentences": numbered,
            "sentence_count": len(sentences),
            "cast_by_sentence": json.dumps(cast_by_sentence, ensure_ascii=False, indent=2),
            "location_keys": ", ".join(LOCATION_KEYS),
        },
        s,
        call_deepseek,
        label=label,
    )
    data = json.loads(raw)
    shots = data.get("visual_descriptions") if isinstance(data, dict) else None
    if not isinstance(shots, list) or len(shots) != len(sentences):
        raise ValueError(
            f"visual_breakdown: expected 1:1 sentence-to-shot mapping "
            f"({len(sentences)} sentences), got {len(shots) if isinstance(shots, list) else 'non-list'}"
        )
    # Cast is decided authoritatively by cast_decision_step (Story 8.10) — attach
    # it here regardless of anything the model echoed, keyed by sentence_start.
    for shot in shots:
        if isinstance(shot, dict):
            sentence_start = shot.get("sentence_start")
            if not isinstance(sentence_start, int):
                raise ValueError(f"visual_breakdown: invalid sentence_start {sentence_start!r}")
            shot["cast"] = cast_by_sentence.get(sentence_start, [])
    return shots


_VALID_VERDICTS = {"pass", "retry", "accept_with_notes"}


async def review_step(
    scp_text: str,
    writing: dict,
    visual_by_scene: dict,
    frozen_descriptor: str,
    format_guide: str,
    s,
    call_deepseek,
    *,
    label: str | None = None,
) -> dict:
    raw = await _call_stage(
        "scenario/review",
        {
            "scp_id": writing.get("scp_id", ""),
            "scp_fact_sheet": scp_text,
            "narration_script": json.dumps(writing, ensure_ascii=False),
            "visual_descriptions": json.dumps(visual_by_scene, ensure_ascii=False),
            "scp_visual_reference": frozen_descriptor,
            "format_guide": format_guide,
            "glossary_section": "",
        },
        s,
        call_deepseek,
        label=label,
    )
    data = json.loads(raw)
    if not isinstance(data, dict) or "overall_pass" not in data:
        raise ValueError("review: payload missing 'overall_pass'")
    return data


async def critic_step(writing: dict, visual_by_scene: dict, format_guide: str, s, call_deepseek, *, label: str | None = None) -> dict:
    scenario_json = {"writing": writing, "visual_descriptions": visual_by_scene}
    raw = await _call_stage(
        "scenario/critic_agent",
        {
            "format_guide": format_guide,
            "scenario_json": json.dumps(scenario_json, ensure_ascii=False),
        },
        s,
        call_deepseek,
        label=label,
    )
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("verdict") not in _VALID_VERDICTS:
        raise ValueError(f"critic_agent: payload has invalid 'verdict' (must be one of {_VALID_VERDICTS})")
    return data


async def tts_normalize_step(writing: dict, format_guide: str, s, call_deepseek, *, label: str | None = None) -> dict:
    """Rewrite each scene's narration for natural Korean TTS, matching scenes positionally.

    A scene whose normalized sentence count doesn't match the original (per
    ``split_sentences()``) keeps its original narration instead of failing the
    whole scenario stage — see story 5-4-tts-korean-naturalization.md.
    """
    original_scenes = writing["scenes"]
    scenes_input = [
        {"scene_num": scene.get("scene_num"), "narration": scene.get("narration", "")} for scene in original_scenes
    ]
    raw = await _call_stage(
        "scenario/tts_normalize",
        {
            "scenes_json": json.dumps(scenes_input, ensure_ascii=False),
            "format_guide": format_guide,
        },
        s,
        call_deepseek,
        label=label,
    )
    data = json.loads(raw)
    normalized_scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(normalized_scenes, list) or len(normalized_scenes) != len(original_scenes):
        got = len(normalized_scenes) if isinstance(normalized_scenes, list) else "non-list"
        raise ValueError(f"tts_normalize: expected {len(original_scenes)} scenes, got {got}")

    updated_scenes = []
    for idx, (original_scene, normalized_scene) in enumerate(zip(original_scenes, normalized_scenes)):
        original_narration = original_scene.get("narration", "")
        normalized_narration = str(normalized_scene.get("narration") or "")
        if len(split_sentences(original_narration)) != len(split_sentences(normalized_narration)):
            logger.warning(
                "tts_normalize: scene %d sentence-count mismatch (original=%d, normalized=%d); keeping original narration",
                idx + 1,
                len(split_sentences(original_narration)),
                len(split_sentences(normalized_narration)),
            )
            # Mismatch degrades to single-track: display == spoken == original (AC:2).
            updated_scenes.append({**original_scene, "display_narration": original_narration})
            continue
        updated_scenes.append(
            {**original_scene, "narration": normalized_narration, "display_narration": original_narration}
        )

    return {**writing, "scenes": updated_scenes}


def _fallback_prompt(scene: dict) -> str:
    """Minimal prompt for a leading transition-only sentence with nothing to merge into."""
    location = scene.get("location") or "an unmarked containment area"
    atmosphere = scene.get("atmosphere") or "tense silence"
    return f"static wide shot, {location}, {atmosphere}, no visible subject"


def _first_line(value: object) -> str:
    """First non-empty line of a stripped string, or "" — the chapter-card
    typography-restraint rule (Story 5.17 AC:4) enforced at data-assembly time."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text.splitlines()[0].strip() if text else ""


def build_scenes(writing: dict, visual_by_scene: dict, structure: list[dict]) -> list:
    """Convert the chain's per-scene narration + visual_descriptions into PipelineState.scenes.

    A shot with an empty ``image_prompt`` (yt.pipe's transition/effect-only
    sentence marker) is merged into the previous shot's ``sentence_indices``
    instead of becoming its own ``ShotData`` — yt.flow's image_node needs a
    real prompt for every shot it renders.

    ``mood`` comes from the **structure** scene at the same positional index
    (structure_step's prompt is the only one that enforces the mood enum) —
    the writing stage's own ``mood`` output is ignored. Same 1:1 positional
    rule ``_write_and_review`` uses for ``scene_role``.
    """
    scenes: list = []
    for idx, writing_scene in enumerate(writing["scenes"]):
        scene_num = idx + 1  # positional, matches scenario.py's pre-existing rule
        raw_shots = visual_by_scene[idx]  # positional — matches _write_and_review's keying

        structure_scene = structure[idx] if idx < len(structure) else None
        raw_mood = structure_scene.get("mood") if isinstance(structure_scene, dict) else None
        if isinstance(raw_mood, str):
            raw_mood = raw_mood.strip().lower()
        if raw_mood not in MOOD_VALUES:
            logger.warning("scenario: scene %d mood %r not in %s; falling back to default", scene_num, raw_mood, MOOD_VALUES)
        mood = resolve_mood(raw_mood)
        title = _first_line(structure_scene.get("title")) if isinstance(structure_scene, dict) else ""
        kicker = _first_line(structure_scene.get("kicker")) if isinstance(structure_scene, dict) else ""

        shots: list = []
        for i, raw_shot in enumerate(raw_shots):
            sentence_idx = raw_shot["sentence_start"] - 1  # 1-based -> 0-based
            image_prompt = str(raw_shot.get("image_prompt") or "").strip()

            if not image_prompt:
                if shots:
                    shots[-1]["sentence_indices"].append(sentence_idx)
                    continue
                # No previous shot to merge into (leading transition sentence) — backfill.
                image_prompt = _fallback_prompt(writing_scene)
                # "no visible subject" backfill prompt — cast is always empty here,
                # regardless of what the LLM emitted for this transition sentence.
                raw_shot = {**raw_shot, "negative_prompt": raw_shot.get("negative_prompt") or "", "cast": []}

            shots.append(
                ShotData(
                    shot_id=f"S{scene_num:03d}{i:02d}",
                    sentence_indices=[sentence_idx],
                    image_prompt=image_prompt,
                    negative_prompt=str(raw_shot.get("negative_prompt") or ""),
                    camera_angle=raw_shot.get("camera_type") if isinstance(raw_shot.get("camera_type"), str) else None,
                    camera_movement=None,  # yt.pipe's visual_breakdown has no equivalent field
                    image_path=None,
                    cast=parse_cast(raw_shot.get("cast")),
                    location_key=parse_location_key(raw_shot.get("location_key")),
                )
            )

        if not shots:
            raise ValueError(f"scene[{scene_num}]: no shots produced after merge")

        scenes.append(
            SceneState(
                scene_num=scene_num,
                narration=writing_scene["narration"],
                shots=shots,
                audio_path=None,
                audio_duration=None,
                word_timings=[],
                subtitle_path=None,
                mood=mood,
                title=title,
                kicker=kicker,
                display_narration=str(writing_scene.get("display_narration") or writing_scene["narration"]),
            )
        )
    return scenes
