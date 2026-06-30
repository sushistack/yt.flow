# Story 2.5: Data Access — SCP List & Stage Artifacts

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want to list available SCP entries and retrieve intermediate stage artifacts via API,
so that the UI can populate the SCP picker and display per-stage output.

## Acceptance Criteria

1. Given `GET /scps`, when called, then returns list from `app.state.scps` (in-memory, loaded at startup) with `id`, `nickname`, `object_class`, `rating`; no per-request file I/O (FR-33).
2. Given `GET /runs/{id}/stages/image/artifacts` on a completed image stage, when called, then returns artifact data by reading LangGraph state — not the `runs` table (FR-28, AD-7).
3. Given `GET /runs/{id}/stages/scenario/artifacts` on a stage not yet reached, when called, then returns HTTP 404.
4. Given `GET /runs/{id}/stages/{stage}/artifacts` with an invalid run_id, when called, then returns HTTP 404 with `{"detail": "Run not found"}`.
5. Given `GET /runs/{id}/stages/{stage}/artifacts` where the stage exists in the graph topology but the run's checkpoint has no data for that stage (not yet executed), when called, then returns HTTP 404.
6. Given `GET /scps` when `data/scps.json` is missing or malformed at startup, when the app starts, then FastAPI lifespan raises a clear error at startup (fail-fast); a running app that reached startup successfully always returns a valid list from `GET /scps`.

## Tasks / Subtasks

- [ ] Create SCP route `GET /scps` (AC: 1, 6)
  - [ ] Create `src/yt_flow/api/routes/scps.py`.
  - [ ] Define `ScpEntry` Pydantic model: `id: str`, `nickname: str`, `object_class: str`, `rating: int`.
  - [ ] Implement `GET /scps`: read `app.state.scps` (loaded in lifespan by Story 2.1) and return `list[ScpEntry]`.
  - [ ] Register `scps` router in `api/main.py`.

- [ ] Create artifact retrieval service `get_stage_artifacts()` (AC: 2, 3, 5)
  - [ ] Add `async def get_stage_artifacts(run_id: str, stage: str) -> dict` to `src/yt_flow/services/run_service.py`.
  - [ ] Build LangGraph config from `run_id`: `{"configurable": {"thread_id": run_id}}`.
  - [ ] Call `graph.aget_state(config)` to read checkpoint (read-only — no `astream()` needed).
  - [ ] If `state.values` is empty or missing (no checkpoint for this run), raise `LookupError` (→ 404).
  - [ ] Extract `PipelineState` from checkpoint.
  - [ ] Validate `stage` is one of the five stage literals (`scenario`, `image`, `tts`, `subtitle`, `video`) — raise `ValueError` (→ 422) if not.
  - [ ] Determine if the stage has been reached:
    - Stage is reached if its output fields in `PipelineState` are non-None/non-empty.
    - Per-stage output indicators:
      - `scenario`: `PipelineState.scenes` is non-empty `list[SceneState]`.
      - `image`: every `ShotData.image_path` in `scenes[*].shots[*]` is non-None.
      - `tts`: every `SceneState.audio_path` is non-None.
      - `subtitle`: every `SceneState.subtitle_path` is non-None.
      - `video`: `PipelineState.video_path` is non-None.
    - If stage not reached, raise `LookupError` (→ 404).
  - [ ] Build and return per-stage artifact response dict (see Dev Notes: Per-Stage Artifact Response Shapes).
  - [ ] If `graph` is not yet wired (e.g., Story 1.4 not implemented), implement as a stub that returns a hardcoded artifact response for testing or raises a clear `NotImplementedError`.

- [ ] Create artifact route `GET /runs/{id}/stages/{stage}/artifacts` (AC: 2, 3, 4, 5)
  - [ ] Add endpoint to `src/yt_flow/api/routes/runs.py`.
  - [ ] Accept `stage: str` path parameter validated against the five stage literals.
  - [ ] Call `run_service.get_stage_artifacts(run_id, stage)`.
  - [ ] Map `LookupError` → HTTP 404; `ValueError` → HTTP 422.
  - [ ] Return artifact response dict as JSON.

