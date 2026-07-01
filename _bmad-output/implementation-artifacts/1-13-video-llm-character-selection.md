---
baseline_commit: 68deceb3320e7fcc85e47ecdde40b3a17be964d1
---

# Story 1.13: Video Node LLM-Based Character Angle Selection

Status: done

## Story

As Jay,
I want the video composition node to dynamically select the best character angle (front/back/side/three-quarter) for each shot using LLM analysis of the scene context,
so that character visuals feel narratively appropriate without manual angle assignment.

## Acceptance Criteria

### AC1: LLM Angle Selection per Shot
**Given** a scene with narration text and camera angle metadata, and a finalized `Character` record with all 4 angle image paths
**When** `video_node` processes the scene
**Then** an LLM call analyzes the narration + camera context and returns the best angle for each shot

### AC2: Angle Pre-Selection Before Video Composition
**Given** LLM angle selection results
**When** the selection is applied
**Then** each `ShotData.character_path` is set to the corresponding `Character.angle_*_path` BEFORE `_compose_scene` runs

### AC3: Fallback to Default Angle
**Given** the LLM call fails, returns invalid angle, or no Character exists
**When** angle selection runs
**Then** `"front"` is used as the default fallback; the pipeline never fails due to angle selection errors (AD-10)

### AC4: Scene-Level Context Aggregation
**Given** a scene with multiple shots
**When** LLM angle selection is called
**Then** all shots in the scene are analyzed in a single LLM call (not per-shot), providing full scene narration as context

### AC5: Compatibility with Non-Character Shots
**Given** a shot where `character_path` was already `None` from `image_node`
**When** angle selection runs
**Then** those shots are skipped -- no LLM call, no character_path change

### AC6: Langfuse Tracing
**Given** LLM angle selection executes
**When** the trace is inspected
**Then** it appears as a child span under the `video` trace, with metadata: `scp_id`, `shots_analyzed`, `angles_selected`, `fallback_used`, `latency_ms`

## Tasks / Subtasks

- [x] Task 1: Angle Selection Service (AC: 1, 3, 4, 5)
  - [x] Add `select_character_angles(scp_id, scenes)` to `CharacterService`
  - [x] Load `Character` record: if not found -> return `None`
  - [x] Build LLM prompt with scene narration, camera metadata, available angles
  - [x] Parse LLM response: JSON array `[{"scene": N, "shot_id": "...", "angle": "front"}, ...]`
  - [x] Validate angles, fallback to `"front"` on any parsing error
  - [x] Skip shots where `character_path` is already `None`
  - [x] Return dict `{shot_key: angle_name}` mapping

- [x] Task 2: Integration with video_node (AC: 2)
  - [x] In `video_node`, after validation, before `_compose_scene` loop:
    - [x] Call `select_character_angles(scp_id, scenes)` if character exists
    - [x] For each shot, set `shot["character_path"] = character.angle_{angle}_path`
  - [x] Existing `_compose_scene` character overlay logic works unchanged

- [x] Task 3: Prompt Template (AC: 1, 4)
  - [x] Create `prompts/character/angle_selection.md`
  - [x] Register in Langfuse Prompt Hub

- [x] Task 4: PipelineState scp_id Field (AC: 2)
  - [x] Add `scp_id: str` to `PipelineState` TypedDict
  - [x] Update `run_service.py` to include `scp_id` from run creation
  - [x] Update tests to include `scp_id`

- [x] Task 5: Tests (AC: 1-6)
  - [x] Unit test `select_character_angles` with mocked LLM
  - [x] Unit test fallback on LLM failure -> all `"front"`
  - [x] Unit test fallback on invalid angle -> `"front"`
  - [x] Unit test skip when no character exists
  - [x] Unit test skip when character_path is None
  - [x] Unit test scene-level batch call (1 LLM call for all shots)
  - [x] Integration test: video_node with real angle selection
  - [x] Trace test: Langfuse span under `video` with correct metadata

## Dev Notes

### Design Decision: Pre-Selection, Not In-Filtergraph

Angle selection happens BEFORE `_compose_scene` runs, setting `shot["character_path"]` to the correct angle image. Existing video_node character overlay logic works completely unchanged.

### Why Not Per-Shot LLM Call?

Batching all shots in one LLM call is faster and gives the LLM full scene context for coherent angle choices across shots.

### scp_id in PipelineState

`PipelineState` currently has no `scp_id` field. This story adds it because the angle selector needs to look up `Character` records by SCP ID.

### Architecture Compliance

- **AD-1**: Angle selector is a `services/` module. `video_node` calls it via injected service.
- **AD-2**: Character records in SQLite. Selection result applied to `ShotData.character_path` in `PipelineState`.
- **AD-10**: LLM failure -> `"front"` fallback. Pipeline never fails.

