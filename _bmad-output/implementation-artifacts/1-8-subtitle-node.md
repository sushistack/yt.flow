---
baseline_commit: 9ddfc9feb256d08d8c79776ad5fe5a5da25eff0d
---

# Story 1.8: subtitle_node

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want `subtitle_node` to produce forced-alignment `.srt` files using the audio and known narration text,
so that each scene has a subtitle file with accurate word-level timing.

## Acceptance Criteria

1. Given `SceneState.audio_path` and `SceneState.narration` per scene, when `subtitle_node` runs forced alignment via `YTFLOW_ALIGNER` config (for example `"whisperx"`), then `SceneState.subtitle_path` is set to an existing `.srt` file with at least 1 subtitle entry. [Source: `_bmad-output/planning-artifacts/epics.md#Story 1.8: subtitle_node`]
2. Given a different aligner library configured in `YTFLOW_ALIGNER`, when `subtitle_node` runs, then it uses the configured aligner without code change; the aligner is a config-driven strategy. [Source: `_bmad-output/planning-artifacts/epics.md#Story 1.8: subtitle_node`]
3. Given `subtitle_node` execution, when it completes, then a Langfuse span named `"subtitle"` appears with latency. [Source: `_bmad-output/planning-artifacts/epics.md#Story 1.8: subtitle_node`]
4. Given an aligner, input audio, or output write failure, when `subtitle_node` encounters the error, then the returned `PipelineState.error` includes `stage="subtitle"` and `run_id`, and the Langfuse span captures the exception detail. This extends the Epic 1 node error pattern from image/tts/video to the subtitle stage. [Source: `_bmad-output/planning-artifacts/epics.md#Story 1.6: image_node`, `_bmad-output/planning-artifacts/epics.md#Story 1.7: tts_node`, `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F2 - Observability`]
5. Given generated subtitle artifacts, when downstream stages and future artifact APIs read state, then subtitle paths live only in `PipelineState.scenes[*].subtitle_path`; no scenes/artifacts database table is introduced. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7 - Single SQLite file; no scenes table; AsyncSqliteSaver`]

## Tasks / Subtasks

- [x] Confirm preconditions from prior Epic 1 stories before editing code (AC: 1, 3)
  - [x] Verify `src/yt_flow/domain/state.py` defines `PipelineState`, `SceneState`, and `WordTiming` with `audio_path`, `audio_duration`, `word_timings`, and `subtitle_path` fields matching the architecture.
  - [x] Verify `src/yt_flow/config.py` uses Pydantic `BaseSettings` with `YTFLOW_` env prefix, and add aligner/subtitle settings there if absent.
  - [x] Verify `src/yt_flow/pipeline/graph.py` already contains the `subtitle` node between `gate_tts` and `gate_subtitle`; if it still uses stubs, replace only the subtitle stub behavior.
- [x] Add config-driven subtitle alignment support (AC: 1, 2)
  - [x] Add `YTFLOW_ALIGNER` with a default suitable for local development, expected value `"whisperx"` unless the existing config already establishes another default.
  - [x] Add any needed aligner settings without hardcoding model names inside the node, for example `YTFLOW_ALIGNER_MODEL`, `YTFLOW_ALIGNER_DEVICE`, `YTFLOW_ALIGNER_COMPUTE_TYPE`, or equivalent names consistent with the existing config style.
  - [x] Implement a small strategy resolver, keeping the stage node call site stable: configured aligner name in, aligner object/function out.
  - [x] Fail fast with a clear `ValueError` or project-local exception for unsupported `YTFLOW_ALIGNER` values.
- [x] Implement `subtitle_node` in `src/yt_flow/pipeline/nodes/subtitle.py` (AC: 1, 3, 4, 5)
  - [x] Treat the stage literal as exactly `"subtitle"` everywhere: node name, `current_stage`, errors, and Langfuse span.
  - [x] For each scene, require non-empty `narration` and an existing `audio_path`; do not attempt alignment against missing files.
  - [x] Use known `SceneState.narration` as the transcript source; do not re-transcribe when forced alignment can consume known text.
  - [x] Write one `.srt` file per scene under `workspace/{run_id}/subtitles/` or the existing workspace convention established by earlier stories.
  - [x] Return a new state update replacing `scenes` wholesale with updated scene dictionaries; do not mutate nested state in place.
  - [x] Set each `SceneState.subtitle_path` to the generated file path and set `current_stage` to `"subtitle"`.
- [x] Implement SRT formatting and timing rules (AC: 1, 5)
  - [x] Generate standards-compliant SRT: 1-based cue index, `HH:MM:SS,mmm --> HH:MM:SS,mmm`, subtitle text, blank line.
  - [x] Ensure each generated file has at least one cue when narration exists.
  - [x] Ensure cue timings are monotonic, non-negative, and do not exceed the scene audio duration when duration data is available.
  - [x] Preserve Korean narration text as UTF-8.
  - [x] Keep line splitting deterministic and readable; prefer word/sentence timing from the aligner over arbitrary fixed-duration chunks.
- [x] Add observability and error handling (AC: 3, 4)
  - [x] Decorate or instrument the node with Langfuse `@observe` using span name `"subtitle"` following the patterns from prior node stories.
  - [x] Capture latency in the span metadata or observation data.
  - [x] On failure, return or raise according to the established node pattern, but ensure `PipelineState.error` carries enough detail for `services/` and Langfuse: `stage`, `run_id`, and a human-readable message.
  - [x] Keep Langfuse failure non-fatal only if the existing observability wrapper has already established that behavior; do not let tracing outages block subtitle generation.
- [x] Add tests and fixtures (AC: 1, 2, 3, 4)
  - [x] Unit-test SRT formatting independently from WhisperX or any cloud/local model dependency.
  - [x] Unit-test `YTFLOW_ALIGNER` strategy selection, including unsupported aligner error behavior.
  - [x] Unit-test `subtitle_node` with a fake aligner and fixture audio path so CI/local tests do not require WhisperX model downloads.
  - [x] Test missing `audio_path`, missing audio file, empty narration, and aligner exception paths.
  - [x] Test that returned `scenes` contains updated `subtitle_path` values and does not introduce DB writes or API-layer imports.

## Dev Notes

### Epic Context

Epic 1 builds the local Python/LangGraph pipeline from SCP text to final video: `scenario -> image -> tts -> subtitle -> video`, with Prompt Hub migration first and Langfuse `@observe` spans on all real node stories. Story 1.8 depends on Story 1.7 because subtitles require per-scene TTS audio and timing context. Story 1.9 will consume `SceneState.subtitle_path` when composing the final video via FFmpeg. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 1: Project Foundation & Pipeline Core`]

