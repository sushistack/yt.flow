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
baseline_commit: 82b169d8bda964c853c5c48eedb23edcac728beb
---

# Story 2.6: Gate Reject Must Nullify State Before Re-Entering a Stage

Status: done

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

- [x] Task 1: Add the reject-triggers-nullify branch in `resume_run` (AC:1,2,3)
- [x] Task 2: Unit test — reject path clears `scenes` image_path before re-entry (AC:4)
- [x] Task 3: Unit test — approve path leaves `scenes` untouched (AC:5)
- [x] Task 4: Run existing `retry_stage`/`resume_run` suites, confirm green (AC:6)
- [x] Task 5: Live verification with real or mocked ComfyUI (AC:7)

### Review Findings

- [x] [Review][Patch] AC1 scope overreach — reject branch nullifies even when `stage == "scenario"`, whose reject routes to END (terminate, no re-entry); wipes the rejected draft's `scenes` for no functional benefit and breaks `GET /runs/{id}/stages/scenario/artifacts` for that run [src/yt_flow/services/run_service.py:655] — fixed: guarded with `stage != _STAGES[0]`
- [x] [Review][Patch] `_delete_image_artifacts` has no error handling — any `OSError` beyond missing-file propagates out of the reject/retry background task uncaught, leaving the run stuck at `status="running"` forever with no surfaced error; also bare `scene["scene_num"]` subscript is inconsistent with the defensive `.get("shots", [])` beside it [src/yt_flow/services/run_service.py:720] — fixed: per-shot try/except OSError+KeyError, logs and continues
- [x] [Review][Patch] `retry_stage`'s new `_delete_image_artifacts` call site has no direct test — every new test drives the fix through `resume_run`'s reject path only [src/yt_flow/services/run_service.py:793] — fixed: added `test_retry_image_stage_resubmits_to_comfyui_instead_of_reusing_disk_cache`
- [x] [Review][Patch] `resume_run`'s docstring doesn't mention the `_delete_image_artifacts` disk-deletion side effect for the image stage [src/yt_flow/services/run_service.py:639] — fixed: docstring updated
- [x] [Review][Patch] AC4's e2e regression test never asserts `shot["image_path"]` actually changes to a new value (only submission count + same filenames) — strengthen via a direct checkpoint read [tests/api/test_e2e_stub_run.py] — fixed: added checkpoint-read assertion that every shot's `image_path` is repopulated and points to an existing file
- [x] [Review][Defer] `retry_stage(stage="scenario")` never cleans up downstream image artifacts (only `stage=="image"` triggers `_delete_image_artifacts`) — retrying scenario on a completed run can resurrect stale images for any shot whose regenerated prompt happens to be byte-identical [src/yt_flow/services/run_service.py:763] — deferred, pre-existing gap (retry_stage's scenario handling untouched by this diff), same bug class at a different entry point
- [x] [Review][Defer] Other stages (tts/subtitle/video) not audited for an analogous disk-resume-cache pattern, especially Story 8.11's fast-path clip reuse [src/yt_flow/pipeline/nodes/] — deferred, out of scope, candidate follow-up story
- [x] [Review][Defer] Derived/adjacent asset caches (pose cards, entity cards) not addressed by this cleanup [src/yt_flow/services/run_service.py] — deferred, speculative, needs separate investigation
- [x] [Review][Defer] Synchronous file I/O inside async `_delete_image_artifacts`, inconsistent with the codebase's `asyncio.to_thread` convention used elsewhere in this file [src/yt_flow/services/run_service.py:720] — deferred, low risk given bounded shot counts
- [x] [Review][Defer] `run_service.py` reaches into `image_node`'s underscore-prefixed private helpers (`_shot_base`, `_sidecar_path`) [src/yt_flow/services/run_service.py:730-731] — deferred, cross-module coupling smell, not a functional bug
- [x] [Review][Defer] Concurrency/interleaving hazard on the `aget_state → mutate → aupdate_state` sequence against a double-clicked reject/approve [src/yt_flow/services/run_service.py:655-666] — deferred, pre-existing pattern shared by `retry_stage`
- [x] [Review][Defer] Checkpoint-level `gate_states[stage]` may transiently read "rejected" then get re-asserted rather than cleanly show "pending" before the stage re-enters [src/yt_flow/pipeline/gates.py:30] — deferred, low-confidence, DB mirror (the only current consumer) is unaffected

## Dev Notes

- `_nullify` already handles the cascade correctly per stage index (`i = _STAGES.index(stage)`) — this story adds a caller, not new zeroing logic. Read `run_service.py:618-643` before touching anything.
- `resume_run`'s docstring currently says "carried for traceability only" about the `stage` param — that comment becomes stale once this fix lands (the param now also drives the nullify branch); update it.
- Do not conflate this with 5.23 (ComfyUI crash mitigation) — that story is about the pipeline recovering from a *crash*; this story is about an explicit human "no, redo it" decision producing a real redo. Different triggers, same underlying resume-cache mechanism, but keep the fixes and tests separate.
- **ponytail:** one `if` branch reusing existing functions. No new state field, no new API parameter, no schema change.
- **Scope discovery (dev session, superseded the above ponytail note for `image` only):** `_nullify` alone does not satisfy AC4. `_existing_complete_shot` (image.py) never reads `image_path` from state — it is a pure disk check (sidecar JSON + PNG file) — so zeroing the state field has zero effect on it. Proved empirically: reverting the disk-cleanup addition below made `retry_stage` exhibit the *identical* silent-reuse symptom on a completed image stage with an unchanged prompt, meaning Story 2.4's `retry_stage` had this same latent bug all along; the live evidence for this story ("manual file deletion was required") is itself proof state-only nullify was never going to work. Jay approved the wider fix (see options presented mid-session): `resume_run` and `retry_stage` now also call a new `_delete_image_artifacts(run_id, scenes)` (unlinks each shot's `.png` + `_done.json` sidecar) whenever `stage == "image"`, right alongside the existing `_nullify` call. `_nullify`/`_reset_gates` themselves are unchanged, per AC2/AC6.

