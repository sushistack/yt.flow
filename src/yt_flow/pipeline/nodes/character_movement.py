"""Character locomotion / screen-blocking curve builder (Story 8.9).

Cinematic blocking for a static RGBA card — not a walk-cycle sim. Generalizes
8.3's fixed position/depth anchor into a small closed vocabulary
(``movement_mode`` x ``movement_direction`` x ``movement_pace``) the LLM
selects per cast member, rendered as deterministic FFmpeg expressions. Terms
returned here are ADDITIVE deltas layered on top of the 8.3 anchor, composed
before 7.3 parallax and 8.8 micro-motion (video.py's overlay chain order).

Pure functions and data only — no I/O, no LangGraph state — consumed by
video.py's overlay/scale filter builders. [AD-1]
"""

from typing import NamedTuple

MOVEMENT_TABLE_VERSION = "1"

# Mirrors video.py's own _POSITION_X_FRAC / _DEPTH_SCALE (Story 8.3/7.3) — kept
# as a small local copy rather than an import to keep this module import-free
# and independently testable; both tables are fixed rule-of-thirds/depth-plane
# constants that don't vary per-story, so drift risk is low and caught by
# test_video.py's cross-checks against these same values.
_POSITION_X_FRAC: dict[str, float] = {"left": 1 / 3, "center": 0.5, "right": 2 / 3}
_DEPTH_SCALE: dict[str, float] = {"near": 1.0, "mid": 0.75, "far": 0.55}

# One step further from camera than a given depth — the "shallower" plane
# approach/retreat interpolate against. far has nowhere shallower to go, so it
# clamps to itself (zero-amplitude movement, still safe/valid).
_SHALLOWER_DEPTH: dict[str, str] = {"near": "mid", "mid": "far", "far": "far"}

# Fraction of the segment duration spent actually transitioning; the
# remainder holds at the settled value. A "fast" blocking beat resolves
# quickly and holds, rather than crawling across the whole shot.
_PACE_FRACTION: dict[str, float] = {"slow": 1.0, "medium": 0.6, "fast": 0.35}

# Small bounded same-slot drift (Interfaces: "drift ... never crossing into
# another third"). The narrowest gap between adjacent thirds at 1920 width is
# main_w/6 == 320px — DRIFT_PX stays a fraction of that by construction.
DRIFT_PX = 40.0


class MovementCurve(NamedTuple):
    x_terms: list[str]
    y_terms: list[str]
    scale_terms: list[str]


def _ease_progress(t_var: str, duration: float, pace: str) -> str:
    """Clamped smoothstep progress in [0, 1] — reaches 1 at ``pace``'s
    fraction of ``duration`` and holds there for the remainder. [AC:6]

    ``smoothstep(s) = s*s*(3-2*s)`` is an actual ease-in/ease-out curve, not
    the plain ``t/duration`` linear ramp AC:6 explicitly guards against.
    """
    frac = _PACE_FRACTION.get(pace, _PACE_FRACTION["slow"])
    span = duration * frac
    if span <= 0:
        return "1"
    s = f"min({t_var}/{span},1)"
    return f"(({s})*({s})*(3-2*({s})))"


def build_movement_terms(
    *,
    mode: str,
    direction: str,
    pace: str,
    position: str,
    depth: str,
    duration: float,
    t_var: str = "t",
) -> MovementCurve:
    """Additive x/y/scale delta terms for one card's movement, over ``duration``
    seconds. [AC:5,7]

    ``anchored`` (and any unrecognized mode — AD-10 degrade) returns empty
    lists, so a caller that skips appending empty terms reproduces the pre-8.9
    filtergraph byte-for-byte (AC:10). Terms are deltas from the 8.3 anchor,
    not absolute positions — callers add these on top of the existing
    position-fraction/depth-scale anchor, same convention as 8.8's
    ``character_motion.axis_terms``.
    """
    if mode == "anchored" or duration <= 0:
        return MovementCurve([], [], [])

    ease = _ease_progress(t_var, duration, pace)

    if mode == "drift":
        return MovementCurve([f"{DRIFT_PX}*{ease}"], [], [])

    if mode in ("enter", "exit"):
        sign = -1.0 if direction == "left" else 1.0
        # enter: full offscreen offset at t=0, eases DOWN to 0 (settles at anchor).
        # exit: 0 at t=0 (starts at anchor), eases UP to the full offscreen offset.
        inv = f"(1-{ease})" if mode == "enter" else ease
        return MovementCurve([f"{sign}*main_w*{inv}"], [], [])

    if mode == "cross":
        end_frac = _POSITION_X_FRAC.get(position, _POSITION_X_FRAC["center"])
        start_frac = _POSITION_X_FRAC.get(direction, end_frac)
        delta_frac = start_frac - end_frac
        return MovementCurve([f"main_w*{delta_frac}*(1-{ease})"], [], [])

    if mode in ("approach", "retreat"):
        declared_scale = _DEPTH_SCALE.get(depth, _DEPTH_SCALE["mid"])
        shallow_scale = _DEPTH_SCALE.get(_SHALLOWER_DEPTH.get(depth, "far"), _DEPTH_SCALE["far"])
        ratio_delta = shallow_scale / declared_scale - 1.0  # always <= 0: shallower never scales up
        # approach: starts at the shallower ratio, eases to 0 (settles at declared depth).
        # retreat: starts at 0 (declared depth), eases to the shallower ratio.
        term = f"(1-{ease})" if mode == "approach" else ease
        return MovementCurve([], [], [f"{ratio_delta}*{term}"])

    return MovementCurve([], [], [])
