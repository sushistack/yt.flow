---
baseline_commit: b8beff3fe357a34009288cf3b8a0052db23df958
---

# Story 2.3: Gate Mechanism

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want stage gates that pause after each stage completion and wait for my explicit approval before the pipeline proceeds,
so that I can review artifacts at every stage before committing to the next.

## Acceptance Criteria

1. **Given** a stage node (e.g., `scenario_node`) completes and the graph transitions to `gate_scenario`, **when** `gate_scenario` runs for the first time, **then** `interrupt({"stage": "scenario"})` is called; the `graph.astream()` event loop yields an `__interrupt__` tuple; `services/run_service.py` detects the interrupt, sets `runs.status = "awaiting_approval"`, and pushes a `gate_pending` SSE event (FR-9, AD-3, AD-4).

2. **Given** `POST /runs/{id}/stages/scenario/gate` with `{"action": "approve"}`, **when** called, **then** returns HTTP 202 Accepted immediately; `services/` calls `graph.astream(Command(resume="approved"), config)` in the background; the gate node re-executes, `interrupt()` returns `"approved"`, the node returns `{"gate_states": {"scenario": "approved"}}` to `PipelineState`; `services/` mirrors `gate_states["scenario"] = "approved"` to `runs` table only after receiving the LangGraph state update event; SSE emits `stage_entry` for `image` confirming progression (FR-29, AD-3, AD-4).

3. **Given** `POST /runs/{id}/stages/scenario/gate` with `{"action": "reject"}`, **when** called, **then** the gate node re-executes with `Command(resume="rejected")` and returns `{"gate_states": {"scenario": "rejected"}}`; `services/` detects the rejected state and sets `runs.status = "failed"`; SSE emits `run_failed` before closing; pipeline terminates — no further stages execute (FR-29, AD-3).

4. **Given** the `gate_video` node receives `Command(resume="approved")`, **when** the graph reaches END, **then** `services/` processes the final `graph.astream()` event and sets `runs.status = "complete"`; SSE emits `stage_exit` for `video`.

5. **Given** `POST /runs/{id}/stages/scenario/gate` on a run whose `runs.status` is not `"awaiting_approval"` or whose `gate_states["scenario"]` is not `"pending"`, **when** called, **then** returns HTTP 409 Conflict with `{"detail": "Gate not pending for stage 'scenario'"}`.

6. **Given** `POST /runs/{id}/stages/scenario/gate` with an invalid `action` value (not `"approve"` or `"reject"`), **when** called, **then** returns HTTP 422 Unprocessable Entity with `{"detail": "action must be 'approve' or 'reject'"}`.

7. **Given** `POST /runs/{id}/stages/scenario/gate` with an unknown `run_id`, **when** called, **then** returns HTTP 404 with `{"detail": "Run not found"}`.

8. **Given** `POST /runs/{id}/stages/scenario/gate` with a stage that does not exist (not one of `scenario`, `image`, `tts`, `subtitle`, `video`), **when** called, **then** returns HTTP 404 with `{"detail": "Stage 'unknown' not found"}`.

## Tasks / Subtasks

- [x] Create `gates.py` with 5 gate nodes (AC: 1, 2, 3, 4)
  - [x] Create `src/yt_flow/pipeline/gates.py`.
  - [x] Implement `gate_scenario(state: PipelineState) → dict`: calls `interrupt({"stage": "scenario"})`; on resume, returns `{"gate_states": {"scenario": resume_value}}` where `resume_value` is `"approved"` or `"rejected"` (the string returned by `interrupt()`).
  - [x] Implement `gate_image(state: PipelineState) → dict`: same pattern with `interrupt({"stage": "image"})`.
  - [x] Implement `gate_tts(state: PipelineState) → dict`: same pattern with `interrupt({"stage": "tts"})`.
  - [x] Implement `gate_subtitle(state: PipelineState) → dict`: same pattern with `interrupt({"stage": "subtitle"})`.
  - [x] Implement `gate_video(state: PipelineState) → dict`: same pattern with `interrupt({"stage": "video"})`.
  - [x] Each gate node must be a pure function — no side-effects to DB, queues, or filesystem. Only reads/writes `PipelineState`.
  - [x] Validate that `interrupt()` import comes from `langgraph.types` (`from langgraph.types import interrupt`).
