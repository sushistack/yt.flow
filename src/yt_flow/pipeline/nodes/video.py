"""video_node — FFmpeg composition stage (Story 1.9 + 1.9b).

Story 1.9: per-scene segment render + concat → video.mp4
Story 1.9b: Ken Burns zoompan per shot
Story 1.13: LLM-based character angle pre-selection before FFmpeg composition
Story 5.16: dip-to-black fade + concat scene boundaries (retires xfade/acrossfade)
Story 8.3: N-card cast compositing replaces the single-character overlay —
cast membership/placement comes from ``ShotData.cast`` (Story 8.1), card
assets from Story 8.2's pose-keyed sprite library.

Layer rule: domain and config only; no db/, api/, services/. [AD-1]
"""

import asyncio
import json
import logging
import shutil
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple, get_args

from yt_flow.observability import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.png import has_alpha
from yt_flow.domain.state import CastDepth, PipelineState, SceneState, ShotData
from yt_flow.pipeline.nodes import camera_path, character_motion, character_movement, shot_timing
from yt_flow.pipeline.nodes.color_grade import build_post_filter
from yt_flow.pipeline.nodes.sound_design import (
    AMBIENT_VOLUME,
    MOOD_ASSET_PATHS,
    STINGER_VOLUME,
    build_sound_design_args,
    build_sound_design_filter,
    resolve_mood,
    validate_mood_assets,
)

logger = logging.getLogger(__name__)

# ── Cast resolution injection (Story 1.13, reworked in Story 8.3) ─────────────
# Injected by the service layer to avoid AD-1 violation. video_node calls this
# to resolve every shot's cast into concrete card assets before FFmpeg runs.
_cast_resolver: Any = None


def inject_cast_resolver(fn: Any) -> None:
    """Inject the cast card resolver service callable.

    ``fn`` signature: ``async fn(scp_id: str, scenes: list) -> dict[str, list[dict]]``
    Returns ``{shot_key: [{"card_key","pose","angle","path","fallback",
    "position","depth"}, ...]}`` — a shot with no resolvable cards is absent.
    """
    global _cast_resolver
    _cast_resolver = fn


# ── Tier 3 relight precomputation injection (Story 8.7) ───────────────────────
# Same AD-1-avoidance pattern as inject_cast_resolver — the real implementation
# needs AssetService + comfyui_client (services/), so it's built and injected
# by the api layer, never imported here.
_relight_resolver: Any = None


def inject_relight_resolver(fn: Any) -> None:
    """Inject the Tier-3 IC-Light relight precomputation callable.

    ``fn`` signature:
    ``async fn(scenes: list, cast_cards: dict) -> tuple[dict[tuple[str,str], Path], dict]``
    Returns ``(relit_map, stats)`` — ``stats`` carries ``computed``/``failed``
    counts for tracing (Story 8.7 AC:11).
    """
    global _relight_resolver
    _relight_resolver = fn


# ── Shot recompose injection (Story 10.1c) ────────────────────────────────────
# Same AD-1-avoidance pattern as the resolvers above. This one is different in kind:
# it does not annotate the cards, it REPLACES the shot's plate with a frame that already
# contains the characters, and then removes those cards so nothing is composited on top.
_recompose_resolver: Any = None


def inject_recompose_resolver(fn: Any) -> None:
    """Inject the Story 10.1c shot-recompose callable.

    ``fn`` signature:
    ``async fn(scenes: list, cast_cards: dict) -> tuple[dict, dict]``

    The callable regenerates each cast-bearing shot from its plate, its cards and a
    natural-language placement instruction, writes the result beside the run's images, and
    **rewrites that shot's ``image_path`` in ``scenes``**. It returns ``(cast_cards, stats)``
    where the returned mapping has the recomposed shots' entries **removed** — that is how
    the composition stage learns to take the background-only path for them. A shot the
    callable could not recompose keeps its cards and renders through the old overlay, so a
    partial failure degrades per shot rather than per run.

    ``stats`` carries ``recomposed``/``skipped``/``failed`` counts for tracing.
    """
    global _recompose_resolver
    _recompose_resolver = fn


# ── Depth-aware ground plane injection (Story 8.16) ───────────────────────────
# Same AD-1-avoidance pattern as the two resolvers above: the depth map lives in
# services/compositing_service.py (ComfyUI + PIL/numpy), never imported here.
_ground_resolver: Any = None


# ── 2.5D motion renderer injection (Story 11.5) ───────────────────────────────
# The renderer drives an external runtime, numpy/PIL and ffprobe, so it arrives
# as a callable and video.py stays on domain+config only [AD-1]. None (the kill
# switch off, or no wiring) means the legacy zoompan path.
#
# [review fix] "Byte-identical to pre-11.5" is NOT true and the comment used to
# claim it. The *filtergraph* the legacy branch emits is unchanged, but three
# constants moved for everyone regardless of the switch: _MACRO_PAN_RESERVE_PX
# widened the motion-safe box (CHAR_MAX_W/H, _GROUND_Y_MAX), which moved
# compositing_service._CARD_HEIGHT_FRAC, and _DEFAULT_GROUND was re-measured
# against the Apache-2.0 Small checkpoint AC3 mandates. The kill switch is a
# behavioural rollback of the RENDERER, not a byte-for-byte rollback of output.
_motion_renderer: Any = None


def inject_motion_renderer(fn: Any) -> None:
    """Inject ``parallax_service.render_motion_clip``.

    ``fn`` is keyword-only and returns ``{"path": str | None, "renderer": str,
    "cached": bool, "latency_ms": int, "fallback_reason": str | None}``.
    ``path=None`` is a normal shot-local outcome: :func:`build_motion_source`
    then uses the legacy zoompan chain and records the reason.
    """
    global _motion_renderer
    _motion_renderer = fn


def inject_ground_resolver(fn: Any) -> None:
    """Inject the depth-aware placement resolver. [Story 8.16]

    ``fn`` signature:
    ``async fn(scenes: list, cast_cards: dict[str, list[dict]]) -> dict[str, list[dict]]``
    Returns, per ``shot_key``, one placement dict per card **in the order the
    cards were given** — ``{"ground_y": float}`` plus an optional
    ``"occlusion_mask"`` path. video_node merges those keys into its own card
    dicts (`_merge_placements`), so a resolver can never add, drop or reorder
    cards.

    Not injected (the default) → no card carries ``ground_y`` → `_overlay_filter`
    and `build_contact_shadow` keep their pre-8.16 expressions byte-for-byte.
    """
    global _ground_resolver
    _ground_resolver = fn


# ── Ken Burns constants ───────────────────────────────────────────────────────

FPS = 25
COMP_W = 1920
COMP_H = 1080
ZOOM_IN_MAX = 1.15   # Story 5.3: raised from 1.08 — review found it read as still-image drift
ZOOM_SAFE_MARGIN = 0.10  # 10% inset before crop so zoom/pan never clips subject

# Card edge feather (Story 11.1 AC6): the existing card assets carry a binary
# alpha edge (pre-11.1 hard snap), so the shared card chain softens it at
# composite time — 2-5px per research §3.4. lr/cr zero → alpha plane only,
# color untouched; inline stage, so no split/label-reuse hazard. ar=2 with the
# default double pass gives a ~4px ramp (live-verified). The min() clamp keeps
# boxblur's "radius ≤ min(w,h)/2" constraint satisfiable on degenerate tiny
# cards (a bare ar=2 hard-fails the whole filtergraph on a 1x1 test sprite;
# gblur=planes=8 heap-crashed this ffmpeg build there — don't swap it in).
CARD_EDGE_FEATHER = "boxblur=lr=0:cr=0:ar='min(2,floor(min(w,h)/2))'"

# Direction pool: round-robin by scene_index to avoid identical consecutive directions.
# Story 5.3 added the diagonal directions for more visible fallback variety.
_DIRECTION_POOL = [
    "in-center", "pan-right", "pan-left", "out-center", "pan-up", "pan-down",
    "pan-up-right", "pan-up-left", "pan-down-right", "pan-down-left",
]

# Story 8.11's multi-clip path composes a per-scene effect index as
# `scene_index * _EFFECT_INDEX_STRIDE + local_i`. Prime, so it can never share
# a factor with len(_DIRECTION_POOL) and cancel scene_index out of the
# rotation (a plain 100 did, since the pool has 10 entries).
_EFFECT_INDEX_STRIDE = 97

# Boundary grammar (Story 5.16): dip-to-black fade + concat replaces xfade —
# narration is never trimmed/overlapped, and the dip marks the act break (the
# chapter card where one exists, otherwise a plain black hold). 7.4's
# mood-driven xfade *type* variety is retired outright (Jay-aligned direction,
# 2026-07-06): wipe/white transitions blend two scene images, exactly the
# artifact this grammar removes.
FADE_DURATION = 0.5  # seconds — in-place fade-out/fade-in at each segment's own edges
BLACK_HOLD_DURATION = 0.3  # seconds — dip-to-black hold at card-less act breaks

# ── Chapter-card constants (Story 5.1, content Story 5.17) ─────────────────────
MIN_CARD_DURATION = 1.5
MAX_CARD_DURATION = 2.5  # Story 5.17: raised 2.0->2.5 — cards now carry title+kicker text
CARD_FADE_DURATION = 0.25  # seconds, in/out fade inside the card itself
CARD_FONT_SIZE = 72
CARD_KICKER_FONT_SIZE = 40
CARD_FONT_PATH = Path("data/fonts/Pretendard-Bold.otf")

# Bundled font directory for the subtitle `.ass` burn-in (Story 5.18 AC:6) — passed
# as the ffmpeg `subtitles=` filter's `fontsdir` so libass resolves Fontname from
# this dir first, never depending on system-installed fonts.
SUBTITLE_FONT_DIR = Path("data/fonts")

# ── CC BY-SA attribution constants (Story 5.20) ───────────────────────────────
WIKI_BASE_URL = "https://scp-wiki.wikidot.com"
CC_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/3.0/"
SCP_DATA_PATH = Path("data/scps.json")

# Character idle-motion amplitude/frequency constants (Story 1.9c) now live in
# character_motion.py's motion table (Story 8.8), keyed by style/energy.

# ── Parallax constants (Story 7.3) ────────────────────────────────────────────
# Character (near plane) zoom/pan is derived from the background (far plane)
# EffectSpec, amplified so it reads as depth rather than two unrelated animations.
# ponytail: fixed module constants tuned via live-render QA (same iteration style
# as ZOOM_IN_MAX's 1.08→1.15 history), not per-scene config.
CHAR_DEPTH_FACTOR = 1.3        # zoom-delta amplification for the near plane
CHAR_PAN_AMPLITUDE_PX = 12     # ponytail: eyeball-tuned; per-direction sign live-verified (AC:7/Task 8)

# Peak character zoom = the amplified in-center push-in. The motion-safe box below
# must reserve room for THIS before sway/bob, or the character grows ~19.5% past
# frame edges at the in-center peak (Story 7.3 AC:4).
CHAR_MAX_ZOOM = 1.0 + (ZOOM_IN_MAX - 1.0) * CHAR_DEPTH_FACTOR

# ── Layered character parallax (Story 11.5 AC7) ───────────────────────────────
# On the 2.5D path the plate's own displacement is depth-modulated, so cards must
# be their own layers moving in the SAME apparent direction at a closed,
# server-owned fraction of the plate's excursion — never a number an LLM emits.
# Keyed on the existing `near | mid | far` enum: nearer layers travel further,
# which is the whole depth cue. Values are the AC7 band's endpoints and midpoint.
_LAYER_PARALLAX_RATIO: dict[str, float] = {"far": 0.60, "mid": 0.70, "near": 0.80}
assert set(_LAYER_PARALLAX_RATIO) == set(get_args(CastDepth))  # closed enum, no drift
assert all(0.60 <= r <= 0.80 for r in _LAYER_PARALLAX_RATIO.values())

# Worst-case card excursion the layer parallax can produce: the AC6 displacement
# ceiling times the widest layer ratio. Reserved in the motion-safe box below
# because AC7 requires the FULL combined excursion to be proven on-frame, not
# assumed — 7.3's CHAR_PAN_AMPLITUDE_PX budget (12px) covers only the bottom of
# the 1-3% band, so a near card at 3% would have clipped by ~34px per side.
_LAYER_MAX_PX = camera_path.DISPLACEMENT_MAX * COMP_W * max(_LAYER_PARALLAX_RATIO.values())

# Worst-case excursion across every motion_style/motion_energy combination
# (Story 8.8 AC:7) — read from character_motion's table so this can never
# drift out of sync with the constants that actually drive the filtergraph.
_MAX_MOTION_X_PX, _MAX_MOTION_Y_PX, _MAX_MOTION_SCALE = character_motion.max_excursion()

# Motion-safe character box: shrink an oversized character to leave room for the
# peak parallax zoom *and* the full idle-motion excursion (sway/bob/tremble/
# pulse/glitch, whichever is worst) *and* the macro pan drift, so no combination
# of depth-zoom + idle motion + parallax pan can push it off-frame and a
# mis-sized ComfyUI asset (character bytes are written raw, never scaled
# upstream) can't overflow. Dividing by CHAR_MAX_ZOOM * _MAX_MOTION_SCALE means
# a character capped here then zoomed to its peak *and* pulsed to its peak
# scale lands back inside the frame; reserving the max x/y excursion *and* the
# widest macro-pan budget per side means the worst-case corner still stays on
# screen by construction — not by eyeball (Story 7.3 AC:4/AC:8, Story 8.8 AC:7
# regression invariant).
#
# Story 11.5 AC:7: the reserved macro-pan budget is now the LARGER of 7.3's
# zoompan-path amplitude and the 2.5D layer-parallax ceiling, because a card can
# take either path and the box has to hold for both. That widened the reserve
# 12px -> 46.08px per side, which is why _CARD_HEIGHT_FRAC in
# compositing_service moved too (it is derived from CHAR_MAX_H).
_MACRO_PAN_RESERVE_PX = max(CHAR_PAN_AMPLITUDE_PX, _LAYER_MAX_PX)
CHAR_MAX_W = (COMP_W - 2 * (_MAX_MOTION_X_PX + _MACRO_PAN_RESERVE_PX)) / CHAR_MAX_ZOOM / _MAX_MOTION_SCALE
CHAR_MAX_H = (COMP_H - 2 * (_MAX_MOTION_Y_PX + _MACRO_PAN_RESERVE_PX)) / CHAR_MAX_ZOOM / _MAX_MOTION_SCALE

# ── Multi-card cast compositing (Story 8.3) ───────────────────────────────────
# Stacking order (far painted first, near painted last/on top) — never stored,
# always derived from each cast member's `depth` via a stable sort.
_DEPTH_ORDER: dict[str, int] = {"far": 0, "mid": 1, "near": 2}

# Depth-scaled size cap, multiplied onto CHAR_MAX_W/H (Story 7.3's motion-safe
# box). Tuning target = conventional shot framing: far ≈ wide-shot subject
# (30-50% frame height), mid ≈ medium shot (60-70%), near ≤ ~85% (close) — a
# card must never cover the frame the way the pre-8.3 override did (D13).
# ponytail: live-tuned starting points (Task 6), same iteration style as
# ZOOM_IN_MAX's 1.08→1.15 history — not per-scene config.
_DEPTH_SCALE: dict[str, float] = {"near": 1.0, "mid": 0.75, "far": 0.55}

# Parallax amplitude scale — near planes move more than far planes (Story 7.3
# amplification and CHAR_PAN_AMPLITUDE_PX both scale by this per card).
_DEPTH_PARALLAX: dict[str, float] = {"near": 1.0, "mid": 0.6, "far": 0.3}

