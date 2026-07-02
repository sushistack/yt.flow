---
title: 'B-1/B-2/B-3 Dev Dependencies (concurrency guard, stub seam, Langfuse flag)'
type: 'chore'
created: '2026-07-02'
status: 'done'
baseline_commit: '92ab9a2'
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

- `src/yt_flow/services/run_service.py` -- B-1: add `run.status` guard to `retry_stage` (L417-452; guard before `aupdate_state` at L443) and `edit_artifact` (L455-491; guard before `aupdate_state` at L487, which is the only mutation — no `_write_run` here). `run.status` is a string attr on the `Run` SQLModel. Status literals: `pending|running|awaiting_approval|complete|failed`.
- `src/yt_flow/api/routes/runs.py:128` -- reference 409 idiom (gate-not-pending): `raise HTTPException(status_code=409, detail=f"Gate not pending for stage '{stage}'")`.
- `src/yt_flow/config.py:11-13` -- B-3: add `langfuse_enabled: bool = True` after the `langfuse_*` block (env `YTFLOW_LANGFUSE_ENABLED`; `pydantic-settings`, `env_prefix="YTFLOW_"`).
- `src/yt_flow/pipeline/nodes/{scenario,image,tts,subtitle,video}.py`, `src/yt_flow/services/eval_service.py` -- B-3: `@observe`-decorated stage sites importing `from langfuse import get_client, observe` and calling `get_client().update_current_span(...)`; must no-op when flag off. NOTE: a 7th site exists — `services/run_service.py:262` (`_trace_cm` calls `get_client()`). The native `tracing_enabled=False` seam (see Design Notes) covers all 7 without touching import sites; a wrapper-swap would need to include run_service too. `services/prompt_service.py` uses `from langfuse import Langfuse` for Prompt Hub fetching (NOT tracing) — the flag must NOT disable prompt fetching.
- `src/yt_flow/pipeline/nodes/scenario.py:35` (`_call_deepseek`), `tts.py:80-94` (`_synthesize` Qwen HTTP), `services/comfyui_client.py` (`submit_and_fetch`/`submit_and_fetch_outputs`), `video.py:317` (`_run_ffmpeg`) -- B-2 monkeypatch seams.
- `tests/api/conftest.py` -- existing env-setup conftest; B-2 fixtures + cassettes added under `tests/stubs/` + root `tests/conftest.py`.

## Tasks & Acceptance

**Execution:**
- [x] `src/yt_flow/services/run_service.py` -- add strict `run.status` guard (helper `_MUTABLE_STATES = frozenset({"awaiting_approval","failed","complete"})`) to `retry_stage` and `edit_artifact`, raising 409 before any state mutation -- B-1
- [x] `src/yt_flow/config.py` -- add `langfuse_enabled: bool = True` -- B-3
- [x] `src/yt_flow/observability.py` (new) OR native langfuse disable -- make `observe`/`get_client` no-op when flag off; swap the 6 import sites to the chosen seam -- prefer langfuse's native tracing-disable if it reliably no-ops `@observe` in 4.12; wrapper module only if not -- B-3 (chose wrapper: global singleton is first-construction-wins keyed by public_key, so native `tracing_enabled` is init-ordering-fragile; wrapper is ordering-independent + preserves Prompt Hub fetching. 7 sites swapped incl. run_service.py:262.)
- [x] `tests/stubs/` (new) + `tests/conftest.py` -- fake ComfyUI client + `_run_ffmpeg` no-op (tiny artifacts), cassette-playback fixtures for `_call_deepseek`/Qwen; cassette JSON under `tests/fixtures/cassettes/` -- B-2
- [x] tests -- `tests/api/test_runs.py` invalid-state guard cases (B-1); `tests/test_config.py` flag default+override and one `@observe`-off no-op assertion (B-3); one stub-profile smoke test running the graph to terminal (B-2) -- unit-test the matrix above

