"""Composite harmonization — collage-look resolution ladder (Story 8.7).

Tier 1/2: pure ffmpeg filter-string builders (tint, contact shadow, light
wrap). No I/O, no ComfyUI — import-safe even when tier=0 (video.py only
imports this module behind the tier>=1 check).

Tier 3: IC-Light ComfyUI re-lighting with pre-computed (card_key, location_key)
caching. ``asset_service``/``comfyui_client`` are accepted as duck-typed
``Any`` parameters rather than imported concretely — this module stays
domain/config-only (no db/, api/, services/) per AD-1; the real instances are
built and injected by the services layer via video.py's
``inject_relight_resolver`` seam (same pattern as Story 8.3's cast resolver
and Story 8.5's location service).

Layer rule: domain and config only; no db/, api/, services/. [AD-1]
"""

import asyncio
import copy
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from yt_flow.domain.png import has_alpha
from yt_flow.domain.state import CastDepth, CastMember, STOCK_CAST_KEYS, SceneState
from yt_flow.pipeline.nodes.sound_design import MOOD_VALUES, resolve_mood

logger = logging.getLogger(__name__)

# ── Mood tint parameters ────────────────────────────────────────────────────
# colorbalance: rs/gs/bs = red/green/blue shadow, rh/gh/bh = highlight.
# Negative = cool shift, positive = warm shift.
MOOD_TINT_PARAMS: dict[str, dict[str, float]] = {
    "dread": {
        "rs": -0.12, "gs": -0.06, "bs": 0.12, "rh": -0.08, "gh": -0.04, "bh": 0.10,
        "saturation": 0.82, "contrast": 1.02,
    },
    "clinical": {
        "rs": -0.05, "gs": 0.00, "bs": 0.05, "rh": -0.03, "gh": -0.01, "bh": 0.04,
        "saturation": 0.90, "contrast": 1.00,
    },
    "escalation": {
        "rs": 0.10, "gs": 0.04, "bs": -0.06, "rh": 0.08, "gh": 0.03, "bh": -0.04,
        "saturation": 1.12, "contrast": 1.04,
    },
    "revelation": {
        "rs": 0.04, "gs": 0.02, "bs": 0.00, "rh": 0.03, "gh": 0.02, "bh": 0.00,
        "saturation": 1.00, "contrast": 1.18,
    },
}
# Enforce lockstep with MOOD_VALUES so a taxonomy change doesn't silently
# produce the wrong tint.
assert set(MOOD_TINT_PARAMS) == set(MOOD_VALUES)

# Depth -> contact-shadow scale: near=large/soft, far=small/crisp. [AC:2]
_SHADOW_DEPTH_SCALES: dict[CastDepth, float] = {"near": 0.95, "mid": 0.75, "far": 0.6}
_SHADOW_BLUR_RADII: dict[CastDepth, int] = {"near": 12, "mid": 9, "far": 6}
# Horizontal offset (fraction of frame width) matching video.py's
# _POSITION_X_FRAC rule-of-thirds anchors, re-expressed as an offset from center.
_SHADOW_POSITION_OFFSETS: dict[str, float] = {"left": -1 / 6, "center": 0.0, "right": 1 / 6}


def build_sprite_tint(mood: str | None) -> str:
    """Return ffmpeg colorbalance filter for mood-driven character tint. [AC:1]"""
    p = MOOD_TINT_PARAMS[resolve_mood(mood)]
    return (
        f"colorbalance=rs={p['rs']}:gs={p['gs']}:bs={p['bs']}:"
        f"rh={p['rh']}:gh={p['gh']}:bh={p['bh']},"
        f"eq=saturation={p['saturation']}:contrast={p['contrast']}"
    )