# Rule-of-thirds horizontal anchors for cast placement (fraction of main_w).
_POSITION_X_FRAC: dict[str, float] = {"left": 1 / 3, "center": 0.5, "right": 2 / 3}

# Phase offset (rad) per card index so N cards' idle sway/bob never lock step.
# ponytail: eyeball-tuned like CHAR_PAN_AMPLITUDE_PX; not derived from anything.
PHASE_STEP = 2.1


# ── EffectSpec dataclass ──────────────────────────────────────────────────────


@dataclass
class EffectSpec:
    direction: str   # one of _DIRECTION_POOL
    start_zoom: float
    end_zoom: float


# ── Effect dispatcher — pure, no I/O ────────────────────────────────────────


_HINT_MAP: dict[str, str] = {
    "zoom in": "in-center",
    "zoom_in": "in-center",
    "push in": "in-center",
    "push_in": "in-center",
    "zoom out": "out-center",
    "zoom_out": "out-center",
    "pull back": "out-center",
    "pull_back": "out-center",
    "pan left": "pan-left",
    "pan_left": "pan-left",
    "pan right": "pan-right",
    "pan_right": "pan-right",
    "pan up": "pan-up",
    "pan_up": "pan-up",
    "pan down": "pan-down",
    "pan_down": "pan-down",
    # Story 11.3: "shake"'s in-center push is the base move UNDER the real
    # handheld shake — _camera_shake_filter supplies the shake-profile fBm
    # noise on top, so shake and push_in now render distinct final chains.
    "shake": "in-center",
    # "static"/"locked" → near-zero drift; "drift" → pan rotation; handled below
}

# Story 11.2 "drift" archetype: lateral moves only.
_PAN_POOL = [d for d in _DIRECTION_POOL if d.startswith("pan-")]


def select_effect(shot: ShotData, scene_index: int) -> EffectSpec:
    """Pure effect dispatcher. Returns EffectSpec for zoompan. [AC:1,3]

    - Recognizes camera archetypes (Story 11.2) and free-text camera_movement hints.
    - Unknown/None → rotates through _DIRECTION_POOL by scene_index (anti-monotony).
    - 'static'/'locked' → near-zero 1.0→1.005 drift reusing the zoompan path.
    - 'drift' → rotates the pan-* subset by scene_index (8.11 feeds per-shot indices).
    """
    # normalize internal/tab whitespace too so "pan  right" / "pan\tright" still match
    hint = " ".join((shot.get("camera_movement") or "").split()).lower()

    if hint in ("static", "locked"):
        # ponytail: reuse zoompan path instead of a separate static branch
        return EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=1.005)

    if hint == "drift":
        direction = _PAN_POOL[scene_index % len(_PAN_POOL)]
    else:
        direction = _HINT_MAP.get(hint)
    if direction is None:
        # Rotate pool so consecutive scenes never share the same direction
        direction = _DIRECTION_POOL[scene_index % len(_DIRECTION_POOL)]

    # in-center and pan-* zoom in; out-center zooms out
    if direction == "out-center":
        return EffectSpec(direction=direction, start_zoom=ZOOM_IN_MAX, end_zoom=1.0)
    return EffectSpec(direction=direction, start_zoom=1.0, end_zoom=ZOOM_IN_MAX)


def _character_spec(bg_spec: EffectSpec, depth: str = "near") -> EffectSpec:
    """Derive a card's parallax spec from the background spec. [AC:1] [Story 8.3 AC:7]

    Same ``direction`` (parallax needs both planes moving the *same* way, only at
    different magnitude); the zoom deviation from 1.0 is amplified by
    CHAR_DEPTH_FACTOR, itself scaled down by ``_DEPTH_PARALLAX[depth]`` so a
    near card gets the full amplification and a far card tracks closer to the
    background's own zoom (near planes move more than far planes — that's what
    parallax is). Direction-agnostic and no special-casing — 'static'
    (1.0→1.005) stays tiny after amplification.
    """
    depth_amp = _DEPTH_PARALLAX.get(depth, _DEPTH_PARALLAX["mid"])
    factor = 1.0 + (CHAR_DEPTH_FACTOR - 1.0) * depth_amp
    return EffectSpec(
        direction=bg_spec.direction,
        start_zoom=1.0 + (bg_spec.start_zoom - 1.0) * factor,
        end_zoom=1.0 + (bg_spec.end_zoom - 1.0) * factor,
    )


# ── Filtergraph builders ──────────────────────────────────────────────────────


def _zoompan_filter(spec: EffectSpec, duration: float) -> str:
    """Build a jitter-safe zoompan filter chain for one shot. [AC:1]

    Chain: scale→setsar→crop→scale=8000 (jitter fix)→zoompan
    The pre-upscale to 8000px wide is the community-standard pixel-rounding fix.
    """
    frames = max(1, round(duration * FPS))
    safe_w = round(COMP_W * (1 - ZOOM_SAFE_MARGIN))
    safe_h = round(COMP_H * (1 - ZOOM_SAFE_MARGIN))

    # Honor the EffectSpec zoom range so 'static' (1.0→1.005) drifts subtly instead
    # of getting a full push-in. start_zoom/end_zoom were previously ignored — the
    # filter always ran to ZOOM_IN_MAX regardless of spec. [review:G]
    lo, hi = spec.start_zoom, spec.end_zoom
    direction = spec.direction
    if direction == "out-center":
        # zoom-out is stateful: the conditional re-seeds zoom to `lo` on the first
        # frame, then decrements by `inc` toward `hi`.
        inc = (lo - hi) / frames
        z_expr = f"if(lte(zoom,{hi}),{lo},max({hi + 0.001:.6f},zoom-{inc:.6f}))"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        inc = (hi - lo) / frames
        z_expr = f"min(zoom+{inc:.6f},{hi})"
        if direction == "pan-right":
            x_expr = f"(iw-iw/zoom)*on/{frames}"
            y_expr = "ih/2-(ih/zoom/2)"
        elif direction == "pan-left":
            x_expr = f"(iw-iw/zoom)*(1-on/{frames})"
            y_expr = "ih/2-(ih/zoom/2)"
        elif direction == "pan-up":
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = f"(ih-ih/zoom)*on/{frames}"
        elif direction == "pan-down":
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = f"(ih-ih/zoom)*(1-on/{frames})"
        elif direction in {
            "pan-up-right", "pan-up-left", "pan-down-right", "pan-down-left",
        }:
            # Diagonal: combine the horizontal pan-left/right expr with the
            # vertical pan-up/down expr instead of centering the other axis.
            diagonal_exprs = {
                "pan-up-right": (
                    f"(iw-iw/zoom)*on/{frames}",
                    f"(ih-ih/zoom)*on/{frames}",
                ),
                "pan-up-left": (
                    f"(iw-iw/zoom)*(1-on/{frames})",
                    f"(ih-ih/zoom)*on/{frames}",
                ),
                "pan-down-right": (
                    f"(iw-iw/zoom)*on/{frames}",
                    f"(ih-ih/zoom)*(1-on/{frames})",
                ),
                "pan-down-left": (
                    f"(iw-iw/zoom)*(1-on/{frames})",
                    f"(ih-ih/zoom)*(1-on/{frames})",
                ),
            }
            x_expr, y_expr = diagonal_exprs[direction]
        else:  # in-center
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"

    zp = (
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={frames}:s={COMP_W}x{COMP_H}:fps={FPS}"
    )

    return (
        f"scale={safe_w}:-2,setsar=1:1,crop={safe_w}:{safe_h},"
        f"scale=8000:-1,{zp}"
    )


# Direction → (x_sign, y_sign) for the character's macro pan, in *apparent
# on-screen* space: the character drifts WITH the background's visible motion,
# which is the OPPOSITE sign of the background's crop-window expression (see
# _zoompan_filter — a crop moving right makes content appear to move left).
# in-center/out-center/static contribute zero pan (default). Story 7.3 AC:3/AC:7 —
# ponytail: provisional signs, live-verified per direction in Task 8.
_PAN_SIGN: dict[str, tuple[int, int]] = {
    "pan-right": (-1, 0),
    "pan-left": (1, 0),
    "pan-up": (0, -1),
    "pan-down": (0, 1),
    "pan-up-right": (-1, -1),
    "pan-up-left": (1, -1),
    "pan-down-right": (-1, 1),
    "pan-down-left": (1, 1),
}


def _character_zoom_filter(spec: EffectSpec, duration: float) -> str:
    """Time-varying scale for the character (near plane). [AC:2]

    ``scale`` (not ``zoompan``): the character is a transparent PNG composited via
    ``overlay`` and needs no crop, and zoompan's alpha handling is unreliable here.
    ``eval=frame`` so ``t`` advances per frame — the same requirement
    ``_overlay_filter`` documents for its sines. Zoom ramps linearly start→end.
    """
    lo, hi = spec.start_zoom, spec.end_zoom
    z = f"({lo}+({hi}-{lo})*t/{duration})"
    return f"scale=w='iw*{z}':h='ih*{z}':eval=frame"


def ground_y_expr(spec: "EffectSpec", duration: float, ground_y: float) -> str:
    """Where a fixed floor point sits in the OUTPUT frame while zoompan moves the plate.

    The ground line is measured once on the still plate, but the plate is under Ken Burns
    for the whole shot: the crop window zooms and pans, so a floor at 0.80 of plate height
    travels to ~0.845 by the last frame of a centre push-in. Pinning the card's feet to
    the static fraction let feet and shadow stay consistent with each other while both
    drifted off the floor — the "floating" read returning in the second half of every
    moving shot.

    zoompan crops ``ih/zoom`` tall at ``y_top`` and scales it to the output, so a source
    fraction ``p`` lands at ``(p - y_top/ih) * zoom``. This mirrors _zoompan_filter's own
    lo/hi/frames/direction so the two cannot drift apart.
    """
    frames = max(1, round(duration * FPS))
    lo, hi = spec.start_zoom, spec.end_zoom
    d = spec.direction
    # zoompan advances per output frame; overlay only has t, and on == t*FPS.
    if d == "out-center":
        inc = (lo - hi) / frames
        z = f"max({hi + 0.001:.6f},{lo:.6f}-{abs(inc):.6f}*t*{FPS})"
    else:
        inc = (hi - lo) / frames
        z = f"min({lo:.6f}+{inc:.6f}*t*{FPS},{hi:.6f})"
    prog = f"min(t*{FPS}/{frames},1)"
    if d in ("pan-up", "pan-up-right", "pan-up-left"):
        top = f"(1-1/({z}))*{prog}"
    elif d in ("pan-down", "pan-down-right", "pan-down-left"):
        top = f"(1-1/({z}))*(1-{prog})"
    else:  # centre zoom in/out and the purely horizontal pans
        top = f"(1/2-1/(2*({z})))"
    # Same ceiling _apply_placement enforces on the static value, but the animated
    # value can climb past it mid-shot (0.80 reaches 0.845 on a 1.15x push-in), so
    # the clamp has to live inside the expression too or the motion box is violated
    # only on the frames nobody checked.
    return f"main_h*min((({ground_y:g}-({top}))*({z})),{_GROUND_Y_MAX:g})-overlay_h"


# ── 2.5D motion source (Story 11.5 AC4/AC7/AC8) ───────────────────────────────


class TrajectoryExprs(NamedTuple):
    """The numeric trajectory re-expressed as ffmpeg expressions in ``t``.

    One source for both consumers: the CARD layer terms and the card's floor
    tracking. The plate itself is rendered from the *samples* of the same
    trajectory, so parity between plate and cards is by construction, not by two
    implementations agreeing — ``camera_path.sample_path`` and
    ``camera_path.camera_noise_exprs`` are proven identical curves by
    ``test_numeric_sampler_matches_ffmpeg_expressions``.
    """
    x_expr: str      # content x offset, fraction of frame WIDTH
    y_expr: str      # content y offset, fraction of frame WIDTH
    zoom_expr: str   # scale delta from 1.0
    margin: float    # overscan the plate was scaled up by


def _trajectory_exprs(
    hint: str | None, k: int, spec: EffectSpec, duration: float,
    *, trauma: float, xy_peak: float, samples: list,
) -> TrajectoryExprs:
    """Build the expression twin of ``samples`` for the same shot."""
    base_pan = _base_pan(spec)
    gain = camera_path.xy_gain(hint, trauma=trauma, xy_peak=xy_peak, base_pan=base_pan)
    noise = camera_path.camera_noise_exprs(hint, k, trauma=trauma)
    frames = max(1, round(duration * FPS))
    prog = f"min(t*{FPS}/{frames},1)"

    def axis(pan: float, noise_expr: str) -> str:
        terms = [f"({pan:.9g})*{prog}"] if pan else []
        if noise_expr:
            terms.append(f"({noise_expr})")
        return f"({'+'.join(terms)})*{gain:.9g}" if terms else "0"

    z0, z1 = spec.start_zoom, spec.end_zoom
    zoom_terms = [f"({z0:.9g}+({z1 - z0:.9g})*{prog}-1)"]
    if noise is not None and noise.zoom_expr:
        zoom_terms.append(f"({noise.zoom_expr})")
    return TrajectoryExprs(
        x_expr=axis(base_pan[0], noise.x_expr if noise else ""),
        y_expr=axis(base_pan[1], noise.y_expr if noise else ""),
        zoom_expr="+".join(zoom_terms),
        margin=camera_path.sample_overscan_margin(samples),
    )


def _base_pan(spec: EffectSpec) -> tuple[float, float]:
    """The shot's Ken Burns base move as a total content displacement, in frame-
    width fractions — the 2.5D twin of ``_zoompan_filter``'s crop-window walk.

    Signs come from ``_PAN_SIGN``, which is already expressed in *apparent
    on-screen* space (a crop moving right makes content appear to move left), so
    the trajectory, the plate warp and the card layers all share one direction
    convention: positive = content moves right/down. Magnitude reuses the AC6
    displacement ceiling, then ``xy_peak`` rescales the whole trajectory into the
    configured band — the pan is never separately tunable, which is what stops it
    from silently escaping the cap.
    """
    sx, sy = _PAN_SIGN.get(spec.direction, (0, 0))
    amp = camera_path.DISPLACEMENT_MAX
    return sx * amp, sy * amp


