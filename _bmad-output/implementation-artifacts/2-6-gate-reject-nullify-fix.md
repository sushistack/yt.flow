---
created: 2026-07-10
story_key: 2-6-gate-reject-nullify-fix
story_id: "2.6"
epic: 2
previous_story: 2-5-data-access-scp-stage-artifacts
depends_on:
  - 2-4-stage-control-retry-inline-edit    # _nullify is defined and used here — this story reuses it
related:
  - 5-14-pipeline-resilience-shot-resume-comfyui-healthcheck  # the resume cache this bug silently defeats
  - 2-3-gate-mechanism                     # graph reject routing (_REJECT_TARGET) this bug lives in
workflow_decision: "Service-layer fix in run_service.resume_run. No graph topology change, no new API surface."
evidence: "Discovered live during iteration-1 investigation (2026-07-09/10): rejecting the image gate through the UI/API path never regenerated images; manual file deletion was required to force real regeneration."
---

# Story 2.6: Gate Reject Must Nullify State Before Re-Entering a Stage

Status: ready-for-dev

## Story

As Jay,
I want rejecting a stage's gate to actually force regeneration,
so that clicking "Reject" behaves the same as clicking "Retry" — both mean "I don't like this output, make a new one" — instead of reject silently replaying the exact same result.

## Context — confirmed bug, two independent causes

Two distinct API paths both "re-run a stage," and only one of them clears state first:

1. `POST /runs/{id}/stages/{stage}/retry` → `run_service.retry_stage()` (Story 2.4) → calls `_nullify(stage, scenes)` (zeroes `image_path`/`audio_path`/etc. for the stage and everything downstream) → `graph.aupdate_state(..., as_node=_RETRY_ENTRY[stage])` → re-invokes the stage node with clean state.
2. `POST /runs/{id}/stages/{stage}/gate {"action": "reject"}` → `run_service.resume_run()` → `graph.astream(Command(resume="rejected"), ...)`. The gate node (`gates.py`) records `gate_states[stage] = "rejected"`, and the graph's conditional edge (`graph.py`) routes rejected straight back into the **same stage node** (`_REJECT_TARGET = {s: s for s in STAGES[1:]}`) — **without calling `_nullify` or resetting anything.** The stage node re-runs against the *exact same* `scenes` state it just produced.

For `image_node` this is catastrophic: `_existing_complete_shot()` (image.py:154) treats disk as ground truth specifically *because* it was written assuming retry always nullifies state first (its own docstring: "retry re-enters with state paths nulled, so disk is the only truth"). Path 2 breaks that assumption — state is NOT nulled, so the shot's sidecar (unchanged prompt) and PNG (unchanged file, from the previous attempt) both still validate, and `_existing_complete_shot` returns the **old path** for every shot. The stage "runs" and produces byte-identical output. Confirmed live on run `d55a265b`: rejecting the image gate left `workspace/{run_id}/images/` completely unchanged; only deleting the files by hand forced real regeneration.

For `tts`/`subtitle`/`video`, which don't have image.py's disk-cache pattern, reject-without-nullify is less visibly broken (they mostly just re-render from state, which — since state also isn't nulled for these — quietly reuses old `audio_path`/`subtitle_path` too, via whatever each node's own idempotence check does). Scope this story to guarantee correctness for **all** stages, not just image, since the fix is one shared code path.

## Acceptance Criteria

1. `resume_run(run_id, stage, action)` calls the same `_nullify(stage, scenes)` + `_reset_gates(gate_states, stage)` sequence `retry_stage` uses, but **only when `action == "reject"`** — approve must not nullify anything (it's moving forward, not redoing).
2. The nullify update is written via `graph.aupdate_state` before `Command(resume="rejected")` is streamed, so the stage node that the graph reject-routes into sees clean state — mirroring `retry_stage`'s ordering. Reuse `_nullify`/`_reset_gates` from their current module location; do not duplicate the logic.
3. `gate_states[stage]` still transiently reflects `"rejected"` for anyone observing the gate decision (SSE, UI) before the stage re-enters and resets it to `"pending"` — same externally-visible sequence `retry_stage` already produces (`_reset_gates` sets the retried stage + downstream to `"pending"`).
4. **Regression proof (image):** a test with a completed image stage (existing valid PNG + matching sidecar on disk) that calls the reject path and asserts the resulting `shot["image_path"]` changes (new file) rather than resolving to the pre-existing one — i.e. `_existing_complete_shot` must NOT short-circuit after a reject.
5. **Approve path unaffected:** existing approve-flow tests (advancing to the next stage with prior artifacts intact) stay green — approve must never touch `scenes`.
6. **`retry_stage` unaffected:** its existing tests stay green; this story does not change `_nullify`/`_reset_gates`'s signatures, only adds a second caller.
7. Live verification: reject the image gate on a real (or mocked-ComfyUI) run with existing valid shot output; confirm new ComfyUI submissions occur for every shot (not zero, as observed pre-fix) and the run completes with fresh files.

## Tasks / Subtasks

- [ ] Task 1: Add the reject-triggers-nullify branch in `resume_run` (AC:1,2,3)
- [ ] Task 2: Unit test — reject path clears `scenes` image_path before re-entry (AC:4)
- [ ] Task 3: Unit test — approve path leaves `scenes` untouched (AC:5)
- [ ] Task 4: Run existing `retry_stage`/`resume_run` suites, confirm green (AC:6)
- [ ] Task 5: Live verification with real or mocked ComfyUI (AC:7)

## Dev Notes

- `_nullify` already handles the cascade correctly per stage index (`i = _STAGES.index(stage)`) — this story adds a caller, not new zeroing logic. Read `run_service.py:618-643` before touching anything.
- `resume_run`'s docstring currently says "carried for traceability only" about the `stage` param — that comment becomes stale once this fix lands (the param now also drives the nullify branch); update it.
- Do not conflate this with 5.23 (ComfyUI crash mitigation) — that story is about the pipeline recovering from a *crash*; this story is about an explicit human "no, redo it" decision producing a real redo. Different triggers, same underlying resume-cache mechanism, but keep the fixes and tests separate.
- **ponytail:** one `if` branch reusing existing functions. No new state field, no new API parameter, no schema change.

### Project Structure Notes

- Modify: `src/yt_flow/services/run_service.py` (`resume_run`)
- Tests: alongside existing `retry_stage`/gate tests (follow current fixture conventions)

### References

- [Source: src/yt_flow/services/run_service.py:552-565] — `resume_run`, the function being fixed
- [Source: src/yt_flow/services/run_service.py:618-643] — `_nullify`/`_reset_gates`, reused unchanged
- [Source: src/yt_flow/pipeline/graph.py:23-27] — `_REJECT_TARGET` routing that re-enters the stage node
- [Source: src/yt_flow/pipeline/nodes/image.py:154-176] — `_existing_complete_shot`, the resume cache this bug defeats
- [Source: _bmad-output/implementation-artifacts/e2e-iteration1-2026-07-09.md] — live discovery context

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
