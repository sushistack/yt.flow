---
baseline_commit: b9b066f13d8ccea5f3bc9607908d21268a3e72f6
---

# Story 1.9c: video effects — transparent character layer + idle motion

Status: done

Depends on:
- **Story 1.6b (`image_node` layered assets)** — DONE. Emits `background_path` + optional transparent `character_path` per `ShotData`.
- **Story 1.9b** — DONE. The `zoompan` background motion this story layers a moving character on top of.

<!-- Origin: deep-research (2026-07-01). Both prerequisites now done; promoted to in-progress for dev. -->

## Story

As Jay,
I want a transparent-PNG character composited over the (already Ken-Burns'd) background with subtle idle motion (breathing/bob/sway),
so that character-driven scenes feel alive instead of a flat pasted cutout — the differentiating layer above the 1.9b baseline.

## Blocking design decision (resolve before dev)

Idle motion needs the character as its own layer. That requires **either**:

- **Option A — layered assets:** `image_node` outputs `background_path` + `character_path` (transparent PNG) per shot; add both to `ShotData`. `video_node` does `zoompan` on background, then `overlay` the character with sin(t) motion.
- **Option B — segmentation at video time:** keep one composed `image_path` and matte the character out in `video_node` (e.g. rembg / alpha model). Adds a heavy ML dependency → violates minimal-deps. `# ponytail: reject unless A is impossible — matting a flattened image is strictly worse than never flattening it`

Recommendation: **Option A**. It's the smaller total change and avoids a segmentation dependency. This story assumes A.

## Acceptance Criteria

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
- `1-6b-image-layered-assets.md` (must extend `image_node` to emit layered assets — Option A)
- `1-6-image-node.md` (baseline image-node implementation)
- FFmpeg overlay docs: https://ffmpeg.org/ffmpeg-filters.html ; https://github.com/endcycles/ffmpeg-engineering-handbook/blob/main/docs/advanced/overlays.md

## Tasks / Subtasks

- [x] Add idle-motion overlay filter builder to `video.py`. (AC: 1, 2)
  - [x] Module constants for sway (x) + bob (y) amplitude/frequency per Tasteful-defaults table.
  - [x] `_overlay_filter()` returns the `overlay=x=…:y=…:eval=frame` chain; `eval=frame` set explicitly.
- [x] Branch `_compose_scene` on presence of `character_path`. (AC: 1, 3)
  - [x] Character present → `-filter_complex`: `[0:v]<zoompan>[bg];[bg][1:v]<overlay>[ov];[ov]subtitles=…[out]`, two looped image inputs + audio, `-map [out] -map 2:a`.
  - [x] Character absent → unchanged 1.9b `-vf` Ken-Burns-only path (background_path or image_path).
  - [x] Prefer `background_path` for the Ken-Burns layer; fall back to `image_path`.
- [x] Validate a set-but-missing `character_path` loudly. (AC: 1)
  - [x] `_validate_scene_assets` raises `FileNotFoundError` when `character_path` is set and the file is absent.
- [x] Extend observability. (AC: 4)
  - [x] Per-scene `effects` metadata gains `character_overlay` bool; trace gains character-motion params + character-scene count.
- [x] Tests. (AC: 1–4)
  - [x] `_overlay_filter` contains `overlay=`, `sin(t*`, `eval=frame`, and NOT `eval=init`.
  - [x] Character-present scene emits `-filter_complex` with overlay + `eval=frame`, maps `[out]`/audio.
  - [x] Character-absent scene uses `-vf` with no overlay (1.9b fallback).
  - [x] `_validate_scene_assets` raises on set-but-missing character.
  - [x] Trace metadata carries character-motion params + count.
  - [x] Real-ffmpeg integration (skippable): layered filtergraph renders rc=0.

## Review Findings

Adversarial review (Blind Hunter + Edge Case Hunter + Acceptance Auditor), 2026-07-01. All 4 ACs verified genuinely met. 1 patch applied, 1 deferred, 3 dismissed.

- [x] [Review][Patch] Character overlay never sized to composition — oversized asset clips/overflows, full-frame character sways off-frame (no coord clamp) [src/yt_flow/pipeline/nodes/video.py] — image_node writes character bytes raw (never scaled), so overlay ran at native size. Fixed with `_character_scale_filter()`: downscale-only, AR-preserving cap to COMP minus sway/bob amplitude so the centered sine excursion always stays on-frame.
- [x] [Review][Defer] Multi-shot scene renders only shot[0]; a character on a later shot is silently dropped and unvalidated [video.py `_compose_scene`] — deferred, pre-existing single-segment-per-scene limitation inherited from 1.9/1.9b (already tracked from the 1.9b review). 1.9c only widens the surprise via the per-shot `character_path` field.
- [x] [Review][Dismiss] Force `format=rgba` on the character input — already guaranteed upstream: `image_node` raises `ComfyUIError` on a non-alpha character (`_has_alpha`, image.py:181), so a non-RGBA character never reaches `video_node`; `overlay` honours native PNG alpha.
- [x] [Review][Dismiss] `subtitles=` escaping incomplete for the filter_complex context (`;` `[` `]`) — ffmpeg single-quoting makes those literal inside `subtitles='…'`; identical pre-existing exposure in the 1.9b `-vf` path, not a regression.
- [x] [Review][Dismiss] `background_path`-only shot selection latent bug — not reachable: `image_node` always sets `image_path` (background copied to it), so the `image_path`-keyed shot selection never skips a valid shot.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8[1m]

### Completion Notes

- Both prerequisites were already merged: `ShotData` carries `background_path`/`character_path` (1.6b) and `video.py` does per-shot zoompan + xfade (1.9b). This story only added the character overlay layer on top — no state or image-node changes needed.
- `_overlay_filter()` builds a centered `overlay` with a sway sine on x (12px @ 0.8 rad/s) and a bob sine on y (8px @ 1.2 rad/s), `eval=frame` set explicitly. A unit test asserts `eval=frame` present / `eval=init` absent (AC 2 freeze-regression guard), and a live-ffmpeg integration test renders the full `zoompan→overlay(eval=frame)` filtergraph at rc=0.
- `_compose_scene` now branches: character present → single `-filter_complex` (bg zoompan → overlay → subtitles) with two looped image inputs + audio, mapping `[out]`/`2:a`; character absent → the unchanged 1.9b `-vf` path. Ken-Burns layer prefers `background_path`, falls back to `image_path` for non-layered (1.9/1.9b) shots.
- `_validate_scene_assets` fails loudly on a set-but-missing `character_path` (a dropped character is worse than a hard error); `character_path=None` stays a valid background-only shot.
- Trace/`effects` metadata gains per-scene `character_overlay` bool plus a run-level `character_scenes` count and the `character_motion` param block.
- Deferred (noted in story): per-character amplitude/phase randomization to avoid a templated look — AC only says "Consider"; add when repetition is actually observed. Tremble motion is out of scope until a scene requests it.
- All 264 tests pass (14 new for 1.9c); ruff clean.

### File List

- `src/yt_flow/pipeline/nodes/video.py`
- `tests/pipeline/nodes/test_video.py`
- `_bmad-output/implementation-artifacts/1-9c-video-character-idle-motion.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

### Change Log

- 2026-07-01: Story 1.9c implemented — transparent-character overlay with sinusoidal idle motion (sway + bob) composited over the Ken-Burns background. Added `_overlay_filter()` + motion constants, branched `_compose_scene` on `character_path` (filter_complex overlay vs. 1.9b `-vf` fallback), character-path validation, and character-motion observability. 14 new tests (incl. live-ffmpeg filtergraph render). Status: blocked → in-progress → review.
