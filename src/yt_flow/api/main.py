import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from yt_flow import db
from yt_flow.api.routes import characters, progress, runs, scps, stages
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


def mount_static_spa(application: FastAPI, dist_dir: Path) -> None:
    """Serve the built React SPA at /app when a build exists (Story 3.1 AC1).

    Mounted under /app only, so API routes elsewhere are never shadowed;
    skipped when frontend/dist is absent so the API runs without a build.
    """
    if dist_dir.is_dir():
        application.mount("/app", StaticFiles(directory=dist_dir, html=True), name="spa")


def mount_workspace_files(application: FastAPI, workspace_dir: Path) -> None:
    """Serve run artifacts (scene images, audio, subtitles, video) at /files (Story 3.4).

    Stage artifacts are stored under workspace/{run_id}/...; the Run Detail UI loads
    them by URL instead of reading the filesystem. StaticFiles blocks path traversal.
    # ponytail: whole-workspace mount is fine for a local single-operator workbench;
    # add per-run auth if this ever serves multiple users.
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)  # may be empty before the first run
    application.mount("/files", StaticFiles(directory=workspace_dir), name="files")


app = FastAPI(title="yt.flow API", lifespan=lifespan)
app.include_router(characters.router)
app.include_router(runs.router)
app.include_router(progress.router)
app.include_router(scps.router)
app.include_router(stages.router)
mount_static_spa(app, Path(__file__).parents[3] / "frontend" / "dist")
mount_workspace_files(app, Path(Settings().workspace_path).resolve())
