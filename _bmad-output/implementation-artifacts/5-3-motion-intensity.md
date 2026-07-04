---
baseline_commit: a3bd5446a22ec69fd6ab4c85c8e4f70e4644ec65
---

# Story 5.3: Motion Intensity - Ken Burns Strength and Variety

Status: review

<!-- Ultimate context engine analysis completed - comprehensive developer guide created -->

## Story

As Jay,
I want per-scene Ken Burns motion to be visibly stronger and less repetitive,
so that the rendered video feels alive instead of like a near-static slideshow.

## Context

Epic 5 responds to the first real render review from 2026-07-03 for run `eb522cf9` / SCP-096. The specific feedback for this story is that camera motion reads too close to still-image drift in practice. The current code already has a normal `ZOOM_IN_MAX = 1.08`, while the explicit `static` path intentionally uses only `1.0 -> 1.005`; implementation should therefore verify which path live scenes are actually taking, add visible fallback variety, and only raise the normal zoom ceiling after render review confirms `1.08` is still too subtle.

This story is deliberately narrow: strengthen and diversify background/single-image camera motion. It must not replace the FFmpeg renderer, add MoviePy/Remotion, change API contracts, alter DB/state schema, or touch UI. Story 5.2 activates layered assets; when those assets exist, this story still applies only to the background Ken Burns layer, while the existing 1.9c character idle-motion overlay remains independent.

## Acceptance Criteria

1. Given a normal non-static scene segment, when `video_node` renders it, then the Ken Burns zoom range reaches at least `1.08` from `1.0` and should be tuned to a visible-but-not-nauseating final value in the `1.08-1.15` range.
2. Given consecutive scenes without explicit `camera_movement`, when `select_effect()` chooses fallback effects, then the selection is deterministic by `scene_index` and rotates through visibly different directions, including zoom-in, zoom-out, horizontal pan, vertical pan, and at least one diagonal pan direction.
3. Given explicit `camera_movement` hints such as `zoom in`, `zoom out`, `pan left`, `pan right`, `pan up`, `pan down`, or `static`, when `select_effect()` runs, then recognized hints keep taking precedence over fallback rotation.
4. Given `camera_movement == "static"`, when the segment renders, then the existing near-zero drift path remains unchanged at `1.0 -> 1.005`; intentionally static shots must not inherit the stronger motion.
5. Given stronger zoom/pan values, when `_zoompan_filter()` builds the FFmpeg filter, then the existing jitter-safe chain still contains `scale=8000:-1` before `zoompan`.
6. Given subtitles are burned into a segment, when the image zooms or pans, then subtitles remain fixed in frame because subtitles are still applied after the background zoompan / optional character overlay chain.
7. Given a layered shot with `background_path` and `character_path`, when `_compose_scene()` renders it, then the background receives the stronger zoompan, the character overlay remains sinusoidal with `eval=frame`, and subtitle burn stays last.
8. Given trace metadata for the video stage, when a run completes, then each scene effect still records `direction`, `start_zoom`, `end_zoom`, and `character_overlay` so live tuning can be verified from Langfuse metadata.

## Tasks / Subtasks

- [x] Strengthen normal Ken Burns constants in `src/yt_flow/pipeline/nodes/video.py`.
  - [x] Raise `ZOOM_IN_MAX` from the current `1.08` only if live review confirms `1.08` is still too subtle; recommended tuning ceiling is `1.15`.
  - [x] Keep `ZOOM_SAFE_MARGIN` large enough that stronger pan/zoom never exposes edges or clips important subject area.
  - [x] Do not change `FPS`, `COMP_W`, `COMP_H`, xfade constants, character overlay constants, or output codec settings for this story.
- [x] Extend deterministic fallback variety in `select_effect()`.
  - [x] Update `_DIRECTION_POOL` to include diagonal directions, for example `pan-up-right`, `pan-up-left`, `pan-down-right`, `pan-down-left`.
  - [x] Preserve explicit hint mapping for current hints; fallback rotation only applies when hint is `None` or unrecognized.
  - [x] Keep `"static"` as a special case returning `EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=1.005)`.
