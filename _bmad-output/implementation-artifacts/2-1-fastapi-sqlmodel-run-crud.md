# Story 2.1: FastAPI + SQLModel + Basic Run CRUD

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want a FastAPI app with the SQLModel `Run` table and basic run management endpoints,
so that I can trigger a pipeline run and query its status via HTTP.

## Acceptance Criteria

1. Given FastAPI app startup via lifespan, when the app starts, then SQLModel creates the `runs` table in `yt_flow.db` if not exists; `data/scps.json` is loaded into `app.state.scps`.
2. Given `POST /runs` with `{"scp_id": "SCP-096", "scp_text": "..."}` (and optionally `"extra": {}`), when called, then returns HTTP 201 with `{"id": "<uuid>", "status": "running", "current_stage": null, ...}` and a row is inserted in the `runs` table; `extra` field is accepted and stored but has no effect in v1 (FR-24).
3. Given `GET /runs`, when called, then returns all runs sorted by `started_at` desc with `status`, `current_stage`, `gate_states` (FR-31).
4. Given `GET /runs/{id}` with a valid run_id, when called, then returns run metadata including a `langfuse_trace_url` field (FR-25).
5. Given `GET /runs/{id}/artifact` on a completed run, when called, then returns HTTP 200 with `Content-Disposition: attachment` header and video file body (FR-26).
6. Given `POST /runs` with `{"scp_id": "SCP-096", "scp_text": "..."}` succeeds, when the 201 response is returned, then `asyncio.create_task(run_service.start_run(run_id))` is launched in the background; the task calls `graph.astream()` and drives the pipeline (services layer, AD-4).
7. Given `GET /runs/{id}` with an unknown run_id, when called, then returns HTTP 404 with `{"detail": "Run not found"}`.

## Tasks / Subtasks

- [ ] Create FastAPI app scaffold with lifespan (AC: 1)
  - [ ] Create `src/yt_flow/api/main.py` — FastAPI app instance with `@asynccontextmanager` lifespan.
  - [ ] Lifespan: call `SQLModel.metadata.create_all()` to create tables; load `data/scps.json` into `app.state.scps`.
  - [ ] Create `src/yt_flow/api/__init__.py`.
- [ ] Define SQLModel `Run` table (AC: 2)
  - [ ] Create `src/yt_flow/db/__init__.py` and `src/yt_flow/db/models.py`.
  - [ ] Define `Run(SQLModel, table=True)` with fields: `id: str` (UUID primary key), `scp_id: str`, `status: str`, `current_stage: str | None`, `gate_states: str | None` (JSON blob), `prompt_variant: str | None`, `ab_pair_id: str | None`, `error: str | None`, `started_at: str`, `updated_at: str`, `extra: str | None` (JSON blob for reserved `extra` dict), `langfuse_trace_url: str | None`.
  - [ ] Validate that `id` uses UUID v4 string (not auto-increment integer).
  - [ ] Validate that `gate_states` is stored as JSON string (flat dict: `{"scenario": "approved", ...}`).
- [ ] Create run routes (AC: 2, 3, 4, 5, 7)
  - [ ] Create `src/yt_flow/api/routes/__init__.py` and `src/yt_flow/api/routes/runs.py`.
  - [ ] `POST /runs`: accept `RunCreate` schema (`scp_id`, `scp_text`, optional `extra`), generate UUID v4, insert row with `status="running"`, return 201 with `RunRead` schema.
  - [ ] `GET /runs`: query all runs sorted by `started_at` desc, return list of `RunRead`.
  - [ ] `GET /runs/{id}`: query by `id`, return `RunRead` or 404.
  - [ ] `GET /runs/{id}/artifact`: return `FileResponse` with video file or 404 if not complete; set `Content-Disposition: attachment`.
- [ ] Create `run_service.py` stub (AC: 6)
  - [ ] Create `src/yt_flow/services/__init__.py` and `src/yt_flow/services/run_service.py`.
  - [ ] Implement `async def start_run(run_id: str)` that in this story is a stub: update run status to `"running"`, then set to `"complete"` or raise if no graph is wired.
  - [ ] Wire `asyncio.create_task(run_service.start_run(run_id))` in the `POST /runs` route handler after DB insert.
  - [ ] Ensure `graph.astream()` call pattern is structured per AD-4 (actual Graph integration deferred to story 2.3 gate mechanism; this story establishes the `services/` layer contract).
- [ ] Wire API router into FastAPI app (AC: 1, 2)
  - [ ] Include `runs` router in `api/main.py`.
  - [ ] Set up Alembic: create `src/yt_flow/db/migrations/` with initial migration for `Run` table or use `SQLModel.metadata.create_all()` for now.
- [ ] Add `scps.json` data file (AC: 1)
  - [ ] Ensure `data/scps.json` exists with SCP entries (copy from existing yt.pipe or create sample).
  - [ ] Define Pydantic schema for SCP entry (`id`, `nickname`, `object_class`, `rating`).
