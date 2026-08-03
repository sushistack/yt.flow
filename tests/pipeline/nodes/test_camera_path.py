"""Story 11.3: fBm camera-path primitives — pure string/number tests, no render."""

import math

import pytest

from yt_flow.domain.state import CAMERA_ARCHETYPES
from yt_flow.pipeline.nodes import camera_path as cp
from yt_flow.pipeline.nodes.sound_design import MOOD_VALUES


# ── fbm_expr: deterministic closed-form value-noise fBm ──────────────────────


def test_fbm_expr_deterministic():
    a = cp.fbm_expr(0.01, 1.0, 2, 3.7)
    b = cp.fbm_expr(0.01, 1.0, 2, 3.7)
    assert a == b and a  # same inputs → byte-identical string


def test_fbm_expr_is_continuous_noise_not_white():
    expr = cp.fbm_expr(0.01, 1.0, 2, 0.0)
    # value noise = hashed lattice + smoothstep interpolation; never ffmpeg random()
    assert "random" not in expr
    assert "floor(" in expr and "sin(" in expr
    assert "3-2*" in expr  # smoothstep u*u*(3-2u)


def test_fbm_expr_zero_amp_or_octaves_is_empty():
    assert cp.fbm_expr(0.0, 1.0, 2, 0.0) == ""
    assert cp.fbm_expr(0.01, 1.0, 0, 0.0) == ""
    assert cp.fbm_expr(0.01, 0.0, 2, 0.0) == ""


def test_fbm_octave_amps_sum_to_amp():
    # normalization invariant: octave amplitude sum == requested amp (AC:1),
    # persistence 0.5 halves each octave
    for octaves in (1, 2, 3):
        amps = cp._octave_amps(0.015, octaves)
        assert len(amps) == octaves
        assert math.isclose(sum(amps), 0.015)
        for j in range(1, octaves):
            assert math.isclose(amps[j], amps[j - 1] * 0.5)


def test_fbm_expr_distinct_offsets_decorrelate():
    assert cp.fbm_expr(0.01, 1.0, 2, 0.0) != cp.fbm_expr(0.01, 1.0, 2, 37.0)


def test_fbm_expr_custom_t_var():
    assert "n/30" in cp.fbm_expr(0.01, 1.0, 1, 0.0, t_var="n/30")


# ── profiles: lockstep + semantics ───────────────────────────────────────────


def test_profiles_lockstep_with_camera_archetypes():
    assert set(cp.CAMERA_NOISE_PROFILES) == set(CAMERA_ARCHETYPES)


def test_trauma_lockstep_with_mood_values():
    assert set(cp.TRAUMA_BY_MOOD) == set(MOOD_VALUES)


def test_locked_profile_is_all_zero():
    p = cp.CAMERA_NOISE_PROFILES["locked"]
    assert all(v == 0 for v in p)


@pytest.mark.parametrize("hint,expected", [
    ("locked", "locked"),
    ("static", "locked"),          # select_effect treats static==locked; so do we
    ("shake", "shake"),
    ("push_in", "push_in"),
    (" Pull_Back ", "pull_back"),  # normalized like select_effect's hint parsing
    (None, "push_in"),             # legacy checkpoint → documentary default
    ("dolly zoom", "push_in"),     # free text → documentary default
])
def test_noise_profile_for_resolution(hint, expected):
    assert cp.noise_profile_for(hint) is cp.CAMERA_NOISE_PROFILES[expected]


def test_shake_profile_is_louder_than_documentary():
    docu = cp.CAMERA_NOISE_PROFILES["push_in"]
    shake = cp.CAMERA_NOISE_PROFILES["shake"]
    assert shake.sway_amp > docu.sway_amp
    assert shake.rot_deg > docu.rot_deg
    assert shake.sway_octaves >= docu.sway_octaves


# ── camera_noise_exprs: the video.py-facing bundle ───────────────────────────


def test_locked_without_trauma_yields_none():
    assert cp.camera_noise_exprs("locked", 0) is None
    assert cp.camera_noise_exprs("static", 3) is None


