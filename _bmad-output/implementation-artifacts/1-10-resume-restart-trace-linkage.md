# Story 1.10: Resume, Restart & Trace Linkage

Status: ready-for-dev

<!-- Completion note: Ultimate context engine analysis completed - comprehensive developer guide created. -->

## Story

As Jay,
I want failed runs to resume from the last successful node and full restart to be explicitly supported,
so that I never reprocess already-completed stages and can start clean when needed.

## Acceptance Criteria

1. Given a run that failed after `scenario_node` and a checkpoint exists in `yt_flow.db`, when the same `run_id` is restarted, execution resumes from `image_node` and `scenario_node` is not re-executed. (FR-7)
2. Given a failed or completed run, when the service triggers a full restart, execution starts from `scenario_node` regardless of existing checkpoint. (FR-8)
3. Given a complete pipeline run, when the Langfuse trace is inspected, all five stage spans (`scenario`, `image`, `tts`, `subtitle`, `video`) appear under one parent trace identified by `run_id`. (FR-12)
4. Given a resumed run, when new spans are created for resumed nodes, the resumed node spans carry the same Langfuse `trace_id` as the original run; no new root trace is created; all spans are visible under one trace tree in Langfuse. (FR-12 trace continuity)

## Tasks / Subtasks

- [ ] Confirm prerequisite graph and node behavior from Stories 1.4-1.9 before implementing this story. (AC: 1, 2, 3, 4)
  - [ ] Verify `src/yt_flow/pipeline/graph.py` compiles the fixed topology: `scenario -> gate_scenario -> image -> gate_image -> tts -> gate_tts -> subtitle -> gate_subtitle -> video -> gate_video`.
  - [ ] Verify the graph uses `AsyncSqliteSaver` from `langgraph.checkpoint.sqlite.aio`, not sync `SqliteSaver`.
  - [ ] Verify every stage node returns `current_stage` and stage outputs through `PipelineState`, with no in-place state mutation.

- [ ] Implement or finalize resume entrypoint in `src/yt_flow/services/run_service.py`. (AC: 1, 4)
  - [ ] Use `run_id` as the LangGraph `thread_id` in the runnable config: `{"configurable": {"thread_id": run_id}}`.
  - [ ] On resume, do not submit a fresh initial `PipelineState`; call `graph.astream(None, config)` or the project-equivalent resume invocation so LangGraph uses the latest checkpoint for that thread.
  - [ ] Preserve `run_id`, `prompt_variant`, `gate_states`, artifact paths, and completed stage outputs from the checkpoint.
  - [ ] Add a focused test that fails after `scenario`, resumes, and proves `scenario_node` was not called a second time.

- [ ] Implement or finalize full restart entrypoint in `src/yt_flow/services/run_service.py`. (AC: 2)
  - [ ] Full restart must be explicit in the service API, e.g. `restart_run(run_id, mode="full")` or a separate `full_restart_run(run_id)`.
  - [ ] Full restart must not accidentally resume from the existing checkpoint.
  - [ ] Choose one consistent strategy and document it in code/tests: either create a fresh LangGraph thread id while keeping the API `run_id`, or deliberately clear/reset the existing thread's checkpoint state before invoking from `scenario`.
  - [ ] If using a fresh internal thread id, persist the mapping required for later API reads and trace links; do not break the invariant that the operator-facing run id remains stable.
  - [ ] Reset stage outputs (`scenes`, `video_path`, per-stage artifact paths, `error`) and `gate_states` to the initial not-yet-approved state before re-running.

- [ ] Implement deterministic trace linkage across initial, resumed, and restarted execution. (AC: 3, 4)
  - [ ] Generate or retrieve one deterministic Langfuse `trace_id` for each operator-facing `run_id`.
  - [ ] Store the trace id where both pipeline and service code can reuse it without adding a new authoritative state source. Prefer `PipelineState` if the field already exists from earlier stories; otherwise add `trace_id: str | None` to `PipelineState` and initialize it from `run_id`.
  - [ ] Ensure resumed nodes attach spans to the existing trace id instead of creating a new root trace.
  - [ ] Ensure tracing failures remain non-fatal: log and continue, per AD-10.

- [ ] Add tests for resume, full restart, and trace continuity. (AC: 1, 2, 3, 4)
  - [ ] Unit-test service resume behavior with spy/stub nodes and an async SQLite checkpointer.
  - [ ] Unit-test full restart re-enters `scenario_node` even when prior checkpoints exist.
  - [ ] Unit-test trace id generation is deterministic for `run_id` and reused on resumed nodes.
  - [ ] Add an integration-style test that runs `scenario -> checkpoint -> forced failure -> resume -> complete` with mock node implementations.

## Dev Notes

### Why this story exists

This story closes Epic 1 by proving the pipeline is operationally recoverable and observable as one coherent run. Earlier stories create config, state, Prompt Hub access, graph topology, and individual nodes. This story wires those capabilities together around failure recovery, explicit clean restart, and Langfuse trace continuity. [Source: `_bmad-output/planning-artifacts/epics.md#Story 1.10: Resume, Restart & Trace Linkage`; `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F1 — Pipeline Core (LangGraph)`; `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F2 — Observability (Langfuse)`]