- [ ] Add tests (AC: 1-7)
  - [ ] Test `POST /runs` creates a row and returns 201 with correct schema.
  - [ ] Test `GET /runs` returns list sorted by `started_at` desc.
  - [ ] Test `GET /runs/{id}` returns run data; test 404 for unknown id.
  - [ ] Test `GET /runs/{id}/artifact` returns 404 for non-complete run.
  - [ ] Test `POST /runs` background task is launched (verify `run_service.start_run` is called).
  - [ ] Test `app.state.scps` is populated at startup.
  - [ ] Test `extra` field round-trips correctly.
  - [ ] Use `TestClient` (httpx-based) with in-memory SQLite for tests.
- [ ] Verify locally (AC: 1, 2, 3)
  - [ ] Run `uv sync`.
  - [ ] Run `uv run uvicorn src.yt_flow.api.main:app --reload`.
  - [ ] Verify `POST /runs`, `GET /runs`, `GET /runs/{id}` via `curl` or http://localhost:8000/docs.
  - [ ] Run `uv run pytest`.

## Dev Notes

### Scope Boundary

This story is the **foundation of Epic 2**: FastAPI app scaffold + SQLModel `Run` table + basic CRUD. It establishes the HTTP API surface that all subsequent Epic 2 stories extend with gates (2.3), SSE (2.2), retry/edit (2.4), and SCP/artifact access (2.5).

**Do NOT implement in this story:**
- Gate mechanism, `interrupt()`, `Command(resume=...)` → Story 2.3
- SSE streaming (`/runs/{id}/progress`) → Story 2.2
- Stage retry (`POST /runs/{id}/stages/{stage}/retry`) → Story 2.4
- Artifact edit (`PATCH /runs/{id}/stages/{stage}/artifact`) → Story 2.4
- `GET /scps` route → Story 2.5
- `GET /runs/{id}/stages/{stage}/artifacts` → Story 2.5
- Real LangGraph graph wiring or `graph.astream()` driving → Story 1.4 + Story 2.3
- React frontend or `/app` static mount → Epic 3
- Auth, CORS, or any security middleware → local-only, single operator

**This story must work independently** even if Epic 1 stories are not yet implemented. The `run_service.start_run()` can be a stub that transitions status `running → complete` without touching LangGraph.

### Architecture Guardrails

- **AD-1 — Layer dependency direction:** Import path must follow `api → services → (pipeline | db) → domain`. `api/routes/` never imports `pipeline/` directly. `db/models.py` may import from `domain/` for shared types. Cross-layer imports are forbidden. [Source: `ARCHITECTURE-SPINE.md#AD-1-Layer-dependency-direction`]

- **AD-2 — LangGraph state is the single source of truth:** The `runs` table is a **read-optimized API projection only** — it mirrors `status`, `current_stage`, `gate_states` and must never be the write-authoritative store for pipeline state. All in-flight pipeline data lives in `PipelineState`. `services/` updates `runs` table from LangGraph events — never independently. [Source: `ARCHITECTURE-SPINE.md#AD-2-LangGraph-state-is-the-single-source-of-truth`]

- **AD-4 — `services/` owns DB sync and SSE fan-out:** `services/` is the **only layer permitted to call `graph.astream()` or `graph.update_state()`** — `api/routes/` never calls LangGraph directly. Pipeline nodes are pure functions of `PipelineState` — no side-effects to DB or queues. [Source: `ARCHITECTURE-SPINE.md#AD-4-services-owns-DB-sync-and-SSE-fan-out`]

- **AD-7 — Single SQLite file; no scenes table; AsyncSqliteSaver:** Use `AsyncSqliteSaver` — not the sync `SqliteSaver`. LangGraph checkpoints and SQLModel models share one SQLite file (separate tables). Artifact paths live only in `PipelineState` — no `scenes` or `artifacts` table. [Source: `ARCHITECTURE-SPINE.md#AD-7-Single-SQLite-file-no-scenes-table-AsyncSqliteSaver`]

### Required Data Contracts

#### Run SQLModel (db/models.py)

Match the architecture spine exactly:

```python
# db/models.py
from sqlmodel import Field, SQLModel
from datetime import datetime

class Run(SQLModel, table=True):
    id: str = Field(primary_key=True)   # UUID v4
    scp_id: str                          # "SCP-096"
    status: str                          # running|awaiting_approval|complete|failed
    current_stage: str | None = None
    gate_states: str | None = None       # JSON blob: {"scenario": "approved", ...}
    prompt_variant: str | None = None
    ab_pair_id: str | None = None        # links A/B pair
    error: str | None = None
    extra: str | None = None             # JSON blob for reserved extra: dict
    langfuse_trace_url: str | None = None
    started_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
```

#### API Schemas (Pydantic, used as FastAPI request/response models)

```python
# api/routes/runs.py

class RunCreate(BaseModel):
    scp_id: str
    scp_text: str
    extra: dict | None = None   # reserved, ignored in v1

class RunRead(BaseModel):
    id: str
    scp_id: str
    status: str
    current_stage: str | None
    gate_states: str | None
    prompt_variant: str | None
    ab_pair_id: str | None
    error: str | None
    extra: str | None
    langfuse_trace_url: str | None
    started_at: str
    updated_at: str
```

