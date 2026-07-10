"""image_node — the ComfyUI image-generation stage (Story 1.6).

Consumes ``SceneState.shots`` from ``scenario_node`` and, per shot, submits the
configured ComfyUI workflow with the shot's prompts injected into workflow nodes
``"6"`` (positive) and ``"7"`` (negative), writing each output under
``workspace/{run_id}/images/``. Pure function of state: reads a few fields and
returns only the changed ones (``scenes``, ``current_stage``, and ``error`` on
failure). No DB / SSE writes and no ``interrupt()`` — gate behaviour stays in
``gates.py``. [AD-1, AD-4]

The image-generation unit is a *shot*, not a scene: every shot gets its own
image. [AD-5]

Background-only (Story 8.3): image_node generates entity-free backgrounds
only — segmentation/inpaint and the layered-asset path were retired outright.
Per-shot character overlays are compositor concerns now: ``video_node``
resolves and composites transparent character cards from ``ShotData.cast``
(Story 8.1/8.2/8.3). ``BG_NEGATIVE_SUFFIX`` is the code-side belt to the
prompt-side (8.1) suspenders keeping entities out of the generated image.

Mock mode (``YTFLOW_COMFYUI_MOCK=true``) never instantiates the HTTP client: a
fixture image from ``tests/fixtures/images/`` is materialized into the run
workspace so downstream code sees an identical artifact layout in mock and real
runs.
"""

import asyncio
import copy
import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from yt_flow.observability import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState, ShotData
from yt_flow.services import comfyui_client
from yt_flow.services.comfyui_client import ComfyUIError

logger = logging.getLogger(__name__)

POSITIVE_NODE = "6"
NEGATIVE_NODE = "7"

# ── Location plate resolution injection (Story 8.5) ────────────────────────
# Injected by the service layer to avoid AD-1 violation (LocationService needs
# a DB session). Same pattern as video.py's inject_cast_resolver.
_location_service: Any = None


def inject_location_service(fn: Any) -> None:
    """Inject the approved-plate lookup callable.

    ``fn`` signature: ``async fn(location_key: str) -> list[dict]`` returning
    approved plates for the key ordered by variant, each
    ``{"variant": str, "path": <absolute file path>}``. Empty list = no
    approved plate — image_node falls back to generation.
    """
    global _location_service
    _location_service = fn

# Story 5.14: integrity floor for resume — matches the E2E baseline's deterministic
# image-gate check ("0-byte/placeholder ≤1KB"). ponytail: module constant, no config.
MIN_VALID_IMAGE_BYTES = 1024

# Story 8.3 AC2: code-side entity exclusion — belt to the prompt-side (8.1)
# suspenders. Values proven in the retired layered workflow's inpaint negative.
BG_NEGATIVE_SUFFIX = ", person, people, human, character, creature, figure, silhouette"

# ponytail: mock fixtures live in the test tree per the story contract; a module
# constant keeps the node dependency-free and lets tests monkeypatch the source.
MOCK_FIXTURES_DIR = Path("tests/fixtures/images")


def _settings() -> Settings:
    # ponytail: one seam so unit tests can inject fake settings without a real .env.
    return Settings()


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _load_workflow(path: str) -> dict:
    """Load and validate the API-format workflow, asserting the prompt nodes exist."""
    try:
        workflow = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError subclass
        raise ValueError(f"cannot load ComfyUI workflow at {path!r}: {exc}") from exc
    if not isinstance(workflow, dict):
        raise ValueError(f"ComfyUI workflow at {path!r} is not an API-format object")
    for node_id in (POSITIVE_NODE, NEGATIVE_NODE):
        node = workflow.get(node_id)
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode" \
                or not isinstance(node.get("inputs"), dict):
            raise ValueError(
                f"workflow node {node_id!r} must be a CLIPTextEncode with an 'inputs' dict"
            )
    return workflow


def _effective_negative_prompt(negative_prompt: str) -> str:
    """Negative prompt actually submitted to ComfyUI and pinned in resume sidecars."""
    return negative_prompt + BG_NEGATIVE_SUFFIX


def _inject_prompts(template: dict, image_prompt: str, negative_prompt: str) -> dict:
    """Return a deep copy of the workflow with prompts injected into nodes 6/7.

    Pure: never mutates ``template`` so one loaded workflow can be reused per shot.
    Appends ``BG_NEGATIVE_SUFFIX`` to the negative prompt (AC2) unconditionally —
    background-only is the only path left, so every generation gets it.
    """
    workflow = copy.deepcopy(template)
    workflow[POSITIVE_NODE]["inputs"]["text"] = image_prompt
    workflow[NEGATIVE_NODE]["inputs"]["text"] = _effective_negative_prompt(negative_prompt)
    return workflow


def _mock_source() -> Path:
    """First fixture image to stand in for a real ComfyUI render."""
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        matches = sorted(MOCK_FIXTURES_DIR.glob(pattern))
        if matches:
            return matches[0]
    raise ValueError(f"no fixture images under {MOCK_FIXTURES_DIR} for mock mode")


