---
baseline_commit: 8486f5cc5843b324dab1ce3abe9727e3f55368c9
---

# Story 4.1: A/B 실행 생성

Status: done

<!-- Validation: validate-create-story passed 2026-07-01 -->

## Story

As Jay,
I want to trigger a second independent pipeline run as Variant B for A/B comparison,
so that I can compare two prompt variants against the same SCP input.

## Acceptance Criteria

1. **Given** a completed run `{id}`, **When** `POST /runs/{id}/ab` is called, **Then** returns HTTP 201 with a new run `id`; new run has `scp_text` copied from original, `prompt_variant="B"`, `ab_pair_id` pointing to `{id}` (FR-27, AD-6)

2. **Given** the new Variant B run, **When** it executes, **Then** uses the same graph and pipeline as any standard run — no graph-level branching (AD-6)

3. **Given** `POST /runs/{id}/ab` on a run still in `"running"` or `"awaiting_approval"` status, **When** called, **Then** returns HTTP 409 Conflict with `{"detail": "Cannot create A/B run: source run is not complete"}`

4. **Given** `POST /runs/{id}/ab` on a run that already has an A/B pair (i.e., another run already has `ab_pair_id` pointing to `{id}`), **When** called, **Then** returns HTTP 409 Conflict with `{"detail": "A/B pair already exists for this run"}`

5. **Given** `POST /runs/{id}/ab` on a non-existent run `{id}`, **When** called, **Then** returns HTTP 404 with `{"detail": "Run not found"}`

6. **Given** both A and B runs in the `runs` table, **When** `GET /runs` is called, **Then** both appear with `ab_pair_id` linking them (FR-18)

7. **Given** the new Variant B run is created, **When** `GET /runs/{new_id}` is called, **Then** response includes `ab_pair_id` field pointing to the source run

8. **Given** `POST /runs/{id}/ab` succeeds, **When** the 201 response is returned, **Then** `asyncio.create_task(run_service.start_run(new_run_id))` is launched in the background — same as `POST /runs` (AD-4, consistent with story 2.1 AC 6)

## Tasks / Subtasks

- [x] Add `POST /runs/{id}/ab` route handler (AC: 1, 3, 4, 5, 8)
  - [x] Create `ab_run()` function in `src/yt_flow/api/routes/runs.py`.
  - [x] Accept path param `run_id: str`.
  - [x] Query `Run` by `id` → 404 if not found.
  - [x] Validate source run status is `"complete"` → 409 if not (`"running"` or `"awaiting_approval"`).
  - [x] Check no existing A/B pair: query `Run` where `ab_pair_id == run_id` → 409 if found.
  - [x] Read source run's `scp_text` (from LangGraph state via `services/`, not from `runs` table — `runs` table has no `scp_text` column per schema).
  - [x] Generate new UUID v4 for variant run.
  - [x] Insert new `Run` row: `status="running"`, `prompt_variant="B"`, `ab_pair_id={run_id}`, `scp_id` copied from source.
  - [x] Fire `asyncio.create_task(run_service.start_run(new_run_id))` in background.
  - [x] Return HTTP 201 with `RunRead` schema.

- [x] Add `create_ab_run()` to run_service (AC: 2, 8)
  - [x] Add `async def create_ab_run(source_run_id: str) -> str` to `src/yt_flow/services/run_service.py`.
  - [x] Read source run's `PipelineState` via `graph.aget_state(config)` to extract `scp_text`.
  - [x] Create new `Run` DB row with `prompt_variant="B"`, `ab_pair_id=source_run_id`.
  - [x] Call `start_run(new_run_id)` — reuses the existing `graph.astream()` driver.
  - [x] Return new `run_id`.
  - [x] **Critical:** do NOT create a new LangGraph thread — use `start_run()` which creates its own thread via `graph.astream()` (AD-6: independent runs, no graph-level branching).

- [x] Wire AB route into FastAPI router (AC: 1)
  - [x] Ensure `POST /runs/{id}/ab` is registered in the runs router (`src/yt_flow/api/routes/runs.py`).
  - [x] Import `create_ab_run` from `services/`.

- [x] Add response schema fields for A/B metadata (AC: 6, 7)
  - [x] Ensure `RunRead` Pydantic schema includes `ab_pair_id: str | None` and `prompt_variant: str | None`.
  - [x] `GET /runs` response includes `ab_pair_id` so UI can group A/B pairs.
  - [x] `GET /runs/{id}` response includes `ab_pair_id` and `prompt_variant`.

