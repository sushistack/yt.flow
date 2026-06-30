# Story 2.4: Stage Control — Retry & Inline Artifact Edit

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want to re-run individual pipeline stages and edit stage text artifacts in-place via API,
So that I can correct output without restarting the full pipeline.

## Acceptance Criteria

1. **Retry — happy path:** Given `POST /runs/{id}/stages/{stage}/retry` where `gate_states` for that stage is `"approved"`, `"rejected"`, or `"failed"`, when called, then new execution starts from the target stage node; SSE emits `stage_entry` for that stage; `gate_states[stage]` resets to `"pending"` (FR-30, AD-9).

2. **Retry — conflict:** Given `POST /runs/{id}/stages/{stage}/retry` where `gate_states[stage]` is `"pending"` or the stage has not yet run, when called, then returns HTTP 409 Conflict.

3. **Retry — not found:** Given `POST /runs/{id}/stages/{stage}/retry` with an unknown `run_id` or invalid stage name, when called, then returns HTTP 404 with `{"detail": "Run not found"}` or `{"detail": "Unknown stage"}`.

4. **Artifact edit — happy path:** Given `PATCH /runs/{id}/stages/{stage}/artifact` with an edited text body for `scenario` or `subtitle`, when called, then `graph.update_state()` persists the edit to the LangGraph checkpoint; the artifact file on disk is rewritten; returns HTTP 200 with `{"stage": stage, "updated": true}` (FR-34, AD-8).

5. **Artifact edit — invalid stage:** Given `PATCH /runs/{id}/stages/{stage}/artifact` where stage is `image`, `tts`, or `video`, when called, then returns HTTP 422 Unprocessable Entity with `{"detail": "Artifact editing is only supported for scenario and subtitle stages"}`.

6. **Artifact edit — not found:** Given `PATCH /runs/{id}/stages/{stage}/artifact` with an unknown `run_id` or a stage not yet run, when called, then returns HTTP 404.

7. **Retry state rewind correctness:** Given a retry on `scenario` where `PipelineState.scenes` was populated from a prior run, when `graph.update_state()` nullifies stage outputs, then the checkpoint has `scenes: []`, `video_path: None`, and downstream stage outputs cleared (AD-9 nullification cascade).

## Tasks / Subtasks

- [ ] Create stage control routes
  - [ ] Create `src/yt_flow/api/routes/stages.py` — `POST /runs/{id}/stages/{stage}/retry` and `PATCH /runs/{id}/stages/{stage}/artifact`.
  - [ ] Register the `stages` router in `api/main.py`.
  - [ ] Validate stage name is one of the 5 stage literals (`scenario`, `image`, `tts`, `subtitle`, `video`); reject invalid stage names with 404.
- [ ] Implement retry logic in `run_service.py`
  - [ ] Add `async def retry_stage(run_id: str, stage: str)` to `src/yt_flow/services/run_service.py`.
  - [ ] Gate state check: load `Run` from DB; parse `gate_states` JSON. If `gate_states[stage]` is `"pending"` or absent → raise `HTTPException(409)`.
  - [ ] Nullify stage outputs: call `graph.update_state(config, nullified_state, as_node=stage)` to zero out the stage's outputs in the LangGraph checkpoint (AD-9).
  - [ ] Ensure downstream cascade: nullifying `scenario` clears `scenes`, `video_path`, and all downstream stage outputs. Nullifying `image` clears `image_path` on all `ShotData` and downstream outputs. Follow the cascade table below.
  - [ ] Re-invoke pipeline: call `graph.astream(None, config)` to resume from the target node (AD-9).
  - [ ] Emit SSE `stage_entry` event for the retried stage via the per-run `asyncio.Queue` (AD-4).
  - [ ] Return HTTP 202 Accepted immediately; pipeline execution proceeds in background.