@dataclass
class MotionSource:
    """How one shot's background arrives at the composition stage.

    THE seam AC8 asks for: all four render branches (fast/multi-clip x
    card/background-only) build their background from exactly this object, so a
    2.5D clip and a legacy zoompan chain cannot drift into two code paths.

    - legacy: ``bg_input`` loops the still plate, ``bg_chain`` is the zoompan
      chain, ``camera_shake`` carries 11.3's post-composite stage, and 7.3's
      card parallax is on — the same filtergraph pre-11.5 emitted. (Card *size*
      and the ground clamp did move for both paths; see ``_motion_renderer``.)
    - 2.5D: ``bg_input`` reads the pre-rendered clip, ``bg_chain`` is a no-op,
      and ``camera_shake``/``parallax_enabled`` are OFF because the trajectory
      already owns base movement, handheld noise and trauma exactly once (AC7).
    """
    bg_input: list[str]
    bg_chain: str
    spec: EffectSpec
    camera_shake: str = ""
    parallax_enabled: bool = False
    trajectory: TrajectoryExprs | None = None
    renderer: str = "legacy"
    fallback_reason: str | None = None
    latency_ms: int = 0
    cached: bool = False

    @property
    def is_clip(self) -> bool:
        return self.trajectory is not None

    def layer_terms(self, depth: str) -> tuple[str, str] | None:
        """Card ``depth``'s (x, y) offset expressions — AC7's 0.60-0.80 of plate
        displacement, in the same apparent direction, in pixels."""
        if self.trajectory is None:
            return None
        ratio = _LAYER_PARALLAX_RATIO.get(depth, _LAYER_PARALLAX_RATIO["mid"])
        amp = ratio * COMP_W
        return (
            f"({self.trajectory.x_expr})*{amp:.6g}",
            f"({self.trajectory.y_expr})*{amp:.6g}",
        )

    def ground_expr(self, ground_y: float, duration: float) -> str:
        """Where the plate's measured floor sits in the OUTPUT frame, per frame.

        On the legacy path this is Story 8.16's zoompan tracker unchanged. On the
        2.5D path the plate is not zoompanned at all — it is scaled up by
        ``margin`` and then inverse-affine warped — so the floor tracking is
        derived from the trajectory's own zoom instead: a source fraction ``p`` of
        the overscanned plate lands at ``0.5 + (p-0.5)*(1+margin)*(1+zoom)``.

        Only the ZOOM term lives here: the translation is already applied to the
        card by :meth:`layer_terms`, and adding it twice is exactly the
        double-motion AC7 forbids.
        """
        if self.trajectory is None:
            return ground_y_expr(self.spec, duration, ground_y)
        m = 1.0 + self.trajectory.margin
        centred = f"(({ground_y:g}-0.5)*{m:.6g}*(1+({self.trajectory.zoom_expr})))"
        return f"main_h*min(0.5+{centred},{_GROUND_Y_MAX:g})-overlay_h"


def _legacy_motion(
    shot: ShotData, spec: EffectSpec, duration: float,
    *, parallax_enabled: bool, camera_shake: str, fallback_reason: str | None = None,
) -> MotionSource:
    """The pre-11.5 background: the still plate looped under zoompan.

    The final rung of AC9's ladder and the whole behaviour of the AC9 kill
    switch — the same two calls Story 7.3/11.3 made, in the same order, so the
    emitted filtergraph is unchanged. (Not the same *output*: see
    ``_motion_renderer`` for the three constants that moved for both paths.)
    """
    return MotionSource(
        bg_input=["-loop", "1", "-framerate", str(FPS), "-i", str(shot["image_path"])],
        bg_chain=_zoompan_filter(spec, duration),
        spec=spec,
        camera_shake=camera_shake,
        parallax_enabled=parallax_enabled,
        renderer="legacy",
        fallback_reason=fallback_reason,
    )


async def build_motion_source(
    shot: ShotData,
    duration: float,
    *,
    k: int,
    trauma: float,
    motion_dir: Path,
    parallax_enabled: bool,
    camera_shake: str,
    renderer_counts: dict[str, int] | None = None,
) -> MotionSource:
    """Resolve one shot's background motion — the single seam of AC8.

    Tries the injected 2.5D renderer (which runs its own depthflow → depth-warp
    ladder) and falls back to the legacy zoompan chain when it declines or fails.
    Every degradation is logged with run/scene/shot context and counted for the
    trace (AC9): a shot that quietly rendered flat must be visible afterwards.

    Never raises: a renderer problem is shot-local by construction here, and the
    stage only fails if the legacy chain itself fails downstream in ffmpeg (AC9 —
    "only failure of every validated renderer fails the video stage").
    """
    spec = select_effect(shot, k)
    counts = renderer_counts if renderer_counts is not None else {}

    def legacy(reason: str | None) -> MotionSource:
        if reason:
            counts[f"fallback_{reason}"] = counts.get(f"fallback_{reason}", 0) + 1
        counts["legacy"] = counts.get("legacy", 0) + 1
        return _legacy_motion(
            shot, spec, duration, parallax_enabled=parallax_enabled,
            camera_shake=camera_shake, fallback_reason=reason,
        )

    if _motion_renderer is None:
        return legacy(None)  # kill switch / no injection: not a degradation

    settings = _settings()
    xy_peak = camera_path.clamp_displacement(settings.parallax_displacement_frac)
    hint = shot.get("camera_movement")
    samples = camera_path.sample_path(
        hint, k, duration=duration, fps=FPS, trauma=trauma, xy_peak=xy_peak,
        base_zoom=(spec.start_zoom, spec.end_zoom), base_pan=_base_pan(spec),
    )
    try:
        result = await _motion_renderer(
            image_path=shot["image_path"],
            depth_map_path=shot.get("depth_map_path"),
            samples=[tuple(s) for s in samples],
            duration=duration,
            fps=FPS,
            out_path=motion_dir / f"{shot['shot_id']}_k{k}.mp4",
            overscan_margin=camera_path.sample_overscan_margin(samples),
            displacement_frac=xy_peak,
            layer_ratios=_LAYER_PARALLAX_RATIO,
            provenance_extra={
                "archetype": hint or "",
                "k": k,
                "trauma": round(trauma, 6),
                "camera_path_version": camera_path.CAMERA_PATH_VERSION,
            },
        )
    except Exception as exc:  # noqa: BLE001 — AD-10: a renderer fault is shot-local
        logger.warning("2.5D renderer raised for shot %s: %s", shot["shot_id"], exc)
        return legacy("renderer_exception")

    if not result or not result.get("path"):
        reason = (result or {}).get("fallback_reason") or "unknown"
        logger.warning(
            "shot %s fell back to legacy zoompan (%s)", shot["shot_id"], reason,
        )
        return legacy(reason)

    renderer = result["renderer"]
    counts[renderer] = counts.get(renderer, 0) + 1
    counts["latency_ms"] = counts.get("latency_ms", 0) + int(result.get("latency_ms") or 0)
    if result.get("cached"):
        counts["cache_hit"] = counts.get("cache_hit", 0) + 1
    return MotionSource(
        # No `-loop`: the clip already carries exactly the planned frame count,
        # validated by FFprobe before promotion.
        bg_input=["-i", str(result["path"])],
        bg_chain="null",
        spec=spec,
        # Both OFF: the trajectory inside the clip already owns base movement,
        # handheld noise and trauma, and 7.3's card zoom coupling would fight the
        # layer ratios (AC7 — "exactly once").
        camera_shake="",
        parallax_enabled=False,
        trajectory=_trajectory_exprs(
            hint, k, spec, duration, trauma=trauma, xy_peak=xy_peak, samples=samples,
        ),
        renderer=renderer,
        latency_ms=int(result.get("latency_ms") or 0),
        cached=bool(result.get("cached")),
    )


def _overlay_filter(
    position: str = "center", k: int = 0,
    spec: EffectSpec | None = None, duration: float | None = None,
    depth: str = "near",
    motion_style: str = "sway", motion_energy: str = "medium",
    movement_mode: str = "anchored", movement_direction: str = "none",
    movement_pace: str = "slow",
    ground_y: float | None = None,
    ground_y_expression: str | None = None,
    layer_terms: tuple[str, str] | None = None,
) -> str:
    """Card overlay, rule-of-thirds anchored, with phase-decorrelated idle motion.
    [AC:1,2,3] [Story 8.3 AC:6,7] [Story 8.8 AC:6,8] [Story 8.9 AC:5,7]

    ``eval=frame`` is REQUIRED and set explicitly: under the ``eval=init`` default
    for *some* builds the ``t``/``n`` timeline vars collapse to NAN and the
    card freezes. x/y sub-expressions come from ``character_motion.axis_terms``
    (Story 8.8) — the default ``motion_style="sway"``/``motion_energy="medium"``
    reproduces the pre-8.8 two-sine sway/bob string exactly. A ``k*PHASE_STEP``
    offset keeps N simultaneous cards from moving in lockstep, deterministic
    from the shot's own cast ordering (Interfaces: stable across retries/A-B).

    ``position`` anchors the card horizontally at a rule-of-thirds fraction of
    ``main_w`` (1/3, 1/2, or 2/3) instead of dead-centering it — multiple cards
    need to occupy distinct screen positions. Composition order (Story 8.9
    AC:5): 8.3 anchor -> 8.9 movement curve -> 7.3 parallax pan -> 8.8 idle
    motion. ``movement_mode="anchored"`` (the default) contributes nothing, so
    the pre-8.9 string is unchanged when a card has no movement fields. When
    ``spec`` is given (parallax on, Story 7.3), a direction-derived macro pan
    term rides *on top of* movement, its amplitude scaled by
    ``_DEPTH_PARALLAX[depth]``. ``spec=None`` reverts to the fixed-size
    idle-motion-only string (parallax off).

    ``ground_y`` (Story 8.16) is the fraction of frame height the card's feet
    stand on, from the plate's depth map via ``inject_ground_resolver``. The
    card's *bottom edge* lands there — cards are bottom-gutter sprites, so the
    bottom edge is the feet — and ``build_contact_shadow`` draws its ellipse at
    the same fraction, which is what makes feet and shadow agree. ``None`` (no
    resolver injected) keeps the pre-8.16 frame-centre anchor exactly.
    """
    x_frac = _POSITION_X_FRAC.get(position, _POSITION_X_FRAC["center"])
    phase = k * PHASE_STEP
    movement = character_movement.build_movement_terms(
        mode=movement_mode, direction=movement_direction, pace=movement_pace,
        position=position, depth=depth, duration=duration or 0.0,
    )
    x = f"main_w*{x_frac}-overlay_w/2"
    if movement.x_terms:
        x += " + " + " + ".join(movement.x_terms)
    if ground_y_expression is not None:
        # Tracks the plate under Ken Burns; see ground_y_expr.
        y = ground_y_expression
    elif ground_y is not None:
        y = f"main_h*{ground_y:g}-overlay_h"
    else:
        y = "(main_h-overlay_h)/2"
    if movement.y_terms:
        y += " + " + " + ".join(movement.y_terms)
    if layer_terms is not None:
        # Story 11.5 AC:7 — the 2.5D layer term REPLACES 7.3's macro pan in the
        # same composition slot. Both are "this card's share of the plate's
        # apparent movement"; running them together would apply base movement
        # twice, which is the double-motion AC7 exists to forbid.
        x += f" + ({layer_terms[0]})"
        y += f" + ({layer_terms[1]})"
    elif spec is not None and duration:
        sx, sy = _PAN_SIGN.get(spec.direction, (0, 0))
        pan_amp = CHAR_PAN_AMPLITUDE_PX * _DEPTH_PARALLAX.get(depth, _DEPTH_PARALLAX["mid"])
        if sx:
            x += f" + ({sx * pan_amp})*t/{duration}"
        if sy:
            y += f" + ({sy * pan_amp})*t/{duration}"
    x_terms = character_motion.axis_terms(motion_style, motion_energy, "x", phase)
    y_terms = character_motion.axis_terms(motion_style, motion_energy, "y", phase)
    if x_terms:
        x += " + " + " + ".join(x_terms)
    if y_terms:
        y += " + " + " + ".join(y_terms)
    return f"overlay=x='{x}':y='{y}':eval=frame"


def _motion_scale_filter(motion_style: str = "sway", motion_energy: str = "medium", k: int = 0) -> str:
    """Time-varying scale pulse for styles that carry one (breath/sway/tremble's
    tiny breathing pulse, pulse's larger supernatural pulse). [Story 8.8 AC:6]

    Empty string for ``hold``/``glitch`` (no scale term in the table) — the
    caller skips appending a filter stage entirely, so those styles cost
    nothing extra in the chain. Same ``k*PHASE_STEP`` phase as the overlay's
    position sines so a card's breathing and its sway/bob stay in the same
    rhythm.
    """
    terms = character_motion.axis_terms(motion_style, motion_energy, "scale", k * PHASE_STEP)
    if not terms:
        return ""
    expr = " + ".join(terms)
    return f"scale=w='iw*(1+({expr}))':h='ih*(1+({expr}))':eval=frame"


def _camera_shake_filter(hint: str | None, duration: float, *, k: int, trauma: float = 0.0) -> str:
    """Handheld camera stage applied to the fully composited frame (Story 11.3
    AC:2) — the camera shakes bg and cards *together*, so no per-layer math
    changes. Chain: overscan scale (margin M derived by construction from
    camera_path's analytic excursion bound, plus the micro-zoom noise) →
    ``rotate`` on the fBm rotation band → ``crop`` back to COMP_W x COMP_H with
    the x/y noise offsetting the window.

    Empty string when every channel is silent (locked/"static" profile with no
    trauma, or the config kill switch upstream) — the caller then attaches no
    stage at all, keeping the chain byte-identical to pre-11.3
    (``_motion_scale_filter``'s "" idiom). ``k`` is the shot's effect index
    (fast path: scene_index; multi-clip: scene_index*stride+local_i), reused as
    a lattice offset so adjacent shots never ride the same curve.

    ``duration`` is unused today (the trauma envelope decays in absolute t) —
    kept so a future duration-scaled band doesn't ripple every call site.

    ``eval=frame`` on the scale stage is REQUIRED (the eval=init default
    collapses ``t`` to NAN — the trap ``_overlay_filter`` documents); the
    even-dimension floor keeps yuv420p happy mid-chain, its ≤1px/side loss
    already folded into the margin. clip() on crop x/y is belt-and-suspenders
    on top of the analytic margin.
    """
    exprs = camera_path.camera_noise_exprs(hint, k, trauma=trauma)
    if exprs is None:
        return ""
    scale_factor = f"{1.0 + exprs.margin:.6g}"
    if exprs.zoom_expr:
        scale_factor = f"({scale_factor}+{exprs.zoom_expr})"
    parts = [
        f"scale=w='2*floor(iw*{scale_factor}/2)':h='2*floor(ih*{scale_factor}/2)':eval=frame",
    ]
    if exprs.rot_expr:
        parts.append(f"rotate=a='{exprs.rot_expr}'")
    x = f"clip((iw-{COMP_W})/2+({exprs.x_expr or '0'})*{COMP_W},0,iw-{COMP_W})"
    # y noise amplitude is a frame-WIDTH fraction too (profile unit), hence *COMP_W
    y = f"clip((ih-{COMP_H})/2+({exprs.y_expr or '0'})*{COMP_W},0,ih-{COMP_H})"
    parts.append(f"crop={COMP_W}:{COMP_H}:x='{x}':y='{y}'")
    return ",".join(parts)


def _movement_scale_filter(
    mode: str, direction: str, pace: str, position: str, depth: str, duration: float,
) -> str:
    """Time-varying scale for ``approach``/``retreat`` (Story 8.9 AC:5,7). Empty
    string for every other mode — the caller skips appending a filter stage
    entirely, same convention as ``_motion_scale_filter``'s hold/glitch skip.
    Chained right after ``_character_scale_filter``'s depth-cap anchor and
    before parallax/idle-motion scale stages (AC:5 composition order).
    """
    terms = character_movement.build_movement_terms(
        mode=mode, direction=direction, pace=pace, position=position, depth=depth, duration=duration,
    ).scale_terms
    if not terms:
        return ""
    expr = " + ".join(terms)
    return f"scale=w='iw*(1+({expr}))':h='ih*(1+({expr}))':eval=frame"


