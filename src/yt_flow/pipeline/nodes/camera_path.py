"""Fractal-noise camera paths (Story 11.3).

Replaces the single-frequency "eyeball-tuned" sinusoid camera motion with a
research-grounded two-band fBm (fractional Brownian motion) model: low-
frequency postural sway (~99% of sway power sits under 2Hz, Gavant et al.
IEEE) plus a faint 8-12Hz physiological tremor band, 2-3 octaves at
persistence 0.5 so the spectrum carries the 1/f structure real handheld
footage has (AE ``wiggle(freq, amp, octaves)`` reference model). A game-dev
standard *trauma* scalar (0-1, time-decaying, amplitude = trauma²) drives
stinger-synchronized event shakes on top.

Same character as character_motion.py (Story 8.8): pure functions and data
only — no I/O, no LangGraph state — consumed by video.py's filter builders.
All noise is a closed-form deterministic ffmpeg expression in ``t``: value
noise (the shader-hash ``sin(i*12.9898)`` idiom character_motion's glitch
staircase already uses, extended with smoothstep interpolation) — never
frame-independent white noise, never ``random`` (resume runs in a different
process; 11-1's sha256-not-hash lesson).

Layer rule: domain + sibling leaf modules only, no service/db/api imports
[AD-1]. video.py and character_motion.py import this module; this module must
never import character_motion (that would be a cycle).
"""

import math
from typing import NamedTuple

from yt_flow.domain.state import CAMERA_ARCHETYPES
from yt_flow.pipeline.nodes.sound_design import MOOD_VALUES

# Bump when any profile/trauma constant below changes — recorded in Langfuse
# trace metadata (AC:7) so "why does this render look different" is answerable
# without redeploying (same rule as character_motion.MOTION_TABLE_VERSION).
CAMERA_PATH_VERSION = "1"

# Shader-hash multipliers (12.9898/78.233 idiom, cf. character_motion glitch):
# separate multipliers keep x and y channels from jittering in lockstep.
_HASH_X = 12.9898
_HASH_Y = 78.233

# Decorrelates octave j's lattice from octave j+1's (they'd otherwise share
# hash inputs wherever the doubled frequency lands on the same integer).
_OCTAVE_OFFSET = 19.19

# Per-shot lattice offset stride: shot k's curves start k*_K_STRIDE lattice
# steps away, so adjacent shots never ride the same noise curve (AC:2).
_K_STRIDE = 37.0

# Channel-distinct base offsets so x/y/rot/zoom (and the trauma channels)
# sample independent stretches of the hash lattice.
_CH_X, _CH_Y, _CH_ROT, _CH_ZOOM = 1.3, 9.7, 23.3, 31.1
_CH_TRAUMA_X, _CH_TRAUMA_Y, _CH_TRAUMA_ROT = 47.9, 59.3, 71.7


class NoiseProfile(NamedTuple):
    sway_amp: float      # low-frequency band amplitude, fraction of frame WIDTH
    sway_freq: float     # lattice steps/s (GLITCH_STEP_FREQ's unit, NOT rad/s)
    sway_octaves: int
    tremor_amp: float    # 8-12Hz physiological band, fraction of frame width
    tremor_freq: float   # lattice steps/s
    rot_deg: float       # peak rotation, degrees (≤1° per AE wiggle model)
    zoom_amp: float      # micro-zoom, fractional scale delta


# ponytail: live-tuning starting points inside the research bands (§4.1) —
# same iteration style as ZOOM_IN_MAX's 1.08→1.15 history; amplitudes are
# frame-width fractions. `locked` is all zero: a tripod is locked's reason to
# exist. push_in/pull_back/drift share the documentary band — their identity
# comes from the zoompan base move, the noise only de-mechanizes it.
_DOCU = NoiseProfile(0.005, 1.0, 2, 0.0008, 10.0, 0.15, 0.003)
_LOCKED = NoiseProfile(0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0)
_SHAKE = NoiseProfile(0.015, 1.5, 3, 0.002, 10.0, 0.8, 0.008)