- [x] Teach `_zoompan_filter()` diagonal directions without changing its public signature.
  - [x] For diagonal directions, combine the existing horizontal pan expressions with vertical pan expressions.
  - [x] Preserve current zoom-out conditional workaround: `if(lte(zoom,1.0),...)` style behavior for `out-center`.
  - [x] Preserve current filter order: `scale -> setsar -> crop -> scale=8000 -> zoompan`.
- [x] Update tests in `tests/pipeline/nodes/test_video.py`.
  - [x] Add/adjust assertions that normal non-static effects use the stronger `ZOOM_IN_MAX` while static still uses `1.005`.
  - [x] Add fallback rotation tests covering diagonal directions and wraparound.
  - [x] Add `_zoompan_filter()` tests proving every direction in `_DIRECTION_POOL` builds a filter containing `zoompan` and `scale=8000`.
  - [x] Add at least one diagonal filter test that asserts both x and y motion expressions are present.
  - [x] Keep existing character overlay, subtitle escaping, xfade, and AD-1 layer guard tests passing.
- [x] Run verification.
  - [x] Fast targeted check: `uv run pytest tests/pipeline/nodes/test_video.py`.
  - [x] Broader backend regression if targeted tests pass: `uv run pytest tests/pipeline`.
  - [x] If FFmpeg is installed locally, allow the existing skippable live-FFmpeg tests to run; do not make live FFmpeg mandatory for CI.
- [x] Live render tuning.
  - [x] Re-run or retry the `video` stage on a representative completed run, preferably SCP-096 or the reviewed run if still available.
  - [x] Inspect the final mp4 and Langfuse effect metadata before finalizing any value above `1.08`.
  - [x] If stronger than `1.15` feels necessary, stop and create a follow-up story for per-shot timing / storyboard motion rather than cranking constants indefinitely.

## Dev Notes

### Implementation Surface

Primary update file: `src/yt_flow/pipeline/nodes/video.py`.

Current state:
- `video_node()` sorts scenes, validates assets, optionally applies angle selection, renders one segment per scene, joins segments with xfade/acrossfade, and records per-scene effect metadata.
- `_compose_scene()` chooses the first image-bearing shot in each scene, prefers `background_path` for layered mode, falls back to `image_path`, then calls `select_effect()` and `_zoompan_filter()`.
- Background-only scenes use `-vf "<zoompan chain>,subtitles='...'"`.
- Layered scenes use `-filter_complex "[0:v]<zoompan>[bg];[1:v]<character scale>[char];[bg][char]<overlay>[ov];[ov]subtitles='...'[out]"`, then map `[out]` and `2:a`.
- `_record_trace()` already includes `effects` entries with `scene_num`, `direction`, `start_zoom`, `end_zoom`, and `character_overlay`.

What changes:
- Normal motion constants / direction choices.
- `select_effect()` fallback pool and `_zoompan_filter()` direction handling.
- Tests for new motion intensity and directions.

What must be preserved:
- AD-1 layering: `video.py` must not import `db`, `api`, or `services`.
- `ShotData` / `SceneState` / `PipelineState` schemas remain unchanged.
- `video_node()` output shape remains `{"current_stage": "video", "video_path": str, "error": None}` on success and an error string with `stage=video run_id=...` on failure.
- `static` keeps the 1.0 -> 1.005 drift because review patches for Story 1.9 fixed a bug where `_zoompan_filter()` ignored the effect spec.
- The `scale=8000:-1` jitter mitigation remains in the chain.
- Subtitles remain burned after motion / overlay so text is fixed in frame.
- The optional angle selector remains non-fatal and does not belong to this story.

### Previous Story Intelligence

Story 5.2 is a draft/backlog operational story, not a completed code story. It states that layered assets are already implemented by Stories 1.6b and 1.9c but not yet active in real renders because `.env` and ComfyUI workflow output wiring are missing.