### Project Structure Notes

- Modify: `src/yt_flow/services/run_service.py` (`resume_run`, `retry_stage`, new `_delete_image_artifacts`)
- Tests: alongside existing `retry_stage`/gate tests (follow current fixture conventions)

### References

- [Source: src/yt_flow/services/run_service.py:552-565] — `resume_run`, the function being fixed
- [Source: src/yt_flow/services/run_service.py:618-643] — `_nullify`/`_reset_gates`, reused unchanged
- [Source: src/yt_flow/pipeline/graph.py:23-27] — `_REJECT_TARGET` routing that re-enters the stage node
- [Source: src/yt_flow/pipeline/nodes/image.py:154-176] — `_existing_complete_shot`, the resume cache this bug defeats
- [Source: _bmad-output/implementation-artifacts/e2e-iteration1-2026-07-09.md] — live discovery context

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Empirically proved (via a throwaway probe, then via reverting/restoring the fix) that `_nullify` alone does not defeat `image_node._existing_complete_shot`'s disk-only resume cache — it reads only sidecar JSON + PNG file, never `state["scenes"][...]["image_path"]`. Confirmed `retry_stage` (Story 2.4) has the identical latent symptom on a completed image stage with an unchanged prompt.
- Presented findings + two options to Jay mid-session (state-nullify-only vs. also deleting stale on-disk artifacts); Jay chose the latter (also fix `retry_stage`).
- Red/green verified twice: (1) the state-nullify unit tests fail without the `resume_run` nullify branch, pass with it; (2) the e2e disk-cache regression test fails without the new `_delete_image_artifacts` call sites (both in `resume_run` and `retry_stage`), passes with them restored.

### Completion Notes List

- `resume_run` now nullifies + resets gates on reject (mirrors `retry_stage`), attributing the checkpoint update to `as_node=stage` (not `_RETRY_ENTRY[stage]`) since the graph is still paused at the gate's interrupt, unlike `retry_stage`'s idle-checkpoint case.
- Added `_delete_image_artifacts(run_id, scenes)`, called from both `resume_run` (reject) and `retry_stage` when `stage == "image"` — deletes each shot's `.png` + `_done.json` sidecar so `_existing_complete_shot` can't resurrect stale output. This also fixes a previously-undiscovered identical bug in `retry_stage` itself (bonus, approved by Jay).
- `_nullify`/`_reset_gates` themselves are unchanged (AC2/AC6) — the new disk-cleanup is an explicit sibling call, not folded into `_nullify`.
- Full suite: 1316 passed, 1 skipped, no regressions. `ruff check` clean on all changed files.
- AC7 "live verification" satisfied via the mocked-ComfyUI e2e test (`test_reject_image_gate_resubmits_to_comfyui_instead_of_reusing_disk_cache`) — no live ComfyUI instance was exercised this session.

### File List

- `src/yt_flow/services/run_service.py` — `resume_run` reject-nullify branch, `_delete_image_artifacts`, `retry_stage` wiring
- `tests/services/test_run_service_gate.py` — reject-nullifies / approve-untouched unit tests
- `tests/api/test_e2e_stub_run.py` — reject-forces-real-ComfyUI-resubmission regression test

## Change Log

- 2026-07-12: Implemented AC1-3 (`resume_run` reject → `_nullify`+`_reset_gates`, `as_node=stage`). Discovered mid-implementation that this alone does not satisfy AC4: `image_node._existing_complete_shot` is a disk-only resume cache that never reads state, so `retry_stage` (Story 2.4) turned out to share the identical latent bug. Presented findings + options to Jay; approved widening the fix to also delete the stage's on-disk sidecar+PNG (`_delete_image_artifacts`) from both `resume_run` and `retry_stage`. Full regression 1316 passed/1 skipped, ruff clean. Status -> review.
- 2026-07-12: Code review (3-layer: Blind Hunter, Edge Case Hunter, Acceptance Auditor) found 0 decision-needed, 5 patch, 7 defer, 5 dismiss. Applied all 5 patches: guarded the reject-nullify branch to skip `stage == "scenario"` (its reject routes to END, not a redo — nullifying only destroyed the rejected draft's artifacts for no benefit); hardened `_delete_image_artifacts` against per-shot `OSError`/`KeyError` so a filesystem hiccup can't leave a run stuck at `status="running"` forever; added a direct e2e test for `retry_stage`'s `_delete_image_artifacts` call site (previously untested); updated `resume_run`'s docstring to mention the disk-deletion side effect; strengthened the reject e2e test with a checkpoint read proving every shot's `image_path` is repopulated post-regeneration. 7 pre-existing/out-of-scope findings deferred to `deferred-work.md` (most notably: `retry_stage(stage="scenario")` doesn't clean up downstream image artifacts — same bug class, different entry point). Full regression 1330 passed/1 skipped, ruff clean. Status -> done.
