# Story 5.3: Motion Intensity - Ken Burns Strength and Variety

Status: ready-for-dev

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

- [ ] Strengthen normal Ken Burns constants in `src/yt_flow/pipeline/nodes/video.py`.
  - [ ] Raise `ZOOM_IN_MAX` from the current `1.08` only if live review confirms `1.08` is still too subtle; recommended tuning ceiling is `1.15`.
  - [ ] Keep `ZOOM_SAFE_MARGIN` large enough that stronger pan/zoom never exposes edges or clips important subject area.
  - [ ] Do not change `FPS`, `COMP_W`, `COMP_H`, xfade constants, character overlay constants, or output codec settings for this story.
- [ ] Extend deterministic fallback variety in `select_effect()`.
  - [ ] Update `_DIRECTION_POOL` to include diagonal directions, for example `pan-up-right`, `pan-up-left`, `pan-down-right`, `pan-down-left`.
  - [ ] Preserve explicit hint mapping for current hints; fallback rotation only applies when hint is `None` or unrecognized.
  - [ ] Keep `"static"` as a special case returning `EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=1.005)`.
- [ ] Teach `_zoompan_filter()` diagonal directions without changing its public signature.
  - [ ] For diagonal directions, combine the existing horizontal pan expressions with vertical pan expressions.
  - [ ] Preserve current zoom-out conditional workaround: `if(lte(zoom,1.0),...)` style behavior for `out-center`.
  - [ ] Preserve current filter order: `scale -> setsar -> crop -> scale=8000 -> zoompan`.
- [ ] Update tests in `tests/pipeline/nodes/test_video.py`.
  - [ ] Add/adjust assertions that normal non-static effects use the stronger `ZOOM_IN_MAX` while static still uses `1.005`.
  - [ ] Add fallback rotation tests covering diagonal directions and wraparound.
  - [ ] Add `_zoompan_filter()` tests proving every direction in `_DIRECTION_POOL` builds a filter containing `zoompan` and `scale=8000`.
  - [ ] Add at least one diagonal filter test that asserts both x and y motion expressions are present.
  - [ ] Keep existing character overlay, subtitle escaping, xfade, and AD-1 layer guard tests passing.
- [ ] Run verification.
  - [ ] Fast targeted check: `uv run pytest tests/pipeline/nodes/test_video.py`.
  - [ ] Broader backend regression if targeted tests pass: `uv run pytest tests/pipeline`.
  - [ ] If FFmpeg is installed locally, allow the existing skippable live-FFmpeg tests to run; do not make live FFmpeg mandatory for CI.
- [ ] Live render tuning.
  - [ ] Re-run or retry the `video` stage on a representative completed run, preferably SCP-096 or the reviewed run if still available.
  - [ ] Inspect the final mp4 and Langfuse effect metadata before finalizing any value above `1.08`.
  - [ ] If stronger than `1.15` feels necessary, stop and create a follow-up story for per-shot timing / storyboard motion rather than cranking constants indefinitely.

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

TBD by dev agent.

### Debug Log References

TBD by dev agent.

### Completion Notes List

TBD by dev agent.

### File List

TBD by dev agent.
