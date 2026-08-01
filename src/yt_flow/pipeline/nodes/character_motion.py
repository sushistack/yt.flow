"""Character micro-motion technique table (Story 8.8).

Generalizes Story 1.9c/7.3/8.3's fixed sway/bob idle overlay into a small
closed vocabulary (``motion_style`` x ``motion_energy``) the LLM selects per
cast member, rendered as deterministic FFmpeg expressions. Pure functions and
data only — no I/O, no LangGraph state — consumed by video.py's overlay/scale
filter builders.

Layer rule: domain only, no service/db/api imports. [AD-1]
"""

from typing import NamedTuple

from yt_flow.domain.state import CharacterMotionEnergy, CharacterMotionStyle
from yt_flow.pipeline.nodes.camera_path import fbm_expr

# Bump when any amplitude/frequency constant below changes — recorded in
# Langfuse trace metadata (AC:10) so a live render's "why did this look
# different" question can be answered without redeploying.
# "2": Story 11.3 — tremble's tremor sines became 2-octave fBm at the
# physiological 8-12Hz band (freq unit changed rad/s → steps/s there).
MOTION_TABLE_VERSION = "2"


class MotionTerm(NamedTuple):
    axis: str            # "x" | "y" | "scale"
    amp: float           # px (x/y) or fractional scale delta (scale)
    freq: float           # rad/s — EXCEPT lattice steps/s when quantized or octaves>0
    quantized: bool = False  # glitch: deterministic staircase, not a smooth sine
    octaves: int = 0     # >0: interpolated value-noise fBm (Story 11.3), 0: legacy sine


_ENERGY_MULT: dict[CharacterMotionEnergy, float] = {"low": 0.6, "medium": 1.0, "high": 1.5}

# Sway/bob keep Story 1.9c's original tuning — "sway" + "medium" (the table's
# 1.0 multiplier) reproduces the exact pre-8.8 idle motion byte-for-byte.
SWAY_AMPLITUDE = 12.0  # px, x-axis idle drift
SWAY_FREQ = 0.8        # rad/s
BOB_AMPLITUDE = 8.0    # px, y-axis breathing/bob
BOB_FREQ = 1.2         # rad/s

# ponytail: eyeball-tuned like SWAY/BOB above, not derived from anything;
# live-verified in Task 5.
BREATH_SCALE_AMP = 0.015    # ~1.5% squash/stretch — barely-perceptible "alive" cue
BREATH_SCALE_FREQ = BOB_FREQ  # rides the same breathing rhythm as the bob sine
TREMBLE_AMP = 3.0            # px — small on purpose (AC:6 caps so subtitles never occlude)
# Story 11.3: tremble's shake is 2-octave fBm in the 8-12Hz physiological
# tremor band (Gavant IEEE) — freq is lattice steps/s (GLITCH_STEP_FREQ's
# unit), no longer rad/s; the pre-11.3 value was a 6.0 rad/s (~0.95Hz) sine,
# spectrally wrong for tremor. Total amplitude stays 3.0px: fbm_expr is
# bounded to ±amp exactly like a sine, so max_excursion() and video.py's
# CHAR_MAX_W/H are numerically unchanged.
TREMBLE_FREQ = 10.0          # lattice steps/s
TREMBLE_OCTAVES = 2
PULSE_SCALE_AMP = 0.05       # 5% scale pulse — noticeable, not a "breathing balloon" (AC:6)
PULSE_SCALE_FREQ = 0.6       # rad/s — low frequency (AC:6)
GLITCH_JITTER_PX = 5.0       # quantized jitter amplitude
GLITCH_STEP_FREQ = 4.0       # discrete steps/s