def build_contact_shadow(cast_member: CastMember) -> str:
    """Return an ffmpeg geq filter for a soft elliptical shadow under one card. [AC:2]

    Renders a dark, semi-transparent ellipse at the bottom-center of the
    frame, shifted per the card's horizontal position and scaled by its depth
    plane. Must be applied to a full-frame (COMP_W x COMP_H) source carrying
    an alpha channel (e.g. a ``color=...,format=rgba`` source) — the caller
    (video.py) overlays the result onto the background before compositing
    the card itself, so the shadow sits underneath.
    """
    depth = cast_member.get("depth", "mid")
    scale = _SHADOW_DEPTH_SCALES.get(depth, _SHADOW_DEPTH_SCALES["mid"])
    blur = _SHADOW_BLUR_RADII.get(depth, _SHADOW_BLUR_RADII["mid"])
    h_offset = _SHADOW_POSITION_OFFSETS.get(cast_member.get("position", "center"), 0.0)
    rx = 0.08 * scale
    ry = 0.03 * scale
    # No `eval=frame` — geq has no such option (X/Y/W/H are per-pixel terms,
    # not time-varying); a static ellipse is exactly what a contact shadow is.
    # h_offset is parenthesized: a negative offset would otherwise produce a
    # bare "- -0.17" double-minus the geq expression parser can't read.
    # `lt(a,b)`, not infix `a<b` — live-verified: ffmpeg's eval parser rejects
    # `<` as an if() condition ("Missing ')' or too many args") but accepts
    # the function form.
    return (
        f"geq=r=0:g=0:b=0:a='if(lt("
        f"(X/W-0.5-({h_offset}))*(X/W-0.5-({h_offset}))/({rx:.4f}*{rx:.4f})"
        f"+(Y/H-0.85)*(Y/H-0.85)/({ry:.4f}*{ry:.4f}),1),64,0)'"
        f",boxblur={blur}:1"
    )


def build_light_wrap(
    bg_label: str,
    char_label: str,
    out_label: str,
    *,
    position: str = "center",
    blur_radius: int = 8,
    intensity: float = 0.15,
) -> str:
    """Return an ffmpeg filter_complex fragment blending background color onto
    a character's edge (light wrap). [AC:5,6]

    Extracts the character's alpha as a mask, edge-detects + box-blurs the
    background at the mask boundary, then overlays that blurred "bleed" back
    onto the character at low opacity. ``bg_label``/``char_label`` are
    existing filter_complex stream labels (without brackets); the fragment
    ends with a new stream at ``[{out_label}]`` carrying the wrapped
    character, ready for the caller's own overlay step.

    Note: labeled parameters (not the hardcoded ``[0:v]``/``[1:v]`` of the
    story's structural sketch) — video.py's real filter graph has N cards at
    dynamic label indices, not a fixed single-character pair. ``blur_radius``/
    ``intensity`` are tuning constants (ponytail: don't add per-shot params
    until a shot actually needs different values — AC:5). ``char_label`` is
    explicitly ``split`` before use: ffmpeg's filtergraph parser rejects a
    labeled pad consumed by two filters without one (live-verified — reusing
    ``[char]`` as both the alpha-extract source and the final overlay base
    raised "Invalid file index 0", the same class of two-consumer hazard
    ``_join_with_fades`` already works around via distinct per-segment labels).

    The background sample is cropped to the same broad left/center/right band
    as the card's placement before it is resized. That keeps the wrap tied to
    the local plate region instead of squeezing the whole scene into every
    sprite edge.

    ``scale2ref`` resizes the edge-detected background to the character's own
    frame size before ``alphamerge`` — live-verified: ``alphamerge`` rejects
    mismatched input dimensions ("Input frame sizes do not match"), and the
    background (full COMP_W x COMP_H) is essentially never the same size as a
    card scaled to its depth-scaled motion-safe box.
    """
    crop_x = {
        "left": "0",
        "center": "iw/3",
        "right": "2*iw/3",
    }.get(position, "iw/3")
    return (
        f"[{char_label}]split=2[{out_label}_c1][{out_label}_c2];"
        f"[{out_label}_c1]alphaextract[{out_label}_mask];"
        f"[{bg_label}]crop=w=iw/3:h=ih:x={crop_x}:y=0,"
        f"edgedetect=low=0.1:high=0.3,boxblur={blur_radius}:1[{out_label}_edge_raw];"
        f"[{out_label}_edge_raw][{out_label}_c2]scale2ref[{out_label}_edge][{out_label}_c2ref];"
        f"[{out_label}_edge][{out_label}_mask]alphamerge,"
        f"colorchannelmixer=aa={intensity}[{out_label}_bleed];"
        f"[{out_label}_c2ref][{out_label}_bleed]overlay=format=auto[{out_label}]"
    )


