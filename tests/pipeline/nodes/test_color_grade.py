"""Tests for src/yt_flow/pipeline/nodes/color_grade.py (Story 7.2)."""

import pytest

from yt_flow.pipeline.nodes.color_grade import MOOD_GRADE_PARAMS, build_post_filter
from yt_flow.pipeline.nodes.sound_design import DEFAULT_MOOD, MOOD_VALUES


@pytest.mark.parametrize("mood", MOOD_VALUES)
def test_build_post_filter_contains_expected_fragments(mood):
    """[AC:1,2,3] eq/vignette/noise fragments, in that fixed order, per mood."""
    f = build_post_filter(mood)
    p = MOOD_GRADE_PARAMS[mood]
    assert f.startswith(
        f"eq=saturation={p['saturation']}:contrast={p['contrast']}:"
        f"brightness={p['brightness']}:gamma={p['gamma']}"
    )
    assert "vignette=angle=PI/5" in f
    assert "noise=alls=8:allf=t+u" in f
    assert f.index("eq=") < f.index("vignette=") < f.index("noise=")


@pytest.mark.parametrize("mood", [None, "", "unknown-mood"])
def test_build_post_filter_falls_back_to_default_mood(mood):
    """[AC:2] Unknown/None/empty mood falls back to DEFAULT_MOOD's params."""
    assert build_post_filter(mood) == build_post_filter(DEFAULT_MOOD)