CAMERA_NOISE_PROFILES: dict[str, NoiseProfile] = {
    "push_in": _DOCU,
    "pull_back": _DOCU,
    "drift": _DOCU,
    "locked": _LOCKED,
    "shake": _SHAKE,
}
# resolve/select fallbacks only guarantee archetype membership; keep keys in
# lockstep or a taxonomy change turns into a silent KeyError (7.2 invariant,
# scenario_chain.py precedent).
assert set(CAMERA_NOISE_PROFILES) == set(CAMERA_ARCHETYPES)

# ponytail: live-tuning starting points. trauma∈[0,1]; event amplitude =
# trauma² × the TRAUMA_MAX_* coefficients, decaying linearly over TRAUMA_TAU
# seconds — the game-dev standard event-shake model (research §4.1;
# rotational shake has the highest per-pixel impact).
TRAUMA_BY_MOOD: dict[str, float] = {
    "dread": 0.5,
    "clinical": 0.25,
    "escalation": 0.8,
    "revelation": 0.6,
}
assert set(TRAUMA_BY_MOOD) == set(MOOD_VALUES)

TRAUMA_TAU = 1.0           # s — linear decay ramp length
TRAUMA_MAX_XY = 0.02       # frame-width fraction at trauma=1
TRAUMA_MAX_ROT_DEG = 1.5   # degrees at trauma=1
TRAUMA_FREQ = 12.0         # lattice steps/s — impact shakes are fast
TRAUMA_OCTAVES = 2


def _octave_amps(amp: float, octaves: int) -> list[float]:
    """Persistence-0.5 octave amplitudes normalized so their sum == amp —
    the analytic excursion bound below is then exact by construction."""
    norm = amp / sum(0.5 ** j for j in range(octaves))
    return [norm * 0.5 ** j for j in range(octaves)]


def _value_noise_expr(p: str, hash_mult: float) -> str:
    """One octave of value noise in [-1, 1] at lattice position ``p`` (an
    ffmpeg sub-expression): hash the two neighboring lattice integers into
    [-1,1] via sin(i*mult), smoothstep-interpolate between them. C0-continuous
    in t, deterministic, no filter state."""
    i = f"floor({p})"
    u = f"({p}-floor({p}))"
    s = f"({u}*{u}*(3-2*{u}))"
    a = f"sin({i}*{hash_mult})"
    b = f"sin(({i}+1)*{hash_mult})"
    # ponytail: subexpressions are recomputed inline instead of st()/ld()
    # registers — C leaves +'s operand evaluation order unspecified in
    # ffmpeg's eval tree, so cross-operand ld() is a portability trap; a few
    # redundant floor()s per frame are free next to encoding.
    return f"({a}+({b}-{a})*{s})"


def fbm_expr(
    amp: float, lattice_freq: float, octaves: int, offset: float,
    t_var: str = "t", hash_mult: float = _HASH_X,
) -> str:
    """2-3 octave value-noise fBm as a deterministic ffmpeg expression in
    ``t_var``, bounded to [-amp, amp] (octave amplitudes are normalized to sum
    to ``amp``). Empty string when the band is silent — callers skip the term.
    """
    if amp == 0 or octaves <= 0 or lattice_freq == 0:
        return ""
    parts = []
    for j, a_j in enumerate(_octave_amps(amp, octaves)):
        f_j = lattice_freq * 2 ** j
        o_j = offset + j * _OCTAVE_OFFSET
        p = f"(({t_var})*{f_j:.6g}+{o_j:.6g})"
        parts.append(f"{_value_noise_expr(p, hash_mult)}*{a_j:.6g}")
    return "(" + "+".join(parts) + ")"


