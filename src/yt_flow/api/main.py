import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from starlette.exceptions import HTTPException

from yt_flow import db
from yt_flow.api.routes import characters, progress, runs, scps, stages
from yt_flow.api.routes.scps import ScpEntry  # re-exported for tests/callers
from yt_flow.api.sse import SSEQueueRegistry
from yt_flow.config import Settings
from yt_flow.pipeline.nodes.image import inject_location_service
from yt_flow.pipeline.nodes.video import inject_cast_resolver
from yt_flow.services import run_service
from yt_flow.services.character_service import CharacterService
from yt_flow.services.location_service import LocationService

__all__ = ["app", "ScpEntry"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    app.state.workspace_path = str(Path(settings.workspace_path).resolve())
    app.state.assets_path = str(Path(settings.assets_path).resolve())
    app.state.sse_registry = SSEQueueRegistry()
    saver = await run_service.init(settings)  # services builds the graph; api stays off pipeline (AD-1)

    # Story 8.3: inject cast card resolver into video_node (replaces 1.13's angle selector)
    async def _resolve_cast(scp_id: str, scenes: list) -> dict[str, list[dict]]:
        with Session(db._engine) as session:
            svc = CharacterService(session, settings=settings)
            return await svc.resolve_cast_cards(scp_id, scenes)

    inject_cast_resolver(_resolve_cast)

    # Story 8.5: inject approved-plate lookup into image_node's STOCK fast path
    async def _resolve_location(location_key: str) -> list[dict]:
        with Session(db._engine) as session:
            svc = LocationService(session, settings=settings)
            return [
                {"variant": p.variant, "path": svc._abs_asset_path(p.image_path)}
                for p in svc.get_approved_plates(location_key)
            ]

    inject_location_service(_resolve_location)

    scps_path = Path(__file__).parents[3] / "data" / "scps.json"
    app.state.scps = [ScpEntry(**s) for s in json.loads(scps_path.read_text())]
    try:
        yield
    finally:
        await saver.conn.close()


class SpaStaticFiles(StaticFiles):
    """Serve index.html for client-side routes that match no file (Story 3.8 D4)."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def mount_static_spa(application: FastAPI, dist_dir: Path) -> None:
    """Serve the built React SPA at /app when a build exists (Story 3.1 AC1).

    Mounted under /app only, so API routes elsewhere are never shadowed;
    skipped when frontend/dist is absent so the API runs without a build.
    """
    if dist_dir.is_dir():
        application.mount("/app", SpaStaticFiles(directory=dist_dir, html=True), name="spa")


def mount_workspace_files(application: FastAPI, workspace_dir: Path) -> None:
    """Serve run artifacts (scene images, audio, subtitles, video) at /files (Story 3.4).

    Stage artifacts are stored under workspace/{run_id}/...; the Run Detail UI loads
    them by URL instead of reading the filesystem. StaticFiles blocks path traversal.
    # ponytail: whole-workspace mount is fine for a local single-operator workbench;
    # add per-run auth if this ever serves multiple users.
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)  # may be empty before the first run
    application.mount("/files", StaticFiles(directory=workspace_dir), name="files")


def mount_asset_files(application: FastAPI, assets_dir: Path) -> None:
    """Serve library assets (character cards, location plates) at /asset-files (Story 8.6).

    Card/plate paths are stored relative to assets_path (not workspace_path) — a
    separate mount from /files keeps the two roots (and their cleanup semantics)
    from ever being conflated.
    """
    assets_dir.mkdir(parents=True, exist_ok=True)
    application.mount("/asset-files", StaticFiles(directory=assets_dir), name="asset-files")


app = FastAPI(title="yt.flow API", lifespan=lifespan)
app.include_router(characters.router)
app.include_router(runs.router)
app.include_router(progress.router)
app.include_router(scps.router)
app.include_router(stages.router)
mount_static_spa(app, Path(__file__).parents[3] / "frontend" / "dist")
mount_workspace_files(app, Path(Settings().workspace_path).resolve())
mount_asset_files(app, Path(Settings().assets_path).resolve())
