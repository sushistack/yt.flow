"""Multi-stage LLM chain for scenario_node.

See docs/superpowers/specs/2026-07-03-scenario-multistage-design.md for the
design this implements. Each ``*_step`` function fetches its Langfuse prompt,
compiles it, calls the LLM via the caller-supplied ``call_llm`` seam, and returns
a parsed+validated payload. No exception handling here: every failure propagates
to ``scenario_node``, which converts it into ``PipelineState.error`` exactly as
before.

``call_llm`` is ``scenario.py``'s ``_call_deepseek`` OR ``_call_gemini`` — this
module does not choose. Story 12.2 split provider ownership per stage and kept
that decision in the orchestration layer (``scenario._GEMINI_STAGES``), so no
parser here has to know or ask which provider it is talking to; the seam's
``(content, usage, finish_reason)`` contract is identical for both.
"""

import asyncio
import json
import logging
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, cast

import yaml

from yt_flow.domain.pose import canonical_guide_key
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
    GroundedContradiction,
    LocationKey,
    STOCK_CAST_KEYS,
    STOCK_CAST_ROLES,
    RepeatedPhrase,
    RuleCounts,
    RuleMetrics,
    SOURCE_EVIDENCE_KEYS,
    STORY_ARCHETYPE_FALLBACK,
    STORY_ARCHETYPES,
    SceneRuleCounts,
    SceneState,
    ShotData,
    SlopPhraseHit,
    missing_archetype_evidence,
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
# Stand-in when a writing scene reaches image work without a `location`. Both
# consumers (visual_breakdown's prompt variable, _fallback_prompt) share it so
# they can't disagree: the strict one used to hard-index and killed live run
# cd2f1fb8 (SCP-999) with a bare KeyError while the other already degraded fine.
_DEFAULT_LOCATION = "an unmarked containment area"
# Same story for `color_palette`/`atmosphere`: visual_breakdown hard-indexed both
# on the lines next to `location`, so the identical KeyError was one output
# variance away. The atmosphere text is the one `_fallback_prompt` already used.
_DEFAULT_COLOR_PALETTE = "desaturated grey, cold fluorescent white"
_DEFAULT_ATMOSPHERE = "tense silence"
# Writing fields the image stages consume directly, all three marked REQUIRED by
# `scenario/writing` — absence is model variance, not a prompt-variant gap, so it
# earns the one corrective retry (see writing_step's parse).
_REQUIRED_WRITING_VISUAL_FIELDS = ("location", "color_palette", "atmosphere")

# --- Story 12.1 retention contract -------------------------------------------
# Hand-set starting constants for TARGET_DURATION_MINUTES = 3, kept beside the
# validator so live tuning is one edit in one place. Calibrating them against
# measured reference scripts is a separate task, deliberately not this story.
HOOK_TYPES = ("question", "shock", "mystery", "contrast")  # format_guide §A, verbatim
_VALID_PATTERN_INTERRUPTS = {"none", "tone_shift", "pov_shift", "direct_address", "format_change"}
# fullmatch, not `^...$`: `$` also matches just before a trailing newline, so a
# folded YAML scalar would smuggle "loop_a\n" through as a legal id.
_LOOP_ID_RE = re.compile(r"loop_[a-z0-9_]+")
MAX_SCENES_WITHOUT_PATTERN_INTERRUPT = 2
MIN_PLANTED_LOOPS, MAX_PLANTED_LOOPS = 2, 3
MIN_SCENE_WORD_BUDGET, MAX_SCENE_WORD_BUDGET = 20, 90
MIN_TOTAL_WORD_BUDGET, MAX_TOTAL_WORD_BUDGET = 180, 360

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


def _parse_pose_guide_key(raw: object, pose_hint: str | None) -> str | None:
    """Story 8.20: validate an explicit structural-guide key from the closed catalog.

    Same omit-on-invalid philosophy as ``_parse_pose_hint``, plus two rules the
    other cast fields don't need:

    - A guide without a ``pose_hint`` is meaningless (the guide constrains
      geometry for a requested action; with no action there is nothing to
      constrain), so it is dropped.
    - An out-of-catalog key warns rather than passing through. Unlike
      ``card_key``, there is no downstream DB resolution that could rescue it —
      the service layer would only degrade it to edit_only silently.
    """
    if raw is None:
        return None
    if pose_hint is None:
        logger.warning("parse_cast: dropping pose_guide_key %r with no pose_hint", raw)
        return None
    key = canonical_guide_key(raw)
    if key is None:
        logger.warning("parse_cast: dropping pose_guide_key outside the approved catalog: %r", raw)
    return key


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


# Story 8.19 — framings that leave no room for a composited full-body card.
# Substrings, matched against the lowercased image_prompt. Deliberately only the
# unambiguous object/macro heads: precision beats recall here, because a false
# suppression silently deletes a character the beat wanted, which is worse than
# the status quo. Measured on the diagnosed corpus these fire on 40/193
# cast-bearing shots, and on 0 shots whose framing gives a full-body card
# anywhere to stand. A handful of fires do mention a person *part* inside an
# object framing ("a cell with a figure's feet visible" on a monitor close-up,
# "a pair of bare feet still as stone" on a floor close-up) — those are drawn by
# the background prompt, so dropping the card is still the correct call.
# ponytail: recall ceiling named, not fixed — 25 of the 27 defective shots in
# c6be1954 fire; the 2 misses are object framings with no marker vocabulary
# ("high-angle shot looking down at a conference table…", "medium shot tight on
# a steel instrument tray…"). Widening to "high-angle shot"/"tight on" would
# start catching legitimate figure framings, so the gap stays until a diagnosed
# case justifies a marker with better precision.
_NO_FIGURE_FRAMINGS = (
    "extreme close-up",
    "macro close-up",
    "macro shot",
    "close-up of",
    "close-up on",
    "no visible subject",
)


def _suppress_cast_on_no_figure_framing(shots: list) -> None:
    """Story 8.19: drop cast from shots whose own framing has no room for a card.

    Diagnosed cause is ORDERING, not key choice. ``cast_decision_step`` reads the
    narration only, and ``visual_breakdown_step`` invents the shot's framing
    *afterwards* (it receives the cast as input), so the cast prompt's own "object
    close-up / empty room -> ``cast: []``" rule asks the LLM to predict a decision
    that does not exist yet. It cannot comply, and in run c6be1954 it did not:
    27/121 cast-bearing shots composited a full-body card over an object macro —
    e.g. S00113 stood SCP-049 beside a macro of an eye, S00406 stood two cards on
    a cardiac-monitor screen. ``build_scenes`` is the first place the cast and the
    prompt coexist, so the reconciliation belongs here.

    Not a text matcher: the diagnosis found zero mis-keyed or hallucinated keys
    (every emitted key was in-vocabulary), so mapping narration text to candidate
    keys would fix nothing and could only *add* wrong cast. This drops, never adds
    — and never crosses into ``location_key``.

    Mark-targeted (6.11/8.18 lesson): only a violating shot's ``cast`` changes;
    sibling shots and every other field stay byte-identical. Pure over the shot
    dicts build_scenes just created, never an input state object [AD-4]. Total and
    never raises — a malformed shot is skipped, matching resolve_mood philosophy:
    the scenario stage degrades, it does not fail.

    Runs BEFORE ``_enforce_cast_diversity`` so placement repair only sees cast
    that survives. That ordering has one *intended* cross-shot consequence worth
    naming, since it is the one thing this function does that a sibling shot can
    observe: emptying a shot's cast opens a gap in R2's consecutive-placement run
    tracking (see ``test_enforce_cast_diversity_absence_resets_run``), so a later
    sibling that used to trip the repeat cap now keeps its LLM-chosen position —
    measured on 5 shots across the diagnosed runs. That is correct, not a
    displacement: a shot with no card on screen genuinely breaks the visual
    repetition R2 exists to break. Running the two in the other order would make
    R2 count cast that is about to vanish, so the order is load-bearing and
    pinned by ``test_build_scenes_suppresses_cast_before_diversity_repair``.
    """
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        cast = shot.get("cast")
        if not isinstance(cast, list) or not cast:
            continue
        prompt = shot.get("image_prompt")
        if not isinstance(prompt, str):
            continue
        prompt_lower = prompt.lower()
        marker = next((m for m in _NO_FIGURE_FRAMINGS if m in prompt_lower), None)
        if marker is None:
            continue
        dropped = [m.get("card_key") for m in cast if isinstance(m, dict)]
        # AC9 decision evidence: namespace, decision, method and reason.
        logger.info(
            "scenario: shot %s cast namespace -> [] (method=framing-marker, reason=%r, dropped=%s)",
            shot.get("shot_id"), marker, dropped,
        )
        shot["cast"] = []


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
        pose_guide_key = _parse_pose_guide_key(entry.get("pose_guide_key"), pose_hint)
        if pose_guide_key is not None:
            member["pose_guide_key"] = pose_guide_key
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


