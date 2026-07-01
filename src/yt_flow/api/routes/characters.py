"""Character CRUD + reference search + multi-angle generation API routes.

Story 3.7 — RESTful character management API. Delegates to CharacterService
for all business logic. SSE-free: candidate generation uses simple polling (3s).
"""
import asyncio
import logging
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from yt_flow.db import get_session, get_engine
from yt_flow.db.models import Character as CharacterModel
from yt_flow.db.models import CharacterCandidate as CandidateModel
from yt_flow.db.models import ReferenceImage as ReferenceImageModel
from yt_flow.services.character_service import CharacterService
from yt_flow.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/characters", tags=["characters"])

# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class CharacterCreate(BaseModel):
    scp_id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)


class CharacterUpdate(BaseModel):
    canonical_name: str | None = None
    aliases: list[str] | None = None
    visual_descriptor: str | None = None
    style_guide: str | None = None
    image_prompt_base: str | None = None


class ReferenceImageRead(BaseModel):
    id: str
    character_id: str
    url: str
    local_path: str
    width: int | None = None
    height: int | None = None
    created_at: str


class CandidateRead(BaseModel):
    id: str
    character_id: str | None = None
    scp_id: str
    angle: str
    candidate_num: int
    status: str
    image_path: str | None = None
    created_at: str
    updated_at: str


class CharacterRead(BaseModel):
    id: str
    scp_id: str
    canonical_name: str
    aliases: list[str]
    visual_descriptor: str | None = None
    style_guide: str | None = None
    image_prompt_base: str | None = None
    selected_image_path: str | None = None
    angle_front_path: str | None = None
    angle_back_path: str | None = None
    angle_side_path: str | None = None
    angle_three_quarter_path: str | None = None
    created_at: str
    updated_at: str


class CharacterDetail(BaseModel):
    """Character with nested references + candidates for the detail view."""
    id: str
    scp_id: str
    canonical_name: str
    aliases: list[str]
    visual_descriptor: str | None = None
    style_guide: str | None = None
    image_prompt_base: str | None = None
    selected_image_path: str | None = None
    angle_front_path: str | None = None
    angle_back_path: str | None = None
    angle_side_path: str | None = None
    angle_three_quarter_path: str | None = None
    created_at: str
    updated_at: str
    references: list[ReferenceImageRead]
    candidates: list[CandidateRead]


class CandidateBatchResponse(BaseModel):
    candidates: list[CandidateRead]
    message: str


# ── Route Helpers ─────────────────────────────────────────────────────────────


def _svc(request: Request, session: Session) -> CharacterService:
    """Build CharacterService from request context."""
    return CharacterService(session=session, settings=Settings())


def _workspace_path(request: Request) -> Path:
    """Get the workspace path from app state."""
    return Path(cast(str, request.app.state.workspace_path))


def _character_to_read(model: CharacterModel) -> CharacterRead:
    return CharacterRead.model_validate(model, from_attributes=True)


def _ref_to_read(model: ReferenceImageModel) -> ReferenceImageRead:
    return ReferenceImageRead(
        id=model.id,
        character_id=model.character_id,
        url=model.url,
        local_path=model.local_path,
        width=model.width,
        height=model.height,
        created_at=model.created_at,
    )