def _occlusion_fragment(k: int, mask_path: str) -> tuple[list[str], str]:
    """Multiply a depth-derived occlusion mask into card ``k``'s alpha, so the
    plate's foreground objects cover the character. [Story 8.16]

    Returns (chain parts, the label carrying the masked sprite). Applied at the
    *head* of the card's chain, where the sprite is still at its native pixel
    size: compositing_service authors the mask at exactly that size, so a plain
    ``alphamerge`` suffices and no ``scale2ref`` dimension matching is needed
    (the later scale stages then shrink card and mask together — by that point
    they are one image).

    The mask arrives through ``movie=`` rather than a new ``-i`` input: both
    render paths derive their narration/audio stream indices from the card count
    (``[{num_cards + 1}:a]``), so an extra input would shift every index.

    ``split`` before use is mandatory — ffmpeg rejects a labeled pad consumed by
    two filters (the same hazard ``build_light_wrap`` documents), and the sprite
    feeds both ``alphaextract`` and ``alphamerge`` here.

    ponytail: the mask rides the card, so the few px of idle sway/bob move the
    occluder edge with it. The alternative — repainting the occluder in frame
    space over the composited card — needs the plate's alpha-cut copy carried
    through zoompan, whose alpha handling ``_character_zoom_filter`` already
    warns about.

    Known ceiling, measured not guessed: the mask is cut once in plate space, but
    under Ken Burns the plate's occluder and the card's ground point travel at
    different rates (they sit at different heights, and the card's own parallax
    zoom only approximates the plate's). On a 1.15x push-in with the feet at 0.85
    and an occluder edge at 0.70 they diverge by ~25px by the last frame — the
    character peeks slightly past a hard edge late in a moving shot. Upgrade path
    is frame-space occlusion, which is a story of its own; recorded in
    deferred-work.md rather than half-built here.
    """
    escaped = _escape_subtitles_path(Path(mask_path).resolve())
    return (
        [
            f"[{k + 1}:v]split=2[om{k}a][om{k}b]",
            f"[om{k}a]alphaextract[om{k}alpha]",
            f"movie='{escaped}',format=gray[om{k}mask]",
            f"[om{k}alpha][om{k}mask]blend=all_mode=multiply[om{k}alpha2]",
            f"[om{k}b][om{k}alpha2]alphamerge[om{k}]",
        ],
        f"om{k}",
    )


def _character_scale_filter(depth: str = "near") -> str:
    """Cap an oversized card to its depth-scaled motion-safe box. [review:1.9c]
    [Story 8.3 AC:6]

    Downscale-only (``min(iw,…)`` guards against upscaling a small cutout) and
    aspect-preserving (``force_original_aspect_ratio=decrease``). A card is never
    resized upstream, so without this an asset larger than the frame clips or
    overflows; capping to CHAR_MAX_W/H (minus sway/bob amplitude) times the
    depth's scale factor keeps the anchored overlay's full sine excursion
    on-frame and enforces the far/mid/near framing convention (never full-frame
    — that's D13).
    """
    scale = _DEPTH_SCALE.get(depth, _DEPTH_SCALE["mid"])
    max_w = CHAR_MAX_W * scale
    max_h = CHAR_MAX_H * scale
    return (
        rf"scale=w='min(iw\,{max_w})':h='min(ih\,{max_h})'"
        ":force_original_aspect_ratio=decrease"
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def _escape_subtitles_path(path: Path) -> str:
    """Escape a path for the ffmpeg ``subtitles=`` filter option. [1.9b hardening]

    The value is wrapped in single quotes by the caller; here we escape the
    characters the filtergraph/option parser still treats as special inside
    quotes: ``\\``, ``'`` and ``:`` (drive colons, run_ids with ``:``).
    """
    return (
        str(path)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
    )


def _settings() -> Settings:
    # ponytail: seam so unit tests can inject fake settings without a real .env.
    return Settings()  # type: ignore[call-arg]


def _card_font() -> str:
    """Resolve the bundled Pretendard Bold card font. [Story 5.17 AC:5]

    A repo-relative committed file, not a fontconfig lookup — portable by
    construction, unlike the machine-specific system-font search it replaces.
    Fails fast if missing: that's repo corruption, not an environment condition.
    """
    if not CARD_FONT_PATH.exists():
        raise RuntimeError(f"bundled card font not found: {CARD_FONT_PATH}")
    return str(CARD_FONT_PATH)


def _subtitle_fontsdir() -> Path:
    """Resolve the bundled subtitle font directory. [Story 5.18 AC:6]

    Fails fast if missing: a silently-absent fontsdir doesn't error in ffmpeg,
    it just falls back to whatever system font libass finds — same repo-corruption
    guard as _card_font().
    """
    if not SUBTITLE_FONT_DIR.is_dir():
        raise RuntimeError(f"bundled subtitle font directory not found: {SUBTITLE_FONT_DIR}")
    return SUBTITLE_FONT_DIR


def _card_label(scene: SceneState) -> str:
    """Chapter-card title for the upcoming scene, falling back to "- N -"
    when the scenario stage hasn't produced one yet. [Story 5.1 AC:3] [Story 5.17 AC:8]"""
    title = str(scene.get("title") or "").strip()
    return title or f"- {scene['scene_num']} -"


def _chapter_card_duration(value: float) -> float:
    """Clamp chapter-card duration to the accepted Story 5.1 range."""
    return min(MAX_CARD_DURATION, max(MIN_CARD_DURATION, float(value)))


def _scp_wiki_slug(scp_id: str) -> str:
    """Wikidot slug: lowercase, hyphenated, no zero-padding. [Story 5.20]

    Deterministic from scp_id alone — confirmed live against the real wiki by
    Story 5.10's ScpWikiImageFetch. No HTTP call needed to know the page URL.
    """
    return scp_id.strip().lower()


_scp_nicknames: dict[str, str] | None = None  # ponytail: lazy-loaded cache; read-only reference data


def _scp_nickname(scp_id: str) -> str | None:
    """Best-effort nickname lookup from data/scps.json, cached after first call.

    Tolerant: a missing/corrupt file or unknown scp_id just means no nickname
    (AC:3) — never raises.
    """
    global _scp_nicknames
    if _scp_nicknames is None:
        try:
            entries = json.loads(SCP_DATA_PATH.read_text(encoding="utf-8"))
            # per-entry tolerant: one entry missing "id"/"nickname" must not
            # discard every other entry's lookup (AC:3).
            _scp_nicknames = {e["id"]: e["nickname"] for e in entries if "id" in e and "nickname" in e}
        except Exception as exc:  # noqa: BLE001 — tolerant lookup (AC:3)
            logger.warning("SCP nickname lookup unavailable: %s", exc)
            _scp_nicknames = {}
    return _scp_nicknames.get(scp_id)


def build_description_text(
    scp_id: str,
    *,
    scp_nickname: str | None = None,
    wiki_page_url: str | None = None,
) -> str:
    """Build the YouTube description.txt block. [Story 5.20 AC:3,4]

    The image-source line reuses the same deterministic wiki URL: whether the
    run's reference image actually came from the wiki or fell back to DDG, the
    article itself is CC BY-SA either way (per AC:4). Author-byline extraction
    is deliberately out of scope — it would require fetching the wiki page at
    video time, which the story's own guardrails rule out; the page link alone
    is the documented-sufficient fallback (AC:3).
    """
    url = wiki_page_url or f"{WIKI_BASE_URL}/{_scp_wiki_slug(scp_id)}"
    title = f"[{scp_id}] {scp_nickname} — SCP Foundation Wiki" if scp_nickname else f"[{scp_id}] — SCP Foundation Wiki"
    return (
        f"{title}\n"
        f"{url}\n"
        "\n"
        "Licensed under CC BY-SA 3.0\n"
        f"{CC_LICENSE_URL}\n"
        "\n"
        f'This video is a derivative work based on "{scp_id}" from the SCP Foundation Wiki.\n'
        "\n"
        "---\n"
        f"Image source: {url}\n"
    )


async def _write_description_artifact(run_dir: Path, scp_id: str) -> Path | None:
    """Write description.txt to the run directory. Non-fatal (AD-10, AC:5).

    Async for consistency with video_node's other await'd calls; the actual I/O
    (mkdir + write_text) is synchronous — same seam _card_font()/_settings() use.
    """
    try:
        text = build_description_text(scp_id, scp_nickname=_scp_nickname(scp_id))
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "description.txt"
        path.write_text(text, encoding="utf-8")
        return path
    except Exception as exc:  # noqa: BLE001 — AD-10: attribution never fails the run
        logger.warning("description.txt write failed: %s", exc)
        return None


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _record_trace(
    *,
    run_id: str,
    scene_count: int,
    latency_ms: int,
    output_path: str | None = None,
    returncode: int | None = None,
    effects: list | None = None,
    upscale_pass: bool = True,
    card_counts: list[int] | None = None,
    motion_style_counts: dict[str, int] | None = None,
    movement_mode_counts: dict[str, int] | None = None,
    movement_pace_counts: dict[str, int] | None = None,
    cast_resolution: dict | None = None,
    chapter_cards_enabled: bool = False,
    chapter_card_duration: float | None = None,
    chapter_card_count: int = 0,
    ending_credit: bool = False,
    ending_credit_error: str | None = None,
    composite_harmonization_tier: int = 0,
    relit_pairs_computed: int = 0,
    relit_pairs_failed: int = 0,
    camera_noise_enabled: bool = False,
    renderer_counts: dict[str, int] | None = None,
    parallax_25d_enabled: bool = False,
    displacement_frac: float = 0.0,
    error=None,
) -> None:
    """Best-effort Langfuse span enrichment. [AD-10 — tracing is non-fatal]"""
    try:
        metadata: dict = {
            "run_id": run_id,
            "scene_count": scene_count,
            "latency_ms": latency_ms,
            **({"output_path": output_path} if output_path else {}),
            **({"ffmpeg_returncode": returncode} if returncode is not None else {}),
            **({"effects": effects} if effects is not None else {}),
            "transition": "dip-to-black",
            "fade_duration": FADE_DURATION,
            "black_hold_sec": BLACK_HOLD_DURATION,
            "chapter_cards_enabled": chapter_cards_enabled,
            "chapter_card_count": chapter_card_count,
            **({"chapter_card_duration": chapter_card_duration} if chapter_card_duration is not None else {}),
            "upscale_pass": upscale_pass,
            # Story 8.7: composite harmonization tier + Tier 3 relight precompute
            # outcome (0/0 when tier<3 or the resolver isn't injected).
            "composite_harmonization_tier": composite_harmonization_tier,
            "relit_pairs_computed": relit_pairs_computed,
            "relit_pairs_failed": relit_pairs_failed,
            # Per-scene card counts (Story 8.3, replaces 1.9c's single character_scenes).
            "card_counts": card_counts or [],
            # Story 8.8: aggregate style counts + table version replace 1.9c's
            # fixed sway/bob numbers, now that a card's motion is one of several
            # LLM-selected techniques rather than a single hardcoded pair.
            "character_motion": {
                "table_version": character_motion.MOTION_TABLE_VERSION,
                "style_counts": motion_style_counts or {},
            },
            # Story 8.9: screen-blocking mode/pace counts, same non-fatal
            # tracing posture as 8.8's style_counts above.
            "character_movement": {
                "table_version": character_movement.MOVEMENT_TABLE_VERSION,
                "mode_counts": movement_mode_counts or {},
                "pace_counts": movement_pace_counts or {},
            },
            # Story 11.3: fBm camera-noise version + kill-switch state — the
            # 8.8 table_version idiom, for "why does this render look
            # different" questions.
            "camera_path": {
                "version": camera_path.CAMERA_PATH_VERSION,
                "enabled": camera_noise_enabled,
            },
            # Story 11.5 AC:10 — which renderer actually produced each shot's
            # background, how long it took, how often the cache answered, and
            # every fallback reason keyed `fallback_<reason>`. This is the ONLY
            # signal separating "2.5D rendered" from "2.5D silently fell back",
            # so it is reported unconditionally, not just when something failed.
            "parallax_25d": {
                "enabled": parallax_25d_enabled,
                "displacement_frac": displacement_frac,
                "layer_ratios": _LAYER_PARALLAX_RATIO,
                "renderer_counts": renderer_counts or {},
            },
            "ending_credit": ending_credit,
            "ending_credit_error": ending_credit_error,
            **({"error": repr(error)} if error is not None else {}),
        }
        # Story 8.3: cast resolution tracing metadata (replaces 1.13's angle_selection)
        if cast_resolution:
            metadata["cast_resolution"] = cast_resolution
        get_client().update_current_span(metadata=metadata)
    except Exception:  # noqa: BLE001
        pass


def _validate_scene_assets(
    scenes: list[SceneState], *, sound_design_enabled: bool = False, min_shot_clip_sec: float = 2.0,
) -> None:
    """Raise before FFmpeg if required per-scene assets are missing. [AC:2]"""
    for scene in scenes:
        n = scene["scene_num"]
        rendered_shots = [s for s in (scene.get("shots") or []) if s.get("image_path")]
        if not rendered_shots:
            raise ValueError(f"scene {n}: no shot has a valid image_path")
        audio = scene.get("audio_path")
        if not audio or not Path(audio).exists():
            raise FileNotFoundError(f"scene {n}: audio_path missing or not found: {audio!r}")
        subtitle = scene.get("subtitle_path")
        if not subtitle or not Path(subtitle).exists():
            raise FileNotFoundError(f"scene {n}: subtitle_path missing or not found: {subtitle!r}")
        # Cast card existence/alpha validation happens after resolution, in video_node
        # (Story 8.3 AC:10) — resolution runs after this check, so it can't live here.
        # audio_duration drives zoompan frame count + segment fade timing; a missing/≤0 value
        # would silently truncate the scene (via -shortest) or corrupt timing. Fail fast
        # instead of inventing a fallback duration. [review:D]
        dur = scene.get("audio_duration")
        if not isinstance(dur, (int, float)) or dur <= 0:
            raise ValueError(f"scene {n}: audio_duration must be a positive number, got {dur!r}")
        # Story 8.11 [review fix]: validate only the shots that will actually get
        # their own clip — shot_timing.plan_shot_clips may merge a short or
        # sentence-unclaimed shot's window away, and an unused shot's missing
        # image must not abort the run (the pre-8.11 rule, now scoped to every
        # kept shot instead of just the first).
        plan = shot_timing.plan_shot_clips(
            rendered_shots, scene.get("word_timings") or [], scene.get("narration") or "",
            dur, min_shot_clip_sec=min_shot_clip_sec,
        )
        for clip in plan:
            img = clip.shot["image_path"]
            assert img is not None  # selected because image_path is truthy
            if not Path(img).exists():
                raise FileNotFoundError(
                    f"scene {n} shot {clip.shot['shot_id']}: image_path not found: {img!r}"
                )
        # Sound design (Story 7.1): fail fast if the resolved mood's assets are missing,
        # same up-front posture as the image/audio/subtitle checks above. [AC:5]
        if sound_design_enabled:
            validate_mood_assets(resolve_mood(scene.get("mood")))


async def _run_ffmpeg(*args: str) -> tuple[int, str]:
    """Spawn ffmpeg with argument list; return (returncode, stderr text)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_bytes = await proc.communicate()
    rc = proc.returncode
    assert rc is not None  # always set after communicate()
    return rc, (stderr_bytes or b"").decode(errors="replace")


_OUTPUT_ARGS = (
    "-c:v", "libx264", "-preset", "fast",
    "-c:a", "aac", "-b:a", "128k",
    "-pix_fmt", "yuv420p",
    "-shortest",
)


def _merge_placements(
    cast_cards: dict[str, list[dict]], placements: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Fold the ground resolver's per-card placement dicts into the cast cards.
    [Story 8.16]

    Positional merge against the exact card list the resolver was handed. A shot
    whose placement list is missing, the wrong length, or not a list of dicts
    keeps its pre-8.16 cards untouched — the resolver's job is to annotate, and
    a shape mismatch means it did something else.
    """
    merged: dict[str, list[dict]] = {}
    for shot_key, cards in cast_cards.items():
        shot_placements = placements.get(shot_key)
        if not isinstance(shot_placements, list) or len(shot_placements) != len(cards):
            if shot_placements is not None:
                logger.warning("Ignoring mismatched placements for shot %s", shot_key)
            merged[shot_key] = cards
            continue
        merged[shot_key] = [
            _apply_placement(card, placement) if isinstance(card, dict) else card
            for card, placement in zip(cards, shot_placements)
        ]
    return merged


# A card is bottom-anchored at ground_y, so the frame below it has to hold the whole
# downward motion excursion — idle bob plus parallax pan. CHAR_MAX_H was derived for a
# centre anchor with that margin on both sides; bottom-anchoring spends it all at the
# bottom, and a measured near ground line of 0.94 leaves 65px for a 28.5px requirement
# only by luck. Clamping here rather than in compositing_service keeps the motion
# constants in the module that owns them (services must not import pipeline, AD-1).
#
# [review fix] The pan budget here is _MACRO_PAN_RESERVE_PX, the SAME reserve
# CHAR_MAX_W/H use — not 7.3's 12px. A 2.5D card's layer term reaches
# _LAYER_MAX_PX (46.08px) downward, so under the old 12px budget a card at the
# clamp ran 34.1px past the bottom edge in the analytic worst case (18.7px at the
# shipped 2%). Measured trajectories only reached ~29px of that ceiling, so it
# survived by ~5px of luck rather than clipping outright — which is the same "only
# by luck" this comment already warned about above, and not a bound this module
# accepts. Widening CHAR_MAX_H alone fixed only the CENTRE-anchored case;
# ground-anchored cards (the production path — depth_placement_enabled=True) spend
# the whole reserve downward and need it reserved here too (AC7's "full combined
# excursion is proven not to clip the card").
_GROUND_Y_MAX = 1.0 - (_MAX_MOTION_Y_PX + _MACRO_PAN_RESERVE_PX) / COMP_H


def _apply_placement(card: dict, placement: object) -> dict:
    """Merge one placement dict, dropping values the filtergraph cannot take.

    ``ground_y`` reaches an f-string format spec, so a string or None there raises out of
    the chain builder long after the resolver's own try/except has returned — a bad
    annotation would fail the whole video stage instead of degrading to the old anchor.
    """
    if not isinstance(placement, dict):
        return card
    clean = dict(placement)
    ground_y = clean.get("ground_y")
    if ground_y is not None:
        if isinstance(ground_y, bool) or not isinstance(ground_y, (int, float)):
            logger.warning("Dropping non-numeric ground_y %r; keeping the centre anchor", ground_y)
            clean.pop("ground_y")
        else:
            clamped = min(max(float(ground_y), 0.0), _GROUND_Y_MAX)
            if clamped != float(ground_y):
                logger.warning(
                    "Clamped ground_y %.3f to %.3f so the card's motion stays in frame",
                    float(ground_y), clamped,
                )
            clean["ground_y"] = clamped
    return {**card, **clean}


_FUSION_STILL_SPEC = EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=1.0)
"""Motionless Ken Burns: zoom 1.0→1.0 on a non-``out-center`` direction.

``ground_y_expr`` then reduces to ``main_h*ground_y - overlay_h`` — the static
bottom anchor — while ``_zoompan_filter`` still emits its exact framing chain
(``scale=1728:-2 → crop=1728:972 → scale=8000 → zoompan``). So the still is framed
identically to the moving render's first frame, and re-animating the fused still
afterwards puts the plate through that chain once more with no change of framing.
"""


