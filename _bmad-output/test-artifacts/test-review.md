---
stepsCompleted: ['step-01-load-context', 'step-02-discover-tests', 'step-03-quality-evaluation', 'step-03f-aggregate-scores', 'step-04-generate-report']
lastStep: 'step-04-generate-report'
lastSaved: '2026-07-02'
workflowType: 'testarch-test-review'
inputDocuments:
  - 'tests/api/test_stages.py'
  - 'tests/api/test_workspace_files.py'
  - 'tests/services/test_run_service_gate.py'
  - 'tests/api/test_e2e_stub_run.py'
  - 'tests/conftest.py'
  - 'tests/stubs/fakes.py'
  - '_bmad-output/test-artifacts/traceability-matrix.md'
  - '.env (existence/keys checked, values not read)'
---

# Test Quality Review: SYS-INT-004 / SYS-INT-007 / SYS-INT-008 / SYS-INT-009 / SYS-E2E-001 (14 new tests)

**Quality Score**: 65/100 (D - Needs Improvement)
**Review Date**: 2026-07-02
**Review Scope**: directory (4 files, tests added in the prior remediation session per `traceability-matrix.md`)
**Reviewer**: Murat (TEA) with Jay

---

Note: This review audits existing tests; it does not generate tests. Coverage mapping and coverage gates are out of scope here — see `_bmad-output/test-artifacts/traceability-matrix.md` (gate: PASS) for coverage.

## Executive Summary

**Overall Assessment**: Needs Improvement

**Recommendation**: Request Changes

### Key Strengths

✅ 11 of the 14 new tests (all of `test_stages.py`'s 3, all of `test_workspace_files.py`'s 4, and the new `test_e2e_stub_run.py`) are fully hermetic, deterministic, and well-isolated — they reuse existing correct fixtures (`tmp_path`, `FakeGraph`, `stub_profile`) with no network/time/random dependency.

✅ The new E2E test (`test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk`) is a genuinely strong addition — it drives the real product contract end-to-end and, per the traceability matrix, is what caught a critical pipeline-wiring bug and a filename-mismatch bug during the prior session. It runs in 0.08s.

✅ Naming is consistently clear and behavior-driven (`test_retry_while_running_returns_409_and_leaves_checkpoint_untouched`, `test_dotdot_traversal_outside_workspace_is_404`, etc.) — no ambiguous test names anywhere in the batch.

### Key Weaknesses

❌ **3 of the 14 new tests make a real, live outbound HTTPS call to a production Langfuse server (`https://langfuse.eli.kr`) on every run**, sourced from the repo's real `.env` file — confirmed empirically, not theoretical. This is the single dominant finding, flagged independently and convergently by the determinism, isolation, and performance passes.

❌ `tests/api/test_stages.py` is now 303 lines — 3 lines past the project's ≤300-line-per-file DoD ceiling.

❌ Moderate duplication: two near-identical trace-failure tests that should be parametrized, and a third re-implementation of an SSE-recording-registry double that already exists (twice) elsewhere in the suite.

### Summary

12 of the 14 newly-added tests meet the project's test-quality DoD (deterministic, isolated, ≤300 lines, ≤1.5 min, self-cleaning) cleanly. The remaining 3 — all in `tests/services/test_run_service_gate.py` (`test_node_failure_surfaces_failing_stage_in_trace_payload`, `test_trace_setup_failure_is_non_fatal_and_logged`, `test_trace_teardown_failure_is_non_fatal_and_logged`) — share one root cause that breaks two DoD criteria at once (not deterministic, not isolated) and degrades a third (performance): they use an `env` fixture that runs the real, un-stubbed `scenario_node`, which reads the project's actual `.env` file and calls the real Langfuse Prompt Hub over the network. This currently "works" only because the `scenario` prompt hasn't been seeded to the Prompt Hub yet (per prior project history) — it fails fast with a 404-equivalent instead of proceeding to a real DeepSeek API call with a real key. The moment that prompt is seeded (a change already planned, independent of these tests), these same three tests will start sending real test data to the production DeepSeek LLM API on every CI run. This is not a hypothetical: forcing `YTFLOW_DEEPSEEK_API_KEY=""` measurably dropped these tests from 0.5–1.9s to 0.01–0.03s, proving the network round-trip is real and live today. Recommend fixing before merge — the fix is small (reuse the existing `stub_profile` fixture) and the risk (silent real-API-cost/data-leak once the prompt is seeded) is disproportionate to the effort.