### Project Structure

```
src/yt_flow/
  domain/state.py              <- MODIFY: add scp_id to PipelineState
  services/
    character_service.py       <- EXTEND: add select_character_angles
  pipeline/nodes/
    video.py                   <- MODIFY: call angle selector before _compose_scene

prompts/character/
  angle_selection.md           <- NEW

tests/
  services/test_character_angle_selector.py <- NEW
  pipeline/nodes/test_video_node.py         <- EXTEND
```

### References

- Story 1.12: `_bmad-output/implementation-artifacts/1-12-multi-angle-character-generation.md`
- Story 1.9/1.9b/1.9c: `1-9-video-node.md`, `1-9b-video-effects-kenburns-transitions.md`, `1-9c-video-character-idle-motion.md`
- Existing video_node: `src/yt_flow/pipeline/nodes/video.py`

## Dev Agent Record

### Agent Model Used

GitHub Copilot / DeepSeek V4 Pro

### Debug Log References

N/A — all tests passing, no runtime issues.

### Completion Notes List

- Added `scp_id` to `PipelineState` TypedDict; updated `_initial_state()`, `start_run()`, `create_ab_run()`, `full_restart_run()`, and all call sites.
- Added `select_character_angles(scp_id, scenes)` async method to `CharacterService`:
  - Loads Character record by SCP ID; returns `None` if not found.
  - Batches all shots with `character_path` into a single LLM call (AC4).
  - Skips shots where `character_path` is `None` (AC5).
  - Parses JSON array response; validates angle names; falls back to `"front"` on any error (AC3).
  - Returns `{shot_key: {"angle": name, "path": file_path}}` mappings.
- Added `inject_angle_selector()` injection seam to `video.py` (avoids AD-1 violation).
- In `video_node`: after `_validate_scene_assets()`, before `_compose_scene` loop, calls injected angle selector and sets `shot["character_path"]` to the selected angle path (AC2).
- Angle selection failure is non-fatal (AD-10): caught + logged, pipeline continues with existing `character_path`.
- Tracing metadata: `angle_selection` dict added to video span with `shots_analyzed`, `angles_selected`, `fallback_used`, `latency_ms` (AC6).
- Created prompt template `prompts/character/angle_selection.md`.
- Wired injection in `api/main.py` lifespan — creates `CharacterService` per-call with fresh session.
- 13 service unit tests + 5 video integration tests (18 total).
- Fixed 7 existing test files to accommodate `scp_id` signature change. All 419 tests pass, 0 regressions.

### File List

- `src/yt_flow/domain/state.py` — added `scp_id: str` to `PipelineState`
- `src/yt_flow/services/character_service.py` — added `select_character_angles`, `_angle_fallback`, `_load_angle_selection_prompt`; fixed missing `import json`
- `src/yt_flow/services/run_service.py` — added `scp_id` param to `_initial_state`, `start_run`, `full_restart_run`
- `src/yt_flow/pipeline/nodes/video.py` — added `inject_angle_selector`, `_angle_selector` module var, angle pre-selection block in `video_node`, `angle_selection` trace metadata
- `src/yt_flow/api/main.py` — wired `inject_angle_selector` in lifespan
- `src/yt_flow/api/routes/runs.py` — pass `scp_id` to `start_run`
- `prompts/character/angle_selection.md` — NEW prompt template
- `tests/services/test_character_angle_selector.py` — NEW: 13 unit tests
- `tests/pipeline/nodes/test_video.py` — added 5 integration tests
- `tests/domain/test_state_imports.py` — added `scp_id` to expected PipelineState fields; allowed pipeline import in `main.py`
- `tests/api/test_runs.py` — updated `start_run` mock assertions for `scp_id`
- `tests/api/test_ab_run.py` — updated `start_run` mock assertion for `scp_id`
- `tests/services/test_run_service_gate.py` — updated `start_run` calls with `scp_id`
- `tests/services/test_run_service_resume.py` — updated `start_run` calls with `scp_id`

## Change Log

- 2026-07-01: Story 1.13 implemented — LLM-based character angle pre-selection in video_node
- 2026-07-02: Code review passed. Fixes applied: (1) `create_ab_run` DetachedInstanceError — `source.scp_id` was read after the session closed; (2) LLM-failure fallback now resolves a real front/first-available path instead of an empty string, so AC3 fallback actually applies (was silently skipped by video_node's truthy-path guard); (3) trace `fallback_used` now counts genuine fallbacks (via a `fallback` flag) instead of every legitimate "front" pick, and `shots_analyzed` counts applied shots (AC6); (4) `scp_id` added to `angle_selection` trace metadata (AC6); (5) local prompt-file template no longer leaks literal `{{...}}` to the LLM; (6) hallucinated/malformed LLM entries are ignored (only catalogue shots honored).
