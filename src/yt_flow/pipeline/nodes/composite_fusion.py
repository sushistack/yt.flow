"""Card/plate fusion — melt the composite into a single generated image.

Jay's direction, 2026-08-08 (anchored in `epics.md`, Epic 10 "확정 방향"): overlaying
a card on a plate is not the deliverable. The composited frame has to become **one
image**, so the card cannot read as something pasted on and cannot drift against the
background.

Two steps, per shot:

1. **Render the composite as a still.** Not re-implemented here — this drives the
   *existing* card chain (`video._build_card_chain`) with a motionless
   ``MotionSource``. Card scale, x anchor, bottom-anchored ``ground_y``, the
   ``_GROUND_Y_MAX`` clamp, edge feather, occlusion-mask alpha multiply, mood tint,
   contact shadow and z-order therefore come from exactly one implementation. A PIL
   re-derivation of that arithmetic was written and thrown away: this repo has already
   been bitten by a framing rule living in two places (`gotcha_one-framing-decision-
   plate-and-derived-map`), and card placement is a far bigger surface than framing.

2. **Fuse it.** A low-denoise img2img pass over the whole still unifies edge quality,
   grain and light so no seam survives at the card boundary. The output replaces the
   shot's plate and the shot renders with **no cards**, so the motion stage animates a
   single image.

The deliberate cost, decided by Jay and recorded in the epic: a fused shot has no
independent card motion — 11.5 layered parallax and 1.9c idle motion are gone for that
shot. That is the point. Grounding can be pixel-perfect and a card that moves against
its background still reads as floating.

Layer rule: domain and config only; no db/, api/, services/. [AD-1] — ``comfyui_client``
is duck-typed, same posture as `composite_harmonization`.
"""

import asyncio
import copy
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from yt_flow.domain.png import dimensions

logger = logging.getLogger(__name__)

# How hard the pass re-draws. The safe band is a property of the MASK, not of the
# researched 0.2-0.3 figure, which assumed an unmasked pass:
#   unmasked  — 0.40 already destroyed the D-class badge and changed the face.
#   masked    — 0.75 left the badge pixel-legible, but re-invented the PLATE into a
#               different room, because all the freedom to re-draw lands there.
# So the ceiling is set by plate survival, not identity. Probed live on S00403
# (2026-08-08): 0.35 too weak to fuse, 0.55 chosen by Jay, 0.75 rejected.
# Evidence: `10-1b-live-validation/fusion-probe/`.
FUSION_DENOISE_MIN = 0.15
FUSION_DENOISE_MAX = 0.70

# Injection points in the fusion workflow, same interchange contract as the
# IC-Light graph: the module writes these node ids and nothing else.
STILL_IMAGE_NODE = "1"
COVERAGE_MASK_NODE = "2"
POSITIVE_PROMPT_NODE = "6"
NEGATIVE_PROMPT_NODE = "7"
SAMPLER_NODE = "3"

_FUSION_CONCURRENCY = 2  # ponytail: fusion is per-shot, not per-card — smaller fan-out than relight


def _load_fusion_workflow(path: str) -> dict:
    """Load and validate the fusion workflow's interchange nodes.

    Mirrors `_load_iclight_workflow`: validate only what this module writes, and
    refuse an unverified graph rather than silently rendering through a placeholder.
    """
    try:
        workflow = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot load fusion workflow at {path!r}: {exc}") from exc
    if not isinstance(workflow, dict):
        raise ValueError(f"fusion workflow at {path!r} is not an API-format object")
    for node_id in (STILL_IMAGE_NODE, COVERAGE_MASK_NODE):
        node = workflow.get(node_id)
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            raise ValueError(f"fusion workflow node {node_id!r} must be a LoadImage node")
    sampler = workflow.get(SAMPLER_NODE)
    if not isinstance(sampler, dict) or "denoise" not in sampler.get("inputs", {}):
        raise ValueError(f"fusion workflow node {SAMPLER_NODE!r} must be a sampler with a denoise input")
    if workflow.get("ytflow_verified_fusion") is not True:
        raise ValueError(
            "fusion workflow is not marked ytflow_verified_fusion=true; "
            "placeholder workflows are treated as non-fatal skips"
        )
    return workflow


def _upload_name(path: Path) -> str:
    """Collision-proof name for ComfyUI's shared input dir.

    ComfyUI keys inputs on the basename and `LoadImage` reads at node-execution
    time, so same-named uploads from concurrent jobs clobber each other. Stills are
    per-shot and could easily share a name across scenes.
    """
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"ytflow_fusion_{digest}{path.suffix or '.png'}"


def _inject_fusion_inputs(
    template: dict,
    still_image_name: str,
    mask_image_name: str,
    denoise: float,
    *,
    prompt: str | None = None,
    size: tuple[int, int] | None = None,
) -> dict:
    """Deep-copy the workflow's nodes with this shot's still and strength injected.

    Only entries carrying a ``class_type`` survive — ComfyUI's ``validate_prompt``
    walks every top-level key and raises on the marker bool (live-verified on the
    IC-Light graph, which returned 500 until the marker was stripped).
    """
    workflow = {k: copy.deepcopy(v) for k, v in template.items() if isinstance(v, dict) and "class_type" in v}
    workflow[STILL_IMAGE_NODE]["inputs"]["image"] = still_image_name
    workflow[COVERAGE_MASK_NODE]["inputs"]["image"] = mask_image_name
    workflow[SAMPLER_NODE]["inputs"]["denoise"] = float(denoise)
    if prompt is not None:
        node = workflow.get(POSITIVE_PROMPT_NODE)
        if isinstance(node, dict) and "text" in node.get("inputs", {}):
            node["inputs"]["text"] = prompt
    if size:
        width, height = size
        for node in workflow.values():
            inputs = node.get("inputs", {})
            if node.get("class_type") in ("EmptyLatentImage", "ImageScale") and {"width", "height"} <= inputs.keys():
                inputs["width"], inputs["height"] = width, height
    return workflow


