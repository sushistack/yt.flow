from datetime import datetime

from sqlmodel import Field, SQLModel


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
    started_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