async def render_composite_still(
    shot: ShotData,
    cards: list[dict],
    out_path: Path,
    *,
    mood: str | None,
    composite_harmonization_tier: int,
    background_override: str | None = None,
) -> Path | None:
    """Render one shot's plate+cards composite as a single motionless PNG.

    This is the input to Story 10.1b-stage-2 fusion. It drives the **existing**
    ``_build_card_chain``, so every placement rule — card scale, x anchor,
    bottom-anchored ``ground_y``, the ``_GROUND_Y_MAX`` clamp, edge feather,
    occlusion alpha multiply, mood tint, contact shadow, far→near z-order — comes
    from the one implementation the moving render uses. Nothing is re-derived here.

    Motion is switched off through the seams the chain already exposes rather than
    by bypassing it: a zoom-1.0 spec (static ground expression and no plate move),
    ``trajectory=None`` (no 11.5 layer terms), ``parallax_enabled=False`` (no card
    zoom, no 7.3 macro pan), and per-card ``motion_style="hold"`` /
    ``movement_mode="anchored"`` (no idle sine, no 8.9 entrance offsets). Those
    terms are the ones that are non-zero at t=0, so leaving any of them on would
    bake a fraction of a frame's animation into the still.
    """
    image_path = shot.get("image_path")
    if (not image_path and not background_override) or not cards:
        return None
    duration = 1.0
    bg_input = (
        ["-f", "lavfi", "-i", f"color={background_override}:s={COMP_W}x{COMP_H}:r={FPS}"]
        if background_override
        else ["-loop", "1", "-framerate", str(FPS), "-i", str(image_path)]
    )
    motion = MotionSource(
        bg_input=bg_input,
        bg_chain=_zoompan_filter(_FUSION_STILL_SPEC, duration),
        spec=_FUSION_STILL_SPEC,
        camera_shake="",
        parallax_enabled=False,
        trajectory=None,
        renderer="fusion-still",
    )
    frozen = [{**c, "motion_style": "hold", "movement_mode": "anchored"} for c in cards]
    ordered = sorted(frozen, key=lambda c: _DEPTH_ORDER.get(c.get("depth", "mid"), 1))
    inputs = list(motion.bg_input)
    for card in ordered:
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(card["path"])]
    chain_parts, prev_label = _build_card_chain(
        motion, ordered, duration, mood, composite_harmonization_tier=composite_harmonization_tier,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    code, err = await _run_ffmpeg(
        "-y", *inputs,
        "-filter_complex", ";".join(chain_parts),
        "-map", f"[{prev_label}]", "-frames:v", "1", "-update", "1",
        str(out_path),
    )
    if code != 0 or not out_path.exists():
        logger.warning("Composite still failed for shot %s: %s", shot.get("shot_id"), err[-400:])
        return None
    return out_path


async def render_card_coverage_mask(
    shot: ShotData,
    cards: list[dict],
    out_path: Path,
    *,
    mood: str | None,
) -> Path | None:
    """White where the cards cover the frame, black where the plate shows through.

    The fusion pass needs to know which pixels are *card* so it can protect them
    while it re-draws the seam. That region could be computed from ``ground_y`` ×
    position × depth × sprite aspect — and must not be, because it would be the
    third copy of placement arithmetic that already lives in ``_build_card_chain``.

    Instead it is *measured*: render the same chain twice, once over solid black
    and once over solid white. A pixel the card covers opaquely is identical in
    both; a pixel showing plate differs by the full 255. So ``255 - |black-white|``
    is the coverage, and a feathered edge at alpha ``a`` lands on ``255a`` for free
    — exactly the soft mask the fusion wants, with no threshold to tune.

    Harmonization is forced to tier 0 here: the contact shadow is drawn onto the
    *background*, not the card, so including it would mark the shadow as protected
    when re-drawing it is precisely what fuses the contact into the plate.
    """
    if not cards:
        return None
    black = out_path.with_name(f"{out_path.stem}.k.png")
    white = out_path.with_name(f"{out_path.stem}.w.png")
    for colour, path in (("black", black), ("white", white)):
        if await render_composite_still(
            shot, cards, path, mood=mood, composite_harmonization_tier=0, background_override=colour,
        ) is None:
            return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    code, err = await _run_ffmpeg(
        "-y", "-i", str(black), "-i", str(white),
        "-filter_complex",
        "[0:v]format=gray[k];[1:v]format=gray[w];"
        "[k][w]blend=all_mode=difference,negate,format=gray[m]",
        "-map", "[m]", "-frames:v", "1", "-update", "1", str(out_path),
    )
    black.unlink(missing_ok=True)
    white.unlink(missing_ok=True)
    if code != 0 or not out_path.exists():
        logger.warning("Card coverage mask failed for shot %s: %s", shot.get("shot_id"), err[-400:])
        return None
    return out_path


def _build_card_chain(
    motion: MotionSource,
    ordered_cards: list[dict],
    duration: float,
    mood: str | None,
    *,
    composite_harmonization_tier: int,
) -> tuple[list[str], str]:
    """Background motion + N stacked card overlays, far painted first, near
    last/on top. [Story 8.3 AC:6,7] [Story 8.7] [Story 8.8] [Story 8.9] [11.5 AC:7,8]

    Shared by the single-pass scene render (`_render_scene_fast`) and Story
    8.11's per-shot silent-clip pass (`_compose_shot_clip`) — one
    implementation of the overlay chain so the two can never drift. Both
    callers only invoke this when `ordered_cards` is non-empty; the
    background-only case renders through a separate, simpler `-vf` path with
    no `-filter_complex` at all. Returns (chain_parts, final_label).

    Story 11.5: the background arrives through `motion` — either a zoompan chain
    over the still plate (legacy) or a no-op over the pre-rendered 2.5D clip. The
    card side reads `motion` for its layer terms, its parallax coupling and its
    floor tracking, so one object decides all four together.
    """
    spec = motion.spec
    parallax_enabled = motion.parallax_enabled
    # Composite harmonization (Story 8.7): lazy import behind the tier check
    # so tier=0 never touches this module (AC:13 — ponytail, don't import
    # what you don't use).
    harmonize = composite_harmonization_tier >= 1
    light_wrap = composite_harmonization_tier >= 2
    tint = ""
    build_contact_shadow = build_light_wrap = None
    if harmonize:
        from yt_flow.pipeline.nodes.composite_harmonization import (
            build_contact_shadow,
            build_sprite_tint,
        )
        tint = build_sprite_tint(mood)
    if light_wrap:
        from yt_flow.pipeline.nodes.composite_harmonization import build_light_wrap

    chain_parts = [f"[0:v]{motion.bg_chain}[bg]"]
    prev_label = "bg"
    for k, card in enumerate(ordered_cards):
        depth = card.get("depth", "mid")
        position = card.get("position", "center")
        motion_style = card.get("motion_style", "breath")
        motion_energy = card.get("motion_energy", "medium")
        movement_mode = card.get("movement_mode", "anchored")
        movement_direction = card.get("movement_direction", "none")
        movement_pace = card.get("movement_pace", "slow")
        # Story 8.16: both None unless the ground resolver ran — the pre-8.16
        # anchor and shadow expressions are then reproduced byte-for-byte.
        ground_y = card.get("ground_y")
        occlusion_mask = card.get("occlusion_mask")
        # Movement (Story 8.9 AC:5): chained right after the depth-cap anchor,
        # before parallax/idle-motion scale stages. "" for anchored — the
        # pre-8.9 chain is unchanged.
        movement_scale = _movement_scale_filter(
            movement_mode, movement_direction, movement_pace, position, depth, duration,
        )
        # Feather first (Story 11.1 AC6): before any scale stage, so downstream
        # scaling preserves/shrinks the soft edge instead of re-hardening it.
        char_chain = f"{CARD_EDGE_FEATHER},{_character_scale_filter(depth)}"
        if movement_scale:
            char_chain += f",{movement_scale}"
        # Parallax (Story 7.3/8.3 AC:7): couple each card's zoom/pan to the
        # background's spec, amplified per depth. Off → fixed-size idle motion.
        if parallax_enabled:
            char_spec = _character_spec(spec, depth)
            char_chain += f",{_character_zoom_filter(char_spec, duration)}"
        else:
            char_spec = None
        # The plate is under Ken Burns for the whole shot, so a floor measured on the
        # still plate moves. Track it (Story 8.16) instead of pinning feet to a static
        # fraction and letting card and floor part company by the last frame.
        ground_expr = (
            motion.ground_expr(float(ground_y), duration) if ground_y is not None else None
        )
        layer_terms = motion.layer_terms(depth)
        overlay = _overlay_filter(
            position, k, char_spec, duration, depth, motion_style, motion_energy,
            movement_mode, movement_direction, movement_pace, ground_y, ground_expr,
            layer_terms,
        )
        # Scale-pulse (Story 8.8 AC:6): "" for hold/glitch, appended as its own
        # stage for breath/sway/tremble/pulse so it composes with either branch above.
        pulse = _motion_scale_filter(motion_style, motion_energy, k)
        if pulse:
            char_chain += f",{pulse}"
        # Tier 1 (Story 8.7 AC:1): mood tint on the sprite, before overlay.
        if harmonize:
            char_chain += f",{tint}"
        out_label = f"o{k}"
        card_source = f"{k + 1}:v"
        if occlusion_mask:
            occlusion_parts, card_source = _occlusion_fragment(k, occlusion_mask)
            chain_parts.extend(occlusion_parts)
        chain_parts.append(f"[{card_source}]{char_chain}[c{k}]")

        # Tier 1 (AC:2): contact shadow, composited between bg and the card.
        base_label = prev_label
        if harmonize:
            shadow = build_contact_shadow(card)
            # geq draws a static ellipse (it has no time terms), so when ground_y_expr
            # walks the feet with the plate the shadow has to slide with them or the
            # card grows a detached puddle. Same expression, offset from the static
            # y_frac the ellipse was drawn at — they cannot disagree by construction.
            shadow_y = "0"
            if ground_expr is not None:
                shadow_y = f"({ground_expr})+main_h*{1.0 - float(ground_y):g}"
            shadow_x = "0"
            if layer_terms is not None:
                # [review fix] The 2.5D layer term translates the card as a whole
                # LAYER, and the contact shadow belongs to that layer — it is the
                # card's own footprint, not a mark on the plate. Without this the
                # shadow stayed pinned while the card slid up to 30.7px away at the
                # shipped 2% displacement (46.08px at 3%), i.e. exactly the
                # "detached puddle" the shadow_y tracking above exists to prevent.
                # Idle bob/sway is still deliberately NOT applied: feet lift off a
                # stationary shadow, a whole layer does not.
                shadow_x = f"({layer_terms[0]})"
                shadow_y = f"({shadow_y})+({layer_terms[1]})"
            chain_parts.append(f"color=c=black:s={COMP_W}x{COMP_H},format=rgba[sh{k}src]")
            chain_parts.append(f"[sh{k}src]{shadow}[sh{k}]")
            chain_parts.append(
                f"[{base_label}][sh{k}]overlay=x='{shadow_x}':y='{shadow_y}':eval=frame[shg{k}]"
            )
            base_label = f"shg{k}"

        # Tier 2 (AC:5,6): light wrap between the tinted card and the overlay.
        # base_label feeds both light_wrap's edge-detection AND the final
        # overlay below — split it first, same "Invalid file index"/"matches
        # no streams" hazard build_light_wrap's own char_label split guards
        # against (live-verified: ffmpeg rejects a label consumed twice).
        card_label = f"c{k}"
        if light_wrap:
            bg_a, bg_b = f"wbg{k}a", f"wbg{k}b"
            chain_parts.append(f"[{base_label}]split=2[{bg_a}][{bg_b}]")
            wrapped_label = f"cw{k}"
            chain_parts.append(build_light_wrap(bg_a, card_label, wrapped_label, position=position))
            card_label = wrapped_label
            base_label = bg_b

        chain_parts.append(f"[{base_label}][{card_label}]{overlay}[{out_label}]")
        prev_label = out_label

    return chain_parts, prev_label


async def _render_scene_fast(
    motion: MotionSource,
    duration: float,
    seg_path: Path,
    n: int,
    *,
    cards: list[dict],
    mood: str | None,
    audio_path: str,
    subtitle_path: str,
    sound_design_enabled: bool,
    post_fx_enabled: bool,
    include_stinger: bool,
    composite_harmonization_tier: int,
) -> None:
    """Render a scene segment in a single ffmpeg pass: background motion +
    burned SRT, optionally with N cast cards + mood-driven sound design/post-fx.
    [AC:1,3] [Story 7.1] [Story 7.2 AC:4,5,6,8,9] [Story 8.3 AC:6,7,8,9]

    The pre-8.11 code path — used by `_compose_scene` whenever a scene's
    shot-clip plan is a single clip (nothing to cut, the common case).
    [Story 8.11 — ponytail: no concat overhead when there's nothing to concat]

    Story 11.5 AC:8 — the background comes from `motion`, the one seam both this
    path and `_compose_shot_clip` share; nothing here knows whether it is looping
    a still plate under zoompan or reading a pre-rendered 2.5D clip.

    `motion.camera_shake` (Story 11.3 AC:2): a prebuilt `_camera_shake_filter`
    chain, inserted after composition and BEFORE post-fx/subtitles — subtitles
    are screen-space UI and must not shake; vignette/grain are lens-space and
    must ride the shaken frame. "" attaches nothing (pre-11.3 byte-identical, and
    always "" on the 2.5D path where the trajectory already owns the shake).
    """
    camera_shake = motion.camera_shake
    shake_head = f"{camera_shake}," if camera_shake else ""   # card branch: before post_label
    shake_tail = f",{camera_shake}" if camera_shake else ""   # bg-only: after bg_chain
    sub = _escape_subtitles_path(Path(subtitle_path).resolve())
    fontsdir = _escape_subtitles_path(_subtitle_fontsdir().resolve())
    # [Story 7.2 AC:4-9] Precomputed fragments, empty when post_fx_enabled=False
    # so every chain below degrades to today's byte-for-byte ungraded output.
    post_filter = build_post_filter(mood) if post_fx_enabled else ""
    post_frag = f",{post_filter}" if post_fx_enabled else ""
    post_label = f"{post_filter}[graded];[graded]" if post_fx_enabled else ""

    # Stacking order (Story 8.3 AC:6): far painted first, near painted last/on
    # top — stable sort so same-depth members keep cast order.
    ordered_cards = sorted(cards or [], key=lambda c: _DEPTH_ORDER.get(c.get("depth", "mid"), 1))
    num_cards = len(ordered_cards)

    if num_cards:
        # N-card compositing: bg=0, cards=1..N, narration=N+1. Each card is a
        # looped still like the background; chained overlays far→near, subtitle
        # burn last (Dev Notes "Overlay chain shape").
        inputs = list(motion.bg_input)
        for card in ordered_cards:
            inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(card["path"])]
        inputs += ["-i", audio_path]

        chain_parts, prev_label = _build_card_chain(
            motion, ordered_cards, duration, mood,
            composite_harmonization_tier=composite_harmonization_tier,
        )
        chain_parts.append(f"[{prev_label}]{shake_head}{post_label}subtitles='{sub}':fontsdir='{fontsdir}'[out]")
        video_chain = ";".join(chain_parts)
        video_map = "[out]"
        narration_label = f"[{num_cards + 1}:a]"
        input_offset = num_cards + 2
        narration_map = f"{num_cards + 1}:a"
    else:
        # Background-only (1.9b): zoompan already emits COMP_W x COMP_H, just burn SRT.
        inputs = [*motion.bg_input, "-i", audio_path]
        video_chain = (
            f"[0:v]{motion.bg_chain}{shake_tail}{post_frag},"
            f"subtitles='{sub}':fontsdir='{fontsdir}'[vout]"
        )
        video_map = "[vout]"
        narration_label = "[1:a]"
        input_offset = 2
        narration_map = "1:a"

    if sound_design_enabled:
        # Hazard 1: -vf and -filter_complex are mutually exclusive in ffmpeg, so the
        # background-only branch's video chain is folded into filter_complex here
        # (labeled [vout]) instead of staying a -vf string. Hazard 2: input_offset/
        # narration_label differ per branch — see class docstring in sound_design.py.
        resolved_mood = resolve_mood(mood)
        sound_args = build_sound_design_args(resolved_mood, include_stinger=include_stinger)
        sound_fragment, audio_out_label = build_sound_design_filter(
            resolved_mood, duration, narration_label, input_offset, include_stinger=include_stinger,
        )
        ffmpeg_args = [
            "-y", *inputs, *sound_args,
            "-filter_complex", f"{video_chain};{sound_fragment}",
            "-map", video_map, "-map", audio_out_label,
            # -shortest alone doesn't reliably bound the infinite `-loop 1` video
            # against a filter-graph-produced [aout] pad (verified against real
            # ffmpeg: without -t, encoding never reaches EOF on the looped bgm/
            # ambient beds). -t pins the segment to the scene's real duration.
            "-t", str(duration),
            *_OUTPUT_ARGS, str(seg_path),
        ]
    elif num_cards:
        ffmpeg_args = [
            "-y", *inputs,
            "-filter_complex", video_chain,
            "-map", video_map, "-map", narration_map,
            *_OUTPUT_ARGS, str(seg_path),
        ]
    else:
        # Sound design disabled (AC:8): keep the pre-existing -vf path, still
        # carrying post_frag (empty string when post_fx_enabled=False too).
        vf = f"{motion.bg_chain}{shake_tail}{post_frag},subtitles='{sub}':fontsdir='{fontsdir}'"
        ffmpeg_args = [
            "-y", *inputs,
            "-vf", vf,
            *_OUTPUT_ARGS, str(seg_path),
        ]

    rc, stderr = await _run_ffmpeg(*ffmpeg_args)
    if rc != 0:
        raise RuntimeError(f"FFmpeg scene {n} failed (rc={rc}): {stderr[-500:]}")
    if not seg_path.exists():
        raise RuntimeError(f"FFmpeg scene {n}: output not created: {seg_path}")


