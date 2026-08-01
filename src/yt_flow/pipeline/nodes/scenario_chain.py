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
import time
from pathlib import Path
from typing import Any, cast

import yaml

from yt_flow.domain.state import (
    CAMERA_ARCHETYPES,
    CastDepth,
    CastMember,
    CastPose,
    CastPosition,
    CharacterMotionEnergy,
    CharacterMotionStyle,
    CharacterMovementDirection,
    CharacterMovementMode,
    CharacterMovementPace,
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
_VALID_MOVEMENT_MODES = {"anchored", "drift", "enter", "exit", "cross", "approach", "retreat"}
_VALID_MOVEMENT_DIRECTIONS = {"none", "left", "right", "in", "out"}
_VALID_MOVEMENT_PACES = {"slow", "medium", "fast"}
_LOCATION_KEY_CANONICAL = {key.lower(): key for key in LOCATION_KEYS}

# Story 8.18 R2: a single repeat stays legal — the prompt allows a continuous
# beat; only the 3rd identical (position, depth) shot in a row is repaired.
_MAX_CONSECUTIVE_SAME_PLACEMENT = 2
# Story 8.18 slot-reassignment preference: opposing third first (8.12's
# opposing-thirds composition rule), then whatever remains.
_SLOT_PREFERENCES = {
    "left": ("right", "center"),
    "right": ("left", "center"),
    "center": ("left", "right"),
}

# Story 11.2: mood → camera-archetype preference order. First entry is the
# scene's per-shot default; the rest is _enforce_camera_variety's reassignment
# order. CAMERA_ prefix keeps this apart from _VALID_MOVEMENT_MODES — that
# "drift" is a cast movement_mode (8.9), this one is a camera archetype.
# ponytail: tuned starting point (research §4.4 motion-mood grammar), expect
# live iteration. Story 11.3's per-archetype noise profiles live in
# camera_path.CAMERA_NOISE_PROFILES (video can't import this module — LLM
# stack), keyed by the archetypes this table selects — the mood→noise link
# runs through the archetype, not through this dict.
CAMERA_PREFERENCES: dict[str, tuple[str, ...]] = {
    "dread": ("push_in", "drift", "locked"),
    "clinical": ("locked", "drift", "pull_back"),
    # Story 11.3 shipped the real fBm shake, so shake and push_in now render
    # distinct final chains (shake-profile noise on top of the same in-center
    # base push) — drift-before-push_in is kept as-is; reordering is a live-
    # tuning call, not a correctness need anymore.
    "escalation": ("shake", "drift", "push_in"),
    "revelation": ("push_in", "pull_back", "drift"),
}
# resolve_mood only guarantees a MOOD_VALUES member; keep keys in lockstep or a
# taxonomy change silently turns into a runtime KeyError here (7.2 invariant).
assert set(CAMERA_PREFERENCES) == set(MOOD_VALUES)
assert {a for prefs in CAMERA_PREFERENCES.values() for a in prefs} == set(CAMERA_ARCHETYPES)


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


def _repair_movement(mode: str, direction: str, position: str) -> str:
    """Interfaces compatibility-repair table (Story 8.9): an incompatible
    mode/direction pair normalizes, it never fails the scenario stage."""
    if mode in ("anchored", "drift"):
        return "none"
    if mode == "approach":
        return "in"
    if mode == "retreat":
        return "out"
    if mode == "cross":
        # An explicit direction on the same side as position is degenerate
        # (start/end thirds coincide -> zero-amplitude "cross"), so only a
        # genuinely different side passes through; same-side/none fall back
        # to the opposite-of-position default.
        if direction in ("left", "right") and direction != position:
            return direction
        if position == "left":
            return "right"
        if position == "right":
            return "left"
        return "right"  # center defaults to right
    if direction in ("left", "right"):
        return direction
    if mode in ("enter", "exit"):
        return "right" if position == "right" else "left"
    return direction


def _resolve_camera_movement(raw: object, mood: str) -> str:
    """Story 11.2: a valid LLM archetype override wins; absent falls back to
    the mood default silently, present-but-invalid falls back with a warning
    (resolve_mood philosophy — no violation ever fails the scenario stage)."""
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in CAMERA_ARCHETYPES:
            return value
    if raw is not None:
        logger.warning(
            "scenario: camera_movement %r not in %s; using mood default", raw, CAMERA_ARCHETYPES
        )
    return CAMERA_PREFERENCES[mood][0]


def _enforce_camera_variety(shots: list, mood: str) -> None:
    """Story 11.2 AC4: within a scene, no two adjacent shots may share a
    ``camera_movement`` value — the later shot is deterministically reassigned
    to the first entry of the mood's preference order that differs from its
    predecessor. No LLM re-call (8.9 ``_repair_movement`` repair lineage), and
    LLM overrides are reassigned the same way — the ban is absolute.

    Archetype-level enforcement satisfies the epics' "archetype+direction"
    ban: drift is the only direction-bearing archetype and drift-drift
    adjacency is itself banned, so "same archetype + same direction" can
    never arise.

    Scene boundaries are deliberately not checked: 5.16's dip-to-black act
    break severs visual continuity between scenes, so within-scene variety
    is sufficient.

    Mutates only the shot dicts build_scenes just created — never an input
    state object [AD-4].
    """
    for prev, cur in zip(shots, shots[1:]):
        if cur["camera_movement"] == prev["camera_movement"]:
            replacement = next(a for a in CAMERA_PREFERENCES[mood] if a != prev["camera_movement"])
            logger.info(
                "scenario: shot %s camera %r duplicates predecessor; reassigned to %r",
                cur["shot_id"], cur["camera_movement"], replacement,
            )
            cur["camera_movement"] = replacement


def _reassign_position(member: dict, shot_id: object, rule: str, new_position: str) -> None:
    """Move a cast member to ``new_position`` and re-derive its
    ``movement_direction`` (Story 8.18 AC5): parse_cast computed the direction
    against the OLD position, and a stale one can be degenerate after the move
    (e.g. a ``cross`` whose direction now matches its start third)."""
    logger.info(
        "scenario: shot %s cast %s position %r %s; reassigned to %r",
        shot_id, member.get("card_key"), member.get("position"), rule, new_position,
    )
    member["position"] = new_position
    if "movement_mode" in member:
        member["movement_direction"] = _repair_movement(
            member.get("movement_mode", "anchored"),
            member.get("movement_direction", "none"),
            new_position,
        )


def _enforce_cast_diversity(shots: list) -> None:
    """Story 8.18: deterministic repair of the placement-diversity rules the
    cast_decision prompt teaches (8.12 Composition section) — code backstop,
    no LLM re-call (8.9 ``_repair_movement`` / 11.2 ``_enforce_camera_variety``
    repair lineage). Mark-targeted (6.11 lesson): only a violating member's
    violating field changes; siblings, other shots, and untouched fields stay
    byte-identical.

    R1 — no two members of one shot share a ``position`` slot; later members
    (list order) move to a free slot, opposing third first. With 4+ members
    all 3 slots fill and the rest keep their slot (3-slot renderer limit).
    R3 — the two explicit "never" camera↔depth pairings (visual_breakdown.md):
    ``wide`` + strict-majority ``near`` demotes those members to ``mid``;
    ``close-up``/``over-the-shoulder`` + a lone ``far`` member promotes it to
    ``mid``. Depth side only — ``camera_angle`` is baked into the rendered
    background and entity angle selection.
    R2 — a card_key repeating an identical (position, depth) for more than
    ``_MAX_CONSECUTIVE_SAME_PLACEMENT`` consecutive shots gets its position
    moved to a free slot (respecting R1 occupancy). Position-only.
    # ponytail: breaking the slot repetition suffices visually; repairing
    # depth would fight the 8.12-calibrated "mostly mid" distribution.

    Pass order per shot: R1 first so slot occupancy is settled, R3 before R2
    so R2's run tracking sees final depths — an R3 demotion behind R2's back
    could complete a >2 run and break idempotence (AC6). Neither R3 nor R2
    can reintroduce stacking: R3 never touches position, R2 only moves onto
    free slots.

    Scene boundaries are deliberately not checked: 5.16's dip-to-black act
    break severs visual continuity between scenes (same rationale as
    ``_enforce_camera_variety``).

    Mutates only the shot dicts build_scenes just created — never an input
    state object [AD-4]. Never raises — a garbage member or shot is skipped
    (D1 lesson, resolve_mood philosophy: violations degrade or repair, the
    scenario stage never fails).
    """
    runs: dict[str, tuple[str, object, int]] = {}
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        shot_id = shot.get("shot_id")
        raw_cast = shot.get("cast")
        members = [
            m for m in (raw_cast if isinstance(raw_cast, list) else [])
            if isinstance(m, dict) and m.get("position") in _VALID_POSITIONS
        ]

        # R1 — within-shot slot stacking ban.
        occupied: set[str] = set()
        for i, member in enumerate(members):
            position = member["position"]
            if position not in occupied:
                occupied.add(position)
                continue
            # A slot a later member still legitimately claims is not free —
            # repairing onto it would cascade-displace a healthy sibling
            # (6.11 mark-targeted lesson: only violating members move).
            reserved = {m["position"] for m in members[i + 1 :]} - occupied
            free = [
                slot
                for slot in _SLOT_PREFERENCES[position]
                if slot not in occupied and slot not in reserved
            ]
            if not free:
                logger.info(
                    "scenario: shot %s has more cast than the 3 position slots; remaining members keep their slot",
                    shot_id,
                )
                break
            _reassign_position(member, shot_id, "stacks with an earlier member (R1)", free[0])
            occupied.add(free[0])

        # R3 — the two explicit camera_angle↔depth "never" pairings, depth side only.
        camera_angle = shot.get("camera_angle")
        if camera_angle == "wide":
            near = [m for m in members if m.get("depth") == "near"]
            if 2 * len(near) > len(members):  # strict majority
                for member in near:
                    logger.info(
                        "scenario: shot %s cast %s depth 'near' contradicts 'wide' camera (R3); demoted to 'mid'",
                        shot_id, member.get("card_key"),
                    )
                    member["depth"] = "mid"
        elif camera_angle in ("close-up", "over-the-shoulder"):
            if len(members) == 1 and members[0].get("depth") == "far":
                logger.info(
                    "scenario: shot %s cast %s lone depth 'far' contradicts %r camera (R3); promoted to 'mid'",
                    shot_id, members[0].get("card_key"), camera_angle,
                )
                members[0]["depth"] = "mid"

        # R2 — consecutive-repeat cap per card_key, on final positions + depths.
        new_runs: dict[str, tuple[str, object, int]] = {}
        slots = {m["position"] for m in members}
        for member in members:
            card_key = member.get("card_key")
            if not isinstance(card_key, str):
                continue
            position, depth = member["position"], member.get("depth")
            prev = runs.get(card_key)
            count = prev[2] + 1 if prev and (prev[0], prev[1]) == (position, depth) else 1
            if count > _MAX_CONSECUTIVE_SAME_PLACEMENT:
                free = [slot for slot in _SLOT_PREFERENCES[position] if slot not in slots]
                if free:
                    _reassign_position(
                        member, shot_id,
                        f"repeats ({position!r}, {depth!r}) beyond {_MAX_CONSECUTIVE_SAME_PLACEMENT} shots (R2)",
                        free[0],
                    )
                    slots.discard(position)
                    slots.add(free[0])
                    position, count = free[0], 1
                else:
                    # ponytail: all 3 slots taken — R1's no-stacking beats R2's
                    # variety; the repeat persists and stays logged.
                    logger.info(
                        "scenario: shot %s cast %s placement repeat not repairable, all slots occupied (R2)",
                        shot_id, card_key,
                    )
            new_runs[card_key] = (position, depth, count)
        runs = new_runs


def _parse_movement_fields(entry: dict, position: str) -> tuple[str, str, str] | None:
    """Story 8.9 leniency rule, same absent-stays-absent philosophy as
    ``_parse_motion_field`` — but movement's three sub-fields are
    interdependent (direction compatibility depends on mode + position), so
    presence of ANY one movement key resolves and sets all three together.
    """
    if not any(key in entry for key in ("movement_mode", "movement_direction", "movement_pace")):
        return None
    mode = _normalize_enum(entry.get("movement_mode"), _VALID_MOVEMENT_MODES, "anchored")
    direction = _normalize_enum(entry.get("movement_direction"), _VALID_MOVEMENT_DIRECTIONS, "none")
    pace = _normalize_enum(entry.get("movement_pace"), _VALID_MOVEMENT_PACES, "slow")
    return mode, _repair_movement(mode, direction, position), pace


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
        movement = _parse_movement_fields(entry, position)
        if movement is not None:
            movement_mode, movement_direction, movement_pace = movement
            member["movement_mode"] = cast(CharacterMovementMode, movement_mode)
            member["movement_direction"] = cast(CharacterMovementDirection, movement_direction)
            member["movement_pace"] = cast(CharacterMovementPace, movement_pace)
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
    canonical = _LOCATION_KEY_CANONICAL.get(raw.strip().lower())
    if canonical is None:
        logger.warning("visual_breakdown emitted unknown location_key %r, falling back to generation", raw)
        return None
    return cast(LocationKey, canonical)


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


class TruncationError(ValueError):
    """A stage's completion hit ``finish_reason == "length"`` (Story 6.9).

    Subclasses ``ValueError`` so every existing ``except (ValueError, ...)`` /
    ``except Exception`` path keeps treating truncation as a stage failure. The
    ``completion_tokens`` and ``raw`` attributes carry the runaway evidence a
    caller can log/route on — e.g. ``_repair_and_review`` distinguishing a
    scoped-repair blow-up from an ordinary parse error to fall back to a full
    rewrite instead of failing the whole run.
    """

    def __init__(
        self, message: str, *, prompt_name: str | None = None,
        completion_tokens: int | None = None, raw: str | None = None,
    ):
        super().__init__(message)
        self.prompt_name = prompt_name
        self.completion_tokens = completion_tokens
        self.raw = raw


class SceneCoverageError(ValueError):
    """``writing_scene_repair`` returned a genuinely different scene set — right
    count, but identifiers that can't be mapped back to the originals (Story
    6.10). Subclasses ``ValueError`` so ``_call_stage_with_retry``'s existing
    semantic-failure retry still gives the model one correction attempt first;
    only after that does the caller (``_repair_and_review``) fall back to a full
    rewrite, mirroring the truncation fallback and keeping recovery narrow.

    A mere *reorder* of the same scene set (the observed SCP-049 habit) never
    reaches here — it is silently reordered at the validation site.
    """

    def __init__(self, message: str, *, prompt_name: str | None = None):
        super().__init__(message)
        self.prompt_name = prompt_name


async def _call_stage(
    prompt_name: str, variables: dict, s, call_deepseek, *, label: str | None = None
) -> tuple[str, dict]:
    """Fetch + compile a Langfuse prompt, call DeepSeek, return (raw text, usage dict).

    Raises ``TruncationError`` on truncation (finish_reason == "length") so a
    caller never has to special-case a partial payload — json.loads on it would
    fail anyway — and so a caller that CAN recover from truncation (Story 6.9's
    scoped-repair fallback) can catch it precisely without string-matching.

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
    raw, usage, finish_reason = await call_deepseek(rendered, s)
    if finish_reason == "length":
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        # ponytail: TruncationError.raw is dropped on every stage except
        # writing_scene_repair (which logs a 300-char preview). Persist the FULL
        # runaway completion so it survives the ephemeral terminal — this is the
        # evidence needed to root-cause runaway generation (Story 6.9/6.10).
        # Delete this dump once the runaway is characterized.
        dump = Path("tmp/truncations") / f"{prompt_name.replace('/', '_')}-{time.time_ns()}.txt"
        try:
            dump.parent.mkdir(parents=True, exist_ok=True)
            dump.write_text(raw or "")
            logger.warning(
                "%s truncated (completion_tokens=%s); full runaway raw -> %s",
                prompt_name, completion_tokens, dump,
            )
        except OSError:  # capture must never mask the real TruncationError
            logger.warning("%s truncated (completion_tokens=%s); raw dump failed", prompt_name, completion_tokens)
        raise TruncationError(
            f"{prompt_name} response truncated (finish_reason=length); raise max_tokens",
            prompt_name=prompt_name,
            completion_tokens=completion_tokens,
            raw=raw,
        )
    return raw, usage


_YAML_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```$", re.DOTALL)


def _parse_yaml(raw: str) -> Any:
    """Parse a stage's raw model output as YAML (Story 6.4 — replaces json.loads).

    Prompts instruct the model not to fence its output, but models sometimes
    do anyway — with any language tag (```yaml, ```json, or bare```), since a
    prompt still running under the pre-YAML production label emits JSON and
    may fence it as ```json without json_object mode forcing bare output any
    more. Strip that fence defensively before handing off to
    ``yaml.safe_load``; JSON parses fine as YAML once unfenced. Raises
    ``yaml.YAMLError`` unchanged on malformed input, same as
    ``json.JSONDecodeError`` did before.
    """
    return yaml.safe_load(_yaml_text(raw))


def _yaml_text(raw: str) -> str:
    """The exact string handed to ``yaml.safe_load`` — stripped and de-fenced.
    Shared with the free-text repair path so a ``YAMLError``'s ``problem_mark``
    line index aligns with the text the repair rewrites (Story 6.11)."""
    text = raw.strip()
    match = _YAML_FENCE_RE.match(text)
    return match.group(1) if match else text


def _normalize_freetext(text: str) -> str:
    """Collapse whitespace runs — including literal newlines a YAML ``|``
    block literal preserves verbatim — to single spaces.

    Live golden-set eval (Story 6.4) caught DeepSeek writing one sentence per
    physical line inside a ``|`` block, something a JSON string value never
    allowed; the embedded ``\\n`` characters read as choppy to the
    review/critic judge and measurably hurt scoring axes (narrative_coherence,
    atmosphere, article_fidelity), even though the underlying content was
    unchanged. Applied to every block-literal free-text field (AC2), not just
    narration — the same model habit reproduces on any of them. Restores the
    flowing single-line text every downstream consumer already expects.
    """
    return " ".join(text.split())


# Free-text fields the scenario prompts emit as block-literal scalars. When the
# model instead emits one inline and its value contains a YAML structural char
# (an unquoted colon, quote, or '#'), safe_load raises YAMLError. These keys are
# ALWAYS free-text-valued (never structural mappings), so rewriting an inline
# value as a block literal is a byte-preserving, LLM-free repair (Story 6.11).
# `hooks` (a list of scalars) is a different shape and out of scope.
FREETEXT_KEYS = (
    "narration", "image_prompt", "negative_prompt", "core_identity",
    "frozen_descriptor", "entity_sheet", "story_logline", "feedback",
)

_FREETEXT_INLINE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<dash>- )?(?P<key>" + "|".join(FREETEXT_KEYS) + r"):[ \t]+(?P<val>\S.*)$"
)


def _blockify_line(text: str, line_no: int) -> str | None:
    """Rewrite ONLY line ``line_no`` (0-based, into the de-fenced YAML ``text``)
    as a block literal (``|-``) if it's a ``FREETEXT_KEYS`` inline scalar whose
    embedded colon/``#`` broke parsing — this is the single line PyYAML's
    ``problem_mark`` flagged, so a valid sibling line is never touched
    (Story 6.11). Returns the rewritten text, or ``None`` if that line isn't a
    repairable free-text inline value (already a ``|``/``>``/quoted scalar, or a
    different key entirely → out of scope, propagate).

    The block literal takes its indented content verbatim (colons, ``#``, all
    safe) and content is indented deeper than the key, accounting for a ``- ``
    list-item marker. A quoted value is left alone: it either already parses
    (so it isn't the flagged line) or is malformed in a way this class can't
    safely disambiguate.
    """
    lines = text.splitlines()
    if not 0 <= line_no < len(lines):
        return None
    m = _FREETEXT_INLINE_RE.match(lines[line_no])
    if m is None or m.group("val")[:1] in ("|", ">", '"', "'"):
        return None
    indent, dash = m.group("indent"), m.group("dash") or ""
    content_indent = indent + " " * (len(dash) + 2)  # deeper than the key column
    lines[line_no:line_no + 1] = [
        f"{indent}{dash}{m.group('key')}: |-",
        f"{content_indent}{m.group('val')}",
    ]
    return "\n".join(lines)


def _reparse_repairing_freetext(raw: str, parse, exc: yaml.YAMLError):
    """Re-parse ``raw`` after rewriting each free-text line PyYAML flags as a
    block literal (Story 6.11). ``exc`` is the ``YAMLError`` the first parse
    already raised. Bounded by the line count; touches ONLY the single flagged
    line each pass, never a valid sibling. Returns the parsed value, or re-raises
    the last ``YAMLError`` when a flagged line isn't a repairable free-text scalar
    (a class this deliberately does not cover → propagate). A non-``YAMLError``
    (e.g. a semantic ``ValueError`` from ``parse``) propagates unchanged.
    """
    text = _yaml_text(raw)
    for _ in range(text.count("\n") + 1):  # ponytail: <= one repair per line, can't loop forever
        mark = getattr(exc, "problem_mark", None)
        fixed = _blockify_line(text, mark.line) if mark is not None else None
        if fixed is None:
            raise exc
        text = fixed
        try:
            return parse(text)
        except yaml.YAMLError as exc2:
            exc = exc2
    raise exc


def _dump_bad_output(kind: str, prompt_name: str, raw: str) -> Path:
    """Persist a full model output that failed to PARSE (finish_reason=stop,
    yaml.YAMLError). Today this raw is dropped everywhere, so this is the only
    place the exact offending text (e.g. an unquoted colon in a scalar —
    'mapping values are not allowed here') can be recovered. 6.4/6.7 both failed
    to capture it. Temporary diagnostic; delete once the class is characterized.
    """
    dump = Path("tmp/yaml-failures") / f"{prompt_name.replace('/', '_')}-{kind}-{time.time_ns()}.txt"
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_text(raw or "")
    return dump


async def _call_stage_with_retry(
    prompt_name: str,
    variables: dict,
    s,
    call_deepseek,
    parse,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
):
    """Bounded self-correcting retry for a stage's parse+validate step. A YAML
    *syntax* failure is repaired deterministically — the single free-text line
    PyYAML flagged is rewritten as a block literal and re-parsed, bounded by the
    line count (Story 6.11, no LLM call); a *semantic* validation failure feeds
    the error back into the original stage prompt for exactly one retry. A
    failure the repair can't fix propagates unchanged — never an LLM fallback,
    never an unbounded retry loop.

    ``usage_sink``, when given, collects each underlying DeepSeek call's raw
    ``usage`` dict (one entry normally, two if the semantic retry fires) —
    Story 6.3's token/cache observability seam, additive to every existing
    caller. The deterministic YAML repair adds no DeepSeek call, so it appends
    nothing.
    """
    raw, usage = await _call_stage(prompt_name, {**variables, "parse_error": ""}, s, call_deepseek, label=label)
    if usage_sink is not None:
        usage_sink.append(usage)
    try:
        return parse(raw)
    except yaml.YAMLError as exc:
        # Deterministic repair (Story 6.11): the model emitted a free-text scalar
        # inline and an embedded ':'/'#' broke parsing. Rewrite ONLY the flagged
        # line (never a valid sibling) as a block literal and re-parse. No LLM.
        try:
            return _reparse_repairing_freetext(raw, parse, exc)
        except yaml.YAMLError as exc2:
            # The flagged line isn't the free-text-colon class this repairs. Dump
            # the raw so the novel class can be characterized, then propagate.
            try:
                dump = _dump_bad_output("unfixed", prompt_name, raw)
                logger.warning(
                    "%s YAML parse failed and deterministic normalization did not fix it "
                    "(%s); broken raw -> %s",
                    prompt_name, " ".join(str(exc2).split())[:160], dump,
                )
            except OSError:  # capture must never mask the real failure
                pass
            raise
    except ValueError as exc:
        error_text = " ".join(str(exc).split())[:500]
        retry_variables = {
            **variables,
            "parse_error": f"Previous output failed validation: {error_text}. "
            "Output ONLY valid YAML, no prose, no markdown code fences.",
        }
        raw, usage = await _call_stage(prompt_name, retry_variables, s, call_deepseek, label=label)
        if usage_sink is not None:
            usage_sink.append(usage)
        return parse(raw)


async def research_step(
    scp_id: str,
    scp_text: str,
    format_guide: str,
    s,
    call_deepseek,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> dict:
    def parse(raw: str) -> dict:
        data = _parse_yaml(raw)
        if isinstance(data, dict):
            for key in ("core_identity", "frozen_descriptor", "entity_sheet", "story_logline", "hooks"):
                if isinstance(data.get(key), str):
                    data[key] = _normalize_freetext(data[key])
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

    return await _call_stage_with_retry(
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
        parse,
        label=label,
        usage_sink=usage_sink,
    )


async def structure_step(
    scp_id: str,
    research: dict,
    format_guide: str,
    s,
    call_deepseek,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> list[dict]:
    def parse(raw: str) -> list[dict]:
        data = _parse_yaml(raw)
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

    return await _call_stage_with_retry(
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
        parse,
        label=label,
        usage_sink=usage_sink,
    )


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
    usage_sink: list[dict] | None = None,
) -> dict:
    def parse(raw: str) -> dict:
        data = _parse_yaml(raw)
        scenes = data.get("scenes") if isinstance(data, dict) else None
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("writing: payload must contain a non-empty 'scenes' list")
        for scene in scenes:
            if not isinstance(scene, dict):
                raise ValueError(f"writing: malformed scene {scene!r}")
            if not isinstance(scene.get("narration"), str) or not scene["narration"].strip():
                raise ValueError(f"writing: scene[{scene.get('scene_num')}] has empty narration")
            scene["narration"] = _normalize_freetext(scene["narration"])
        return data

    return await _call_stage_with_retry(
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
        parse,
        label=label,
        usage_sink=usage_sink,
    )


async def writing_scene_repair_step(
    scp_id: str,
    original_scenes: list[dict],
    scene_feedback: str,
    frozen_descriptor: str,
    format_guide: str,
    s,
    call_deepseek,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> list[dict]:
    """Repair an exact positional subset without trusting model scene numbers."""
    expected_ids = [scene.get("scene_num") for scene in original_scenes]

    def parse(raw: str) -> list[dict]:
        data = _parse_yaml(raw)
        scenes = data.get("scenes") if isinstance(data, dict) else None
        if not isinstance(scenes, list) or len(scenes) != len(original_scenes):
            raise SceneCoverageError(
                f"writing_scene_repair: expected {len(original_scenes)} scenes, "
                f"got {len(scenes) if isinstance(scenes, list) else 'non-list'}",
                prompt_name="scenario/writing_scene_repair",
            )
        actual_ids: list[object] = []
        for scene in scenes:
            if not isinstance(scene, dict):
                raise ValueError(f"writing_scene_repair: malformed scene {scene!r}")
            if not isinstance(scene.get("narration"), str) or not scene["narration"].strip():
                raise ValueError(f"writing_scene_repair: scene[{scene.get('scene_num')}] has empty narration")
            scene["narration"] = _normalize_freetext(scene["narration"])
            actual_ids.append(scene.get("scene_num"))
        if actual_ids != expected_ids:
            # Same scene set, wrong order (observed SCP-049 habit: the model
            # returns the requested scenes sorted by scene_num). Reorder to the
            # requested positional order so the caller's zip(indexes, repaired)
            # stays aligned — not a coverage failure. A genuinely different set
            # (missing/extra/renumbered scenes, or non-unique ids we can't map)
            # can't be reordered back and is a real coverage mismatch.
            keys_actual, keys_expected = sorted(map(repr, actual_ids)), sorted(map(repr, expected_ids))
            if keys_actual == keys_expected and len(set(keys_actual)) == len(actual_ids):
                by_num = {scene["scene_num"]: scene for scene in scenes}
                scenes = [by_num[sid] for sid in expected_ids]
            else:
                raise SceneCoverageError(
                    f"writing_scene_repair: scene coverage mismatch; expected {expected_ids!r}, got {actual_ids!r}",
                    prompt_name="scenario/writing_scene_repair",
                )
        return scenes

    return await _call_stage_with_retry(
        "scenario/writing_scene_repair",
        {
            "scp_id": scp_id,
            "original_scenes": json.dumps(original_scenes, ensure_ascii=False),
            "scene_feedback": scene_feedback,
            "scp_visual_reference": frozen_descriptor,
            "format_guide": format_guide,
            "glossary_section": "",
        },
        s,
        call_deepseek,
        parse,
        label=label,
        usage_sink=usage_sink,
    )


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
    usage_sink: list[dict] | None = None,
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

    def parse(raw: str) -> dict[int, list]:
        data = _parse_yaml(raw)
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

    return await _call_stage_with_retry(
        "scenario/cast_decision",
        {
            "scp_id": scp_id,
            "stock_cast_keys": ", ".join(STOCK_CAST_KEYS),
            "characters_present": json.dumps(scene.get("characters_present", []), ensure_ascii=False),
            "numbered_sentences": numbered,
            "sentence_count": len(sentences),
        },
        s,
        call_deepseek,
        parse,
        label=label,
        usage_sink=usage_sink,
    )


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
    usage_sink: list[dict] | None = None,
) -> list[dict]:
    numbered = "\n".join(f"{i + 1}. {sent}" for i, sent in enumerate(sentences))

    def parse(raw: str) -> list[dict]:
        data = _parse_yaml(raw)
        shots = data.get("visual_descriptions") if isinstance(data, dict) else None
        if not isinstance(shots, list) or len(shots) != len(sentences):
            raise ValueError(
                f"visual_breakdown: expected 1:1 sentence-to-shot mapping "
                f"({len(sentences)} sentences), got {len(shots) if isinstance(shots, list) else 'non-list'}"
            )
        # Cast is decided authoritatively by cast_decision_step (Story 8.10) — attach
        # it here regardless of anything the model echoed, keyed by sentence_start.
        for shot in shots:
            if not isinstance(shot, dict):
                raise ValueError(f"visual_breakdown: malformed shot {shot!r}")
            for key in ("image_prompt", "negative_prompt"):
                if isinstance(shot.get(key), str):
                    shot[key] = _normalize_freetext(shot[key])
            sentence_start = shot.get("sentence_start")
            if type(sentence_start) is not int:
                raise ValueError(f"visual_breakdown: invalid sentence_start {sentence_start!r}")
            shot["cast"] = cast_by_sentence.get(sentence_start, [])
        starts = [shot["sentence_start"] for shot in shots]
        expected = list(range(1, len(sentences) + 1))
        if sorted(starts) != expected:
            raise ValueError(f"visual_breakdown: sentence coverage mismatch; expected {expected}, got {sorted(starts)}")
        return shots

    return await _call_stage_with_retry(
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
        parse,
        label=label,
        usage_sink=usage_sink,
    )


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
    usage_sink: list[dict] | None = None,
) -> dict:
    def parse(raw: str) -> dict:
        data = _parse_yaml(raw)
        if isinstance(data, dict):
            for collection, fields in (
                ("issues", ("description", "correction")),
                ("corrections", ("original", "corrected")),
                ("storytelling_issues", ("description", "correction")),
            ):
                items = data.get(collection)
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    for field in fields:
                        if isinstance(item.get(field), str):
                            item[field] = _normalize_freetext(item[field])
        if not isinstance(data, dict) or type(data.get("overall_pass")) is not bool:
            raise ValueError("review: payload missing boolean 'overall_pass'")
        return data

    return await _call_stage_with_retry(
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
        parse,
        label=label,
        usage_sink=usage_sink,
    )


async def critic_step(
    writing: dict,
    visual_by_scene: dict,
    format_guide: str,
    s,
    call_deepseek,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> dict:
    scenario_json = {"writing": writing, "visual_descriptions": visual_by_scene}

    def parse(raw: str) -> dict:
        data = _parse_yaml(raw)
        if isinstance(data, dict):
            if isinstance(data.get("feedback"), str):
                data["feedback"] = _normalize_freetext(data["feedback"])
            notes = data.get("scene_notes")
            if isinstance(notes, list):
                for note in notes:
                    if not isinstance(note, dict):
                        continue
                    for field in ("issue", "suggestion"):
                        if isinstance(note.get(field), str):
                            note[field] = _normalize_freetext(note[field])
        if not isinstance(data, dict) or data.get("verdict") not in _VALID_VERDICTS:
            raise ValueError(f"critic_agent: payload has invalid 'verdict' (must be one of {_VALID_VERDICTS})")
        return data

    return await _call_stage_with_retry(
        "scenario/critic_agent",
        {
            "format_guide": format_guide,
            "scenario_json": json.dumps(scenario_json, ensure_ascii=False),
        },
        s,
        call_deepseek,
        parse,
        label=label,
        usage_sink=usage_sink,
    )


async def tts_normalize_step(
    writing: dict,
    format_guide: str,
    s,
    call_deepseek,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> dict:
    """Rewrite each scene's narration for natural Korean TTS, matching scenes positionally.

    A scene whose normalized sentence count doesn't match the original (per
    ``split_sentences()``) keeps its original narration instead of failing the
    whole scenario stage — see story 5-4-tts-korean-naturalization.md.
    """
    original_scenes = writing["scenes"]
    scenes_input = [
        {"scene_num": scene.get("scene_num"), "narration": scene.get("narration", "")} for scene in original_scenes
    ]
    def parse(raw: str) -> list[dict]:
        data = _parse_yaml(raw)
        normalized_scenes = data.get("scenes") if isinstance(data, dict) else None
        if not isinstance(normalized_scenes, list) or len(normalized_scenes) != len(original_scenes):
            got = len(normalized_scenes) if isinstance(normalized_scenes, list) else "non-list"
            raise ValueError(f"tts_normalize: expected {len(original_scenes)} scenes, got {got}")
        for scene in normalized_scenes:
            if not isinstance(scene, dict):
                raise ValueError(f"tts_normalize: malformed scene {scene!r}")
            if not isinstance(scene.get("narration"), str) or not scene["narration"].strip():
                raise ValueError(f"tts_normalize: scene[{scene.get('scene_num')}] has empty narration")
            scene["narration"] = _normalize_freetext(scene["narration"])
        return normalized_scenes

    normalized_scenes = await _call_stage_with_retry(
        "scenario/tts_normalize",
        {
            "scenes_json": json.dumps(scenes_input, ensure_ascii=False),
            "format_guide": format_guide,
        },
        s,
        call_deepseek,
        parse,
        label=label,
        usage_sink=usage_sink,
    )

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
                    camera_movement=_resolve_camera_movement(raw_shot.get("camera_movement"), mood),
                    image_path=None,
                    cast=parse_cast(raw_shot.get("cast")),
                    location_key=parse_location_key(raw_shot.get("location_key")),
                )
            )

        if not shots:
            raise ValueError(f"scene[{scene_num}]: no shots produced after merge")

        _enforce_camera_variety(shots, mood)
        _enforce_cast_diversity(shots)

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