# ── Story 12.3: deterministic quality metrics (no LLM call) ───────────────────
#
# These are MEASUREMENTS, not a verdict. They exist because the review/critic
# judge is the same kind of model that wrote the text, so "is this repetitive?"
# is exactly the question it is worst at and code is best at. Nothing here fails
# a run or sets a threshold — Story 12.1 owns calibrated word budgets; this pass
# only puts unambiguous repeat/slop evidence in front of the human at the gate.
#
# Bump SLOP_VOCABULARY_VERSION whenever KOREAN_SLOP_PHRASES changes, so hits
# recorded in an old checkpoint stay interpretable against the tuple that
# produced them.
SLOP_VOCABULARY_VERSION = 1

# ponytail: an exact-match tuple, deliberately NOT a semantic classifier. Each
# entry is documentary-narration hype filler that survives review because it
# *sounds* like atmosphere — a diagnostic list, so a false positive costs the
# operator one glance, never a failed run.
KOREAN_SLOP_PHRASES = (
    "상상해 보십시오",
    "충격적인 사실",
    "믿을 수 없는 일",
    "소름 돋는",
    "말로 설명할 수 없는",
    "그 누구도 알지 못했습니다",
    "과연 무엇일까요",
    "지금부터 함께",
)

_NGRAM_SIZE = 4
_NGRAM_MIN_OCCURRENCES = 3  # "at least three times" — twice is ordinary Korean cohesion
_TERMINAL_PUNCTUATION = ".?!"