def test_locked_with_trauma_yields_event_shake_only():
    # a stinger hit shakes even a tripod — trauma is the dramatic beat, not
    # part of the idle profile
    exprs = cp.camera_noise_exprs("locked", 0, trauma=0.8)
    assert exprs is not None
    assert "max(0" in exprs.x_expr  # decay envelope present


def test_exprs_deterministic_and_k_decorrelated():
    a = cp.camera_noise_exprs("shake", 0)
    b = cp.camera_noise_exprs("shake", 0)
    c = cp.camera_noise_exprs("shake", 1)
    assert a == b
    assert a.x_expr != c.x_expr and a.y_expr != c.y_expr


def test_exprs_have_no_random():
    exprs = cp.camera_noise_exprs("shake", 2, trauma=0.8)
    for e in (exprs.x_expr, exprs.y_expr, exprs.rot_expr, exprs.zoom_expr):
        assert "random" not in e


def test_trauma_zero_has_no_event_term():
    exprs = cp.camera_noise_exprs("shake", 0, trauma=0.0)
    assert "max(0" not in exprs.x_expr  # no decay envelope without trauma


def test_x_and_y_are_decorrelated():
    exprs = cp.camera_noise_exprs("shake", 0)
    assert exprs.x_expr != exprs.y_expr


# ── excursion bound / overscan margin: by construction, not by eyeball ───────


def test_margin_covers_analytic_excursion():
    # margin must be ≥ zoom + (xy px + rotated-corner displacement)/(h/2)
    for hint in CAMERA_ARCHETYPES:
        for trauma in (0.0, 0.8):
            p = cp.noise_profile_for(hint)
            xy, rot, zoom = cp.max_excursion(hint, trauma=trauma)
            assert xy >= p.sway_amp + p.tremor_amp
            m = cp.overscan_margin(hint, trauma=trauma)
            r = math.hypot(1920, 1080) / 2
            assert m >= zoom + (xy * 1920 + r * rot) / (1080 / 2)


def test_margin_grows_with_trauma():
    assert cp.overscan_margin("shake", trauma=0.8) > cp.overscan_margin("shake", trauma=0.0)


def test_margin_is_modest():
    # sanity: documentary band stays a small overscan, shake+max trauma < 25%
    assert cp.overscan_margin("push_in") < 0.06
    assert cp.overscan_margin("shake", trauma=0.8) < 0.25


def test_locked_margin_zero():
    assert cp.overscan_margin("locked") == 0.0


def test_version_constant():
    assert cp.CAMERA_PATH_VERSION == "1"


# ── Numeric trajectory sampler (Story 11.5 AC4) ──────────────────────────────


def _eval_expr(expr: str, t: float) -> float:
    """Evaluate one of Story 11.3's generated ffmpeg expressions in Python.

    The generated strings use only ``sin``/``floor``/``pow``/``max``/``min``,
    parentheses and arithmetic, so they ARE valid Python given this namespace.
    That is what makes the parity assertion below a real proof rather than two
    reimplementations agreeing with each other's bugs.
    """
    return float(eval(expr, {  # noqa: S307 — fixed, code-generated expressions
        "__builtins__": {},
        "sin": math.sin, "floor": math.floor, "pow": pow, "max": max, "min": min, "t": t,
    }))


@pytest.mark.parametrize("hint", CAMERA_ARCHETYPES)
@pytest.mark.parametrize("trauma", [0.0, 0.5])
def test_numeric_sampler_matches_ffmpeg_expressions(hint, trauma):
    """AC4: the numeric sampler and Story 11.3's expressions are ONE curve."""
    exprs = cp.camera_noise_exprs(hint, 3, trauma=trauma)
    samples = cp.sample_path(hint, 3, duration=2.0, fps=25, trauma=trauma)
    if exprs is None:  # locked, no trauma — proven silent below
        assert all(s.x == s.y == s.rot == s.zoom == 0.0 for s in samples)
        return
    for s in samples:
        assert s.x == pytest.approx(_eval_expr(exprs.x_expr or "0", s.t), abs=1e-12)
        assert s.y == pytest.approx(_eval_expr(exprs.y_expr or "0", s.t), abs=1e-12)
        assert s.rot == pytest.approx(_eval_expr(exprs.rot_expr or "0", s.t), abs=1e-12)
        assert s.zoom == pytest.approx(_eval_expr(exprs.zoom_expr or "0", s.t), abs=1e-12)