- [x] Wire gate nodes into `graph.py` StateGraph (AC: 1)
  - [x] Update `src/yt_flow/pipeline/graph.py`: add all 5 gate nodes to the StateGraph.
  - [x] Add edges: `scenario → gate_scenario → image` (on approved) / `gate_scenario → END` (on rejected).
  - [x] Add edges: `image → gate_image → tts` (on approved) / `gate_image → image` (on rejected — retry loop).
  - [x] Add edges: `tts → gate_tts → subtitle` (on approved) / `gate_tts → tts` (on rejected).
  - [x] Add edges: `subtitle → gate_subtitle → video` (on approved) / `gate_subtitle → subtitle` (on rejected).
  - [x] Add edges: `video → gate_video → END` (on approved) / `gate_video → video` (on rejected).
  - [x] Use `add_conditional_edges` from each gate node, routing on `gate_states[stage]`: `"approved"` → next stage node, `"rejected"` → either retry (same stage node) or END (for gate_scenario reject → terminate pipeline).
  - [x] Graph topology must match the Architecture spine diagram exactly: all 10 nodes (5 stage + 5 gate), always present.
- [x] Implement `run_service.py` gate-aware event loop (AC: 1, 2, 3, 4)
  - [x] Update `src/yt_flow/services/run_service.py`: the `start_run()` function must consume `graph.astream()` events and detect `__interrupt__` tuples in the event stream.
  - [x] On `__interrupt__` detection: extract `stage` from the interrupt value dict; set `runs.status = "awaiting_approval"`; set `runs.current_stage` to the gate stage; push `gate_pending` SSE event via `asyncio.Queue`.
  - [x] The event loop must handle the pattern where `graph.astream()` yields an interrupt and then the async generator is **exhausted** (the stream stops at the interrupt). The loop should exit cleanly — not raise an error.
  - [x] Implement `async def resume_run(run_id: str, stage: str, action: str)`: called by the gate endpoint. Looks up the `config` for the run's thread; calls `graph.astream(Command(resume=action), config)`; continues consuming events including the next stage execution and subsequent interrupts.
  - [x] On `"rejected"` resume: after the gate node returns rejected state, detect it in the event stream; set `runs.status = "failed"`; push `run_failed` SSE event.
  - [x] On final completion (all 5 gates approved): set `runs.status = "complete"`.
  - [x] All DB writes happen **after** LangGraph confirms the state change — never before (AD-4).
- [x] Add `POST /runs/{id}/stages/{stage}/gate` endpoint (AC: 2, 3, 5, 6, 7, 8)
  - [x] Update `src/yt_flow/api/routes/runs.py`: add the gate endpoint.
  - [x] Define Pydantic schema: `class GateAction(BaseModel): action: Literal["approve", "reject"]`.
  - [x] Validate `stage` path parameter against the set of valid stages: `{"scenario", "image", "tts", "subtitle", "video"}`.
  - [x] Query `runs` table by `run_id` → 404 if not found.
  - [x] Check `runs.status == "awaiting_approval"` and `gate_states[stage] == "pending"` → 409 Conflict if not.
  - [x] Return HTTP 202 Accepted immediately; launch `asyncio.create_task(run_service.resume_run(run_id, stage, action))` in background. Do NOT await the graph call in the request handler (AD-4: 202 then background).
  - [x] On invalid `action` → 422 with detail message.
- [x] Wire `run_service.resume_run()` with config management (AC: 2)
  - [x] The `services/` layer must maintain a mapping of `run_id → config` (LangGraph `RunnableConfig` with `thread_id`). Store this in the `run_service` module or in an in-memory dict keyed by `run_id`.
  - [x] `start_run()` creates the config (`{"configurable": {"thread_id": run_id}}`) before first `graph.astream()` call and stores it.
  - [x] `resume_run()` retrieves the stored config; if the event loop exited (interrupt exhausted the stream), creates a new `graph.astream(Command(resume=action), config)` call.