def _metric_text(text: object) -> str:
    """NFKC-normalized, whitespace-collapsed narration. A non-string (absent /
    null / malformed scene) measures as empty rather than raising — metrics are
    diagnostics and must never be the thing that fails a run [AD-10]."""
    if not isinstance(text, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _sentence_key(sentence: str) -> str:
    """Comparison key for duplicate detection: terminal ``.?!`` stripped and
    case folded, so "It is good." / "It is good!" / "IT IS GOOD." are one
    sentence. Terminal punctuation is ignored HERE ONLY — the n-gram tokens
    below keep it (AC5)."""
    return sentence.rstrip(_TERMINAL_PUNCTUATION).strip().casefold()


def _rule_counts(
    keys: list[str], token_runs: list[list[str]], chars: int
) -> tuple[RuleCounts, list[RepeatedPhrase]]:
    """Counts + n-gram evidence over already-normalized sentence keys and tokens.

    Called once per scene and once with every scene's keys/tokens pooled — which
    is why the aggregate is exact rather than a re-split of a concatenation: the
    pooled sentence count IS the sum of the per-scene counts, while duplicates
    and repeated n-grams additionally catch phrases recycled BETWEEN scenes.

    ``token_runs`` is a list of per-scene token sequences, NOT one flat list: a
    window may never straddle a scene boundary, or the aggregate reports phrases
    ("…end-of-scene-1 start-of-scene-2…") that appear nowhere in the script as
    evidence the operator is asked to act on.
    """
    grams = Counter(
        " ".join(tokens[i:i + _NGRAM_SIZE])
        for tokens in token_runs
        for i in range(len(tokens) - _NGRAM_SIZE + 1)
    )
    repeated: list[RepeatedPhrase] = sorted(
        ({"phrase": phrase, "count": count} for phrase, count in grams.items()
         if count >= _NGRAM_MIN_OCCURRENCES),
        key=lambda hit: (-hit["count"], hit["phrase"]),
    )
    counts: RuleCounts = {
        # `chars` is counted on the un-keyed text: `_sentence_key` strips terminal
        # punctuation for duplicate comparison only, and those characters are real.
        "character_count": chars,
        "sentence_count": len(keys),
        "duplicate_sentence_count": sum(n - 1 for n in Counter(keys).values() if n > 1),
        "repeated_4gram_count": len(repeated),
    }
    return counts, repeated


def compute_rule_metrics(writing: object) -> RuleMetrics:
    """Pure-Python quality measurements over a writing payload (Story 12.3 AC5).

    Merged into the quality object AFTER review parsing by ``scenario._build_quality``,
    so a model that reports flattering metrics of its own cannot overwrite these.
    """
    scenes = writing.get("scenes") if isinstance(writing, dict) else None
    scenes = scenes if isinstance(scenes, list) else []
    scene_counts: list[SceneRuleCounts] = []
    slop_hits: list[SlopPhraseHit] = []
    all_keys: list[str] = []
    all_token_runs: list[list[str]] = []
    total_chars = 0

    for idx, scene in enumerate(scenes):
        text = _metric_text(scene.get("narration") if isinstance(scene, dict) else None)
        # Positional scene_num, never the model's own — the same rule `_stamped`
        # and `_retry_scope` apply, because duplicate/reordered scene_num is a
        # tested failure mode of this chain.
        keys = [_sentence_key(sentence) for sentence in split_sentences(text)]
        tokens = text.split()
        chars = len(text.replace(" ", ""))  # `text` is already whitespace-collapsed
        counts, _ = _rule_counts(keys, [tokens], chars)
        scene_counts.append(cast(SceneRuleCounts, {"scene_num": idx + 1, **counts}))
        all_keys.extend(keys)
        all_token_runs.append(tokens)
        total_chars += chars
        for phrase in KOREAN_SLOP_PHRASES:
            if hits := text.count(phrase):
                slop_hits.append({"scene_num": idx + 1, "phrase": phrase, "count": hits})

    aggregate, repeated = _rule_counts(all_keys, all_token_runs, total_chars)
    return {
        "aggregate": aggregate,
        "scenes": scene_counts,
        "repeated_ngrams": repeated,
        "slop_phrase_hits": slop_hits,
        "slop_vocabulary_version": SLOP_VOCABULARY_VERSION,
    }


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


class RetentionError(ValueError):
    """The Stage 2 outline violates the Story 12.1 retention contract.

    Deliberately NOT raised from ``structure_step``'s parse callback: a
    ``ValueError`` there buys one LLM regeneration, and re-rolling the dice
    on a narrative-ledger violation is exactly the LLM-recall this story exists
    to avoid. It is raised after ``_call_stage_with_retry`` has returned, so it
    propagates straight out of the stage and ``scenario_node`` turns it into
    ``PipelineState.error``. ``code`` is the stable identifier tests assert on;
    the message text is diagnostic and free to change.
    """

    def __init__(self, code: str, detail: str):
        super().__init__(f"retention[{code}] {detail}")
        self.code = code


class StoryArchetypeError(ValueError):
    """The research packet is valid EXCEPT for its ``story_archetype`` (Story 12.4).

    Narrow on purpose. It carries the otherwise-good packet so that — and only
    when — the model still emits an unusable archetype on its one semantic
    correction retry, ``_parse_with_retry``'s ``semantic_fallback`` seam can swap
    in ``incident_first`` rather than throwing away a packet whose descriptors,
    entity fields and logline are all fine. Every OTHER validation failure
    (including a missing ``archetype_rationale``) stays a plain ``ValueError``
    and still fails the stage after the retry — there is no general
    "salvage the packet" path here.
    """

    def __init__(self, reason: str, *, research: dict):
        super().__init__(f"research: story_archetype {reason}")
        self.reason = reason
        self.research = research


def _canonicalize(scene: dict, key: str) -> object:
    """Strip surrounding/inner whitespace and ASCII-case a closed-vocabulary scalar.

    Writes back only when the value is a string that actually changed, so an
    absent key stays absent and a non-string value stays byte-identical for the
    error message to quote.
    """
    raw = scene.get(key)
    if not isinstance(raw, str):
        return raw
    value = " ".join(raw.split()).lower()
    if value != raw:
        scene[key] = value
    return value


def _loop_ids(scene: dict, key: str, where: str) -> list[str]:
    value = scene.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RetentionError(
            "loop_field_malformed", f"{where} {key} must be a list of loop-id strings, got {value!r}"
        )
    return value


def _validate_retention_outline(scenes: list) -> None:
    """Story 12.1: deterministic, LLM-free enforcement of the retention contract.

    Pure over the freshly parsed structure list — no I/O, no state object, no
    repair. Unlike ``_enforce_camera_variety`` / ``_enforce_cast_diversity``,
    which repair what they find, a narrative violation hard-fails: code cannot
    invent an actor, a consequence, or the payoff of a promise the outline never
    kept, and a silent rewrite would be exactly the invisible degradation this
    contract exists to expose.

    The only write is scalar canonicalization of the two closed-vocabulary enums
    (``hook_type``, ``pattern_interrupt``); everything else — unknown fields,
    list order, non-enum values — is left byte-identical, so the function is
    idempotent and a valid outline passes through unchanged.

    List position is the authoritative chronology. ``scene_num`` is model-supplied
    and is known to duplicate and reorder (6.5/6.6), so it never drives the ledger.
    """
    planted: dict[str, int] = {}
    closed: set[str] = set()
    active: set[str] = set()
    total_budget = 0
    scenes_since_interrupt = 0

    for pos, scene in enumerate(scenes, start=1):
        where = f"scene at position {pos}"
        if not isinstance(scene, dict):
            raise RetentionError("scene_malformed", f"{where} is not a mapping: {scene!r}")

        event = scene.get("event")
        if not isinstance(event, dict):
            raise RetentionError("event_missing", f"{where} has no 'event' mapping")
        for field in ("who", "what", "consequence"):
            value = event.get(field)
            if not isinstance(value, str) or not value.strip():
                raise RetentionError(
                    "event_field_empty", f"{where} event.{field} must be a non-empty string, got {value!r}"
                )

        # Shape only. Whether a statement is actually grounded in the source
        # article is not machine-checkable here — review/critic and Story 12.3's
        # deterministic metrics own that, and this story adds no fact-check call.
        facts = scene.get("fact_references")
        if (
            not isinstance(facts, list)
            or not facts
            or not all(isinstance(fact, str) and fact.strip() for fact in facts)
        ):
            raise RetentionError(
                "fact_references_invalid",
                f"{where} fact_references must be a non-empty list of non-empty fact statements",
            )

        hook = _canonicalize(scene, "hook_type")
        if pos == 1:
            if hook not in HOOK_TYPES:
                raise RetentionError(
                    "hook_invalid", f"scene 1 hook_type {hook!r} must be one of {list(HOOK_TYPES)}"
                )
        elif hook != "none":
            raise RetentionError("hook_misplaced", f"{where} hook_type must be 'none', got {hook!r}")

        interrupt = _canonicalize(scene, "pattern_interrupt")
        # isinstance first: a YAML list/dict value is unhashable, and a bare `in`
        # against the set would raise TypeError instead of a clean RetentionError.
        if not isinstance(interrupt, str) or interrupt not in _VALID_PATTERN_INTERRUPTS:
            raise RetentionError(
                "interrupt_invalid",
                f"{where} pattern_interrupt {interrupt!r} must be one of {sorted(_VALID_PATTERN_INTERRUPTS)}",
            )
        if pos == 1:
            scenes_since_interrupt = 0  # the hook itself is scene 1's interrupt
        elif interrupt == "none":
            scenes_since_interrupt += 1
            if scenes_since_interrupt > MAX_SCENES_WITHOUT_PATTERN_INTERRUPT:
                raise RetentionError(
                    "interrupt_cadence",
                    f"{where} is consecutive scene {scenes_since_interrupt} without a pattern interrupt "
                    f"(max {MAX_SCENES_WITHOUT_PATTERN_INTERRUPT})",
                )
        else:
            scenes_since_interrupt = 0

        budget = scene.get("word_budget")
        # `type(...) is not int` — bool is an int subclass, and `word_budget: true`
        # is a real YAML slip that would otherwise sail through as 1.
        if type(budget) is not int:
            raise RetentionError(
                "budget_type", f"{where} word_budget must be an int, got {type(budget).__name__} {budget!r}"
            )
        if not MIN_SCENE_WORD_BUDGET <= budget <= MAX_SCENE_WORD_BUDGET:
            raise RetentionError(
                "budget_range",
                f"{where} word_budget {budget} outside {MIN_SCENE_WORD_BUDGET}-{MAX_SCENE_WORD_BUDGET}",
            )
        total_budget += budget

        plants = _loop_ids(scene, "loops_planted", where)
        closes = _loop_ids(scene, "loops_closed", where)
        # Checked before either list is processed, so a same-scene plant+close can
        # never be legalized by plant-then-close ordering.
        both = sorted(set(plants) & set(closes))
        if both:
            raise RetentionError("loop_same_scene", f"{where} plants and closes {both} in the same scene")
        for loop_id in plants:
            if not _LOOP_ID_RE.fullmatch(loop_id):
                raise RetentionError("loop_id_invalid", f"{where} planted loop id {loop_id!r} must match loop_[a-z0-9_]+")
            if loop_id in planted:
                raise RetentionError(
                    "loop_duplicate_plant", f"{where} re-plants {loop_id}, already planted at position {planted[loop_id]}"
                )
            planted[loop_id] = pos
            active.add(loop_id)
        for loop_id in closes:
            if not _LOOP_ID_RE.fullmatch(loop_id):
                raise RetentionError("loop_id_invalid", f"{where} closed loop id {loop_id!r} must match loop_[a-z0-9_]+")
            if loop_id not in planted:
                raise RetentionError(
                    "loop_unknown_close", f"{where} closes {loop_id}, which was never planted in an earlier scene"
                )
            if loop_id in closed:
                raise RetentionError("loop_duplicate_close", f"{where} closes {loop_id} a second time")
            closed.add(loop_id)
            active.discard(loop_id)

    if not MIN_PLANTED_LOOPS <= len(planted) <= MAX_PLANTED_LOOPS:
        raise RetentionError(
            "loop_count",
            f"outline plants {len(planted)} loops; contract is {MIN_PLANTED_LOOPS}-{MAX_PLANTED_LOOPS}",
        )
    if 1 not in planted.values():
        raise RetentionError("loop_missing_scene1_plant", "no open loop is planted in scene 1")
    if active:
        first = min(active, key=lambda loop_id: planted[loop_id])
        raise RetentionError(
            "loop_unclosed", f"{first} planted at position {planted[first]} is still active after the final scene"
        )
    if not MIN_TOTAL_WORD_BUDGET <= total_budget <= MAX_TOTAL_WORD_BUDGET:
        raise RetentionError(
            "budget_total",
            f"outline word_budget total {total_budget} outside "
            f"{MIN_TOTAL_WORD_BUDGET}-{MAX_TOTAL_WORD_BUDGET}",
        )


async def _call_stage(
    prompt_name: str, variables: dict, s, call_llm, *, label: str | None = None
) -> tuple[str, dict]:
    """Fetch + compile a Langfuse prompt, call the injected provider, return (raw text, usage dict).

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
    raw, usage, finish_reason = await call_llm(rendered, s)
    if finish_reason == "length":
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        # ponytail: TruncationError.raw is dropped on every stage except
        # writing_scene_repair (which logs a 300-char preview). Persist the FULL
        # runaway completion so it survives the ephemeral terminal — this is the
        # evidence needed to root-cause runaway generation (Story 6.9/6.10).
        # Delete this dump once the runaway is characterized.
        dump = Path("tmp/truncations") / f"{prompt_name.replace('/', '_')}-{time.time_ns()}.txt"
        body = raw or ""
        try:
            dump.parent.mkdir(parents=True, exist_ok=True)
            # Always write the header: every truncation dump from the 2026-08-05 runs
            # was 0 bytes while the log claimed "full runaway raw -> <path>", so there
            # was no way to tell an empty response from a failed capture. `raw_chars`
            # in the log says which one it is. (Root cause of the empty body was
            # scenario._call_deepseek dropping `reasoning_content` — fixed there.)
            dump.write_text(f"# {prompt_name} completion_tokens={completion_tokens} raw_chars={len(body)}\n{body}")
            logger.warning(
                "%s truncated (completion_tokens=%s, raw_chars=%d); full runaway raw -> %s",
                prompt_name, completion_tokens, len(body), dump,
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


# MULTILINE so the opening fence may start on any line (a model that writes a
# markdown heading first — live run 64b6d9a8); the `\Z` branch takes everything
# after an unterminated fence rather than failing to match at all.
_YAML_FENCE_RE = re.compile(
    r"^```[a-zA-Z]*[ \t]*\n(.*?)(?:\n?[ \t]*```|\Z)", re.DOTALL | re.MULTILINE
)


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
    line index aligns with the text the repair rewrites (Story 6.11) — it stays
    aligned because both paths call this one pure function, so prose dropped
    before the fence is dropped identically on both sides.

    ``search``, not ``match``: the fence need not open at position 0 (the model
    may narrate or emit a markdown heading first). The first fenced block wins;
    anything before the opening fence or after the closing one is prose.
    """
    text = raw.strip()
    match = _YAML_FENCE_RE.search(text)
    return match.group(1) if match else text


# SCP designations are a closed token class, so they are spelled in code rather
# than asked of the LLM. Live run e5ed4b3a produced FOUR readings of the same
# object across nine scenes — `에스씨피 공사구` / `에스시피-049-2` / `에스시피 공사구 이`
# / `에스씨피 공사 구` — because `tts_normalize.md` tells the model to spell
# acronyms and expand numbers without naming a canonical form. One narrator
# saying the subject's name four different ways is the defect; determinism is
# the fix. The prompt now leaves `SCP-###` verbatim for this pass to convert.
_SCP_DESIGNATION = re.compile(r"\bSCP[-–—]?(\d{2,4})(?:[-–—](\d+))?", re.IGNORECASE)
_DIGIT_HANGUL = {"0": "공", "1": "일", "2": "이", "3": "삼", "4": "사",
                 "5": "오", "6": "육", "7": "칠", "8": "팔", "9": "구"}


def spell_scp_designations(text: str) -> str:
    """Rewrite ``SCP-049`` / ``SCP-049-2`` into their spoken Hangul reading.

    Digits are read individually (``049`` → ``공사구``), which is how Korean SCP
    narration says them; the instance suffix becomes a trailing digit word
    (``-2`` → ``이``). Sentence count is untouched — no punctuation is added or
    removed — so this is safe to apply after the sentence-count invariant check.
    """
    def sub(m: re.Match[str]) -> str:
        head = "".join(_DIGIT_HANGUL[d] for d in m.group(1))
        tail = "".join(_DIGIT_HANGUL[d] for d in m.group(2)) if m.group(2) else ""
        return f"에스씨피 {head} {tail}".rstrip()
    return _SCP_DESIGNATION.sub(sub, text)


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
    "archetype_rationale",  # Story 12.4 — a rationale quoting the source will contain
                            # ':' ("Addendum 173-1: ...") far more often than not
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
    call_llm,
    parse,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
    what: str | None = None,
    semantic_fallback=None,
):
    """Every scenario-chain LLM call goes through here, so the truncation
    re-roll is wired ONCE, here, rather than per stage. Truncation is stochastic
    reasoning-token exhaustion, so any stage can be the next victim: live run
    ce0a455a (2026-08-05) died at ``scenario/cast_decision``, which is already
    per-scene — batching wasn't the gap, coverage was.

    The re-roll wraps the whole parse+validate attempt, so a truncation in
    either the initial call or the semantic retry costs one independent re-roll
    and a second truncation propagates (see ``reroll_on_truncation``). ``what``
    only labels the re-roll log line — writing names the individual scene.

    ``semantic_fallback``, when given, is consulted for exactly one error class:
    a ``StoryArchetypeError`` from the RETRY's parse (Story 12.4). See
    ``_parse_with_retry``.
    """
    return await reroll_on_truncation(
        what or prompt_name,
        lambda: _parse_with_retry(
            prompt_name, variables, s, call_llm, parse, label=label, usage_sink=usage_sink,
            semantic_fallback=semantic_fallback,
        ),
    )


