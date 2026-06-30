# Story 2.2: SSE Infrastructure

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want a Server-Sent Events endpoint that streams stage and gate events in real time,
so that clients can observe pipeline progress without polling.

## Acceptance Criteria

1. Given `GET /runs/{id}/progress` with a valid run_id, when connected, then HTTP 200 with `Content-Type: text/event-stream` and `Cache-Control: no-cache` (FR-32).
2. Given a running pipeline stage completes, when `services/run_service.py` processes the `graph.astream()` event, then SSE stream emits `event: stage_entry` and `event: stage_exit` with `{"stage": "scenario", "run_id": "..."}` data.
3. Given a stage gate triggers `interrupt()`, when `services/` processes it, then SSE stream emits `event: gate_pending` with `{"stage": "scenario", "run_id": "..."}`.
4. Given a pipeline failure, when `services/run_service.py` catches the exception, then SSE emits `event: run_failed` with `{"run_id": "...", "stage": "...", "error": "..."}` before closing; `runs.status` set to `"failed"` (AD-4).
5. Given the SSE client disconnects, when the connection drops, then the per-run `asyncio.Queue` is removed from the registry.

## Tasks / Subtasks

- [ ] Create SSE queue registry (`api/sse.py`) (AC: 5)
  - [ ] Define `EventData` TypedDict: `{"event": str, "data": dict}` where data contains `run_id`, `stage` (for stage events), and `error` (for run_failed).
  - [ ] Implement `SSEQueueRegistry` class with:
    - `_queues: dict[str, asyncio.Queue[EventData]]` — per-run_id queue map.
    - `async def subscribe(run_id: str) -> AsyncGenerator[str, None]`: create queue, yield SSE-formatted events, cleanup on disconnect.
    - `async def publish(run_id: str, event: EventData)`: push to the queue; no-op if no subscriber.
    - `async def unsubscribe(run_id: str)`: remove queue from registry.
    - `def has_subscriber(run_id: str) -> bool`: check if run has active SSE client.
  - [ ] Registry is instantiated as a module-level singleton or attached to `app.state`.
  - [ ] Thread-safe: asyncio.Queue is naturally single-consumer; publish/subscribe use asyncio primitives (no locks needed for dict access in single-threaded async).