_SHOT_CLIP_OUTPUT_ARGS = ("-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p")


async def _compose_shot_clip(
    shot: ShotData,
    motion: MotionSource,
    duration: float,
    out_path: Path,
    *,
    cards: list[dict],
    mood: str | None,
    composite_harmonization_tier: int,
) -> None:
    """Render one shot's silent background+cards clip — pass 1 of Story 8.11's
    per-shot cut assembly. No audio, no subtitle burn, no post-fx: those apply
    once at scene level in pass 2 (`_assemble_scene_from_clips`). `duration`
    is the shot's own clip span (its sentence window), not the scene's
    audio_duration — 8.9's movement curves key off this.

    `camera_shake` (Story 11.3 AC:2) attaches after composition; pass 2 then
    adds post-fx/subtitles, so the shake→post→subtitles order holds by
    construction on this path.
    """
    camera_shake = motion.camera_shake
    ordered_cards = sorted(cards or [], key=lambda c: _DEPTH_ORDER.get(c.get("depth", "mid"), 1))

    if ordered_cards:
        inputs = list(motion.bg_input)
        for card in ordered_cards:
            inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(card["path"])]
        chain_parts, prev_label = _build_card_chain(
            motion, ordered_cards, duration, mood,
            composite_harmonization_tier=composite_harmonization_tier,
        )
        if camera_shake:
            chain_parts.append(f"[{prev_label}]{camera_shake}[shk]")
            prev_label = "shk"
        ffmpeg_args = [
            "-y", *inputs,
            "-filter_complex", ";".join(chain_parts),
            "-map", f"[{prev_label}]",
            "-t", str(duration),
            *_SHOT_CLIP_OUTPUT_ARGS, str(out_path),
        ]
    else:
        inputs = list(motion.bg_input)
        ffmpeg_args = [
            "-y", *inputs,
            "-vf", f"{motion.bg_chain},{camera_shake}" if camera_shake else motion.bg_chain,
            "-t", str(duration),
            *_SHOT_CLIP_OUTPUT_ARGS, str(out_path),
        ]

    rc, stderr = await _run_ffmpeg(*ffmpeg_args)
    if rc != 0:
        raise RuntimeError(f"FFmpeg shot clip {shot['shot_id']} failed (rc={rc}): {stderr[-500:]}")
    if not out_path.exists():
        raise RuntimeError(f"FFmpeg shot clip {shot['shot_id']}: output not created: {out_path}")


async def _assemble_scene_from_clips(
    clip_paths: list[Path],
    duration: float,
    seg_path: Path,
    *,
    audio_path: str,
    subtitle_path: str,
    mood: str | None,
    sound_design_enabled: bool,
    post_fx_enabled: bool,
    include_stinger: bool,
) -> None:
    """Concat pass-1's silent shot clips — hard cuts, no crossfade (Dev Notes:
    the documentary idiom, avoids re-introducing 5.16's retired xfade
    problems) — then burn subtitles + mix narration audio/sound design/
    post-fx exactly as `_render_scene_fast` does for a single clip. Pass 2 of
    Story 8.11's per-shot cut assembly. [AC:6]
    """
    n_clips = len(clip_paths)
    sub = _escape_subtitles_path(Path(subtitle_path).resolve())
    fontsdir = _escape_subtitles_path(_subtitle_fontsdir().resolve())
    post_filter = build_post_filter(mood) if post_fx_enabled else ""
    post_label = f"{post_filter}[graded];[graded]" if post_fx_enabled else ""

    # concat demands identical w/h/SAR on every input. Generated 1344x768
    # backgrounds scaled to the canvas land on SAR 4600:4599 while stock-sized
    # ones stay 1:1, and the mix aborts the whole scene ("Input link ... do not
    # match"). Normalize each clip first — identity for an already-correct
    # 1920x1080 SAR-1:1 clip, so nothing that worked before changes.
    norm_parts = [
        f"[{i}:v]scale={COMP_W}:{COMP_H}:force_original_aspect_ratio=decrease,"
        f"pad={COMP_W}:{COMP_H}:(ow-iw)/2:(oh-ih)/2,setsar=1[cn{i}]"
        for i in range(n_clips)
    ]
    concat_labels = "".join(f"[cn{i}]" for i in range(n_clips))
    video_chain = (
        f"{';'.join(norm_parts)};"
        f"{concat_labels}concat=n={n_clips}:v=1:a=0[concat_v];"
        f"[concat_v]{post_label}subtitles='{sub}':fontsdir='{fontsdir}'[vout]"
    )

    inputs: list[str] = []
    for p in clip_paths:
        inputs += ["-i", str(p)]
    inputs += ["-i", audio_path]
    narration_label = f"[{n_clips}:a]"
    input_offset = n_clips + 1
    narration_map = f"{n_clips}:a"

    if sound_design_enabled:
        resolved_mood = resolve_mood(mood)
        sound_args = build_sound_design_args(resolved_mood, include_stinger=include_stinger)
        sound_fragment, audio_out_label = build_sound_design_filter(
            resolved_mood, duration, narration_label, input_offset, include_stinger=include_stinger,
        )
        ffmpeg_args = [
            "-y", *inputs, *sound_args,
            "-filter_complex", f"{video_chain};{sound_fragment}",
            "-map", "[vout]", "-map", audio_out_label,
            "-t", str(duration),
            *_OUTPUT_ARGS, str(seg_path),
        ]
    else:
        ffmpeg_args = [
            "-y", *inputs,
            "-filter_complex", video_chain,
            "-map", "[vout]", "-map", narration_map,
            "-t", str(duration),
            *_OUTPUT_ARGS, str(seg_path),
        ]

    rc, stderr = await _run_ffmpeg(*ffmpeg_args)
    if rc != 0:
        raise RuntimeError(f"FFmpeg scene assembly failed (rc={rc}): {stderr[-500:]}")
    if not seg_path.exists():
        raise RuntimeError(f"FFmpeg scene assembly: output not created: {seg_path}")


async def _compose_scene(
    scene: SceneState,
    scene_index: int,
    out_dir: Path,
    *,
    cards_by_shot: dict[str, list[dict]] | None = None,
    sound_design_enabled: bool = False,
    post_fx_enabled: bool = False,
    parallax_enabled: bool = False,
    include_stinger: bool = True,
    composite_harmonization_tier: int = 0,
    min_shot_clip_sec: float = 2.0,
    camera_noise_enabled: bool = False,
    renderer_counts: dict[str, int] | None = None,
) -> tuple[Path, EffectSpec, bool]:
    """Render one scene segment. [AC:1,3] [Story 7.1] [Story 7.2] [Story 8.3] [Story 8.11]

    `include_stinger=False` (Story 5.17 AC:7) omits this scene's own baked
    scene-entry stinger — set by the caller for a scene immediately preceded
    by a chapter card, since the card now carries that boundary's stinger hit.

    Camera noise (Story 11.3): `camera_noise_enabled` attaches the fBm
    handheld stage per clip. The trauma event shake (AC:3) rides ONLY the
    scene's first clip, and only when `sound_design_enabled and
    include_stinger` — the stinger one-shot plays at scene-segment t=0
    (sound_design.build_sound_design_args feeds it as a plain input), so the
    first clip's t=0 decay start IS the hit sync, by construction.
    `include_stinger=False` (a chapter card took this boundary's stinger,
    Story 5.17 AC:7) skips trauma entirely: the hit sounds during the card, so
    a scene-side shake would be exactly the desynced thump this rule avoids.
    The chapter card itself is never shaken (`_compose_chapter_card` untouched
    — it's a text card).

    `cards_by_shot` (Story 8.3/8.11): resolved cast cards keyed by shot_id,
    covering every rendered shot in the scene (not just one representative
    shot). A shot absent from the mapping (or mapped to []) renders
    background-only.

    Story 8.11: the scene's shots are cut into clips timed to the narration
    sentences each shot was written for (`shot_timing.plan_shot_clips`)
    instead of Ken-Burnsing the first shot for the whole scene. A single-clip
    plan (nothing to cut — the common case) renders through the original
    one-pass path (`_render_scene_fast`, byte-identical to pre-8.11 output).
    A multi-clip plan renders each shot's silent clip (`_compose_shot_clip`)
    then concats + burns subtitles/audio/sound-design/post-fx once
    (`_assemble_scene_from_clips`).

    Returns (segment_path, effect_spec, cards_overlaid) — effect_spec is the
    first rendered clip's spec (the scene-level trace-metadata representative).
    """
    n = scene["scene_num"]
    shots = scene.get("shots") or []
    rendered_shots = [s for s in shots if s.get("image_path")]
    if not rendered_shots:  # defensive; _validate_scene_assets guarantees this upstream
        raise ValueError(f"scene {n}: no shot has a valid image_path")
    audio_path: str = scene["audio_path"]  # type: ignore[assignment]
    subtitle_path: str = scene["subtitle_path"]  # type: ignore[assignment]
    duration: float = scene["audio_duration"]  # type: ignore[assignment]  # validated positive upstream
    mood = scene.get("mood")
    seg_path = out_dir / f"seg_{n:03d}.mp4"
    cards_by_shot = cards_by_shot or {}

    plan = shot_timing.plan_shot_clips(
        rendered_shots, scene.get("word_timings") or [], scene.get("narration") or "",
        duration, min_shot_clip_sec=min_shot_clip_sec,
    )
    logger.info(
        "scene %d: %d shots -> %d clips (merged %d)",
        n, len(rendered_shots), len(plan), max(0, len(rendered_shots) - len(plan)),
    )

    # Story 11.3 AC:3: trauma only when the stinger hit actually plays at this
    # segment's t=0 (see docstring); applied to the first clip alone below.
    scene_trauma = (
        camera_path.TRAUMA_BY_MOOD[resolve_mood(mood)]
        if camera_noise_enabled and sound_design_enabled and include_stinger
        else 0.0
    )

    def _shake(shot: ShotData, clip_duration: float, k: int, trauma: float) -> str:
        if not camera_noise_enabled:
            return ""
        return _camera_shake_filter(shot.get("camera_movement"), clip_duration, k=k, trauma=trauma)

    async def _motion(shot: ShotData, clip_duration: float, k: int, trauma: float) -> MotionSource:
        return await build_motion_source(
            shot, clip_duration, k=k, trauma=trauma,
            motion_dir=out_dir / "motion",
            parallax_enabled=parallax_enabled,
            camera_shake=_shake(shot, clip_duration, k, trauma),
            renderer_counts=renderer_counts,
        )

    if len(plan) == 1:
        clip = plan[0]
        cards = cards_by_shot.get(clip.shot["shot_id"], [])
        motion = await _motion(clip.shot, duration, scene_index, scene_trauma)
        await _render_scene_fast(
            motion, duration, seg_path, n,
            cards=cards, mood=mood, audio_path=audio_path, subtitle_path=subtitle_path,
            sound_design_enabled=sound_design_enabled, post_fx_enabled=post_fx_enabled,
            include_stinger=include_stinger,
            composite_harmonization_tier=composite_harmonization_tier,
        )
        return seg_path, motion.spec, bool(cards)

    shots_dir = out_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    # Story 8.11 [review fix]: a retry whose plan drops a shot_id a prior
    # attempt rendered (merge threshold or timings changed) must not leave
    # that stale clip on disk forever (AC:8 — "overwrites... cleanly").
    for stale in shots_dir.glob(f"scene_{n:03d}_*.mp4"):
        stale.unlink()
    clip_paths: list[Path] = []
    specs: list[EffectSpec] = []
    any_cards = False
    for local_i, clip in enumerate(plan):
        cards = cards_by_shot.get(clip.shot["shot_id"], [])
        any_cards = any_cards or bool(cards)
        # [review fix] `scene_index * 100 + local_i` cancelled scene_index out of
        # the rotation whenever scene_index*100 % len(_DIRECTION_POOL) == 0 — true
        # for every scene since the pool has 10 entries, so every scene's Nth shot
        # always got the same fixed direction. _EFFECT_INDEX_STRIDE is prime (and
        # comfortably larger than any real per-scene shot count), so it can't
        # divide the pool size and cancel scene_index regardless of pool length.
        k = scene_index * _EFFECT_INDEX_STRIDE + local_i
        # first clip only: its local t=0 IS scene t=0, the stinger hit (AC:3)
        motion = await _motion(
            clip.shot, clip.duration, k, scene_trauma if local_i == 0 else 0.0,
        )
        specs.append(motion.spec)
        clip_path = shots_dir / f"scene_{n:03d}_{clip.shot['shot_id']}.mp4"
        await _compose_shot_clip(
            clip.shot, motion, clip.duration, clip_path,
            cards=cards, mood=mood,
            composite_harmonization_tier=composite_harmonization_tier,
        )
        clip_paths.append(clip_path)

    await _assemble_scene_from_clips(
        clip_paths, duration, seg_path,
        audio_path=audio_path, subtitle_path=subtitle_path, mood=mood,
        sound_design_enabled=sound_design_enabled, post_fx_enabled=post_fx_enabled,
        include_stinger=include_stinger,
    )
    return seg_path, specs[0], any_cards


