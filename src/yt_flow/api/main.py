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
from yt_flow.pipeline.nodes.image import inject_depth_resolver, inject_location_service
from yt_flow.pipeline.nodes.video import (
    inject_cast_resolver,
    inject_ground_resolver,
    inject_motion_renderer,
    inject_relight_resolver,
)
from yt_flow.services import compositing_service, parallax_service, run_service
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
            return svc.resolve_stock_plates(location_key)

    inject_location_service(_resolve_location)

    # Story 11.5: inject the depth-companion resolver into image_node so every
    # shot carries the depth map its 2.5D parallax render needs. Shares Story
    # 8.16's content-addressed cache — one estimation per distinct plate, ever.
    # Gated on the same kill switch as the renderer: off, shots carry no
    # depth_map_path and the video stage keeps its pre-11.5 zoompan behaviour.
    if settings.parallax_25d_enabled:
        async def _resolve_depth(image_path: str) -> dict:
            # [review fix] `cached` asks the SAME strict question depth_map_file
            # asks (verify_depth_pair), not just "is a file there". A map present
            # without a valid sidecar — 8.16's legacy Large-model maps, or a crash
            # between map and sidecar — is a miss that re-runs inference, and
            # reporting it as a hit is precisely the trace lie AC10 forbids.
            import hashlib

            source_sha = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()
            cache = compositing_service.depth_map_cache_path(image_path, settings)
            cached = compositing_service.verify_depth_pair(
                cache, source_sha, compositing_service.depth_contract(settings),
            )
            path = await compositing_service.depth_map_file(image_path, settings)
            return {"path": str(path) if path else None, "cached": cached and path is not None}

        inject_depth_resolver(_resolve_depth)

        # Story 11.5: inject the 2.5D renderer ladder into video_node. Same gate
        # as the depth resolver above — a run must never composite cards against
        # layer ratios for a plate that got no depth companion.
        inject_motion_renderer(
            lambda **kw: parallax_service.render_motion_clip(settings=settings, **kw)
        )

    # Story 8.7 Tier 3: inject IC-Light relight precomputation into video_node
    async def _precompute_relights(scenes: list, cast_cards: dict) -> tuple[dict, dict]:
        with Session(db._engine) as session:
            return await run_service.precompute_relights_for_run(scenes, cast_cards, session, settings)

    inject_relight_resolver(_precompute_relights)

    # Story 8.16: inject depth-aware ground-plane placement into video_node.
    # Gated: off, video.py keeps its pre-8.16 frame-centre anchor byte-for-byte.
    if settings.depth_placement_enabled:
        async def _resolve_grounds(scenes: list, cast_cards: dict) -> dict[str, list[dict]]:
            return await compositing_service.resolve_placements(scenes, cast_cards, settings)

        inject_ground_resolver(_resolve_grounds)

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
