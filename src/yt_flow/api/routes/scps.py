"""GET /scps — SCP picker data source (Story 2.5, FR-33).

Serves the in-memory list loaded into ``app.state.scps`` at startup by the
lifespan. No per-request file I/O; filtering/search is done client-side (UX-DR8).
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["scps"])


class ScpEntry(BaseModel):
    id: str
    nickname: str
    object_class: str
    rating: float  # scps.json uses fractional ratings (e.g. 4.8)
    # Full article text. exclude=True keeps the picker list a light summary (UX-DR8)
    # while the attribute stays readable server-side for POST /runs resolution by scp_id.
    scp_text: str | None = Field(default=None, exclude=True)


@router.get("/scps", response_model=list[ScpEntry])
def list_scps(request: Request) -> list[ScpEntry]:
    return request.app.state.scps