Impact for this story:
- Do not wait for 5.2 to complete; the Ken Burns background path exists today and can be improved now.
- Do not solve ComfyUI layered workflow generation here.
- In layered mode, stronger Ken Burns should affect only the background path. Character movement remains the existing `_overlay_filter()` sine sway/bob behavior.
- If a live render still feels flat after this story and 5.2, the likely missing piece is per-shot timing. That is outside this story because current `video_node()` renders only the first image-bearing shot per scene.

### Relevant Architecture Constraints

- Pipeline nodes are pure functions of `PipelineState` and do not write DB rows or queues directly.
- Artifact paths live in LangGraph state, not in a scenes/artifacts table.
- FFmpeg is an external subprocess dependency; tests should monkeypatch `_run_ffmpeg()` for speed and determinism.
- Langfuse tracing is non-fatal; trace enrichment must never fail the video stage.
- Performance target is end-to-end <= 2 hours, quality over speed. Avoid expensive new renderers or multiple render passes.
- Test quality gate from the architecture test design: maintain >=80% coverage across core layers and prefer unit/API integration over expensive real-provider E2E.

### Latest Technical Notes

- FFmpeg's current generated docs still define `zoompan` with `z/zoom`, `x`, `y`, `d`, `s`, and `fps`; zoom range is documented as `1-10`, but this project should stay in a conservative `1.08-1.15` range for watchability. Source: https://ffmpeg.org/ffmpeg-filters.html#zoompan
- `zoompan` examples continue to use center expressions like `iw/2-(iw/zoom/2)` and incremental `min(zoom+..., target)` patterns. Use the existing project filter builder rather than inventing a new graph. Source: https://ffmpeg.org/ffmpeg-filters.html#zoompan
- FFmpeg `overlay` evaluates x/y per frame by default and exposes `main_w`, `main_h`, `overlay_w`, `overlay_h`, `n`, and `t`; `n` and `t` are only valid with frame evaluation. Keep explicit `eval=frame`. Source: https://ffmpeg.org/ffmpeg-filters.html#overlay
- FFmpeg `xfade` inputs must share resolution, pixel format, frame rate, and timebase. This story must not disturb the existing segment normalization to `COMP_W x COMP_H`, `FPS`, and `yuv420p`. Source: https://ffmpeg.org/ffmpeg-filters.html#xfade
- Filtergraph syntax still uses comma-separated filters in a chain and semicolon-separated chains in complex graphs; keep tests around command/filter construction rather than relying on visual inspection alone. Source: https://ffmpeg.org/ffmpeg-filters.html#Filtergraph-syntax

### Testing Guidance

Use existing tests as the pattern:
- `test_select_effect_*` for pure effect selection.
- `test_zoompan_filter_*` for filter string behavior.
- `test_video_node_zoompan_in_vf` and `test_video_node_character_uses_filter_complex` for command-path coverage.
- Existing live FFmpeg integration tests are skippable and should remain skippable.

Recommended new assertions:
- `select_effect(_shot(camera_movement=None), i)` covers every direction in the new pool across `len(_DIRECTION_POOL)`.
- `select_effect(_shot(camera_movement="static"), 0)` still returns `end_zoom == 1.005`.
- For a diagonal direction, `_zoompan_filter()` includes both an x expression based on `(iw-iw/zoom)` and a y expression based on `(ih-ih/zoom)`.
- Trace metadata test still sees updated `end_zoom` values for normal effects.

### References