def noise_profile_for(hint: str | None) -> NoiseProfile:
    """Archetype → its profile; "static" → locked (select_effect's aliasing);
    None/legacy free text → documentary default. Mirrors select_effect's
    fallback philosophy: no camera_movement value can fail the stage, so a
    pre-11.2 checkpoint's video retry renders unchanged in spirit (AC:7)."""
    normalized = " ".join((hint or "").split()).lower()
    if normalized == "static":
        return _LOCKED
    return CAMERA_NOISE_PROFILES.get(normalized, _DOCU)


class CameraNoiseExprs(NamedTuple):
    x_expr: str     # crop-window x offset, fraction of frame WIDTH
    y_expr: str     # crop-window y offset, fraction of frame WIDTH
    rot_expr: str   # rotation angle, radians
    zoom_expr: str  # micro-zoom scale delta (may be "" — silent channel)
    margin: float   # required overscan margin fraction, see overscan_margin()


def _trauma_term(trauma: float, peak: float, offset: float, hash_mult: float, t_var: str) -> str:
    """Event-shake term: trauma(t) = trauma·(1-t/τ)+ so amplitude(t) =
    trauma(t)²·peak_coeff rides an fBm carrier. Peaks at trauma²·peak — the
    bound max_excursion() uses."""
    if trauma <= 0 or peak == 0:
        return ""
    carrier = fbm_expr(trauma * trauma * peak, TRAUMA_FREQ, TRAUMA_OCTAVES, offset, t_var, hash_mult)
    return f"pow(max(0,1-({t_var})/{TRAUMA_TAU:.6g}),2)*{carrier}"


def camera_noise_exprs(
    hint: str | None, k: int, *, trauma: float = 0.0, t_var: str = "t",
) -> CameraNoiseExprs | None:
    """The full x/y/rot/zoom noise bundle for one shot, or None when every
    channel is silent (locked/static profile with no trauma) — the caller then
    attaches no camera stage at all, keeping the chain byte-identical to
    pre-11.3 (AC:2).

    ``k`` is the shot's effect index (fast path: scene_index; multi-clip:
    scene_index*stride+local_i) reused as a lattice offset so adjacent shots
    decorrelate. ``trauma`` > 0 adds the decaying event shake to x/y/rot even
    on a locked profile — a stinger hit shakes a tripod too; the impact is the
    point, not the idle handheld texture.
    """
    p = noise_profile_for(hint)
    base = k * _K_STRIDE

    def channel(amp_sway: float, ch: float, ch_trauma: float, trauma_peak: float, hm: float) -> str:
        terms = [
            fbm_expr(amp_sway, p.sway_freq, p.sway_octaves, base + ch, t_var, hm),
            fbm_expr(p.tremor_amp, p.tremor_freq, 2, base + ch + 2.7, t_var, hm),
            _trauma_term(trauma, trauma_peak, base + ch_trauma, hm, t_var),
        ]
        return "+".join(t for t in terms if t)

    x = channel(p.sway_amp, _CH_X, _CH_TRAUMA_X, TRAUMA_MAX_XY, _HASH_X)
    y = channel(p.sway_amp, _CH_Y, _CH_TRAUMA_Y, TRAUMA_MAX_XY, _HASH_Y)
    rot = "+".join(t for t in (
        fbm_expr(math.radians(p.rot_deg), p.sway_freq, max(p.sway_octaves, 1) if p.rot_deg else 0,
                 base + _CH_ROT, t_var, _HASH_Y),
        _trauma_term(trauma, math.radians(TRAUMA_MAX_ROT_DEG), base + _CH_TRAUMA_ROT, _HASH_Y, t_var),
    ) if t)
    zoom = fbm_expr(p.zoom_amp, p.sway_freq, p.sway_octaves, base + _CH_ZOOM, t_var, _HASH_X)

    if not (x or y or rot or zoom):
        return None
    return CameraNoiseExprs(x, y, rot, zoom, overscan_margin(hint, trauma=trauma))