def _shot_base(scene_num: int, shot: ShotData) -> str:
    return f"scene_{scene_num:03d}_{shot['shot_id']}"


def _sidecar_path(out_dir: Path, scene_num: int, shot: ShotData) -> Path:
    return out_dir / f"{_shot_base(scene_num, shot)}_done.json"


def _write_sidecar(out_dir: Path, scene_num: int, shot: ShotData) -> None:
    """Completion sentinel, written last after the shot's image file.

    Records the prompts so a later retry can tell a stale (post-prompt-edit)
    output from a genuinely complete one. [AC1, AC2]
    """
    _sidecar_path(out_dir, scene_num, shot).write_text(
        json.dumps({
            "image_prompt": shot["image_prompt"],
            "negative_prompt": _effective_negative_prompt(shot["negative_prompt"]),
        }),
        encoding="utf-8",
    )


def _existing_complete_shot(out_dir: Path, scene_num: int, shot: ShotData) -> str | None:
    """Return the existing image path iff a prior attempt fully completed this shot.

    Pure file/sidecar check only (retry re-enters with state paths nulled, so
    disk is the only truth). Any filesystem hiccup (missing/racing file,
    malformed sidecar) is treated as incomplete rather than raised — this check
    runs inside image_node's AD-10 boundary and must never fail a whole run
    over one shot's resume check. [AC1-3]
    """
    try:
        sidecar = json.loads(_sidecar_path(out_dir, scene_num, shot).read_text(encoding="utf-8"))
        if not isinstance(sidecar, dict) \
                or sidecar.get("image_prompt") != shot["image_prompt"] \
                or sidecar.get("negative_prompt") != _effective_negative_prompt(shot["negative_prompt"]):
            return None

        img_dest = out_dir / f"{_shot_base(scene_num, shot)}.png"
        if not (img_dest.is_file() and img_dest.stat().st_size > MIN_VALID_IMAGE_BYTES):
            return None
        return str(img_dest)
    except (OSError, ValueError):
        return None


def _record_trace(
    *,
    comfyui_url,
    workflow_path,
    request_count,
    image_count,
    latency_ms,
    skipped_count=0,
    stock_plate_count=0,
    error=None,
) -> None:
    """Best-effort enrich the current ``image`` span. [AD-10 — tracing is non-fatal]"""
    try:
        get_client().update_current_span(
            metadata={
                "comfyui_url": comfyui_url,
                "workflow_path": workflow_path,
                "comfyui_request_count": request_count,
                "image_count": image_count,
                "skipped_count": skipped_count,
                "stock_plate_count": stock_plate_count,
                "latency_ms": latency_ms,
                **({"error": repr(error)} if error is not None else {}),
            },
        )
    except Exception:  # noqa: BLE001 — a tracing failure must never break the pipeline
        pass


async def _wait_for_comfyui_recovery(
    base_url: str, *, poll_sec: float, timeout_sec: float, shots_done: int, total_shots: int,
) -> None:
    """Bounded wait-and-recheck loop for a mid-batch ComfyUI crash. [AC2-5]

    Called after a health-check or ``submit_and_fetch`` failure past shot 0's
    initial fail-fast check — a crash is a crash regardless of which call
    first notices it. Polls ``check_health`` every ``poll_sec`` until it
    succeeds or ``timeout_sec`` elapses; re-raises the last failure on timeout
    so the stage fails with the existing AD-10 error format. [AC3]
    """
    logger.warning(
        "ComfyUI health check failed after %d/%d shots, waiting for recovery", shots_done, total_shots,
    )
    start = time.monotonic()
    while True:
        try:
            await comfyui_client.check_health(base_url)
        except ComfyUIError:  # still down, keep polling within budget
            if time.monotonic() - start >= timeout_sec:
                logger.warning("ComfyUI did not recover within %ds, failing stage", int(timeout_sec))
                raise
            await asyncio.sleep(poll_sec)
            continue
        logger.info("ComfyUI recovered after %ds, resuming", int(time.monotonic() - start))
        return


def _plate_variant_index(run_id: str, scene_num: int, location_key: str, count: int) -> int:
    """Deterministic per-run variant pick: same run always picks the same variant
    for the same scene (spatial continuity); different runs vary naturally.

    Uses sha256, not the builtin ``hash()`` — CPython salts str hashing per
    process (PYTHONHASHSEED), so ``hash()`` would pick a different variant for
    the same run/scene after a process restart (e.g. a resumed run), breaking
    the continuity guarantee this function exists for.
    """
    digest = hashlib.sha256(f"{run_id}:{scene_num}:{location_key}".encode()).hexdigest()
    return int(digest, 16) % count


