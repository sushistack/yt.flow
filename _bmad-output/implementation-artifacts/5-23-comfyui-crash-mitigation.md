---
created: 2026-07-10
story_key: 5-23-comfyui-crash-mitigation
story_id: "5.23"
epic: 5
previous_story: 5-22-narration-style-designation-rules
depends_on:
  - 5-14-pipeline-resilience-shot-resume-comfyui-healthcheck  # check_health + shot-resume this story extends
related:
  - 2-6-gate-reject-nullify-fix   # a different resume-cache concern — do not conflate
workflow_decision: "Extend image_node's existing health-check call site; reuse comfyui_client.check_health. No new stage, no ComfyUI process supervision (out of scope — see Dev Notes)."
evidence: "Baseline run 272b05a4 crashed near shot 39; iteration-1 run d55a265b crashed at shot 42. Both hipErrorIllegalAddress core dumps mid-image-stage on ROCm (RX 9060 XT)."
---

# Story 5.23: ComfyUI Sustained-Load Crash Mitigation

Status: ready-for-dev

## Story

As Jay,
I want the image stage to notice a mid-batch ComfyUI crash and wait for it to come back instead of failing the whole stage immediately,
so that a long shot batch (50+ shots) doesn't require me to manually notice the crash, restart ComfyUI, and click retry every time.

## Context

Two independent runs have now crashed ComfyUI (ROCm, RX 9060 XT) at nearly the same point under sustained load: baseline (272b05a4) at ~39 shots, iteration 1 (d55a265b) at shot 42 — both `hipErrorIllegalAddress`, both a hard process abort (`core dumped`), not a graceful error. This is a driver-level fault outside this project's control; **not fixable in code.** What IS fixable: the app's reaction.

Today's reaction (`image.py`): `check_health` runs exactly **once**, before the first non-resumed shot in the whole stage (`health_checked` flag, image.py:229,275-277). A crash 40 shots later goes completely undetected until `submit_and_fetch` itself fails (connection refused), which propagates up and fails the entire stage — correctly surfaced as a clear error (confirmed: `failed image stage=image run_id=... ComfyUI produced no image for prompt_id=... within timeout`), never silent. But recovery requires a human to notice, restart ComfyUI, and call `POST /stages/image/retry` — which then works correctly because completed shots resume from disk (`_existing_complete_shot`, unaffected by this story).

This story removes exactly one step from that manual loop: **noticing + waiting for recovery**, not process supervision. Whether ComfyUI actually comes back up (systemd restart policy, a supervisor script, or Jay manually running `./run.sh` again) is explicitly out of scope — see Dev Notes.

## Acceptance Criteria

1. `Settings.comfyui_health_poll_every_n_shots: int = Field(20, ge=1)` (env `YTFLOW_COMFYUI_HEALTH_POLL_EVERY_N_SHOTS`). Every N **generated** (non-resumed, non-plate) shots, `check_health` runs again — not just once at stage start. Choose the default conservatively below the observed ~39-42 shot crash window so a check lands before the typical failure point.
2. On a health-check failure mid-batch (not the pre-existing first-shot check — this AC is about a NEW mid-batch failure), the stage does **not** immediately fail. It enters a bounded wait-and-recheck loop: poll `check_health` every `comfyui_crash_recovery_poll_sec` (`Settings`, default 15.0) for up to `comfyui_crash_recovery_timeout_sec` (`Settings`, default 300.0). Recovery = health check succeeds → log INFO, continue the shot loop from the next unprocessed shot exactly as today's manual retry would (no state nullification needed — this is a resume, not a redo; do not touch 2.6's reject/nullify path).
3. If the recovery window expires without a successful health check, fail the stage with the existing clear error format (AD-10 — degrade to a loud, attributable failure, never a silent hang) — same externally-visible behavior as today, just after the wait instead of immediately.
4. The submit-time crash case (health check passed N shots ago, but `submit_and_fetch` itself now fails because ComfyUI died in between checks) reuses the SAME bounded wait-and-recheck loop before failing — a crash is a crash regardless of which call first notices it. Structure the retry-with-recovery logic as one helper both call sites use.
5. Every wait/recovery event is logged at INFO (recovery) or WARNING (timeout exceeded) with shot progress (`"ComfyUI health check failed after N/M shots, waiting for recovery"` / `"ComfyUI recovered after Xs, resuming"` / `"ComfyUI did not recover within Ys, failing stage"`).
6. No change to `_existing_complete_shot`, `_nullify`, or any reject/retry endpoint behavior — this story is purely inside `image_node`'s own shot loop.
7. Tests: mocked `check_health` failing then succeeding after N polls (asserts loop continues, no stage failure); mocked `check_health` failing for the full timeout window (asserts stage fails with the existing error format, unchanged message shape); mid-batch periodic check triggers at the configured shot interval (not only shot 0).
8. Live verification note: a real crash-and-recover cycle is expensive to reproduce on demand (needs actual sustained ComfyUI load). Acceptable evidence: the mocked test suite above, PLUS a manual kill-and-restart-within-window test against real ComfyUI (kill the process mid-run, restart it within the default 300s window, confirm the stage auto-continues without a `retry` call).

## Tasks / Subtasks

- [ ] Task 1: `Settings` fields for poll interval, recovery poll/timeout (AC:1,2)
- [ ] Task 2: Extract a `_wait_for_comfyui_recovery(base_url) -> bool` helper wrapping the bounded poll loop (AC:2,3)
- [ ] Task 3: Wire periodic health check into the shot loop (every N generated shots) (AC:1)
- [ ] Task 4: Wire `submit_and_fetch` failure through the same recovery helper before propagating (AC:4)
- [ ] Task 5: Logging (AC:5)
- [ ] Task 6: Mocked recovery/timeout/periodic-trigger tests (AC:7)
- [ ] Task 7: Manual kill-and-restart live verification, record in Dev Agent Record (AC:8)

## Dev Notes

- **Explicit non-goal:** this story does not manage the ComfyUI process itself (no subprocess spawn/kill/restart from within yt.flow). If Jay wants the app to *also* auto-restart ComfyUI, that's a materially bigger story (process ownership, log capture, restart-loop guards) — flag it, don't build it here. A `systemd`/Docker `restart: on-failure` policy on the ComfyUI service is the standard way to get "comes back on its own" without any app code, and is worth recommending to Jay as an infra note, not a code deliverable.
- Recovery does not require `_nullify` — completed shots are already correctly persisted (sidecar + PNG) and `_existing_complete_shot` resumes them on the very next loop iteration once ComfyUI is healthy again. This story only adds the *wait*, not any new resume logic.
- Keep `comfyui_client.check_health`'s own bounded transport retry (`CONNECT_ATTEMPTS`/`CONNECT_RETRY_DELAY`, comfyui_client.py:21-22) untouched — this story's recovery loop wraps calls to it, it doesn't change its internals.
- **ponytail:** one helper function, two config fields, reused at two call sites. No new module, no process supervision.

### Project Structure Notes

- Modify: `src/yt_flow/pipeline/nodes/image.py`, `src/yt_flow/config.py`
- Tests: alongside existing `image_node`/health-check test fixtures

### References

- [Source: src/yt_flow/pipeline/nodes/image.py:220-310] — `image_node`, single health-check-at-start call site
- [Source: src/yt_flow/services/comfyui_client.py:29-61] — `check_health`, `_request_with_retry`
- [Source: _bmad-output/implementation-artifacts/e2e-iteration1-2026-07-09.md] — crash-at-42-shots evidence
- [Source: _bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md] — crash-at-~39-shots precedent

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
