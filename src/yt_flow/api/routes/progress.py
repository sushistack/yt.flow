from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import EventSourceResponse
from sqlmodel import Session

from yt_flow import db
from yt_flow.db.models import Run

router = APIRouter(prefix="/runs", tags=["progress"])


@router.get("/{run_id}/progress")
async def get_progress(run_id: str, request: Request):
    with Session(db._engine) as session:
        if session.get(Run, run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")
    registry = request.app.state.sse_registry
    return EventSourceResponse(
        registry.subscribe(run_id),
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
