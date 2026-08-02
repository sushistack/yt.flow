"""compositing_service — depth-aware card placement (Story 8.16).

One monocular depth map per background plate, computed once through ComfyUI's
``DepthAnythingV2Preprocessor`` and cached *beside the plate* as
``<plate>.depth.png`` — never per shot, never per card, and in a location Story
11.5's parallax work can reuse. From that map:

* :func:`ground_line` — the fraction of frame height where a card at a given
  (``position``, ``depth``) plants its feet. video_node anchors the overlay's
  bottom edge there and ``composite_harmonization.build_contact_shadow`` draws
  its ellipse at the same value, which is what stops feet and shadow from
  disagreeing by construction (the pre-8.16 defect: a frame-centre overlay
  against a hardcoded ``Y/H=0.85`` shadow).
* :func:`occlusion_mask` — a card-sized gray mask, black where the plate is
  nearer than the card's own depth plane, multiplied into the card's alpha by
  video_node's card chain.

:func:`resolve_placements` is the callable the api layer injects into video_node
via ``inject_ground_resolver`` — pipeline/ never imports services/ (AD-1).

Depth convention: DepthAnything V2 "Relative" emits *brighter = nearer*, so a
higher sample value means closer to camera throughout this module.
"""

import copy
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from yt_flow.config import Settings

logger = logging.getLogger(__name__)

# The workflow's LoadImage interchange node — the only node this module writes
# to (same posture as image.py's ``_load_workflow``: the estimator graph itself
# is opaque here).
DEPTH_IMAGE_NODE = "1"

# Rule-of-thirds horizontal anchors. Deliberately duplicated from video.py's
# ``_POSITION_X_FRAC`` because services/ may not import pipeline/ (AD-1) — the
# same three floats ``composite_harmonization._SHADOW_POSITION_OFFSETS`` already
# re-expresses as offsets.
_X_FRAC: dict[str, float] = {"left": 1 / 3, "center": 0.5, "right": 2 / 3}

# Where each depth plane sits inside the plate's own observed depth spread
# (0.0 = the farthest pixel in frame, 1.0 = the nearest).
# Where in the column's depth range this card's feet sit. `far` was 0.30, which on a real
# plate resolved above the horizon and had to be rescued by the band clamp; 0.45 keeps a
# far card demonstrably behind a mid card without leaving the floor.
_DEPTH_TARGET: dict[str, float] = {"far": 0.45, "mid": 0.65, "near": 0.85}

# Ground line when no depth map is available (estimation off, unavailable or
# failed). ``near`` is exactly the pre-8.16 hardcoded shadow ``Y/H`` — so a
# fallback near card keeps today's shadow position and simply moves its feet
# onto it instead of leaving them at frame centre.
_DEFAULT_GROUND: dict[str, float] = {"far": 0.65, "mid": 0.75, "near": 0.85}

# A ground line outside this band is a depth artifact, not a floor: above the
# low bound the card would stand on the back wall, below the high bound its feet
# leave the frame.
# A floor cannot be above the room's horizon. Measured on a real control-room plate, the
# `far` target reached the band floor at 0.40 and put the character's feet on the back
# wall, mid-air over the desks — the same "floating" defect this story exists to remove,
# just in the other direction. 0.55 is below the horizon of every plate in the library
# (their vanishing points sit between 0.42 and 0.52 of frame height).
_GROUND_BAND = (0.55, 0.98)

# Occluder test: a plate pixel is in front of the card once it is this much
# nearer than the card's plane, in units of the plate's depth spread.
_OCCLUSION_MARGIN = 0.10
# Fewer masked pixels than this inside the card box is depth noise, not an
# object — no mask is written and the overlay stays unchanged.
_MIN_OCCLUDER_FRAC = 0.02