- [ ] Create `/runs/{id}/progress` SSE endpoint (`api/routes/progress.py`) (AC: 1, 5)
  - [ ] `GET /runs/{id}/progress` → 404 if run not in `runs` table.
  - [ ] Returns `EventSourceResponse` (FastAPI 0.135.0+ built-in) yielding from `SSEQueueRegistry.subscribe(run_id)`.
  - [ ] Response headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`.
  - [ ] On client disconnect: `subscribe()` generator's `finally` block calls `registry.unsubscribe(run_id)`.
  - [ ] Wire router into `api/main.py`.

- [ ] Add SSE publishing to `services/run_service.py` (AC: 2, 3, 4)
  - [ ] Accept `SSEQueueRegistry` reference in `start_run()` signature (or access via app.state).
  - [ ] After receiving `graph.astream()` event for stage entry → `registry.publish(run_id, EventData(event="stage_entry", data={"stage": stage, "run_id": run_id}))`.
  - [ ] After stage exit → `registry.publish(run_id, EventData(event="stage_exit", data={...}))`.
  - [ ] After gate interrupt detected → `registry.publish(run_id, EventData(event="gate_pending", data={...}))`.
  - [ ] On exception caught → `registry.publish(run_id, EventData(event="run_failed", data={"run_id": run_id, "stage": stage, "error": str(exc)}))` THEN set `runs.status = "failed"` THEN close SSE by calling `registry.publish()` with a terminal sentinel or simply let disconnect handle it.
  - [ ] **Design note — SSE termination on run_failed:** The `run_failed` event is the final event. After publishing it, `registry.unsubscribe(run_id)` is called to close the client side. The `subscribe()` generator catches this and exits cleanly. No explicit `close` event type is needed — client detects stream end.

- [ ] Register SSE queue registry in FastAPI app startup (AC: 1)
  - [ ] In `api/main.py` lifespan: instantiate `SSEQueueRegistry` and attach to `app.state.sse_registry`.
  - [ ] Pass `app.state.sse_registry` to `run_service.start_run()` calls (or inject via dependency).
  - [ ] Ensure `api/sse.py` is importable from `api/routes/progress.py` and `services/run_service.py`.

- [ ] Wire progress router (AC: 1, 5)
  - [ ] `api/main.py`: `app.include_router(progress.router)`.
  - [ ] Verify `/docs` shows `GET /runs/{id}/progress`.

- [ ] Add tests (AC: 1-5)
  - [ ] Test `GET /runs/{id}/progress` returns text/event-stream with correct headers.
  - [ ] Test SSE stream emits `stage_entry` and `stage_exit` when run_service publishes events (use `httpx` async streaming client).
  - [ ] Test SSE stream emits `gate_pending` on interrupt simulation.
  - [ ] Test SSE stream emits `run_failed` on exception.
  - [ ] Test queue cleanup: after client disconnect, `registry.has_subscriber(run_id)` returns False.
  - [ ] Test `404` for unknown run_id on progress endpoint.
  - [ ] Test multiple concurrent SSE clients for different runs (isolated queues).
  - [ ] Test that publishing to a run with no subscriber is a no-op (no error, no queue buildup).
  - [ ] Test that SSE event JSON data is valid and matches `EventData` schema.
  - [ ] Use `TestClient` (httpx-based, async) for SSE streaming tests; `httpx.stream("GET", ...)` reads SSE incrementally.

## Dev Notes

### Scope Boundary

This story is the **SSE plumbing layer** of Epic 2. It establishes the real-time event transport that all downstream stories (gate mechanism 2.3, stage control 2.4, UI Epic 3) depend on for live progress.

**Do NOT implement in this story:**
- Gate mechanism, `interrupt()`, `Command(resume=...)` → Story 2.3
- Stage retry (`POST /runs/{id}/stages/{stage}/retry`) → Story 2.4
- Artifact edit (`PATCH /runs/{id}/stages/{stage}/artifact`) → Story 2.4
- `GET /scps` route → Story 2.5
- `GET /runs/{id}/stages/{stage}/artifacts` → Story 2.5
- Real LangGraph graph wiring or `graph.astream()` driving actual pipeline nodes → Story 2.3
- React frontend or `/app` static mount → Epic 3
- Auth, CORS, or any security middleware → local-only, single operator

**This story must work independently** — it provides the SSE queue infrastructure and progress endpoint. The `run_service` SSE publishing can be tested with synthetic events even before real LangGraph integration in 2.3. Story 2.1 provides the `runs` table and `run_service.start_run()` stub that this story extends.

### Architecture Guardrails

- **AD-4 — `services/` owns DB sync and SSE fan-out:** `services/run_service.py` is the **only module** that publishes SSE events. Pipeline nodes are pure functions — they never touch queues. `api/routes/progress.py` only reads from the queue (via `subscribe()`), never writes. `services/` consumes `graph.astream()` events, then (a) updates `runs` table projection and (b) pushes to the per-run `asyncio.Queue`. [Source: `ARCHITECTURE-SPINE.md#AD-4-services-owns-DB-sync-and-SSE-fan-out`]

- **AD-1 — Layer dependency direction:** Import path must follow `api → services → (pipeline | db) → domain`. `api/sse.py` and `api/routes/progress.py` are in `api/` — they may import from `services/` but `services/` must NOT import from `api/`. The SSE queue registry (`api/sse.py`) is in `api/` because it's the API's infrastructure concern; `services/` accesses it via the `app.state` reference passed at call time, NOT via direct import of `api/` modules. This is the approved pattern: dependency injection through `app.state` preserves the layer direction. [Source: `ARCHITECTURE-SPINE.md#AD-1-Layer-dependency-direction`]

- **SSE event types are fixed:** Four event types only: `stage_entry`, `stage_exit`, `gate_pending`, `run_failed`. No additional event types. Event data is always `{"run_id": "...", "stage": "..."}` for stage events; `{"run_id": "...", "stage": "...", "error": "..."}` for `run_failed`. Stage values are the five stage literals: `scenario`, `image`, `tts`, `subtitle`, `video`. [Source: `ARCHITECTURE-SPINE.md#Consistency-Conventions`]

