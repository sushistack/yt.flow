"""Tests for src/yt_flow/pipeline/nodes/character_motion.py (Story 8.8).

Pure functions only — no I/O, no ffmpeg, no fakes needed.
"""

import yt_flow.pipeline.nodes.character_motion as cm


# ── axis_terms: per-style term counts ───────────────────────────────────────


def test_hold_has_no_terms_on_any_axis():
    for axis in ("x", "y", "scale"):
        assert cm.axis_terms("hold", "medium", axis, 0.0) == []


def test_breath_has_y_and_scale_only():
    assert cm.axis_terms("breath", "medium", "x", 0.0) == []
    assert len(cm.axis_terms("breath", "medium", "y", 0.0)) == 1
    assert len(cm.axis_terms("breath", "medium", "scale", 0.0)) == 1


def test_sway_has_x_y_and_scale():
    assert len(cm.axis_terms("sway", "medium", "x", 0.0)) == 1
    assert len(cm.axis_terms("sway", "medium", "y", 0.0)) == 1
    assert len(cm.axis_terms("sway", "medium", "scale", 0.0)) == 1


def test_tremble_is_breath_plus_shake():
    """tremble = breath's bob + its own shake — y carries both terms, x only the shake."""
    assert len(cm.axis_terms("tremble", "medium", "x", 0.0)) == 1
    assert len(cm.axis_terms("tremble", "medium", "y", 0.0)) == 2
    assert len(cm.axis_terms("tremble", "medium", "scale", 0.0)) == 1


def test_pulse_is_scale_only():
    assert cm.axis_terms("pulse", "medium", "x", 0.0) == []
    assert cm.axis_terms("pulse", "medium", "y", 0.0) == []
    assert len(cm.axis_terms("pulse", "medium", "scale", 0.0)) == 1


def test_glitch_has_x_and_y_only_and_is_quantized():
    x = cm.axis_terms("glitch", "medium", "x", 0.0)
    y = cm.axis_terms("glitch", "medium", "y", 0.0)
    assert len(x) == 1 and len(y) == 1
    assert cm.axis_terms("glitch", "medium", "scale", 0.0) == []
    assert "floor(" in x[0] and "floor(" in y[0]
    assert x[0] != y[0]  # different hash multiplier decorrelates the axes


# ── sway/medium reproduces the pre-8.8 sine exactly ─────────────────────────


def test_sway_medium_matches_legacy_sway_bob_constants():
    x_expr = cm.axis_terms("sway", "medium", "x", 1.5)[0]
    y_expr = cm.axis_terms("sway", "medium", "y", 1.5)[0]
    assert x_expr == f"sin(t*{cm.SWAY_FREQ}+1.5)*{cm.SWAY_AMPLITUDE}"
    assert y_expr == f"sin(t*{cm.BOB_FREQ}+1.5)*{cm.BOB_AMPLITUDE}"


# ── energy scales amplitude, not frequency ──────────────────────────────────


def test_energy_scales_amplitude_low_lt_medium_lt_high():
    def amp(energy):
        expr = cm.axis_terms("sway", energy, "x", 0.0)[0]
        return float(expr.rsplit("*", 1)[1])

    assert amp("low") < amp("medium") < amp("high")


def test_energy_does_not_change_frequency():
    def freq(energy):
        expr = cm.axis_terms("breath", energy, "y", 0.0)[0]
        return expr.split("t*")[1].split("+")[0]

    assert freq("low") == freq("medium") == freq("high")


# ── determinism ──────────────────────────────────────────────────────────────


def test_same_inputs_always_produce_same_expression():
    a = cm.axis_terms("glitch", "high", "x", 2.1)
    b = cm.axis_terms("glitch", "high", "x", 2.1)
    assert a == b


# ── max_excursion: off-frame invariant source of truth (AC:7) ──────────────


def test_max_excursion_reflects_worst_case_style():
    max_x, max_y, max_scale = cm.max_excursion()
    high_mult = cm._ENERGY_MULT["high"]
    # sway is the only x-axis contributor; tremble sums bob+shake on y.
    assert max_x == cm.SWAY_AMPLITUDE * high_mult
    assert max_y == (cm.BOB_AMPLITUDE + cm.TREMBLE_AMP) * high_mult
    assert max_scale == 1.0 + cm.PULSE_SCALE_AMP * high_mult


def test_max_excursion_never_smaller_than_any_single_style():
    max_x, max_y, _max_scale = cm.max_excursion()
    for style in cm._STYLE_TERMS:
        for energy in ("low", "medium", "high"):
            x = sum(float(e.rsplit("*", 1)[1]) for e in cm.axis_terms(style, energy, "x", 0.0))
            y = sum(float(e.rsplit("*", 1)[1]) for e in cm.axis_terms(style, energy, "y", 0.0))
            assert x <= max_x + 1e-9
            assert y <= max_y + 1e-9


def test_axis_terms_degrades_on_out_of_vocab_style_or_energy():
    """A resolved card carrying a style/energy outside the current vocab (e.g.
    a checkpoint written by a different code version) must degrade to
    breath/medium, not raise — Epic 8's 'taxonomy violation never raises' rule
    (AD-10) applies here, not just in parse_cast (review finding)."""
    assert cm.axis_terms("nonexistent-style", "medium", "y", 0.0) == cm.axis_terms("breath", "medium", "y", 0.0)
    assert cm.axis_terms("breath", "nonexistent-energy", "y", 0.0) == cm.axis_terms("breath", "medium", "y", 0.0)