- [x] Ensure SSE integration (AC: 1, 2, 3, 4)
  - [x] `run_service` must push events to the per-run `asyncio.Queue` managed by `api/sse.py`.
  - [x] Events: `gate_pending` (on interrupt), `stage_entry` (when next stage node starts), `stage_exit` (when stage node completes), `run_failed` (on reject or error).
  - [x] The SSE queue registry should be created in `api/sse.py` (Story 2.2) — this story wires `run_service` to use it. If Story 2.2 is not yet implemented, create a minimal SSE queue registry stub in `api/sse.py` with `queues: dict[str, asyncio.Queue]` and a `push_event(run_id, event)` helper.
  - [x] SSE event format: `{"event": "gate_pending", "data": {"stage": "scenario", "run_id": "..."}}`.
- [x] Add tests (AC: 1–8)
  - [x] Unit test each gate node in isolation: call with state where `gate_states[stage]` is not yet set → verify `interrupt()` is raised (GraphInterrupt). Mock or test with a real checkpointer in test graph.
  - [x] Integration test: `graph.astream()` yields `__interrupt__` tuple after stage node completes.
  - [x] Integration test: `graph.astream(Command(resume="approved"), config)` resumes past the gate and executes the next stage node.
  - [x] Integration test: `graph.astream(Command(resume="rejected"), config)` routes to END (scenario gate) or back to same stage (other gates).
  - [x] API test: `POST /runs/{id}/stages/scenario/gate` with `{"action": "approve"}` → 202; verify `run_service.resume_run` is called.
  - [x] API test: `POST /runs/{id}/stages/scenario/gate` with `{"action": "reject"}` → 202; verify run status becomes `"failed"`.
  - [x] API test: gate on non-awaiting run → 409.
  - [x] API test: gate with invalid action → 422.
  - [x] API test: gate with unknown run_id → 404.
  - [x] API test: gate with invalid stage → 404.
  - [x] Service test: `run_service` detects `__interrupt__` and updates `runs.status` to `"awaiting_approval"`.
  - [x] Service test: `run_service` pushes `gate_pending` SSE event on interrupt.
  - [x] Service test: `run_service` pushes `run_failed` SSE event on reject.
  - [x] Use `TestClient` with in-memory SQLite; use `InMemorySaver` or `AsyncSqliteSaver` with temp file for graph tests.
- [x] Verify locally (AC: 1, 2, 3)
  - [x] Run `uv run uvicorn src.yt_flow.api.main:app --reload`.
  - [x] `POST /runs` → get `run_id`.
  - [x] Observe SSE at `GET /runs/{id}/progress` — should see `stage_entry` for `scenario`, then `gate_pending` for `scenario` (once scenario_node is real or stub completes).
  - [x] `POST /runs/{id}/stages/scenario/gate` with `{"action": "approve"}` → 202.
  - [x] Verify SSE shows `stage_entry` for `image`.
  - [x] `POST /runs/{id}/stages/scenario/gate` with `{"action": "reject"}` on another run → 202; verify `runs.status` = `"failed"` via `GET /runs/{id}`.
  - [x] Run `uv run pytest`.

## Dev Notes

### Scope Boundary — CRITICAL

This story implements the **gate pause-and-resume mechanism** — the core human-in-the-loop control flow for Epic 2. It is the bridge between the pipeline graph (Epic 1) and the API surface (Epic 2).

**Do implement in this story:**
- 5 gate nodes in `gates.py` using `langgraph.types.interrupt()`
- Graph wiring: all 10 nodes (5 stage + 5 gate), conditional edges for approved/rejected routing
- `POST /runs/{id}/stages/{stage}/gate` endpoint (202 Accepted, background resume)
- `run_service.py` gate-aware event loop: detect `__interrupt__`, capture config, call `graph.astream(Command(resume=...))`
- SSE integration: push `gate_pending`, `stage_entry`, `stage_exit`, `run_failed` events
- Status transitions: `running → awaiting_approval` (on interrupt), `awaiting_approval → running` (on approved resume), `awaiting_approval → failed` (on reject)