# ── Numeric trajectory sampler (Story 11.5 AC4) ──────────────────────────────
# Story 11.3 emits the model above as closed-form ffmpeg expressions in `t`.
# A 2.5D renderer needs the same curve as PER-FRAME NUMBERS, so the two share
# this module's constants and noise formula rather than growing a second,
# subtly-different noise implementation. `_fbm` below is `fbm_expr` evaluated;
# tests/pipeline/nodes/test_camera_path.py proves that literally, by eval()ing
# the generated expression string against the numeric sampler at representative
# timestamps (the strings are valid Python given sin/floor/pow/max/min).

# AC6: visible x/y displacement stays inside the 1-3% of frame WIDTH band that
# single-image depth displacement can hide disocclusion inside. Wider than 3%
# and the disoccluded edge behind a foreground object becomes a rubber smear;
# under 1% there is no readable depth cue at all.
DISPLACEMENT_MIN = 0.01
DISPLACEMENT_MAX = 0.03


def clamp_displacement(frac: float) -> float:
    """Config's requested peak displacement, forced into the AC6 band."""
    return min(max(frac, DISPLACEMENT_MIN), DISPLACEMENT_MAX)


class CameraSample(NamedTuple):
    """One frame of camera state. Renderer-independent by contract (AC4).

    ``x``/``y`` are offsets of the *visible content*, both as fractions of frame
    WIDTH (y shares the width unit because NoiseProfile's amplitudes do —
    ``_camera_shake_filter`` multiplies both by COMP_W for the same reason).
    Positive x moves content right, positive y moves content down. ``rot`` is
    radians, ``zoom`` a scale delta from 1.0.
    """
    t: float
    x: float
    y: float
    rot: float
    zoom: float


def _value_noise_num(p_val: float, hash_mult: float) -> float:
    """Numeric twin of :func:`_value_noise_expr` — same hash, same smoothstep."""
    i = math.floor(p_val)
    u = p_val - i
    s = u * u * (3 - 2 * u)
    a = math.sin(i * hash_mult)
    b = math.sin((i + 1) * hash_mult)
    return a + (b - a) * s


def _fbm(
    amp: float, lattice_freq: float, octaves: int, offset: float, t: float,
    hash_mult: float = _HASH_X,
) -> float:
    """Numeric twin of :func:`fbm_expr`, bounded to [-amp, amp]."""
    if amp == 0 or octaves <= 0 or lattice_freq == 0:
        return 0.0
    total = 0.0
    for j, a_j in enumerate(_octave_amps(amp, octaves)):
        # Round-trip through the same %.6g formatting fbm_expr emits, or the
        # numeric path and the expression path disagree in the 7th digit and the
        # parity test has to be loosened until it stops proving anything.
        f_j = float(f"{lattice_freq * 2 ** j:.6g}")
        o_j = float(f"{offset + j * _OCTAVE_OFFSET:.6g}")
        total += _value_noise_num(t * f_j + o_j, hash_mult) * float(f"{a_j:.6g}")
    return total


def _trauma_envelope(t: float) -> float:
    return max(0.0, 1 - t / TRAUMA_TAU) ** 2


def _trauma_value(trauma: float, peak: float, offset: float, hash_mult: float, t: float) -> float:
    """Numeric twin of :func:`_trauma_term`."""
    if trauma <= 0 or peak == 0:
        return 0.0
    carrier = _fbm(trauma * trauma * peak, TRAUMA_FREQ, TRAUMA_OCTAVES, offset, t, hash_mult)
    return _trauma_envelope(t) * carrier


def has_motion(hint: str | None, *, trauma: float = 0.0) -> bool:
    """False for a genuinely static camera — ``locked``/``static`` with no
    trauma. Mirrors :func:`camera_noise_exprs` returning None, so AC4's "locked
    with no trauma remains a no-motion path" is one predicate both renderers
    agree on instead of two independent guesses."""
    return camera_noise_exprs(hint, 0, trauma=trauma) is not None