async def _parse_with_retry(
    prompt_name: str,
    variables: dict,
    s,
    call_llm,
    parse,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
    semantic_fallback=None,
):
    """Bounded self-correcting retry for a stage's parse+validate step. A YAML
    *syntax* failure is repaired deterministically first — the single free-text
    line PyYAML flagged is rewritten as a block literal and re-parsed, bounded by
    the line count (Story 6.11, no LLM call). Anything the repair can't fix —
    syntax OR semantic — feeds the error back into the ORIGINAL stage prompt via
    ``parse_error`` for exactly one retry. Never a second corrective call, never
    an unbounded loop, and never a dedicated repair prompt: this is the one
    generic self-correction, not 6.11's deleted ``scenario/yaml_syntax_repair``.

    The syntax fall-through exists because a response can miss the output
    contract entirely: live run 23ce9a6a (SCP-999) got a chatty reply — prose
    about an invented ``1_0|260|640|760`` marker, finish_reason=stop, not
    truncation — from ``scenario/visual_breakdown``. No line was repairable, so
    the run died, even though feeding "that wasn't YAML" back is exactly the fix.

    Truncation short-circuits ahead of all of this: ``_call_stage`` raises
    ``TruncationError`` before any parse, so it reaches the re-roll in
    ``_call_stage_with_retry`` and is never treated as a syntax failure.

    ``usage_sink``, when given, collects each underlying provider call's raw
    ``usage`` dict (one entry normally, two if the corrective retry fires) —
    Story 6.3's token/cache observability seam, additive to every existing
    caller. The deterministic YAML repair adds no provider call, so it appends
    nothing.

    ``semantic_fallback`` is the ONE exception to "a second failure propagates",
    and it is deliberately typed shut: it is invoked only when the retry's parse
    raises ``StoryArchetypeError`` — the class that means "everything in this
    packet is usable except its narrative-template choice" (Story 12.4). It adds
    no third provider call. Any other error from the retry, including a plain
    ``ValueError`` and a ``StoryArchetypeError`` from callers that pass no
    callback, propagates exactly as before.
    """
    raw, usage = await _call_stage(prompt_name, {**variables, "parse_error": ""}, s, call_llm, label=label)
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
            # Not the free-text-colon class. Dump the raw for characterization,
            # then fall through to the one corrective retry below.
            try:
                dump = _dump_bad_output("unfixed", prompt_name, raw)
                logger.warning(
                    "%s YAML parse failed and deterministic normalization did not fix it "
                    "(%s); retrying once with the error fed back; broken raw -> %s",
                    prompt_name, " ".join(str(exc2).split())[:160], dump,
                )
            except OSError:  # capture must never mask the real failure
                pass
            parse_error = (
                f"Previous output was not valid YAML: {' '.join(str(exc2).split())[:500]}. "
                "Your ENTIRE response must be the YAML document itself — no prose, no "
                "commentary, no markdown code fences, no backticks. Start at the first key."
            )
    except ValueError as exc:
        parse_error = (
            f"Previous output failed validation: {' '.join(str(exc).split())[:500]}. "
            "Output ONLY valid YAML, no prose, no markdown code fences."
        )
    raw, usage = await _call_stage(
        prompt_name, {**variables, "parse_error": parse_error}, s, call_llm, label=label
    )
    if usage_sink is not None:
        usage_sink.append(usage)
    if semantic_fallback is None:
        return parse(raw)
    try:
        return parse(raw)
    except StoryArchetypeError as archetype_exc:
        return semantic_fallback(archetype_exc)


async def reroll_on_truncation(what: str, call):
    """Story 6.9's truncation fallback, now applied to EVERY scenario stage —
    it is wired once inside ``_call_stage_with_retry``, not at call sites.

    Before this, only the *scoped repair* write could survive a
    ``TruncationError`` (``scenario_node`` routed it to a full rewrite); a
    truncation in the initial structure or writing generation killed the whole
    run — 6 of 6 live attempts on 2026-08-05 died exactly there.

    Recovery is one independent re-roll of the same call, because truncation
    here is VARIANCE, not a deterministic capacity wall: 6.9's AC3/AC4 finding,
    and directly confirmed on 2026-08-05 when ``scenario/structure`` — truncating
    4/4 at 16384 — passed cleanly the moment the budget doubled. A second
    truncation is a genuine shortfall and propagates, so the run still fails
    loudly rather than silently degrading twice.

    ``call`` must be a zero-arg factory returning a fresh coroutine (a coroutine
    object can only be awaited once).
    """
    try:
        return await call()
    except TruncationError as exc:
        logger.warning(
            "scenario: %s truncated (completion_tokens=%s); re-rolling once. runaway preview: %r",
            what, exc.completion_tokens, (exc.raw or "")[:300],
        )
        return await call()


def _parse_source_evidence(raw: object) -> dict[str, bool]:
    """Normalize the reported addendum inventory to the closed key set (Story 12.4).

    Unknown keys are dropped and every closed key gets an explicit bool, so the
    evidence gate reads a total function rather than guessing at absence. A
    non-mapping (or absent) inventory normalizes to "nothing reported", which
    makes only ``incident_first`` eligible — the fidelity-safe direction, since
    the alternative is letting an unverified archetype invent its framing device.
    """
    entries = raw if isinstance(raw, dict) else {}
    return {
        key: entries.get(key) is True or str(entries.get(key)).strip().lower() in ("true", "yes")
        for key in SOURCE_EVIDENCE_KEYS
    }


def _parse_story_archetype(data: dict) -> str:
    """The closed archetype value, casing/whitespace normalized (Story 12.4 AC2).

    Raises ``StoryArchetypeError`` — the one class ``_parse_with_retry`` can
    resolve deterministically — for a missing, non-string or unknown value.
    """
    raw = data.get("story_archetype")
    if not isinstance(raw, str):
        raise StoryArchetypeError(f"must be a string, got {type(raw).__name__}", research=data)
    value = raw.strip().lower()
    if value not in STORY_ARCHETYPES:
        raise StoryArchetypeError(f"{raw!r} is not one of {STORY_ARCHETYPES}", research=data)
    return value


def _fallback_rationale(reason: str) -> str:
    """The rationale that replaces the model's when code overrides its choice.

    Not cosmetic. ``structure_step`` dumps the whole research packet into
    ``{{research_packet}}``, directly under a prompt that names the injected guide
    the sole authority — so a surviving rationale arguing for the *rejected*
    archetype ("Addendum 173-4의 심문 기록이 증언 서사를 지지함") is a written
    invitation to reintroduce the framing device the evidence gate just refused.
    That is the invent-the-interview loss the gate exists to prevent, so the
    override rewrites the field it invalidated. The model's original wording is
    already in the WARNING beside it.
    """
    return (
        f"[code override] 모델이 고른 아키타입은 사용할 수 없었습니다 ({reason}). "
        f"파이프라인이 '{STORY_ARCHETYPE_FALLBACK}'로 결정했으므로, 모델이 제시한 원래 근거는 "
        "이 에피소드에 적용되지 않습니다 — 그 근거가 가리켰던 서사 장치를 되살리지 마세요."
    )