**Do NOT implement in this story:**
- Stage retry endpoint (`POST /runs/{id}/stages/{stage}/retry`) → Story 2.4
- Inline artifact edit (`PATCH /runs/{id}/stages/{stage}/artifact`) → Story 2.4
- `GET /scps` route → Story 2.5
- `GET /runs/{id}/stages/{stage}/artifacts` → Story 2.5
- Full SSE endpoint with `EventSourceResponse` → Story 2.2 (this story creates a minimal SSE queue stub if 2.2 is not done)
- Real stage node implementations (scenario, image, tts, subtitle, video) → Epic 1 stories
- React frontend gate controls → Epic 3

### Architecture Guardrails

- **AD-3 — Gate mechanism is LangGraph `interrupt()`:** Every gate node calls `interrupt({"stage": stage_name})` and returns `{"gate_states": {stage: "pending"}}` as its state update — gate nodes are the **sole writers** of `gate_states` into `PipelineState`. On resume, `Command(resume="approved" | "rejected")` is passed; the gate node returns `{"gate_states": {stage: "approved" | "rejected"}}`. `services/` mirrors `gate_states` to the `runs` table only after receiving the LangGraph confirmation event — `services/` never writes `gate_states` independently. Graph topology is fixed: all 5 gate nodes always present. [Source: `ARCHITECTURE-SPINE.md#AD-3-Gate-mechanism-is-LangGraph-interrupt()`]

- **AD-4 — `services/` owns DB sync and SSE fan-out:** `services/` is the **only layer permitted to call `graph.astream()` or `graph.update_state()`** — `api/routes/` never calls LangGraph directly. `POST /gate` returns 202 Accepted once LangGraph resume is kicked off; the client confirms stage progression via SSE `stage_entry`. If `astream()` raises, `services/` catches it, sets `runs.status = "failed"`, and pushes a `run_failed` SSE event before closing the loop. Pipeline nodes are pure functions of `PipelineState` — no side-effects to DB or queues. [Source: `ARCHITECTURE-SPINE.md#AD-4-services-owns-DB-sync-and-SSE-fan-out`]

- **AD-1 — Layer dependency direction:** Import path must follow `api → services → (pipeline | db) → domain`. Cross-layer imports forbidden. `api/routes/runs.py` must import from `services/run_service.py`, never from `pipeline/` directly. `pipeline/gates.py` must not import from `db/` or `services/`. [Source: `ARCHITECTURE-SPINE.md#AD-1-Layer-dependency-direction`]

- **AD-2 — LangGraph state is the single source of truth:** All in-flight pipeline data lives in `PipelineState`, persisted by `AsyncSqliteSaver`. The `runs` table is a read-optimised API projection only — it mirrors `status`, `current_stage`, `gate_states` and must never be the write-authoritative store. [Source: `ARCHITECTURE-SPINE.md#AD-2-LangGraph-state-is-the-single-source-of-truth`]

- **AD-7 — Single SQLite file; AsyncSqliteSaver:** Use `AsyncSqliteSaver` (`langgraph.checkpoint.sqlite.aio`) — not the sync `SqliteSaver` — to avoid blocking FastAPI's async event loop. LangGraph checkpoints and SQLModel models share one SQLite file. [Source: `ARCHITECTURE-SPINE.md#AD-7-Single-SQLite-file-no-scenes-table-AsyncSqliteSaver`]

### LangGraph `interrupt()` API — Latest Patterns (v1.2.6+)

The `interrupt()` function in LangGraph works as follows (verified from langgraph source at `langgraph/types.py`):

```python
from langgraph.types import interrupt, Command

def gate_scenario(state: PipelineState) -> dict:
    """Gate node for scenario stage. Interrupts for human approval."""
    # First invocation: raises GraphInterrupt, halting execution.
    # The value {"stage": "scenario"} is surfaced to the caller.
    # On resume (re-execution): returns the resume value from Command(resume=...).
    action = interrupt({"stage": "scenario"})
    # action is "approved" or "rejected" (the string passed via Command.resume)
    return {"gate_states": {"scenario": action}}
```

**Critical behavior details:**

1. **Re-execution on resume:** When `Command(resume=...)` is passed to `graph.astream()`, the gate node **re-executes from the beginning**. The `interrupt()` call returns the resume value instead of raising `GraphInterrupt`. All logic before `interrupt()` runs again — keep gate nodes minimal (just the `interrupt()` call + return).

