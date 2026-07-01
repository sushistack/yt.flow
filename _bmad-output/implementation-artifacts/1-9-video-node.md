---
baseline_commit: 9ddfc9feb256d08d8c79776ad5fe5a5da25eff0d
---

# Story 1.9: video_node

Status: done

<!-- Completion note: Ultimate context engine analysis completed - comprehensive developer guide created. -->

## Story

As Jay,
I want `video_node` to compose scene images, audio, and subtitles into a final `.mp4` via FFmpeg,
so that the pipeline produces a deliverable video file.

## Acceptance Criteria

1. Given `ShotData.image_path`, `SceneState.audio_path`, and `SceneState.subtitle_path` for all scenes, when `video_node` runs FFmpeg subprocess, then `PipelineState.video_path` is set to an existing `.mp4` under `workspace/{run_id}/`. [Source: _bmad-output/planning-artifacts/epics.md#Story-1.9-video_node]
2. Given FFmpeg is not installed or returns a non-zero exit code, when `video_node` encounters the error, then `PipelineState.error` is set with `stage="video"` and `run_id`. [Source: _bmad-output/planning-artifacts/epics.md#Story-1.9-video_node]
3. Given `video_node` execution, when it completes, then a Langfuse span named `"video"` appears with latency. [Source: _bmad-output/planning-artifacts/epics.md#Story-1.9-video_node]

## Tasks / Subtasks

- [x] Implement the pure pipeline node in `src/yt_flow/pipeline/nodes/video.py`. (AC: 1, 2, 3)
  - [x] Validate every scene has at least one shot image path, an audio path, and a subtitle path before invoking FFmpeg.
  - [x] Resolve output under `YTFLOW_WORKSPACE_PATH` defaulting to `./workspace`, specifically `workspace/{run_id}/video.mp4` or an equivalent deterministic `.mp4` path under the run directory.
  - [x] Return a replacement-style `PipelineState` update containing `current_stage="video"` and `video_path=<mp4 path>`; do not mutate state in place.
- [x] Add FFmpeg composition service/helper code only where it avoids bloating the node. (AC: 1, 2)
  - [x] Prefer a small helper such as `src/yt_flow/services/ffmpeg.py` only if command construction, probing, or error normalization becomes non-trivial.
  - [x] Invoke FFmpeg through `asyncio.create_subprocess_exec` or `subprocess.run` from a pure node-safe helper; capture stdout/stderr for error reporting.
  - [x] Build commands with argument lists, not shell strings.
- [x] Preserve graph and state contracts. (AC: 1, 2)
  - [x] Ensure `src/yt_flow/pipeline/graph.py` already routes `subtitle -> gate_subtitle -> video -> gate_video`; if graph scaffolding exists, update only the `video` binding from stub to real node.
  - [x] Do not import from `db/`, `api/`, or SSE modules in the node.
  - [x] Keep artifact paths only in `PipelineState`; do not add scenes/artifacts tables.
- [x] Add observability for the video stage. (AC: 3)
  - [x] Decorate or wrap the node with Langfuse instrumentation so the observation/span name is exactly `"video"`.
  - [x] Record latency and useful metadata: `run_id`, scene count, input asset counts, output path, FFmpeg return code.
  - [x] Treat Langfuse failures as non-fatal; log and continue according to AD-10.
- [x] Add tests and fixtures. (AC: 1, 2, 3)
  - [x] Unit test successful composition with tiny fixture assets or a mocked FFmpeg runner.
  - [x] Unit test missing FFmpeg / non-zero exit code produces `PipelineState.error` with `stage="video"` and `run_id`.
  - [x] Unit test missing required input assets fails before FFmpeg and does not write `video_path`.
  - [x] If real FFmpeg is available in CI/dev, add an integration test marked/skippable when `ffmpeg` is absent.

## Dev Notes

### Epic Context

Epic 1 builds the local Python/LangGraph pipeline from SCP text to final video: `scenario -> image -> tts -> subtitle -> video`, with Prompt Hub migration, node-level observability, and checkpoint persistence as the foundation. Story 1.9 depends on Story 1.8 because subtitles must exist before video composition. Story 1.10 will later verify resume/restart and full trace linkage, so this story must leave a clean stage boundary and correct `current_stage`/`video_path` state for checkpointing. [Source: _bmad-output/planning-artifacts/epics.md#Epic-1-Project-Foundation--Pipeline-Core]

### Architecture Guardrails

- Final architecture spine overrides older version pins embedded in the epics inventory. Use Python 3.12, LangGraph 1.2.6, `langgraph-checkpoint-sqlite` with `AsyncSqliteSaver`, SQLModel 0.0.38, FastAPI 0.115.x, and Langfuse Python SDK 4.x. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack]
- Dependency direction is strict: `api -> services -> (pipeline | db) -> domain`. Pipeline nodes never import `db/`; API never imports `pipeline/` directly. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1--Layer-dependency-direction]
- `PipelineState` is authoritative for in-flight data. The `runs` table is only a read-optimized API projection. Do not persist `video_path` in a new table. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2--LangGraph-state-is-the-single-source-of-truth]
- Stage nodes are pure functions of `PipelineState`; `services/` owns `graph.astream()`, DB sync, and SSE fan-out. `video_node` must not emit SSE events or update DB rows. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4--services-owns-DB-sync-and-SSE-fan-out]
- State updates replace fields wholesale; avoid in-place mutation of nested scene/shot structures unless an earlier implemented pattern in the repo already standardizes copy/update helpers. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions]
- `workspace/` root is configurable via `YTFLOW_WORKSPACE_PATH` and defaults to `./workspace`. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10--Operational-envelope]