- `_bmad-output/planning-artifacts/epics.md` - Epic 5 goal and Story 5.3 summary.
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md` - FR-6 video composition, FR-10/FR-12 trace requirements, performance NFR.
- `_bmad-output/test-artifacts/test-design/test-design-architecture.md` - architecture risks, testing strategy, coverage expectations, external seam strategy.
- `_bmad-output/implementation-artifacts/5-2-layered-assets-activation.md` - layered asset operational dependency and 1.9c overlay expectations.
- `_bmad-output/implementation-artifacts/1-9b-video-effects-kenburns-transitions.md` - original Ken Burns / xfade implementation notes and FFmpeg research.
- `_bmad-output/implementation-artifacts/1-9c-video-character-idle-motion.md` - layered overlay path and `eval=frame` guardrails.
- `src/yt_flow/pipeline/nodes/video.py` - current implementation to update.
- `tests/pipeline/nodes/test_video.py` - current unit/integration test suite to extend.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5), via bmad-dev-story workflow.

### Debug Log References

- Targeted suite: `uv run pytest tests/pipeline/nodes/test_video.py` → 89 passed.
- Full backend regression: `uv run pytest tests/pipeline` → 205 passed, 1 skipped (unrelated TTS smoke test gated by `YTFLOW_QWEN_TTS_SMOKE`).
- `uv run ruff check` on both changed files → clean.
- Live render tuning: reconstructed the reviewed run's 9-scene state from the real assets still on disk at `workspace/eb522cf9-4e13-40f1-8876-f66d6695cb79/{images,audio,subtitles}` and re-ran `video_node()` end-to-end (real ffmpeg, no mocks) via an ad-hoc scratch script. Captured trace `effects` metadata confirmed deterministic rotation across all 9 scenes (`in-center, pan-right, pan-left, out-center, pan-up, pan-down, pan-up-right, pan-up-left, pan-down-right`) each at `1.0↔1.15`. Extracted first/last frames of the `pan-right` and `pan-up-right` (diagonal) segments with `ffmpeg`/`ffprobe` and visually inspected them (Read tool) — diagonal motion is clearly visible with no edge clipping, so `1.15` was kept as final and no follow-up story was needed. Verification render output and extracted frames were scratch artifacts, not committed.

### Completion Notes List

- Raised `ZOOM_IN_MAX` 1.08 → 1.15 (top of the story's recommended band); `ZOOM_SAFE_MARGIN` (10%) left unchanged — still ample headroom at 1.15 zoom, confirmed via live render with no clipping.
- Added 4 diagonal directions (`pan-up-right/-left`, `pan-down-right/-left`) to `_DIRECTION_POOL`; `select_effect()` needed no other change since fallback rotation, hint precedence, and the `static` special case already worked generically off the pool.
- `_zoompan_filter()` gained one new `elif` branch combining the existing horizontal/vertical pan expressions for the 4 diagonal directions; filter order, zoom-out conditional, and jitter-fix (`scale=8000`) chain untouched.
- Existing pool-driven tests (`test_select_effect_none_rotates_pool`, `_unknown_rotates_pool`, `_pool_wraps`, `test_zoompan_filter_all_directions_build`) automatically exercised the new diagonals since they iterate `video._DIRECTION_POOL` rather than hardcoding the old 6 directions — no changes needed there.
- Added: `test_zoom_in_max_within_recommended_range` (AC:1 band check) and `test_zoompan_filter_diagonal_has_both_axes` (parametrized over the 4 new directions, AC:2). Fixed one stale hardcoded-`"1.08"` literal in `test_zoompan_filter_honors_spec_zoom_range` to reference `video.ZOOM_IN_MAX` instead.
- No new dependencies; no API/DB/UI changes; AD-1 layering guard test still passes unmodified.

### File List

- `src/yt_flow/pipeline/nodes/video.py`
- `tests/pipeline/nodes/test_video.py`

## Change Log

- 2026-07-04: Raised `ZOOM_IN_MAX` 1.08 → 1.15, added 4 diagonal fallback directions to `_DIRECTION_POOL` and their `_zoompan_filter()` x/y expressions; live-rendered the reviewed run's real assets end-to-end with real ffmpeg to confirm visible, non-clipping motion before finalizing 1.15 as the ceiling. Full backend regression green (205 passed, 1 unrelated skip).
