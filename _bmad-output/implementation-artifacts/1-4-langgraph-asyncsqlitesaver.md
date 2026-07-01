---
baseline_commit: 078cbecf4b2888ded4f27a12c23ab8705d5b95f1
---

# Story 1.4: LangGraph Graph + AsyncSqliteSaver

Status: done

<!-- Completion note: Ultimate context engine analysis completed - comprehensive developer guide created. -->

## Story

As Jay,
I want the LangGraph StateGraph compiled with AsyncSqliteSaver and stub nodes in place,
so that checkpoint persistence and the full graph topology are confirmed before real node logic is written.

## Acceptance Criteria

1. Given `YTFLOW_DB_PATH` points to `yt_flow.db`, when `graph.py` initializes `AsyncSqliteSaver` and compiles `StateGraph`, then no exception is raised and `yt_flow.db` is created on disk.
2. Given the Architecture graph structure (`scenario -> gate_scenario -> image -> gate_image -> tts -> gate_tts -> subtitle -> gate_subtitle -> video -> gate_video`), when `graph.get_graph().nodes` is inspected, then all 10 nodes are present in correct topological order.
3. Given a stub run with minimal `PipelineState`, when one stub node completes, then `AsyncSqliteSaver.aget_tuple(config)` returns a non-None checkpoint. (FR-36)

## Tasks / Subtasks

- [x] Verify prerequisites from earlier stories before implementation.
  - [x] Confirm Story 1.2 scaffold exists: `pyproject.toml`, `src/yt_flow/{domain,pipeline/nodes,services,db,api/routes}/`, and `src/yt_flow/domain/state.py`.
  - [x] Confirm Story 1.3 Prompt Hub migration foundation exists or explicitly defer prompt use; this story must not hardcode real stage prompts.
  - [x] If prerequisites are missing, create only the minimal files needed for this story while preserving the architecture paths.
- [x] Add or update dependency pins. (AC: 1, 3)
  - [x] Use Python 3.12.
  - [x] Include `langgraph==1.2.6` or compatible `1.2.x` if the project already pins patch ranges.
  - [x] Include `langgraph-checkpoint-sqlite==3.1.0` or compatible current `3.x`.
  - [x] Include `aiosqlite`, required for async SQLite checkpointing.
  - [x] Keep FastAPI/SQLModel/Langfuse versions aligned with the architecture spine if touching `pyproject.toml`.
- [x] Implement graph construction in `src/yt_flow/pipeline/graph.py`. (AC: 1, 2, 3)
  - [x] Build a `StateGraph(PipelineState)`.
  - [x] Add stage nodes named exactly `scenario`, `image`, `tts`, `subtitle`, `video`.
  - [x] Add gate nodes named exactly `gate_scenario`, `gate_image`, `gate_tts`, `gate_subtitle`, `gate_video`.
  - [x] Wire edges in the fixed architecture order.
  - [x] Compile with an `AsyncSqliteSaver` checkpointer.
  - [x] Expose a small factory API that service code can reuse later, such as `async def build_graph(settings: Settings) -> tuple[CompiledStateGraph, AsyncSqliteSaver]`.
- [x] Implement gate stubs in `src/yt_flow/pipeline/gates.py`. (AC: 2)
  - [x] Gate nodes must be separate from stage nodes.
  - [x] Use LangGraph `interrupt({"stage": stage_name})` in gate nodes.
  - [x] On resume, accept only `"approved"` or `"rejected"` and return a `gate_states` update for that stage.
  - [x] Do not write to DB, queues, or service-level state from gate nodes.
- [x] Implement stage stub nodes without real external calls. (AC: 2, 3)
  - [x] Each stub stage returns a partial `PipelineState` update with `current_stage` set to the stage literal.
  - [x] Preserve existing state fields; do not mutate input state in place.
  - [x] Do not call DeepSeek, ComfyUI, Qwen, FFmpeg, Langfuse Prompt Hub, or API/DB services in this story.