# On-screen card height per depth plane as a fraction of frame height — the
# framing convention video.py's ``_DEPTH_SCALE`` targets (far ≈ wide shot,
# near ≈ close).
# ponytail: only used to place the occlusion mask's crop box. The mask is
# authored at the card's own pixel size, so a few percent of box error shifts
# the occluder edge slightly and costs nothing else; deriving the exact box
# would mean duplicating video.py's motion-safe CHAR_MAX_W/H math into services/.
_CARD_HEIGHT_FRAC: dict[str, float] = {"far": 0.45, "mid": 0.65, "near": 0.82}


# ── Depth map: compute once per plate, cache beside it ───────────────────────


def depth_map_cache_path(background_path: str | Path) -> Path:
    """``assets/locations/<key>/<variant>.png`` -> ``.../<variant>.depth.png``."""
    return Path(background_path).with_suffix(".depth.png")


async def depth_map_file(
    background_path: str | Path,
    settings: Settings,
    *,
    comfyui_client: Any = None,
) -> Path | None:
    """Return the plate's cached depth map, computing it once if absent.

    ``None`` on any failure (mock mode, unreachable ComfyUI, missing estimator
    node/checkpoint, malformed workflow) — the caller then falls back to
    :data:`_DEFAULT_GROUND`, so depth estimation can never fail a run (AD-10).

    ponytail: cached beside the image rather than under a content-hash index.
    A stock plate is a stable file (that's the reuse Story 11.5 wants), and a
    freely generated background is unique to its run by construction, so a hash
    key would add a lookup table that could never hit twice.
    """
    background = Path(background_path)
    cache = depth_map_cache_path(background)
    if cache.exists():
        return cache
    if getattr(settings, "comfyui_mock", False):
        return None
    client = comfyui_client
    if client is None:
        from yt_flow.services import comfyui_client as client
    try:
        template = json.loads(
            Path(settings.depth_comfyui_workflow_path).read_text(encoding="utf-8")
        )
        node = template.get(DEPTH_IMAGE_NODE)
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            raise ValueError(f"depth workflow node {DEPTH_IMAGE_NODE!r} must be a LoadImage node")
        uploaded = await client.upload_image(
            settings.comfyui_url, background.read_bytes(), background.name,
        )
        workflow = copy.deepcopy(template)
        workflow[DEPTH_IMAGE_NODE]["inputs"]["image"] = uploaded
        image_bytes = await client.submit_and_fetch(settings.comfyui_url, workflow)
        # Atomic publish, same idiom as RelightCache.store: a half-written depth
        # map would otherwise be read as a valid cache hit forever.
        tmp = cache.with_name(f"{cache.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(image_bytes)
        tmp.replace(cache)
        return cache
    except Exception as exc:  # noqa: BLE001 — AD-10: estimation failure degrades, never fails
        logger.warning("Depth estimation failed for %s: %s", background, exc)
        return None


def load_depth_map(path: str | Path | None) -> Any:
    """Read a depth map as a 2-D float array (``None`` if absent/unreadable)."""
    if path is None:
        return None
    try:
        import numpy as np
        from PIL import Image

        with Image.open(path) as im:
            return np.asarray(im.convert("L"), dtype=float)
    except Exception as exc:  # noqa: BLE001 — a corrupt cache degrades to the default ground line
        logger.warning("Unreadable depth map %s: %s", path, exc)
        return None


# ── Geometry (pure) ──────────────────────────────────────────────────────────


def ground_line(depth_map: Any, position: str, depth: str) -> float:
    """Fraction of frame height where a (``position``, ``depth``) card's feet land.

    Reads the depth profile of the column band under the card's rule-of-thirds
    anchor, then returns the row where that profile reaches the card's depth
    plane. A floor never gets *farther* as it comes down the frame, so the
    running maximum of the profile is the monotone ground-depth curve; taking
    the crossing row off that curve makes ``far`` strictly higher in frame than
    ``near`` for any plate by construction, instead of hoping a noisy profile
    behaves.

    Falls back to :data:`_DEFAULT_GROUND` when there is no map, or when the
    band carries no depth spread to read a plane out of.

    Known coupling: a foreground object rising through the card's own column
    band *is* the first surface at that depth, so it lifts the ground line and
    the card stands higher, behind it. That is why :func:`occlusion_mask` then
    finds it in front and masks the card there — the two read the same plane.
    """
    fallback = _DEFAULT_GROUND.get(depth, _DEFAULT_GROUND["mid"])
    if depth_map is None:
        return fallback
    import numpy as np

    arr = np.asarray(depth_map, dtype=float)
    if arr.ndim != 2 or arr.shape[0] < 2 or arr.shape[1] < 1:
        return fallback
    h, w = arr.shape
    centre = _X_FRAC.get(position, _X_FRAC["center"]) * w
    half = max(1, w // 12)
    band = arr[:, max(0, int(centre - half)):min(w, int(centre + half) + 1)]
    profile = np.median(band, axis=1)
    low, high = float(profile.min()), float(profile.max())
    if high - low < 1e-6:
        return fallback
    # Accumulate upward from the bottom row, not downward from the top. A floor is the
    # nearest surface at the bottom of the frame and recedes as it goes up, so scanning
    # up is the direction that describes it. Accumulating downward instead let anything
    # bright high in the band — a ceiling pipe, a foreground railing, a desk crossing the
    # frame — saturate the running max for every row beneath it: measured, a near-depth
    # object wider than half the band collapsed far/mid/near to one identical clamped
    # value, which is exactly the depth-independent anchor this story removed.
    # Scan upward from the bottom row, taking a running MINIMUM. The floor is the nearest
    # surface at the bottom of frame and recedes (gets darker) as it rises, so "the
    # nearest the floor has been at or below this row" is non-increasing going up, and
    # the row where it first drops to the target is that depth's ground line.
    #
    # The previous version accumulated a running maximum downward from the top, which let
    # anything bright high in the band — a ceiling pipe, a foreground railing, a desk
    # crossing frame — saturate every row beneath it. Measured: a near-depth object wider
    # than half the band collapsed far/mid/near to one identical clamped value, i.e. the
    # depth-independent anchor this story exists to remove.
    monotone = np.minimum.accumulate(profile[::-1])
    target = low + (high - low) * _DEPTH_TARGET.get(depth, _DEPTH_TARGET["mid"])
    hits = np.nonzero(monotone <= target)[0]
    idx = int(hits[0]) if hits.size else h - 1
    row = (h - 1) - idx
    return min(max(row / (h - 1), _GROUND_BAND[0]), _GROUND_BAND[1])


def card_box(
    depth_shape: tuple[int, int], position: str, ground_y: float, depth: str, aspect: float,
) -> tuple[int, int, int, int]:
    """The card's on-screen rect in depth-map pixel coordinates, bottom edge on
    the ground line. ``aspect`` is the card image's width/height."""
    h, w = depth_shape
    card_h = _CARD_HEIGHT_FRAC.get(depth, _CARD_HEIGHT_FRAC["mid"]) * h
    card_w = max(1.0, card_h * aspect)
    centre = _X_FRAC.get(position, _X_FRAC["center"]) * w
    bottom = ground_y * h
    return (
        int(round(centre - card_w / 2)), int(round(bottom - card_h)),
        int(round(centre + card_w / 2)), int(round(bottom)),
    )


def occlusion_mask(
    depth_map: Any,
    box: tuple[int, int, int, int],
    card_depth: str,
    out_path: str | Path,
    *,
    card_size: tuple[int, int] | None = None,
) -> Path | None:
    """Write a gray alpha mask for whatever the plate puts *in front* of a card.

    Black where the plate is nearer than the card's depth plane, white
    elsewhere; video_node multiplies it into the card's alpha. ``None`` when
    nothing is in front (the common case) so the overlay stays untouched.

    Deviation from the story's ``occlusion_mask(depth_map, card_box, card_depth)``
    signature: a mask is a file, so the caller supplies ``out_path``, and
    ``card_size`` authors the mask at the sprite's own pixel size — that is what
    lets video.py apply it with a plain ``alphamerge`` at the head of the card
    chain, with no ``scale2ref`` dimension matching.
    """
    if depth_map is None:
        return None
    import numpy as np
    from PIL import Image

    arr = np.asarray(depth_map, dtype=float)
    if arr.ndim != 2:
        return None
    h, w = arr.shape
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    low, high = float(arr.min()), float(arr.max())
    if high - low < 1e-6:
        return None
    plane = low + (high - low) * (
        _DEPTH_TARGET.get(card_depth, _DEPTH_TARGET["mid"]) + _OCCLUSION_MARGIN
    )
    occluded = arr[y0:y1, x0:x1] > plane
    # `.all()` guards an inverted/failed estimate: "the whole card is behind
    # everything" means the plane is wrong, not that the card is invisible.
    if occluded.mean() < _MIN_OCCLUDER_FRAC or occluded.all():
        return None
    image = Image.fromarray(np.where(occluded, 0, 255).astype(np.uint8), "L")
    if card_size:
        image = image.resize(card_size, Image.BILINEAR)  # soft occluder edge
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out


# ── video_node's inject_ground_resolver contract ─────────────────────────────


async def resolve_placements(
    scenes: list,
    cast_cards: dict[str, list[dict]],
    settings: Settings | None = None,
    *,
    comfyui_client: Any = None,
) -> dict[str, list[dict]]:
    """Per shot, one placement dict per card **in the order given**:
    ``{"ground_y": float}`` plus ``"occlusion_mask"`` when the plate has
    something in front of that card. video_node merges these keys into its own
    card dicts, so this can never add, drop or reorder cards.

    One depth map per background path, reused across every shot and card that
    shares it (AC: estimation runs once per plate).
    """
    settings = settings or Settings()  # type: ignore[call-arg]
    placements: dict[str, list[dict]] = {}
    depth_maps: dict[str, Any] = {}
    for scene in scenes:
        for shot in scene.get("shots") or []:
            shot_key = f"{scene['scene_num']}:{shot['shot_id']}"
            cards = cast_cards.get(shot_key) or []
            background = shot.get("image_path")
            if not cards or not background:
                continue
            if background not in depth_maps:
                depth_maps[background] = load_depth_map(
                    await depth_map_file(background, settings, comfyui_client=comfyui_client)
                )
            depth_map = depth_maps[background]
            placements[shot_key] = [
                _place(card, depth_map, background) for card in cards
            ]
    return placements


def _place(card: dict, depth_map: Any, background: str) -> dict:
    position = card.get("position") or "center"
    depth = card.get("depth") or "mid"
    ground_y = ground_line(depth_map, position, depth)
    placement: dict[str, Any] = {"ground_y": round(ground_y, 4)}
    mask = _card_occlusion_mask(card, depth_map, background, position, depth, ground_y)
    if mask is not None:
        placement["occlusion_mask"] = str(mask)
    return placement


def _card_occlusion_mask(
    card: dict, depth_map: Any, background: str, position: str, depth: str, ground_y: float,
) -> Path | None:
    """Write card k's mask beside the background, named for the tuple that
    produced it — (plate, card, position, depth) is a finite set, same reasoning
    as the relight cache, and rewriting it per run means it can never go stale
    against a resized card. Never fatal: no mask is a valid outcome.
    """
    if depth_map is None or not card.get("path"):
        return None
    try:
        from PIL import Image

        with Image.open(card["path"]) as im:
            card_size = im.size  # header read only
        aspect = card_size[0] / max(1, card_size[1])
        stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(card.get("card_key", "card")))
        out = Path(background).with_suffix(f".occ_{stem}_{position}_{depth}.png")
        return occlusion_mask(
            depth_map, card_box(depth_map.shape, position, ground_y, depth, aspect),
            depth, out, card_size=card_size,
        )
    except Exception as exc:  # noqa: BLE001 — AD-10: no mask is always a valid outcome
        logger.warning("Occlusion mask failed for card %r: %s", card.get("card_key"), exc)
        return None
