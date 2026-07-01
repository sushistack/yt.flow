# Story 1.9c: video effects — transparent character layer + idle motion

Status: blocked

Depends on:
- **Story 1.6 (`image_node`) extension** — must emit a *transparent-background character PNG* separate from the background image. The current single `ShotData.image_path` model cannot carry two layers; this is the blocking prerequisite.
- **Story 1.9b** — the `zoompan` background motion this story layers a moving character on top of.

<!-- Origin: deep-research (2026-07-01). Kept lean; promote to ready-for-dev once 1.6 emits layers and the state change below is agreed. -->

## Story

As Jay,
I want a transparent-PNG character composited over the (already Ken-Burns'd) background with subtle idle motion (breathing/bob/sway),
so that character-driven scenes feel alive instead of a flat pasted cutout — the differentiating layer above the 1.9b baseline.

## Blocking design decision (resolve before dev)

Idle motion needs the character as its own layer. That requires **either**:

- **Option A — layered assets:** `image_node` outputs `background_path` + `character_path` (transparent PNG) per shot; add both to `ShotData`. `video_node` does `zoompan` on background, then `overlay` the character with sin(t) motion.
- **Option B — segmentation at video time:** keep one composed `image_path` and matte the character out in `video_node` (e.g. rembg / alpha model). Adds a heavy ML dependency → violates minimal-deps. `# ponytail: reject unless A is impossible — matting a flattened image is strictly worse than never flattening it`

Recommendation: **Option A**. It's the smaller total change and avoids a segmentation dependency. This story assumes A.

## Acceptance Criteria (draft — finalize after 1.6 extension)

1. Given a shot with `background_path` and `character_path`, when `video_node` renders the segment, then the background carries `zoompan` motion (from 1.9b) and the character is `overlay`-composited on top with a continuous sinusoidal idle motion.
2. Given `eval` is not explicitly set, when the overlay renders, then motion animates per-frame (must verify `eval=frame`); a regression that freezes motion (NAN under `eval=init`) fails a test.
3. Given a shot has no `character_path` (background-only), when `video_node` renders, then it falls back to the 1.9b Ken-Burns-only path with no overlay.
4. Error/observability contracts identical to 1.9/1.9b (`stage="video"`, span metadata gains character-motion params).

## Verified FFmpeg recipe

Character sway/bob over an animated background (background already produced as `[bg]`):
```
[bg][char]overlay=\
  x='(main_w-overlay_w)/2 + sin(t*0.8)*12':\
  y='(main_h-overlay_h)/2 + sin(t*1.2)*8'\
  :eval=frame[out]
```
- Variables `main_w/main_h` (bg), `overlay_w/overlay_h` (char), `t` (sec), `n` (frame) are documented overlay params; verified against a live ffmpeg 8.0.1 render (position matched sin(t) exactly). [ffmpeg docs]
- **Critical:** `eval=frame` is the default and is required — under `eval=init`, `t`/`n` → NAN and the character freezes. Set it explicitly and test it (AC 2). [ffmpeg docs]
- Tremble = sum two sines at different freq/amplitude on the same axis. Breathing = small-amplitude (~6–8px), slow (~1.2 rad/s) vertical `y` sine. Sway = larger (~12px), slower (~0.8 rad/s) horizontal `x` sine.

## Tasteful defaults

| Motion | Axis | Amplitude | Frequency | Notes |
|---|---|---|---|---|
| Breathing/bob | y | 6–8 px | ~1.2 rad/s | almost subliminal |
| Sway | x | 10–14 px | ~0.6–0.8 rad/s | idle drift |
| Tremble | x (+y) | 2–4 px | 8–12 rad/s | tense scenes only |

Consider randomizing amplitude/phase per character so many videos don't look templated (open question from research — no source addressed anti-repetition for automated pipelines).

## Non-goals

Rigged/skeletal animation, lip-sync, physics, per-limb motion. If real character animation is ever wanted, that's a generative-video path (Runway/Veo class), not FFmpeg — out of this project's scope. `# ponytail: sinusoidal idle motion is the ceiling here by design`

## References

- `1-9b-video-effects-kenburns-transitions.md` (baseline background motion + shared error/observability contract)
- `1-6-image-node.md` (must be extended to emit layered assets — Option A)
- FFmpeg overlay docs: https://ffmpeg.org/ffmpeg-filters.html ; https://github.com/endcycles/ffmpeg-engineering-handbook/blob/main/docs/advanced/overlays.md

## Dev Agent Record

### Agent Model Used
TBD by dev agent