### Expected State Shape

The architecture defines `ShotData.image_path`, `SceneState.audio_path`, `SceneState.audio_duration`, `SceneState.subtitle_path`, and `PipelineState.video_path`. Use the actual `src/yt_flow/domain/state.py` definitions if earlier stories have refined them, but preserve these semantic fields. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#PipelineState-OQ-7-resolved]

### FFmpeg Implementation Guidance

- Compose one final MP4 from scene image(s), scene audio, and scene subtitle files. The simplest robust approach is to render per-scene video segments with matching codec, pixel format, and resolution, burn or overlay the corresponding SRT, then concatenate the normalized segments into the final MP4.
- Official FFmpeg docs support complex filtergraphs for multi-input pipelines and `-shortest` to finish encoding when the shortest output stream ends. Use these intentionally for image/audio/subtitle synchronization. [Source: https://ffmpeg.org/ffmpeg.html]
- FFmpeg filtergraphs use comma-separated filters within a chain and semicolon-separated chains for distinct paths; generate filtergraphs carefully and test command construction. [Source: https://ffmpeg.org/ffmpeg-filters.html]
- The concat demuxer reads a list of files and demuxes them sequentially; use it only after per-scene segments are normalized to compatible codecs/container parameters. [Source: https://ffmpeg.org/ffmpeg-formats.html]
- For subtitles, prefer a deterministic strategy. If burning subtitles into the video with FFmpeg's `subtitles` filter, ensure the installed FFmpeg has libass support; otherwise fail clearly with `stage="video"` and stderr detail.
- Avoid shell interpolation for filter paths. SRT paths can contain special characters; quote/escape through FFmpeg argument rules or write temporary concat/filter files in `workspace/{run_id}/`.

### Error Handling

- If FFmpeg binary discovery fails, set `PipelineState.error` with enough detail to diagnose missing installation and include `stage="video"` plus `run_id`.
- If FFmpeg exits non-zero, include stderr tail in the error detail. Do not claim completion; `video_path` must remain `None` or absent from the returned update.
- If an input asset path is missing or does not exist, fail before running FFmpeg with `stage="video"`, `run_id`, and the missing field/path.
- Pipeline errors additionally carry `stage` and `run_id`; FastAPI error shaping is for later API layers. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions]

### Observability Requirements

- Every node has Langfuse tracing. For this story, the span/observation name must be the stage literal `"video"`. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions]
- Langfuse SDK 4.x supports manual/custom instrumentation using context managers, wrappers, or manual observations; context manager observations propagate child observations through OpenTelemetry context. Use the pattern already established by earlier node stories if present. [Source: https://langfuse.com/docs/observability/sdk/instrumentation]
- Observability must not become a hard dependency for successful video generation; architecture says tracing failures are non-fatal. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10--Operational-envelope]

### Project Structure Notes

Expected files once earlier stories have run:

```text
src/yt_flow/
  domain/state.py
  pipeline/graph.py
  pipeline/gates.py
  pipeline/nodes/video.py
  config.py
tests/
  pipeline/nodes/test_video.py
```

Current repository inspection found no `src/` or `tests/` tree yet. If implementing this story before Stories 1.1-1.8, first create or run the prerequisite scaffold stories; otherwise reuse their actual patterns and do not reinvent domain types, config loading, Langfuse setup, or graph construction.

### Previous Story Intelligence

No previous implementation story file exists under `_bmad-output/implementation-artifacts/` for Epic 1 story 1.8 at story creation time. Use the epics and architecture documents as the implementation source of truth. If Stories 1.1-1.8 are implemented before this story is developed, inspect their committed code and story Dev Agent Records before touching `video_node`.

### Git Intelligence

Recent commits are planning/setup only:

- `2390ead` initialized sprint status tracking.
- `4be98ee` added epic breakdown and readiness report.
- `6db2416` added UX design specs and HTML mockups.
- `ca2fb1d` added architecture design and review docs.
- `b9dc0b0` added the PRD.

There are no implementation commits yet, so no local code pattern supersedes the architecture spine.

### Testing Requirements

- Use `uv` and the test runner established by Story 1.2. If none exists yet, add focused pytest coverage with clear fixture boundaries.
- Do not require cloud APIs, ComfyUI, Langfuse availability, or long media generation in unit tests.
- Mock the FFmpeg runner for fast unit tests; separately add a skippable integration test that checks `shutil.which("ffmpeg")`.
- Test that output file existence is verified before setting `video_path`.
- Test that error paths do not leave stale `video_path` in the returned state update.

### UX / API Downstream Impact

This story does not implement UI or API endpoints, but it must produce state that downstream stories can expose:

- Epic 2 `GET /runs/{id}/artifact` expects a completed run to have a downloadable final video. [Source: _bmad-output/planning-artifacts/epics.md#Story-2.1-FastAPI-app--SQLModel--basic-Run-CRUD]
- Epic 3's video artifact panel expects a full-width native `<video controls>` player and download link for the `video` stage. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run-Detail--artifact-panel-by-stage]

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md`
- FFmpeg docs: https://ffmpeg.org/ffmpeg.html, https://ffmpeg.org/ffmpeg-filters.html, https://ffmpeg.org/ffmpeg-formats.html
- Langfuse instrumentation docs: https://langfuse.com/docs/observability/sdk/instrumentation

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- Fixed `nodes/__init__.py` naming collision: importing `video_node as video` shadowed the `video` submodule, causing `AttributeError` in tests. Fixed by importing as `video_node` and referencing it explicitly in `STAGE_NODES`.
- Pyright type narrowing for `str | None` in list comprehension: replaced comprehension with explicit loop in `_validate_scene_assets` so Pyright correctly infers `list[str]`.

### Completion Notes List

- Implemented `video_node` in `src/yt_flow/pipeline/nodes/video.py` following the subtitle_node pattern exactly.
- FFmpeg composition: per-scene segments via `_compose_scene` (image loop + audio + burned SRT subtitles), then single-segment rename or multi-segment concat via `_concat_segments` (concat demuxer).
- FFmpeg invoked via `asyncio.create_subprocess_exec` with argument lists, never shell strings. [AC:1, AD-1]
- Pre-flight asset validation via `_validate_scene_assets` runs before FFmpeg, fails fast with `stage=video` error. [AC:2]
- `@observe(name="video")` + `_record_trace` with latency, run_id, scene_count, output_path, returncode. [AC:3]
- Langfuse failures non-fatal (bare except in `_record_trace`). [AD-10]
- Input state never mutated; returns replacement-style partial update. [AD-4]
- No imports from `db/`, `api/`, or `services/` in the node. [AD-1]
- Updated `nodes/__init__.py` to wire real `video_node` into `STAGE_NODES["video"]` (Story 1.9 task: update stub binding).
- Updated `tests/pipeline/test_graph.py` stub test to exclude `video` (now real/async).
- 25 unit tests pass; 1 integration test (real FFmpeg, skippable) added.
- Full test suite: 130 passed, 1 skipped (Qwen TTS smoke test), 0 failures.

### File List

- `src/yt_flow/pipeline/nodes/video.py` (new)
- `src/yt_flow/pipeline/nodes/__init__.py` (modified — wired real video_node)
- `tests/pipeline/nodes/test_video.py` (new)
- `tests/pipeline/test_graph.py` (modified — updated stub test to exclude video)
- `_bmad-output/implementation-artifacts/1-9-video-node.md` (modified — story tracking)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — in-progress → review)

## Change Log

- 2026-07-01: Story 1.9 implemented — video_node with FFmpeg composition, observability, full test coverage (claude-sonnet-4-6)
