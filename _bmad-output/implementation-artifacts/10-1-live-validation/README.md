# 10.1 Live Validation — Grounding & Compositing off/on Frame Evidence

Evidence for Story 10.1. The question: **are the cast cards attached to the plate, or pasted on it?**
Jay raised findings 3 ("characters look torn out and pasted onto the background") and 11 ("characters
float") after watching run `8a9a288b-800f-4c73-88a2-25ae6b5a4d7d` (SCP-049, 3:06) on 2026-08-08.

That run was rendered with `YTFLOW_DEPTH_PLACEMENT_ENABLED=false`, so **Story 8.16 depth-aware ground
placement was off**. Findings 3/11 therefore never tested the feature — they only recorded what the
video looked like without it. This directory holds the controlled comparison that does test it.

**Verdict: STILL FLOATING → primary broken link `harmonization`.** Full reasoning, the ground_y table,
and the clamp measurement are in `../10-1-grounding-composite-live-verification.md`.

## Why a video-only re-render, not a fresh run

The shot seed is `_shot_seed(run_id, scene_num, shot_id)` — the run id is in the hash — and the
scenario stage regenerates per run. **A new SCP-049 run produces different backgrounds, a different
shot list and different narration**, so its frames cannot be paired with `8a9a288b`'s. Re-running only
the `video` stage keeps the same 66 plates, the same cards, the same script and the same shot ids, and
changes exactly one thing: the flag.

A useful side effect: the plate's Ken Burns chain is untouched between the two renders, so the
backgrounds in each pair get **identical treatment**. Every *meaningful* difference inside a pair is
the card, its contact shadow, or its occlusion mask, which makes a numeric frame diff a precise
instrument.

They are not bit-identical, though — these are two separate h264 encodes, and background-only regions
measure a **~0.87 mean luminance noise floor**. So the method only works **with a control band inside
the same frame pair**: sample the region under test and a background region at the same y, and compare
the two. That is how the contact shadow was measured (**+15.7** luminance under the feet against
**+0.05** and **−0.02** in two controls, 78% of pixels shifted by >8 levels) and how an incorrect
"no shadow" eyeball reading got corrected. Reading absolute diff values without a control would have
put a 0.87 noise floor and a 15.7 signal on the same scale.

## Layout

| Path | What it is |
|---|---|
| `off/*.png` | Frames from the **features-off** render, extracted **before** anything re-rendered |
| `off/*.mp4` | The six source clips from the off-state render (gitignored) |
| `off/video_off.mp4` | Full off-state video, 56 MB (gitignored — this is the only surviving copy of the render Jay watched) |
| `on/*.png` | Frames from the **features-on** render, same shot ids, same timestamps |
| `pairs/*_pair.jpg` | `off | on` side by side, labelled — the adjudication artifacts |
| `pairs/_zoom_*.jpg` | 2× close reads of contact regions used to reach the verdict |
| `make_pairs.sh` | Rebuilds `on/` and `pairs/` from the workspace. Never touches `off/` |

`off/` is irreplaceable and **must not be regenerated**: `video.py:1885` unlinks every
`shots/scene_NNN_*.mp4` before re-rendering a scene, and the segment/final concat overwrite in place.
The off-state exists only because it was copied out at 18:22 KST, before the 18:24:27 retry.

## The slate

Six shots, chosen to span all three card depth bands, three positions, and both the one-card and
two-card cases. Only 42 of the run's 66 images have a clip in `shots/` (8.11 per-shot cut assembly
merges and drops shots) and 31 of those carry cast, so the slate is drawn from that intersection.

| clip | t | cards (depth / position) | what it isolates |
|---|---|---|---|
| `scene_001_S00102` | 1.5 s | SCP-049 far/right | smallest card; largest off-state float (~280 px above the floor) |
| `scene_001_S00101` | 1.5 s | STOCK-d-class mid/left | the only plate with an unambiguous floor line and a scale reference (a stool) |
| `scene_002_S00203` | 2.4 s | SCP-049 mid/center | centre position — separates the x anchor from the ground line |
| `scene_002_S00202` | 3.1 s | SCP-049 near/right | brightest plate; contact shadow and harmonization are most visible here |
| `scene_001_S00104` | 1.2 s | SCP-049 near/right + STOCK-d-class mid/left | two depth bands in one frame — band ordering checkable inside a single image |
| `scene_004_S00403` | 1.2 s | SCP-049 near/right + STOCK-d-class near/left | two cards, same band — they must share a ground line |

Timestamps are mid-clip, where Ken Burns drift is largest and a static anchor visibly slides.

## Reading the pairs

1. **Do the feet meet a surface?** Four of six do in the on-state; none did in the off-state.
2. **Does the card size agree with its depth band?** `_CARD_HEIGHT_FRAC = far 0.379 / mid 0.516 / near 0.688`. Card scale is *not* gated on the flag — it is the same in both halves.
3. **Is there a shadow where the feet touch?** Present but faint. Measure, do not eyeball; see above.
4. **Do card and plate share a colour and light cast?** They do not. This is the verdict's named link.

Two plates cannot answer question 1 at all: `S00202` is a brick wall and `S00203` is a top-down
corridor whose floor is nowhere near the card. No placement algorithm puts a figure on a floor the
plate does not contain — those are routed to stories 10.2 and 10.4, not fixed here.

## What this evidence does NOT cover

**Story 11.5 2.5D parallax was not exercised.** `video.py:707` reads `depth_map_path` from checkpoint
state, and `8a9a288b`'s image stage ran with the depth resolver gated off, so **0 of 66 shots carry
that key**. Every shot logged `fell back to legacy zoompan (no_depth_map)`. `parallax_25d_enabled` was
`True` the whole time and was inert — the flag being on is not evidence the feature ran. These pairs
isolate **8.16 ground placement + contact shadow + 8.7 harmonization (tier 1)** and nothing else.
A parallax-on comparison needs a fresh run, because re-running the image stage with depth on would
destroy the shot-matched plates this comparison depends on.

## Reproducing

```bash
# off/ is already on disk and must not be regenerated.
systemctl --user stop ytflow-api && systemctl --user reset-failed ytflow-api
# recreate the transient unit with YTFLOW_DEPTH_PLACEMENT_ENABLED=true
# (the unit is transient — `systemctl --user restart` re-uses the old ExecStart and keeps depth=false)
curl -X POST localhost:8000/runs/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d/stages/video/retry
./make_pairs.sh
```

**Never retry the `image` stage on this run.** `_delete_image_artifacts` deletes all 66 rendered PNGs;
a previous session did exactly that. The comparison is unreproducible afterwards.