- [ ] Wire up and verify (AC: 1–6)
  - [ ] Ensure `data/scps.json` is committed and valid (copy from `~/Documents/myWorkflows/` or create sample ≥10 entries).
  - [ ] Register both routers in `api/main.py`.
  - [ ] Write tests (see Testing section below).
  - [ ] Run `uv sync && uv run uvicorn src.yt_flow.api.main:app --reload`.
  - [ ] Verify `GET /scps` returns SCP list.
  - [ ] Verify artifact endpoint returns correct per-stage data (or 404/422 for edge cases).

## Dev Notes

### Scope Boundary

This story provides **two read-only data access endpoints** that the UI layer (Epic 3) depends on: the SCP picker data source and the per-stage artifact viewer. It is the **last backend story before the frontend** — after this, the API surface has every endpoint the React SPA needs.

**This story touches these files:**

| File | Action | Purpose |
|------|--------|---------|
| `src/yt_flow/api/routes/scps.py` | **NEW** | `GET /scps` endpoint |
| `src/yt_flow/api/routes/runs.py` | **UPDATE** | Add `GET /runs/{id}/stages/{stage}/artifacts` |
| `src/yt_flow/services/run_service.py` | **UPDATE** | Add `get_stage_artifacts()` |
| `src/yt_flow/api/main.py` | **UPDATE** | Register `scps` router |
| `data/scps.json` | **ENSURE EXISTS** | SCP facts data (committed to repo) |

**Do NOT implement in this story:**
- SSE streaming (`/runs/{id}/progress`) → Story 2.2
- Gate mechanism, `interrupt()`, `Command(resume=...)` → Story 2.3
- Stage retry (`POST /runs/{id}/stages/{stage}/retry`) → Story 2.4
- Artifact edit (`PATCH /runs/{id}/stages/{stage}/artifact`) → Story 2.4
- `GET /scps` filtering/search logic — the route returns the full list; UI does client-side filtering (UX-DR8)
- Writing to LangGraph state (this story is read-only — only `aget_state()`, never `update_state()` or `astream()`)
- React frontend or `/app` static mount → Epic 3
- Auth, CORS, or security middleware → local-only, single operator

### Architecture Guardrails

#### AD-4 — `services/` owns all LangGraph interactions

`services/` is the **only layer permitted to call `graph.aget_state()`**, `graph.astream()`, or `graph.update_state()`. `api/routes/` never calls LangGraph directly. This story's artifact endpoint must call `run_service.get_stage_artifacts()`, not `graph.aget_state()` from the route handler.

[Source: `ARCHITECTURE-SPINE.md#AD-4-services-owns-DB-sync-and-SSE-fan-out`]

#### AD-7 — Artifact paths live only in PipelineState

Artifact paths live only in `PipelineState` — no `scenes` or `artifacts` table. `GET /runs/{id}/stages/{stage}/artifacts` reads LangGraph state, **not** the `runs` table. Do NOT add artifact columns to the `Run` SQLModel.

[Source: `ARCHITECTURE-SPINE.md#AD-7-Single-SQLite-file-no-scenes-table-AsyncSqliteSaver`]

#### AD-2 — LangGraph state is the single source of truth

The `runs` table is a read-optimized API projection only. Artifact data comes from `PipelineState` via LangGraph checkpoint — never from the DB.

[Source: `ARCHITECTURE-SPINE.md#AD-2-LangGraph-state-is-the-single-source-of-truth`]

### Per-Stage Artifact Response Shapes

The artifact endpoint returns stage-specific JSON. These shapes are designed to match what the UI panels need (UX-DR10):

#### scenario — narrative text + shot data

```json
{
  "stage": "scenario",
  "scenes": [
    {
      "scene_num": 1,
      "narration": "SCP-096은 어두운 복도에 서 있었다...",
      "shots": [
        {
          "shot_id": "S001",
          "sentence_indices": [0, 1],
          "image_prompt": "A dark corridor...",
          "negative_prompt": "daylight, bright...",
          "camera_angle": "medium",
          "camera_movement": "static"
        }
      ]
    }
  ]
}
```

#### image — image paths per shot

```json
{
  "stage": "image",
  "images": [
    {"scene_num": 1, "shot_id": "S001", "image_path": "workspace/{run_id}/images/S001.png"},
    {"scene_num": 1, "shot_id": "S002", "image_path": "workspace/{run_id}/images/S002.png"}
  ]
}
```

