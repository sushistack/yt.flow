"""Domain state types — the single shared type substrate for the pipeline.

Pure stdlib typing only. This module MUST NOT import any upper layer
(pipeline, services, db, api); the layered dependency rule is
`api -> services -> (pipeline | db) -> domain`. [AD-1]

These are TypedDicts, not Pydantic models, because LangGraph state is the
source of truth and must stay plain JSON-serializable for checkpointing. [AD-2]
"""

from typing import Literal, NotRequired, TypedDict

StageName = Literal["scenario", "image", "tts", "subtitle", "video"]
GateState = Literal["pending", "approved", "rejected", "n/a"]
PromptVariant = Literal["A", "B"]
AngleName = Literal["front", "back", "side", "three_quarter"]
CastPosition = Literal["left", "center", "right"]
CastDepth = Literal["near", "mid", "far"]
CastPose = Literal["standing", "sitting"]  # closed v1 vocabulary — free-text special
                                            # poses arrive via Story 8.4's pose_hint field

STOCK_CAST_KEYS = ("STOCK-d-class", "STOCK-researcher", "STOCK-security")  # single source of truth


class CastMember(TypedDict):
    card_key: str          # CharacterModel.scp_id key: entity's scp_id, a STOCK_CAST_KEYS
                            # member, or a derived "<scp_id>-<n>"
    position: CastPosition  # horizontal slot in frame
    depth: CastDepth        # distance plane: drives scale, parallax amplitude, and stacking
    pose: CastPose          # body stance: selects which pose entry of the card library


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
    image_path: str | None       # composed/preview; backward-compatible with 1.9/1.9b
    background_path: str | None  # layered mode: opaque background layer
    character_path: str | None   # layered mode: transparent character PNG; None = background-only
    layered_fallback: bool       # layered mode: True if segmentation errored and this shot degraded to flat
    cast: list[CastMember]       # [] == background-only shot: downstream does NO overlay work at all


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