## Dev Notes

### Architecture Compliance (AD-6 — this story's binding invariant)

```
AD-6: A/B testing is two independent runs linked by ab_pair_id.
POST /runs/{id}/ab creates a second independent run with the same
scp_text, prompt_variant="B", and ab_pair_id pointing to the
originating run. Evaluation reads both LangGraph states after both
complete. No graph-level branching.
```

**Key implications for this story:**
- The variant B run is a **normal run** — same graph, same pipeline, same gates.
- The only difference is `prompt_variant="B"` in both the `runs` row and `PipelineState`.
- `ab_pair_id` is the only link between the two runs.
- Do NOT modify `graph.py` or `gates.py` — this story touches only `api/` and `services/`.

### Layer Discipline (AD-1, AD-4)

- `api/routes/runs.py` must NOT import `pipeline/` or `db/` models directly. Route handler calls `services/run_service.py`.
- `services/run_service.py` may call `graph.aget_state()` (for reading source run state) and `graph.astream()` (for launching new run).
- `services/` writes to `runs` table AFTER LangGraph confirms (AD-4), but for run *creation* (before any graph execution), the `Run` row insert happens in `services/` before `astream()` is called — this is consistent with `POST /runs` pattern from story 2.1.

### Data Flow

```
POST /runs/{id}/ab
  → api/routes/runs.py: ab_run(run_id)
    → validate: run exists, status=="complete", no existing AB pair
    → services/run_service.py: create_ab_run(source_run_id)
      → graph.aget_state(source_config) → extract scp_text
      → insert Run(id=new_uuid, scp_id=source.scp_id, prompt_variant="B",
                   ab_pair_id=source_run_id, status="running", ...)
      → asyncio.create_task(start_run(new_run_id))
        → graph.astream() with PipelineState containing scp_text + prompt_variant="B"
    ← return new_run_id
  ← HTTP 201 { id, ab_pair_id, prompt_variant, ... }
```

### scp_text Source

The `runs` table does NOT store `scp_text` — it stores `scp_id`. The full `scp_text` lives only in `PipelineState` (LangGraph checkpoint). To copy it:

- Read source run's LangGraph state: `await graph.aget_state({"configurable": {"thread_id": source_run_id}})` → `state.values["scp_text"]`
- This requires `graph` to be importable in `services/run_service.py` (already the case — `start_run()` already uses `graph.astream()`).
- If `aget_state()` fails or `scp_text` is missing, raise `ValueError` (500 — shouldn't happen for a completed run).

### Files to Create / Modify

| File | Action | What changes |
|------|--------|-------------|
| `src/yt_flow/api/routes/runs.py` | MODIFY | Add `POST /runs/{id}/ab` route handler |
| `src/yt_flow/services/run_service.py` | MODIFY | Add `create_ab_run()` function |
| `src/yt_flow/api/routes/runs.py` (schemas) | MODIFY — if needed | Ensure `RunRead` includes `ab_pair_id`, `prompt_variant` |

### Dependencies on Other Stories

- **2.1 (FastAPI + SQLModel + Run CRUD)** — MUST be complete first. Needs `Run` model with `ab_pair_id`, `prompt_variant` fields; `POST /runs` pattern; `run_service.start_run()`.
- **1.2 (Project Scaffold)** — MUST be complete for directory structure, `pyproject.toml`.
- **1.4 (LangGraph Graph)** — MUST be complete for `graph.aget_state()` and `graph.astream()`.
- **Pipeline nodes (1.5–1.9)** — Needed for Variant B to actually *complete*, but not needed for this story's API to work (the variant run will start and wait at gates like any run).

### Previous Story Intelligence

No previous Epic 4 stories. Patterns to follow from Epic 2 story 2.1:

- **Route handler pattern:** `POST /runs` in `api/routes/runs.py` creates a `RunCreate` schema, inserts via service, fires background task. Follow the same pattern.
- **Service pattern:** `start_run(run_id)` in `services/run_service.py` uses `graph.astream()`. Your `create_ab_run()` calls `start_run()` after creating the DB row — reuse, don't reinvent.
- **Error shape:** FastAPI `HTTPException(status_code=..., detail="...")` — consistent with all other routes.
- **UUID:** `uuid.uuid4().hex` for run IDs (follow whatever pattern 2.1 established).

### Testing Requirements

- **Unit test `create_ab_run()`:** mock `graph.aget_state()` returning `PipelineState` with `scp_text`, verify new `Run` row has `prompt_variant="B"` and `ab_pair_id` set.
- **Route test `POST /runs/{id}/ab`:** 
  - 201 with valid completed run → verify response includes `ab_pair_id`, `prompt_variant`.
  - 409 when source run status is `"running"`.
  - 409 when AB pair already exists.
  - 404 when source run doesn't exist.
- **Integration:** verify new run appears in `GET /runs` with `ab_pair_id`.

### Edge Cases

- **Empty `scp_text`:** Should never happen for a completed run, but handle gracefully (500 with clear error).
- **Source run completed but `scp_text` missing from state:** 500 — LangGraph state corruption, not this story's responsibility.
- **Concurrent A/B requests:** Two simultaneous `POST /runs/{id}/ab` — the "no existing pair" check + insert is not atomic across requests. Acceptable for single-operator local tool. If this bothers you, add a DB-level unique constraint on `ab_pair_id` in a migration.
- **Variant B's `scp_id`:** Copied from source run — they share the same SCP article.

### Project Structure Notes

- Consistent with `src/yt_flow/{api/routes, services}/` layering.
- No new files needed — all changes in existing route and service files.
- Follow `snake_case` naming, `PascalCase` TypedDicts/models.
- Stage literals: not relevant to this story (no stage-level logic).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic 4 Story 4.1]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-6]
- [Source: _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#FR-18, FR-27]
- [Source: _bmad-output/implementation-artifacts/2-1-fastapi-sqlmodel-run-crud.md] (reference pattern)

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m]

