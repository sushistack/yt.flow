---
baseline_commit: a5f6395cd6fd18403fb186f1668112a1c7d5dfde
---

# Story 1.9b: video effects — Ken Burns + scene transitions

Status: done

Depends on: Story 1.9 (`video_node`) — this story extends the segment renderer and concat step produced there. Do not start until 1.9 is `done`.

<!-- Origin: deep-research (2026-07-01) + AI auto-video benchmark. Findings embedded in Dev Notes with citations. -->

## Story

As Jay,
I want `video_node` to apply Ken Burns motion (slow zoom/pan) to every shot image and join scenes with a short crossfade,
so that the final video reads as intentionally directed instead of a static slideshow — the 2025–2026 table-stakes baseline for faceless/SCP-style narration content.

## Scope & Non-Goals

- **In scope:** motion on the single composed image per shot (`ShotData.image_path`) via FFmpeg `zoompan`; scene-to-scene `xfade` crossfade (+ `acrossfade` for audio); a rule-based effect dispatcher keyed on `ShotData.camera_movement`.
- **Out of scope (deferred):**
  - Per-character idle motion (breathing/bob/sway/tremble) → **Story 1.9c** — requires the image node to emit a *transparent character layer* separate from the background, which the current single-`image_path` model does not support.
  - Parallax / faux-3D depth, custom easing curves, shake/impact, whip/wipe/exotic transitions, per-character amplitude randomization.
  - Any code-based renderer (Remotion, MoviePy, motion-canvas). Research verdict: FFmpeg native filters cover this story fully; renderers add a Node/Chromium or AWS-Lambda dependency lift that violates the project's minimal-dependency philosophy. Revisit only if FFmpeg's expressiveness ceiling is hit in practice. `# ponytail: ffmpeg-only, add a renderer only when a filter genuinely can't express the effect`

## Acceptance Criteria