- [x] Add graph/checkpoint tests. (AC: 1, 2, 3)
  - [x] Test DB file creation with a temporary `YTFLOW_DB_PATH`.
  - [x] Test node names and topology via the compiled graph inspection API.
  - [x] Test a checkpoint is persisted after at least one stage execution using `{"configurable": {"thread_id": run_id}}`.
  - [x] Test `aget_tuple(config)` returns a checkpoint for the same `thread_id`.
  - [x] If using gate interrupts in tests, either stop before the first gate or assert interrupt behavior explicitly with a checkpointer.

## Dev Notes

### Current Repository State

- At story creation time, the repository did not expose committed `src/yt_flow` implementation files in `find . -maxdepth 4`; treat this as mostly NEW-file work unless local implementation appears before dev starts.
- `sprint-status.yaml` changed during this story-context run as nearby Epic 1 stories were also contexted. Before implementation, verify current statuses for Stories 1.1-1.3. Treat Story 1.3 as an implementation dependency for later real prompt use, not for stub graph construction.
- Recent commits are planning-only: PRD, architecture, UX, epics, readiness report, and sprint tracking. There is no established code pattern yet beyond the architecture spine.

### Source Documents Loaded

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md`
- No `project-context.md` files were found.

### Architecture Guardrails

- Follow AD-1 dependency direction: `api -> services -> (pipeline | db) -> domain`. For this story, `pipeline/graph.py` and `pipeline/gates.py` may import `domain`, but must not import `db`, `api`, or `services`. [Source: ARCHITECTURE-SPINE.md#AD-1]
- `PipelineState` is the authoritative in-flight state, persisted by LangGraph `AsyncSqliteSaver`; the future `runs` table is only an API projection. Do not add `scenes` or `artifacts` tables. [Source: ARCHITECTURE-SPINE.md#AD-2, #AD-7]
- Use `AsyncSqliteSaver` from `langgraph.checkpoint.sqlite.aio`, not sync `SqliteSaver`. The sync saver is specifically prohibited because it can block FastAPI's async event loop. [Source: ARCHITECTURE-SPINE.md#AD-7]
- LangGraph checkpoints and SQLModel tables must share one SQLite file: `YTFLOW_DB_PATH`, defaulting to `yt_flow.db`. Use separate tables inside the same file, not separate DB files. [Source: ARCHITECTURE-SPINE.md#AD-7]
- Gate nodes belong in `src/yt_flow/pipeline/gates.py` and are separate StateGraph nodes. They call `interrupt({"stage": stage_name})`; stage nodes do not pause themselves. [Source: ARCHITECTURE-SPINE.md#AD-3, #LangGraph-Graph-Structure]
- `gate_states` must remain a flat JSON-compatible dict such as `{"scenario": "pending"}` with string values only. Never use arrays or nested objects for gate status. [Source: ARCHITECTURE-SPINE.md#Consistency-Conventions]
- Pipeline nodes are pure functions of `PipelineState`; no DB writes, no SSE queue writes, and no filesystem artifacts in stub nodes for this story. [Source: ARCHITECTURE-SPINE.md#AD-4]
- `current_stage` is set only by stage nodes in their returned `PipelineState` update. Services will mirror it later; services must not be introduced here. [Source: ARCHITECTURE-SPINE.md#AD-4]

### Required File Structure

Expected files for this story:

```text
src/yt_flow/
  config.py
  domain/
    state.py
  pipeline/
    graph.py
    gates.py
    nodes/
      __init__.py
tests/
  pipeline/
    test_graph.py
```

Use these names exactly:

- Stage literals: `scenario`, `image`, `tts`, `subtitle`, `video`
- Gate node names: `gate_scenario`, `gate_image`, `gate_tts`, `gate_subtitle`, `gate_video`
- Config env prefix: `YTFLOW_`
- DB env var: `YTFLOW_DB_PATH`
- Run/thread IDs: UUID v4 strings; never auto-increment integers

### PipelineState Contract

If `src/yt_flow/domain/state.py` does not already exist from Story 1.2, create the minimal full contract from the architecture spine:

```python
class WordTiming(TypedDict):
    word: str
    start_sec: float
    end_sec: float

