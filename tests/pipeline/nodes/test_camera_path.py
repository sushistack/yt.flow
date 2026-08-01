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