- **No polling fallback:** SSE is the sole real-time transport. WebSocket is explicitly not required (NFR-12). There is no polling endpoint as fallback — SSE is the only progress channel. [Source: `epics.md#NFR-12`]

### Required Data Contracts

#### EventData (api/sse.py)

```python
from typing import TypedDict, Literal

class EventData(TypedDict):
    event: Literal["stage_entry", "stage_exit", "gate_pending", "run_failed"]
    data: dict  # {"run_id": str, "stage": str} or {"run_id": str, "stage": str, "error": str}
```

#### SSEQueueRegistry (api/sse.py)

```python
import asyncio
from typing import AsyncGenerator

class SSEQueueRegistry:
    def __init__(self):
        self._queues: dict[str, asyncio.Queue[EventData]] = {}

    async def subscribe(self, run_id: str) -> AsyncGenerator[str, None]:
        """Create a queue for run_id, yield SSE-formatted events, cleanup on disconnect."""
        queue: asyncio.Queue[EventData] = asyncio.Queue()
        self._queues[run_id] = queue
        try:
            while True:
                event = await queue.get()
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(run_id)

    async def publish(self, run_id: str, event: EventData) -> None:
        """Push event to queue; no-op if no subscriber."""
        queue = self._queues.get(run_id)
        if queue is not None:
            await queue.put(event)

    def unsubscribe(self, run_id: str) -> None:
        """Remove queue from registry."""
        self._queues.pop(run_id, None)

    def has_subscriber(self, run_id: str) -> bool:
        return run_id in self._queues
```

#### SSE Endpoint Shape (api/routes/progress.py)

```python
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse  # or EventSourceResponse in 0.135.0+
from src.yt_flow.api.sse import SSEQueueRegistry

router = APIRouter(prefix="/runs", tags=["progress"])

# registry injected via app.state or dependency
```

### FastAPI SSE Support (Tech Research)

As of 2026-07-01, FastAPI 0.138.2 is the latest stable:

- **Built-in `EventSourceResponse`** (0.135.0+): FastAPI now has native SSE support. Use `from fastapi.responses import EventSourceResponse`. It handles `text/event-stream` content type and keep-alive headers automatically. This is preferred over manual `StreamingResponse` with custom headers.
- **Async generator pattern:** The endpoint handler returns `EventSourceResponse(sse_registry.subscribe(run_id))` — FastAPI handles the async iteration and disconnect lifecycle.
- **Headers set automatically by `EventSourceResponse`:** `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `Connection: keep-alive`. You may need to add `X-Accel-Buffering: no` manually for nginx/proxy compatibility.
- **Alternative if EventSourceResponse unavailable:** Use `StreamingResponse(generator, media_type="text/event-stream")` with explicit headers.

### Integration with Story 2.1

Story 2.1 establishes:
- `api/main.py` — FastAPI app with lifespan (SQLModel table creation, `scps.json` loading)
- `api/routes/runs.py` — `POST /runs`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/artifact`
- `services/run_service.py` — `start_run(run_id)` stub
- `db/models.py` — `Run` SQLModel table

**This story extends that foundation:**
- Adds `api/sse.py` (new file) — SSE registry
- Adds `api/routes/progress.py` (new file) — SSE endpoint
- Modifies `api/main.py` — register SSE registry in app.state, include progress router
- Modifies `services/run_service.py` — inject SSE publishing calls

If Story 2.1 has NOT been implemented yet, the dev agent must ensure:
- `services/run_service.py` exists with at least a `start_run(run_id)` function signature
- `api/main.py` exists with FastAPI app and lifespan
- `db/models.py` exists with `Run` table (needed for 404 check on run existence)
- If these files don't exist, create minimal stubs so this story can stand alone for testing

### Conventions

| Concern | Convention |
|---------|------------|
| Naming | `snake_case` modules; `PascalCase` classes; stage literals: `scenario`, `image`, `tts`, `subtitle`, `video` |
| Naming — API routes | `kebab-case` path segments (`/runs/{id}/progress`) |
| IDs | UUID v4 strings everywhere |
| Error shape | FastAPI `HTTPException` with `detail: str` |
| SSE event types | `stage_entry`, `stage_exit`, `gate_pending`, `run_failed` — exactly these four |
| SSE data shape | `{"run_id": "...", "stage": "..."}` for stage events; `{"run_id": "...", "stage": "...", "error": "..."}` for `run_failed` |
| Queue lifecycle | Per-run queue created on first subscribe, destroyed on disconnect or run_failed |
| Thread safety | asyncio.Queue is coroutine-safe; dict access in single-threaded async is safe without locks |