# ── Tier 3: IC-Light re-lighting with pre-computed caching ─────────────────

CARD_IMAGE_NODE = "1"
BACKGROUND_IMAGE_NODE = "2"

_RELIGHT_CONCURRENCY = 3  # ponytail: fixed cap, matches Story 5.10-era ComfyUI concurrency norms


class RelightCache:
    """assets/relit/{card_key}/{location_key}/epoch_{style_epoch}.png cache. [AC:8]"""

    def __init__(self, assets_path: Path, asset_service: Any) -> None:
        self._assets_path = Path(assets_path)
        self._asset_service = asset_service

    @staticmethod
    def _key(card_key: str, location_key: str) -> str:
        return f"relit/{_safe_cache_part(card_key)}/{_safe_cache_part(location_key)}"

    @staticmethod
    def _relative_path(card_key: str, location_key: str, style_epoch: int) -> str:
        return f"relit/{_safe_cache_part(card_key)}/{_safe_cache_part(location_key)}/epoch_{style_epoch}.png"

    def get_or_compute(self, card_key: str, location_key: str, style_epoch: int) -> Path | None:
        """Cache lookup only, despite the name (Interfaces AC:8) — a hit
        returns the verified path; a miss returns ``None`` so the caller
        triggers ComfyUI generation and calls :meth:`store`.

        A cached entry from a stale ``style_epoch`` counts as a miss — the
        underlying card/plate assets have moved on, so the cached relight no
        longer matches what it was composited against.
        """
        key = self._key(card_key, location_key)
        entry = self._asset_service.get_asset(key)
        if entry is None or entry.get("style_epoch") != style_epoch:
            return None
        if not self._asset_service.verify_asset(key):
            return None
        try:
            path = _asset_path_under_root(self._assets_path, entry.get("path"))
        except ValueError as exc:
            logger.warning("Ignoring cached relight with unsafe path: %s", exc)
            return None
        try:
            if not has_alpha(path.read_bytes()):
                logger.warning("Ignoring cached relight without alpha: %s", path)
                return None
        except OSError as exc:
            logger.warning("Ignoring unreadable cached relight %s: %s", path, exc)
            return None
        return path

    def store(self, card_key: str, location_key: str, style_epoch: int, image_bytes: bytes) -> Path:
        rel_path = self._relative_path(card_key, location_key, style_epoch)
        abs_path = self._assets_path / rel_path
        if not has_alpha(image_bytes):
            raise ValueError("IC-Light relight output is not a valid alpha PNG")
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = abs_path.with_name(f"{abs_path.name}.{uuid.uuid4().hex}.tmp")
        previous_bytes = abs_path.read_bytes() if abs_path.exists() else None
        tmp_path.write_bytes(image_bytes)
        key = self._key(card_key, location_key)
        try:
            tmp_path.replace(abs_path)
            self._asset_service.add_asset(
                key, rel_path,
                source={"type": "iclight_relight", "card_key": card_key, "location_key": location_key},
                style_epoch=style_epoch,
            )
            # Auto-approve: a pipeline-derived asset, same precedent as Story 8.6's
            # auto-generated character cards (no human curation step mid-run).
            self._asset_service.approve_asset(key)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            if previous_bytes is None:
                abs_path.unlink(missing_ok=True)
            else:
                abs_path.write_bytes(previous_bytes)
            raise
        return abs_path