def _candidate_to_read(model: CandidateModel) -> CandidateRead:
    return CandidateRead(
        id=model.id,
        character_id=model.character_id,
        scp_id=model.scp_id,
        angle=model.angle,
        candidate_num=model.candidate_num,
        status=model.status,
        image_path=model.image_path,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# ── CRUD Routes ───────────────────────────────────────────────────────────────


@router.post("", status_code=201, response_model=CharacterRead)
def create_character(
    body: CharacterCreate,
    request: Request,
    session: Session = Depends(get_session),
):
    """Create a new character record."""
    svc = _svc(request, session)
    try:
        model = svc.create_character(
            scp_id=body.scp_id,
            canonical_name=body.canonical_name,
            aliases=body.aliases,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _character_to_read(model)


@router.get("", response_model=list[CharacterRead])
def list_characters(
    request: Request,
    session: Session = Depends(get_session),
    scp_id: str | None = None,
):
    """List all characters, optionally filtered by scp_id."""
    svc = _svc(request, session)
    if scp_id:
        models = svc.list_characters(scp_id)
    else:
        models = svc.list_all_characters()
    return [_character_to_read(m) for m in models]


@router.get("/{id}", response_model=CharacterDetail)
def get_character(id: str, request: Request, session: Session = Depends(get_session)):
    """Get character detail with references and candidates."""
    svc = _svc(request, session)
    model = svc.get_character(id)
    if model is None:
        raise HTTPException(status_code=404, detail="Character not found")
    refs = svc.get_reference_images(id)
    candidates = svc.list_candidates(model.scp_id)
    return CharacterDetail(
        **_character_to_read(model).model_dump(),
        references=[_ref_to_read(r) for r in refs],
        candidates=[_candidate_to_read(c) for c in candidates],
    )


@router.patch("/{id}", response_model=CharacterRead)
def update_character(
    id: str,
    body: CharacterUpdate,
    request: Request,
    session: Session = Depends(get_session),
):
    """Partial update of character fields."""
    svc = _svc(request, session)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=422, detail="No fields to update")
    try:
        model = svc.update_character(id, **fields)
    except LookupError:
        raise HTTPException(status_code=404, detail="Character not found")
    return _character_to_read(model)


@router.delete("/{id}", status_code=204)
def delete_character(id: str, request: Request, session: Session = Depends(get_session)):
    """Delete a character and all associated files/references."""
    svc = _svc(request, session)
    try:
        svc.delete_character(id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Character not found")


# ── Reference Image Routes ────────────────────────────────────────────────────


@router.post("/{id}/search-refs", status_code=200)
async def search_references(
    id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Trigger DuckDuckGo image search for character references (AC3).

    Downloads images with SSRF/safety checks. Returns existing references
    if already present (deduplication).
    """
    svc = _svc(request, session)
    model = svc.get_character(id)
    if model is None:
        raise HTTPException(status_code=404, detail="Character not found")

    try:
        refs = await svc.search_references(
            scp_id=model.scp_id,
            workspace_path=_workspace_path(request),
            max_results=10,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Reference search failed for character %s", id)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"references": [_ref_to_read(r) for r in refs], "count": len(refs)}


@router.get("/{id}/references", response_model=list[ReferenceImageRead])
def list_references(id: str, request: Request, session: Session = Depends(get_session)):
    """List reference images for a character."""
    svc = _svc(request, session)
    model = svc.get_character(id)
    if model is None:
        raise HTTPException(status_code=404, detail="Character not found")
    refs = svc.get_reference_images(id)
    return [_ref_to_read(r) for r in refs]


# ── Multi-Angle Generation Routes ─────────────────────────────────────────────


@router.post("/{id}/generate", status_code=202, response_model=CandidateBatchResponse)
async def generate_candidates(
    id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Trigger multi-angle character generation (AC4).

    Creates pending candidates for all 4 angles, then fires async generation
    in a background task with a fresh DB session per operation. Poll
    GET /{id}/candidates for progress (3s interval).
    """
    svc = _svc(request, session)
    model = svc.get_character(id)
    if model is None:
        raise HTTPException(status_code=404, detail="Character not found")

    # Create pending candidate batch
    candidates = svc.create_candidate_batch(model.scp_id)

    # Require at least one reference image for i2i generation
    refs = svc.get_reference_images(id)
    if not refs:
        raise HTTPException(status_code=422, detail="No reference images selected. Run search-refs first.")

    ref_path = refs[0].local_path
    scp_id = model.scp_id
    candidate_ids = [(c.id, c.angle) for c in candidates]
    workspace = _workspace_path(request)

    # Fire-and-forget async generation with per-candidate fresh sessions
    async def _generate_all():
        for candidate_id, angle in candidate_ids:
            # Fresh DB session per angle to avoid cross-task contamination
            with Session(get_engine()) as task_session:
                try:
                    svc_gen = CharacterService(session=task_session, settings=Settings())
                    svc_gen.update_candidate_status(candidate_id, "generating")

                    # Generate directly in the async context
                    saved_paths = await svc_gen.generate_candidates_from_reference(
                        scp_id=scp_id,
                        ref_image_path=ref_path,
                        angles=[angle],
                    )
                    if saved_paths:
                        svc_gen.update_candidate_status(candidate_id, "ready", image_path=saved_paths[0])
                    else:
                        svc_gen.update_candidate_status(candidate_id, "failed", image_path=None)
                except Exception as exc:
                    logger.exception("Candidate generation failed for %s angle=%s", id, angle)
                    try:
                        with Session(get_engine()) as fail_session:
                            svc_fail = CharacterService(session=fail_session, settings=Settings())
                            svc_fail.update_candidate_status(candidate_id, "failed")
                    except Exception:
                        pass

    asyncio.create_task(_generate_all())

    return CandidateBatchResponse(
        candidates=[_candidate_to_read(c) for c in candidates],
        message="Generation started for 4 angles. Poll GET /api/characters/{id}/candidates for status.",
    )


@router.get("/{id}/candidates", response_model=list[CandidateRead])
def list_candidates(
    id: str,
    request: Request,
    session: Session = Depends(get_session),
    angle: str | None = None,
):
    """List candidates with current status (for polling, AC4)."""
    svc = _svc(request, session)
    model = svc.get_character(id)
    if model is None:
        raise HTTPException(status_code=404, detail="Character not found")
    candidates = svc.list_candidates(model.scp_id, angle=angle)
    return [_candidate_to_read(c) for c in candidates]


class SelectCandidateBody(BaseModel):
    candidate_num: int = Field(ge=1)
    angle: str


@router.post("/{id}/select", status_code=200, response_model=CharacterRead)
def select_candidate(
    id: str,
    body: SelectCandidateBody,
    request: Request,
    session: Session = Depends(get_session),
):
    """Select a generated candidate for a specific angle (AC5).

    Sets the character's ``angle_{angle}_path`` to the candidate's image path.
    For the front angle, also sets ``selected_image_path`` as the preview.
    Creates a character record if none exists (memorization).
    """
    svc = _svc(request, session)
    model = svc.get_character(id)
    if model is None:
        raise HTTPException(status_code=404, detail="Character not found")
    try:
        updated = svc.select_candidate(scp_id=model.scp_id, candidate_num=body.candidate_num, angle=body.angle)
    except (LookupError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _character_to_read(updated)


@router.post("/{id}/finalize", status_code=200, response_model=CharacterDetail)
def finalize_character(
    id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Finalize character after all 4 angles have selected candidates (AC6).

    Validates that all four angle paths are populated.
    """
    svc = _svc(request, session)
    try:
        finalized = svc.finalize_character(id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Character not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    refs = svc.get_reference_images(id)
    candidates = svc.list_candidates(finalized.scp_id)
    return CharacterDetail(
        **_character_to_read(finalized).model_dump(),
        references=[_ref_to_read(r) for r in refs],
        candidates=[_candidate_to_read(c) for c in candidates],
    )