def sample_path(
    hint: str | None,
    k: int,
    *,
    duration: float,
    fps: int,
    trauma: float = 0.0,
    xy_peak: float | None = None,
    base_zoom: tuple[float, float] = (1.0, 1.0),
    base_pan: tuple[float, float] = (0.0, 0.0),
) -> list[CameraSample]:
    """Per-frame camera samples for one shot — the same archetype/profile/``k``/
    trauma/duration model Story 11.3 emits as ffmpeg expressions (AC4).

    Deterministic and byte-stable across processes and retries: every value
    comes from ``sin``-hash value noise over ``(t, k, channel)``, never
    ``random`` and never the builtin ``hash()`` (PYTHONHASHSEED would resalt it
    on a resumed run — 11-1's lesson). Adjacent ``k`` decorrelate through
    ``_K_STRIDE``, exactly as the expression path does.

    ``base_zoom``/``base_pan`` carry the shot's Ken Burns *base move* — the
    push-in ramp and the directional pan — because AC7 requires the trajectory to
    own base movement, handheld noise and trauma **exactly once**. video.py
    derives them from its own ``EffectSpec``/``_PAN_SIGN`` vocabulary and passes
    them in; keeping that vocabulary out of here is what leaves this module
    renderer- and Ken-Burns-independent. ``base_pan`` is the TOTAL content
    displacement over the shot, in width fractions, reached linearly.

    ``xy_peak`` (AC6) rescales x and y — base pan and noise together — so their
    analytic worst case equals exactly that fraction of frame width. Capping the
    combined peak rather than each contributor is what makes the bound hold by
    construction instead of by hoping the two never peak together.
    """
    p = noise_profile_for(hint)
    base = k * _K_STRIDE
    frames = max(1, round(duration * fps))
    noise_xy, _, _ = max_excursion(hint, trauma=trauma)
    pan_x, pan_y = base_pan
    peak = max(abs(pan_x), abs(pan_y)) + noise_xy
    gain = 1.0 if (xy_peak is None or peak <= 0) else xy_peak / peak
    z0, z1 = base_zoom

    def channel(ch: float, ch_trauma: float, hm: float, t: float) -> float:
        return (
            _fbm(p.sway_amp, p.sway_freq, p.sway_octaves, base + ch, t, hm)
            + _fbm(p.tremor_amp, p.tremor_freq, 2, base + ch + 2.7, t, hm)
            + _trauma_value(trauma, TRAUMA_MAX_XY, base + ch_trauma, hm, t)
        )

    samples: list[CameraSample] = []
    for frame in range(frames):
        t = frame / fps
        prog = min(t * fps / frames, 1.0)
        x = (pan_x * prog + channel(_CH_X, _CH_TRAUMA_X, _HASH_X, t)) * gain
        y = (pan_y * prog + channel(_CH_Y, _CH_TRAUMA_Y, _HASH_Y, t)) * gain
        rot = _fbm(
            math.radians(p.rot_deg), p.sway_freq,
            max(p.sway_octaves, 1) if p.rot_deg else 0, base + _CH_ROT, t, _HASH_Y,
        ) + _trauma_value(
            trauma, math.radians(TRAUMA_MAX_ROT_DEG), base + _CH_TRAUMA_ROT, _HASH_Y, t,
        )
        zoom = (z0 + (z1 - z0) * prog) - 1.0 + _fbm(
            p.zoom_amp, p.sway_freq, p.sway_octaves, base + _CH_ZOOM, t, _HASH_X,
        )
        samples.append(CameraSample(t, x, y, rot, zoom))
    return samples