Story 1.8 implements FR-5: generate subtitles via forced alignment, where script text is already known from the scenario stage and must be aligned against TTS audio output. Do not build a separate transcription workflow as the primary path. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F1 - Pipeline Core`]

### Architecture Compliance

- Layering: place stage behavior under `src/yt_flow/pipeline/nodes/subtitle.py`. Pipeline nodes may import `domain` and config/helpers, but must not import `db/`, `api/`, or `services/`. `api -> services -> (pipeline | db) -> domain` is the only allowed direction. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1 - Layer dependency direction`]
- State authority: all subtitle output state lives in `PipelineState`, persisted through LangGraph `AsyncSqliteSaver`. Do not add a subtitle table, scenes table, artifacts table, or DB projection for per-scene subtitle paths. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2 - LangGraph state is the single source of truth`, `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7 - Single SQLite file; no scenes table; AsyncSqliteSaver`]
- Graph position: `subtitle` is a pure stage node between `gate_tts` and `gate_subtitle`. Gate behavior belongs in `gates.py`; do not call `interrupt()` inside `subtitle_node`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#LangGraph Graph Structure`]
- State mutation convention: return replacement fields from the node; do not rely on in-place mutation of nested scene dictionaries. Because `scenes` is a list of dictionaries, copy each scene you modify and return `{"scenes": updated_scenes, "current_stage": "subtitle"}` or the equivalent established pattern. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency Conventions`]
- Current stage: `current_stage` is set only by stage nodes and mirrored by services. Story 1.8 should set `"subtitle"` for this node, not `"video"` or a future stage. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency Conventions`]