def _card_hold_audio_input(mood: str | None, *, sound_design_enabled: bool) -> tuple[list[str], list[str]]:
    """Audio input args + optional volume filter for a card/hold segment. [Story 5.16 AC:3]

    Sound design on: the upcoming scene's mood ambient bed, looped, at
    AMBIENT_VOLUME — the boundary never drops to digital silence. Off: today's
    anullsrc silence, unchanged.
    """
    if not sound_design_enabled:
        return ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"], []
    ambient = MOOD_ASSET_PATHS[resolve_mood(mood)]["ambient"]
    return ["-stream_loop", "-1", "-i", str(ambient)], ["-af", f"volume={AMBIENT_VOLUME}"]


async def _compose_chapter_card(
    label: str,
    index: int,
    out_dir: Path,
    duration: float,
    *,
    kicker: str = "",
    mood: str | None = None,
    post_fx_enabled: bool = False,
    sound_design_enabled: bool = False,
) -> Path:
    """Render a black title-card segment: color bg + centered title/kicker
    drawtext + audio bed, fading in/out at its own edges.
    [Story 5.1 AC:2,5] [Story 5.16 AC:3,5] [Story 5.17 AC:4,5,7]

    `mood` grades the card to the *upcoming* scene's mood, applied before
    drawtext so the text isn't grained. [Story 7.2 AC:7,8] The same mood also
    picks the card's ambient audio bed, and — when sound design is on — its
    mood stinger: the card IS the boundary now (Story 5.16's dip-to-black,
    Story 5.17's stinger-on-entry), so it carries the boundary's full audio,
    not just the ambient bed.

    Matches _compose_scene's output contract (COMP_W x COMP_H, FPS, H.264/AAC,
    yuv420p, has an audio stream) so _join_with_fades can treat it as an
    ordinary segment — no join-engine changes needed.
    """
    card_path = out_dir / f"card_{index:03d}.mp4"
    label_file = out_dir / f"card_{index:03d}_label.txt"
    label_stripped = label.strip()
    label_clean = label_stripped.splitlines()[0].strip() if label_stripped else label_stripped
    label_file.write_text(label_clean, encoding="utf-8")
    font = _escape_subtitles_path(Path(_card_font()))
    title_textfile = _escape_subtitles_path(label_file)
    fade_out_start = max(0.0, duration - CARD_FADE_DURATION)
    post_frag = f"{build_post_filter(mood)}," if post_fx_enabled else ""

    kicker_frag = ""
    kicker_stripped = kicker.strip()
    kicker_clean = kicker_stripped.splitlines()[0].strip() if kicker_stripped else ""
    if kicker_clean:
        kicker_file = out_dir / f"card_{index:03d}_kicker.txt"
        kicker_file.write_text(kicker_clean, encoding="utf-8")
        kicker_textfile = _escape_subtitles_path(kicker_file)
        kicker_frag = (
            f",drawtext=fontfile='{font}':textfile='{kicker_textfile}':"
            f"fontcolor=white:fontsize={CARD_KICKER_FONT_SIZE}:x=(w-text_w)/2:y=(h-text_h)/2+60"
        )
    vf = (
        f"{post_frag}"
        f"drawtext=fontfile='{font}':textfile='{title_textfile}':"
        f"fontcolor=white:fontsize={CARD_FONT_SIZE}:x=(w-text_w)/2:y=(h-text_h)/2-40"
        f"{kicker_frag},"
        f"fade=t=in:st=0:d={CARD_FADE_DURATION},"
        f"fade=t=out:st={fade_out_start:.3f}:d={CARD_FADE_DURATION}"
    )

    if sound_design_enabled:
        # Ambient bed (5.16) + this boundary's mood stinger, one-shot from t=0
        # (Story 5.17 AC:7) — the following scene omits its own baked stinger
        # via include_stinger=False so the boundary gets exactly one hit.
        resolved_mood = resolve_mood(mood)
        ambient = MOOD_ASSET_PATHS[resolved_mood]["ambient"]
        stinger = MOOD_ASSET_PATHS[resolved_mood]["stinger"]
        # normalize=0 (matches sound_design.py's own final mix): amix's default
        # normalize=1 auto-attenuates by active-input count, which flattened the
        # stinger down to the ambient bed's level — no audible hit at all. Summing
        # at the configured volumes verbatim is what makes AC:7's "one hit at
        # card t=0" actually audible. [caught in Story 5.17 live validation]
        audio_fragment = (
            f"[1:a]volume={AMBIENT_VOLUME}[amb_v];"
            f"[2:a]volume={STINGER_VOLUME},apad=whole_dur={duration}[stg_v];"
            f"[amb_v][stg_v]amix=inputs=2:duration=first:normalize=0[aout]"
        )
        rc, stderr = await _run_ffmpeg(
            "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={COMP_W}x{COMP_H}:r={FPS}:d={duration}",
            "-stream_loop", "-1", "-i", str(ambient),
            "-i", str(stinger),
            "-filter_complex", f"[0:v]{vf}[vout];{audio_fragment}",
            "-map", "[vout]", "-map", "[aout]",
            "-t", f"{duration:.3f}",
            *_OUTPUT_ARGS,
            str(card_path),
        )
    else:
        audio_input, _ = _card_hold_audio_input(mood, sound_design_enabled=False)
        rc, stderr = await _run_ffmpeg(
            "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={COMP_W}x{COMP_H}:r={FPS}:d={duration}",
            *audio_input,
            "-vf", vf,
            # Explicit -map: without it, a real ambient .mp3 (unlike anullsrc) could
            # carry an embedded cover-art video stream that hijacks ffmpeg's default
            # video-stream auto-selection away from the color background.
            "-map", "0:v", "-map", "1:a",
            "-t", f"{duration:.3f}",
            *_OUTPUT_ARGS,
            str(card_path),
        )
    if rc != 0:
        raise RuntimeError(f"FFmpeg chapter card {index} failed (rc={rc}): {stderr[-500:]}")
    if not card_path.exists():
        raise RuntimeError(f"FFmpeg chapter card {index}: output not created: {card_path}")
    return card_path


async def _compose_ending_credit(
    scp_id: str,
    out_dir: Path,
    *,
    mood: str | None = None,
    post_fx_enabled: bool = False,
    sound_design_enabled: bool = False,
) -> Path:
    """Render the CC BY-SA attribution ending card. [Story 5.20 AC:2]

    Thin wrapper over _compose_chapter_card — same renderer, distinct output
    filename (credit_ending.mp4, never card_NNN.mp4) so it can never collide
    with a chapter card. Raises on failure, same as _compose_chapter_card;
    video_node's caller decides how to log/report it (AC:5 non-fatal handling
    needs the run_id, which this function has no reason to know).
    """
    slug = _scp_wiki_slug(scp_id)
    label = f"Based on '{scp_id}' from the SCP Foundation Wiki"
    kicker = f"CC BY-SA 3.0 — scp-wiki.wikidot.com/{slug}"
    card_path = await _compose_chapter_card(
        label, 0, out_dir, MAX_CARD_DURATION,
        kicker=kicker, mood=mood, post_fx_enabled=post_fx_enabled,
        sound_design_enabled=sound_design_enabled,
    )
    ending_path = out_dir / "credit_ending.mp4"
    card_path.replace(ending_path)
    return ending_path


async def _compose_black_hold(
    out_dir: Path,
    index: int,
    *,
    mood: str | None = None,
    sound_design_enabled: bool = False,
) -> Path:
    """Render a pure-black hold segment for a card-less scene boundary dip.
    [Story 5.16 AC:1,3,5]

    No drawtext, no self-fades — it sits between two segments that already
    fade to/from black at their own edges. Carries the incoming scene's mood
    ambient bed when sound design is on (same recipe as the card); anullsrc
    otherwise. Mood-independent (silent) holds share one file per run; mood-
    bearing holds render per boundary since adjacent boundaries may announce
    different moods.
    """
    hold_path = out_dir / (
        f"hold_{index:03d}.mp4" if sound_design_enabled else "hold_shared.mp4"
    )
    if hold_path.exists():
        return hold_path
    audio_input, audio_filter_args = _card_hold_audio_input(
        mood, sound_design_enabled=sound_design_enabled,
    )
    # Render to a tmp path and rename into place atomically: a crash mid-render
    # must never leave a truncated file at hold_path for the exists() cache
    # check above to pick up on a retried/resumed run.
    tmp_path = hold_path.with_suffix(".tmp.mp4")
    rc, stderr = await _run_ffmpeg(
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={COMP_W}x{COMP_H}:r={FPS}:d={BLACK_HOLD_DURATION}",
        *audio_input,
        *audio_filter_args,
        "-map", "0:v", "-map", "1:a",
        "-t", f"{BLACK_HOLD_DURATION:.3f}",
        *_OUTPUT_ARGS,
        str(tmp_path),
    )
    if rc != 0:
        raise RuntimeError(f"FFmpeg black hold {index} failed (rc={rc}): {stderr[-500:]}")
    if not tmp_path.exists():
        raise RuntimeError(f"FFmpeg black hold {index}: output not created: {tmp_path}")
    tmp_path.replace(hold_path)
    return hold_path


async def _join_with_fades(
    segments: list[tuple[Path, float, float, float]],
    output: Path,
) -> None:
    """Join segments with in-place fades + concat — no overlap. [Story 5.16 AC:1,2,6]

    segments: list of (path, duration_seconds, fade_in_sec, fade_out_sec).
    Fades are computed by the caller (video_node): 0.0 for cards/holds (already
    black, or self-fading), 0.0 fade-in on the first segment and 0.0 fade-out
    on the last (no fade into/out of nothing).

    Each segment fades to/from black over its OWN first/last frames — no frame
    ever blends two segments' images, and no segment content is trimmed or
    consumed by a shared transition window (replaces xfade's offset
    accounting, the #1 source of its timing bugs). Audio passes through
    untouched via plain concat: no acrossfade, no adelay/amix, no gain
    manipulation anywhere — narration plays to its last sample before the
    boundary (Story 5.9's no-volume-dip guarantee now holds by construction,
    since there is no overlap window at all).
    """
    n = len(segments)
    assert n >= 2

    v_parts: list[str] = []
    concat_labels: list[str] = []
    for i, (_, dur, fade_in, fade_out) in enumerate(segments):
        # Clamp fade_out against the remaining duration after fade_in (not just
        # against dur) so a segment shorter than fade_in+fade_out can't get
        # overlapping fade-in/fade-out windows on its own frames.
        fade_in = min(fade_in, dur)
        fade_out = min(fade_out, dur - fade_in)
        fades = []
        if fade_in:
            fades.append(f"fade=t=in:st=0:d={fade_in:.3f}")
        if fade_out:
            fades.append(f"fade=t=out:st={dur - fade_out:.3f}:d={fade_out:.3f}")
        if fades:
            v_label = f"[v{i}]"
            v_parts.append(f"[{i}:v]{','.join(fades)}{v_label}")
            concat_labels.append(v_label)
        else:
            concat_labels.append(f"[{i}:v]")
        concat_labels.append(f"[{i}:a]")

    filter_complex = "; ".join(
        [*v_parts, "".join(concat_labels) + f"concat=n={n}:v=1:a=1[vout][aout]"]
    )

    input_args: list[str] = []
    for path, _, _, _ in segments:
        input_args += ["-i", str(path)]

    rc, stderr = await _run_ffmpeg(
        "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        str(output),
    )
    if rc != 0:
        raise RuntimeError(f"FFmpeg fade join failed (rc={rc}): {stderr[-500:]}")
    if not output.exists():
        raise RuntimeError(f"FFmpeg fade join: output not created: {output}")



# ── Node ──────────────────────────────────────────────────────────────────────