- [ ] Implement artifact edit logic in `run_service.py`
  - [ ] Add `async def edit_artifact(run_id: str, stage: str, body: str)` to `src/yt_flow/services/run_service.py`.
  - [ ] Validate stage: only `scenario` and `subtitle` are valid — else `HTTPException(422)` (FR-34, AD-8).
  - [ ] Update LangGraph checkpoint: call `graph.update_state(config, {stage_field: body}, as_node=stage)` where `stage_field` is `"scenes[n].narration"` for scenario and the subtitle text for subtitle. (Note: exact field path depends on PipelineState structure — the scenario's main text artifact lives in `scenes[*].narration`; the subtitle text is in the SRT file content.)
  - [ ] Rewrite artifact file on disk: after checkpoint update, write the edited text to the corresponding artifact file under `workspace/{run_id}/`.
  - [ ] Return HTTP 200; do NOT re-run the stage.
  - [ ] Ensure `api/routes/` calls this via `services/` — never calls `graph.update_state()` directly (AD-4).
- [ ] Wire retry into SSE event stream
  - [ ] On retry initiation, push `stage_entry` for the retried stage to the per-run `asyncio.Queue` so SSE clients see the stage transition. (The `run_service.retry_stage()` must accept or look up the queue from the SSE registry.)
  - [ ] On retry completion (success or failure), the normal `stage_exit` or `run_failed` event flow applies — no special retry events needed.
- [ ] Add tests
  - [ ] Test `POST /runs/{id}/stages/scenario/retry` on a run with `gate_states["scenario"] = "approved"` — verify 202 and SSE `stage_entry` for `scenario`.
  - [ ] Test `POST /runs/{id}/stages/scenario/retry` on a run with `gate_states["scenario"] = "pending"` — verify 409.
  - [ ] Test `POST /runs/{id}/stages/image/retry` on a run with `gate_states["image"] = "failed"` — verify 202.
  - [ ] Test `POST /runs/{id}/stages/nonexistent/retry` — verify 404.
  - [ ] Test `PATCH /runs/{id}/stages/scenario/artifact` with edited text — verify 200, checkpoint updated, file rewritten.
  - [ ] Test `PATCH /runs/{id}/stages/video/artifact` — verify 422.
  - [ ] Test `PATCH /runs/{id}/stages/scenario/artifact` on stage not yet run — verify 404.
  - [ ] Test retry cascade: after retrying `scenario`, verify that `scenes`, `video_path`, and all downstream stage outputs are cleared from checkpoint.
- [ ] Verify locally
  - [ ] Run `uv run uvicorn src.yt_flow.api.main:app --reload`.
  - [ ] Create a run, advance to `scenario` completion, then `POST /runs/{id}/stages/scenario/retry` — verify behavior.
  - [ ] `PATCH /runs/{id}/stages/scenario/artifact` — verify checkpoint update and file rewrite.
  - [ ] Run `uv run pytest` — all tests pass.

## Dev Notes

### Scope Boundary

This story implements **two API endpoints** that give the operator fine-grained control over individual pipeline stages:

1. **`POST /runs/{id}/stages/{stage}/retry`** — Re-execute a single stage from its checkpointed entry point, nullifying that stage's outputs and all downstream outputs.
2. **`PATCH /runs/{id}/stages/{stage}/artifact`** — Edit a text artifact in-place without re-running the stage; valid for `scenario` and `subtitle` only.

**Do NOT implement in this story:**
- Gate mechanism (`POST /gate`, `interrupt()`, `Command(resume=...)`) → Story 2.3
- SSE endpoint (`GET /runs/{id}/progress`) or `asyncio.Queue` registry → Story 2.2
- `GET /scps` or `GET /runs/{id}/stages/{stage}/artifacts` → Story 2.5
- `POST /runs` or `GET /runs` or `GET /runs/{id}` → Story 2.1
- Any UI components (retry button, inline editor) → Epic 3 (Story 3.5)
- A/B evaluation retry → Epic 4

**This story assumes the following are already implemented:**
- Story 2.1: FastAPI app, `Run` SQLModel, `run_service.py` with `start_run()`, `api/routes/runs.py`
- Story 2.2: `asyncio.Queue` registry for SSE, `src/yt_flow/api/sse.py`
- Story 2.3: Gate nodes in `gates.py`, `gate_states` populated in `PipelineState` and mirrored to `runs` table, `POST /gate` endpoint
- Epic 1: All 10 stories — `PipelineState` TypedDict, `StateGraph` with 10 nodes, `AsyncSqliteSaver`, all 5 stage nodes (scenario, image, tts, subtitle, video), resume/restart, domain types

**If any of these are not yet implemented**, the dev agent must create stub interfaces sufficient to make this story's endpoints functional and independently testable. For LangGraph interactions (`graph.update_state()`, `graph.astream()`), use a mock or stub `Graph` if the real graph is not yet wired — but structure the code so the real graph drops in without refactoring.

### Architecture Guardrails

#### AD-9 — Stage retry rewinds via `graph.update_state()` + re-invoke

**Rule:** `POST /runs/{id}/stages/{stage}/retry` calls `graph.update_state(config, nullified_stage_state, as_node=stage)` to zero out that stage's outputs in the checkpoint, then calls `graph.astream(None, config)` to re-execute from that node. No new LangGraph thread is created; the original thread's checkpoint is mutated in-place.

[Source: `ARCHITECTURE-SPINE.md#AD-9`]

**Retry cascade — what to nullify per stage:**

| Retried stage | Nullify in checkpoint |
|---|---|
| `scenario` | `scenes: []`, `video_path: None`, all downstream stage artifact paths cleared; `gate_states` reset for scenario+downstream |
| `image` | All `ShotData.image_path` → `None`, `video_path: None`, downstream tts/subtitle/video artifact paths cleared; `gate_states` reset for image+downstream |
| `tts` | All `SceneState.audio_path` → `None`, `word_timings: []`, `audio_duration: None`, downstream subtitle/video artifact paths cleared; `gate_states` reset for tts+downstream |
| `subtitle` | All `SceneState.subtitle_path` → `None`, `video_path: None`; `gate_states` reset for subtitle+downstream |
| `video` | `video_path: None`; `gate_states` reset for video only |

The `as_node=stage` parameter tells LangGraph which node to re-enter. The nullified state ensures no stale data persists.

#### AD-8 — Artifact text edits go through `graph.update_state()`

**Rule:** `PATCH /runs/{id}/stages/{stage}/artifact` calls `graph.update_state()` to persist the edit into the LangGraph checkpoint, then rewrites the artifact file on disk. Valid for `scenario` and `subtitle` stages only.

[Source: `ARCHITECTURE-SPINE.md#AD-8`]

**What to update per stage:**

| Stage | Field in PipelineState | File on disk |
|---|---|---|
| `scenario` | `scenes[*].narration` — the Korean prose text for each scene | `workspace/{run_id}/scenario/scenario.txt` (or however story 1.5 stores it) |
| `subtitle` | The SRT text content — stored as `scenes[*].subtitle_path` pointing to the `.srt` file | `workspace/{run_id}/subtitle/scene_{n}.srt` |

For `scenario`, the edit body contains the full edited narration text. The dev must parse it back into per-scene `narration` fields if the scenario node stores them that way. If the scenario stores a single text blob, update that blob.

#### AD-1 — Layer dependency direction

Import path must follow `api → services → (pipeline | db) → domain`. `api/routes/stages.py` never imports `pipeline/` directly. Cross-layer imports are forbidden.

[Source: `ARCHITECTURE-SPINE.md#AD-1`]

#### AD-2 — LangGraph state is the single source of truth

The `runs` table is a read-optimised API projection only. All in-flight pipeline data (artifact paths, scenes, gate_states) lives in `PipelineState`, persisted by `AsyncSqliteSaver`. `services/` updates `runs` table from LangGraph events — never independently.

[Source: `ARCHITECTURE-SPINE.md#AD-2`]

#### AD-4 — `services/` owns DB sync and SSE fan-out

`services/` is the **only layer permitted to call `graph.astream()` or `graph.update_state()`** — `api/routes/` never calls LangGraph directly. On retry, `run_service.retry_stage()` calls `graph.update_state()` then `graph.astream()`. The route handler returns 202 immediately.

[Source: `ARCHITECTURE-SPINE.md#AD-4`]

### Required Data Contracts

#### Retry Request/Response

```
POST /runs/{id}/stages/{stage}/retry
# No request body required

Response 202:
{
  "run_id": "<uuid>",
  "stage": "scenario",
  "status": "retrying",
  "message": "Stage retry initiated — stage_entry SSE event will confirm execution start"
}

Response 409:
{
  "detail": "Cannot retry stage 'scenario': gate state is 'pending'. Stage must be approved, rejected, or failed to retry."
}
```

#### Artifact Edit Request/Response

```
PATCH /runs/{id}/stages/{stage}/artifact
Content-Type: application/json

{
  "body": "Edited narration text or SRT content..."
}

Response 200:
{
  "run_id": "<uuid>",
  "stage": "scenario",
  "updated": true,
  "message": "Artifact updated in checkpoint and on disk"
}

Response 422:
{
  "detail": "Artifact editing is only supported for scenario and subtitle stages"
}
```

### Service Layer Contract

Add to `src/yt_flow/services/run_service.py`:

```python
async def retry_stage(run_id: str, stage: str, sse_queue: asyncio.Queue | None = None) -> None:
    """
    Retry a specific pipeline stage.

    1. Validate gate_state allows retry (approved/rejected/failed)
    2. Build nullified state dict per cascade table (AD-9)
    3. graph.update_state(config, nullified_state, as_node=stage)
    4. Push stage_entry SSE event
    5. graph.astream(None, config) — re-execute from target node
    """
    ...

async def edit_artifact(run_id: str, stage: str, body: str) -> dict:
    """
    Edit a text artifact for scenario or subtitle stages.

    1. Validate stage is 'scenario' or 'subtitle'
    2. Build state update dict per AD-8
    3. graph.update_state(config, {field: body}, as_node=stage)
    4. Rewrite artifact file on disk
    5. Return success response
    """
    ...
```

### Route Layer Contract

Create `src/yt_flow/api/routes/stages.py`:

```python
router = APIRouter(prefix="/runs/{run_id}/stages", tags=["stages"])

@router.post("/{stage}/retry", status_code=202)
async def retry_stage(
    run_id: str,
    stage: str,
    run_service: RunService = Depends(get_run_service),
):
    """
    Re-execute a specific pipeline stage.
    Stage must be approved, rejected, or failed — not pending.
    """
    ...

@router.patch("/{stage}/artifact")
async def edit_artifact(
    run_id: str,
    stage: str,
    body: ArtifactEditRequest,
    run_service: RunService = Depends(get_run_service),
):
    """
    Edit a text artifact (scenario or subtitle only).
    Persists to LangGraph checkpoint and rewrites file on disk.
    """
    ...
```

### Stage Literal Validation

All 5 valid stage names: `scenario`, `image`, `tts`, `subtitle`, `video`.

Use a Pydantic `Literal` type or a FastAPI path parameter validator:

```python
from typing import Literal

StageName = Literal["scenario", "image", "tts", "subtitle", "video"]
```

Or use a regex constraint on the path parameter:

```python
from fastapi import Path

@router.post("/{stage}/retry")
async def retry_stage(
    stage: str = Path(..., pattern=r"^(scenario|image|tts|subtitle|video)$"),
    ...
):
```

### Previous Story Intelligence

**Story 2.1 (FastAPI + SQLModel + Run CRUD)** established:
- FastAPI app scaffold with lifespan (`src/yt_flow/api/main.py`)
- `Run` SQLModel with `gate_states: str | None` (JSON blob) — this story reads/parses that field
- `run_service.py` with `start_run()` — this story adds `retry_stage()` and `edit_artifact()` to the same service
- `api/routes/runs.py` with `POST /runs`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/artifact`
- Conventions: UUID v4 strings, `datetime.utcnow().isoformat()`, `HTTPException` error shape
- Test pattern: `TestClient` with in-memory SQLite

**Stories 2.2 and 2.3** (not yet implemented, but this story depends on them):
- 2.2 provides the SSE `asyncio.Queue` registry — `retry_stage()` must push `stage_entry` events to it
- 2.3 provides `gate_states` JSON in the `runs` table — `retry_stage()` reads this to validate eligibility
- 2.3 provides `graph.astream()` calling patterns in `run_service.py` — `retry_stage()` follows the same pattern

### Expected Files (this story)

**New:**
- `src/yt_flow/api/routes/stages.py` — retry and artifact edit endpoints
- Tests under `tests/` for stage control endpoints

**Modified:**
- `src/yt_flow/api/main.py` — register stages router
- `src/yt_flow/services/run_service.py` — add `retry_stage()` and `edit_artifact()`

**Dependencies (must exist from prior stories):**
- `src/yt_flow/domain/state.py` — `PipelineState`, `SceneState`, `ShotData` (Epic 1.2)
- `src/yt_flow/pipeline/graph.py` — compiled `StateGraph` with `AsyncSqliteSaver` (Epic 1.4)
- `src/yt_flow/db/models.py` — `Run` SQLModel (Story 2.1)
- `src/yt_flow/api/sse.py` — `asyncio.Queue` registry (Story 2.2)
- `src/yt_flow/config.py` — `YTFLOW_DB_PATH`, `YTFLOW_WORKSPACE_PATH`

### Conventions (from Architecture Spine)

| Concern | Convention |
|---------|------------|
| Naming — files | `snake_case` modules; `PascalCase` models/TypedDicts |
| Naming — API routes | `kebab-case` path segments; nouns for resources, verbs only in sub-resources (`/retry`, `/gate`, `/artifact`) |
| IDs | UUID v4 strings everywhere; never auto-increment integers |
| Timestamps | `datetime.utcnow().isoformat()` stored as TEXT in SQLite |
| Error shape | FastAPI `HTTPException` with `detail: str`; pipeline errors additionally carry `stage` and `run_id` |
| Stage literals | `scenario`, `image`, `tts`, `subtitle`, `video` — English monospace, technical identifiers |
| `gate_states` format | Flat JSON dict: `{"scenario": "approved", "image": "pending", ...}` — string values only; never an array |
| Config | Pydantic `BaseSettings` in `config.py`; env prefix `YTFLOW_` |
| SSE events | Four types: `stage_entry`, `stage_exit`, `gate_pending`, `run_failed` |

### UX Context (for developer awareness)

The retry and edit endpoints support these UI behaviors (implemented in Epic 3, Story 3.5):

- **Retry button** — appears in the artifact panel header when a stage is `approved`, `rejected`, or `failed`. Outline button "재시도". On click: inline confirmation "이 스테이지를 다시 실행합니까? 확인/취소" with `role="alert"`. Auto-dismiss after 5s of no action. No modal.
- **Inline text editor** — scenario and subtitle panels only. "편집" toggles textarea; "저장" → PATCH to this endpoint; "취소" reverts. Saving does not advance the pipeline; "승인" is still required separately.
- **SSE state update** — on retry initiation, the sidebar item transitions to "실행 중" state via `stage_entry` event.

Korean UI strings throughout. Stage tokens displayed in English monospace.

### Retry vs Resume/Replay Semantics

This story's retry is distinct from Epic 1.10's resume (FR-7):

| Feature | Resume (1.10) | Retry (2.4) |
|---------|--------------|-------------|
| Trigger | System restart or explicit resume after failure | User action via API |
| Starting point | Last successful node | User-chosen stage |
| State handling | Preserves all checkpoint data | Nullifies target stage + downstream |
| Gate re-entry | Follows normal gate flow | Resets gate to pending, re-enters gate after re-execution |
| SSE events | Normal stage_entry/exit | stage_entry for retried stage |

## Project Context Reference

- **PRD**: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md` — Sections F5 (API Interface, FR-30, FR-34), F6 (Data & Job Management)
- **Architecture**: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` — AD-8 (artifact edit), AD-9 (retry), AD-1 (layering), AD-2 (state authority), AD-4 (service layer)
- **Epics**: `_bmad-output/planning-artifacts/epics.md` — Story 2.4 section
- **UX Design**: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md` — Retry Button, Inline Text Editor, SSE Progress patterns
- **Stack**: Python 3.12, LangGraph 1.2.6, FastAPI 0.115.x, SQLModel 0.0.38, langfuse 4.x
- **Project root**: `yt.flow/` — see `CLAUDE.md` and Architecture Structural Seed

## Story Completion

- Status: ready-for-dev
- Story ID: 2.4
- Story Key: 2-4-stage-control-retry-artifact-edit
- Epic: 2 — HTTP API & Gate-Controlled Pipeline Execution
- Ultimate context engine analysis completed — comprehensive developer guide created with architecture guardrails, cascade tables, API contracts, and dependency mapping.