**Important:** `scp_text` from `RunCreate` is **NOT stored in the `runs` table** — it flows into `PipelineState` via the pipeline. The `POST /runs` handler must hold `scp_text` and pass it to `run_service.start_run()` which will later inject it into the LangGraph initial state. For now, the stub stores `scp_text` on a local variable or in `extra` JSON.

### Conventions

| Concern | Convention |
|---------|------------|
| Naming | `snake_case` modules; `PascalCase` models/TypedDicts; stage literals: `scenario`, `image`, `tts`, `subtitle`, `video` |
| Naming — API routes | `kebab-case` path segments (`/runs/{id}/stages/{stage}/artifact`) |
| IDs | UUID v4 strings everywhere; never auto-increment integers |
| Timestamps | `datetime.utcnow().isoformat()` stored as TEXT in SQLite |
| Error shape | FastAPI `HTTPException` with `detail: str` |
| Config | Pydantic `BaseSettings` in `config.py`; env prefix `YTFLOW_` |
| Alembic | Migrations in `src/yt_flow/db/migrations/` |

### FastAPI 0.138.x Key Notes

As of 2026-07-01, FastAPI 0.138.2 is the latest stable (architecture pins 0.115.x). Notable recent features and changes:

- **`app.frontend()`** (0.138.0): New method to serve static frontend directories, replacing manual `StaticFiles` mount. For Story 3.1, use `app.frontend("/", directory="frontend/dist")`. Not needed in this story.
- **Server-Sent Events** (0.135.0): Built-in SSE support via `EventSourceResponse`. Relevant for Story 2.2 — use FastAPI's native SSE, not custom streaming.
- **`APIRouter` preserves instances** (0.137.0): `router.include_router()` now preserves the original router object instead of cloning routes. This means adding routes after inclusion works. Not critical for this story.
- **Pydantic v2 only** (0.128.0+): No Pydantic v1 compatibility layer. Use `pydantic >= 2.7.0`.
- **Use `"fastapi[standard]"`** install with `uv` to get uvicorn, httpx, and other standard extras.

### SQLModel 0.0.39 Notes

As of 2026-06-25, SQLModel 0.0.39 is the latest stable (architecture says 0.0.38). Both are compatible with Pydantic v2 and SQLAlchemy 2.0.x:

- Uses `SQLModel.metadata.create_all(engine)` for DDL
- UUID support built-in via `sqlmodel.UUID` type or `str` with `Field(sa_type=...)` — but since architecture says UUID v4 as `str`, use `str` directly
- Use `Session(engine)` for sync SQLite; later switch to async if needed

### Project Structure Notes

This repository currently contains planning artifacts only — no application source tree. If Stories 1.1 (config), 1.2 (scaffold + domain types), and 1.4 (LangGraph + AsyncSqliteSaver) have not been implemented before this story, the dev agent must ensure:

- `src/yt_flow/config.py` exists with `YTFLOW_DB_PATH` (default `./yt_flow.db`) and `YTFLOW_WORKSPACE_PATH` (default `./workspace`)
- `src/yt_flow/domain/state.py` exists with `PipelineState`, `SceneState`, `ShotData`, `WordTiming` TypedDicts
- `pyproject.toml` includes FastAPI and SQLModel dependencies

**Expected files for this story:**
- `src/yt_flow/api/__init__.py` (new)
- `src/yt_flow/api/main.py` (new)
- `src/yt_flow/api/routes/__init__.py` (new)
- `src/yt_flow/api/routes/runs.py` (new)
- `src/yt_flow/db/__init__.py` (new)
- `src/yt_flow/db/models.py` (new)
- `src/yt_flow/db/migrations/` (new)
- `src/yt_flow/services/__init__.py` (new)
- `src/yt_flow/services/run_service.py` (new)
- `src/yt_flow/config.py` (update — add DB path if Story 1.1 didn't)
- `data/scps.json` (new or copy from yt.pipe)
- `pyproject.toml` (update — add FastAPI + SQLModel + Alembic deps)
- Tests under `tests/`

### Previous Story Intelligence

No Epic 1 story files have been implemented as application code at story creation time. Git history shows only documentation commits:

```
2390ead chore: init sprint status tracking (24 stories across 4 epics)
4be98ee docs: add epic breakdown and implementation readiness report
6db2416 docs: add UX design specs and HTML mockups
ca2fb1d docs: add architecture design and review docs
b9dc0b0 docs: add PRD for yt.flow
b3feda2 docs: add initial brainstorm & intent document
bd4ec4f chore: init project — .gitignore and CLAUDE.md
```

No application code patterns established yet. The dev agent must create the initial application code following the architecture spine conventions.

### References

- Epic 2 requirements: `_bmad-output/planning-artifacts/epics.md#Epic-2-HTTP-API--Gate-Controlled-Pipeline-Execution`
- Architecture spine: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
- AD-1: Layer dependency direction
- AD-2: LangGraph state single source of truth
- AD-4: services/ owns DB sync and SSE fan-out
- AD-7: Single SQLite file, AsyncSqliteSaver
- PRD FR-24, FR-25, FR-26, FR-31: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