class ShotData(TypedDict):
    shot_id: str
    sentence_indices: list[int]
    image_prompt: str
    negative_prompt: str
    camera_angle: str | None
    camera_movement: str | None
    image_path: str | None

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

Do not add artifact paths outside `PipelineState`. Future artifact endpoints read LangGraph state, not the DB. [Source: ARCHITECTURE-SPINE.md#PipelineState, #AD-7]

### Graph Topology

Build this fixed topology:

```text
START
  -> scenario
  -> gate_scenario
  -> image
  -> gate_image
  -> tts
  -> gate_tts
  -> subtitle
  -> gate_subtitle
  -> video
  -> gate_video
  -> END
```

The architecture diagram also describes rejected gates looping back to the same stage for later Epic 2 retry/gate behavior. For this story's stub graph, preserve the node names and extension point, but do not implement API retry semantics. If conditional edges are implemented now, rejected should not silently continue to the next stage. [Source: ARCHITECTURE-SPINE.md#LangGraph-Graph-Structure]

### AsyncSqliteSaver Implementation Notes

- Use an async context manager or explicit lifecycle that keeps the SQLite connection alive for the compiled graph while it is being used.
- Call `await checkpointer.setup()` before the first graph invocation so checkpoint tables exist.
- Use LangGraph config with `thread_id`:

```python
config = {"configurable": {"thread_id": run_id}}
```

- For checkpoint assertions, call:

```python
checkpoint = await checkpointer.aget_tuple(config)
assert checkpoint is not None
```

- Do not use `":memory:"` for the AC that proves `yt_flow.db` is created. Use a temp file path in tests.
- Consider setting `LANGGRAPH_STRICT_MSGPACK=true` in tests or documenting it for runtime. Current `langgraph-checkpoint-sqlite` package guidance says strict msgpack or an explicit allow-list restricts checkpoint deserialization if the DB is compromised.

### Latest Technical Context

- `langgraph-checkpoint-sqlite` latest release found during story creation: `3.1.0`, released May 12, 2026, requires Python `>=3.10`, and provides sync and async SQLite checkpoint savers via `aiosqlite`. [Source: PyPI `langgraph-checkpoint-sqlite`, checked 2026-07-01]
- LangGraph persistence docs describe checkpointers as thread-scoped graph-state persistence for human-in-the-loop, time travel, fault tolerance, and continuity. They are accessed by passing `thread_id` in graph config. [Source: LangChain Docs, Persistence, checked 2026-07-01]
- LangGraph interrupt docs state that interrupts pause graph execution and save graph state through the persistence layer until resumed. Therefore gate behavior must be tested with a real checkpointer, not only in-memory function calls. [Source: LangChain Docs, Interrupts, checked 2026-07-01]
- Official reference notes `AsyncSqliteSaver` is intended for async environments and requires `aiosqlite`; SQLite is appropriate here because the project is local-only and architecture explicitly chooses a single SQLite file. [Source: LangChain Reference, checkpoints, checked 2026-07-01]

### Testing Guidance

Use `pytest` with async support. Suggested focused tests:

1. `test_build_graph_creates_sqlite_file`
   - Set `YTFLOW_DB_PATH` to `tmp_path / "yt_flow.db"`.
   - Build graph and run setup.
   - Assert DB file exists.
2. `test_graph_contains_expected_nodes`
   - Inspect `graph.get_graph().nodes`.
   - Assert the 10 required node names exist.
3. `test_stub_stage_persists_checkpoint`
   - Invoke or stream the graph with a minimal `PipelineState` and a UUID `thread_id`.
   - Stop before or at the first interrupt if needed.
   - Assert `await checkpointer.aget_tuple(config)` is non-None.
4. `test_stage_nodes_return_current_stage_without_mutating_input`
   - Call stub node functions directly if exported.
   - Assert returned update sets `current_stage`.

Minimal input state for tests:

```python
state = {
    "run_id": run_id,
    "scp_text": "SCP test text",
    "scenes": [],
    "video_path": None,
    "current_stage": "",
    "gate_states": {},
    "prompt_variant": None,
    "error": None,
}
```

### Out of Scope

- Real scenario generation, prompt rendering, or Prompt Hub fetches. Story 1.5 owns `scenario_node`; Story 1.3 owns Prompt Hub migration.
- ComfyUI, Qwen TTS, forced alignment, FFmpeg, artifact file writing, and workspace folder creation.
- FastAPI routes, `run_service`, DB projection table writes, SSE queues, gate API endpoints, retry API, artifact PATCH API.
- Full resume/restart semantics across failed/completed runs. Story 1.10 owns explicit resume/restart verification.
- Langfuse tracing implementation for real nodes. Later node stories own span details, though stubs should not block future `@observe` decoration.

## Previous Story Intelligence

- No previous story implementation files were present under `_bmad-output/implementation-artifacts` at creation time.
- Do not assume Prompt Hub migration exists from status alone. Verify the working tree before using Prompt Hub output; this story can build the stub graph without real prompt access.

## Git Intelligence Summary

- Last five commits are documentation and planning only:
  - `2390ead` sprint status tracking
  - `4be98ee` epic breakdown and readiness report
  - `6db2416` UX design specs and HTML mockups
  - `ca2fb1d` architecture design and review docs
  - `b9dc0b0` PRD
- There is no committed implementation style to preserve yet. Use architecture naming and paths as the source of truth.

## References

- `_bmad-output/planning-artifacts/epics.md#Story-1.4-LangGraph-graph-AsyncSqliteSaver`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1-Layer-dependency-direction`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2-LangGraph-state-is-the-single-source-of-truth`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-3-Gate-mechanism-is-LangGraph-interrupt`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7-Single-SQLite-file-no-scenes-table-AsyncSqliteSaver`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F1-Pipeline-Core-LangGraph`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F6-Data-Job-Management`
- LangChain Docs: https://docs.langchain.com/oss/python/langgraph/persistence
- LangChain Docs: https://docs.langchain.com/oss/python/langgraph/interrupts
- PyPI: https://pypi.org/project/langgraph-checkpoint-sqlite/

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (BMAD dev-story workflow)

### Debug Log References

- Prerequisite check: Story 1.2 scaffold + `domain/state.py` and Story 1.3 Prompt Hub files were restored/present before dev; deps (`langgraph==1.2.7`, `langgraph-checkpoint-sqlite==3.1.0`) already pinned in `pyproject.toml`. Added `aiosqlite>=0.20` as an explicit direct dependency since `graph.py` imports it directly.
- RED→GREEN: initial `test_gate_rejects_invalid_decision` called a gate node directly; `interrupt()` raises `RuntimeError` (get_config outside runnable context), not the validation path. Rewrote the test to drive rejection through the graph via `Command(resume=...)`, which correctly surfaces the gate's `ValueError`.
- `ruff` flagged an unused `gates` import after that rewrite; removed it. Final: 33 passed, ruff clean.

### Implementation Plan

- `config.py`: added `db_path: str = "yt_flow.db"` (maps to `YTFLOW_DB_PATH` via `YTFLOW_` prefix). [AD-7]
- `pipeline/nodes/__init__.py`: five pure stub stage nodes built from a `_stub(stage)` factory; each returns `{"current_stage": stage}` without mutating input. `STAGE_NODES` map + `STAGES` tuple exported. [AD-4]
- `pipeline/gates.py`: five gate nodes built from a `_gate(stage)` factory; each calls `interrupt({"stage": stage})`, validates the resume decision against `("approved","rejected")`, and returns a manually-merged flat `gate_states` update. No DB/queue/service writes. [AD-3]
- `pipeline/graph.py`: `build_state_graph()` interleaves stage+gate nodes in the fixed order and wires START→…→END; `build_graph(settings)` opens an `aiosqlite` connection, constructs `AsyncSqliteSaver`, runs `await saver.setup()`, compiles, and returns `(graph, saver)` with caller-owned connection lifetime. Imports `domain` + sibling `pipeline` only (never db/api/services). [AD-1, AD-2, AD-7]

### Completion Notes List

- AC1 satisfied: `build_graph` initializes `AsyncSqliteSaver` and compiles the `StateGraph` with no exception; `test_build_graph_creates_sqlite_file` proves `yt_flow.db` is created on disk (temp path, not `:memory:`); default `db_path` verified as `yt_flow.db`.
- AC2 satisfied: all 10 nodes (`scenario`, `gate_scenario`, `image`, `gate_image`, `tts`, `gate_tts`, `subtitle`, `gate_subtitle`, `video`, `gate_video`) present, and edge order asserted by `test_graph_edges_follow_fixed_topology`.
- AC3 (FR-36) satisfied: after the first stub stage runs and the graph pauses at `gate_scenario`, `await saver.aget_tuple(config)` returns a non-None checkpoint whose `current_stage == "scenario"`.
- Gate resume/reject behavior covered: `approved` records into `gate_states`; invalid resume value raises `ValueError`.
- Stub purity covered: stage nodes return only `{"current_stage": ...}` and do not mutate input state.
- Out-of-scope items (real node logic, Prompt Hub fetches, external services, API/DB/SSE, full resume/restart, Langfuse spans) intentionally not implemented per story.
- Test infra: added `asyncio_mode = "auto"` to `[tool.pytest.ini_options]` for async tests. Full suite: 33 passed; `ruff check src tests` clean.

### File List

- `src/yt_flow/config.py` (modified — added `db_path`)
- `src/yt_flow/pipeline/nodes/__init__.py` (modified — stage stub nodes)
- `src/yt_flow/pipeline/gates.py` (new — gate interrupt nodes)
- `src/yt_flow/pipeline/graph.py` (new — `build_state_graph` / `build_graph`)
- `pyproject.toml` (modified — added `aiosqlite>=0.20` dep, `asyncio_mode = "auto"`)
- `tests/pipeline/__init__.py` (new)
- `tests/pipeline/test_graph.py` (new — AC1/AC2/AC3 + gate resume/reject + stub purity)

### Change Log

- 2026-07-01: Implemented LangGraph stub graph + AsyncSqliteSaver checkpointing (Story 1.4). Added `db_path` config, stage/gate stub nodes, `build_graph` factory, and graph/checkpoint tests. Status → review.
- 2026-07-01: Code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor). 1 patch applied, 2 deferred, remainder dismissed. Status → done.

