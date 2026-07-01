"""
services/run_service.py — owns DB sync and SSE fan-out (AD-4).
This story: stub that transitions run status without touching LangGraph.
Graph integration wired in Story 2.3.
"""
from datetime import datetime, timezone

from sqlmodel import Session

from yt_flow import db
from yt_flow.db.models import Run


async def start_run(run_id: str, scp_text: str) -> None:  # noqa: ARG001 — scp_text flows into graph in 2.3
    """
    Drives the pipeline for run_id. Stub only in Story 2.1.
    ponytail: no graph.astream() — deferred to Story 2.3; establishes services/ layer contract per AD-4.
    """
    try:
        with Session(db._engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                return
            # ponytail: stub transition running→complete; real graph.astream() loop replaces this in 2.3
            run.status = "complete"
            run.updated_at = datetime.now(tz=timezone.utc).isoformat()
            session.add(run)
            session.commit()
    except Exception as exc:
        with Session(db._engine) as session:
            run = session.get(Run, run_id)
            if run:
                run.status = "failed"
                run.error = str(exc)
                run.updated_at = datetime.now(tz=timezone.utc).isoformat()
                session.add(run)
                session.commit()