### Expected State Shape

The architecture defines these fields relevant to Story 1.8:

```python
class WordTiming(TypedDict):
    word: str
    start_sec: float
    end_sec: float

class SceneState(TypedDict):
    scene_num: int
    narration: str
    shots: list[ShotData]
    audio_path: str | None
    audio_duration: float | None
    word_timings: list[WordTiming]
    subtitle_path: str | None

class PipelineState(TypedDict):
    run_id: str
    scp_text: str
    scenes: list[SceneState]
    video_path: str | None
    current_stage: str
    gate_states: dict[str, str]
    prompt_variant: str | None
    error: str | None
```

[Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#PipelineState (OQ-7 resolved)`]

### File Structure Requirements

Expected files to create or update, depending on what prior stories have already produced:

- `src/yt_flow/pipeline/nodes/subtitle.py` - implement `subtitle_node` and SRT generation orchestration.
- `src/yt_flow/config.py` - add `YTFLOW_ALIGNER` and aligner-specific settings if absent.
- `src/yt_flow/domain/state.py` - update only if prior stories did not already include `subtitle_path`, `WordTiming`, or related fields exactly as specified.
- `src/yt_flow/pipeline/graph.py` - update only if the subtitle node is still a stub or not wired to the real function.
- `tests/pipeline/nodes/test_subtitle.py` or the existing test path convention - add unit tests with fake aligner fixtures.
- `tests/fixtures/` - add minimal fixture files only if needed by the local test convention.

No existing source files are present in the repository at story creation time, but prior stories are expected to create this structure before Story 1.8 is implemented. The dev agent must inspect the actual tree before editing, because Stories 1.2-1.7 may have established concrete helper names or test conventions.

### Aligner Strategy Guidance

`YTFLOW_ALIGNER` is intentionally config-driven. Use a narrow strategy interface so replacing WhisperX later does not require changing `subtitle_node`:

```python
class AlignmentSegment(TypedDict):
    start_sec: float
    end_sec: float
    text: str

class SubtitleAligner(Protocol):
    async def align(self, audio_path: str, transcript: str) -> list[AlignmentSegment]:
        ...
```

This interface is illustrative; match the repo's typing style if prior stories define another pattern. The invariant is that `subtitle_node` depends on a stable aligner abstraction, not directly on one library throughout the node body.

Implementation must include a fake or stub aligner for tests. Do not make unit tests download WhisperX models, require GPU, or call networked services.

### Latest Technical Notes

- Architecture review updated the stack to current packages: LangGraph `1.2.6`, `langgraph-checkpoint-sqlite` as a separate package, SQLModel `0.0.38`, and Langfuse Python SDK `4.x (4.12.0+)`. Follow the architecture spine over older PRD/epic stack pins where they conflict. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack`, `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/reviews/review-tech-currency.md#Langfuse Python SDK`]
- WhisperX remains the named example for `YTFLOW_ALIGNER`; its upstream project describes forced alignment on top of Whisper output and supports word-level timestamps. Treat it as the default implementation candidate, but keep it behind the strategy boundary. [Source: `https://github.com/m-bain/whisperX`, `https://pypi.org/project/whisperx/`]
- Langfuse SDK v4 still supports the `@observe` decorator pattern, but import paths and client setup must follow the installed SDK version used by Story 1.1. Do not copy old Langfuse 2.x examples if `pyproject.toml` pins SDK 4.x. [Source: `https://langfuse.com/docs/sdk/python/decorators`, `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/reviews/review-tech-currency.md#Langfuse Python SDK`]

### SRT Generation Rules

- Write UTF-8 `.srt` files.
- Use 1-based cue indices.
- Use comma millisecond separators: `00:00:01,250 --> 00:00:03,500`.
- Do not emit overlapping cues.
- Clamp tiny negative starts to `0.0` only if caused by aligner precision; otherwise treat invalid timings as an error.
- If aligner returns word-level timings, group words into readable cue text while preserving monotonic timing.
- If Story 1.7 already populated `SceneState.word_timings`, prefer reusing those timings when they are valid for the same narration/audio rather than invoking a redundant expensive aligner pass. If the timings are incomplete or absent, use the configured aligner.

### Error Handling

Use the same error contract as prior nodes:

- `stage`: `"subtitle"`
- `run_id`: `state["run_id"]`
- message: include failing scene number and whether the failure was input validation, aligner execution, or file writing
- tracing: span captures exception detail and input identifiers; do not include full SCP text unless prior observability code already handles redaction/size concerns

Examples of required failure coverage:

- scene has no `audio_path`
- `audio_path` does not exist
- scene has empty `narration`
- unsupported `YTFLOW_ALIGNER`
- aligner returns no segments for non-empty narration
- aligner returns invalid/overlapping timestamps
- subtitle directory or file write fails

### Testing Requirements

Minimum tests:

- `format_srt` produces valid SRT text for representative Korean subtitle text and floating-point timings.
- `subtitle_node` with fake aligner creates files under the run workspace and returns updated `subtitle_path` values.
- `subtitle_node` returns/reports stage-specific error information for missing audio files.
- strategy resolver uses `YTFLOW_ALIGNER` and rejects unknown aligner names.
- no test requires real WhisperX, GPU, Qwen TTS, Langfuse, SQLite, FastAPI, or network access.

Suggested command after implementation, adjusted to the repo's actual test setup:

```bash
uv run pytest tests/pipeline/nodes/test_subtitle.py
```

### UX/API Forward Compatibility

Later API/UI stories depend on subtitle artifacts being readable and editable:

- API Story 2.4 will allow `PATCH /runs/{id}/stages/{stage}/artifact` for `scenario` and `subtitle` only, using `graph.update_state()` before rewriting the artifact file on disk. [Source: `_bmad-output/planning-artifacts/epics.md#Story 2.4: Stage Control - Retry & Inline Artifact Edit`]
- UI Story 3.4/3.5 will display subtitle content as SRT in a monospace scroll area with a subtitle count label, and allow inline editing for `subtitle`. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run Detail - artifact panel by stage`]

Because of that, Story 1.8 must produce plain text SRT files that are deterministic, human-readable, and safe to rewrite later. Avoid binary subtitle formats and avoid embedding subtitle content only in LangGraph state without a file path.

### Previous Story Intelligence

No previous story files exist in `_bmad-output/implementation-artifacts/` at creation time, so there are no direct dev notes from Stories 1.1-1.7. Use the architecture and epics as the source of truth, then inspect the actual source tree before implementation because preceding stories may already have established helper modules, exception types, workspace path utilities, Langfuse wrappers, or test fixtures.

### Git Intelligence Summary

Recent commits are planning/documentation commits:

- `2390ead` initialized sprint status tracking for 24 stories across 4 epics.
- `4be98ee` added epic breakdown and implementation readiness report.
- `6db2416` added UX design specs and HTML mockups.
- `ca2fb1d` added architecture design and review docs.
- `b9dc0b0` added the PRD.

There is no implementation code history yet. The highest-confidence guidance is therefore the architecture spine, epics, and readiness report, not inferred code patterns.

### Project Structure Notes

- Existing source tree at story creation time: no `src/`, `tests/`, `data/`, or `frontend/` implementation files found.
- Expected implementation root remains the architecture structural seed: `src/yt_flow/`.
- The story intentionally avoids requiring a specific helper module name for the aligner strategy beyond `subtitle.py`; dev agent should follow the concrete conventions created by earlier stories.
- Detected planning conflict: PRD/epics mention older stack pins in places, while the architecture spine incorporates tech-currency review updates. Use the architecture spine's Stack section when dependency versions conflict.

### References

- `_bmad-output/planning-artifacts/epics.md#Story 1.8: subtitle_node`
- `_bmad-output/planning-artifacts/epics.md#Epic 1: Project Foundation & Pipeline Core`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F1 - Pipeline Core`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F2 - Observability`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Invariants & Rules`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#PipelineState (OQ-7 resolved)`
- `_bmad-output/planning-artifacts/implementation-readiness-report-2026-06-30.md#PRD Completeness Assessment`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run Detail - artifact panel by stage`
- `https://github.com/m-bain/whisperX`
- `https://pypi.org/project/whisperx/`
- `https://langfuse.com/docs/sdk/python/decorators`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- Test fix: `_FakeAligner(segments=[])` used `or` instead of `is not None` check, causing default segments to be returned on empty list.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Implemented `subtitle_node` with `@observe(name="subtitle")` Langfuse span (AC3).
- Added config-driven aligner strategy (`YTFLOW_ALIGNER`, `YTFLOW_ALIGNER_MODEL`, `YTFLOW_ALIGNER_DEVICE`, `YTFLOW_ALIGNER_COMPUTE_TYPE`) to `config.py` (AC2).
- `WhisperXAligner` uses lazy import (not in pyproject.toml); kept behind `SubtitleAligner` Protocol.
- Reuses `SceneState.word_timings` from `tts_node` when populated; calls aligner only when empty (AC1).
- SRT files written to `workspace/{run_id}/subtitles/scene_NNN.srt` as UTF-8 (AC1, AC5).
- Error contract: `stage=subtitle run_id=<id>: <message>` in `PipelineState.error` (AC4).
- 29 unit tests, 0 regressions in the full suite (116 passed, 1 skipped).
- `nodes/__init__.py` and `graph.py` unchanged — consistent with prior stories (1.5-1.7 pattern).

### File List

- `src/yt_flow/config.py` — added `aligner`, `aligner_model`, `aligner_device`, `aligner_compute_type` fields
- `src/yt_flow/pipeline/nodes/subtitle.py` — new: `subtitle_node`, `WhisperXAligner`, `_get_aligner`, `format_srt`, `_word_timings_to_segments`, `_validate_segments`
- `tests/pipeline/nodes/test_subtitle.py` — new: 29 unit tests

### Change Log

- Added aligner config settings to Settings class (2026-07-01)
- Implemented subtitle_node with forced-alignment SRT generation, WhisperX strategy, Langfuse observability, and full error handling (2026-07-01)
- Applied 4 code review patches (asyncio, audio_duration guard, SRT trailing newline, last_end fallback) (2026-07-01)

### Review Findings

- [x] [Review][Patch] asyncio.get_event_loop() → get_running_loop() in async context [subtitle.py:43]
- [x] [Review][Patch] _validate_segments audio_duration falsy-zero guard → is not None [subtitle.py:133]
- [x] [Review][Patch] format_srt missing trailing blank line after last SRT cue [subtitle.py:93]
- [x] [Review][Patch] WhisperXAligner last_end sentinel 999.0 → len(audio)/16000 [subtitle.py:59]
- [x] [Review][Defer] Partial alignment: word_segments non-empty but all unaligned silently returns [] [subtitle.py:64] — deferred, WhisperX-specific edge case, no test path without live model
- [x] [Review][Defer] WhisperX model reloaded on every scene (performance) [subtitle.py:48] — deferred, correctness not affected; cache model in instance if throughput matters
- [x] [Review][Defer] Error format is a flat string, not a structured dict (AC4 ambiguity) [subtitle.py:208] — deferred, consistent with prior nodes; revisit in API layer if parsers need structured errors
- [x] [Review][Defer] Overlapping input word_timings from TTS not pre-validated [subtitle.py:108] — deferred, TTS node is responsible for monotonic output; guard here if TTS diverges
- [x] [Review][Defer] Empty scenes list is a valid no-op but video_node has no downstream guard [subtitle.py:180] — deferred, add guard in video_node integration story
- [x] [Review][Defer] run_id path traversal via Path(workspace)/run_id with no sanitisation [subtitle.py:176] — deferred, internal CLI state; add sanitisation if run_id ever comes from HTTP input