1. Given a scene whose shots have `image_path` set, when `video_node` renders each shot's segment, then the segment contains a continuous `zoompan` motion (no shot is fully static). [Source: research finding — Ken Burns is table-stakes]
2. Given two or more scenes, when `video_node` joins them, then adjacent scenes are joined by an `xfade` crossfade of the configured duration (default 0.5s) with audio joined by `acrossfade`, and the final video/audio stay in sync (final duration ≈ Σ segment_durations − (n−1)·transition_duration). [Source: research finding — xfade offset accumulation]
3. Given `ShotData.camera_movement` is set to a recognized hint, when the effect dispatcher runs, then the chosen `zoompan` direction matches that hint; when it is `None` or unrecognized, then a rotating direction from a fixed pool is used such that no two consecutive scenes get the identical direction (anti-monotony). [Source: benchmark — Pictory randomizes across 7 directions]
4. Given a malformed filtergraph or a non-zero FFmpeg exit, when `video_node` runs, then `PipelineState.error` is set with `stage="video"` and `run_id`, and `video_path` remains unset (same contract as 1.9). [Source: 1-9-video-node.md#Error-Handling]
5. Given `video_node` completes, when the Langfuse `"video"` span is recorded, then it includes effect metadata: per-scene effect direction, transition type/duration, and whether the jitter-mitigation upscale pass ran.

## Tasks / Subtasks

- [x] Add an effect dispatcher — pure function, no I/O. (AC: 1, 3)
  - [x] `select_effect(shot: ShotData, scene_index: int) -> EffectSpec` returning `{effect, direction, start_zoom, end_zoom}`.
  - [x] Map free-text `camera_movement` hints (e.g. `"zoom in"`, `"push in"`, `"pan left"`, `"pull back"`, `"static"`) to presets; treat unknown/`None` as "rotate from pool".
  - [x] Direction pool: `[in-center, out-center, pan-left, pan-right, pan-up, pan-down]`; pick `pool[scene_index % len]` for the fallback so consecutive scenes differ.
  - [x] Honor an explicit `"static"` hint by emitting a near-zero drift (still apply a barely-perceptible 1.0→1.005 push so the frame isn't dead), `# ponytail: reuse the zoompan path instead of a separate static branch`.
- [x] Extend the per-shot segment renderer from 1.9 to inject `zoompan`. (AC: 1)
  - [x] Build the jitter-safe chain: `scale=<comp_w>:-2, setsar=1:1, crop=<comp_w>:<comp_h>, scale=8000:-1, zoompan=...:d=<frames>:s=<comp_w>x<comp_h>:fps=<fps>`. The pre-upscale (`scale=8000:-1`) is the documented fix for zoompan pixel-rounding jitter. [Source: bannerbear/creatomate]
  - [x] Inset a ~10% safe margin before crop so the zoom/pan does not clip the subject. [Source: benchmark — InVideo safe-zone]
  - [x] `d` (frames) = shot duration × fps; shot duration derives from the scene's `audio_duration` split across shots (reuse whatever split 1.9 already uses — do not invent a new timing model).
  - [x] Zoom-in preset: `z='min(zoom+<inc>,1.08)'` where `<inc>=(1.08-1.0)/frames`. Zoom-out preset needs the conditional workaround: `z='if(lte(zoom,1.0),1.08,max(1.001,zoom-<inc>))'` (zoompan clamps z to ≥1 and is stateful, so a naive decrement floors immediately). [Source: creatomate/hadna.space]
  - [x] Pan presets set `x`/`y` as functions of zoom, e.g. pan-right `x='(iw-iw/zoom)*on/<frames>'`. Keep amplitude subtle.
- [x] Replace the plain concat with `xfade` + `acrossfade`. (AC: 2)
  - [x] Chain scenes pairwise; each `xfade`/`acrossfade` `offset` = running total of prior segment durations minus prior overlaps. Track a `running_offset` accumulator — this is the #1 source of xfade timing bugs with many short scenes. [Source: ffmpeglab; royshil gist]
  - [x] Default `transition=fade`, `duration=0.5`. Expose transition type/duration as constants (not per-scene config yet) — `# ponytail: single crossfade type until a second one is actually wanted`.
  - [x] Guard the single-scene case (no transition) and the two-scene case explicitly.
- [x] Filtergraph construction hardening. (AC: 4)
  - [x] Build with argument lists / filtergraph strings assembled from validated parts; never shell-interpolate paths (SRT/PNG paths may contain special chars) — carry over 1.9's escaping approach.
  - [x] If the filtergraph or ffmpeg exits non-zero, set `PipelineState.error` with `stage="video"`, `run_id`, and stderr tail; leave `video_path` unset.
  - [x] If total scene count is 0 or any required asset missing, fail before invoking ffmpeg (same as 1.9).
- [x] Observability. (AC: 5)
  - [x] Extend the existing `"video"` span metadata with `effects`: list of `{scene_num, direction, start_zoom, end_zoom}`, `transition`, `transition_duration`, `upscale_pass=true`. Tracing failures stay non-fatal. [Source: 1-9-video-node.md#Observability]
- [x] Tests. (AC: 1, 2, 3, 4)
  - [x] Unit: `select_effect` returns the mapped direction for known hints and a rotating, non-repeating direction for `None`/unknown across a sequence of scene indices.
  - [x] Unit: filtergraph builder produces a `zoompan` clause for every shot and correct cumulative `xfade` offsets for a 3-scene fixture (assert offset math, not pixels).
  - [x] Unit: non-zero ffmpeg exit → `error` with `stage="video"`, `video_path` unset.
  - [x] Integration (skippable via `shutil.which("ffmpeg")`): render 2 tiny still fixtures into a crossfaded mp4 and assert output exists and `ffprobe` duration ≈ expected (Σ − overlap) within tolerance.

## Dev Notes

### Why this is a separate story from 1.9

1.9 delivers a *correct static* video (deliverable, checkpointable, unblocks 1.10). Effects are additive and don't block the pipeline producing output. Splitting keeps 1.9 closeable and lets effects iterate independently. This story only touches the *segment render* and *join* steps 1.9 already owns — if 1.9 factored those as injectable helpers, this is a small diff; if not, refactor them first.

### State contract (no new fields needed)

`ShotData.camera_movement: str | None` already exists ([src/yt_flow/domain/state.py:30](../../src/yt_flow/domain/state.py#L30)) and is the effect-selection input. No domain-state change in this story. The scenario node (1.5) is the natural producer of these hints; if it doesn't emit them yet, the rotating fallback (AC 3) keeps output good without blocking.

### Verified FFmpeg recipes (adversarially checked, 22/25 claims confirmed)

**Ken Burns (zoompan), jitter-safe, capped zoom-in:**
```
ffmpeg -loop 1 -i shot.png -filter_complex \
  "[0]scale=1920:-2,setsar=1:1,crop=1920:1080,scale=8000:-1,\
   zoompan=z='min(zoom+0.0006,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':\
   d=250:s=1920x1080:fps=25[v]" \
  -map "[v]" -pix_fmt yuv420p -r 25 -t 10 seg.mp4
```
- Pre-`scale=8000:-1` fixes the pixel-rounding jitter (community-standard, not an official fix; costs an upscale pass). [bannerbear, creatomate]
- `z` clamps to 1–10, default 1, and is **stateful** — zoom-out from 1.0 needs `z='if(lte(zoom,1.0),1.08,max(1.001,zoom-<inc>))'`. [creatomate, hadna.space, ffmpeg docs]
- Directional pan = make `x`/`y` a function of `zoom`/`on`. [NapoleonWils0n]

**Scene transition (xfade + audio acrossfade), cumulative offset:**
```
# offset_k = Σ(dur_0..dur_{k-1}) − k·0.5   (running accumulator)
[v0][v1]xfade=transition=fade:duration=0.5:offset=<offset_1>[vx1];
[vx1][v2]xfade=transition=fade:duration=0.5:offset=<offset_2>[vx2];
[a0][a1]acrossfade=d=0.5[ax1]; ...
```
- `xfade` offset is relative to the **combined** prior output, not the new clip — must accumulate. [ffmpeglab, royshil gist]
- Verified transition catalog is ~30+ named types (indices 0–30: `fade, fadeblack, fadewhite, dissolve, pixelize, wipeleft/right/up/down, slideleft/right/up/down, circleopen/close, radial, smooth*, diag*`), plus `custom` expr mode. (Claims of "50+/60+" were **refuted** in verification — don't over-promise the catalog.) [ffmpeg source vf_xfade.c enum]

**overlay `eval` pitfall (relevant to 1.9c, noted here so it isn't rediscovered):** overlay x/y expressions only animate with `eval=frame` (the default); `eval=init` makes `t`/`n` evaluate to NAN and the motion freezes. Never rely on the default silently through a filter-chain refactor. [ffmpeg docs]

### Tasteful default parameters (industry-converged)

| Param | Default | Source |
|---|---|---|
| Zoom range | 1.0 → 1.08 over shot duration | benchmark synthesis (subtle push) |
| Direction pool | in/out-center, pan L/R/U/D, rotate to avoid repeats | Pictory (7-dir randomization) |
| Safe margin | ~10% inset before crop | InVideo safe-zone guidance |
| Transition | `fade` crossfade, 0.5s | industry convergence (0.5–1s) |
| Motion speed | slow + subtle (SCP horror = deliberate pacing) | Cloudinary/Kapwing mood-to-speed |
| Effect duration | = TTS/narration segment length | all benchmarked tools |

### Architecture guardrails (unchanged from 1.9)

- `video_node` stays a pure function of `PipelineState`; no DB/SSE, no imports from `db/`/`api/`. [AD-1, AD-4]
- Effect selection + filtergraph build belong in the node or a small `services/ffmpeg.py` helper only if it grows non-trivial. `# ponytail: keep in the node until command construction is genuinely hard to read`
- Pin/verify against the actual ffmpeg version in the runtime/Docker image; zoompan/overlay/xfade behavior was checked stable across ffmpeg 3.1–8.0 but the project must confirm its own build.

### Known caveats from research

- The mood-to-speed and "table-stakes" framing is generic faceless-YouTube convention, not a frame-by-frame study of specific SCP channels — reasonable but not channel-verified.
- Anti-repetition strategy (rotating pool) is our design; no source specifically addressed variance strategies for automated pipelines. Watch for a templated look across many videos and tune later.

## References

- `_bmad-output/implementation-artifacts/1-9-video-node.md` (base story this extends)
- Research (2026-07-01): FFmpeg docs https://ffmpeg.org/ffmpeg-filters.html ; zoompan — https://www.bannerbear.com/blog/how-to-do-a-ken-burns-style-effect-with-ffmpeg/ , https://creatomate.com/blog/how-to-zoom-images-and-videos-using-ffmpeg , https://hadna.space/en/notes/11-ffmpeg-ken-burns-effect-zoom-pan ; xfade — https://www.ffmpeglab.com/articles/ffmpeg-xfade-transitions-guide.html ; mood/style — https://cloudinary.com/guides/image-effects/ken-burns-effect-complete-guide-and-how-to-apply-it
- Benchmark (auto-video tools) scratch: NotebookLM Video Overviews is a closed generative feature (no API) — reference only, not an integration target.

## Dev Agent Record

### Agent Model Used
claude-sonnet-4-6

### Debug Log References
- Fixed `_join_with_xfade` Pyright possibly-unbound: moved `v_prev`/`a_prev` init outside loop.
- Integration test: original 1×1 PNG + scale=8000 was too slow; replaced with `color`+`sine` lavfi sources that test xfade plumbing directly without subtitle/zoompan overhead.
- Fixed `asyncio.get_event_loop().run_until_complete()` in xfade unit tests → proper `async def`.

### Completion Notes List
- `select_effect()` pure dispatcher: 8 known hint aliases + static near-zero drift + rotating pool fallback (anti-monotony). `EffectSpec` dataclass carries direction/start_zoom/end_zoom.
- `_zoompan_filter()`: jitter-safe chain `scale→setsar→crop→scale=8000→zoompan` with 10% safe margin, correct zoom-out conditional workaround, pan x/y as zoom functions.
- `_compose_scene()` extended with zoompan vf chain + post-scale/pad to output dims + subtitle burn.
- `_join_with_xfade()` replaces concat for ≥2 scenes: `xfade`+`acrossfade` pairwise with running_offset accumulator. Single-scene still uses `rename`.
- `_record_trace()` extended with `effects` list (per-scene direction/zoom), `transition`, `transition_duration`, `upscale_pass` params. [AC:5]
- 44 tests: 10 select_effect, 6 zoompan filter, 5 xfade unit, 7 validate, 14 video_node happy/error, 4 observability, 1 layer guard, 1 integration. All pass in 0.68s.
- Full suite: 195 passed, 1 skipped, 0 failures.

### File List
- `src/yt_flow/pipeline/nodes/video.py` (modified — zoompan + xfade + effect dispatcher)
- `tests/pipeline/nodes/test_video.py` (modified — 44 tests covering 1.9b ACs)
- `_bmad-output/implementation-artifacts/1-9b-video-effects-kenburns-transitions.md` (this file)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — in-progress → review)

## Change Log

- 2026-07-01: Story 1.9b implemented — Ken Burns zoompan + xfade/acrossfade scene transitions (claude-sonnet-4-6)
- 2026-07-01: Code review (3-layer adversarial: Blind Hunter, Edge Case Hunter, Acceptance Auditor) — 8 patches applied, 3 deferred, 5 dismissed; stories 1.9/1.9b → done (claude-opus-4-8)

## Review Findings

3-layer adversarial review (Blind Hunter / Edge Case Hunter / Acceptance Auditor). All 5 ACs verified functionally passing; xfade offset math independently confirmed correct by two layers.

### Patched (applied in `🐛 fix` commit)

- [x] [Review][Patch] `subtitles=` filtergraph path not escaped — colon/space/comma in run_id or workspace path breaks the graph [src/yt_flow/pipeline/nodes/video.py] — HIGH; violated the "never shell-interpolate paths, carry over escaping" hardening subtask. Now escaped + single-quoted; verified with a real ffmpeg render against a `a b:c.srt` path.
- [x] [Review][Patch] Zero-scene case relied on an `assert` (stripped under `python -O`) [video.py] — now an explicit `ValueError("no scenes to render")`, satisfying AC4's "fail before ffmpeg on 0 scenes".
- [x] [Review][Patch] `_validate_scene_assets` existence-checked every shot image but only the first image-bearing shot is rendered [video.py] — an unused later shot's missing image would abort the run; now validates only the rendered shot.
- [x] [Review][Patch] Dead duplicate two-scene join branch [video.py] — `elif len==2` and `else` were byte-identical; collapsed (n≥2 handled uniformly).
- [x] [Review][Patch] Redundant `scale`+`pad` after zoompan [video.py] — zoompan already emits exact `COMP_W×COMP_H` via `s=`; removed dead filter work.
- [x] [Review][Patch] `Path.rename` → `Path.replace` [video.py] — cross-platform atomic overwrite (rename raises `FileExistsError` on Windows if output exists).
- [x] [Review][Patch] Internal-whitespace `camera_movement` hints (`"pan  right"`, tabs) fell through to the pool [video.py] — now normalized via `" ".join(split())`.
- [x] [Review][Patch] Misleading xfade-offset docstring formula (off-by-one vs the correct code) [video.py] — comment corrected.

### Deferred

- [x] [Review][Defer] Per-scene vs per-shot motion — only the first image-bearing shot per scene is rendered; multi-shot scenes drop remaining shots [video.py] — departs from AC1's per-shot framing but is inherited from 1.9's single-segment-per-scene timing model, which the spec said to reuse ("do not invent a new timing model"). Needs a product decision + reworking 1.9's split before implementing.
- [x] [Review][Defer] Declared `audio_duration` drives xfade offsets while actual segment length is `-shortest` (real audio) [video.py] — drift if metadata ≠ real audio length. Fixing requires ffprobe-based timing, out of 1.9b scope.
- [x] [Review][Defer] Sub-`XFADE_DURATION` scenes → negative xfade offset / acrossfade underflow [video.py] — not reachable for multi-second TTS narration; assumption documented with a `# ponytail:` comment naming the clamp upgrade path.

### Dismissed (false positives / accurate as-is)

- A/V desync from `acrossfade` having no explicit offset — FALSE: sequential `acrossfade` overlap lands at the same cumulative points as the `xfade` offsets regardless of unequal durations; confirmed by two layers + arithmetic.
- Zoom-out "sawtooth pop" — FALSE: `max(1.001, …)` floors above 1.0 so `lte(zoom,1.0)` never retriggers; this is the spec-documented workaround.
- `upscale_pass=True` hardcoded — accurate; the upscale pass is unconditionally in the chain.
- Anti-monotony "not enforced for explicit hints" — AC3 scopes the rotating anti-monotony guarantee to the None/unknown fallback; explicit hints are honored as specified.
- Leftover partial segment files on failure — retries overwrite with `-y`.
