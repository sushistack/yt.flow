# Story 8.9 live validation — character locomotion and screen blocking

Stubbed one-scene sample rendered through the real `_compose_scene` (not a
reimplementation of the filtergraph — same code path `video_node` uses),
synthetic colored RGBA cards over a synthetic background, real ffmpeg. 3
cards, 4 seconds, 1920x1080, `parallax_enabled=True`:

- **ANCHORED** (blue, left, mid depth) — `movement_mode="anchored"`, the
  no-travel default; only 8.8 idle motion (breath) and 7.3 parallax apply.
- **ENTER** (green, center, mid depth) — `movement_mode="enter"`,
  `movement_direction="left"`, `movement_pace="medium"` — starts offscreen
  left, settles at its declared center/mid position.
- **APPROACH** (red, right, near depth) — `movement_mode="approach"`,
  `movement_direction="in"`, `movement_pace="medium"` — looms from a
  shallower depth plane to the declared near depth (a threat-reveal beat).

`motion_sample.mp4` is the full render; `frame_t{0,1,2,3,3.9}.png` are frame
grabs.

## Quantitative motion evidence

Sampled 5 frames across the clip, tracked each card's bounding box by color
(`analyze.py`, not committed — scratch tooling):

```
              t=0.0              t=1.0              t=2.0              t=3.0              t=3.9
ANCHORED  (504,270,777,807) (501,273,780,819) (501,270,777,816) (504,267,774,804) (504,264,777,798)
ENTER     offscreen         offscreen         (684,264,954,798) (822,267,1089,804) (819,267,1089,816)
APPROACH  (1143,267,1413,798)(1128,231,1431,831)(1098,186,1461,897)(1092,180,1467,915)(1092,177,1467,909)
```

- **ANCHORED**: left/right edges hold within a 501-504px / 774-780px band for
  the whole clip — no locomotion. The few-pixel wobble is 8.8's breath idle
  motion riding on top, not travel (AC:5,10).
- **ENTER**: undetected (fully offscreen) at t=0 and t=1, appears mid-transit
  at t=2, and settles into a stable 822-1089px / 819-1089px window by t=3
  that holds through t=3.9 — starts outside frame and arrives at the
  declared position, matching the mode contract (AC:7,8).
- **APPROACH**: on-screen for the whole clip (approach scales toward camera,
  it doesn't travel from offscreen), but its width grows from 270px (t=0) to
  375px (t=3.9) — a ~39% size increase toward the declared near depth, with
  top/bottom edges expanding roughly around its anchor (a ~10px vertical
  centroid shift alongside the scale change, consistent with idle-motion
  wobble riding on top rather than the movement curve itself) — a
  scale-dominant looming move, negligible x drift (AC:5,7).

No card's settled frame reaches into the lower subtitle-safe band, and the
z-order (blue painted first/leftmost depth "mid", green "mid", red "near"
painted last/on top) stayed stable across every sampled frame — consistent
with the AC:8/AC:9 off-frame and z-order-stability regression tests
(`test_video.py`, `test_character_movement.py`).

## What this does NOT validate

This is a mechanism check, not a taste check — synthetic colored rectangles,
not real character art over a real background. Whether `enter`/`approach`
reads as intentional cinematic blocking versus a sliding sticker (the actual
DoD ask, AC:14) needs a real render with real cast cards and Jay's eyes.
Recommend a real-SCP render pass with a motivated shot beat (a door entrance,
a looming threat reveal) before broadening `movement_mode` use in the prompt
beyond what `cast_decision.md` already recommends "sparingly, at most once
or twice per scene." The mechanism itself (curve shape, off-frame safety,
z-order stability, composition order) is verified working here and by the
automated test suite (`tests/pipeline/nodes/test_character_movement.py`,
`tests/pipeline/nodes/test_video.py`).
