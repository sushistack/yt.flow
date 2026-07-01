import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from yt_flow import db
from yt_flow.api.routes import progress, runs, scps, stages
from yt_flow.api.routes.scps import ScpEntry  # re-exported for tests/callers
from yt_flow.api.sse import SSEQueueRegistry
from yt_flow.config import Settings
from yt_flow.services import run_service

__all__ = ["app", "ScpEntry"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    app.state.workspace_path = str(Path(settings.workspace_path).resolve())
    app.state.sse_registry = SSEQueueRegistry()
    saver = await run_service.init(settings)  # services builds the graph; api stays off pipeline (AD-1)
    scps_path = Path(__file__).parents[3] / "data" / "scps.json"
    app.state.scps = [ScpEntry(**s) for s in json.loads(scps_path.read_text())]
    try:
        yield
    finally:
        await saver.conn.close()


app = FastAPI(title="yt.flow API", lifespan=lifespan)
app.include_router(runs.router)
app.include_router(progress.router)
app.include_router(scps.router)
app.include_router(stages.router)
