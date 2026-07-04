# Post-Processing Filters (Film Grain / Vignette / Color Grade) — Design

**Date**: 2026-07-04
**Status**: Approved for planning
**Depends on**: [2026-07-04-sound-design-design.md](2026-07-04-sound-design-design.md) —
reuses `SceneState.mood` and `sound_design.resolve_mood`/`MOOD_VALUES`/`DEFAULT_MOOD`.
This spec assumes that work has landed (or lands first).
**Scope**: 2nd priority sub-project of the "영상미 개선" initiative (see the
sound-design spec's "Out of scope" for the full candidate list — real
parallax is 3rd priority, transition/subtitle variety is deferred further).

## Problem

Every frame is a straight zoompan of a raw ComfyUI-generated still. There is
no color treatment, no film texture, no vignette — footage reads as flat,
static-image drift rather than graded video. Cheapest-per-effect item on the
production-value list: pure ffmpeg filters, no new assets, no new pipeline
stage.

## Goals

- Per-scene color grade driven by `SceneState.mood` (same field the sound
  design spec introduces) — reinforces mood with a visual language instead of
  audio alone.
- Subtle, constant film grain + vignette applied uniformly (not mood-driven —
  only the color grade varies; grain/vignette intensity varying per mood was
  explicitly rejected as a second axis of complexity not worth it for v1).
- Chapter cards get the same treatment as scene footage, keyed to the
  *upcoming* scene's mood, so the card doesn't visually reset the tone.
- Subtitles stay untouched by grain/vignette (burned in after, not before) —
  legibility is not up for negotiation.
- Zero new dependencies — `eq`, `vignette`, `noise` are stock ffmpeg filters.

## Architecture decision

Same pattern as the sound-design spec: extend `video_node._compose_scene`'s
existing filter chain, no new pipeline stage. The case for a separate stage
is even weaker here than for sound design — this is three more filter names
appended to a `-vf`/`filter_complex` string that ffmpeg already builds and
runs once per scene. A dedicated approach-comparison table is skipped; the
"one ffmpeg call per scene, no new LangGraph node" decision was already
established and re-litigating it per sub-feature isn't warranted.

## New module: `src/yt_flow/pipeline/nodes/color_grade.py`

Pure function, no I/O, same layer as `video.py`/`sound_design.py`:

```python
from yt_flow.pipeline.nodes.sound_design import resolve_mood  # reused taxonomy, not redefined

VIGNETTE_ANGLE = "PI/5"     # constant across all moods
GRAIN_STRENGTH = 8          # noise filter `alls=`, subtle photographic grain

MOOD_GRADE_PARAMS: dict[str, dict[str, float]] = {
    "dread":      {"saturation": 0.75, "contrast": 1.05, "brightness": -0.03, "gamma": 0.95},
    "clinical":   {"saturation": 0.55, "contrast": 1.00, "brightness":  0.00, "gamma": 1.00},
    "escalation": {"saturation": 1.15, "contrast": 1.15, "brightness":  0.02, "gamma": 1.00},
    "revelation": {"saturation": 1.00, "contrast": 1.30, "brightness":  0.00, "gamma": 1.05},
}


def build_post_filter(mood: str | None) -> str:
    """eq (mood-driven color grade) -> vignette -> noise (grain), fixed order."""
    p = MOOD_GRADE_PARAMS[resolve_mood(mood)]
    eq = f"eq=saturation={p['saturation']}:contrast={p['contrast']}:brightness={p['brightness']}:gamma={p['gamma']}"
    return f"{eq},vignette=angle={VIGNETTE_ANGLE},noise=alls={GRAIN_STRENGTH}:allf=t+u"
```

`resolve_mood`/`MOOD_VALUES`/`DEFAULT_MOOD` are imported from `sound_design.py`
rather than redefined — the mood taxonomy has exactly one owner. `# ponytail:`
note in the module: extract to a shared `mood.py` only if a third consumer
needs the taxonomy; two consumers importing from the first owner is not worth
a new file.

Illustrative param values only — tuned by eye once real rendered footage is
available, same caveat as the sound-design spec's ffmpeg filter sketch.

## Filter chain placement

Inserted after character overlay (or after zoompan on the background-only
path), before subtitle burn-in — grain/vignette/grade apply to the whole
composited frame, never to burned text.

Layered path (`_compose_scene`, character present):
```
[0:v]{zp_chain}[bg];
[1:v]{_character_scale_filter()}[char];
[bg][char]{_overlay_filter()}[ov];
[ov]{build_post_filter(mood)}[graded];
[graded]subtitles='{sub}'[out]
```

Background-only path:
```
{zp_chain},{build_post_filter(mood)},subtitles='{sub}'
```

`mood` is `scene.get("mood")` — resolved the same lenient way sound design
does, so pre-mood checkpointed runs still render (falling back to
`DEFAULT_MOOD`'s grade).

## Chapter cards

`_compose_chapter_card` gains a `mood: str | None` param — `video_node`
passes `scenes[i + 1]["mood"]` (the card announces the *upcoming* scene, same
convention the sound-design spec's stinger-selection rule uses). Inserted
before `drawtext` so the label text isn't grained:

```
{build_post_filter(mood)},drawtext=...,fade=...,fade=...
```

On the card's solid black background, `eq`/`vignette` are near-invisible;
`noise` still shows as visible grain texture on the card, which is the
desired consistency effect (card doesn't read as a flat, ungraded interstitial
between two graded scenes).

## Settings

```python
# src/yt_flow/config.py
post_fx_enabled: bool = True   # same pattern as chapter_cards / sound_design_enabled
```

`VIGNETTE_ANGLE`, `GRAIN_STRENGTH`, and `MOOD_GRADE_PARAMS` are fixed module
constants in `color_grade.py`, not `Settings` fields or per-scene config —
same precedent as `SWAY_AMPLITUDE`/`ZOOM_IN_MAX` in `video.py` and the
volume/ducking constants in `sound_design.py`. Add a knob only when a real
scene needs a different value than its mood's default.

## Testing

`build_post_filter` is a pure function — unit test asserts the returned
string contains the expected `eq=`/`vignette=`/`noise=` fragments for each of
the 4 moods, and that an unknown/`None` mood falls back to `DEFAULT_MOOD`'s
params (delegates to `resolve_mood`, already tested by the sound-design
spec's test suite). `_compose_scene`/`_compose_chapter_card` integration
covered via the existing `fake_run_ffmpeg` stub — assert the vf/filter_complex
string contains the post-filter fragment in the right position (after overlay,
before `subtitles=`).

## Error handling

No new failure modes. Unlike sound design (which depends on asset files that
can go missing), `eq`/`vignette`/`noise` are always-available stock ffmpeg
filters with no external files — the only degradation path is an unknown
`mood` value, already covered by `resolve_mood`'s fallback to `DEFAULT_MOOD`.
`post_fx_enabled = False` skips `build_post_filter` entirely, reverting to
today's ungraded output.