def xy_gain(
    hint: str | None, *, trauma: float, xy_peak: float | None,
    base_pan: tuple[float, float],
) -> float:
    """The rescale factor :func:`sample_path` applies to x and y.

    Exposed because the *card* layer terms (Story 11.5 AC7) are built as ffmpeg
    expressions rather than samples, and they must ride the identical gain or the
    plate and the cards drift apart on exactly the shots where the cap bites.
    """
    noise_xy, _, _ = max_excursion(hint, trauma=trauma)
    peak = max(abs(base_pan[0]), abs(base_pan[1])) + noise_xy
    return 1.0 if (xy_peak is None or peak <= 0) else xy_peak / peak


def sample_overscan_margin(
    samples: list[CameraSample], *, w: float = 1920.0, h: float = 1080.0,
) -> float:
    """Overscan margin M (scale = 1+M) a warping renderer needs so no frame can
    expose an uncovered border (Story 11.5 AC6).

    Same construction as :func:`overscan_margin` — translation excursion plus the
    rotated corner's swing against the shorter half-extent, plus the micro-zoom
    trough — but read off the OBSERVED samples, because ``xy_peak`` rescaling
    makes the analytic profile bound wrong for a capped trajectory.

    This function is the single owner of that number: parallax_service receives
    it, and video.py's card-side ground tracking uses the same value, so the
    plate's scale-up and the cards' floor tracking cannot disagree.
    """
    if not samples:
        return 0.0
    x_max, y_max, rot_max, _ = sample_bounds(samples)
    zoom_min = min(s.zoom for s in samples)
    corner_r = math.hypot(w, h) / 2
    displaced = max(x_max, y_max) * w + corner_r * rot_max + _EDGE_SLACK_PX
    return max(0.0, -zoom_min) + max(displaced / (w / 2), displaced / (h / 2))


def sample_bounds(samples: list[CameraSample]) -> tuple[float, float, float, float]:
    """Observed ``(|x|max, |y|max, |rot|max, zoom_max)`` — what the renderer's
    overscan must cover and what tests assert the AC6 cap against."""
    if not samples:
        return 0.0, 0.0, 0.0, 0.0
    return (
        max(abs(s.x) for s in samples),
        max(abs(s.y) for s in samples),
        max(abs(s.rot) for s in samples),
        max(s.zoom for s in samples),
    )


def max_excursion(hint: str | None, *, trauma: float = 0.0) -> tuple[float, float, float]:
    """Analytic worst case ``(xy_frac_of_width, rot_rad, zoom_delta)`` — exact
    because fbm_expr normalizes octave sums to the requested amp and the
    trauma carrier peaks at trauma²·coeff (7.3's CHAR_MAX_W "by construction,
    not by eyeball" lineage)."""
    p = noise_profile_for(hint)
    t2 = trauma * trauma
    xy = p.sway_amp + p.tremor_amp + t2 * TRAUMA_MAX_XY
    rot = math.radians(p.rot_deg + t2 * TRAUMA_MAX_ROT_DEG)
    return xy, rot, p.zoom_amp


# Even-dimension rounding in the overscan scale stage can eat up to 1px per
# side; fold that into the margin instead of trusting clip() alone.
_EDGE_SLACK_PX = 2.0


def overscan_margin(
    hint: str | None, *, trauma: float = 0.0, w: float = 1920.0, h: float = 1080.0,
) -> float:
    """Overscan scale margin M (scale factor = 1+M) guaranteeing the crop
    window never leaves the scaled+rotated source: per side we need the x/y
    translation excursion plus the rotated crop-corner displacement (corner
    radius × θ, small-angle), against the *shorter* half-extent, plus the
    micro-zoom trough. Derived from max_excursion, so AC:2's margin follows
    the profile by construction."""
    xy, rot, zoom = max_excursion(hint, trauma=trauma)
    if xy == 0 and rot == 0 and zoom == 0:
        return 0.0
    corner_r = math.hypot(w, h) / 2
    displaced = xy * w + corner_r * rot + _EDGE_SLACK_PX
    return zoom + max(displaced / (w / 2), displaced / (h / 2))
