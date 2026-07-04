# Real Parallax (Background/Character Speed Separation) — Design

**Date**: 2026-07-04
**Status**: Approved for planning
**Related**: `deferred-work.md` "Deferred from: 5-3 motion-intensity 라이브 QA
(2026-07-04)" — this spec is the reconsideration this deferral asked for.
**Scope**: 3rd priority sub-project of the "영상미 개선" initiative (see the
sound-design spec's "Out of scope" for the full candidate list).

## Problem

Story 5.3 raised `ZOOM_IN_MAX` from 1.08 to 1.15 for the background's Ken
Burns zoom. Live QA on that change noticed the background now visibly
approaches the viewer while the character overlay (fixed size, only
sway/bob idle motion) does not — an *accidental*, zoom-only, uncontrolled
parallax-like artifact. `deferred-work.md` explicitly deferred fixing this
pending a decision on whether to make it deliberate. This spec makes it
deliberate: couple the character's motion to the same `EffectSpec` that
already drives the background, amplified by a fixed depth factor, across
**all** ten directions (not just zoom) — a real multiplane depth cue instead
of an emergent side effect of one direction.

## Goals

- Character (near plane) moves/zooms in the *same direction* as the
  background (far plane), amplified by a fixed factor — this is what makes
  it read as parallax rather than "two unrelated animations."
- Covers all 10 entries in `_DIRECTION_POOL` (pans, diagonals, in/out-center,
  static), not just zoom — the artifact that prompted this was zoom-only, but
  a real depth cue is more convincing shown consistently across cuts.
- Character never leaves the frame at any point in its animation, at any
  depth-amplified extreme — this is a hard constraint, not a nice-to-have
  (the character clipping off-frame is a regression, not an edge case).
- No new file — this extends the *same* Ken Burns motion system already in
  `video.py` (`EffectSpec`, `select_effect`, `_zoompan_filter`), unlike the
  sound-design/color-grade specs which are genuinely separate concerns. New
  functions live in `video.py` itself.

## Approach

Considered and rejected: an independent, randomly-selected `EffectSpec` for
the character (decoupled from the background's). Rejected because parallax
specifically requires the *same* direction at different magnitude — a
background panning right while the character independently pans left would
read as broken, not as depth.

**Chosen**: derive the character's `EffectSpec` from the background's,
amplifying only the zoom delta, direction unchanged:

```python
CHAR_DEPTH_FACTOR = 1.3  # ponytail: fixed constant, tune via live-render QA
                         # (same iteration style as Story 5.3's ZOOM_IN_MAX 1.08->1.15)

def _character_spec(bg_spec: EffectSpec) -> EffectSpec:
    """Same direction as the background; zoom deviation from 1.0 amplified."""
    return EffectSpec(
        direction=bg_spec.direction,
        start_zoom=1.0 + (bg_spec.start_zoom - 1.0) * CHAR_DEPTH_FACTOR,
        end_zoom=1.0 + (bg_spec.end_zoom - 1.0) * CHAR_DEPTH_FACTOR,
    )
```

This formula is direction-agnostic and handles `static` (1.0→1.005 delta is
tiny, stays tiny after amplification) with no special-casing.

## Character zoom: `scale`, not `zoompan`

The background uses `zoompan` because it needs to crop-and-pan across a
large source image. The character layer doesn't need cropping — it's a
small transparent PNG composited via `overlay`. Growing/shrinking it over
time is a `scale` filter with a time-varying expression and `eval=frame`
(the same `eval=frame` requirement `_overlay_filter` already documents for
its sway/bob sines — zoompan's alpha-channel handling is the other reason to
avoid it here):

```
scale=w='iw*({start}+({end}-{start})*t/{duration})':h='ih*(...)':eval=frame
```

applied to the character stream right after the existing
`_character_scale_filter()` cap, before `overlay`. Because `overlay`'s
`overlay_w`/`overlay_h` re-evaluate every frame under `eval=frame`, the
existing centering formula `(main_w-overlay_w)/2` keeps the growing/shrinking
character centered with no extra math.

## Character pan: extend the existing overlay x/y expression

`_overlay_filter` currently positions the character with sway/bob sines only.
Add a macro pan term derived from `spec.direction`, on top of (not replacing)
the existing sway/bob — they serve different purposes at different
timescales: sway/bob is constant-amplitude "alive" idle motion, the new term
is the shot-duration-scale depth cue tied to the camera move.

**Sign warning**: the background's `pan-right` crop-space expression
(`x_expr = (iw-iw/zoom)*on/frames`) moves the *crop window* rightward across
the source, which makes the visible content appear to drift **left** on
screen (classic pan-camera semantics — the background streams past opposite
the crop direction). The character's pan term must match the background's
*apparent on-screen* motion direction (amplified), not the crop-window's own
sign — getting this backwards makes the character drift opposite the
background, which is the exact bug this spec exists to prevent. **This must
be verified against a live render for each of the 10 directions before
merging** — sign correctness is a visual judgment call, not something to
derive from the crop-math convention alone and trust blindly.

Pan amplitude is a new fixed constant (`CHAR_PAN_AMPLITUDE_PX`, exact value
tuned by eye during implementation, same as `ZOOM_IN_MAX`'s own history) —
deliberately conservative relative to the background's own effective pan
range, since it stacks with the zoom growth below.

## Required fix: motion-safe character box must account for zoom growth

`CHAR_MAX_W`/`CHAR_MAX_H` (`video.py`) are currently sized only for the
*fixed*-size character plus sway/bob excursion:

```python
CHAR_MAX_W = COMP_W - 2 * SWAY_AMPLITUDE
CHAR_MAX_H = COMP_H - 2 * BOB_AMPLITUDE
```

With character zoom now reaching up to `1.0 + (ZOOM_IN_MAX - 1.0) *
CHAR_DEPTH_FACTOR ≈ 1.195` at its peak, a character already capped to the old
`CHAR_MAX_W`/`H` would grow ~19.5% past frame edges at the extreme of an
in-center shot. **This is not an edge case to note and defer — it is a
correctness requirement of this spec.** The box must shrink to leave room for
the peak zoom *before* sway/bob is applied:

```python
CHAR_MAX_ZOOM = 1.0 + (ZOOM_IN_MAX - 1.0) * CHAR_DEPTH_FACTOR
CHAR_MAX_W = (COMP_W - 2 * SWAY_AMPLITUDE) / CHAR_MAX_ZOOM
CHAR_MAX_H = (COMP_H - 2 * BOB_AMPLITUDE) / CHAR_MAX_ZOOM
```

`_character_scale_filter()` itself is unchanged — it already reads these two
module constants, so shrinking them is sufficient.

## Settings

```python
# src/yt_flow/config.py
parallax_enabled: bool = True   # same pattern as chapter_cards / sound_design_enabled / post_fx_enabled
```

`CHAR_DEPTH_FACTOR`, `CHAR_PAN_AMPLITUDE_PX` are fixed `video.py` module
constants, matching the `SWAY_AMPLITUDE`/`ZOOM_IN_MAX` precedent — no
per-scene config.

## Testing

`_character_spec` is a pure function — unit test asserts the zoom-delta
amplification math for a representative direction (`in-center`, `out-center`,
`static`) and that `direction` passes through unchanged. `_character_zoom_filter`
and the extended `_overlay_filter` are pure string-building functions tested
the same way `_zoompan_filter` already is (assert the returned filter string
contains the expected `scale=`/`eval=frame` fragments). A `CHAR_MAX_W`/`H`
regression test asserts the shrunk box divided by `CHAR_MAX_ZOOM` stays
within `COMP_W`/`COMP_H` minus the sway/bob amplitude — i.e. the invariant
this spec exists to preserve is itself checked, not just eyeballed.

## Error handling

No new failure modes — this is pure filter-graph math over already-validated
inputs (`character_path` presence is already validated by
`_validate_scene_assets`). `parallax_enabled = False` reverts `_overlay_filter`
and the character scale step to today's fixed-size, sway/bob-only behavior.