_SAFE_CACHE_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _safe_cache_part(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_CACHE_PART_RE.fullmatch(value):
        raise ValueError(f"unsafe relight cache key component: {value!r}")
    return value


def _asset_path_under_root(root: Path, relative_path: Any) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError(f"invalid relight asset path: {relative_path!r}")
    rel = Path(relative_path)
    if rel.is_absolute():
        raise ValueError(f"relight asset path must be relative: {relative_path!r}")
    base = root.resolve()
    path = (base / rel).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"relight asset path escapes assets root: {relative_path!r}")
    return path


def _verified_asset(asset_service: Any, key: str) -> bool:
    return asset_service.get_asset(key) is not None and asset_service.verify_asset(key)


def _verified_card_asset(asset_service: Any, card: dict) -> bool:
    card_key = card.get("card_key")
    pose = card.get("pose") or "standing"
    angle = card.get("angle") or "front"
    if not all(isinstance(v, str) for v in (card_key, pose, angle)):
        return False
    return _verified_asset(asset_service, f"{card_key}/{pose}_{angle}")


def _verified_location_asset(asset_service: Any, location_key: str) -> bool:
    manifest = asset_service.load_manifest()
    for key, entry in manifest.get("assets", {}).items():
        if entry.get("status") != "approved":
            continue
        if entry.get("location_key") != location_key and not key.startswith(f"{location_key}/"):
            continue
        if asset_service.verify_asset(key):
            return True
    return False


def _load_iclight_workflow(path: str) -> dict:
    """Load and validate the IC-Light API-format workflow's two image inputs.

    Only validates the LoadImage interchange nodes this module writes to —
    the internal IC-Light conditioning graph is opaque here (same posture as
    image.py's ``_load_workflow``, which only validates its own CLIPTextEncode
    interchange nodes).
    """
    try:
        workflow = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot load IC-Light workflow at {path!r}: {exc}") from exc
    if not isinstance(workflow, dict):
        raise ValueError(f"IC-Light workflow at {path!r} is not an API-format object")
    for node_id in (CARD_IMAGE_NODE, BACKGROUND_IMAGE_NODE):
        node = workflow.get(node_id)
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            raise ValueError(f"IC-Light workflow node {node_id!r} must be a LoadImage node")
    if workflow.get("ytflow_verified_iclight") is not True:
        raise ValueError(
            "IC-Light workflow is not marked ytflow_verified_iclight=true; "
            "placeholder workflows are treated as non-fatal cache misses"
        )
    return workflow


def _inject_relight_inputs(template: dict, card_image_name: str, background_image_name: str) -> dict:
    """Deep-copy the workflow with the uploaded image filenames injected."""
    workflow = copy.deepcopy(template)
    workflow[CARD_IMAGE_NODE]["inputs"]["image"] = card_image_name
    workflow[BACKGROUND_IMAGE_NODE]["inputs"]["image"] = background_image_name
    return workflow


async def relight_sprite(
    card_path: Path,
    background_path: Path,
    comfyui_client: Any,
    workflow_path: str,
    comfyui_url: str,
) -> bytes | None:
    """Submit one IC-Light relight job to ComfyUI. Returns PNG bytes or ``None``
    on any failure (workflow load, upload, submission, timeout). [AC:7,11]

    ``comfyui_client`` is the ``yt_flow.services.comfyui_client`` module (or
    anything exposing the same ``upload_image``/``submit_and_fetch`` async
    functions) — accepted as ``Any`` to keep this module out of the services
    layer per AD-1.
    """
    try:
        template = _load_iclight_workflow(workflow_path)
        card_name = await comfyui_client.upload_image(comfyui_url, card_path.read_bytes(), card_path.name)
        bg_name = await comfyui_client.upload_image(comfyui_url, background_path.read_bytes(), background_path.name)
        workflow = _inject_relight_inputs(template, card_name, bg_name)
        return await comfyui_client.submit_and_fetch(comfyui_url, workflow)
    except Exception as exc:  # noqa: BLE001 — AC:11: IC-Light failure is always non-fatal
        logger.warning("IC-Light relight failed for %s over %s: %s", card_path, background_path, exc)
        return None