# One source of truth for both the FFmpeg expression builders below and the
# off-frame excursion math in video.py — never duplicate these numbers.
# Additive: "tremble" = breath's slow bob + its own high-frequency shake, not
# a replacement, per Interfaces ("tremble: breath + high-frequency ... shake").
_STYLE_TERMS: dict[CharacterMotionStyle, tuple[MotionTerm, ...]] = {
    "hold": (),
    "breath": (
        MotionTerm("y", BOB_AMPLITUDE, BOB_FREQ),
        MotionTerm("scale", BREATH_SCALE_AMP, BREATH_SCALE_FREQ),
    ),
    "sway": (
        MotionTerm("x", SWAY_AMPLITUDE, SWAY_FREQ),
        MotionTerm("y", BOB_AMPLITUDE, BOB_FREQ),
        MotionTerm("scale", BREATH_SCALE_AMP, BREATH_SCALE_FREQ),
    ),
    "tremble": (
        MotionTerm("y", BOB_AMPLITUDE, BOB_FREQ),
        MotionTerm("scale", BREATH_SCALE_AMP, BREATH_SCALE_FREQ),
        MotionTerm("x", TREMBLE_AMP, TREMBLE_FREQ, octaves=TREMBLE_OCTAVES),
        MotionTerm("y", TREMBLE_AMP, TREMBLE_FREQ, octaves=TREMBLE_OCTAVES),
    ),
    "pulse": (
        MotionTerm("scale", PULSE_SCALE_AMP, PULSE_SCALE_FREQ),
    ),
    "glitch": (
        MotionTerm("x", GLITCH_JITTER_PX, GLITCH_STEP_FREQ, quantized=True),
        MotionTerm("y", GLITCH_JITTER_PX, GLITCH_STEP_FREQ, quantized=True),
    ),
}


def _term_expr(term: MotionTerm, mult: float, phase: float, t_var: str) -> str:
    amp = term.amp * mult
    if term.octaves:
        # Story 11.3: interpolated value-noise fBm (camera_path owns the
        # primitive); phase doubles as the lattice offset, and the same
        # 12.9898/78.233 axis split as the quantized branch below keeps x/y
        # decorrelated. Bounded to ±amp, like the sine it replaced.
        hash_mult = 12.9898 if term.axis == "x" else 78.233
        return fbm_expr(amp, term.freq, term.octaves, phase, t_var=t_var, hash_mult=hash_mult)
    if term.quantized:
        # Deterministic "random-looking" hash: a classic shader hash constant
        # (sin(x*12.9898) decorrelates a step index into [-1,1]) applied to a
        # floor()'d step counter — a staircase, not a continuous sine, and
        # fully deterministic (no ffmpeg random() filter state). Different
        # multiplier per axis so x/y don't jitter in lockstep.
        step = f"floor({t_var}*{term.freq}+{phase})"
        hash_mult = 12.9898 if term.axis == "x" else 78.233
        return f"sin({step}*{hash_mult})*{amp}"
    return f"sin({t_var}*{term.freq}+{phase})*{amp}"


def axis_terms(
    style: CharacterMotionStyle,
    energy: CharacterMotionEnergy,
    axis: str,
    phase: float,
    *,
    t_var: str = "t",
) -> list[str]:
    """FFmpeg sub-expressions contributing to one axis for a style/energy pair.

    Callers join with ``" + "``; an empty list means the axis is untouched
    (e.g. every axis for ``hold``, x/y for ``pulse``).

    An out-of-vocab ``style``/``energy`` degrades to ``"breath"``/``"medium"``
    rather than raising — Epic 8's taxonomy-violation-degrades rule (AD-10)
    applies here too, not just in ``parse_cast``, since a resolved card can
    reach this function without passing back through the parser (e.g. a
    checkpoint written by a different code version).
    """
    mult = _ENERGY_MULT.get(energy, _ENERGY_MULT["medium"])
    terms = _STYLE_TERMS.get(style, _STYLE_TERMS["breath"])
    return [_term_expr(t, mult, phase, t_var) for t in terms if t.axis == axis]


def max_excursion() -> tuple[float, float, float]:
    """Worst-case ``(x_px, y_px, scale_factor)`` across every style/energy
    combination in the table above — the single source video.py's
    motion-safe box math (AC:7) reads from, so the off-frame guard can never
    drift out of sync with these constants.

    Same-axis terms are summed (worst case: both sines peak on the same
    frame); energy always uses ``"high"``, the loudest tier.
    """
    mult = _ENERGY_MULT["high"]
    max_x = max_y = 0.0
    max_scale = 1.0
    for terms in _STYLE_TERMS.values():
        x = sum(t.amp for t in terms if t.axis == "x") * mult
        y = sum(t.amp for t in terms if t.axis == "y") * mult
        scale = 1.0 + sum(t.amp for t in terms if t.axis == "scale") * mult
        max_x, max_y, max_scale = max(max_x, x), max(max_y, y), max(max_scale, scale)
    return max_x, max_y, max_scale
