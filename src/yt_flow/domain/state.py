"""Domain state types — the single shared type substrate for the pipeline.

Pure stdlib typing only. This module MUST NOT import any upper layer
(pipeline, services, db, api); the layered dependency rule is
`api -> services -> (pipeline | db) -> domain`. [AD-1]

These are TypedDicts, not Pydantic models, because LangGraph state is the
source of truth and must stay plain JSON-serializable for checkpointing. [AD-2]
"""

from typing import Literal, NotRequired, TypedDict, get_args

StageName = Literal["scenario", "image", "tts", "subtitle", "video"]
GateState = Literal["pending", "approved", "rejected", "n/a"]
PromptVariant = Literal["A", "B"]
AngleName = Literal["front", "back", "side", "three_quarter"]
CastPosition = Literal["left", "center", "right"]
CastDepth = Literal["near", "mid", "far"]
CastPose = Literal["standing", "sitting"]  # closed v1 vocabulary — free-text special
                                            # poses arrive via Story 8.4's pose_hint field

# Story 8.8: closed micro-motion vocabulary the LLM selects per cast member,
# rendered procedurally by video_node. No amplitude/frequency knobs — those
# stay server-side constants (Interfaces rule: closed enums are the point).
CharacterMotionStyle = Literal["hold", "breath", "sway", "tremble", "pulse", "glitch"]
CharacterMotionEnergy = Literal["low", "medium", "high"]

# Story 8.9: closed screen-blocking vocabulary for a card's movement *through*
# the frame (distinct from 8.8's in-place idle motion above). Cinematic
# blocking, not a walk-cycle sim — video_node maps each mode to a
# deterministic x/y/scale curve over the shot's duration.
CharacterMovementMode = Literal[
    "anchored", "drift", "enter", "exit", "cross", "approach", "retreat",
]
CharacterMovementDirection = Literal["none", "left", "right", "in", "out"]
CharacterMovementPace = Literal["slow", "medium", "fast"]

STOCK_CAST_KEYS = ("STOCK-d-class", "STOCK-researcher", "STOCK-security")  # single source of truth

# Story 8.19 — controlled role descriptions for the stock cast. Diagnosed cause:
# cast_decision received *bare* key names, so whenever a sentence mentioned any
# person it reached for the nearest stock key regardless of fit (villagers ->
# STOCK-d-class in an orange prison jumpsuit; "지역 경찰" -> STOCK-security as a
# facility guard). Naming the role makes "no stock role fits -> empty cast" a
# decidable call. Lives beside the keys so the prompt catalog cannot drift.
STOCK_CAST_ROLES: dict[str, str] = {
    "STOCK-d-class": "Foundation D-class test subject — orange prison jumpsuit with a stenciled number. Only ever inside Foundation custody.",
    "STOCK-researcher": "Foundation research staff — white lab coat, ID badge, clinical posture. Site personnel, never a civilian doctor.",
    "STOCK-security": "Foundation site security — black tactical vest and cap, alert posture. A facility guard, never civilian police or military.",
}
assert set(STOCK_CAST_ROLES) == set(STOCK_CAST_KEYS)  # the prompt catalog must cover every key

# Story 8.5 — closed location key vocabulary for pre-built stock background
# plates. Closed because an LLM emitting an unknown key degrades to free-text
# image_prompt generation (parse_location_key), the existing safe behavior.
LocationKey = Literal[
    "containment-chamber",   # primary SCP holding cell — cold, concrete, reinforced
    "observation-room",      # scientists viewing through reinforced glass/monitors
    "corridor",               # facility hallway — dim utilitarian, pipes/conduits
    "interview-room",         # interrogation/interview — table, two chairs, bare walls
    "autopsy-room",           # medical/autopsy suite — stainless steel, drain channels
    "control-room",           # monitoring stations, banks of screens, consoles
    "facility-exterior",      # outside the Site — brutalist architecture, fences, night
    "server-room",            # data center rows, blinking lights, climate control
    "storage-vault",          # high-security artifact storage — lockers, cages, dim
    "medical-bay",            # infirmary/treatment room — bed, IV stands, clinical
    "cafeteria",              # mess hall — empty, fluorescent, unsettlingly normal
    "office",                 # researcher office/desk work
    "maintenance-tunnel",     # below-grade service access — pipes, steam, grates
    "entrance-checkpoint",    # security screening/airlock entry
]
LOCATION_KEYS = get_args(LocationKey)  # single source of truth for prompt template + parser