---

## Quality Criteria Assessment

| Criterion                            | Status  | Violations | Notes |
| ------------------------------------- | ------- | ---------- | ----- |
| Determinism (no real network/time/random) | ❌ FAIL | 3 HIGH, 2 MEDIUM | Real Langfuse network call in 3 tests; symlink test lacks a platform guard; unreset `_bg_tasks` global |
| Isolation (no shared/external state, cleanup) | ❌ FAIL | 3 HIGH, 2 MEDIUM | Same real-network root cause (external, unowned service = shared state); `app.state.*` and `_bg_tasks` unreset in `test_e2e_stub_run.py` teardown |
| Maintainability (structure, DRY, length) | ⚠️ WARN | 4 MEDIUM, 4 LOW | `test_stages.py` at 303 lines (DoD ceiling 300); duplicate trace-failure tests; duplicate `_RecordingRegistry`; stale docstring |
| Performance (≤1.5 min/test, no needless slowness) | ⚠️ WARN | 3 HIGH, 1 LOW | Same 3 tests: real network latency is the only non-trivial cost in the whole 14-test batch (0.5–1.9s vs ≤0.02s for everything else); numerically still well under the 1.5 min ceiling today, but the margin is a network SLA, not code |
| Hard waits (sleep/hangs)             | ✅ PASS | 0 | None found; one bounded `asyncio.wait_for(timeout=10)` safety guard in `test_e2e_stub_run.py` is a good pattern, not a violation |
| Test length (≤300 lines/file)        | ⚠️ WARN | 1 | `test_stages.py` = 303 lines (others: 102 / 255 / 110, all within DoD) |
| Test duration (≤1.5 min/test)        | ✅ PASS (fragile) | 0 numerically | All 14 tests measured at ≤1.9s; see performance note above on why this margin is not fully code-controlled |
| Cleanup / fixture teardown           | ⚠️ WARN | 2 MEDIUM | `test_e2e_stub_run.py`'s `api_env` fixture doesn't reset `run_service._bg_tasks` or `app.state.*` |
| Explicit assertions                  | ⚠️ WARN | 1 LOW | `test_edit_allowed_when_run_settled` checks only `status_code == 200`, weaker than the file's sibling happy-path test |
| Priority markers (P0/P1/P2/P3)       | N/A | — | Project doesn't use `pytest.mark.p0`-style tagging anywhere yet (a pre-existing, project-wide gap noted in the traceability matrix, not new to this batch) |

**Total Violations**: 0 Critical (P0-blocking-merge), 9 High, 8 Medium, 5 Low — **22 total**, but see note below: the 9 HIGH entries collapse to **3 distinct test functions sharing 1 root cause**, reported three times because it independently breaks three DoD dimensions.

---

## Quality Score Breakdown

Weighted per TEA quality priorities (determinism 30%, isolation 30%, maintainability 25%, performance 15%; coverage excluded — see `trace`):

```
Determinism:       60/100 (D)  x 0.30 = 18.0
Isolation:         60/100 (D)  x 0.30 = 18.0
Maintainability:   72/100 (C)  x 0.25 = 18.0
Performance:       70/100 (C)  x 0.15 = 10.5
                                       ------
Overall Score:                          64.5 -> 65/100
Grade:                                  D
```

---

## Critical Issues (Must Fix)

### 1. Three tests make a real network call to a production Langfuse server, one seeding-event away from also calling the real DeepSeek API