async def research_step(
    scp_id: str,
    scp_text: str,
    format_guide: str,
    s,
    call_llm,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> dict:
    def parse(raw: str) -> dict:
        data = _parse_yaml(raw)
        if isinstance(data, dict):
            for key in ("core_identity", "frozen_descriptor", "entity_sheet", "story_logline",
                        "hooks", "archetype_rationale"):
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
        # Story 12.4. Rationale FIRST and as a plain ValueError: it is an ordinary
        # required field, so it stays fatal after the one retry — the archetype
        # fallback must never smuggle a packet with no stated grounding past it.
        if not isinstance(data.get("archetype_rationale"), str) or not data["archetype_rationale"].strip():
            raise ValueError("research: payload missing non-empty 'archetype_rationale'")
        data["story_archetype"] = _parse_story_archetype(data)
        data["source_evidence"] = _parse_source_evidence(data.get("source_evidence"))
        return data

    def resolve_invalid_archetype(exc: StoryArchetypeError) -> dict:
        """Second invalid archetype in a row — resolve, never retry again (AC2)."""
        logger.warning(
            "research: story_archetype %s after one correction retry; falling back to %r",
            exc.reason, STORY_ARCHETYPE_FALLBACK,
        )
        return {
            **exc.research,
            "story_archetype": STORY_ARCHETYPE_FALLBACK,
            "source_evidence": _parse_source_evidence(exc.research.get("source_evidence")),
            "archetype_rationale": _fallback_rationale(exc.reason),
            "story_archetype_fallback_used": True,
        }

    research = await _call_stage_with_retry(
        "scenario/research",
        {
            "scp_id": scp_id,
            "scp_fact_sheet": scp_text,
            "main_text": scp_text,
            "format_guide": format_guide,
            "glossary_section": "",
        },
        s,
        call_llm,
        parse,
        label=label,
        usage_sink=usage_sink,
        semantic_fallback=resolve_invalid_archetype,
    )
    research.setdefault("story_archetype_fallback_used", False)
    # AFTER the await, deliberately — the evidence gate must NOT buy the model an
    # LLM correction attempt (AC2). "You picked an archetype whose framing device
    # isn't in the source" is not a formatting slip the model can talk its way out
    # of; it is a fidelity verdict on the source, so it resolves in code.
    if missing := missing_archetype_evidence(research["story_archetype"], research.get("source_evidence")):
        logger.warning(
            "research: story_archetype %r requires source evidence %s, none reported; "
            "falling back to %r",
            research["story_archetype"], list(missing), STORY_ARCHETYPE_FALLBACK,
        )
        research["story_archetype"] = STORY_ARCHETYPE_FALLBACK
        research["archetype_rationale"] = _fallback_rationale(
            f"requires source evidence {list(missing)}, none reported"
        )
        research["story_archetype_fallback_used"] = True
    return research


def archetype_guide(story_archetype: str, *, label: str | None = None) -> str:
    """The one selected archetype's guide text, from the Prompt Hub (Story 12.4 AC5).

    Fetched through the same label-aware seam every other stage prompt uses, so
    the suspended candidate workflow keeps working and repo files stay authoring
    sources rather than runtime reads. Only the SELECTED guide is fetched: four
    guides in every structure call would be token bloat plus three templates the
    model was told not to follow.
    """
    if story_archetype not in STORY_ARCHETYPES:
        # Unreachable via research_step (which resolves before returning); a direct
        # caller passing junk gets production's pre-12.4 behavior, not a crash.
        logger.warning("structure: unknown story_archetype %r; using %r guide",
                       story_archetype, STORY_ARCHETYPE_FALLBACK)
        story_archetype = STORY_ARCHETYPE_FALLBACK
    name = f"scenario/archetypes/{story_archetype}"
    prompt = (
        prompt_service.get_prompt_with_fallback(name, label=label)
        if label
        else prompt_service.get_prompt(name)
    )
    return prompt.compile()


async def structure_step(
    scp_id: str,
    research: dict,
    format_guide: str,
    s,
    call_llm,
    *,
    story_archetype: str = STORY_ARCHETYPE_FALLBACK,
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

    scenes = await _call_stage_with_retry(
        "scenario/structure",
        {
            "scp_id": scp_id,
            "research_packet": json.dumps(research, ensure_ascii=False),
            "scp_visual_reference": research["frozen_descriptor"],
            "target_duration": TARGET_DURATION_MINUTES,
            "format_guide": format_guide,
            # Passed explicitly rather than read out of `research_packet`: the choice
            # was already made and this stage's job is to OBEY it, so the value it
            # follows must be the same one the state/trace/eval record (AC3).
            "story_archetype": story_archetype,
            "archetype_guide": archetype_guide(story_archetype, label=label),
            "glossary_section": "",
        },
        s,
        call_llm,
        parse,
        label=label,
        usage_sink=usage_sink,
    )
    # AFTER the await, never inside `parse` (Story 12.1 AC7): raising from the
    # callback would spend one LLM regeneration on a retention violation.
    # A broken ledger is a planning failure, not a formatting slip — it fails the
    # run loudly rather than being re-rolled or silently repaired.
    _validate_retention_outline(scenes)
    return scenes


def _loops_to_close_context(structure: list[dict], idx: int) -> dict[str, str]:
    """For each loop this scene must close, the earlier scene that planted it.

    Writing is one call per scene and the neighbour context is a one-line summary
    of ±1 scene only, but the contract forbids closing a loop in the scene that
    planted it — so a closure is non-adjacent by construction. Without this the
    writer of scene 7 sees the bare string ``loop_redacted_page7`` and is told by
    ``writing.md`` to answer that question; it can only invent one, which is the
    ungrounded assertion ``critic_agent.md`` criterion 7 exists to catch.
    """
    scene = structure[idx] if isinstance(structure[idx], dict) else {}
    closes = scene.get("loops_closed")
    if not isinstance(closes, list):
        return {}
    context: dict[str, str] = {}
    for loop_id in closes:
        for pos, earlier in enumerate(structure[:idx], start=1):
            planted = earlier.get("loops_planted") if isinstance(earlier, dict) else None
            if isinstance(planted, list) and loop_id in planted:
                context[str(loop_id)] = f"scene {pos}: {_scene_role_text(earlier)}"
                break
    return context


def _writing_scene_brief(structure: list[dict], idx: int) -> str:
    """The ``scene_structure`` variable for ONE scene's writing call.

    Carries the minimum cross-scene context narration continuity needs — the
    neighbours' compact ``act / beat: synopsis`` line (``_scene_role_text``, the
    same one-line summary ``visual_breakdown_step`` already gets) — and nothing
    else. With no context at all a per-scene call re-tells the previous scene's
    beat or resolves what a later scene exists to reveal; with the siblings' full
    narration we would be back to the payload size batching exists to avoid.

    The steering sentence lives in this variable rather than in the prompt
    template because ``scene_structure`` is free text: no Langfuse prompt version
    has to move for the batching to take effect.
    """
    total = len(structure)
    scene = structure[idx] if isinstance(structure[idx], dict) else {}
    payload = {
        "write_only_this_scene": {**scene, "scene_num": idx + 1},
        "previous_scene_context": _scene_role_text(structure[idx - 1]) if idx else None,
        "next_scene_context": _scene_role_text(structure[idx + 1]) if idx + 1 < total else None,
        "loops_to_close_context": _loops_to_close_context(structure, idx),
    }
    return (
        f"You are writing SCENE {idx + 1} OF {total} ONLY. Output a `scenes` list holding "
        "exactly ONE scene object: the one under `write_only_this_scene`. "
        "`previous_scene_context` / `next_scene_context` exist only so your narration "
        "connects to its neighbours — never write narration for them, and never resolve "
        "what a later scene is there to reveal. `loops_to_close_context` maps each id in "
        "this scene's `loops_closed` to the earlier scene that planted it — that is the "
        "question you owe an answer to here.\n"
        + json.dumps(payload, ensure_ascii=False)
    )


async def writing_step(
    scp_id: str,
    structure: list[dict],
    frozen_descriptor: str,
    format_guide: str,
    quality_feedback: str,
    s,
    call_llm,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> dict:
    """Write every scene's narration — ONE LLM call per scene, concurrently.

    Story 12.2: this stage runs on Gemini (``scenario._call_gemini``).

    Batched 2026-08-05 after 6 live run attempts proved the single all-scenes call
    unusable: with 8-12 scenes in one completion, ``YTFLOW_DEEPSEEK_MAX_TOKENS``
    16384 and 32768 both truncated (``finish_reason=length``), and at 65536 one
    call was still outstanding after 29 minutes (0.3% CPU, open HTTPS connection,
    zero artifacts). Raising the budget only trades truncation for unusable
    latency; splitting the call removes the volume instead. Each scene's
    completion is small and the calls overlap, so wall-clock is roughly one scene.

    # ponytail: one scene per call, no group-size knob — a group re-introduces the
    # exact variable that broke, and per-scene is already the smallest unit the
    # positional scene contract allows.

    Returns the same ``{"scp_id", "scenes": [...]}`` shape the single call did.
    Order is ``structure``'s order (``asyncio.gather`` returns results in argument
    order, not completion order) and each scene's ``scene_num`` is *forced* to its
    1-based position — see the assembly comment.
    """
    if not structure:
        raise ValueError("writing: structure has no scenes")

    async def _write_one(idx: int) -> dict:
        def parse(raw: str) -> dict:
            data = _parse_yaml(raw)
            scenes = data.get("scenes") if isinstance(data, dict) else None
            if not isinstance(scenes, list) or len(scenes) != 1:
                raise ValueError(
                    f"writing: scene {idx + 1} call must return exactly 1 scene, got "
                    f"{len(scenes) if isinstance(scenes, list) else 'non-list'}"
                )
            scene = scenes[0]
            if not isinstance(scene, dict):
                raise ValueError(f"writing: malformed scene {scene!r}")
            if not isinstance(scene.get("narration"), str) or not scene["narration"].strip():
                raise ValueError(f"writing: scene[{idx + 1}] has empty narration")
            scene["narration"] = _normalize_freetext(scene["narration"])
            # The fields the image stages consume directly, all REQUIRED by the prompt
            # since it was repatriated from production — so absence is model variance,
            # not a prompt-variant gap, and is worth the one corrective retry. Ungated
            # (unlike `title`): no writing variant omits them. A scene still missing one
            # after the retry degrades to the _DEFAULT_* stand-in rather than crashing.
            for field in _REQUIRED_WRITING_VISUAL_FIELDS:
                if not str(scene.get(field) or "").strip():
                    raise ValueError(f"writing: scene[{idx + 1}] missing non-empty {field!r}")
            return scene

        # Per-scene re-roll: a truncated scene costs one small re-call, not the
        # whole stage — the finest granularity the batching makes available. The
        # re-roll itself lives in `_call_stage_with_retry`; because writing calls
        # it once per scene, that IS per-scene granularity. `what` keeps the log
        # naming the scene.
        return await _call_stage_with_retry(
            "scenario/writing",
            {
                "scp_id": scp_id,
                "scene_structure": _writing_scene_brief(structure, idx),
                "scp_visual_reference": frozen_descriptor,
                "format_guide": format_guide,
                "glossary_section": "",
                "quality_feedback": quality_feedback,
            },
            s,
            call_llm,
            parse,
            label=label,
            usage_sink=usage_sink,
            what=f"writing scene {idx + 1}",
        )

    scenes = await asyncio.gather(*(_write_one(idx) for idx in range(len(structure))))
    # scene_num is positional, never the model's. ``build_scenes`` reads mood/title/
    # kicker from ``structure[idx]`` and ``scenario._retry_scope`` maps a reviewer's
    # scene_num back with ``idx = raw - 1`` and then asserts
    # ``scenes[idx]["scene_num"] == raw`` (the 6.5/6.6 mismatch guard). A per-scene
    # call has no way to know its own index — asked in isolation the model answers
    # "1" every time — so position is now the only source of scene_num rather than
    # something that guard has to catch drifting.
    return {"scp_id": scp_id, "scenes": [{**scene, "scene_num": idx + 1} for idx, scene in enumerate(scenes)]}


async def writing_scene_repair_step(
    scp_id: str,
    original_scenes: list[dict],
    scene_structure: list[dict],
    scene_feedback: str,
    frozen_descriptor: str,
    format_guide: str,
    s,
    call_llm,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> list[dict]:
    """Repair an exact positional subset without trusting model scene numbers.

    ``scene_structure`` is the SAME subset in the SAME order — the caller pairs
    it by position (Story 12.1 AC9). Without it a repair sees only prose and
    reviewer feedback, so it can drop a promised loop closure, swap an event's
    consequence, or replace the scene's grounded facts with atmosphere; those are
    exactly the defects the retention contract exists to prevent.
    """
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
            "scene_structure": json.dumps(scene_structure, ensure_ascii=False),
            "scene_feedback": scene_feedback,
            "scp_visual_reference": frozen_descriptor,
            "format_guide": format_guide,
            "glossary_section": "",
        },
        s,
        call_llm,
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
    call_llm,
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
            # 8.19: roles, not bare keys — bare keys made the LLM substitute the
            # nearest stock card for any person the narration mentioned.
            "stock_cast_catalog": "\n".join(
                f"  - `{key}` — {role}" for key, role in STOCK_CAST_ROLES.items()
            ),
            "characters_present": json.dumps(scene.get("characters_present", []), ensure_ascii=False),
            "numbered_sentences": numbered,
            "sentence_count": len(sentences),
        },
        s,
        call_llm,
        parse,
        label=label,
        usage_sink=usage_sink,
    )


def _cast_union(cast_by_sentence: dict, start: int, end: int) -> list:
    """Every cast member appearing in sentences ``start..end``, deduped by ``card_key``.

    First occurrence wins, so the earliest sentence's ``position``/``depth``/``pose``
    are the ones the merged shot renders — the frame is staged for the beat it opens
    on. Order is narration order (Story 10.4).
    """
    merged: list = []
    seen: set = set()
    for number in range(start, end + 1):
        for member in cast_by_sentence.get(number) or []:
            key = member.get("card_key") if isinstance(member, dict) else repr(member)
            if key in seen:
                continue
            seen.add(key)
            merged.append(member)
    return merged


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
    call_llm,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> list[dict]:
    numbered = "\n".join(f"{i + 1}. {sent}" for i, sent in enumerate(sentences))

    def parse(raw: str) -> list[dict]:
        data = _parse_yaml(raw)
        shots = data.get("visual_descriptions") if isinstance(data, dict) else None
        count = len(sentences)
        if not isinstance(shots, list) or not shots:
            raise ValueError(
                f"visual_breakdown: expected a non-empty visual_descriptions list "
                f"({count} sentences), got {type(shots).__name__ if shots is not None else 'nothing'}"
            )
        if len(shots) > count:
            # The stated bound (Story 10.4). The ordered cover may redistribute frames
            # across sentences, never mint more of them than the 1:1 mapping already
            # cost — a cover with no ceiling lets one scene order 40 renders.
            raise ValueError(
                f"visual_breakdown: {len(shots)} shots for {count} sentences — the cover may "
                f"never emit more shots than sentences; merge a sentence to pay for a split"
            )
        covered: set[int] = set()
        prev_start = prev_end = 0
        for position, shot in enumerate(shots, start=1):
            if not isinstance(shot, dict):
                raise ValueError(f"visual_breakdown: malformed shot {shot!r}")
            for key in ("image_prompt", "negative_prompt"):
                if isinstance(shot.get(key), str):
                    shot[key] = _normalize_freetext(shot[key])
            start = shot.get("sentence_start")
            # A shot that omits sentence_end — or writes it as YAML null, which is the
            # same statement — covers exactly its start sentence, so the pre-cover
            # shape stays valid rather than becoming a parse failure.
            end = shot.get("sentence_end")
            if end is None:
                end = start
            if type(start) is not int:
                raise ValueError(f"visual_breakdown: invalid sentence_start {start!r} on shot {position}")
            if type(end) is not int:
                raise ValueError(f"visual_breakdown: invalid sentence_end {end!r} on shot {position}")
            if not 1 <= start <= end <= count:
                raise ValueError(
                    f"visual_breakdown: shot {position} range {start}..{end} is inverted or "
                    f"outside 1..{count}"
                )
            if start < prev_start or end < prev_end:
                raise ValueError(
                    f"visual_breakdown: shot {position} range {start}..{end} moves backwards "
                    f"from the previous shot's {prev_start}..{prev_end}; the cover is ordered"
                )
            shot["sentence_end"] = end
            # Cast is decided authoritatively by cast_decision_step (Story 8.10) — attach
            # it here regardless of anything the model echoed. A shot spanning several
            # sentences takes their union, so a merge never drops whoever was in frame.
            shot["cast"] = _cast_union(cast_by_sentence, start, end)
            covered.update(range(start, end + 1))
            prev_start, prev_end = start, end
        missing = sorted(set(range(1, count + 1)) - covered)
        if missing:
            raise ValueError(
                f"visual_breakdown: sentences {missing} are covered by no shot; every sentence "
                f"must belong to at least one shot (extend a neighbouring shot's range)"
            )
        return shots

    return await _call_stage_with_retry(
        "scenario/visual_breakdown",
        {
            "scene_num": scene["scene_num"],
            "location": scene.get("location") or _DEFAULT_LOCATION,
            "characters_present": json.dumps(scene.get("characters_present", []), ensure_ascii=False),
            "color_palette": scene.get("color_palette") or _DEFAULT_COLOR_PALETTE,
            "atmosphere": scene.get("atmosphere") or _DEFAULT_ATMOSPHERE,
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
        call_llm,
        parse,
        label=label,
        usage_sink=usage_sink,
    )


_VALID_VERDICTS = {"pass", "retry", "accept_with_notes"}
# Worst verdict wins when aggregating per-scene critics: one scene demanding a
# rewrite is enough to send the whole script back.
_VERDICT_RANK = ("pass", "accept_with_notes", "retry")


def _scene_review_brief(idx: int, total: int) -> str:
    """Steering prefix for a single-scene review/critic call.

    Lives in the stage's free-text variable (``narration_script`` /
    ``scenario_json``) rather than in the prompt template, so no Langfuse prompt
    version has to move for the batching to take effect — the same trick
    ``_writing_scene_brief`` uses for ``scene_structure``.
    """
    opening = "" if idx == 0 else (
        " This is NOT the opening scene, so checks written for Scene 1 only (hook "
        "strength, opening line) do not apply — skip them."
    )
    return (
        f"You are reviewing SCENE {idx + 1} OF {total} ONLY. The payload below holds that one "
        f"scene and nothing else; judge it as part of a {total}-scene script, not as a "
        f"standalone piece.{opening} Report every `scene_num` as {idx + 1}.\n"
    )


def _stamped(items: object, idx: int) -> list:
    """Force ``scene_num`` to the call's own 1-based position on every entry.

    A per-scene call cannot know its index — asked in isolation the model answers
    "1" every time (the ``writing_step`` lesson) — and ``scenario._retry_scope``
    maps ``scene_num`` back to a position and then asserts the scene at that
    position agrees. Position is therefore the only source of ``scene_num`` here
    too, exactly as it is for ``writing_step``. Non-dict entries pass through
    untouched so ``_retry_scope`` still records them as rejected evidence.
    """
    entries = items if isinstance(items, list) else []
    return [{**item, "scene_num": idx + 1} if isinstance(item, dict) else item for item in entries]


_CONTRADICTION_EVIDENCE = (
    "narration_quote", "grounding_source", "grounding_quote", "explanation", "correction",
)
# The only three grounding artifacts the review is given. An unlisted source name
# means the model graded the narration against its own knowledge of the SCP — the
# exact failure the prompt's grounding section forbids — so it is not evidence.
GROUNDING_SOURCES = ("entity_sheet", "frozen_descriptor", "scp_text")


def _validated_contradiction(item: object, position: int) -> GroundedContradiction:
    """One entry, held to the evidence bar. Raises ``ValueError`` if it fails."""
    if not isinstance(item, dict):
        raise ValueError(f"review: grounded_contradiction #{position} is not a mapping: {item!r}")
    for field in _CONTRADICTION_EVIDENCE:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"review: grounded_contradiction #{position} needs a non-empty {field!r} — "
                "quote the exact narration and the exact conflicting grounding text, or omit "
                "the contradiction entirely"
            )
        item[field] = _normalize_freetext(value)
    if item["grounding_source"] not in GROUNDING_SOURCES:
        raise ValueError(
            f"review: grounded_contradiction #{position} has grounding_source "
            f"{item['grounding_source']!r} — must be one of {GROUNDING_SOURCES}; the narration "
            "may only be contradicted by a source that was actually supplied"
        )
    return cast(GroundedContradiction, item)


def _validate_grounded_contradictions(data: dict, *, strict: bool = True) -> list[GroundedContradiction]:
    """Story 12.3 AC4 — evidence-or-nothing, decided in code.

    An unevidenced "this contradicts the source" claim is worse than silence: it
    sends the scoped repair after a scene with no quote to fix and no way for the
    operator to check the call. So on the first parse a malformed claim raises
    ``ValueError``, which buys exactly one prompt-level correction inside
    ``_parse_with_retry`` — the same bound every other semantic failure gets.

    ``strict=False`` is that retry: the claim is still rejected, but by DROPPING it
    with a WARNING rather than by killing the run. This field is a diagnostic the
    story added on top of a working pipeline; a model that cannot quote its evidence
    twice must not be able to fail a scenario that is otherwise fine [AD-10]. The
    required-contract fields (``overall_pass`` and friends) keep failing hard, as
    they must — the pipeline cannot proceed without those.

    Absent / ``None`` is the normal clean case and stays clean; only a *claimed*
    contradiction is held to the evidence bar.
    """
    raw = data.get("grounded_contradictions")
    if raw is None:
        return []
    if not isinstance(raw, list):
        if not strict:
            logger.warning(
                "review: dropping 'grounded_contradictions' — expected a list, got %s (after the "
                "one allowed correction)", type(raw).__name__,
            )
            return []
        raise ValueError(
            f"review: 'grounded_contradictions' must be a list of grounded_contradiction "
            f"entries, got {type(raw).__name__}"
        )
    entries: list[GroundedContradiction] = []
    for position, item in enumerate(raw, start=1):
        try:
            entries.append(_validated_contradiction(item, position))
        except ValueError:
            if strict:
                raise
            logger.warning(
                "review: dropping unevidenced grounded_contradiction #%d after the one allowed "
                "correction — the claim is rejected, the run is not. entry: %.300r", position, item,
            )
    return entries


def _apply_grounded_contradictions(data: dict, entries: list[GroundedContradiction]) -> None:
    """Force the consequences of a contradiction rather than trusting the prompt.

    Two things the model is asked to do and demonstrably may not: fail the review,
    and mirror the contradiction into ``issues[]`` so ``scenario._retry_scope``
    picks the scene up. Both are re-derived here from the evidence — the mirrored
    issues are rebuilt from scratch (any model-authored ``grounded_contradiction``
    issue is dropped first) so the mapping stays exactly 1:1.
    """
    # Write the VALIDATED list back: it is what `_aggregate_review` merges and what
    # reaches the gate, so a claim the validator dropped must not survive in the raw
    # payload. (It is also the only reason the two functions must stay paired.)
    if "grounded_contradictions" in data or entries:
        data["grounded_contradictions"] = entries
    if not entries:
        return
    data["overall_pass"] = False
    existing = data.get("issues")
    kept = [
        issue for issue in (existing if isinstance(existing, list) else [])
        if not (isinstance(issue, dict) and issue.get("type") == "grounded_contradiction")
    ]
    data["issues"] = kept + [
        {
            "scene_num": entry.get("scene_num") if type(entry.get("scene_num")) is int else 1,
            "type": "grounded_contradiction",
            "severity": "critical",
            "description": (
                f"narration contradicts {entry['grounding_source']}: "
                f"\"{entry['narration_quote']}\" vs \"{entry['grounding_quote']}\" — "
                f"{entry['explanation']}"
            ),
            "correction": entry["correction"],
        }
        for entry in entries
    ]


def _aggregate_review(reports: list[dict]) -> dict:
    """Merge per-scene review reports into the single report ``scenario.py`` consumes."""
    merged: dict = {
        "overall_pass": all(bool(report.get("overall_pass")) for report in reports),
        "issues": [],
        "corrections": [],
        "storytelling_issues": [],
        "grounded_contradictions": [],
    }
    coverages: list[float] = []
    scores: list[float] = []
    for idx, report in enumerate(reports):
        for key in ("issues", "corrections", "storytelling_issues", "grounded_contradictions"):
            merged[key].extend(_stamped(report.get(key), idx))
        for sink, key in ((coverages, "coverage_pct"), (scores, "storytelling_score")):
            value = report.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sink.append(float(value))
    # coverage_pct is a whole-script "% of the source facts that appear" metric, but a
    # per-scene call sees only its own scene against the full fact sheet, so it reports
    # what THAT scene covers. max() is the closest honest whole-script figure (a lower
    # bound: a fact covered anywhere counts once); a mean would report roughly 1/N of
    # reality. storytelling_score is a per-scene quality rating by construction, so the
    # mean means the same thing it always did. Neither is read by production code today.
    if coverages:
        merged["coverage_pct"] = max(coverages)
    if scores:
        merged["storytelling_score"] = round(sum(scores) / len(scores), 1)
    return merged


def _aggregate_critic(reports: list[dict]) -> dict:
    """Merge per-scene critic reports into the single verdict ``scenario.py`` consumes."""
    return {
        "verdict": max((report["verdict"] for report in reports), key=_VERDICT_RANK.index),
        # Scene-prefixed so `_format_feedback`'s whole-script rewrite brief keeps
        # scene identity — a per-scene critic writes "이 장면은…" with no number.
        "feedback": "\n".join(
            f"Scene {idx + 1}: {text}"
            for idx, report in enumerate(reports)
            if (text := str(report.get("feedback") or "").strip())
        ),
        "scene_notes": [
            note for idx, report in enumerate(reports) for note in _stamped(report.get("scene_notes"), idx)
        ],
    }
    # ponytail: hook_effective / retention_risk / ending_impact are dropped — the
    # prompt emits them, nothing reads them. Aggregate when a consumer appears.


async def review_step(
    scp_text: str,
    writing: dict,
    visual_by_scene: dict,
    frozen_descriptor: str,
    format_guide: str,
    s,
    call_llm,
    *,
    entity_sheet: str = "",
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> dict:
    """Fact-check + quality review — ONE LLM call per scene, concurrently.

    Story 12.2: this stage runs on Gemini (``scenario._call_gemini``).

    Batched 2026-08-05 for the same reason ``writing_step`` was: live run 370666ba
    (SCP-999, 9 scenes) truncated this stage twice, so even the central re-roll in
    ``_call_stage_with_retry`` couldn't save it. The dump proves the shape of the
    failure — ``completion_tokens=32765``, ``raw_chars=99629``, all of it
    ``reasoning_content`` ("Need inspect script vs source facts… Need check…") and
    zero emitted content. Reasoning over a whole-script input exhausts the budget
    before the report starts. Raising ``max_tokens`` only defers it; one scene per
    call removes the volume.

    ``entity_sheet`` is Story 12.3's third grounding source, alongside the
    ``scp_text`` fact sheet and the ``frozen_descriptor`` visual profile: the
    review could not previously catch narration that contradicts the cast/entity
    roster because it never saw it. Keyword-only with an empty default so every
    existing positional call site stays valid; ``scenario.py`` passes it at both
    call sites (initial write and scoped repair).

    Returns the same aggregated report shape the single call did — see
    ``_aggregate_review`` for how each field is combined.
    """
    scenes = writing.get("scenes") or []
    if not scenes:
        raise ValueError("review: writing has no scenes")

    def _make_parse():
        """One parser per scene call, because it counts ITS OWN attempts — the scenes
        are reviewed concurrently, so a shared counter would leak between them."""
        attempts = 0

        def parse(raw: str) -> dict:
            nonlocal attempts
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
            # Counted only once the payload is structurally sound, so the YAMLError
            # branch's deterministic re-parse (Story 6.11) does not spend the attempt.
            attempts += 1
            # Validate BEFORE applying: a claim without evidence must not be able to
            # fail the review on the strength of a sentence nobody can check (AC4).
            # First attempt is strict (buys the model its one correction); after that
            # the unevidenced claim is dropped rather than failing the whole run.
            _apply_grounded_contradictions(
                data, _validate_grounded_contradictions(data, strict=attempts == 1)
            )
            return data

        return parse

    async def _review_one(idx: int, scene: dict) -> dict:
        return await _call_stage_with_retry(
            "scenario/review",
            {
                "scp_id": writing.get("scp_id", ""),
                "scp_fact_sheet": scp_text,
                "narration_script": _scene_review_brief(idx, len(scenes))
                + json.dumps({**writing, "scenes": [scene]}, ensure_ascii=False),
                "visual_descriptions": json.dumps(visual_by_scene.get(idx, []), ensure_ascii=False),
                "scp_visual_reference": frozen_descriptor,
                "entity_sheet": entity_sheet,
                "format_guide": format_guide,
                "glossary_section": "",
            },
            s,
            call_llm,
            _make_parse(),
            label=label,
            usage_sink=usage_sink,
            what=f"review scene {idx + 1}",
        )

    # gather returns results in ARGUMENT order, not completion order — the index
    # each report is stamped with in `_aggregate_review` is its own scene's.
    reports = await asyncio.gather(*(_review_one(idx, scene) for idx, scene in enumerate(scenes)))
    return _aggregate_review(list(reports))


async def critic_step(
    scp_text: str,
    writing: dict,
    visual_by_scene: dict,
    format_guide: str,
    s,
    call_llm,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> dict:
    """Viewer-perspective critique — ONE LLM call per scene, concurrently.

    Story 12.2: this stage runs on Gemini (``scenario._call_gemini``).

    Same whole-script input shape as ``review_step``, so the same reasoning-token
    exhaustion was next in line; batched pre-emptively alongside it.

    Takes ``scp_text`` for the same reason ``review_step`` does (Story 12.1 AC12a):
    every criterion used to judge *delivery* only, so filler that correctly applied
    all six mandated immersion techniques scored as immersive — the critic
    structurally could not report a scene that says nothing. Substance and fidelity
    are judged against this fact sheet, never against the model's own SCP knowledge.
    """
    scenes = writing.get("scenes") or []
    if not scenes:
        raise ValueError("critic_agent: writing has no scenes")

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

    async def _critique_one(idx: int, scene: dict) -> dict:
        scenario_json = {
            "writing": {**writing, "scenes": [scene]},
            "visual_descriptions": visual_by_scene.get(idx, []),
        }
        return await _call_stage_with_retry(
            "scenario/critic_agent",
            {
                "format_guide": format_guide,
                "scp_fact_sheet": scp_text,
                "scenario_json": _scene_review_brief(idx, len(scenes))
                + json.dumps(scenario_json, ensure_ascii=False),
            },
            s,
            call_llm,
            parse,
            label=label,
            usage_sink=usage_sink,
            what=f"critic_agent scene {idx + 1}",
        )

    reports = await asyncio.gather(*(_critique_one(idx, scene) for idx, scene in enumerate(scenes)))
    return _aggregate_critic(list(reports))


async def tts_normalize_step(
    writing: dict,
    format_guide: str,
    s,
    call_llm,
    *,
    label: str | None = None,
    usage_sink: list[dict] | None = None,
) -> dict:
    """Rewrite each scene's narration for natural Korean TTS — ONE call per scene.

    Batched 2026-08-06 (live run bad091eb, SCP-999) for the same reason as
    ``writing`` (f7639b2) and ``review``/``critic`` (53e5c8f): the dump header
    ``completion_tokens=32768 raw_chars=77634`` on the whole-script call is
    reasoning-token exhaustion, not narration volume. This was the last scenario
    stage still sending every scene in one completion.

    The three validations the single call enforced are unchanged, just relocated:
    the per-scene ``parse`` rejects a malformed scene and an empty narration for
    ITS scene, and issuing exactly one call per original scene — each of which
    must return exactly one scene — is what makes the aggregate scene count equal
    ``len(original_scenes)``.

    A scene whose normalized sentence count doesn't match the original (per
    ``split_sentences()``) keeps its original narration instead of failing the
    whole scenario stage — see story 5-4-tts-korean-naturalization.md.
    """
    original_scenes = writing["scenes"]
    total = len(original_scenes)

    async def _normalize_one(idx: int, original: dict) -> dict:
        def parse(raw: str) -> dict:
            data = _parse_yaml(raw)
            scenes = data.get("scenes") if isinstance(data, dict) else None
            if not isinstance(scenes, list) or len(scenes) != 1:
                got = len(scenes) if isinstance(scenes, list) else "non-list"
                raise ValueError(f"tts_normalize: scene {idx + 1} call must return exactly 1 scene, got {got}")
            scene = scenes[0]
            if not isinstance(scene, dict):
                raise ValueError(f"tts_normalize: malformed scene {scene!r}")
            if not isinstance(scene.get("narration"), str) or not scene["narration"].strip():
                raise ValueError(f"tts_normalize: scene[{idx + 1}] has empty narration")
            return {"narration": _normalize_freetext(scene["narration"])}

        return await _call_stage_with_retry(
            "scenario/tts_normalize",
            {
                # The steering prefix rides the free-text `scenes_json` variable, so
                # no Langfuse prompt version has to move — the same trick
                # `_writing_scene_brief` / `_scene_review_brief` use.
                "scenes_json": (
                    f"You are normalizing SCENE {idx + 1} OF {total} ONLY. The list below holds "
                    "that one scene and nothing else. Output a `scenes` list containing exactly "
                    f"ONE scene object with `scene_num: {idx + 1}`. Rule 5's scene-order/count "
                    "invariant is satisfied by returning that single scene; Rule 2's sentence-count "
                    "invariant still applies within it.\n"
                    + json.dumps(
                        [{"scene_num": idx + 1, "narration": original.get("narration", "")}], ensure_ascii=False
                    )
                ),
                "format_guide": format_guide,
            },
            s,
            call_llm,
            parse,
            label=label,
            usage_sink=usage_sink,
            what=f"tts_normalize scene {idx + 1}",
        )

    # gather returns results in ARGUMENT order, not completion order, so zipping
    # against `original_scenes` below stays aligned however the calls interleave.
    # scene_num is never read back off the model — the aggregation keeps each
    # ORIGINAL scene dict wholesale and replaces only its narration text.
    normalized_scenes = await asyncio.gather(
        *(_normalize_one(idx, original) for idx, original in enumerate(original_scenes))
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
            # The designation still gets spelled — a degraded track is still spoken aloud.
            updated_scenes.append({
                **original_scene,
                "narration": spell_scp_designations(original_narration),
                "display_narration": original_narration,
            })
            continue
        updated_scenes.append({
            **original_scene,
            "narration": spell_scp_designations(normalized_narration),
            "display_narration": original_narration,
        })

    return {**writing, "scenes": updated_scenes}


def _fallback_prompt(scene: dict) -> str:
    """Minimal prompt for a leading transition-only sentence with nothing to merge into.

    Story 10.4b: the old text ended in ``"no visible subject"``, which made this
    backfill a code-side instance of the exact defect that story removes — a prompt
    whose subject is an absence renders as unreadable geometry, because diffusion
    cannot draw a nothing. It also matched ``_NO_FIGURE_FRAMINGS``, so the shot lost
    its cast as a side effect of a phrase chosen to mean "placeholder".

    The floor is a subject: it exists in every location, it takes the scene's own
    atmosphere, and it gives the renderer a surface to describe.

    ponytail: this backfill only fires when a scene's FIRST sentence has an empty
    ``image_prompt`` and there is no earlier shot to merge into — the merge at the
    call site is backward-only. The prompt now tells the model to widen the first
    shot's range forward instead (``sentence_start: 1, sentence_end: 2``), which the
    ordered cover already accepts, so this path should get rarer. Add a forward merge
    only if it is ever measured to still fire.
    """
    location = scene.get("location") or _DEFAULT_LOCATION
    atmosphere = scene.get("atmosphere") or _DEFAULT_ATMOSPHERE
    return f"static wide shot, {location}, {atmosphere}, worn floor surface in the foreground"


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
            # The ordered cover (Story 10.4): a shot owns sentence_start..sentence_end.
            # A shot with no sentence_end owns just its start — every pre-cover
            # checkpoint and every pre-cover test keeps producing a one-element list.
            start = raw_shot["sentence_start"]
            end = raw_shot.get("sentence_end")
            if type(end) is not int or end < start:
                end = start
            sentence_idxs = list(range(start - 1, end))  # 1-based -> 0-based
            image_prompt = str(raw_shot.get("image_prompt") or "").strip()

            if not image_prompt:
                if shots:
                    shots[-1]["sentence_indices"].extend(sentence_idxs)
                    continue
                # No previous shot to merge into (leading transition sentence) — backfill.
                image_prompt = _fallback_prompt(writing_scene)
                # "no visible subject" backfill prompt — cast is always empty here,
                # regardless of what the LLM emitted for this transition sentence.
                raw_shot = {**raw_shot, "negative_prompt": raw_shot.get("negative_prompt") or "", "cast": []}

            shots.append(
                ShotData(
                    shot_id=f"S{scene_num:03d}{i:02d}",
                    sentence_indices=sentence_idxs,
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
        _suppress_cast_on_no_figure_framing(shots)  # 8.19 before 8.18: drop first, then place
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
