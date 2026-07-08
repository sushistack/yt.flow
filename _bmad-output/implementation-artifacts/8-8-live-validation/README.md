# Story 8.8 live validation — micro-motion techniques

Stubbed two-scene sample (synthetic colored RGBA cards, not real character art —
this validates the FFmpeg motion filtergraph itself, not scenario/image
generation). 3 cards, 4 seconds, 1920x1080, real ffmpeg:

- **BREATH** (left, medium energy) — default idle motion for ordinary figures
- **TREMBLE** (center, high energy) — anxious/hurt/restrained subjects
- **HOLD** (right, medium energy) — statues/corpses, no idle motion at all

`motion_sample.mp4` is the full render; `frame_t{0,1,2,3}.0.png` are frame
grabs at each second.

## Quantitative motion evidence

Sampled at 10fps, tracked each card's bounding box by color across the full
clip (`analyze.py`, not committed — scratch tooling):

```
BREATH:  x Δ4px   y Δ12px
TREMBLE: x Δ12px  y Δ20px
HOLD:    x Δ0px   y Δ0px
```

This matches the design intent exactly:
- HOLD never moves a single pixel — the "no idle motion at all" contract holds.
- BREATH moves the least (a small vertical bob only, per Interfaces: "barely
  perceptible alive cue").
- TREMBLE moves visibly more than BREATH on both axes (its own shake layered
  on top of breath's bob), without any card leaving safe framing.

No card's bounding box approaches the frame edges in any sampled frame —
consistent with the AC:7 off-frame invariant regression test
(`test_char_max_box_reserves_scale_pulse_growth`).

## What this does NOT validate

This is a mechanism check, not a taste check. Whether the motion actually
*reads as alive* rather than distracting on a real character card composited
over a real background — the actual DoD ask — is a subjective call that
needs a real render (real cast cards + real backgrounds) and Jay's eyes, not
a synthetic colored rectangle. Recommend a quick real-SCP render pass before
fully closing that judgment call; the mechanism itself (per-style amplitude,
decorrelation, off-frame safety) is verified working here and by the
automated test suite.
