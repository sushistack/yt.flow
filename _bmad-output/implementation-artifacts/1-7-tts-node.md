# Story 1.7: tts_node

Status: ready-for-dev

<!-- Ultimate context engine analysis completed - comprehensive developer guide created -->

## Story

As Jay,
I want `tts_node` to generate per-scene TTS audio via Qwen TTS and capture word timings,
so that each scene has playable audio and timing data for subtitle alignment.

## Acceptance Criteria

1. Given `SceneState.narration` for each scene, when `tts_node` runs via Qwen TTS cloud API, then `SceneState.audio_path` is set to an existing audio file and `word_timings` is a non-empty `list[WordTiming]` with `word`, `start_sec`, and `end_sec`. (FR-4)
2. Given Qwen TTS API returns an error, when `tts_node` encounters it, then `PipelineState.error` is set with `stage="tts"` and `run_id`; the Langfuse span captures the error. (FR-13)
3. Given `tts_node` execution, when it completes, then a Langfuse span named `"tts"` appears with latency and token count or documented usage metrics. (FR-10)

## Tasks / Subtasks

- [ ] Verify the dependency substrate from earlier stories before coding (AC: 1, 2, 3)
  - [ ] Confirm `src/yt_flow/domain/state.py` defines `PipelineState`, `SceneState`, and `WordTiming` exactly as the architecture spine specifies.
  - [ ] Confirm `src/yt_flow/pipeline/nodes/tts.py` exists as a stub from Story 1.4 or create it only if the scaffold exists and the graph imports it.
  - [ ] Confirm config already exposes `YTFLOW_WORKSPACE_PATH`; add TTS-specific config only if absent.
- [ ] Add Qwen TTS configuration and client boundary (AC: 1, 2)
  - [ ] Add `YTFLOW_QWEN_TTS_API_KEY`, `YTFLOW_QWEN_TTS_MODEL`, `YTFLOW_QWEN_TTS_VOICE`, and `YTFLOW_QWEN_TTS_MOCK` settings using the existing Pydantic `YTFLOW_` config pattern.
  - [ ] Pin the Qwen TTS model identifier in config, never in node code.
  - [ ] Keep the API client wrapper local and small; do not introduce a broad provider abstraction unless another implemented TTS provider already exists.
- [ ] Implement `tts_node(state: PipelineState) -> Partial PipelineState` (AC: 1, 2, 3)
  - [ ] Iterate `state["scenes"]` in `scene_num` order and synthesize each `SceneState.narration`.
  - [ ] Write audio files under `workspace/{run_id}/audio/scene_{scene_num:03d}.wav` or the closest existing workspace naming convention.
  - [ ] Return a new `scenes` list with each scene replaced; do not mutate nested scene dictionaries in place.
  - [ ] Return `current_stage: "tts"` from the node result and preserve all upstream `shots`, `narration`, and prior fields.
  - [ ] On failure, return or raise consistently with existing node patterns, but ensure `PipelineState.error` contains `stage="tts"` and `run_id`.
- [ ] Produce honest `WordTiming` data (AC: 1)
  - [ ] Do not assume Qwen TTS returns word-level timestamps; current official Qwen-TTS docs describe audio output and usage, not a word-timestamp response contract.
  - [ ] If the API response has no word timings, derive provisional timings from measured audio duration and narration tokens, and document the fallback in code/tests.
  - [ ] Keep `start_sec >= 0`, `end_sec > start_sec`, monotonic ordering, and final `end_sec <= audio_duration` with a small rounding tolerance.
  - [ ] Store `audio_duration` on each `SceneState` because Story 1.8 and UI artifact preview depend on it.
- [ ] Add Langfuse observability (AC: 2, 3)
  - [ ] Decorate the node or the smallest stable node entry function with `@observe(name="tts")` following the existing Langfuse SDK v4 pattern.
  - [ ] Capture per-scene latency, total latency, model, voice, run_id, scene count, and usage/token-equivalent metrics if the provider returns them.
  - [ ] Capture error details without logging API keys or raw secrets.
  - [ ] Treat Langfuse send failures as non-fatal, consistent with AD-10.