### Expected Files

- `src/yt_flow/api/sse.py` (new) — `EventData`, `SSEQueueRegistry`
- `src/yt_flow/api/routes/__init__.py` (may exist from 2.1; create if needed)
- `src/yt_flow/api/routes/progress.py` (new) — `GET /runs/{id}/progress`
- `src/yt_flow/api/main.py` (update) — register SSE registry, include progress router
- `src/yt_flow/services/run_service.py` (update) — SSE publishing calls
- `tests/test_sse.py` (new) — SSE queue registry + endpoint tests

### Previous Story Intelligence

Story 2.1 (FastAPI + SQLModel + Basic Run CRUD) is in `ready-for-dev` status. At story creation time, no application code has been written — the repository contains only planning documents. Key facts:

- **No .py files exist yet** in the workspace. The entire `src/yt_flow/` tree needs to be created from scratch.
- Git history shows only documentation commits (7 commits, all docs/config).
- Story 2.1 expects to create: `api/main.py`, `api/routes/runs.py`, `db/models.py`, `services/run_service.py`, `config.py`.
- If Story 2.1 has been implemented before this story: integrate with existing code. Use the established patterns for error handling, test setup, and import paths.
- If Story 2.1 has NOT been implemented before this story: create minimal stubs (`api/main.py` with FastAPI app, `db/models.py` with `Run` table, `services/run_service.py` with `start_run(run_id)` signature) so SSE infrastructure can be developed and tested independently.

### Git Intelligence

All 7 commits are documentation-only:
```
2390ead chore: init sprint status tracking
4be98ee docs: add epic breakdown and implementation readiness report
6db2416 docs: add UX design specs and HTML mockups
ca2fb1d docs: add architecture design and review docs
b9dc0b0 docs: add PRD for yt.flow
b3feda2 docs: add initial brainstorm & intent document
bd4ec4f chore: init project — .gitignore and CLAUDE.md
```

No code patterns established. The dev agent is creating the first application code. Follow the architecture spine conventions strictly — there are no "existing patterns" to match, only the architecture spec to implement against.

### UX Design Requirements

SSE progress client behavior (for Epic 3 implementation reference — not implemented in this story):
- Hidden `EventSource` on `/runs/{id}/progress` (UX-DR15)
- `stage_entry` / `stage_exit` → update sidebar item state
- `gate_pending` → update gate badge (purple border)
- No toast notifications; all state encoded in sidebar
- The SSE events this story emits must carry enough data for the UI to update sidebar state without additional API calls

### Ponytail Reminder

This project runs Ponytail full mode:
1. Does this need to exist? — Yes, SSE is the spec-mandated realtime transport (FR-32, NFR-12).
2. Stdlib does it? — `asyncio.Queue` is stdlib; use it.
3. Native platform feature? — FastAPI's `EventSourceResponse` (0.135.0+) is the native SSE support.
4. Already-installed dependency? — No additional deps needed; `asyncio` + FastAPI cover everything.
5. Can it be one line? — No; but keep it minimal. The registry is ~30 lines, endpoint ~10 lines.
6. Only then: the minimum code that works.

### References

- Epic 2, Story 2.2: `_bmad-output/planning-artifacts/epics.md#Story-2.2-SSE-인프라`
- Architecture AD-4 (services owns SSE fan-out): `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4-services-owns-DB-sync-and-SSE-fan-out`
- Architecture AD-1 (layer dependency): `ARCHITECTURE-SPINE.md#AD-1-Layer-dependency-direction`
- SSE event conventions: `ARCHITECTURE-SPINE.md#Consistency-Conventions`
- FR-32 (SSE stream): `epics.md#FR-32`
- NFR-12 (SSE, no WebSocket): `epics.md#NFR-12`
- UX-DR15 (SSE progress client): `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#UX-DR15`
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`
- Previous story (2.1): `_bmad-output/implementation-artifacts/2-1-fastapi-sqlmodel-run-crud.md`

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