def test_sampler_is_deterministic_across_calls():
    a = cp.sample_path("shake", 7, duration=1.5, fps=25, trauma=0.6)
    b = cp.sample_path("shake", 7, duration=1.5, fps=25, trauma=0.6)
    assert a == b  # exact float equality: no hash(), no unseeded randomness


def test_sampler_frame_count_and_timestamps():
    samples = cp.sample_path("push_in", 0, duration=2.0, fps=25)
    assert len(samples) == 50
    assert samples[0].t == 0.0
    assert samples[-1].t == pytest.approx(49 / 25)
    # A sub-frame duration still yields one frame, never zero.
    assert len(cp.sample_path("push_in", 0, duration=0.01, fps=25)) == 1


def test_adjacent_shot_indices_decorrelate():
    a = cp.sample_path("push_in", 4, duration=1.0, fps=25)
    b = cp.sample_path("push_in", 5, duration=1.0, fps=25)
    assert [s.x for s in a] != [s.x for s in b]


def test_locked_without_trauma_is_no_motion():
    samples = cp.sample_path("locked", 2, duration=1.0, fps=25)
    assert not cp.has_motion("locked")
    assert not cp.has_motion("static")
    assert all(s == (s.t, 0.0, 0.0, 0.0, 0.0) for s in samples)


def test_locked_with_trauma_still_shakes():
    assert cp.has_motion("locked", trauma=0.5)
    samples = cp.sample_path("locked", 2, duration=1.0, fps=25, trauma=0.5)
    assert any(s.x != 0.0 for s in samples)


def test_trauma_decays_to_zero():
    samples = cp.sample_path("locked", 1, duration=2.0, fps=25, trauma=0.9)
    early = max(abs(s.x) for s in samples if s.t < cp.TRAUMA_TAU / 2)
    late = max(abs(s.x) for s in samples if s.t > cp.TRAUMA_TAU)
    assert late == 0.0 < early


@pytest.mark.parametrize("hint", CAMERA_ARCHETYPES)
@pytest.mark.parametrize("frac", [0.01, 0.02, 0.03])
def test_xy_peak_caps_combined_displacement(hint, frac):
    """AC6: base pan + noise + trauma together never exceed the requested cap."""
    samples = cp.sample_path(
        hint, 6, duration=3.0, fps=25, trauma=0.8, xy_peak=frac,
        base_zoom=(1.0, 1.15), base_pan=(0.05, -0.04),  # deliberately over-budget
    )
    x_max, y_max, _, _ = cp.sample_bounds(samples)
    assert x_max <= frac + 1e-12
    assert y_max <= frac + 1e-12


def test_clamp_displacement_holds_the_ac6_band():
    assert cp.clamp_displacement(0.0) == cp.DISPLACEMENT_MIN == 0.01
    assert cp.clamp_displacement(0.9) == cp.DISPLACEMENT_MAX == 0.03
    assert cp.clamp_displacement(0.02) == 0.02


def test_base_move_is_carried_and_owned_once():
    """AC7: the base Ken Burns move lives in the trajectory, not beside it."""
    zoom_only = cp.sample_path("locked", 0, duration=2.0, fps=25, base_zoom=(1.0, 1.15))
    assert zoom_only[0].zoom == pytest.approx(0.0)
    assert zoom_only[-1].zoom == pytest.approx(0.15, abs=0.01)
    pan_only = cp.sample_path("locked", 0, duration=2.0, fps=25, base_pan=(0.02, 0.0))
    assert pan_only[0].x == pytest.approx(0.0)
    assert pan_only[-1].x == pytest.approx(0.02, abs=0.001)
    assert all(s.y == 0.0 for s in pan_only)


def test_legacy_expression_api_unchanged():
    """AC4: 11.3's expression surface keeps working exactly as before."""
    assert cp.fbm_expr(0.0, 1.0, 2, 0.0) == ""
    assert cp.camera_noise_exprs("locked", 0) is None
    assert cp.camera_noise_exprs("push_in", 0) is not None
    assert cp.overscan_margin("locked") == 0.0
