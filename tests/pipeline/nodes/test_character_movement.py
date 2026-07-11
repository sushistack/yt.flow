"""Tests for src/yt_flow/pipeline/nodes/character_movement.py (Story 8.9).

Pure functions only — no I/O, no ffmpeg, no fakes needed. Numeric assertions
mirror test_character_motion.py's style: check the constants that feed the
expression string, not a full ffmpeg-expression evaluator.
"""

import pytest

import yt_flow.pipeline.nodes.character_movement as mv


def _build(**overrides):
    kwargs = dict(mode="anchored", direction="none", pace="slow", position="center", depth="mid", duration=2.0)
    kwargs.update(overrides)
    return mv.build_movement_terms(**kwargs)


# ── anchored: identity, no terms at all (AC:10) ─────────────────────────────


def test_anchored_has_no_terms_on_any_axis():
    curve = _build(mode="anchored")
    assert curve.x_terms == [] and curve.y_terms == [] and curve.scale_terms == []


def test_zero_duration_has_no_terms_regardless_of_mode():
    for mode in ("drift", "enter", "exit", "cross", "approach", "retreat"):
        curve = _build(mode=mode, duration=0.0)
        assert curve.x_terms == [] and curve.y_terms == [] and curve.scale_terms == []


def test_unrecognized_mode_degrades_to_no_terms():
    """AD-10: an out-of-vocab mode never raises, degrades to no movement."""
    curve = _build(mode="teleport")
    assert curve.x_terms == [] and curve.y_terms == [] and curve.scale_terms == []


# ── ease curve is not a plain linear ramp (AC:6) ────────────────────────────


def test_drift_ease_is_not_plain_linear_ramp():
    curve = _build(mode="drift")
    assert curve.x_terms, "drift must produce an x term"
    expr = curve.x_terms[0]
    assert expr != f"{mv.DRIFT_PX}*t/2.0"
    assert "3-2*" in expr  # smoothstep signature


# ── mode -> axis mapping (AC:7) ──────────────────────────────────────────────


def test_drift_has_only_x_term_bounded_small():
    curve = _build(mode="drift")
    assert len(curve.x_terms) == 1 and curve.y_terms == [] and curve.scale_terms == []
    assert str(mv.DRIFT_PX) in curve.x_terms[0]


def test_enter_and_exit_have_only_x_term():
    for mode in ("enter", "exit"):
        curve = _build(mode=mode, direction="left")
        assert len(curve.x_terms) == 1 and curve.y_terms == [] and curve.scale_terms == []


def test_cross_has_only_x_term():
    curve = _build(mode="cross", direction="right", position="left")
    assert len(curve.x_terms) == 1 and curve.y_terms == [] and curve.scale_terms == []


def test_approach_and_retreat_have_only_scale_term():
    for mode in ("approach", "retreat"):
        curve = _build(mode=mode, depth="near")
        assert curve.x_terms == [] and curve.y_terms == []
        assert len(curve.scale_terms) == 1


# ── off-frame / settled-value invariants (AC:8) ─────────────────────────────


def test_enter_settles_at_anchor_starts_offscreen():
    """enter: at t=duration the delta is 0 (settled at the 8.3 anchor); the
    deliberate offscreen excursion only exists at t=0 (AC:8)."""
    curve = _build(mode="enter", direction="left", pace="slow", duration=2.0)
    expr = curve.x_terms[0]
    # slow pace spans the full duration ⇒ ease(duration)==1 ⇒ term evaluates to 0
    t = 2.0
    value = eval(expr.replace("main_w", "1920").replace("t", str(t)), {"min": min})
    assert value == pytest.approx(0.0, abs=1e-9)


def test_exit_starts_at_anchor_settles_offscreen():
    """exit: at t=0 the delta is 0 (starts at anchor); it deliberately ends
    offscreen at t=duration (AC:8)."""
    curve = _build(mode="exit", direction="right", pace="slow", duration=2.0)
    expr = curve.x_terms[0]
    value = eval(expr.replace("main_w", "1920").replace("t", "0"), {"min": min})
    assert value == pytest.approx(0.0, abs=1e-9)


def test_cross_stays_in_frame_at_start_and_end():
    """cross traverses thirds but both endpoints stay on-frame (AC:7): the
    settled (t=duration) delta is 0, and the start (t=0) delta only shifts by
    one third-width, never a full frame width."""
    curve = _build(mode="cross", direction="right", position="left", pace="slow", duration=2.0)
    expr = curve.x_terms[0]
    settled = eval(expr.replace("main_w", "1920").replace("t", "2.0"), {"min": min})
    start = eval(expr.replace("main_w", "1920").replace("t", "0"), {"min": min})
    assert settled == pytest.approx(0.0, abs=1e-9)
    assert abs(start) < 1920  # less than a full frame width — stays on-screen


def test_drift_settled_offset_never_crosses_into_another_third():
    """Adjacent thirds are main_w/6 apart at 1920 width; drift must stay well
    under that gap so a drifting card never reads as having changed slot."""
    third_gap_px = 1920 * (1 / 2 - 1 / 3)
    assert mv.DRIFT_PX < third_gap_px / 2


def test_approach_settles_at_declared_depth_scale():
    """approach ends AT the declared depth (delta==0 at t=duration)."""
    curve = _build(mode="approach", depth="near", pace="slow", duration=2.0)
    expr = curve.scale_terms[0]
    value = eval(expr.replace("t", "2.0"), {"min": min})
    assert value == pytest.approx(0.0, abs=1e-9)


def test_retreat_starts_at_declared_depth_scale():
    """retreat starts AT the declared depth (delta==0 at t=0)."""
    curve = _build(mode="retreat", depth="near", pace="slow", duration=2.0)
    expr = curve.scale_terms[0]
    value = eval(expr.replace("t", "0"), {"min": min})
    assert value == pytest.approx(0.0, abs=1e-9)


def test_approach_retreat_scale_delta_never_grows_the_card():
    """Shallower depths never scale UP (near > mid > far) — the movement scale
    delta is always <= 0, so approach/retreat can never overflow the
    motion-safe box beyond what a static card at that depth already respects."""
    for depth in ("near", "mid", "far"):
        for mode in ("approach", "retreat"):
            curve = _build(mode=mode, depth=depth, pace="slow", duration=2.0)
            for t in (0.0, 1.0, 2.0):
                expr = curve.scale_terms[0]
                value = eval(expr.replace("t", str(t)), {"min": min})
                assert value <= 1e-9


def test_far_depth_approach_retreat_has_zero_amplitude():
    """far has no shallower plane to interpolate against — clamps to itself,
    a zero-amplitude (but still valid) movement term."""
    for mode in ("approach", "retreat"):
        curve = _build(mode=mode, depth="far", pace="slow", duration=2.0)
        for t in (0.0, 1.0, 2.0):
            expr = curve.scale_terms[0]
            value = eval(expr.replace("t", str(t)), {"min": min})
            assert value == pytest.approx(0.0, abs=1e-9)


# ── determinism ──────────────────────────────────────────────────────────────


def test_same_inputs_always_produce_same_expression():
    a = _build(mode="cross", direction="left", position="right")
    b = _build(mode="cross", direction="left", position="right")
    assert a == b
