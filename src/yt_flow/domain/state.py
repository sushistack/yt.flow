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
    motion_style: NotRequired[CharacterMotionStyle]  # Story 8.8; absent == parser/resolver default "breath"
    motion_energy: NotRequired[CharacterMotionEnergy]  # Story 8.8; absent == parser/resolver default "medium"
    movement_mode: NotRequired[CharacterMovementMode]  # Story 8.9; absent == parser/resolver default "anchored"
    movement_direction: NotRequired[CharacterMovementDirection]  # Story 8.9; absent == default "none"
    movement_pace: NotRequired[CharacterMovementPace]  # Story 8.9; absent == default "slow"


class WordTiming(TypedDict):
    word: str
    start_sec: float
    end_sec: float


class ShotData(TypedDict):
    shot_id: str
    sentence_indices: list[int]  # 0-based narration sentence indices; the image-gen unit [AD-5]
    image_prompt: str
    negative_prompt: str
    camera_angle: str | None
    camera_movement: str | None
    image_path: str | None       # background-only render (Story 8.3); character overlays live in `cast`
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
