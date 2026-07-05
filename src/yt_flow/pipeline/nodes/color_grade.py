"""color_grade — mood-driven color grade + constant vignette/film-grain (Story 7.2).

Pure function, no I/O, same layer as video.py/sound_design.py — the only
degradation path is an unknown mood, already handled by resolve_mood's
fallback.

Layer rule: domain and config only; no db/, api/, services/. [AD-1]
"""

from yt_flow.pipeline.nodes.sound_design import MOOD_VALUES, resolve_mood

VIGNETTE_ANGLE = "PI/5"  # constant across all moods
GRAIN_STRENGTH = 8  # noise filter `alls=`, subtle photographic grain

# ponytail: extract to a shared mood.py only if a 3rd consumer needs the
# taxonomy; two consumers importing from sound_design (the owner) isn't
# worth a new file yet.
MOOD_GRADE_PARAMS: dict[str, dict[str, float]] = {
    "dread": {"saturation": 0.75, "contrast": 1.05, "brightness": -0.03, "gamma": 0.95},
    "clinical": {"saturation": 0.55, "contrast": 1.00, "brightness": 0.00, "gamma": 1.00},
    "escalation": {"saturation": 1.15, "contrast": 1.15, "brightness": 0.02, "gamma": 1.00},
    "revelation": {"saturation": 1.00, "contrast": 1.30, "brightness": 0.00, "gamma": 1.05},
}
# resolve_mood only guarantees a MOOD_VALUES member; keep this dict's keys in
# lockstep or a taxonomy change silently turns into a runtime KeyError here.
assert set(MOOD_GRADE_PARAMS) == set(MOOD_VALUES)


def build_post_filter(mood: str | None) -> str:
    """eq (mood-driven color grade) -> vignette -> noise (grain), fixed order."""
    p = MOOD_GRADE_PARAMS[resolve_mood(mood)]
    eq = (
        f"eq=saturation={p['saturation']}:contrast={p['contrast']}:"
        f"brightness={p['brightness']}:gamma={p['gamma']}"
    )
    return f"{eq},vignette=angle={VIGNETTE_ANGLE},noise=alls={GRAIN_STRENGTH}:allf=t+u"
