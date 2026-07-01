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

_VALID_STAGES = {"scenario", "image", "tts", "subtitle", "video"}


class RunCreate(BaseModel):
    scp_id: str
    scp_text: str | None = None  # optional: resolved from app.state.scps by scp_id when omitted
    extra: dict | None = None  # reserved, ignored in v1 (FR-24)


class GateAction(BaseModel):
    # ponytail: `action` typed as str (not Literal) so an invalid value yields the exact
    # AC-6 detail message below, not Pydantic's default 422 validation-error list.
    action: str


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
    # Resolve the article text server-side by scp_id when the caller omits it, so the
    # picker only needs to send scp_id (frontend never carries the full text).
    scp_text = body.scp_text
    if scp_text is None:
        scp_text = next(
            (s.scp_text for s in request.app.state.scps if s.id == body.scp_id), None
        )
    if not scp_text:
        raise HTTPException(status_code=422, detail=f"No scp_text available for {body.scp_id}")
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
    run_service.spawn(run_service.start_run(run.id, scp_text, registry))
    return RunRead.model_validate(run, from_attributes=True)


@router.post("/{run_id}/ab", status_code=201, response_model=RunRead)
async def ab_run(run_id: str, request: Request, session: Session = Depends(get_session)):
    """Create Variant B: a second independent run for A/B comparison (FR-27, AD-6)."""
    source = session.get(Run, run_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if source.status != "complete":
        raise HTTPException(status_code=409, detail="Cannot create A/B run: source run is not complete")
    if session.exec(select(Run).where(Run.ab_pair_id == run_id)).first() is not None:
        raise HTTPException(status_code=409, detail="A/B pair already exists for this run")
    registry = getattr(request.app.state, "sse_registry", None)
    new_id = await run_service.create_ab_run(run_id, registry)
    session.expire_all()  # the row was inserted on a separate service session
    return RunRead.model_validate(session.get(Run, new_id), from_attributes=True)


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


@router.post("/{run_id}/stages/{stage}/gate", status_code=202)
async def gate(run_id: str, stage: str, body: GateAction, request: Request,
               session: Session = Depends(get_session)):
    """Approve/reject a paused gate; kicks off the LangGraph resume in the background (AD-4)."""
    if stage not in _VALID_STAGES:
        raise HTTPException(status_code=404, detail=f"Stage '{stage}' not found")
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="action must be 'approve' or 'reject'")
    gate_states = json.loads(run.gate_states) if run.gate_states else {}
    if run.status != "awaiting_approval" or gate_states.get(stage) != "pending":
        raise HTTPException(status_code=409, detail=f"Gate not pending for stage '{stage}'")
    registry = getattr(request.app.state, "sse_registry", None)
    run_service.spawn(run_service.resume_run(run_id, stage, body.action, registry))
    return {"status": "accepted", "run_id": run_id, "stage": stage, "action": body.action}


@router.get("/{run_id}/stages/{stage}/artifacts")
async def get_stage_artifacts(run_id: str, stage: str):
    # ponytail: stage validation + reachability live in the service (AD-4); route just maps errors
    try:
        return await run_service.get_stage_artifacts(run_id, stage)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown stage: {stage}")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


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