class CastMember(TypedDict):
    card_key: str          # CharacterModel.scp_id key: entity's scp_id, a STOCK_CAST_KEYS
                            # member, or a derived "<scp_id>-<n>"
    position: CastPosition  # horizontal slot in frame
    depth: CastDepth        # distance plane: drives scale, parallax amplitude, and stacking
    pose: CastPose          # body stance: selects which pose entry of the card library
    pose_hint: NotRequired[str]  # Story 8.4 on-demand key-art pose; advisory, falls back to `pose`
    pose_guide_key: NotRequired[str]  # Story 8.20 structural guide for the hint, from the closed
                                      # domain.pose.POSE_GUIDE_KEYS catalog. Absent == reference-only
                                      # editing. Never inferred from `pose_hint` — the hint stays the
                                      # action instruction, this names the geometry source.
    motion_style: NotRequired[CharacterMotionStyle]  # Story 8.8; absent == parser/resolver default "breath"
    motion_energy: NotRequired[CharacterMotionEnergy]  # Story 8.8; absent == parser/resolver default "medium"
    movement_mode: NotRequired[CharacterMovementMode]  # Story 8.9; absent == parser/resolver default "anchored"
    movement_direction: NotRequired[CharacterMovementDirection]  # Story 8.9; absent == default "none"
    movement_pace: NotRequired[CharacterMovementPace]  # Story 8.9; absent == default "slow"
    ground_y: NotRequired[float]  # Story 8.16; fraction of FRAME height the feet stand on.
                                  # Written only by inject_ground_resolver; absent == the
                                  # pre-8.16 centre anchor. Read by video.py's overlay AND
                                  # build_contact_shadow — one value, two consumers.
    occlusion_mask: NotRequired[str]  # Story 8.16; gray mask at the sprite's own pixel size,
                                      # multiplied into its alpha. Absent == nothing in front.


class WordTiming(TypedDict):
    word: str
    start_sec: float
    end_sec: float


# Story 11.2: closed camera-motion vocabulary for ShotData.camera_movement.
# Lives here because scenario_chain (producer) and video (consumer) both
# already import domain.state and never each other — same placement logic as
# MOOD_VALUES living in sound_design.
CAMERA_ARCHETYPES = ("push_in", "pull_back", "drift", "locked", "shake")


class ShotData(TypedDict):
    shot_id: str
    sentence_indices: list[int]  # 0-based narration sentence indices; the image-gen unit [AD-5]
    image_prompt: str
    negative_prompt: str
    camera_angle: str | None
    camera_movement: str | None  # one of CAMERA_ARCHETYPES (Story 11.2) | legacy free-text hint | None
    image_path: str | None       # background-only render (Story 8.3); character overlays live in `cast`
    depth_map_path: NotRequired[str | None]  # Story 11.5: monocular depth companion of THIS
                                  # shot's image_path, resolved once in the image stage and
                                  # consumed by the video stage's 2.5D parallax renderer.
                                  # NotRequired so pre-11.5 checkpoints still deserialize;
                                  # absent/None == no depth, renderer falls back (AC9).
    cast: list[CastMember]       # [] == background-only shot: downstream does NO overlay work at all
    location_key: LocationKey | None  # Story 8.5: STOCK plate to copy instead of generating.
                                       # None == use image_prompt (existing generation behavior).


class SceneState(TypedDict):
    scene_num: int
    narration: str
    shots: list[ShotData]
    audio_path: str | None
    audio_duration: float | None
    word_timings: list[WordTiming]
    subtitle_path: str | None
    mood: str  # one of sound_design.MOOD_VALUES; drives BGM/ambient/stinger selection
    title: str  # chapter-card title for this scene; "" = card falls back to "- N -" (Story 5.17)
    kicker: str  # chapter-card one-line context below the title; "" = no kicker line (Story 5.17)
    display_narration: str  # pre-normalization original writing text; subtitles render this, TTS speaks `narration` (Story 5.18)


class SearchResult(TypedDict):
    """A single image search result from a provider (e.g. DuckDuckGo)."""
    url: str
    thumbnail_url: str
    title: str


class ReferenceImage(TypedDict):
    """A downloaded reference image record — persisted in DB, used in UI."""
    id: str
    character_id: str
    url: str
    local_path: str
    width: int | None
    height: int | None
    created_at: str