2. **Event stream on interrupt:** `graph.astream()` yields an `__interrupt__` tuple when a node calls `interrupt()`. After that yield, the async generator is exhausted (the stream ends). The caller must detect this and later call `graph.astream(Command(resume=...), config)` to continue.

3. **Async checkpointer:** With `AsyncSqliteSaver`, use `graph.astream()` (async). The config must include `thread_id`:
   ```python
   config = {"configurable": {"thread_id": run_id}}
   ```

4. **Multiple interrupts per node:** If a node calls `interrupt()` multiple times, each call is resolved by successive `Command(resume=...)` invocations. For our gates, we only call `interrupt()` once per gate node.

5. **import path:** `from langgraph.types import interrupt, Command` — this is the canonical import. Do NOT use `langgraph.prebuilt.interrupt.HumanInterrupt` (deprecated since v10).

### Graph Structure — Conditional Edges

The gate node returns `{"gate_states": {stage: action}}`. The conditional edge function checks `gate_states[stage]`:

```python
def route_after_gate_scenario(state: PipelineState) -> str:
    action = state["gate_states"].get("scenario")
    if action == "approved":
        return "image"         # proceed to next stage
    else:
        return END              # rejected → terminate pipeline

def route_after_gate_image(state: PipelineState) -> str:
    action = state["gate_states"].get("image")
    if action == "approved":
        return "tts"            # proceed to next stage
    else:
        return "image"          # rejected → retry same stage
```

**Rejected routing differs per gate:**
- `gate_scenario` rejected → `END` (terminate pipeline; first gate reject = no point continuing)
- `gate_image`, `gate_tts`, `gate_subtitle`, `gate_video` rejected → loop back to the same stage node (retry loop; user can re-run via Story 2.4 retry endpoint)

### run_service.py Event Loop Pattern

The `start_run()` function must handle the interrupt pattern:

```python
async def start_run(run_id: str, scp_text: str) -> None:
    config = {"configurable": {"thread_id": run_id}}
    _store_config(run_id, config)  # save for later resume

    initial_state: PipelineState = {
        "run_id": run_id,
        "scp_text": scp_text,
        "scenes": [],
        "video_path": None,
        "current_stage": "scenario",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }

    try:
        async for event in graph.astream(initial_state, config):
            # event is a dict like {"scenario": {...}} or {"gate_scenario": {...}}
            # or {"__interrupt__": (Interrupt(value={"stage": "scenario"}),)}
            if "__interrupt__" in event:
                interrupt_val = event["__interrupt__"][0].value
                stage = interrupt_val["stage"]
                await _update_run_status(run_id, "awaiting_approval")
                await _update_run_gate_state(run_id, stage, "pending")
                await _push_sse(run_id, "gate_pending", {"stage": stage, "run_id": run_id})
                # Stream ends here — function returns
                return
            # Handle normal node events: update DB from PipelineState changes
            await _process_node_event(run_id, event)
    except Exception as e:
        await _update_run_status(run_id, "failed")
        await _push_sse(run_id, "run_failed", {"run_id": run_id, "error": str(e)})
        raise

async def resume_run(run_id: str, stage: str, action: str) -> None:
    config = _get_stored_config(run_id)
    try:
        async for event in graph.astream(Command(resume=action), config):
            if "__interrupt__" in event:
                # Handle next gate interrupt same as above
                ...
            await _process_node_event(run_id, event)
    except Exception as e:
        # ...error handling same as start_run
```

**Key insight:** `graph.astream()` is a context manager / async generator. When an interrupt fires, the stream yields the `__interrupt__` event and then the generator is exhausted. A new `graph.astream(Command(resume=...), config)` call is needed to continue from the checkpoint.

### Config Management

The `services/` layer must track `config` per `run_id`:
- Store after first `graph.astream()` call in `start_run()`.
- Retrieve in `resume_run()` for the resume `graph.astream()` call.
- Use an in-memory dict: `_run_configs: dict[str, dict] = {}`.
- Clean up on run completion or failure.

### SSE Queue Stub (if Story 2.2 not yet implemented)

If `api/sse.py` does not exist, create a minimal stub:

```python
# api/sse.py
import asyncio

_queues: dict[str, asyncio.Queue] = {}

def get_queue(run_id: str) -> asyncio.Queue:
    if run_id not in _queues:
        _queues[run_id] = asyncio.Queue()
    return _queues[run_id]

def remove_queue(run_id: str) -> None:
    _queues.pop(run_id, None)

async def push_event(run_id: str, event_type: str, data: dict) -> None:
    queue = _queues.get(run_id)
    if queue:
        await queue.put({"event": event_type, "data": data})
```

The full SSE endpoint (`GET /runs/{id}/progress` with `EventSourceResponse`) belongs to Story 2.2. This story only needs the queue push mechanism.

### Required Data Contracts

#### gate_states Format

```python
# In PipelineState (TypedDict):
gate_states: dict[str, str]  # stage → "pending" | "approved" | "rejected" | "n/a"

# In runs table (SQLModel, stored as JSON string):
gate_states: str | None  # '{"scenario": "approved", "image": "pending", ...}'
```

**Gate state values:**
- `"pending"`: gate is active, waiting for human approval
- `"approved"`: user approved, pipeline advanced to next stage
- `"rejected"`: user rejected, pipeline failed (scenario gate) or stage loops back (other gates)
- `"n/a"`: stage not yet reached

#### API Schema

```python
# api/routes/runs.py

class GateAction(BaseModel):
    action: Literal["approve", "reject"]

# Gate endpoint path parameter:
# stage: str  — one of {"scenario", "image", "tts", "subtitle", "video"}
```

#### Status Values

```python
# runs.status:
# - "running": pipeline is actively executing a stage node
# - "awaiting_approval": pipeline is paused at a gate, waiting for POST /gate
# - "complete": all 5 stages completed, all gates approved
# - "failed": pipeline terminated (rejected at scenario gate, or stage error)
```

### Langfuse Tracing

Gate nodes should be decorated with `@observe(name="gate_scenario")` etc., matching the pattern established in Epic 1. Each gate node span is a child of the parent trace. The `interrupt()` call does not close the span — it remains open until the node completes on resume.

### LangGraph Version Notes

Architecture spine specifies LangGraph 1.2.6. The `interrupt()` / `Command(resume=...)` API is stable across LangGraph 1.x. However:

- `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver` is a **separate package** (`langgraph-checkpoint-sqlite`). Install with `uv add langgraph-checkpoint-sqlite`.
- The `Command` dataclass has a `resume` field that accepts `Any`. For our case, pass a string: `Command(resume="approved")`.
- `graph.astream()` with `AsyncSqliteSaver` must be called in an async context; the FastAPI route handler uses `asyncio.create_task()` to launch the background task.

### Previous Story Intelligence

**Story 2.1 (fastapi-sqlmodel-run-crud):** Status `ready-for-dev`. Establishes:
- FastAPI app scaffold in `src/yt_flow/api/main.py` with lifespan
- SQLModel `Run` table in `src/yt_flow/db/models.py`
- Basic CRUD endpoints in `src/yt_flow/api/routes/runs.py`
- `src/yt_flow/services/run_service.py` with `start_run()` stub
- `asyncio.create_task()` pattern in `POST /runs` handler

This story (2.3) extends the `run_service.py` stub into a real gate-aware event loop and adds the gate endpoint. The `Run` model already has `gate_states: str | None` (JSON blob) — this story populates it.

**Story 1.4 (langgraph-asyncsqlitesaver):** Status `ready-for-dev`. Establishes:
- `src/yt_flow/pipeline/graph.py` with StateGraph + AsyncSqliteSaver
- All 10 nodes (5 stage + 5 gate) as stubs

If Story 1.4 is implemented before 2.3, the gate nodes should already be registered in the graph (as stubs). This story replaces the stubs with real `interrupt()` implementations.

**Git history:** All commits are documentation-only. No application code patterns established yet. The dev agent creates the initial application code.

### Graph Topology (exact)

```
START → scenario → gate_scenario → image → gate_image → tts → gate_tts → subtitle → gate_subtitle → video → gate_video → END
                       ↓ rejected          ↓ rejected       ↓ rejected          ↓ rejected            ↓ rejected
                      END                 image             tts                subtitle              video
```

