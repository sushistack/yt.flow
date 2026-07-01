# Story 1.13: Video Node LLM-Based Character Angle Selection

Status: ready-for-dev

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

- [ ] Task 1: Angle Selection Service (AC: 1, 3, 4, 5)
  - [ ] Add `select_character_angles(scp_id, scenes)` to `CharacterService`
  - [ ] Load `Character` record: if not found -> return `None`
  - [ ] Build LLM prompt with scene narration, camera metadata, available angles
  - [ ] Parse LLM response: JSON array `[{"scene": N, "shot_id": "...", "angle": "front"}, ...]`
  - [ ] Validate angles, fallback to `"front"` on any parsing error
  - [ ] Skip shots where `character_path` is already `None`
  - [ ] Return dict `{shot_key: angle_name}` mapping

- [ ] Task 2: Integration with video_node (AC: 2)
  - [ ] In `video_node`, after validation, before `_compose_scene` loop:
    - [ ] Call `select_character_angles(scp_id, scenes)` if character exists
    - [ ] For each shot, set `shot["character_path"] = character.angle_{angle}_path`
  - [ ] Existing `_compose_scene` character overlay logic works unchanged

- [ ] Task 3: Prompt Template (AC: 1, 4)
  - [ ] Create `prompts/character/angle_selection.md`
  - [ ] Register in Langfuse Prompt Hub

- [ ] Task 4: PipelineState scp_id Field (AC: 2)
  - [ ] Add `scp_id: str` to `PipelineState` TypedDict
  - [ ] Update `run_service.py` to include `scp_id` from run creation
  - [ ] Update tests to include `scp_id`

- [ ] Task 5: Tests (AC: 1-6)
  - [ ] Unit test `select_character_angles` with mocked LLM
  - [ ] Unit test fallback on LLM failure -> all `"front"`
  - [ ] Unit test fallback on invalid angle -> `"front"`
  - [ ] Unit test skip when no character exists
  - [ ] Unit test skip when character_path is None
  - [ ] Unit test scene-level batch call (1 LLM call for all shots)
  - [ ] Integration test: video_node with real angle selection
  - [ ] Trace test: Langfuse span under `video` with correct metadata

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

_To be filled by dev agent_

### Debug Log References

_To be filled by dev agent_

### Completion Notes List

_To be filled by dev agent_

### File List

_To be filled by dev agent_