### Debug Log References

None — implementation passed on first green run; no HALT conditions triggered.

### Completion Notes List

- `RunRead` already carried `ab_pair_id` and `prompt_variant` (added in story 2.1 schema), so Task 4 required no schema change — only verification.
- `create_ab_run()` recovers `scp_text` from the source run's LangGraph checkpoint (`aget_state`), since the `runs` table stores only `scp_id`. Missing/empty `scp_text` → `ValueError` (→ 500), per Dev Notes edge case.
- Variant B launches through the standard `start_run()` driver (now accepting an optional `prompt_variant`), preserving AD-6: two independent runs, no graph-level branching, linked only by `ab_pair_id`.
- Route is thin for A/B creation and maps `run_service` exceptions to the required 404/409 response shapes; source existence/status/pair validation and insert now live in `create_ab_run()`.
- Concurrent-request A/B pair race was fixed during review with a DB-level unique constraint on `Run.ab_pair_id`, a service-level duplicate check, and `IntegrityError` → 409-style service conflict mapping.
- Variant B cannot be used as the source for another A/B run.
- Tests: `tests/api/test_ab_run.py` — 404/409×3/201 route cases (incl. GET /runs linkage for AC 6) + service unit tests (state copy → prompt_variant="B", duplicate guard, missing scp_text → ValueError). Full suite: 320 passed, 1 skipped; ruff clean.

### File List

- `src/yt_flow/api/routes/runs.py` (MODIFIED — added `POST /runs/{id}/ab` route)
- `src/yt_flow/db/models.py` (MODIFIED — unique `ab_pair_id` to prevent duplicate Variant B rows)
- `src/yt_flow/services/run_service.py` (MODIFIED — added `create_ab_run()`; threaded optional `prompt_variant` through `start_run()`/`_initial_state()`)
- `tests/api/test_ab_run.py` (NEW — route + service tests)

## Review Findings

- [x] [Review][Patch] Created A/B pairs could not be evaluated by Story 4.2 because only Variant B stores `ab_pair_id` — fixed in evaluation pair validation.
- [x] [Review][Patch] Duplicate Variant B rows could be created by concurrent A/B requests — fixed with service-side duplicate check, unique `ab_pair_id`, and `IntegrityError` conflict handling.
- [x] [Review][Patch] Variant B could be used as the source for another A/B run — fixed with a 409 guard in `create_ab_run()`.
- [x] [Review][Patch] A/B route performed story-specific validation directly instead of delegating to `services/` — fixed by moving A/B validation into `run_service.create_ab_run()`.

## Change Log

| Date       | Change                                                              |
|------------|---------------------------------------------------------------------|
| 2026-07-01 | Story 4.1 implemented: A/B Variant B run creation (`POST /runs/{id}/ab`). Status → review. |
| 2026-07-01 | Code review findings fixed; status → done. |