async def precompute_relights(
    scenes: list[SceneState],
    cast_cards: dict[str, list[dict]],
    asset_service: Any,
    comfyui_client: Any,
    workflow_path: str,
    assets_path: Path,
    comfyui_url: str,
) -> tuple[dict[tuple[str, str], Path], dict[str, int]]:
    """Pre-compute IC-Light relit sprites for every STOCK (card, location) pair
    in this run's shots. Non-fatal per pair (AC:11); returns the successful
    lookup map plus ``{"computed": n, "failed": n}`` counts for tracing.
    [AC:9,11]

    Only STOCK cards (``STOCK_CAST_KEYS``) over STOCK backgrounds (a shot with
    ``location_key`` set) are eligible — entity-specific cards and free-text
    backgrounds are excluded (AC:9: finite combinations is the whole point of
    pre-computing; a free-text background has no stable identity to cache
    against, and IC-Light needs a reference plate, not a prompt).

    Deviation from the story's literal signature
    (``precompute_relights(scenes, asset_service)``): takes ``cast_cards``,
    the already-resolved card paths from video_node's cast resolver, instead
    of re-deriving sprite paths from scratch via AssetService — video_node
    has already done this resolution; duplicating it here would be redundant
    lookup logic for no behavioral benefit.
    """
    cache = RelightCache(assets_path, asset_service)
    style_epoch = asset_service.style_epoch

    pairs: dict[tuple[str, str], tuple[Path, Path]] = {}
    for scene in scenes:
        for shot in scene.get("shots") or []:
            try:
                location_key = shot.get("location_key")
                bg_path = shot.get("image_path")
                if not location_key or not bg_path:
                    continue
                _safe_cache_part(location_key)
                if not _verified_location_asset(asset_service, location_key):
                    continue
                shot_key = f"{scene['scene_num']}:{shot['shot_id']}"
            except ValueError:
                logger.warning("Skipping unsafe relight location key: %r", location_key)
                continue
            except Exception as exc:  # noqa: BLE001 — one malformed shot must not disable Tier 3
                logger.warning("Skipping relight shot %r after metadata error: %s", shot, exc)
                continue
            for card in cast_cards.get(shot_key, []):
                card_key = None
                try:
                    if not isinstance(card, dict):
                        continue
                    card_key = card.get("card_key")
                    card_path = card.get("path")
                    if card_key not in STOCK_CAST_KEYS or not card_path:
                        continue
                    _safe_cache_part(card_key)
                    _safe_cache_part(location_key)
                    if not _verified_card_asset(asset_service, card):
                        continue
                except ValueError:
                    logger.warning("Skipping unsafe relight cache pair: %r/%r", card_key, location_key)
                    continue
                except Exception as exc:  # noqa: BLE001 — one bad card must not disable all relights
                    logger.warning("Skipping relight card %r after metadata error: %s", card, exc)
                    continue
                pairs.setdefault((card_key, location_key), (Path(card_path), Path(bg_path)))

    relit_map: dict[tuple[str, str], Path] = {}
    stats = {"computed": 0, "failed": 0}
    sem = asyncio.Semaphore(_RELIGHT_CONCURRENCY)

    async def _resolve_pair(pair: tuple[str, str], paths: tuple[Path, Path]) -> None:
        card_key, location_key = pair
        try:
            cached = cache.get_or_compute(card_key, location_key, style_epoch)
            if cached is not None:
                relit_map[pair] = cached
                stats["computed"] += 1
                return
            async with sem:
                image_bytes = await relight_sprite(paths[0], paths[1], comfyui_client, workflow_path, comfyui_url)
            if image_bytes is None or not has_alpha(image_bytes):
                stats["failed"] += 1
                return
            relit_map[pair] = cache.store(card_key, location_key, style_epoch, image_bytes)
            stats["computed"] += 1
        except Exception as exc:  # noqa: BLE001 — AC:11: per-pair relight is non-fatal
            logger.warning("IC-Light relight failed for %s/%s: %s", card_key, location_key, exc)
            stats["failed"] += 1

    if pairs:
        await asyncio.gather(*(_resolve_pair(pair, paths) for pair, paths in pairs.items()))
    return relit_map, stats
