"""Stage control routes — retry a stage or edit its text artifact (Story 2.4).

AD-1/AD-4: routes never call LangGraph directly; they delegate to services/run_service,
which owns all graph.update_state()/astream() and SSE fan-out.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from yt_flow.services import run_service

router = APIRouter(prefix="/runs/{run_id}/stages", tags=["stages"])

_STAGES = ("scenario", "image", "tts", "subtitle", "video")


class ArtifactEditRequest(BaseModel):
    body: str


@router.post("/{stage}/retry", status_code=202)
async def retry_stage(run_id: str, stage: str, request: Request):
    """Re-execute a stage. Stage must be approved, rejected, or failed — not pending."""
    if stage not in _STAGES:
        raise HTTPException(status_code=404, detail="Unknown stage")
    registry = getattr(request.app.state, "sse_registry", None)
    return await run_service.retry_stage(run_id, stage, registry)


@router.patch("/{stage}/artifact")
async def edit_artifact(run_id: str, stage: str, body: ArtifactEditRequest, scene: int = 1):
    """Edit a text artifact (scenario or subtitle only); persists to checkpoint + disk."""
    if stage not in _STAGES:
        raise HTTPException(status_code=404, detail="Unknown stage")
    return await run_service.edit_artifact(run_id, stage, body.body, scene)