#### tts — audio paths + durations per scene

```json
{
  "stage": "tts",
  "audio": [
    {"scene_num": 1, "audio_path": "workspace/{run_id}/audio/scene_01.mp3", "duration_sec": 12.5}
  ]
}
```

#### subtitle — subtitle paths per scene

```json
{
  "stage": "subtitle",
  "subtitles": [
    {"scene_num": 1, "subtitle_path": "workspace/{run_id}/subtitles/scene_01.srt"}
  ]
}
```

#### video — video path

```json
{
  "stage": "video",
  "video_path": "workspace/{run_id}/output.mp4"
}
```

**Important:** The response shapes above are derived from `PipelineState` fields. Build them by reading the checkpoint state — do NOT hardcode or store them in the DB. If `PipelineState` field names differ from what was implemented in Story 1.2, adapt the response keys to match the actual `PipelineState` fields.

### Conventions

| Concern | Convention |
|---------|------------|
| Naming | `snake_case` modules; `PascalCase` models/TypedDicts; stage literals: `scenario`, `image`, `tts`, `subtitle`, `video` |
| Naming — API routes | `kebab-case` path segments; stage in path must match stage literal exactly |
| IDs | UUID v4 strings everywhere; never auto-increment integers |
| Error shape | FastAPI `HTTPException` with `detail: str` |
| Config | Pydantic `BaseSettings` in `config.py`; env prefix `YTFLOW_` |
| SCP data | `data/scps.json` committed to repo; loaded into memory at startup via FastAPI lifespan (`app.state.scps`); `GET /scps` filters in-memory — no per-request file I/O |

### LangGraph `aget_state()` Usage

This story introduces the first read-only LangGraph state access (previous stories use `astream()` for execution). Key details:

```python
# services/run_service.py
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from yt_flow.config import settings

async def get_stage_artifacts(run_id: str, stage: str) -> dict:
    config = {"configurable": {"thread_id": run_id}}
    
    # graph is the compiled StateGraph from pipeline/graph.py
    state = await graph.aget_state(config)
    
    if not state.values:
        raise LookupError(f"No checkpoint found for run {run_id}")
    
    pipeline_state = state.values  # PipelineState TypedDict
    # ... extract per-stage data ...
```

**Reachability check per stage:** Use the following heuristics derived from which node populates each field:
- `scenario` node sets `scenes` → check `pipeline_state.get("scenes")` is non-empty
- `image` node sets `ShotData.image_path` → check all shots have non-None `image_path`
- `tts` node sets `SceneState.audio_path` → check all scenes have non-None `audio_path`
- `subtitle` node sets `SceneState.subtitle_path` → check all scenes have non-None `subtitle_path`
- `video` node sets `video_path` → check `pipeline_state.get("video_path")` is non-None

These heuristics are intentionally simple — they don't require knowledge of `current_stage` or `gate_states` from the runs table. The LangGraph checkpoint is the sole truth source.

### Project Structure Notes

This is a **greenfield project** — no Python source files exist yet. Stories 1.1 through 2.4 have not been implemented. The dev agent must ensure prerequisite files exist or create stubs:

**Files this story expects to exist (from Story 2.1):**
- `src/yt_flow/api/main.py` — FastAPI app with lifespan that loads `data/scps.json` into `app.state.scps`
- `src/yt_flow/api/routes/runs.py` — existing run CRUD endpoints
- `src/yt_flow/services/run_service.py` — `start_run()` stub from Story 2.1
- `src/yt_flow/config.py` — `YTFLOW_DB_PATH` setting
- `data/scps.json` — SCP facts data

**Files this story expects to exist (from Epic 1):**
- `src/yt_flow/domain/state.py` — `PipelineState`, `SceneState`, `ShotData`, `WordTiming` TypedDicts
- `src/yt_flow/pipeline/graph.py` — compiled `StateGraph` with `AsyncSqliteSaver`

**If prerequisite files don't exist:** Create minimal stubs sufficient for this story's ACs to pass. For example:
- If `graph.py` doesn't exist yet, create a stub that returns a mock `PipelineState` from `aget_state()`.
- If `state.py` doesn't exist yet, create the TypedDicts this story needs.

