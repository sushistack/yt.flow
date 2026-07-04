# Mood-Driven Transition Variety — Design

**Date**: 2026-07-04
**Status**: Approved for planning (not scheduled — drafted ahead of need)
**Depends on**: [2026-07-04-sound-design-design.md](2026-07-04-sound-design-design.md) —
reuses `SceneState.mood` and `sound_design.resolve_mood`/`MOOD_VALUES`.
**Scope**: 4th candidate of the "영상미 개선" initiative (see the sound-design
spec's "Out of scope"), split from "트랜지션/자막 다양화" — subtitle kinetic
typography is its own sibling spec
([2026-07-04-kinetic-subtitles-design.md](2026-07-04-kinetic-subtitles-design.md)),
different file (`subtitle.py`), different failure modes, no shared code.

## Problem

`XFADE_TRANSITION = "fadeblack"` is a single hardcoded constant used for
every scene boundary, with a `# ponytail:` comment noting it's "single
crossfade type until a second is actually wanted." With `SceneState.mood`
now available (from the sound-design spec), a second type — driven by mood,
not arbitrary — is worth having: a transition can visually announce the
mood shift the same way the sound-design stinger and the color-grade card
already do.

## Design

Same "upcoming scene" convention already established twice: the sound-design
spec's SFX stinger and the color-grade spec's chapter card both key off the
*next* scene's mood, not the outgoing one. Transition type follows the same
rule for consistency — one rule, three features.

Only the transition **type** varies by mood; duration (`XFADE_DURATION =
0.5`) stays constant for every boundary, regardless of mood. Varying two axes
(type and duration) at once was considered and rejected — same reasoning as
color-grade's "only hue varies, vignette/grain intensity stays constant":
one axis of mood-driven variation per feature keeps tuning tractable.

```python
# video.py
MOOD_XFADE_MAP: dict[str, str] = {
    "dread": "fadeblack",       # unchanged — Story 5.1 already found plain
    "clinical": "fadeblack",    # "fade" showed both images overlapped; keep
                                 # the calmer two moods on the proven default
    "escalation": "wipeleft",   # directional, kinetic — illustrative pick,
    "revelation": "fadewhite",  # tune by eye against a live render
}


def resolve_transition(mood: str | None) -> str:
    return MOOD_XFADE_MAP[resolve_mood(mood)]
```

All four values are ffmpeg's own built-in `xfade` transition names (`fade`,
`fadeblack`, `fadewhite`, `wipeleft/right/up/down`, `slideleft/right/up/down`,
`circleopen/close`, `dissolve`, `pixelize`, …) — zero new dependencies, just
a different string passed to the filter ffmpeg already runs.

**Chapter-card boundaries are exempt.** Any boundary touching a chapter card
(scene→card or card→scene) keeps the fixed `"fadeblack"` — cutting a
kinetic wipe into/out of a solid black title card was judged not worth the
complexity of a second mapping table for a rare boundary type. Only
scene-to-scene boundaries are mood-driven.

## `_join_with_xfade` change

`segments` grows a third tuple element — the transition type to use *entering*
that segment:

```python
def _join_with_xfade(segments: list[tuple[Path, float, str]], output: Path) -> None:
    ...
    for i, (_, dur, _) in enumerate(segments):
        if i < n - 1:
            transition = segments[i + 1][2]  # next segment announces its own cut-in
            ...
            v_parts.append(
                f"{v_prev}[{i+1}:v]xfade=transition={transition}"
                f":duration={XFADE_DURATION}:offset={offset:.4f}{v_out}"
            )
```

`segments[0][2]` is never read (nothing precedes the first segment) but is
still populated for tuple-shape uniformity with the rest of the list.
`video_node` builds each scene tuple as `(seg_path, duration,
resolve_transition(scenes[i]["mood"]))` and each chapter-card tuple as
`(card_path, card_duration, "fadeblack")`.

## Settings

```python
# src/yt_flow/config.py
transition_variety_enabled: bool = True   # same pattern as the other 3 specs
```

`False` → every boundary uses `"fadeblack"`, i.e. today's behavior exactly.

## Testing

`resolve_transition` is a pure function — unit test asserts the mapping for
all 4 moods plus the unknown/`None` → `DEFAULT_MOOD` fallback path (delegates
to `resolve_mood`, already tested by the sound-design spec's suite).
`_join_with_xfade`'s existing tests (which already assert the constructed
filter string) extend to assert the per-boundary transition name appears
correctly, and that a chapter-card boundary always gets `"fadeblack"`
regardless of the adjacent scenes' moods.

## Error handling

No new failure modes — every value in `MOOD_XFADE_MAP` is a valid built-in
`xfade` transition name, and `resolve_mood`'s existing fallback covers
missing/invalid mood values. `transition_variety_enabled = False` reverts to
the single hardcoded constant.