- [ ] Add focused tests and fixtures (AC: 1, 2, 3)
  - [ ] Unit test mock-mode TTS without network access; fixture should create deterministic WAV files under a temp workspace.
  - [ ] Unit test returned scenes preserve upstream fields while adding `audio_path`, `audio_duration`, and `word_timings`.
  - [ ] Unit test Qwen/API error handling sets `stage="tts"` and includes the `run_id`.
  - [ ] Unit test timing monotonicity and file existence.
  - [ ] Add an explicit manual smoke command for real Qwen TTS, separate from default unit tests.

## Dev Notes

### Scope Boundary

This story implements the `tts` stage only. It depends on Story 1.5 producing `PipelineState.scenes[*].narration`; it does not create scenes, alter shot/image data, generate subtitles, or compose video. Story 1.8 owns forced alignment and `.srt` generation. This story may produce provisional word timings to satisfy the `WordTiming` contract, but it must not pretend those timings are forced-alignment quality.

The current repo is still mostly planning artifacts. At story-creation time there is no committed `src/` tree. If the dev agent starts before Stories 1.2, 1.4, or 1.5 are implemented, it must stop and implement only after those prerequisites exist or are included in the active dev scope.

### Architecture Compliance

- Follow AD-1 imports: `pipeline/nodes/tts.py` may import `domain` and `config`; it must not import `db`, `api`, or route/service modules. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1--Layer-dependency-direction`]
- `PipelineState` is the single source of truth. Audio artifact paths live in `SceneState.audio_path`; do not create a scenes/artifacts DB table. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2--LangGraph-state-is-the-single-source-of-truth`; `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7--Single-SQLite-file-no-scenes-table-AsyncSqliteSaver`]
- Stage nodes are pure functions of `PipelineState`: no DB writes, no SSE events, no service-layer calls. File artifact writes are allowed because node stories explicitly write runtime artifacts to `workspace/`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4--services-owns-DB-sync-and-SSE-fan-out`; `_bmad-output/planning-artifacts/epics.md#Story-1.7-tts_node`]
- State mutation convention is wholesale replacement. Build and return a new `scenes` list; do not mutate nested dictionaries in place and then return `{}`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions`]
- `current_stage` must be set to the current node literal `"tts"` by the stage node return. Do not advance it to `"subtitle"`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions`]
- Workspace root is configurable via `YTFLOW_WORKSPACE_PATH`, defaulting to `./workspace`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10--Operational-envelope`]

### Data Contract

Expected relevant state shape:

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
    scenes: list[SceneState]
    current_stage: str
    error: str | None
```

Preserve all fields not owned by this story. In particular, do not rewrite `shots`, `image_path`, `subtitle_path`, `video_path`, `gate_states`, `prompt_variant`, or `scp_text` except to carry them through in the returned state.

### Qwen TTS Implementation Notes

- Use Qwen TTS via Alibaba Cloud Model Studio / DashScope cloud API. Official Qwen-TTS docs identify the model family and speech synthesis endpoint, with audio returned by URL or binary/base64 depending on the API mode. [Source: `https://help.aliyun.com/en/model-studio/qwen-tts-api`]
- The current official documentation does not present a guaranteed word-level timestamp field for Qwen TTS responses. The dev agent must inspect the actual SDK/API response used in implementation; if no word timings exist, generate deterministic provisional `WordTiming` values from the audio duration and narration tokenization. [Source: `https://help.aliyun.com/en/model-studio/qwen-tts-api`]
- Prefer `.wav` output for simple duration measurement with Python stdlib `wave`. If the API returns another format, either request WAV through provider parameters or add the smallest existing dependency-backed duration reader already present in the project. Do not add a media stack just for duration if WAV is available.
- For Korean narration tokenization, whitespace tokenization is acceptable for this story. If narration has no whitespace, fall back to one timing segment for the full narration rather than returning an empty list.
- `audio_duration` should be measured from the written file, not guessed from text length, whenever the file format allows.
- A mid-scene Qwen failure means the whole `tts` stage fails. Do not partially checkpoint successful scene audio as a successful stage; NFR-8 accepts node-level retry granularity.

### File Structure Requirements

Likely new or updated files after prerequisites exist:

- `src/yt_flow/config.py` - add Qwen TTS settings if not already present.
- `src/yt_flow/pipeline/nodes/tts.py` - implement the node.
- `tests/pipeline/nodes/test_tts.py` or nearest existing test path - mock-mode and error tests.
- `tests/fixtures/audio/` - optional tiny fixture WAV if an existing fixture pattern supports it.
- `.env.example` - add Qwen TTS env placeholders if not already present.

Read any existing versions of these files completely before editing. If `graph.py` imports `tts_node`, preserve the import name and callable signature already wired by Story 1.4.

### Testing Requirements

- Default tests must not call Qwen cloud APIs.
- Mock mode should be controlled by `YTFLOW_QWEN_TTS_MOCK=true` or an existing test fixture hook, and must still write real local audio files so downstream file-existence checks are meaningful.
- Tests should verify:
  - all scenes receive existing `audio_path` values under the run workspace;
  - `word_timings` are non-empty and monotonic;
  - `audio_duration` is positive;
  - upstream scene fields are preserved;
  - provider failure surfaces `stage="tts"` and `run_id`;
  - Langfuse decoration/instrumentation does not make tests require a live Langfuse server.
- A real-provider smoke test may be documented but should be skipped by default unless explicit env credentials and a smoke flag are present.

### Previous Story / Git Intelligence

Story files for 1.2 and 1.6 are present in `_bmad-output/implementation-artifacts` at finalization time. They establish patterns this story should reuse:

- Story 1.2 narrows domain literals with `StageName`, `GateState`, and `PromptVariant` while preserving the architecture JSON shape. Use those aliases if implemented; do not redeclare them in `tts.py`.
- Story 1.2 requires `SceneState.audio_path`, `audio_duration`, and `word_timings`, so this story must fill existing fields rather than introducing a parallel audio artifact type.
- Story 1.6 uses mock mode that still writes/copies real files into `workspace/{run_id}/images/`; TTS mock mode should mirror that pattern by writing real audio files into `workspace/{run_id}/audio/`.
- Story 1.6 requires copied/rebuilt state rather than mutating input state in place; use the same pattern for scenes updated by TTS.
- Story 1.6 error strings include at least `stage=image`, `run_id=<run_id>`, and root cause; use the analogous `stage=tts` format unless the implemented project has since introduced a structured error helper.

Recent commits are documentation-only:

- `2390ead` initialized sprint status tracking.
- `4be98ee` added epics and implementation readiness report.
- `6db2416` added UX specs and mockups.
- `ca2fb1d` added architecture and review docs.
- `b9dc0b0` added the PRD.

Actionable implication: follow the architecture spine, Story 1.2 domain contract, Story 1.6 node/test conventions, and Ponytail rules. Once actual code exists, prefer implemented local helpers and test layout over this document's suggested filenames.

### UX / Downstream Consumers

The React artifact panel for `tts` expects per-scene native `<audio controls>` with scene index and duration, sorted by scene number. This story's `audio_path` and `audio_duration` must be sufficient for the future API/UI to expose playable per-scene audio. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run-Detail--artifact-panel-by-stage`]

### Project Rules From CLAUDE.md

- Use Ponytail full mode: no speculative abstractions, no one-implementation interfaces, no boilerplate scaffolding for later.
- Use stdlib where enough. For this story, `pathlib`, `urllib.request`, `wave`, `contextlib`, and `time.perf_counter()` are likely enough around the provider SDK.
- Never log or print API keys.

### References

- `_bmad-output/planning-artifacts/epics.md#Story-1.7-tts_node`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F1--Pipeline-Core-LangGraph`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F2--Observability-Langfuse`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#PipelineState-OQ-7-resolved`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Structural-Seed`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run-Detail--artifact-panel-by-stage`
- `CLAUDE.md#Code-Philosophy--Ponytail-always-active`
- `https://help.aliyun.com/en/model-studio/qwen-tts-api`

## Dev Agent Record

### Agent Model Used

TBD by dev-story agent

### Debug Log References

TBD

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Qwen TTS word-timing ambiguity is explicitly handled; implementation must not claim provider word timings unless the actual API response includes them.

### File List

TBD by dev-story agent
