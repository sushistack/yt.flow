"""Domain state types — the single shared type substrate for the pipeline.

Pure stdlib typing only. This module MUST NOT import any upper layer
(pipeline, services, db, api); the layered dependency rule is
`api -> services -> (pipeline | db) -> domain`. [AD-1]

These are TypedDicts, not Pydantic models, because LangGraph state is the
source of truth and must stay plain JSON-serializable for checkpointing. [AD-2]
"""

from typing import Literal, TypedDict

StageName = Literal["scenario", "image", "tts", "subtitle", "video"]
GateState = Literal["pending", "approved", "rejected", "n/a"]
PromptVariant = Literal["A", "B"]
AngleName = Literal["front", "back", "side", "three_quarter"]


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


class SceneState(TypedDict):
    scene_num: int
    narration: str
    shots: list[ShotData]
    audio_path: str | None
    audio_duration: float | None
    word_timings: list[WordTiming]
    subtitle_path: str | None


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
