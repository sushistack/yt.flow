from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import JSON, Column, Field, SQLModel


class Run(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID v4
    scp_id: str
    status: str  # running|awaiting_approval|complete|failed
    current_stage: str | None = None
    gate_states: str | None = None  # JSON blob: {"scenario": "approved", ...}
    prompt_variant: str | None = None
    ab_pair_id: str | None = None
    error: str | None = None
    extra: str | None = None  # JSON blob for reserved extra: dict
    langfuse_trace_url: str | None = None
    started_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


class Character(SQLModel, table=True):
    __tablename__ = "characters"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    scp_id: str = Field(index=True, unique=True)
    canonical_name: str
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    visual_descriptor: str | None = None
    style_guide: str | None = None
    image_prompt_base: str | None = None
    selected_image_path: str | None = None
    angle_front_path: str | None = None
    angle_back_path: str | None = None
    angle_side_path: str | None = None
    angle_three_quarter_path: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


class ReferenceImage(SQLModel, table=True):
    __tablename__ = "reference_images"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    character_id: str = Field(foreign_key="characters.id", ondelete="CASCADE")
    url: str
    local_path: str
    width: int | None = None
    height: int | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


class CharacterCandidate(SQLModel, table=True):
    __tablename__ = "character_candidates"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    character_id: str | None = Field(default=None, foreign_key="characters.id", ondelete="SET NULL")
    scp_id: str = Field(index=True)
    angle: str  # front, back, side, three_quarter
    candidate_num: int = 1
    status: str = "pending"  # pending, generating, ready, failed
    image_path: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    class Config:
        # ponytail: SQLModel doesn't support UniqueConstraint as a field arg;
        # table_args tells SQLAlchemy to create one inline.
        __table_args__ = (
            # Prevent duplicate candidates for same SCP+angle+candidate_num
            {"sqlite_on_conflict_unique": "IGNORE"},
        )