### Relevant Epic 1 context

- Stories 1.1-1.3 establish Langfuse environment validation, project scaffold/domain types, and Prompt Hub migration.
- Story 1.4 establishes `StateGraph` + `AsyncSqliteSaver` checkpoint persistence.
- Stories 1.5-1.9 implement `scenario`, `image`, `tts`, `subtitle`, and `video` stage nodes with `@observe` spans and error capture.
- Story 1.10 should not rebuild those nodes. It should verify and tighten graph/service behavior around existing nodes. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 1: Project Foundation & Pipeline Core`]

### Required architecture invariants

- Respect dependency direction: `api -> services -> (pipeline | db) -> domain`. `api/routes/` must not call LangGraph directly; `pipeline/` must not import `db/`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1 — Layer dependency direction`]
- `PipelineState` persisted by LangGraph is authoritative for in-flight pipeline data. The `runs` table is a read-optimized projection only. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2 — LangGraph state is the single source of truth`]
- `services/` is the only layer permitted to call `graph.astream()` or `graph.update_state()`. Implement resume/restart orchestration there, not inside route handlers or pipeline nodes. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4 — services/ owns DB sync and SSE fan-out`]
- Use `AsyncSqliteSaver` and a single SQLite file shared by LangGraph checkpoints and SQLModel tables. Do not introduce scenes/artifacts tables. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7 — Single SQLite file; no scenes table; AsyncSqliteSaver`]
- Stage retry later uses `graph.update_state(config, nullified_stage_state, as_node=stage)` and re-invokes from the same thread. Do not let this story's full restart design conflict with that future API behavior. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-9 — Stage retry rewinds via graph.update_state() + re-invoke`]
- Langfuse tracing failures are non-fatal; the pipeline must continue if observability is unavailable. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10 — Operational envelope`]

### Current project state observed during story creation

- Runtime source files are not present yet in the repository scan outside planning/skill artifacts. This story should be implemented after Stories 1.1-1.9 create `src/yt_flow/...`.
- No previous story implementation files were found under `_bmad-output/implementation-artifacts/`; therefore there are no prior Dev Agent Records to reuse.
- Recent commits are documentation/tracking only: PRD, architecture, UX, epics/readiness, and sprint status. No runtime code patterns have been established yet.
- `sprint-status.yaml` already had other Epic 1 stories moved to `ready-for-dev` when this story was created; this story does not assume sequential status completion.

### Expected files to update or create

The exact file set depends on what Stories 1.1-1.9 produce. Keep changes within these architecture-approved paths:

- `src/yt_flow/domain/state.py`
  - Update only if a `trace_id` field is not already present in `PipelineState`.
  - Preserve existing fields: `run_id`, `scp_text`, `scenes`, `video_path`, `current_stage`, `gate_states`, `prompt_variant`, `error`.
- `src/yt_flow/pipeline/graph.py`
  - Confirm graph compilation uses `AsyncSqliteSaver`.
  - Expose a graph factory or accessor usable by `services/run_service.py`.
- `src/yt_flow/services/run_service.py`
  - Primary home for resume, full restart, DB projection sync, and SSE fan-out hooks.
  - This service owns `graph.astream()` calls.
- `src/yt_flow/pipeline/nodes/*.py`
  - Update only as needed to accept/reuse trace context; do not move service orchestration into nodes.
- `src/yt_flow/config.py`
  - Add configuration only if needed for trace URL construction or restart behavior; keep env prefix `YTFLOW_`.
- `tests/`
  - Add async tests for checkpoint resume/restart and trace id continuity.

### Resume design guardrails

- LangGraph persistence is thread-scoped. Use one stable `thread_id` per pipeline run for normal execution and resume; for yt.flow, that should be the operator-facing `run_id` unless the full restart implementation deliberately introduces an internal thread id mapping. [Source: LangGraph Persistence docs: https://docs.langchain.com/oss/python/langgraph/persistence]
- Resume must rely on the checkpoint's latest state. Passing a fresh initial state during resume risks re-running `scenario` and overwriting completed artifacts.
- AC 1 is node-level resume, not scene-level resume. If TTS fails on scene 8 of 20, a later resume restarts the `tts` stage, not scene 8 only. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Non-Functional Requirements`]
- Do not use DB projection fields (`runs.current_stage`, `runs.gate_states`) to decide authoritative resume state. Read LangGraph checkpoint state.

### Full restart design guardrails

- Full restart is not stage retry. It must restart from `scenario` and disregard existing successful checkpoints for that run.
- Make restart mode explicit at the service boundary so an accidental caller cannot silently choose resume behavior.
- Preserve the operator-facing run identity and Langfuse inspectability. A full restart may create a new internal checkpoint thread if needed, but API responses and trace URLs must remain coherent for `run_id`.
- Reset generated artifacts in state. If old files remain in `workspace/{run_id}/`, do not let stale paths survive in `PipelineState`.

### Trace linkage guardrails

- Use a deterministic Langfuse trace id derived from `run_id`; Langfuse documents deterministic trace id generation via `create_trace_id(seed=...)`. [Source: Langfuse trace IDs docs: https://langfuse.com/docs/observability/features/trace-ids-and-distributed-tracing]
- All five stage spans must share one parent trace. Do not let a resumed `image`, `tts`, `subtitle`, or `video` node create a separate root trace.
- If using Langfuse LangChain/LangGraph callbacks, wrap graph execution or pass callback config so the existing trace id is used consistently. Langfuse's LangChain integration documents passing a custom trace id through an enclosing span/callback flow. [Source: Langfuse LangChain integration docs: https://langfuse.com/integrations/frameworks/langchain]
- Trace id must be valid for the current Langfuse Python SDK. Prefer SDK-provided `create_trace_id(seed=run_id)` over homegrown UUID/string manipulation.
- Langfuse SDKs queue/send tracing asynchronously, so tests should flush or inspect mocked calls rather than assume immediate network visibility. [Source: Langfuse observability overview: https://langfuse.com/docs/observability/overview]

### LangGraph API notes from current docs

- Checkpointers persist graph state as checkpoints for thread-scoped continuity and fault tolerance. This is the mechanism behind FR-7. [Source: LangGraph Persistence docs: https://docs.langchain.com/oss/python/langgraph/persistence]
- `update_state` applies values using the specified node's writers; specifying `as_node` is useful when execution history is ambiguous or tests set up fresh state. This matters for future stage retry and for any full restart strategy that rewrites state. [Source: LangGraph time travel docs: https://docs.langchain.com/oss/python/langgraph/use-time-travel]
- The SQLite checkpoint package provides both sync and async support via `aiosqlite`; this project requires async to avoid blocking FastAPI's event loop. [Source: `langgraph-checkpoint-sqlite` PyPI: https://pypi.org/project/langgraph-checkpoint-sqlite/]

### Testing requirements

- Use `pytest` and async tests consistent with the dependency stack established in earlier stories.
- Prefer stub node functions over real DeepSeek, ComfyUI, Qwen TTS, forced alignment, or FFmpeg. This story tests orchestration semantics, not media generation.
- Use a temporary SQLite database path per test to avoid cross-test checkpoint contamination.
- Spy counters should prove:
  - Initial run calls `scenario` once before forced failure.
  - Resume calls `image` next and does not call `scenario` again.
  - Full restart calls `scenario` again even with prior checkpoint data.
- Trace tests should prove the same deterministic trace id is used for initial and resumed spans. Mock Langfuse client/callbacks instead of depending on the homelab instance.
- If prior stories added API routes, add route/service tests only through `api -> services`; do not test route handlers by patching pipeline internals directly.

### Out of scope

- Implementing HTTP restart/retry endpoints from Epic 2 unless they already exist and only need to call this service behavior.
- Scene-level resume.
- A/B evaluation or comparison trace scoring.
- UI changes.
- Cleanup/retention of old artifact files beyond ensuring stale paths do not remain in restarted `PipelineState`.

## Project Structure Notes

- Expected code root: `src/yt_flow/`.
- Expected pipeline modules: `src/yt_flow/pipeline/graph.py`, `src/yt_flow/pipeline/gates.py`, `src/yt_flow/pipeline/nodes/{scenario,image,tts,subtitle,video}.py`.
- Expected service module: `src/yt_flow/services/run_service.py`.
- Expected state module: `src/yt_flow/domain/state.py`.
- Expected runtime workspace: configurable `YTFLOW_WORKSPACE_PATH`, default `./workspace`.
- Expected DB path: configurable `YTFLOW_DB_PATH`, default/project convention `yt_flow.db`.

## References

- `_bmad-output/planning-artifacts/epics.md#Story 1.10: Resume, Restart & Trace Linkage`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F1 — Pipeline Core (LangGraph)`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F2 — Observability (Langfuse)`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1 — Layer dependency direction`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2 — LangGraph state is the single source of truth`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4 — services/ owns DB sync and SSE fan-out`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7 — Single SQLite file; no scenes table; AsyncSqliteSaver`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-9 — Stage retry rewinds via graph.update_state() + re-invoke`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10 — Operational envelope`
- LangGraph Persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph Time Travel / `update_state`: https://docs.langchain.com/oss/python/langgraph/use-time-travel
- LangGraph SQLite checkpoint package: https://pypi.org/project/langgraph-checkpoint-sqlite/
- Langfuse Trace IDs & Distributed Tracing: https://langfuse.com/docs/observability/features/trace-ids-and-distributed-tracing
- Langfuse LangChain integration: https://langfuse.com/integrations/frameworks/langchain
- Langfuse observability overview: https://langfuse.com/docs/observability/overview

## Dev Agent Record

### Agent Model Used

TBD by dev agent

### Debug Log References

### Completion Notes List

### File List