class Character(TypedDict):
    """SCP character definition — long-lived configuration, not per-run state. [AD-2]"""
    id: str
    scp_id: str
    canonical_name: str
    aliases: list[str]
    visual_descriptor: str | None
    style_guide: str | None
    image_prompt_base: str | None
    selected_image_path: str | None
    angle_front_path: str | None
    angle_back_path: str | None
    angle_side_path: str | None
    angle_three_quarter_path: str | None
    created_at: str
    updated_at: str


class CharacterCandidate(TypedDict):
    """A generated candidate image for a character angle. [AD-2]"""
    id: str
    character_id: str | None
    scp_id: str
    angle: str  # front, back, side, three_quarter
    candidate_num: int
    status: str  # pending, generating, ready, failed
    image_path: str | None
    created_at: str
    updated_at: str


# ── Story 12.3: scenario quality contract carried to the human gate ───────────
# Every field below is a plain JSON scalar/list/dict so the whole object survives
# a LangGraph checkpoint round-trip AND a `interrupt()` value AND the artifact
# endpoint's JSON encoding. No exceptions, prompt objects, or raw completions.


class RuleCounts(TypedDict):
    """Deterministic, code-derived measurements. Raw counts only — this story
    deliberately defines no failure threshold on them (Story 12.1 owns calibrated
    word budgets)."""
    character_count: int          # non-whitespace code points after NFKC
    sentence_count: int           # split_sentences() result count
    duplicate_sentence_count: int  # occurrences beyond the first, normalized
    repeated_4gram_count: int     # distinct 4-grams occurring >= 3 times


class SceneRuleCounts(RuleCounts):
    scene_num: int


class RepeatedPhrase(TypedDict):
    """Script-wide n-gram repeat evidence — counted across the whole script, so a
    phrase recycled between two scenes shows up (the actual slop signal)."""
    phrase: str
    count: int


class SlopPhraseHit(TypedDict):
    scene_num: int
    phrase: str
    count: int


class RuleMetrics(TypedDict):
    aggregate: RuleCounts          # pooled over every scene: character/sentence counts are
                                   # exactly the per-scene sums, while duplicates and repeated
                                   # n-grams additionally catch phrases recycled BETWEEN scenes
    scenes: list[SceneRuleCounts]
    repeated_ngrams: list[RepeatedPhrase]
    slop_phrase_hits: list[SlopPhraseHit]
    slop_vocabulary_version: int   # bump when the phrase tuple changes, so an old
                                   # checkpoint's hits stay interpretable


class GroundedContradiction(TypedDict):
    """A narration/grounding conflict backed by quoted evidence. Every field is
    required — an unevidenced claim is rejected at parse time (AC4)."""
    scene_num: int
    narration_quote: str
    grounding_source: str   # which grounding artifact conflicts (entity_sheet / frozen_descriptor / scp_text)
    grounding_quote: str
    explanation: str
    correction: str


class ReviewIssue(TypedDict):
    scene_num: int
    type: str
    severity: str
    description: str
    correction: str


class ScenarioWarning(TypedDict):
    code: str      # "unresolved_pass2" — the stable identifier the UI keys on
    message: str   # Korean operator copy


class ScenarioQuality(TypedDict):
    """The scenario stage's final review/critic verdict, kept for the human gate.

    Written once per successful scenario run. ``warning`` is absent for a clean
    result — its presence IS the "approve knowingly" signal (AC2/AC3).
    """
    final_pass_index: int
    retry_scope: str
    review_overall_pass: bool
    critic_verdict: str
    critic_feedback: str
    rule_metrics: RuleMetrics
    grounded_contradictions: list[GroundedContradiction]
    review_issues: list[ReviewIssue]
    warning: NotRequired[ScenarioWarning]


class PipelineState(TypedDict):
    run_id: str
    scp_id: str
    scp_text: str
    scenes: list[SceneState]
    video_path: str | None
    current_stage: StageName
    gate_states: dict[StageName, GateState]
    prompt_variant: PromptVariant | None
    error: str | None
    ending_credit_error: NotRequired[str | None]  # Story 5.20 — absent unless the run attempted the ending credit (cc_attribution=True); presence signals attempted
    scenario_quality: NotRequired[ScenarioQuality | None]  # Story 12.3 — final review/critic
                                   # verdict + deterministic metrics, read by the scenario gate.
                                   # NotRequired so pre-12.3 checkpoints still deserialize;
                                   # None == cleared by a retry/restart (never "clean").