def fusion_cache_path(workspace: Path, shot_id: str, digest: str) -> Path:
    """Content-addressed: a fused still is a pure function of its inputs.

    Keyed on the still's own bytes plus the fusion parameters, so re-running the
    video stage reuses the fuse, and any change to the plate, the cards, their
    placement, the prompt or the denoise invalidates it. Lives beside the run's
    images rather than in `assets/` — a fused still is per-shot, not a reusable
    library asset (unlike an IC-Light relit sprite, which is card x location).
    """
    return workspace / "fused" / f"{shot_id}_{digest}.png"


def fusion_digest(still_bytes: bytes, denoise: float, prompt: str) -> str:
    h = hashlib.sha256(still_bytes)
    h.update(f"|{denoise:.4f}|{prompt}".encode("utf-8"))
    return h.hexdigest()[:16]


async def fuse_still(
    still_path: Path,
    mask_path: Path,
    comfyui_client: Any,
    workflow_path: str,
    comfyui_url: str,
    *,
    denoise: float,
    prompt: str | None = None,
) -> bytes | None:
    """Submit one composited still for low-denoise fusion. PNG bytes, or ``None``.

    Non-fatal by contract, exactly like `relight_sprite`: a fusion failure must
    leave the run rendering the un-fused composite rather than dying. The caller
    counts the failure and moves on.
    """
    try:
        template = _load_fusion_workflow(workflow_path)
        still_bytes = still_path.read_bytes()
        name = await comfyui_client.upload_image(comfyui_url, still_bytes, _upload_name(still_path))
        mask_name = await comfyui_client.upload_image(
            comfyui_url, mask_path.read_bytes(), _upload_name(mask_path),
        )
        workflow = _inject_fusion_inputs(
            template, name, mask_name, denoise, prompt=prompt, size=dimensions(still_bytes),
        )
        return await comfyui_client.submit_and_fetch(comfyui_url, workflow)
    except Exception as exc:  # noqa: BLE001 — fusion failure is never fatal
        logger.warning("Fusion failed for %s: %s", still_path, exc)
        return None


def clamp_denoise(value: float) -> float:
    """Keep the fusion strength inside the band that actually fuses.

    Below the floor the pass is a no-op and the seam survives; above the ceiling
    the character stops being the approved card. Clamped rather than rejected so a
    bad config value degrades to the nearest useful render instead of killing tier
    fusion for the whole run.
    """
    return min(max(float(value), FUSION_DENOISE_MIN), FUSION_DENOISE_MAX)


async def fuse_shots(
    stills: dict[str, Path],
    masks: dict[str, Path],
    comfyui_client: Any,
    workflow_path: str,
    comfyui_url: str,
    workspace: Path,
    *,
    denoise: float,
    prompts: dict[str, str] | None = None,
) -> tuple[dict[str, Path], dict[str, int]]:
    """Fuse every shot still, cache-first. Returns ``({shot_id: fused_path}, stats)``.

    Concurrency is capped because these are full-frame SDXL passes, one per shot —
    the cost scales with shot count, unlike the relight cache which scales with
    card x location combinations. A shot whose fusion fails is simply absent from
    the map and its caller falls back to the un-fused composite.
    """
    denoise = clamp_denoise(denoise)
    prompts = prompts or {}
    fused: dict[str, Path] = {}
    stats = {"fused": 0, "cached": 0, "failed": 0}
    sem = asyncio.Semaphore(_FUSION_CONCURRENCY)

    async def _one(shot_id: str, still_path: Path) -> None:
        try:
            mask_path = masks.get(shot_id)
            if mask_path is None:
                # No coverage mask means no way to protect the cards; an unmasked
                # pass at this denoise rewrites faces and insignia (probed).
                logger.warning("Fusion skipped for shot %s: no card coverage mask", shot_id)
                stats["failed"] += 1
                return
            prompt = prompts.get(shot_id, "")
            still_bytes = still_path.read_bytes()
            out = fusion_cache_path(
                workspace, shot_id,
                fusion_digest(still_bytes + mask_path.read_bytes(), denoise, prompt),
            )
            # A fused still is an opaque frame, not a sprite — validate it is a
            # readable PNG, not that it carries alpha.
            if out.exists() and dimensions(out.read_bytes()) is not None:
                fused[shot_id] = out
                stats["cached"] += 1
                return
            async with sem:
                image_bytes = await fuse_still(
                    still_path, mask_path, comfyui_client, workflow_path, comfyui_url,
                    denoise=denoise, prompt=prompt or None,
                )
            if not image_bytes:
                stats["failed"] += 1
                return
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(f"{out.name}.tmp")
            tmp.write_bytes(image_bytes)
            tmp.replace(out)
            fused[shot_id] = out
            stats["fused"] += 1
        except Exception as exc:  # noqa: BLE001 — one bad shot must not disable fusion
            logger.warning("Fusion skipped for shot %s: %s", shot_id, exc)
            stats["failed"] += 1

    if stills:
        await asyncio.gather(*(_one(shot_id, path) for shot_id, path in stills.items()))
    return fused, stats