**Severity**: High (functionally the review's only P0-equivalent finding — flagged convergently by 3 of 4 independent quality passes)
**Location**: `tests/services/test_run_service_gate.py:170` (`test_node_failure_surfaces_failing_stage_in_trace_payload`), `:216` (`test_trace_setup_failure_is_non_fatal_and_logged`), `:230` (`test_trace_teardown_failure_is_non_fatal_and_logged`)
**Criteria violated**: Determinism, Isolation, Performance (stability of the ≤1.5min guarantee)

**Issue Description**:

All three tests use the file's `env` fixture (lines 51-67), which builds a real compiled LangGraph via `run_service.init(settings)` but — unlike `tests/api/test_e2e_stub_run.py`'s `api_env` fixture — never applies `stub_profile` (`tests/conftest.py`). Each test's first `await run_service.start_run(...)` therefore drives the real `scenario_node` (`src/yt_flow/pipeline/nodes/scenario.py:157-180`).

`scenario_node` does not use the `Settings(...)` object the test constructed for `run_service.init()`. It calls its own local seam, `_settings()` (scenario.py:26-28), which is a bare `Settings()` — pydantic-settings, `env_file=".env"` — reading the **repository's real `.env` file**. That file is confirmed (keys checked, not printed) to contain a real, non-empty `YTFLOW_DEEPSEEK_API_KEY` and `YTFLOW_LANGFUSE_HOST=https://langfuse.eli.kr` (a real, reachable, self-hosted server). Because the key is non-empty, the `if not s.deepseek_api_key: raise RuntimeError(...)` short-circuit at scenario.py:166-167 does **not** fire, and execution reaches `get_prompt(PROMPT_NAME)` → `src/yt_flow/services/prompt_service.py`'s `build_client()` (itself another bare `Settings()` read) → a real `Langfuse(...)` client → a real outbound HTTPS request to `https://langfuse.eli.kr`.

Confirmed empirically (not inferred):

```
$ PYTHONPATH=$PWD/src python -m pytest tests/services/test_run_service_gate.py \
    -k "trace_setup or trace_teardown or node_failure" --durations=10
  1.86s  test_trace_teardown_failure_is_non_fatal_and_logged
  0.72s  test_trace_setup_failure_is_non_fatal_and_logged
  0.63s  test_node_failure_surfaces_failing_stage_in_trace_payload

$ YTFLOW_DEEPSEEK_API_KEY="" PYTHONPATH=$PWD/src python -m pytest ... (same 3 tests)
  0.02s / 0.01s / 0.01s   # forcing the fast-fail path removes the network round-trip entirely

$ PYTHONPATH=$PWD/src python -c "from yt_flow.services.prompt_service import get_prompt; get_prompt('scenario')"
  RuntimeError: Langfuse prompt fetch failed: name='scenario' label=production   (elapsed: 0.80s)
```

A second, independent re-run by the performance reviewer reproduced the same pattern with different absolute numbers (0.86s/0.71s/0.49s vs. the original 0.63s/0.72s/1.86s) — the run-to-run variance on an otherwise-identical test is itself confirmation that real network latency, not code, governs these tests' duration.

Today this only "fails fast" (~0.6-0.9s) because the `scenario` prompt isn't yet seeded to the real Prompt Hub (a known, separately-tracked gap per project history). The moment it is seeded, these same three tests will proceed past `get_prompt` into `_call_deepseek()` (scenario.py:35-55) and send real HTTP requests — with the real API key from `.env` — to the production DeepSeek chat-completions API, using test SCP text as input. That is a real-money, real-third-party-dependency, potential-data-exposure risk introduced silently by an unrelated future change, with no test currently guarding against it.

**Current Code** (`tests/services/test_run_service_gate.py`):

```python
@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    # Real graph on a temp checkpointer + in-memory runs table.
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "ws"))
    db.init("sqlite://")
    settings = Settings(
        langfuse_host="http://localhost", langfuse_public_key="pk", langfuse_secret_key="sk",
        db_path=str(tmp_path / "cp.db"),
    )
    ...  # no stub_profile — scenario_node's *own* Settings() call still reads the real .env

async def test_trace_setup_failure_is_non_fatal_and_logged(env, monkeypatch, caplog):
    monkeypatch.setattr(run_service, "get_client", lambda: _RaisingClient())
    with caplog.at_level("WARNING", logger="yt_flow.services.run_service"):
        await run_service.start_run(run_id, "SCP-096", "t", reg)  # <- real scenario_node runs first
```

**Recommended Fix**:

Reuse the seam that already exists and is already correctly applied elsewhere in the suite (`tests/api/test_e2e_stub_run.py`'s `api_env` fixture, and the file-wide `stub_profile` fixture in `tests/conftest.py`):

```python
async def test_trace_setup_failure_is_non_fatal_and_logged(env, stub_profile, monkeypatch, caplog):
    monkeypatch.setattr(run_service, "get_client", lambda: _RaisingClient())
    with caplog.at_level("WARNING", logger="yt_flow.services.run_service"):
        await run_service.start_run(run_id, "SCP-096", "t", reg)  # scenario_node now uses fakes.fake_get_prompt / deepseek_from_cassette()
```

Apply the same one-line fixture addition to `test_node_failure_surfaces_failing_stage_in_trace_payload` and `test_trace_teardown_failure_is_non_fatal_and_logged`. This isolates each test to the single behavior it's meant to exercise (Langfuse-tracing-wrapper failure, or the failing-stage-name plumbing) instead of incidentally depending on Prompt Hub reachability.

**Why This Matters**:

This is not a flakiness risk in the usual sense (the test doesn't intermittently fail) — it's a hermeticity and blast-radius risk: CI runs, contributor laptops without VPN/network access to `langfuse.eli.kr`, and any future change that fixes the "seed the scenario prompt" gap can all change these tests' behavior or cost for reasons that have nothing to do with the code they're supposed to verify (AD-10's non-fatal-tracing-failure contract). It also means a real third-party API key from `.env` is live and reachable from the test suite today.

**Related Violations**: The same `env` fixture (without `stub_profile`) is reused by 7 pre-existing tests earlier in the same file (e.g. `test_start_run_pauses_at_scenario_gate`, `test_approve_advances_to_next_gate`) that were out of scope for this review (they predate the session under review) but share the identical gap — fixing the fixture itself, or documenting why `stub_profile` should be the default pairing with `env`, would remediate all of them at once. Recommend a follow-up ticket.

---

## Recommendations (Should Fix)

### 1. `tests/api/test_stages.py` exceeds the 300-line DoD ceiling

**Severity**: P2 (Medium)
**Location**: `tests/api/test_stages.py` (303 lines total; the 3 new tests occupy lines 271-303)
**Criterion**: Test length (≤300 lines)

The 3 new B-1 concurrency-guard tests are individually well-formed (10-13 lines each), but pushed the file 3 lines past the project's own DoD ceiling. Either trim (e.g., the `g.astream_calls == []` assertion in `test_retry_while_running_returns_409_and_leaves_checkpoint_untouched` is redundant with `g.updates == []` for proving "checkpoint untouched" — one of the two likely suffices) or split retry-tests vs. edit-tests into two files once the next test is added to this file.

### 2. Two trace-failure tests are near-duplicates that should be parametrized

**Severity**: P2 (Medium)
**Location**: `tests/services/test_run_service_gate.py:216` and `:230`
**Criterion**: DRY / duplication

`test_trace_setup_failure_is_non_fatal_and_logged` and `test_trace_teardown_failure_is_non_fatal_and_logged` share an identical body shape (seed run → build registry → monkeypatch `get_client` → run `start_run` under `caplog` → assert `awaiting_approval` + a "Langfuse" warning was logged); the only difference is which fake client class is injected. Recommend `@pytest.mark.parametrize("client_cls", [_RaisingClient, _RaisingExitClient])` over one shared test body. (Also hoist `_RaisingExitClient`/`_RaisingExitSpan` out of the test-local scope to module level alongside `_RaisingClient` for consistency, regardless of whether parametrization is adopted.)

### 3. Duplicate SSE-recording-registry test double

**Severity**: P2 (Medium)
**Location**: `tests/api/test_e2e_stub_run.py:23-30` (`_RecordingRegistry`)
**Criterion**: Cross-file duplication

This duplicates `_FakeRegistry` in `tests/services/test_run_service_gate.py:20-27` (and a third similarly-shaped registry already exists in `test_stages.py`) — same shape, different name, none living in the project's designated shared-fakes module (`tests/stubs/fakes.py`). Consolidate into one double, importable from `tests/stubs/fakes.py` or a shared conftest fixture.

### 4. `tests/stubs/fakes.py`'s module docstring is stale

**Severity**: P3 (Low)
**Location**: `tests/stubs/fakes.py:1`
**Criterion**: Documentation accuracy

Still says "four external seams (B-2)" and omits the new `fake_get_prompt`/`_FakePrompt` (added this session) from its bullet list, while `tests/conftest.py`'s `stub_profile` docstring was correctly updated to "five". Update for consistency.

### 5. `api_env` fixture teardown leaves two categories of global/singleton state unreset

**Severity**: P2 (Medium)
**Location**: `tests/api/test_e2e_stub_run.py:38-56`
**Criterion**: Isolation / cleanup

- `run_service._bg_tasks` (module-level `set()`) is never cleared in teardown, unlike `_configs`/`_graph`/`db._engine`. Self-cleans on the happy path via `add_done_callback`, but a test failure between a stage's `spawn()` and the subsequent `_drain_bg_tasks()` await would leave a task bound to a dead event loop in the shared global, able to raise `RuntimeError: Task got Future attached to a different loop` in a later, unrelated test.
- `app.state.scps` / `app.state.workspace_path` / `app.state.sse_registry` (on the module-level `app` singleton from `yt_flow.api.main`) are set but never reset. This mirrors a pre-existing pattern in `test_stages.py`/`test_ab_run.py` (not a novel regression), but centralizing it into a shared, resetting `conftest.py` fixture would remove the latent order-dependency risk architecturally rather than relying on every test file remembering to overwrite state before reading it.

### 6. `test_symlink_escape_is_404` has no cross-platform guard

**Severity**: P3 (Low)
**Location**: `tests/api/test_workspace_files.py:97`
**Criterion**: Determinism (platform-dependent operation)

`Path.symlink_to` can raise `OSError` on Windows without Developer Mode/admin rights, or on filesystems without symlink support. Wrap in `try/except OSError: pytest.skip(...)` or an explicit `skipif`, so unsupported environments skip cleanly instead of erroring.

### 7. Weak assertion in the positive-control test

**Severity**: P3 (Low)
**Location**: `tests/api/test_stages.py:298-303` (`test_edit_allowed_when_run_settled`)
**Criterion**: Explicit assertions

Only checks `status_code == 200`, weaker than the file's other happy-path edit test (which also checks the `updated` flag and written file content). Add `assert resp.json()["updated"] is True` at minimum.

### 8. `# ponytail:` comment used for bugfix history rather than a deliberate simplification

**Severity**: P3 (Low)
**Location**: `tests/conftest.py:33`
**Criterion**: Comment convention drift

The project's `# ponytail:` marker is meant to flag deliberate simplifications with a known ceiling, not to narrate a retrospective bug discovery. Reword as a plain `# NOTE:`.

---

## Best Practices Found

### 1. `stub_profile` fixture is a strong, reusable hermeticity seam

**Location**: `tests/conftest.py:9-39`
**Pattern**: Centralized fake-injection fixture

Wiring all five external seams (Langfuse Prompt Hub, DeepSeek, Qwen TTS, ComfyUI, ffmpeg) through one fixture, with fakes centralized in `tests/stubs/fakes.py`, is exactly the right pattern — the gap in this review isn't the pattern, it's that 3 new tests didn't request it. Use this fixture as the template when writing the next test that drives `run_service.start_run`/`resume_run` through a real graph.

### 2. `test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk` as an E2E reference

**Location**: `tests/api/test_e2e_stub_run.py:70-110`
**Pattern**: Full-contract, zero-mocking-of-the-system-under-test E2E test

Drives the real HTTP API, verifies SSE event ordering, and asserts a real artifact on disk — all while remaining fully offline via `stub_profile`. Per the traceability matrix, this test caught two real production bugs (stub-node wiring, artifact filename mismatch) that unit tests and a direct-call smoke test both missed. This is the pattern other E2E-level tests in this project should follow.

---

## Test File Analysis

| File | Lines | New tests | Framework | Notes |
| --- | --- | --- | --- | --- |
| `tests/api/test_stages.py` | 303 | 3 (`test_retry_while_running_returns_409_and_leaves_checkpoint_untouched`, `test_edit_while_running_returns_409_and_leaves_checkpoint_untouched`, `test_edit_allowed_when_run_settled` ×3 parametrized) | pytest (sync, FastAPI `TestClient`) | 3 lines over the 300-line DoD |
| `tests/api/test_workspace_files.py` | 102 | 4 (`test_dotdot_traversal_outside_workspace_is_404`, `test_encoded_dotdot_traversal_is_404`, `test_encoded_absolute_path_is_404`, `test_symlink_escape_is_404`) | pytest (sync, `TestClient`) | Clean; 1 LOW platform-guard note |
| `tests/services/test_run_service_gate.py` | 255 | 4 (`test_node_failure_surfaces_failing_stage_in_trace_payload`, `test_stage_from_exception_falls_back_to_unknown_without_notes`, `test_trace_setup_failure_is_non_fatal_and_logged`, `test_trace_teardown_failure_is_non_fatal_and_logged`) | pytest-asyncio | 3 of 4 hit the real-network defect |
| `tests/api/test_e2e_stub_run.py` | 110 (whole file new) | 1 (`test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk`) | pytest-asyncio, `httpx.AsyncClient` + ASGI transport | Correctly hermetic via `stub_profile`; teardown gaps noted above |

**Test count**: 14 pytest items collected (`test_edit_allowed_when_run_settled` contributes 3 via `@pytest.mark.parametrize`). The user-reported count of "15" is close but not exact against what's in the current working tree — see Appendix note.

**Total measured runtime (all 14, filtered run)**: 2.95-4.14s across two independent runs (well under the 1.5 min/test ceiling numerically; see Critical Issue #1 for why that margin isn't fully code-controlled for 3 of the 14).

---

## Context and Integration

### Related Artifacts

- **Traceability Matrix**: [`_bmad-output/test-artifacts/traceability-matrix.md`](traceability-matrix.md) — documents why each of these 14 tests was written (closing SYS-INT-004/007/008/009 and SYS-E2E-001 gaps), and records the gate flipping PASS after this batch landed. This review does not change that gate decision (coverage is out of scope here) but flags that the *quality* of the SYS-INT-007/008 tests specifically needs a follow-up fix.
- **Gate Decision**: [`_bmad-output/test-artifacts/gate-decision.json`](gate-decision.json) — PASS, unaffected by this review's findings (coverage-based, not quality-based).

---

## Next Steps

### Immediate Actions (Before Merge)

1. **Add `stub_profile` to the 3 affected tests in `test_run_service_gate.py`** — Critical Issue #1.
   - Priority: P0 (functionally — closes a live real-network/real-secret exposure)
   - Estimated Effort: ~15 minutes (one fixture-parameter addition × 3 tests)

2. **Trim or split `test_stages.py`** to get back under 300 lines.
   - Priority: P2
   - Estimated Effort: ~10 minutes

### Follow-up Actions (Future PRs)

1. **Audit the 7 pre-existing tests sharing the un-stubbed `env` fixture** in `test_run_service_gate.py` for the same real-network exposure.
   - Priority: P2
   - Target: next test-quality pass

2. **Consolidate the 3 duplicate SSE-recording-registry doubles** into `tests/stubs/fakes.py`; parametrize the two trace-failure tests; centralize `app.state.*` reset into a shared fixture; clear `run_service._bg_tasks` in `api_env` teardown.
   - Priority: P2/P3
   - Target: backlog

### Re-Review Needed?

⚠️ **Re-review after critical fix** — once `stub_profile` is added to the 3 affected tests, a quick re-run of the determinism/isolation/performance checks against just those 3 tests (confirming sub-20ms runtime and zero network calls) would be sufficient; a full re-review of all 14 is not needed.

---

## Decision

**Recommendation**: Request Changes

**Rationale**: 12 of 14 new tests are solid and ship-ready as-is. The 3 tests sharing the real-network root cause are not merge-blocking in the sense of "currently flaky" — they pass reliably today — but they encode a live, silent risk (real API key + real external host reachable from the test suite, one unrelated future change away from real production LLM calls) that is cheap to close now and expensive to discover later (e.g., via an unexpected DeepSeek bill or a CI run that hangs because `langfuse.eli.kr` is temporarily unreachable from a runner). Given the fix is a one-line `stub_profile` addition per test, recommend closing it before merge rather than deferring.

---

## Appendix

### Violation Summary by Location

| File | Line | Severity | Criterion | Issue |
| --- | --- | --- | --- | --- |
| `tests/services/test_run_service_gate.py` | 170/177 | HIGH ×3 (determinism/isolation/performance) | Determinism, Isolation, Performance | Real HTTPS call to `langfuse.eli.kr` via un-stubbed `scenario_node` |
| `tests/services/test_run_service_gate.py` | 216/223 | HIGH ×3 | Determinism, Isolation, Performance | Same root cause, `test_trace_setup_failure_is_non_fatal_and_logged` |
| `tests/services/test_run_service_gate.py` | 230/251 | HIGH ×3 | Determinism, Isolation, Performance | Same root cause, `test_trace_teardown_failure_is_non_fatal_and_logged` |
| `tests/api/test_stages.py` | 303 (EOF) | MEDIUM | Maintainability | File 3 lines over 300-line DoD |
| `tests/services/test_run_service_gate.py` | 216 / 230 | MEDIUM | Maintainability | Near-duplicate trace-failure tests, not parametrized |
| `tests/api/test_e2e_stub_run.py` | 23 | MEDIUM | Maintainability | Duplicate `_RecordingRegistry` (3rd copy in the suite) |
| `tests/stubs/fakes.py` | 1 | MEDIUM | Maintainability | Stale "four seams" docstring |
| `tests/api/test_e2e_stub_run.py` | 39/53-56 | MEDIUM | Isolation | `_bg_tasks` not cleared in teardown |
| `tests/api/test_e2e_stub_run.py` | 42 | MEDIUM | Isolation | `app.state.*` not reset in teardown |
| `tests/api/test_workspace_files.py` | 97 | LOW/MEDIUM | Determinism | Symlink test lacks platform guard |
| `src/yt_flow/services/prompt_service.py` | 23 | LOW | Performance | No explicit client timeout (defense-in-depth only) |
| `tests/api/test_stages.py` | 298 | LOW | Maintainability | Weak assertion (`status_code` only) |
| `tests/services/test_run_service_gate.py` | 231 | LOW | Maintainability | `_RaisingExitClient` placement inconsistency |
| `tests/conftest.py` | 33 | LOW | Maintainability | `# ponytail:` used for bugfix narration, not simplification |

### Note on requested test count

The request cited "15 tests." This review found **14 pytest-collected items** across the 4 files in the current working tree's diff (5 in `test_stages.py` counting parametrization, 4 in `test_workspace_files.py`, 4 in `test_run_service_gate.py`, 1 in `test_e2e_stub_run.py`). The traceability matrix's narrative also references a `test_artifact_downloads_video_mp4_when_complete` regression test in `tests/api/test_runs.py` (for the `output.mp4`→`video.mp4` filename fix found while building SYS-E2E-001) that would bring the count to 15 — but that file has no uncommitted changes and no such test currently exists in it. This is a minor doc-vs-code drift in the traceability matrix's "Update 6" narrative, not a defect in the 14 tests actually reviewed here; flagging it so it doesn't silently under-count coverage on a future trace re-run.

---

## Knowledge Base References

- **test-quality.md** — Definition of Done for tests (no hard waits, ≤300 lines, ≤1.5 min, self-cleaning) — the primary rubric applied throughout this review.
- **test-levels-framework.md** — E2E vs. API vs. Unit appropriateness (used to validate `test_e2e_stub_run.py`'s scope).
- **selective-testing.md** — Duplicate-coverage detection (used for the `_RecordingRegistry` and trace-failure-test findings).

For coverage mapping, consult `_bmad-output/test-artifacts/traceability-matrix.md`.

---

## Review Metadata

**Generated By**: BMad TEA Agent (Test Architect) — Murat
**Workflow**: bmad-testarch-test-review (Create mode)
**Review ID**: test-review-sys-int-004-007-008-009-e2e-001-20260702
**Timestamp**: 2026-07-02
**Execution mode**: subagent (4 parallel quality-dimension workers, cross-validated by independent empirical re-runs)