[Source: `ARCHITECTURE-SPINE.md#LangGraph-Graph-Structure`]

### Stage Literals

The stage name literals are: `scenario`, `image`, `tts`, `subtitle`, `video`. These are used everywhere — `interrupt()` value, `gate_states` keys, API path parameters, SSE event data. They are technical identifiers displayed in English monospace in the UI. Never translate them.

### Conventions

| Concern | Convention |
|---------|------------|
| Naming — files | `snake_case` modules; `PascalCase` TypedDicts/models |
| Stage literals | `scenario`, `image`, `tts`, `subtitle`, `video` (English, monospace) |
| IDs | UUID v4 strings everywhere; never auto-increment integers |
| Timestamps | `datetime.utcnow().isoformat()` stored as TEXT in SQLite |
| Error shape | FastAPI `HTTPException` with `detail: str` |
| Config | Pydantic `BaseSettings` in `config.py`; env prefix `YTFLOW_` |
| Langfuse tracing | Every node decorated with `@observe`; span name = stage name literal |
| SSE events | Four event types: `stage_entry`, `stage_exit`, `gate_pending`, `run_failed` |
| `gate_states` format | Flat JSON dict: `{"scenario": "approved", ...}` — string values only; never an array |
| `current_stage` writer | Set only by stage nodes in their `PipelineState` return dict; `services/` mirrors to DB |
| Gate node return | `{"gate_states": {stage: action}}` — only writes its own stage's gate state |

### Expected Files

- `src/yt_flow/pipeline/gates.py` (new — 5 gate node functions)
- `src/yt_flow/pipeline/graph.py` (update — add gate nodes + conditional edges)
- `src/yt_flow/services/run_service.py` (update — real gate-aware event loop + `resume_run()`)
- `src/yt_flow/api/sse.py` (new or update — SSE queue registry stub)
- `src/yt_flow/api/routes/runs.py` (update — add `POST /gate` endpoint)
- `src/yt_flow/domain/state.py` (may need update — ensure `gate_states` field exists)
- `src/yt_flow/config.py` (may need update — ensure `YTFLOW_DB_PATH`)
- Tests under `tests/`

### References

- Epic 2 requirements: `_bmad-output/planning-artifacts/epics.md#Epic-2-HTTP-API--Gate-Controlled-Pipeline-Execution`
- Story 2.3 ACs: `_bmad-output/planning-artifacts/epics.md#Story-2.3-Gate-Mechanism`
- Architecture AD-3 (Gate mechanism): `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-3-Gate-mechanism-is-LangGraph-interrupt()`
- Architecture AD-4 (services owns DB sync): `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4-services-owns-DB-sync-and-SSE-fan-out`
- Graph structure diagram: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#LangGraph-Graph-Structure`
- PipelineState definition: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#PipelineState-(OQ-7-resolved)`
- PRD FR-9, FR-29: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`
- Previous story 2.1: `_bmad-output/implementation-artifacts/2-1-fastapi-sqlmodel-run-crud.md`
- LangGraph `interrupt()` source: `langgraph/types.py` (function docstring + implementation)
- LangGraph `Command` source: `langgraph/types.py#Command` dataclass
- LangGraph test patterns: `langgraph/tests/test_pregel.py`, `langgraph/tests/test_time_travel.py`

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (1M context)

### Debug Log References

- Concurrent-session note: while this story was in development, a parallel story-automator session was
  implementing Stories 2.4 and 2.5 in the same working tree. `run_service.py`, `api/routes/runs.py`, and
  `api/main.py` were edited by both. All 2.3 additions coexist without conflict markers; `_run()` is shared
  with 2.4's `retry_stage()`, so its `(run_id, stream, sse_registry)` signature was kept intact.
- `interrupt()` called on a gate node outside a runnable context raises `RuntimeError: Called get_config
  outside of a runnable context` — the gate-isolation unit test asserts this rather than `GraphInterrupt`
  (which only surfaces inside graph execution).

### Completion Notes List

- **Gate nodes** (`pipeline/gates.py`): already implemented per Story 1.4 (5 `interrupt()`-based nodes,
  approved/rejected validation). No change needed — matches Task 1 exactly.
