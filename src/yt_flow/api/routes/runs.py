import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from yt_flow.db import get_session
from yt_flow.db.models import Run
from yt_flow.services import run_service

router = APIRouter(prefix="/runs", tags=["runs"])


class RunCreate(BaseModel):
    scp_id: str
    scp_text: str
    extra: dict | None = None  # reserved, ignored in v1 (FR-24)


class RunRead(BaseModel):
    id: str
    scp_id: str
    status: str
    current_stage: str | None
    gate_states: str | None
    prompt_variant: str | None
    ab_pair_id: str | None
    error: str | None
    extra: str | None
    langfuse_trace_url: str | None
    started_at: str
    updated_at: str


@router.post("", status_code=201, response_model=RunRead)
async def create_run(body: RunCreate, request: Request, session: Session = Depends(get_session)):
    run = Run(
        id=str(uuid.uuid4()),
        scp_id=body.scp_id,
        status="running",
        extra=json.dumps(body.extra) if body.extra else None,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    registry = getattr(request.app.state, "sse_registry", None)
    asyncio.create_task(run_service.start_run(run.id, body.scp_text, registry))
    return RunRead.model_validate(run, from_attributes=True)


@router.get("", response_model=list[RunRead])
def list_runs(session: Session = Depends(get_session)):
    runs = session.exec(select(Run).order_by(Run.started_at.desc())).all()  # type: ignore[attr-defined]
    return [RunRead.model_validate(r, from_attributes=True) for r in runs]


@router.get("/{run_id}", response_model=RunRead)
def get_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunRead.model_validate(run, from_attributes=True)


@router.get("/{run_id}/artifact")
def get_artifact(run_id: str, request: Request, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "complete":
        raise HTTPException(status_code=404, detail="Artifact not available")
    # ponytail: workspace_path stored in app.state at startup to avoid re-constructing Settings
    ws = Path(request.app.state.workspace_path) / run_id / "output.mp4"
    if not ws.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return FileResponse(
        str(ws),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.mp4"'},
    )