## Review Findings

Code review 2026-07-01 (3 adversarial layers). Patches applied and verified (`uv run pytest -q` → 34 passed).

- [x] [Review][Patch] `build_graph` leaked the aiosqlite connection when `saver.setup()` or `.compile()` raised (bad db_path, locked/read-only file, disk full) [src/yt_flow/pipeline/graph.py:48] — fixed: connection is now closed on any failure via `try/except BaseException: await conn.close(); raise`.
- [x] [Review][Defer] AD-3 asks each gate node to write `{"gate_states": {stage: "pending"}}` on interrupt entry, but LangGraph discards a node's return when `interrupt()` pauses (node re-runs from the top on resume), so `pending` is never observable — empirically verified: paused `gate_states == {}`. Making `pending` observable needs a pre-gate writer (e.g. the stage node), which conflicts with AD-3's "gate is the sole writer" rule [src/yt_flow/pipeline/gates.py:17] — deferred: architecture reconciliation for the story that first consumes `gate_states`. No consumer exists in this stub. Marked with a `ponytail:` comment.
- [x] [Review][Defer] `gate_states` is a plain dict with no LangGraph reducer; if two gates ever run concurrently (future parallel topology / `Send`), last-write-wins silently drops a decision [src/yt_flow/pipeline/gates.py:24] — deferred: current topology is strictly sequential, so no failure today. Add an `Annotated[..., merge]` reducer when parallel gates are introduced.
- Dismissed as noise: `build_graph` caller-owned close (contract documented, tests close correctly); `gate_states` KeyError on missing key (`PipelineState` always includes it); unhashable resume value (handled — falls into ValueError); gate no-mutation test gap (gate exercised via graph tests).