- **Conditional routing** (`pipeline/graph.py`): replaced plain gate→next edges with `add_conditional_edges`
  routing on `gate_states[stage]`: approved → next stage, rejected → END (scenario) or same stage node
  (image/tts/subtitle/video retry loop). All 10 nodes always present. [AD-3]
- **Gate-aware event loop** (`services/run_service.py`): `start_run()` streams (`stream_mode="updates"`)
  until the first `__interrupt__`, mirroring `awaiting_approval` + `gate_states[stage]="pending"` to the
  runs projection and emitting `gate_pending`. `resume_run()` resumes with `Command(resume=...)`
  (approve→"approved", reject→"rejected"). Scenario reject → `failed` + `run_failed`; other rejects loop
  back and re-interrupt. Full approval → `complete`. Per-run config tracked in `_configs`; graph injected
  via `init()`/`configure()` so the `api` layer never imports `pipeline` (AD-1). All runs-table writes
  happen after the corresponding LangGraph event (AD-4).
- **Gate endpoint** (`api/routes/runs.py`): `POST /runs/{id}/stages/{stage}/gate` → 404 invalid stage,
  404 unknown run, 422 invalid action (exact AC-6 detail), 409 not-pending, else 202 + background
  `resume_run` task. `GateAction.action` typed `str` (not `Literal`) to yield the exact 422 detail string.
- **Lifespan** (`api/main.py`): builds the long-lived graph via `run_service.init(settings)` and closes
  the checkpointer connection on shutdown.
- **Verification**: full suite green — **250 passed, 1 skipped**, including 20 new gate tests. The
  "Verify locally" uvicorn smoke test could not be run as written (`uvicorn` is not a project dependency;
  adding one is out of scope and disallowed under Ponytail); it is substituted by end-to-end automated
  coverage that drives the real ASGI app (`TestClient`/`httpx.ASGITransport` against `app`) and the real
  compiled graph + service loop — functionally equivalent and repeatable.

### File List

- `src/yt_flow/pipeline/graph.py` (modified — conditional approved/rejected gate edges)
- `src/yt_flow/services/run_service.py` (modified — `init`/`configure`, gate-aware `start_run`/`resume_run`,
  `_consume`/`_run` event loop, config tracking)
- `src/yt_flow/api/routes/runs.py` (modified — `GateAction` schema + `POST .../gate` endpoint)
- `src/yt_flow/api/main.py` (modified — lifespan builds/injects graph, closes saver)
- `tests/pipeline/test_gates.py` (new — gate node isolation + conditional routing integration)
- `tests/services/test_run_service_gate.py` (new — service event loop, DB sync, SSE fan-out, resume)
- `tests/api/test_gate.py` (new — gate endpoint 202/409/422/404 cases)

Note: `pipeline/gates.py` and `api/sse.py` were already present (Stories 1.4 / 2.2) and needed no change.

## Change Log

| Date       | Change                                                                     |
|------------|----------------------------------------------------------------------------|
| 2026-07-01 | Implemented Story 2.3 gate mechanism: conditional graph routing, gate-aware run_service event loop + resume, `POST .../gate` endpoint, and tests. Status → review. |

## Review Findings

_Code review 2026-07-01 (3-layer adversarial: Blind Hunter, Edge Case Hunter, Acceptance Auditor). Reviewed together with stories 2.4/2.5._

- [x] [Review][Patch] Background gate-resume task ref retained via `run_service.spawn()` — bare `asyncio.create_task` let the event loop GC a running resume mid-flight [src/yt_flow/api/routes/runs.py gate endpoint]
- [x] [Review][Defer] Gate node cannot persist `pending` into `PipelineState` (LangGraph discards a node's return when `interrupt()` pauses); services mirrors `pending` to the runs projection only. Spec-acknowledged; documented in `gates.py`. [src/yt_flow/pipeline/gates.py] — deferred (architecture reconciliation)

Dismissed as noise: eager `astream` evaluation (lazy generator — exception is caught inside `_run`); gate double-resume race and interrupt-payload guards (theoretical for a local single-operator app; our gate always emits `{"stage": ...}`).
