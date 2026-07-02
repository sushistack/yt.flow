---
title: 'B-1/B-2/B-3 Dev Dependencies (concurrency guard, stub seam, Langfuse flag)'
type: 'chore'
created: '2026-07-02'
status: 'draft'
context:
  - '{project-root}/_bmad-output/test-artifacts/test-design/test-design-architecture.md'
  - '{project-root}/_bmad-output/test-artifacts/test-design/test-design-qa.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Three pre-test-development blockers (decided 2026-07-02) are unimplemented, so QA cannot write SYS-INT-004 (concurrency guards), SYS-E2E-001 (stub-profile full run), or SYS-INT-007 (Langfuse degradation). Without them the highest risks (R-009 concurrency, R-005 no E2E, R-004 trace overhead) stay untested.

**Approach:** Land the three Dev dependencies exactly as decided — (B-1) strict `running`-state guard on retry/edit, (B-2) test-level fake/cassette seams for the four external deps, (B-3) a `YTFLOW_LANGFUSE_ENABLED` config flag that makes `@observe` a no-op — each independently but shipped together.

## Boundaries & Constraints

**Always:**
- B-1 strict semantics: `retry_stage`/`edit_artifact` proceed only when `run.status ∈ {awaiting_approval, failed, complete}`; any other status (`running`, `pending`) → HTTP 409 with the checkpoint left untouched (guard BEFORE any `aupdate_state`/`_write_run`/file write).
- B-1 reuses the existing service-layer `HTTPException(status_code=409, ...)` idiom; does not weaken the pre-existing gate-state and double-approve guards.
- B-2 wiring lives entirely at test level (pytest fixtures/monkeypatch) at the seams `scenario._call_deepseek`, `tts` HTTP call, `comfyui_client`, `video._run_ffmpeg`. Fakes emit tiny deterministic artifacts; DeepSeek/Qwen use recorded-shape cassette JSON.
- B-3 flag defaults `true`; when `false`, decorated stages run to completion and no tracing call raises.

**Ask First:**
- Adding any NEW production stub/mock flag (B-2 forbids it — the existing `comfyui_mock`/`qwen_tts_mock` are not to be extended for this).
- Adding a new third-party dependency (e.g. vcrpy) instead of hand-authored cassette JSON.

**Never:** Modifying pipeline node business logic; changing external API request shapes; building the full SYS-E2E-001 5×-approve test (that is QA's downstream task — B-2 delivers only the reusable seam + one smoke check); scene-level resume granularity.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| B-1 retry while running | `run.status="running"`, POST retry | 409; checkpoint + gate_states unchanged | 409 detail names current status |
| B-1 retry when allowed | `run.status ∈ {awaiting_approval,failed,complete}` + retryable gate | proceeds as today (202) | existing gate-state guard still applies |
| B-1 edit while running | `run.status="running"`, PATCH artifact | 409; no file write, no `aupdate_state` | 409 detail names current status |
| B-3 flag off | `YTFLOW_LANGFUSE_ENABLED=false` | `@observe` stage runs, returns normally, no trace emitted | tracing calls no-op, never raise |
| B-3 flag on/default | unset | tracing behaves as today | unchanged |
| B-2 stubbed graph | fixtures active | full graph reaches terminal state with tiny artifacts on disk | fakes deterministic, no network |

</frozen-after-approval>

## Code Map

- `src/yt_flow/services/run_service.py` -- B-1: add `run.status` guard to `retry_stage` (~L425) and `edit_artifact` (~L466), before checkpoint mutation. Status literals: `pending|running|awaiting_approval|complete|failed`.
- `src/yt_flow/api/routes/runs.py:129` -- reference 409 idiom (gate-not-pending).
- `src/yt_flow/config.py` -- B-3: add `langfuse_enabled: bool = True` after the `langfuse_*` block (env `YTFLOW_LANGFUSE_ENABLED`, `pydantic-settings`).
- `src/yt_flow/pipeline/nodes/{scenario,tts,image,subtitle,video}.py`, `src/yt_flow/services/eval_service.py` -- B-3: 6 sites importing `from langfuse import get_client, observe` and calling `get_client().update_current_span(...)`; must no-op when flag off.
- `src/yt_flow/pipeline/nodes/scenario.py:35` (`_call_deepseek`), `tts.py`, `services/comfyui_client.py`, `video.py:317` (`_run_ffmpeg`) -- B-2 monkeypatch seams.
- `tests/api/conftest.py` -- existing env-setup conftest; B-2 fixtures + cassettes added under `tests/stubs/` + root `tests/conftest.py`.

## Tasks & Acceptance

**Execution:**
- [ ] `src/yt_flow/services/run_service.py` -- add strict `run.status` guard (helper `_MUTABLE_STATES = frozenset({"awaiting_approval","failed","complete"})`) to `retry_stage` and `edit_artifact`, raising 409 before any state mutation -- B-1
- [ ] `src/yt_flow/config.py` -- add `langfuse_enabled: bool = True` -- B-3
- [ ] `src/yt_flow/observability.py` (new) OR native langfuse disable -- make `observe`/`get_client` no-op when flag off; swap the 6 import sites to the chosen seam -- prefer langfuse's native tracing-disable if it reliably no-ops `@observe` in 4.12; wrapper module only if not -- B-3
- [ ] `tests/stubs/` (new) + `tests/conftest.py` -- fake ComfyUI client + `_run_ffmpeg` no-op (tiny artifacts), cassette-playback fixtures for `_call_deepseek`/Qwen; cassette JSON under `tests/fixtures/cassettes/` -- B-2
- [ ] tests -- `tests/api/test_runs.py` invalid-state guard cases (B-1); `tests/test_config.py` flag default+override and one `@observe`-off no-op assertion (B-3); one stub-profile smoke test running the graph to terminal (B-2) -- unit-test the matrix above

**Acceptance Criteria:**
- Given a run with `status="running"`, when retry or PATCH-artifact is called, then the API returns 409 and `aget_state` shows the checkpoint unchanged.
- Given `YTFLOW_LANGFUSE_ENABLED=false`, when a decorated stage node executes, then it completes normally and no Langfuse network/tracing call is made or raised.
- Given the B-2 fixtures active, when the full graph is invoked, then it reaches a terminal state producing tiny deterministic artifacts with zero real network/subprocess calls.
- Given no new production stub flag and no new runtime dependency were added, when the suite runs, then `uv run pytest` and `npm test --prefix frontend` stay green.

## Design Notes

- **B-3 seam choice is deferred to implementation:** express the outcome (flag off ⇒ `@observe` no-op, stages complete). Try langfuse 4.12's own disable first (env/init); fall back to a ~15-line `observability.py` re-exporting real vs. dummy `observe`/`get_client`. Note the 6 sites also call `get_client().update_current_span(...)` inside the function body — the dummy client must accept these silently.
- **B-2 cassettes:** live DeepSeek/Qwen keys are unavailable here, so cassette JSON is hand-authored to match the documented response shapes already encoded in `test_scenario.py`/`test_tts.py`. Per test-design, cassettes must be re-recorded when Prompt Hub templates or pinned model IDs change — add a short README in the cassette dir stating this.

## Verification

**Commands:**
- `uv run pytest -q` -- expected: all pass, including new B-1 guard, B-3 flag, B-2 smoke tests
- `uv run pytest tests/api/test_runs.py -q` -- expected: invalid-state 409 cases pass
- `npm test --prefix frontend` -- expected: unchanged, green (no frontend impact)
