"""
services/run_service.py — owns DB sync and SSE fan-out (AD-4).
This story: stub drives SSE events with synthetic stage progression.
Graph integration wired in Story 2.3.
"""
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlmodel import Session

from yt_flow import db
from yt_flow.db.models import Run

if TYPE_CHECKING:
    from yt_flow.api.sse import SSEQueueRegistry

# ponytail: sse_registry accessed via TYPE_CHECKING import; services/ never imports api/ at runtime (AD-1)
_STAGES = ("scenario", "image", "tts", "subtitle", "video")


async def start_run(run_id: str, scp_text: str, sse_registry: "SSEQueueRegistry | None" = None) -> None:  # noqa: ARG001
    """
    Drives the pipeline for run_id. Stub only in Story 2.1/2.2.
    ponytail: no graph.astream() — deferred to Story 2.3; establishes AD-4 SSE fan-out contract.
    """
    try:
        for stage in _STAGES:
            if sse_registry is not None:
                await sse_registry.publish(run_id, {"event": "stage_entry", "data": {"run_id": run_id, "stage": stage}})
                await sse_registry.publish(run_id, {"event": "stage_exit", "data": {"run_id": run_id, "stage": stage}})
        with Session(db._engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                return
            # ponytail: stub transition running→complete; real graph.astream() loop replaces this in 2.3
            run.status = "complete"
            run.updated_at = datetime.now(tz=timezone.utc).isoformat()
            session.add(run)
            session.commit()
        if sse_registry is not None:
            sse_registry.unsubscribe(run_id)
    except Exception as exc:
        stage = getattr(exc, "_stage", "unknown")
        if sse_registry is not None:
            await sse_registry.publish(run_id, {
                "event": "run_failed",
                "data": {"run_id": run_id, "stage": stage, "error": str(exc)},
            })
        with Session(db._engine) as session:
            run = session.get(Run, run_id)
            if run:
                run.status = "failed"
                run.error = str(exc)
                run.updated_at = datetime.now(tz=timezone.utc).isoformat()
                session.add(run)
                session.commit()