**Acceptance Criteria:**
- Given a run with `status="running"`, when retry or PATCH-artifact is called, then the API returns 409 and `aget_state` shows the checkpoint unchanged.
- Given `YTFLOW_LANGFUSE_ENABLED=false`, when a decorated stage node executes, then it completes normally and no Langfuse network/tracing call is made or raised.
- Given the B-2 fixtures active, when the full graph is invoked, then it reaches a terminal state producing tiny deterministic artifacts with zero real network/subprocess calls.
- Given no new production stub flag and no new runtime dependency were added, when the suite runs, then `uv run pytest` and `npm test --prefix frontend` stay green.

## Design Notes

- **B-3 seam choice is deferred to implementation:** express the outcome (flag off ⇒ `@observe` no-op, stages complete). langfuse 4.12 exposes a native `tracing_enabled: bool` param on the `Langfuse(...)` constructor — confirmed present. Preferred seam: init the global client with `tracing_enabled=settings.langfuse_enabled` at the single init site, so `@observe` and `update_current_span` no-op everywhere (all 7 sites incl. `_trace_cm`) without touching import sites, and Prompt Hub fetching in `prompt_service.py` is unaffected. Fall back to a ~15-line `observability.py` re-exporting real vs. dummy `observe`/`get_client` ONLY if the native flag does not reliably no-op `@observe`; the dummy client must accept `update_current_span(...)` calls silently.
- **B-2 cassettes:** live DeepSeek/Qwen keys are unavailable here, so cassette JSON is hand-authored to match the documented response shapes already encoded in `test_scenario.py`/`test_tts.py`. Per test-design, cassettes must be re-recorded when Prompt Hub templates or pinned model IDs change — add a short README in the cassette dir stating this.

## Verification

**Commands:**
- `uv run pytest -q` -- expected: all pass, including new B-1 guard, B-3 flag, B-2 smoke tests
- `uv run pytest tests/api/test_runs.py -q` -- expected: invalid-state 409 cases pass
- `npm test --prefix frontend` -- expected: unchanged, green (no frontend impact)

## Suggested Review Order

**B-1 — concurrency guard (the core change)**

- Guard entry point: strict allow-list of statuses that may mutate a checkpoint.
  [`run_service.py:39`](../../src/yt_flow/services/run_service.py#L39)

- Retry guard — 409 before gate-state read and any `aupdate_state`/`_write_run`.
  [`run_service.py:431`](../../src/yt_flow/services/run_service.py#L431)

- Edit guard — 409 inside the session, before file write and the sole `aupdate_state`.
  [`run_service.py:478`](../../src/yt_flow/services/run_service.py#L478)

**B-3 — langfuse tracing on/off seam**

- The seam: env-read (not `Settings()`) binds real vs no-op `observe`/`get_client` at import.
  [`observability.py:65`](../../src/yt_flow/observability.py#L65)

- No-op client: `__getattr__` catch-all swallows every tracing call silently.
  [`observability.py:41`](../../src/yt_flow/observability.py#L41)

- The flag itself (default true); does NOT gate Prompt Hub fetching.
  [`config.py:16`](../../src/yt_flow/config.py#L16)

**B-2 — offline stub seam (test-level only)**

- Reusable fixture wiring the four external seams to deterministic fakes.
  [`conftest.py:25`](../../tests/conftest.py#L25)

- Fakes emit tiny artifacts, zero network/subprocess; cassettes are hand-authored JSON.
  [`fakes.py:1`](../../tests/stubs/fakes.py#L1)

**Tests (supporting)**

- B-1 invalid-state 409 cases + settled-status pass-through.
  [`test_runs.py:269`](../../tests/api/test_runs.py#L269)

- B-2 graph-to-terminal smoke (offline).
  [`test_stub_profile_smoke.py:43`](../../tests/pipeline/test_stub_profile_smoke.py#L43)

- B-3 flag default/override + `@observe` no-op contract.
  [`test_config.py:47`](../../tests/test_config.py#L47)