@observe(name="video")
async def video_node(state: PipelineState) -> dict:
    run_id = state.get("run_id", "?")
    t0 = time.perf_counter()
    try:
        if not shutil.which("ffmpeg"):
            raise EnvironmentError("ffmpeg not found in PATH; install ffmpeg to use video_node")

        scenes = sorted(state.get("scenes", []), key=lambda sc: sc["scene_num"])
        if not scenes:  # explicit guard — don't rely on the join assert (stripped under -O)
            raise ValueError("no scenes to render")
        s = _settings()
        scp_id = state.get("scp_id", "")
        _validate_scene_assets(
            scenes, sound_design_enabled=s.sound_design_enabled, min_shot_clip_sec=s.min_shot_clip_sec,
        )

        # ── Story 8.3: cast card resolution (replaces 1.13's angle override) ─
        # Story 11.5 AC:10 — run-level renderer tally, filled per shot by
        # build_motion_source and reported in the trace below.
        renderer_counts: dict[str, int] = {}
        cast_cards: dict[str, list[dict]] = {}
        cast_meta: dict = {}
        if _cast_resolver is not None:
            t_cast = time.perf_counter()
            try:
                cast_cards = await _cast_resolver(scp_id, scenes) or {}
                total_cards = sum(len(v) for v in cast_cards.values())
                fallback_used = sum(1 for v in cast_cards.values() for c in v if c.get("fallback"))
                cast_meta = {
                    "scp_id": scp_id,
                    "shots_with_cards": len(cast_cards),
                    "total_cards": total_cards,
                    "fallback_used": fallback_used,
                    "latency_ms": int((time.perf_counter() - t_cast) * 1000),
                }
                logger.info(
                    "Cast resolution: %d shots, %d cards in %dms",
                    len(cast_cards), total_cards, cast_meta["latency_ms"],
                )
            except Exception as exc:  # noqa: BLE001 — AD-10: resolver/LLM failures degrade, never fail the run
                logger.warning("Cast resolution failed, continuing background-only: %s", exc)
                cast_cards = {}

        # AC:10 — hard alpha validation, after resolution (can't live in
        # _validate_scene_assets, which runs before the resolver). Asset
        # contract failures fail the stage loudly (unlike the AD-10 catch above).
        seen_cards: dict[str, dict] = {}
        for card_list in cast_cards.values():
            for card in card_list:
                if not isinstance(card, dict) or not card.get("path"):
                    logger.warning("Cast resolver returned malformed card, skipping: %r", card)
                    continue
                seen_cards.setdefault(card["path"], card)
        for path, card in seen_cards.items():
            if not has_alpha(Path(path).read_bytes()):
                raise ValueError(
                    f"card {card['card_key']!r} angle {card['angle']!r} at {path} is opaque "
                    "(not an RGBA sprite) — regenerate via Story 8.2's sprite pipeline"
                )

        # ── Story 8.16: depth-aware ground plane per (shot, card) ──────────
        # After alpha validation (the cards are known-good sprites by here) and
        # before Tier 3, whose relit sprites inherit the same placement keys.
        if _ground_resolver is not None and cast_cards:
            try:
                cast_cards = _merge_placements(
                    cast_cards, await _ground_resolver(scenes, cast_cards) or {},
                )
            except Exception as exc:  # noqa: BLE001 — AD-10: degrades to the frame-centre anchor
                logger.warning("Depth-aware placement failed, keeping centre anchor: %s", exc)

        # ── Story 10.1c: shot recompose ───────────────────────────────────
        # Regenerate each shot from its plate + cards + a placement instruction, then
        # composite NOTHING: the returned frame already contains the characters, so the
        # shot renders through the background-only path and the motion stage animates one
        # image. This replaces the overlay, so everything below that exists to make a
        # pasted card look attached — ground placement, occlusion, contact shadow,
        # harmonization tiers, 11.5 layer parallax — is bypassed for recomposed shots by
        # construction, not by flag checks.
        # getattr, not attribute access: Settings stubs in tests are SimpleNamespaces built
        # per test, so a hard reference makes every unrelated video test fail on a field they
        # never opted into. Absent == off, which is also the production default.
        if getattr(s, "shot_recompose_enabled", False) and _recompose_resolver is not None and cast_cards:
            try:
                cast_cards, recompose_stats = await _recompose_resolver(scenes, cast_cards)
                logger.info("Shot recompose: %s", recompose_stats)
            except Exception as exc:  # noqa: BLE001 — AD-10: falls back to the overlay path
                logger.warning("Shot recompose failed, keeping the overlay path: %s", exc)

        # ── Story 8.7 Tier 3: IC-Light relight precomputation ─────────────
        relit_map: dict[tuple[str, str], Path] = {}
        relight_stats = {"computed": 0, "failed": 0}
        card_variant = None
        if s.composite_harmonization_tier >= 3 and _relight_resolver is not None:
            # Lazy, like the tier 1/2 builders below — this module stays
            # import-safe at tier 0.
            from yt_flow.pipeline.nodes.composite_harmonization import card_variant
            try:
                relit_map, relight_stats = await _relight_resolver(scenes, cast_cards)
            except Exception as exc:  # noqa: BLE001 — AD-10/AC:11: IC-Light never fails the run
                logger.warning("Tier 3 relight precompute failed, continuing without: %s", exc)
                relit_map, relight_stats = {}, {"computed": 0, "failed": 0}

        # ── Story 1.9/1.9b: FFmpeg composition ────────────────────────────

        run_dir = Path(s.workspace_path) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Chapter cards (Story 5.1): only meaningful with 2+ scenes to join. Computed
        # up front (Story 5.17 AC:7) so _compose_scene knows whether to suppress its
        # own scene-entry stinger for scenes immediately following a card.
        chapter_cards_enabled = bool(s.chapter_cards) and len(scenes) >= 2

        segs_with_specs: list[tuple[Path, float, EffectSpec, bool]] = []
        card_counts: list[int] = []
        rendered_cards: list[dict] = []
        total_shots_rendered = 0
        total_clips_kept = 0
        for i, scene in enumerate(scenes):
            # Story 8.11: every rendered shot gets its own clip now, so cards
            # are resolved per shot (not just for one representative shot).
            rendered_shots_for_scene = [sh for sh in scene.get("shots") or [] if sh.get("image_path")]
            cards_by_shot: dict[str, list[dict]] = {}
            for sh in rendered_shots_for_scene:
                shot_key = f"{scene['scene_num']}:{sh['shot_id']}"
                shot_cards = [
                    card for card in cast_cards.get(shot_key, [])
                    if isinstance(card, dict) and card.get("path")
                ]
                # Tier 3 (Story 8.7 AC:10): substitute the re-lit sprite for a
                # (card variant, location) pair before composition — never inside
                # _compose_scene, so the composition loop makes no ComfyUI calls.
                # Each shot substitutes using its OWN location_key (Story 8.11).
                # The key is the card *variant* (key+pose+angle), not card_key:
                # keying on card_key alone handed a shot whichever pose was
                # precomputed first and silently swapped the pose (Story 10.1b).
                location_key = sh.get("location_key")
                if relit_map and location_key:
                    relit_shot_cards = []
                    for card in shot_cards:
                        try:
                            variant = card_variant(card)
                        except (ValueError, TypeError, AttributeError):
                            relit_shot_cards.append(card)
                            continue
                        relit_path = relit_map.get((variant, location_key))
                        if relit_path is None:
                            relit_shot_cards.append(card)
                            continue
                        try:
                            if has_alpha(Path(relit_path).read_bytes()):
                                relit_shot_cards.append({**card, "path": str(relit_path)})
                            else:
                                logger.warning("Relit sprite has no alpha; using original card: %s", relit_path)
                                relit_shot_cards.append(card)
                        except OSError as exc:
                            logger.warning("Relit sprite unreadable; using original card %s: %s", relit_path, exc)
                            relit_shot_cards.append(card)
                    shot_cards = relit_shot_cards
                cards_by_shot[sh["shot_id"]] = shot_cards

            seg_path, spec, has_char = await _compose_scene(
                scene, i, run_dir,
                cards_by_shot=cards_by_shot,
                sound_design_enabled=s.sound_design_enabled,
                post_fx_enabled=s.post_fx_enabled,
                parallax_enabled=s.parallax_enabled,
                composite_harmonization_tier=s.composite_harmonization_tier,
                include_stinger=not (chapter_cards_enabled and i > 0),
                min_shot_clip_sec=s.min_shot_clip_sec,
                camera_noise_enabled=s.camera_noise_enabled,
                renderer_counts=renderer_counts,
            )
            duration: float = scene["audio_duration"]  # type: ignore[assignment]  # validated positive
            # [review fix] Scope card/motion metrics to the shots that actually
            # survived the clip plan — shot_timing.plan_shot_clips may merge a
            # shot's window away, and its cards are never composited. Recomputes
            # the same pure plan `_compose_scene` already built internally (no
            # I/O, can't drift from it) rather than reporting every image-bearing
            # shot's cards regardless of whether that shot rendered.
            plan = shot_timing.plan_shot_clips(
                rendered_shots_for_scene, scene.get("word_timings") or [], scene.get("narration") or "",
                duration, min_shot_clip_sec=s.min_shot_clip_sec,
            )
            kept_shot_ids = {clip.shot["shot_id"] for clip in plan}
            scene_cards = [
                card for shot_id, shot_cards in cards_by_shot.items()
                if shot_id in kept_shot_ids for card in shot_cards
            ]
            card_counts.append(len(scene_cards))
            rendered_cards.extend(scene_cards)
            total_shots_rendered += len(rendered_shots_for_scene)
            total_clips_kept += len(plan)
            segs_with_specs.append((seg_path, duration, spec, has_char))

        # AC:10 — run-level rollup of the per-scene "shots -> clips (merged)"
        # log lines, for live-verification without hand-summing scene entries.
        logger.info(
            "video_node: %d shots rendered / %d merged / %d scenes",
            total_shots_rendered, max(0, total_shots_rendered - total_clips_kept), len(scenes),
        )

        output = run_dir / "video.mp4"
        segs = [p for p, _, _, _ in segs_with_specs]

        card_duration = _chapter_card_duration(s.chapter_card_duration_sec)
        card_count = 0

        # CC BY-SA attribution (Story 5.20): compute up front so both the single-
        # and multi-scene join paths know whether to append it as the true last
        # segment. Composition failure is non-fatal (AC:5) — the run's own
        # try/except records the message, ending_credit_path stays None, and the
        # join proceeds without it.
        cc_attribution = s.cc_attribution
        ending_credit_path: Path | None = None
        ending_credit_error: str | None = None
        if cc_attribution:
            try:
                ending_credit_path = await _compose_ending_credit(
                    scp_id, run_dir, mood=scenes[-1].get("mood"),
                    post_fx_enabled=s.post_fx_enabled,
                    sound_design_enabled=s.sound_design_enabled,
                )
            except Exception as exc:  # noqa: BLE001 — AD-10: attribution never fails the run
                logger.warning("Ending credit card failed for run %s: %s", run_id, exc)
                ending_credit_error = str(exc)

        if len(segs) == 1:
            if ending_credit_path is not None:
                await _join_with_fades(
                    [
                        (segs[0], segs_with_specs[0][1], 0.0, FADE_DURATION),
                        (ending_credit_path, MAX_CARD_DURATION, 0.0, 0.0),
                    ],
                    output,
                )
            else:
                segs[0].replace(output)  # replace: atomic overwrite, cross-platform
        else:  # 2+ scenes: dip-to-black fade+concat join (Story 5.16)
            last_idx = len(segs_with_specs) - 1
            join_segments: list[tuple[Path, float, float, float]] = []
            for i, (seg_path, duration, _, _) in enumerate(segs_with_specs):
                fade_in = 0.0 if i == 0 else FADE_DURATION
                # The true final segment gets no fade-out (nothing follows it) —
                # UNLESS the ending credit card is appended after it, in which
                # case it must dip to black like any other internal boundary.
                is_true_end = i == last_idx and ending_credit_path is None
                fade_out = 0.0 if is_true_end else FADE_DURATION
                join_segments.append((seg_path, duration, fade_in, fade_out))
                if i == last_idx:
                    continue
                upcoming_mood = scenes[i + 1].get("mood")
                if chapter_cards_enabled:
                    # Card boundaries produce no double dip (AC:5) — the card
                    # IS the dip, self-fading internally; it gets 0.0 join-fades.
                    next_scene = scenes[i + 1]
                    label = _card_label(next_scene)
                    # AC:8 — the "- N -" fallback carries no kicker line, even if a
                    # kicker exists without a title (partial checkpoint/LLM omission).
                    has_title = bool(str(next_scene.get("title") or "").strip())
                    kicker = (next_scene.get("kicker") or "") if has_title else ""
                    card_path = await _compose_chapter_card(
                        label, i + 1, run_dir, card_duration,
                        kicker=kicker, mood=upcoming_mood, post_fx_enabled=s.post_fx_enabled,
                        sound_design_enabled=s.sound_design_enabled,
                    )
                    join_segments.append((card_path, card_duration, 0.0, 0.0))
                    card_count += 1
                else:
                    hold_path = await _compose_black_hold(
                        run_dir, i + 1, mood=upcoming_mood,
                        sound_design_enabled=s.sound_design_enabled,
                    )
                    join_segments.append((hold_path, BLACK_HOLD_DURATION, 0.0, 0.0))
            if ending_credit_path is not None:
                # Self-fading, same contract as a chapter card (AC:2). Its actual
                # rendered length is always MAX_CARD_DURATION (_compose_ending_credit
                # never uses the configured card_duration), so the join must declare
                # the same value it was rendered at.
                join_segments.append((ending_credit_path, MAX_CARD_DURATION, 0.0, 0.0))
            await _join_with_fades(join_segments, output)

        if cc_attribution:
            await _write_description_artifact(run_dir, scp_id)

        effects_meta = [
            {
                "scene_num": scenes[i]["scene_num"],
                "direction": spec.direction,
                "start_zoom": spec.start_zoom,
                "end_zoom": spec.end_zoom,
                "character_overlay": has_char,
            }
            for i, (_, _, spec, has_char) in enumerate(segs_with_specs)
        ]

        # Scoped to `rendered_cards` (the shots that survived each scene's clip
        # plan, the same set `_compose_scene` actually drew), not every shot key
        # in `cast_cards` — matches `card_counts`'s scoping so the metric never
        # reports a style that never appeared on screen.
        motion_style_counts = dict(Counter(
            card.get("motion_style", "breath") for card in rendered_cards
        ))
        movement_mode_counts = dict(Counter(
            card.get("movement_mode", "anchored") for card in rendered_cards
        ))
        movement_pace_counts = dict(Counter(
            card.get("movement_pace", "slow") for card in rendered_cards
        ))

        _record_trace(
            run_id=run_id, scene_count=len(scenes),
            latency_ms=_ms(t0), output_path=str(output),
            returncode=0, effects=effects_meta, upscale_pass=True,
            card_counts=card_counts,
            motion_style_counts=motion_style_counts,
            movement_mode_counts=movement_mode_counts,
            movement_pace_counts=movement_pace_counts,
            cast_resolution=cast_meta if cast_meta else None,
            chapter_cards_enabled=chapter_cards_enabled,
            chapter_card_duration=card_duration,
            chapter_card_count=card_count,
            ending_credit=ending_credit_path is not None,
            ending_credit_error=ending_credit_error,
            composite_harmonization_tier=s.composite_harmonization_tier,
            relit_pairs_computed=relight_stats["computed"],
            relit_pairs_failed=relight_stats["failed"],
            camera_noise_enabled=s.camera_noise_enabled,
            renderer_counts=renderer_counts,
            parallax_25d_enabled=s.parallax_25d_enabled,
            displacement_frac=camera_path.clamp_displacement(s.parallax_displacement_frac),
        )
        if renderer_counts:
            logger.info("video_node 2.5D renderers: %s", renderer_counts)
        result = {"current_stage": "video", "video_path": str(output), "error": None}
        if cc_attribution:
            result["ending_credit_error"] = ending_credit_error
        return result

    except Exception as exc:  # noqa: BLE001
        _record_trace(
            run_id=run_id, scene_count=len(state.get("scenes", [])),
            latency_ms=_ms(t0), error=exc,
        )
        return {"current_stage": "video", "error": f"stage=video run_id={run_id}: {exc}"}