**SCP data file (`data/scps.json`):** Must be committed to the repo. Expected shape:
```json
[
  {"id": "SCP-096", "nickname": "shy-guy", "object_class": "Euclid", "rating": 150},
  {"id": "SCP-173", "nickname": "the-sculpture", "object_class": "Euclid", "rating": 200}
]
```

### Previous Story Intelligence

**Story 2-1 (`fastapi-sqlmodel-run-crud`):** Status is `ready-for-dev` — spec created, not yet implemented. Key context this story inherits:

- `api/main.py` lifespan pattern: `@asynccontextmanager` that calls `SQLModel.metadata.create_all()` and loads `data/scps.json` into `app.state.scps`
- `services/run_service.py` exports `start_run()` as the async entry point
- `api/routes/runs.py` has `POST /runs`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/artifact`
- Run model (`db/models.py`) uses UUID v4 string primary keys, not auto-increment
- `config.py` uses Pydantic `BaseSettings` with `YTFLOW_` env prefix

**Cross-story dependency:** The `GET /scps` endpoint reads `app.state.scps` which must be populated by the lifespan in `api/main.py` (Story 2.1). The artifact endpoint needs `graph.aget_state()` to work, which requires Story 1.4 (LangGraph + AsyncSqliteSaver). These are hard dependencies.

**No prior implementations or codebase learnings exist** — this is a greenfield project. All stories in Epic 1 and Epic 2 are either `ready-for-dev` or `backlog`.

### Latest Library Versions (2026-07-01)

| Library | Architecture Spine | Latest Stable | Notes |
|---------|-------------------|---------------|-------|
| FastAPI | 0.115.x | **0.138.2** | ⚠️ 0.137.0 breaking: `router.routes` is no longer a plain list. Use `iter_route_contexts()` if iterating routes. Not relevant to this story. |
| SQLModel | 0.0.38 | **0.0.39** | Safe upgrade. No API changes. |
| Pydantic | 2.x | **2.13.4** | `BaseSettings` in separate `pydantic-settings` package. No breaking changes. |
| LangGraph | 1.2.6 | **1.2.7** | Checkpoint API (`aget_state`, `update_state`) stable. Safe to use either version. |
| langgraph-checkpoint-sqlite | separate pkg | latest | Provides `AsyncSqliteSaver` at `langgraph.checkpoint.sqlite.aio`. |

**Recommendation:** Follow the architecture spine versions unless a specific fix is needed. The delta between pinned and latest is small and non-breaking for this story's concerns.

### Testing

**Test framework:** `pytest` + `httpx.AsyncClient` (via `httpx`, included with `fastapi[standard]`). Use in-memory SQLite for tests (set `YTFLOW_DB_PATH=:memory:` or use a temp file).

**Test cases:**

| # | Endpoint | Scenario | Expected |
|---|----------|----------|----------|
| 1 | `GET /scps` | Normal | 200, list of `ScpEntry` with correct fields |
| 2 | `GET /scps` | `data/scps.json` missing | App fails at startup (lifespan error) |
| 3 | `GET /runs/{id}/stages/scenario/artifacts` | Stage completed | 200, artifact JSON with scenes array |
| 4 | `GET /runs/{id}/stages/image/artifacts` | Image stage completed | 200, artifact JSON with images array |
| 5 | `GET /runs/{id}/stages/tts/artifacts` | TTS stage completed | 200, artifact JSON with audio array |
| 6 | `GET /runs/{id}/stages/subtitle/artifacts` | Subtitle stage completed | 200, artifact JSON with subtitles array |
| 7 | `GET /runs/{id}/stages/video/artifacts` | Video stage completed | 200, artifact JSON with video_path |
| 8 | `GET /runs/{id}/stages/scenario/artifacts` | Stage not yet reached | 404 |
| 9 | `GET /runs/{id}/stages/{stage}/artifacts` | Invalid run_id | 404 |
| 10 | `GET /runs/{id}/stages/{stage}/artifacts` | Invalid stage name (e.g., `"render"`) | 422 |

**Mocking strategy:** For artifact endpoint tests, mock `graph.aget_state()` to return a `PipelineState` with appropriate field values per stage. Do NOT require a real LangGraph DB for unit tests.

### Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