@observe(name="image")
async def image_node(state: PipelineState) -> dict:
    run_id = state.get("run_id", "?")
    t0 = time.perf_counter()
    s: Settings | None = None
    request_count = 0
    image_count = 0
    skipped_count = 0
    stock_plate_count = 0
    generated_count = 0  # Story 5.23: drives the periodic mid-batch health re-check
    health_checked = False  # Story 5.14: lazy — never touched at all if every shot resumes
    try:
        s = _settings()  # inside try: a config/env failure surfaces as PipelineState.error too
        out_dir = Path(s.workspace_path) / run_id / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        template = None if s.comfyui_mock else _load_workflow(s.comfyui_workflow_path)
        total_shots = sum(len(scene["shots"]) for scene in state.get("scenes", []))

        async def _recover() -> None:
            # shots_done spans every path (resumed/plate/generated) so the AC5 log
            # reflects true run progress, not just the newly-generated subset.
            await _wait_for_comfyui_recovery(
                s.comfyui_url,
                poll_sec=s.comfyui_crash_recovery_poll_sec,
                timeout_sec=s.comfyui_crash_recovery_timeout_sec,
                shots_done=generated_count + skipped_count + stock_plate_count,
                total_shots=total_shots,
            )

        plate_cache: dict[str, list[dict]] = {}  # one lookup per location_key per run, not per shot
        new_scenes: list[SceneState] = []
        for scene in state.get("scenes", []):
            new_shots: list[ShotData] = []
            for shot in scene["shots"]:
                existing = _existing_complete_shot(out_dir, scene["scene_num"], shot)
                if existing is not None:
                    skipped_count += 1
                    image_count += 1
                    new_shots.append({**shot, "image_path": existing})
                    continue

                location_key = shot.get("location_key")
                if location_key and _location_service is not None:
                    try:
                        if location_key not in plate_cache:
                            plate_cache[location_key] = await _location_service(location_key)
                        plates = plate_cache[location_key]
                        if plates:
                            plate = plates[_plate_variant_index(run_id, scene["scene_num"], location_key, len(plates))]
                            dest = out_dir / f"{_shot_base(scene['scene_num'], shot)}.png"
                            shutil.copyfile(plate["path"], dest)
                            _write_sidecar(out_dir, scene["scene_num"], shot)
                            image_count += 1
                            stock_plate_count += 1
                            logger.info(
                                "shot %s using STOCK plate %s variant %s",
                                shot["shot_id"], location_key, plate["variant"],
                            )
                            new_shots.append({**shot, "image_path": str(dest)})
                            continue
                        logger.warning(
                            "location_key %r has no approved plates, falling back to generation", location_key,
                        )
                    except Exception as exc:  # noqa: BLE001 — AD-10: plate lookup is best-effort, never fails the stage
                        logger.warning(
                            "stock plate resolution failed for %r, falling back to generation: %s", location_key, exc,
                        )

                if not s.comfyui_mock:
                    if not health_checked:
                        await comfyui_client.check_health(s.comfyui_url)
                        health_checked = True
                    elif generated_count and generated_count % s.comfyui_health_poll_every_n_shots == 0:
                        try:
                            await comfyui_client.check_health(s.comfyui_url)
                        except ComfyUIError:  # a NEW mid-batch failure, not the fail-fast first check
                            await _recover()

                dest = out_dir / f"{_shot_base(scene['scene_num'], shot)}.png"
                if s.comfyui_mock:
                    shutil.copyfile(_mock_source(), dest)
                else:
                    if template is None:
                        raise ValueError("workflow must be loaded in real mode")
                    workflow = _inject_prompts(template, shot["image_prompt"], shot["negative_prompt"])
                    try:
                        image_bytes = await comfyui_client.submit_and_fetch(s.comfyui_url, workflow)
                    except ComfyUIError:  # AC4: a submit-time crash reuses the same recovery loop
                        await _recover()
                        image_bytes = await comfyui_client.submit_and_fetch(s.comfyui_url, workflow)
                    dest.write_bytes(image_bytes)
                    request_count += 1
                generated_count += 1
                image_count += 1
                _write_sidecar(out_dir, scene["scene_num"], shot)
                # Copy the shot; set only image_path — never mutate the input state. [AD-4]
                new_shots.append({**shot, "image_path": str(dest)})
            new_scenes.append({**scene, "shots": new_shots})

        if skipped_count > 0:
            logger.info(
                "image stage resume: skipped %d complete shot(s), generated %d",
                skipped_count, image_count - skipped_count,
            )
        _record_trace(
            comfyui_url=s.comfyui_url, workflow_path=s.comfyui_workflow_path,
            request_count=request_count, image_count=image_count,
            skipped_count=skipped_count, stock_plate_count=stock_plate_count, latency_ms=_ms(t0),
        )
        return {"scenes": new_scenes, "current_stage": "image", "error": None}
    except Exception as exc:  # noqa: BLE001 — surfaced as PipelineState.error, never raised past the node
        _record_trace(
            comfyui_url=s.comfyui_url if s else "?",
            workflow_path=s.comfyui_workflow_path if s else "?",
            request_count=request_count, image_count=image_count,
            skipped_count=skipped_count, stock_plate_count=stock_plate_count, latency_ms=_ms(t0), error=exc,
        )
        return {"current_stage": "image", "error": f"stage=image run_id={run_id}: {exc}"}
