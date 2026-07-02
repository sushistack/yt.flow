---
stepsCompleted: ['step-01-load-context', 'step-02-discover-tests', 'step-03-map-criteria', 'step-04-analyze-gaps', 'step-05-gate-decision']
lastStep: 'step-05-gate-decision'
lastSaved: '2026-07-02'
tempCoverageMatrixPath: '/tmp/claude-1000/-mnt-work-projects-yt-flow/870abc91-22d2-464c-bf98-5bdb9c63d8a2/scratchpad/tea-trace-coverage-matrix-2026-07-02.json'
workflowStatus: 'completed'
gateStatus: 'PASS'
coverageBasis: 'acceptance_criteria'
oracleConfidence: 'high'
oracleResolutionMode: 'formal_requirements'
oracleSources:
  - '_bmad-output/test-artifacts/test-design/test-design-qa.md'
  - '_bmad-output/test-artifacts/test-design/test-design-architecture.md'
  - '_bmad-output/implementation-artifacts/sprint-status.yaml'
  - '_bmad-output/implementation-artifacts/deferred-work.md'
externalPointerStatus: 'not_used'
---

# Traceability Matrix — yt.flow: SCP Content Pipeline

**Project:** yt.flow
**Date:** 2026-07-02
**Author:** Murat (TEA) with Jay

---

## Step 1: Coverage Oracle Resolution

**Resolved oracle:** `test-design-qa.md`'s **Test Coverage Plan** (20 scenario groups: SYS-INT-\*, SYS-UNIT-\*, SYS-E2E-\*, SYS-COMP-\*, SYS-OPS-\*), cross-linked to the 10 scored risks (R-001..R-010) in `test-design-architecture.md`.

- **oracleResolutionMode:** `formal_requirements` — a completed BMad `testarch-test-design` workflow output (dated 2026-07-02, `workflowStatus: completed`), not inferred/synthetic.
- **coverageBasis:** `acceptance_criteria` (closest fit — each Test ID carries a requirement statement, priority, risk link, and test level; functions as the AC set for this system-level plan).
- **oracleConfidence:** `high` — Test IDs are enumerated with explicit requirement text, risk linkage, test level, and either a `[verify-existing]` file pointer or an explicit `gap` marker. Both companion docs are dated today and internally consistent (same risk IDs, same B-1/B-2/B-3 decisions).
- **externalPointerStatus:** `not_used` — no placeholder/pointer files to Jira/Linear/Confluence found; this is a solo-operator project tracked entirely in-repo (`_bmad-output/`, `sprint-status.yaml`).

### Artifacts loaded

| Artifact | Role |
|---|---|
| `test-design-qa.md` | Primary oracle — 20 Test IDs, priorities, risk links, `[verify-existing]` pointers |
| `test-design-architecture.md` | Risk detail (R-001..R-010, P×I scores), B-1/B-2/B-3 blocker decisions |
| `sprint-status.yaml` | Confirms all 4 epics / 30 stories are `done` — implementation is complete, so gaps are test-gaps, not feature-gaps |
| `deferred-work.md` | Confirms tracing is now default-OFF in the test suite (`tests/conftest.py`), and that verifying the real `@observe` path for SYS-INT-007 needs `YTFLOW_LANGFUSE_ENABLED=true` set before process start (binds once at import) |

### Pre-check: B-1/B-2/B-3 dependency status (blockers noted in test-design docs)

The test-design docs (dated 2026-07-02) list B-1/B-2/B-3 as "decided, implementation pending." A same-day commit (`dfd35cd 🧹 chore: land B-1/B-2/B-3 test-dev dependencies`) suggests this landed since. Verified directly against source:

| Blocker | Status | Evidence |
|---|---|---|
| **B-1** strict concurrency guard | ✅ Implemented | `run_service.py:39` `_MUTABLE_STATES = frozenset({"awaiting_approval", "failed", "complete"})`; 409 returns at lines 433/440/480 |
| **B-2** stub-profile seam (hybrid) | ✅ Implemented | `tests/conftest.py::stub_profile` fixture (fakes ComfyUI/FFmpeg + monkeypatch); `tests/stubs/fakes.py`; cassettes at `tests/fixtures/cassettes/{deepseek_scenario,qwen_tts}.json` |
| **B-3** Langfuse kill-switch | ✅ Implemented | `src/yt_flow/observability.py:65` reads `YTFLOW_LANGFUSE_ENABLED` (default true); test suite sets it OFF by default per `deferred-work.md` |

This unblocks SYS-INT-004, SYS-E2E-001, and SYS-INT-007 for coverage discovery in Step 2 — none of the three are structurally blocked anymore; remaining gaps are test-authoring gaps only.

**Next:** Step 2 — Discover Tests (map existing ~50 test files against the 20 Test IDs, confirm `[verify-existing]` pointers, and identify literal gaps).

---

## Step 2: Test Discovery & Catalog

**Test dir:** `tests/` (backend, pytest, 33 files) + `frontend/src/**/*.test.{ts,tsx}` (frontend, Vitest, 16 files). No dedicated `e2e/` directory — E2E is a pytest-level stub-profile suite per architecture decision (no k6/Playwright layer built yet).

Discovery method: matched each of the 20 Test IDs in `test-design-qa.md` against its named `[verify-existing]` file(s) or `gap` marker, read the actual test bodies (not just filenames), and corrected the oracle's coverage claims where the code disagreed with the doc.

### Catalog by scenario group (oracle altitude — matches test-design-qa.md granularity)

| Test ID | Level | File(s) | Test count | Oracle claim | Actual finding |
|---|---|---|---|---|---|
| SYS-INT-001 | INT | `tests/pipeline/test_gates.py`, `tests/api/test_gate.py` | 8 + ~10 | verify-existing | ✅ Confirmed — approve/reject/gate-writer-sole-owner sequences present |
| SYS-INT-002 | INT | `tests/services/test_run_service_resume.py` | 6 | verify-existing | ✅ Confirmed — node-level resume tested |
| SYS-INT-003 | INT | `tests/api/test_stages.py`, `test_stage_artifacts.py` | 12+ | verify-existing | ✅ Confirmed — retry nullify + PATCH edit + reset-gate sequences present |
| **SYS-INT-004** | INT | — | 0 | gap (B-1 decided) | ⚠️ **Still a real gap.** B-1 guard *is implemented* (`run_service.py:431,478`, `_MUTABLE_STATES` check in `retry_stage`/`edit_artifact`), but existing 409 tests in `test_stages.py` only cover gate-state conflicts (pending/absent gate), never `run.status == "running"`. No test drives a run into `running` and asserts retry/PATCH → 409 + checkpoint untouched. |
| SYS-E2E-001 | E2E | `tests/pipeline/test_stub_profile_smoke.py` | 2 | gap (B-2 decided) | ⚠️ **Still a real gap.** The B-2 smoke test drives `run_service` directly (not via FastAPI), asserts terminal `complete` status and a video artifact — but its own docstring says "SYS-E2E-001's full 5×-approve content assertions are QA's downstream task." No `POST /runs` → SSE-observed → 5-gate-approve → artifacts-on-disk test exists yet. |
| SYS-UNIT-001 | UNIT | `tests/pipeline/nodes/test_scenario.py` (15), `test_image.py` (24) | 39 | partial — extend | ✅ Strong — malformed JSON, None camera fields, empty shots covered extensively |
| SYS-INT-005 | INT | `tests/services/test_run_service_gate.py` | ~15 | verify-existing | ✅ Confirmed — `run_failed` SSE emission + DB-after-checkpoint tested |
| SYS-INT-006 | INT | `tests/api/test_sse.py` | 13 | verify-existing | ✅ Confirmed — `gate_pending`, `stage_entry/exit` order, queue cleanup, disconnect all covered |
| SYS-UNIT-002 | UNIT | `test_comfyui_client.py` (9), `nodes/test_tts.py` (14) | 23 | partial — extend | ✅ Confirmed — node-error body, HTTP 400, timeout+retry, Qwen timings covered |
| **SYS-INT-007** | INT | — | 0 | gap (B-3 decided) | ⚠️ **Still a real gap** for the pipeline `@observe` path. B-3 flag exists (`observability.py:65`) and IS exercised for degradation in `test_eval_service.py` (`test_evaluate_ab_langfuse_failure_non_fatal`, `test_store_results_langfuse_failure_non_fatal`) — but that's the **evaluation service**, not the pipeline stage nodes AD-10 targets. No test forces a Langfuse client exception during a pipeline stage and asserts the stage still completes. Per `deferred-work.md`, this needs a subprocess/re-import harness since the flag binds once at import — plain monkeypatch won't work. |
| **SYS-INT-008** | INT | — | 0 | gap | ⚠️ Confirmed gap — no test asserts a failed node's trace payload carries stage/inputs/exception (FR-13). |
| **SYS-INT-009** | INT | `tests/api/test_workspace_files.py` | 3 | **verify-existing (doc claim is WRONG)** | ❌ **Contradicts oracle.** File has only 3 tests: serves-artifact-200, missing-404, creates-dir-when-absent. **Zero tests for `../`, absolute paths, or symlink escape** — the exact negatives SYS-INT-009 requires. Underlying `mount_workspace_files` likely inherits Starlette `StaticFiles`' built-in traversal guard, but this is unverified by any test. Reclassify as **gap**, not verify-existing. |
| SYS-UNIT-003 | UNIT | `test_eval_service.py` (39), `test_ab_run.py` (6) | 45 | verify-existing | ✅ Strong — majority/tiebreak/floor/tie/malformed-judge-output all covered explicitly |
| SYS-COMP-001 | COMP | `frontend/src/pages/RunDetail.test.tsx` | ~10+ | verify-existing | ✅ Confirmed — SSE reconnect (run-id change closes old stream), gate control aria-disabled per stage, EventSource cleanup on unmount |
| SYS-INT-010 | INT | `test_stage_artifacts.py` | (shared w/ SYS-INT-003) | verify-existing | ✅ Confirmed — reads state from LangGraph checkpoint not DB |
| SYS-INT-011 | INT | `test_scps.py` (2), `test_ab_run.py` (6) | 8 | verify-existing | ✅ Confirmed — `ab_pair_id`/variant-B linkage tested in `test_ab_run.py`; `test_scps.py` is thin (2 tests) but covers the documented scope |
| SYS-E2E-002 | E2E | `e2e/dashboard-run-gate-artifacts.spec.ts` | 1 | built | ✅ Built (2026-07-02, `bmad-qa-generate-e2e-tests`) — Playwright journey against the stub-profile server: dashboard → SCP search/select → create run → SSE-observed gate_pending per stage → approve all 5 gates → per-stage artifact panel (text/images/audio/subtitle/video) → completion verified via `GET /runs/{id}`. Found and documented (not fixed, out of scope for this skill) two real gaps: no SSE event for the run→`complete` transition, and no SPA history-fallback for direct navigation to `/app/runs/{id}`. |
| **SYS-INT-012** | INT | — | 0 | gap | ⚠️ **Deeper than a test gap.** `src/yt_flow/db/__init__.py` uses `SQLModel.metadata.create_all(_engine)` — there is **no Alembic setup in this project at all** (no `alembic/` dir, no `alembic.ini`; `alembic` only present as a transitive venv dependency). "Alembic migration roundtrip" cannot be tested because the migration tooling doesn't exist yet. This is a scoping question for Dev/Architecture, not a QA backlog item. |
| SYS-OPS-001 | manual | — | — | runbook, P3 | Manual runbook, not automatable — no gap by definition |
| SYS-OPS-002 | manual | — | — | runbook, P3 | Manual runbook, not automatable — no gap by definition |

### Coverage heuristics inventory

**API endpoint coverage** — all REST endpoints referenced in the PRD (FR-24–34) have at least one direct API test (`tests/api/*`); no orphan endpoints found.

**Auth/authz coverage** — N/A by design (no auth, local-only, PRD-accepted trade-off). No negative-path gap here.

**Error-path coverage** — strong at the unit/pipeline level (scenario/image malformed-input fixtures, ComfyUI/DeepSeek/Qwen client error branches, eval-service Langfuse-failure branches). Weak at two specific seams: workspace file traversal (SYS-INT-009) and pipeline-stage Langfuse degradation (SYS-INT-007) — both flagged above.

**UI journey / state coverage** — `RunDetail.test.tsx` covers loading/gate/disabled states and SSE reconnect; frontend suite (16 files) has no dedicated empty-state or permission-denied assertions, but none are required (no auth, and empty-state is low-risk per architecture doc's "Accepted Trade-offs").

**Priority-tagging infrastructure** — Appendix A of `test-design-qa.md` documents a `@pytest.mark.p0`-style tagging convention for selective execution, but **no test in the suite currently uses these markers** (`grep` for `pytest.mark.p[0-3]` returns zero hits). Exit Criteria ("P0 100%, P1 ≥95%") can only be evaluated today by manually bucketing Test IDs against this matrix — there's no automated `pytest -m p0` filter. Not a coverage gap per se, but a CI/reporting gap worth flagging to Step 5.

**Next:** Step 3 — Map Criteria (build the bidirectional Test ID ↔ test-file matrix and compute pass-rate/coverage percentages).

---

## Step 3: Coverage Matrix (Oracle Item → Coverage Status)

**Status legend:** FULL (happy + error paths covered) · PARTIAL (happy path only, or wrong layer) · NONE (no test) · N/A (manual runbook or explicitly optional, not a gap)

| Test ID | Priority | Risk | Level | Status | Evidence |
|---|---|---|---|---|---|
| SYS-INT-001 | P0 | R-001 (6) | INT | **FULL** | `test_gates.py` + `test_gate.py` |
| SYS-INT-002 | P0 | R-001 (6) | INT | **FULL** | `test_run_service_resume.py` |
| SYS-INT-003 | P0 | R-001 (6) | INT | **FULL** | `test_stages.py`, `test_stage_artifacts.py` |
| **SYS-INT-004** | **P0** | R-009 (6) | INT | **NONE** | Guard code exists (`run_service.py:431,478`); zero tests drive `status=running` → 409 |
| SYS-E2E-001 | P0 | R-005 (6) | E2E | **PARTIAL** | `test_stub_profile_smoke.py` proves the seam only (integration-level, direct `run_service` calls) — no API-layer, SSE-observed, 5-gate full run |
| SYS-UNIT-001 | P0 | R-003 (6) | UNIT | **FULL** | `test_scenario.py`, `test_image.py` — malformed/adversarial fixtures present |
| SYS-INT-005 | P1 | R-002 (4) | INT | **FULL** | `test_run_service_gate.py` |
| SYS-INT-006 | P1 | R-008 (4) | INT | **FULL** | `test_sse.py` |
| SYS-UNIT-002 | P1 | R-003 (6) | UNIT | **FULL** | `test_comfyui_client.py`, `nodes/test_tts.py` |
| **SYS-INT-007** | **P1** | R-004 (4) | INT | **NONE** | B-3 flag exists and is exercised in `test_eval_service.py` (adjacent, evaluation path only) — the pipeline-stage AD-10 degradation path has zero direct coverage |
| **SYS-INT-008** | **P1** | — | INT | **NONE** | No test on failed-node trace payload content (stage/inputs/exception) |
| **SYS-INT-009** | **P1** | R-006 (4) SEC | INT | **NONE** | Oracle claimed `[verify-existing]`; actual file has 0 traversal/absolute-path/symlink tests — **oracle correction applied** |
| SYS-UNIT-003 | P1 | R-007 (4) | UNIT | **FULL** | `test_eval_service.py`, `test_ab_run.py` |
| SYS-COMP-001 | P1 | R-008 (4) | COMP | **FULL** | `RunDetail.test.tsx` |
| SYS-INT-010 | P2 | — | INT | **FULL** | `test_stage_artifacts.py` |
| SYS-INT-011 | P2 | — | INT | **FULL** | `test_scps.py`, `test_ab_run.py` |
| SYS-E2E-002 | P2 | R-005 | E2E | **FULL** | `e2e/dashboard-run-gate-artifacts.spec.ts` (built 2026-07-02) |
| SYS-INT-012 | P2 | — | INT | **NONE (blocked)** | Not a test-authoring gap — no Alembic migration tooling exists in the codebase to test |
| SYS-OPS-001 | P3 | R-004 | manual | N/A | Runbook, not automated by design |
| SYS-OPS-002 | P3 | R-005 | manual | N/A | Runbook, not automated by design |

### Coverage validation against rules (per `risk-governance.md` / `probability-impact.md`)

Applying "P0/P1 items must have coverage" and "items are not happy-path-only when the oracle implies error handling":

- ❌ **P0 violation:** SYS-INT-004 — score-6 risk (R-009, concurrent mutation) with zero coverage despite the mitigating code already existing. Cheapest gap to close (guard is written; only the test is missing).
- ⚠️ **P0 borderline:** SYS-E2E-001 — score-6 risk (R-005) only integration-smoke covered, not the full E2E contract the oracle specifies.
- ❌ **P1 violations:** SYS-INT-007, SYS-INT-008, SYS-INT-009 — three P1 items with zero direct coverage. SYS-INT-009 is the most concerning: it is a **security-negative-path item (R-006)** that the source oracle incorrectly believed was already covered — without this trace exercise, that false confidence would have persisted.
- ✅ No duplicate/redundant coverage found across levels.
- ✅ No auth/authz items apply (N/A by design).
- N/A: no synthetic UI journeys in this oracle (formal test-design based).

**Next:** Step 4 — Analyze Gaps (severity-rank the 4 confirmed NONE/PARTIAL P0/P1 items + the 2 P2/N/A structural findings, and produce remediation guidance).

---

## Step 4: Gap Analysis & Coverage Statistics (Phase 1 Complete)

**Execution mode:** sequential (no subagent/agent-team orchestration needed at this scale — 20 oracle items, single-session analysis was sufficient and cheaper than fan-out).

### Coverage Statistics

| Priority | Total | Fully Covered | Partial | Uncovered | N/A (by design) | % (FULL/total) |
|---|---|---|---|---|---|---|
| P0 | 6 | 4 | 1 (SYS-E2E-001) | 1 (SYS-INT-004) | 0 | **67%** |
| P1 | 8 | 5 | 0 | 3 (SYS-INT-007/008/009) | 0 | **63%** |
| P2 | 4 | 3 | 0 | 1 (SYS-INT-012) | 0 | **75%** |
| P3 | 2 | 0 | 0 | 0 | 2 (manual runbooks) | 0%* |
| **Total** | **20** | **12** | **1** | **5** | **2** | **60%** overall |

\* P3 percentage is misleading in isolation — both "uncovered" slots are N/A by explicit design (manual runbooks OPS-001/002), not real gaps. Real, actionable gap count is **5** (1×P0, 3×P1, 1×P2). SYS-E2E-002 moved from N/A to FULL on 2026-07-02 (`bmad-qa-generate-e2e-tests` built it); stats above reflect that.

### Gap Analysis (ranked by risk score, matches `probability-impact.md` MITIGATE/BLOCK thresholds)

| Rank | Test ID | Priority | Risk score | Gap type | Why it matters |
|---|---|---|---|---|---|
| 1 | **SYS-INT-004** | P0 | 6 (MITIGATE) | Critical gap | Guard code (`_MUTABLE_STATES`) is already shipped and correct-looking, but nothing proves it. If a future refactor breaks the check silently, no test fails — the exact regression class R-009 exists to prevent. **Cheapest fix on this list**: guard is written, only the test is missing (~1-2 tests, no new code). |
| 2 | **SYS-INT-009** | P1 | 4 (MITIGATE) | Corrected gap | Security-negative gap the test-design doc believed was already closed. `mount_workspace_files` likely relies on Starlette's built-in traversal protection, but that's an assumption, not a verified fact — and it's the *one* place in this local-only, no-auth app where the file system is exposed to a client-controllable path. |
| 3 | **SYS-INT-007** | P1 | 4 (MITIGATE) | Gap | AD-10's core promise ("Langfuse down ⇒ pipeline unaffected") is unverified at the layer it actually matters (pipeline stage nodes) — only the adjacent eval-service path is tested. Per `deferred-work.md`, this needs a subprocess/re-import harness since the flag binds once at import; that harness doesn't exist yet either. |
| 4 | **SYS-E2E-001** | P0 | 6 (MITIGATE) | Partial | The one test standing between "the graph completes" and "the product actually works end-to-end" is a direct-call smoke test, not the real HTTP/SSE contract. Its own docstring defers the real assertions to this trace's scope. |
| 5 | **SYS-INT-008** | P1 | — | Gap | Lower urgency than the above three — FR-13 error-visibility is a diagnosability nice-to-have, not a correctness/security risk. |
| 6 | **SYS-INT-012** | P2 | — | Structural, not test gap | Not actionable as a QA task — no Alembic tooling exists to write a roundtrip test against. Needs a Dev/Architecture decision (adopt Alembic, or drop the requirement) before any test can be written. |

### Coverage Heuristics Summary

- Endpoint gaps: **0** — every FR-24–34 endpoint has direct API test coverage
- Auth/authz negative-path gaps: **0** — N/A by design (no auth)
- Happy-path-only criteria: **3** (SYS-INT-007, 008, 009) — all three are error/degradation/security paths with zero negative-path assertions
- UI journey/state gaps: **0** — `RunDetail.test.tsx` covers the state machine the frontend exposes

### Recommendations

| Priority | Action | Test IDs |
|---|---|---|
| URGENT | Write the SYS-INT-004 concurrency-guard test (`status=running` → 409, checkpoint byte-identical) for both `retry_stage` and `edit_artifact` | SYS-INT-004 |
| HIGH | Add the 3 missing P1 tests: pipeline-stage Langfuse-raises degradation (needs re-import/subprocess harness), failed-node trace-payload assertions, and `/files` path-traversal negatives | SYS-INT-007, SYS-INT-008, SYS-INT-009 |
| MEDIUM | Upgrade SYS-E2E-001 to a real API-driven E2E: `POST /runs` → SSE-observed → approve ×5 → assert artifacts on disk | SYS-E2E-001 |
| MEDIUM | Take SYS-INT-012 back to Dev/Architecture — decide whether Alembic is adopted or the requirement is dropped; it cannot be tested as currently written | SYS-INT-012 |
| LOW | Wire up the `@pytest.mark.p0`–`p3` convention already documented in Appendix A so Exit Criteria (P0 100%, P1 ≥95%) can be checked by `pytest -m p0` instead of manual bucketing against this matrix | — (infra) |

**Phase 1 coverage matrix persisted to:** `/tmp/claude-1000/-mnt-work-projects-yt-flow/870abc91-22d2-464c-bf98-5bdb9c63d8a2/scratchpad/tea-trace-coverage-matrix-2026-07-02.json`

---

## Step 5: Gate Decision (Phase 2)

**Gate eligibility:** `allow_gate=true`, `collection_status=COLLECTED` → **gate-eligible**.

**Decision tree evaluation (deterministic, per `risk-governance.md` thresholds):**

- Rule 1 — P0 coverage must be 100%: **actual 67%** → **FAIL** (stops here; rules 2-5 not reached)

### 🚨 GATE DECISION: **FAIL**

**Rationale:** P0 coverage is 67% (required: 100%). 1 critical requirement is uncovered (SYS-INT-004 — concurrency guard, R-009 score 6). Overall coverage is 55% (minimum: 80%) and P1 coverage is 63% (minimum: 80%) would also independently fail once P0 is resolved — this is not a borderline call.

| Gate criterion | Required | Actual | Status |
|---|---|---|---|
| P0 coverage | 100% | 67% | ❌ NOT_MET |
| P1 coverage | 90% target / 80% min | 63% | ❌ NOT_MET |
| Overall coverage | 80% min | 55% | ❌ NOT_MET |

**Critical gaps blocking the gate:** 1 (SYS-INT-004)
**High gaps to clear before re-trace:** 3 (SYS-INT-007, SYS-INT-008, SYS-INT-009)

### Reading this FAIL correctly

This is **not** a signal that yt.flow is broadly under-tested — 11 of 20 scenario groups are fully, explicitly covered, including the highest-complexity ones (A/B verdict logic: 45 tests; LLM output hardening: 39 tests; SSE lifecycle: 13 tests). The FAIL is driven by a small, well-defined punch list:

1. **1 test-authoring gap** where the production code is already correct (SYS-INT-004) — lowest-effort item on this entire report.
2. **3 P1 gaps**, one of which (SYS-INT-009) is a corrected false-positive in the source test-design doc — genuinely useful to have caught before it shipped as "verified."
3. **1 structural, non-QA gap** (SYS-INT-012) that needs a Dev/Architecture scoping decision, not a test.
4. **1 partial** (SYS-E2E-001) where the seam is proven but the full contract isn't.

Closing items 1–3 (5 tests, ~1 architecture conversation) would bring P0 to 100% and P1 to ~88-100%, very plausibly flipping the gate to PASS or CONCERNS on re-trace. This is a small, closeable list, not a systemic quality problem — treat it as a sprint task, not a re-architecture.

### Machine-readable outputs

- `_bmad-output/test-artifacts/e2e-trace-summary.json` — full CI/CD-consumable summary
- `_bmad-output/test-artifacts/gate-decision.json` — slim gate signal for pipeline enforcement

### Recommended next actions (in order)

1. Write the SYS-INT-004 concurrency-guard test — smallest, highest-leverage fix
2. Add SYS-INT-009 path-traversal negatives — closes the corrected security gap
3. Add SYS-INT-008 trace-payload assertions
4. Build the SYS-INT-007 pipeline-degradation test (needs the subprocess/re-import harness noted in `deferred-work.md`)
5. Take SYS-INT-012 to a Dev/Architecture conversation (Alembic: adopt or drop)
6. Re-run `/bmad-testarch-trace` after the above land — expect PASS or CONCERNS

---

**Workflow complete.** Full report: `_bmad-output/test-artifacts/traceability-matrix.md`

---

## Post-Trace Remediation Update (2026-07-02)

**SYS-INT-004 closed.** Added `test_retry_while_running_returns_409_and_leaves_checkpoint_untouched`, `test_edit_while_running_returns_409_and_leaves_checkpoint_untouched`, and `test_edit_allowed_when_run_settled` (positive control for `awaiting_approval`/`failed`/`complete`) to `tests/api/test_stages.py`. Full suite re-run: **460 passed, 1 skipped, 0 failed** — no regressions.

**Revised coverage after this fix:**

| Priority | Total | Fully Covered | Partial | Uncovered | % |
|---|---|---|---|---|---|
| P0 | 6 | **5** (was 4) | 1 (SYS-E2E-001) | 0 (was 1) | **83%** (was 67%) |
| P1 | 8 | 5 | 0 | 3 | 63% (unchanged) |
| Overall | 20 | **12** (was 11) | 1 | 4 (was 5) | **60%** (was 55%) |

**Gate re-evaluation:** Rule 1 (P0 must be 100%) — actual **83%** → **still FAIL**, but the sole remaining P0 blocker is now SYS-E2E-001 (PARTIAL, not NONE). SYS-INT-004 is fully resolved and off the punch list.

**Remaining punch list to reach PASS/CONCERNS**, in order:
1. SYS-E2E-001 — upgrade seam-smoke to full API-driven E2E (last P0 item)
2. SYS-INT-009 — path-traversal negative tests (P1, corrected security gap)
3. SYS-INT-008 — failed-node trace-payload assertions (P1)
4. SYS-INT-007 — pipeline-stage Langfuse-degradation test, needs subprocess/re-import harness (P1)
5. SYS-INT-012 — Dev/Architecture scoping conversation on Alembic (P2, not a test task)

`e2e-trace-summary.json` and `gate-decision.json` were **not** regenerated for this partial fix — they remain the point-in-time record of the original trace. Re-run `/bmad-testarch-trace` after the remaining P1 items land to get a fresh machine-readable gate signal.

### Update 2: SYS-INT-009 closed

Added 4 tests to `tests/api/test_workspace_files.py`: literal `..` traversal, URL-encoded `%2e%2e` traversal (survives client-side normalization, unlike a literal `..`), encoded absolute path (`%2fetc%2fpasswd`), and symlink escape (`evil_link.txt` → file outside workspace). All assert `404`.

**Finding confirmed, not just assumed:** Starlette's `StaticFiles.lookup_path` (v1.3.1, installed) already rejects absolute paths outright and checks `os.path.commonpath([realpath(joined), realpath(directory)])` after resolving symlinks (`follow_symlink=False` default) — so `mount_workspace_files`'s `# ponytail: whole-workspace mount is fine...` comment was correct that no extra guard code was needed. The gap was purely the missing verification, not missing production code. Full suite re-run: **464 passed, 1 skipped, 0 failed.**

**Revised coverage:**

| Priority | Total | Fully Covered | Partial | Uncovered | % |
|---|---|---|---|---|---|
| P0 | 6 | 5 | 1 (SYS-E2E-001) | 0 | 83% |
| P1 | 8 | **6** (was 5) | 0 | **2** (was 3) | **75%** (was 63%) |
| Overall | 20 | **13** (was 12) | 1 | **3** (was 4) | **65%** (was 60%) |

**Gate re-evaluation:** Rule 1 (P0 must be 100%) — actual 83% → **still FAIL** (SYS-E2E-001 is the sole blocker). Once that lands, Rule 3 would trigger next: P1 at 75% is still below the 80% minimum, so even a full P0 fix wouldn't reach PASS/CONCERNS until at least one more P1 item (SYS-INT-007 or SYS-INT-008) also closes — 75% → 6/8; closing one more brings P1 to 7/8 = 88% (CONCERNS-eligible), closing both reaches 100% (PASS-eligible, pending overall ≥80%).

**Remaining punch list:**
1. SYS-E2E-001 (P0) — upgrade seam-smoke to full API-driven E2E
2. SYS-INT-008 (P1) — failed-node trace-payload assertions
3. SYS-INT-007 (P1) — pipeline-stage Langfuse-degradation test (needs subprocess/re-import harness)
4. SYS-INT-012 (P2) — Dev/Architecture scoping conversation on Alembic, not a test task

### Update 3: SYS-INT-008 closed — required a real product fix, not just a test

Unlike SYS-INT-004/009, this one was a genuine gap in production code, not just missing coverage. Investigation found `run_service.py`'s generic-exception handler (`_run()`, was line 301-304) hardcoded `"stage": "unknown"` for every node failure — FR-13 explicitly requires the failed node's stage to be surfaced, and it wasn't, ever.

**Root cause & fix:** LangGraph attaches `During task with name '<node>' and id '<uuid>'` as a PEP 678 exception note (`__notes__`) when a node raises inside `astream()` — confirmed empirically against the installed LangGraph version by forcing a node to raise mid-graph and inspecting the resulting exception. Added `_stage_from_exception()` (regex-parses the note, falls back to `"unknown"` if absent) and wired it into `_run()`'s except handler so both `run.current_stage` (DB) and the `run_failed` SSE event's `stage` field now report the actual failing node instead of a constant.

**Tests added** (`tests/services/test_run_service_gate.py`): `test_node_failure_surfaces_failing_stage_in_trace_payload` (forces an `image`-node failure via a synthetic exception note, asserts `run.current_stage == "image"` and the SSE event's `stage` field — both would have read `"unknown"` before this fix) and `test_stage_from_exception_falls_back_to_unknown_without_notes` (regression guard for exceptions without LangGraph notes). Full suite re-run: **466 passed, 1 skipped, 0 failed.**

**Scope note on FR-13's other half ("inputs at failure point"):** stage nodes are already `@observe`-decorated (Langfuse SDK), which captures function inputs/exceptions into the trace automatically when tracing is enabled — that's vendor behavior, not project code, so it's out of scope to test here. The DB/SSE-level "stage" surfacing above was the part actually owned (and broken) by this codebase.

**Revised coverage:**

| Priority | Total | Fully Covered | Partial | Uncovered | % |
|---|---|---|---|---|---|
| P0 | 6 | 5 | 1 (SYS-E2E-001) | 0 | 83% |
| P1 | 8 | **7** (was 6) | 0 | **1** (was 2, SYS-INT-007 only) | **88%** (was 75%) |
| Overall | 20 | **14** (was 13) | 1 | **2** (was 3) | **70%** (was 65%) |

**Gate re-evaluation:** P0 still 83% (SYS-E2E-001 blocks Rule 1) → **still FAIL**. But P1 has now crossed the 80% minimum (88%) — once SYS-E2E-001 closes, the gate would very plausibly land on **CONCERNS** (P1 at 88%, just short of the 90% PASS target) rather than FAIL, assuming overall coverage also clears 80% (currently 70%, needs SYS-INT-007 or SYS-INT-012 to close too).

**Remaining punch list:**
1. SYS-E2E-001 (P0) — upgrade seam-smoke to full API-driven E2E — **last P0 blocker**
2. SYS-INT-007 (P1) — pipeline-stage Langfuse-degradation test (needs subprocess/re-import harness) — **last P1 gap**
3. SYS-INT-012 (P2) — Dev/Architecture scoping conversation on Alembic, not a test task

### Update 4: SYS-INT-007 closed — also a real (small) fix, not just a test

Same pattern as SYS-INT-008: writing the test first exposed that `_trace_cm()`'s two `except Exception: ...` blocks (Langfuse span setup and teardown) were completely silent — no `logger` call anywhere in `run_service.py`. AD-10 explicitly requires "log the error and continue," and only the "continue" half was implemented.

**Fix:** added `logger = logging.getLogger(__name__)` (matching the existing convention in `eval_service.py`) and a `logger.warning(..., exc_info=True)` call in both the setup and teardown except-blocks of `_trace_cm()`.

**Scope decision:** tested at the `get_client()`/`_trace_cm()` seam (monkeypatching `run_service.get_client` to return a client whose `start_as_current_observation`/`span.__exit__` raises) rather than via the subprocess/re-import harness `deferred-work.md` flagged as necessary for exercising the *real* `langfuse.observe` decorator with `YTFLOW_LANGFUSE_ENABLED=true`. AD-10's actual requirement is about this project's own wrapper code being resilient and logging — that's now proven and fixed. Whether the vendor SDK's own `@observe` internals swallow-and-log network failures is vendor behavior, out of this project's test scope (same reasoning applied to SYS-INT-008's "inputs" half).

**Tests added:** `test_trace_setup_failure_is_non_fatal_and_logged`, `test_trace_teardown_failure_is_non_fatal_and_logged` — both assert the run still reaches `awaiting_approval` (pipeline unaffected) and a WARNING-level log record mentioning "Langfuse" was emitted (would have failed pre-fix: zero log records existed). Full suite re-run: **468 passed, 1 skipped, 0 failed.**

**Revised coverage — P1 is now fully closed:**

| Priority | Total | Fully Covered | Partial | Uncovered | % |
|---|---|---|---|---|---|
| P0 | 6 | 5 | 1 (SYS-E2E-001) | 0 | 83% |
| P1 | 8 | **8** (was 7) | 0 | **0** (was 1) | **100%** (was 88%) |
| Overall | 20 | **15** (was 14) | 1 | 1 (SYS-INT-012, structural) | **75%** (was 70%) |

**Gate re-evaluation:** P0 still 83% → **still FAIL** (SYS-E2E-001 is now the *only* remaining blocker of any kind, besides the structural SYS-INT-012). Once SYS-E2E-001 closes: P0→100%, P1 stays 100% (≥90% target) → **Rule 4 (PASS)** would fire, provided overall coverage also clears the 80% minimum. Closing SYS-E2E-001 alone brings overall to 16/20 = **80%** — exactly at the minimum. **This is now the single test standing between this trace and a PASS gate.**

**Remaining punch list:**
1. SYS-E2E-001 (P0) — upgrade seam-smoke to full API-driven E2E — **only remaining blocker**
2. SYS-INT-012 (P2) — Dev/Architecture scoping conversation on Alembic, not a test task (does not block the gate math above — P2 items aren't in the P0/P1 gate rules)

### Update 5: SYS-INT-004 discovery-phase correction

While building SYS-E2E-001 (below), reading `tests/api/test_runs.py` in full surfaced a "B-1 — strict run.status guard on retry / edit-artifact (R-009 concurrency)" test section (`test_retry_while_in_progress_returns_409`, `test_edit_artifact_while_in_progress_returns_409`, `test_retry_settled_status_passes_run_guard`) that **predates this session** (landed in commit `dfd35cd`, the HEAD commit when this trace started). Step 2's original discovery only grepped `tests/api/test_stages.py` for the retry/edit 409 scenarios and missed this sibling file — SYS-INT-004 was never actually a coverage gap.

The tests added earlier in this trace (`tests/api/test_stages.py::test_retry_while_running_returns_409_and_leaves_checkpoint_untouched` etc.) are not wasted — they additionally assert the checkpoint itself is untouched (`FakeGraph.updates == []`), which `test_runs.py`'s HTTP-status-only assertions cannot prove — but they are acknowledged duplicate coverage of the same guard, kept for the extra rigor on a P0-risk item rather than deleted. Noted here for the record; does not change any coverage numbers (SYS-INT-004 was already correctly counted as FULL after Update 1).

**Process lesson:** when a Test ID's `[verify-existing]` pointer names one file, still grep sibling files in the same directory before concluding a scenario is a gap — retry/edit-artifact guard tests turned out to live in `test_runs.py`, not `test_stages.py`, despite the latter owning the retry/edit *feature* tests generally.

### Update 6: SYS-E2E-001 closed — uncovered a critical, previously-undetected production bug

This is the most significant finding of the entire trace, and it is exactly the class of bug SYS-E2E-001 exists to catch.

**What broke:** `src/yt_flow/pipeline/nodes/__init__.py` still wired the **Story 1.4 stub functions** into `STAGE_NODES` for `scenario`/`image`/`tts`/`subtitle` — literally `{"current_stage": stage}` no-ops — even though all four stages were fully implemented and individually unit-tested in stories 1.5–1.8 (all marked `done` in `sprint-status.yaml`, and covered by 39/24/14/many unit tests respectively, which is exactly why SYS-UNIT-001/002 showed FULL coverage). **The compiled pipeline graph never called any of the real implementations.** Every real run of yt.flow — not just tests — would produce zero scenes at the scenario stage and fail with "no scenes to render" at the video stage. The individually-excellent unit-test coverage created false confidence: each real node function worked perfectly in isolation, but the graph wiring connecting them to the actual product was never updated after the stub-to-real migration.

No existing test caught this because:
- Unit tests (`tests/pipeline/nodes/test_*.py`) call the real node functions directly, bypassing `STAGE_NODES` entirely.
- `tests/pipeline/test_stub_profile_smoke.py`'s "full run" test only asserted `run.status == "complete"`, never that any scenes/files were actually produced — the graph reaches `complete` regardless, because every node (including the stubs) swallows its own errors into `PipelineState.error` and returns normally (AD-10's error-isolation design, correctly implemented, but it meant a completely non-functional stage could never fail the graph outright).
- `tests/pipeline/test_graph.py::test_stub_stage_nodes_return_current_stage_without_mutating_input` actively *asserted* the stub behavior was still in place — a Story 1.4 test that was never updated when stories 1.5–1.8 landed, so it stayed green while encoding the wrong expectation. Removed as part of this fix (stubs no longer exist for these stages).

**Fix:** rewrote `pipeline/nodes/__init__.py` to import and wire `scenario_node`, `image_node`, `tts_node`, `subtitle_node` (all already-implemented, already-tested real functions) alongside the already-correctly-wired `video_node`.

**Second bug found in the same investigation:** `GET /runs/{id}/artifact` (video download, FR-26) looked for `output.mp4`, but `video_node` — and every other consumer (`ArtifactPanel.tsx`, its tests, the `/files` static mount, `test_video.py`) — has always used `video.mp4`. This endpoint 404'd unconditionally for every completed run. Fixed the one-line filename mismatch in `src/yt_flow/api/routes/runs.py` and added a dedicated regression test (`test_artifact_downloads_video_mp4_when_complete` in `tests/api/test_runs.py`) since the only existing coverage was the 404-when-incomplete path.

**Third fix (test infrastructure):** the `stub_profile` fixture's "four seams" (DeepSeek, Qwen, ComfyUI, ffmpeg) missed a fifth real network dependency — `scenario_node` fetches its prompt template from the Langfuse Prompt Hub *before* ever reaching the (already-stubbed) DeepSeek call. Without a reachable Langfuse server, this failed into `PipelineState.error` silently (AD-10 again) rather than a loud test failure. Added `fake_get_prompt`/`_FakePrompt` to `tests/stubs/fakes.py` and wired it into `stub_profile` — this is what makes SYS-E2E-001 (and the underlying B-2 smoke test) *genuinely* offline/CI-runnable, closing R-005 for real.

**New test:** `tests/api/test_e2e_stub_run.py::test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk` — drives the actual product contract (`POST /runs` → SSE-order-verified → 5× real gate approvals over HTTP → `GET .../artifact` returns the real `video.mp4`) with zero real network/subprocess calls. This is the test that caught both bugs above; it would have failed loudly against the pre-fix code (0 scenes, empty workspace, 404 on artifact download).

Full suite re-run after all three fixes: **468 passed, 1 skipped, 0 failed** (backend) + **94 passed** (frontend, unaffected — confirms the bug was pipeline-only, not surfaced through any frontend contract test).

**Final coverage — gate flips to PASS:**

| Priority | Total | Fully Covered | Partial | Uncovered | % |
|---|---|---|---|---|---|
| P0 | 6 | **6** (was 5) | 0 (was 1) | 0 | **100%** (was 83%) |
| P1 | 8 | 8 | 0 | 0 | 100% |
| Overall | 20 | **16** (was 15) | 0 | 1 (SYS-INT-012, structural) | **80%** |

**Final gate re-evaluation:**
- Rule 1 (P0 = 100%): **MET** (100%)
- Rule 2 (overall ≥ 80%): **MET** (exactly 80%)
- Rule 3 (P1 ≥ 80%): N/A, superseded by Rule 4
- Rule 4 (P1 ≥ 90% target): **MET** (100%) → **PASS**

### 🎉 REVISED GATE DECISION: **PASS**

**Rationale:** P0 coverage is 100% (6/6). P1 coverage is 100% (8/8, exceeds the 90% PASS target). Overall coverage is 80% (exactly meets the minimum). The one remaining uncovered item, SYS-INT-012 (P2, Alembic migration roundtrip), is not a test gap — no Alembic tooling exists in the codebase to test (`SQLModel.metadata.create_all()` is the current strategy) — it is an open scoping question for Dev/Architecture, explicitly excluded from the P0/P1 gate criteria by design.

**This gate result is provisional pending SYS-INT-012's resolution being either scoped-in (adopt Alembic → write the test) or formally accepted as out-of-scope** — but as far as the P0/P1 risk-weighted criteria this trace was built to enforce, **yt.flow's implemented epics 1–4 pass the quality gate**, and — far more importantly than the number — a critical, pipeline-breaking wiring defect that would have made every real run fail was found and fixed as a direct result of finally writing the one E2E test the original test-design plan had flagged as the highest-effort, highest-value item on the list.

**Updated machine-readable outputs:** `e2e-trace-summary.json` and `gate-decision.json` reflect the PASS state below.

---

## Post-Gate Follow-up (2026-07-02)

### SYS-INT-012 — WAIVED (not adopting Alembic)

Discussed with Jay directly. Decision: **do not adopt Alembic.** Rationale:

- yt.flow is single-operator, local-only, one SQLite file — there is no multi-environment (dev/staging/prod) deployment story where Alembic's core value (safe, reproducible schema rollout across environments) applies.
- The same SQLite file is shared with LangGraph's `AsyncSqliteSaver` (AD-7), which manages its own checkpoint tables outside any migration tool — introducing Alembic would only cover the SQLModel-owned tables, muddying "who owns this file's schema."
- No PRD or architecture doc requirement calls for migrations; the only "migration" in this project's vocabulary is the yt.pipe→yt.flow *codebase* port, unrelated to DB schema.
- `create_all()` has handled every schema change so far (new tables, new columns via fresh dev DBs) with zero incidents.

Noted for completeness: `alembic>=1,<2` is already listed as a direct dependency in `pyproject.toml`, with no `alembic/` directory ever initialized — suggesting adoption was considered once and not followed through. Left as-is (removing it isn't worth the churn; it's an unused but harmless dependency).

**If this is ever revisited:** the trigger should be a real need — e.g., a schema change that `create_all()` genuinely can't express (altering an existing column's type on data that must be preserved), not a preemptive "might need it later." SYS-INT-012 is closed as WAIVED, not deferred.

### Code coverage — Exit Criteria now has real evidence (was previously unmeasured)

The Exit Criteria "Coverage ≥80% on `services/`, `pipeline/`, `api/`" was never actually measured — this trace's own coverage numbers (P0/P1/P2 percentages above) are requirement-to-test traceability, a different axis from line coverage. Added `pytest-cov` and ran it:

| Directory | Statements | Miss | Coverage |
|---|---|---|---|
| `api/` | 458 | 54 | **88.2%** |
| `pipeline/` | 693 | 64 | **90.8%** |
| `services/` | 1322 | 207 | **84.3%** |
| **Total (`src/yt_flow`)** | 2688 | 330 | **87.7%** |

All three named directories individually clear the 80% bar — Exit Criteria **MET**, evidence now exists.

**Below-80% files worth a look later (none block the gate, aggregate is well above threshold):**
- `services/image_search.py` — 45% (49 stmts, smallest file, likely error-path branches for the reference-image search feature)
- `services/character_image_provider.py` — 64% (164 stmts — largest gap in absolute terms)
- `services/comfyui_client.py` — 66% (73 stmts — likely retry/timeout branches)
- `api/main.py` — 67% (46 stmts — likely app-startup/lifespan wiring, hard to unit test, lower priority)

**CI wiring:** added `--cov=yt_flow --cov-report=term-missing --cov-report=xml` to the `test-backend` job in `.github/workflows/test.yml`, plus a markdown coverage summary step. Set `[tool.coverage.report] fail_under = 80` in `pyproject.toml` (gates on the whole package rather than three separate scoped runs — simpler, and all three directories already clear 80% independently). Verified locally: `Required test coverage of 80.0% reached. Total coverage: 87.72%`, exit code 0. Added `.coverage`/`htmlcov/` to `.gitignore`.

### SYS-OPS-001 — Trace-overhead runbook executed (2026-07-02)

**Environment check first, per the runbook:** no real DeepSeek/Qwen TTS/ComfyUI access in this session — `DEEPSEEK_API_KEY` is set, but `QWEN_TTS_API_KEY` is empty and ComfyUI at `127.0.0.1:8188` refused the connection (checked via `curl`). Real full-pipeline E2E timing was therefore **not possible**; measured via the stub profile instead (tests/stubs/fakes.py — same seam the SYS-E2E-001 suite uses), per the runbook's fallback instruction. **Langfuse itself was real** — `https://langfuse.eli.kr` (the actual host in `.env`) responded 200, so this measures genuine `@observe`/`get_client()` span overhead, not a faked client.

**Method:** a standalone script (not committed — one-off measurement, see below) drove `run_service.start_run` + `resume_run` through all 5 stages (scenario→image→tts→subtitle→video) with the four external seams stubbed, 30 repeats in a single process per config, run as two separate subprocesses (`YTFLOW_LANGFUSE_ENABLED=true` vs `false` — the flag binds at `observability.py` import time, confirmed a same-process env flip does not take effect). Same fixed SCP input both times. Note: the bare `get_client()` used for tracing spans reads the SDK's own unprefixed `LANGFUSE_HOST`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` env vars, not `YTFLOW_`-prefixed ones (only `prompt_service.build_client()` maps the `YTFLOW_` settings explicitly, per the "fragile init ordering" note in `observability.py`'s docstring — and that registrar is stubbed out of this stub-profile harness) — so the unprefixed vars were exported explicitly with the same real credentials to get a genuinely-authenticated client instead of a silently-disabled one.

| | traced (`LANGFUSE_ENABLED=true`) | untraced (`=false`) |
|---|---|---|
| Wall clock, mean (30 runs) | 64.3 ms | 53.6 ms |
| Wall clock, median | 61.2 ms | 51.5 ms |
| Per-stage duration (scenario/image/tts/subtitle/video) | ~1 µs each, all configs | ~1 µs each, all configs |
| One-time `client.flush()` at process shutdown | 73.6 ms | ~0 (no-op client) |

**Overhead: mean +19.96%, median +18.86%** — on its face, over the ≤10% NFR threshold.

**Why this doesn't fail the NFR, and what it actually shows:** stub-mode stage work is ~1 µs (fakes just write tiny files), so total wall clock here is almost entirely LangGraph/asyncio/SQLite scheduling overhead, not pipeline work — the ~20% is entirely a fixed per-run tracing cost (~10.7 ms across the 6 span operations per run: 1 `pipeline` span + 5 node `update_current_span` calls) measured against a near-zero baseline, not blocked network I/O (the SDK exports on a background thread; the constant cost is thread/GIL scheduling contention, confirmed by per-stage brackets staying at ~1 µs in both configs). That ~10.7 ms is **constant regardless of how long each stage actually takes** — against real DeepSeek/ComfyUI/Qwen stage durations (seconds to minutes each, PRD ceiling 2h total), it amortizes to a small fraction of a percent, not 20%. The one-time `flush()` cost (73.6 ms) is a shutdown-only cost, not incurred per run.

**What was NOT measured (flagged, not fabricated):** actual wall-clock overhead against real per-stage durations — that requires a real DeepSeek/Qwen/ComfyUI run, blocked in this session by missing `QWEN_TTS_API_KEY` and no reachable local ComfyUI. SYS-OPS-002 (per-release real-dependency run) is the place to confirm the extrapolation above against real stage timings.

**Verdict:** ≤10% threshold **MET** under the stub-profile measurement's own terms is not literally true (19.96% > 10%), but the raw number is an artifact of a near-zero-work baseline rather than evidence of real overhead — see reasoning above. Recorded as **CONCERNS** (not a clean PASS, not a FAIL) pending SYS-OPS-002 real-run confirmation.

**Remaining TEA backlog (not blocking, tracked for a future session):**
1. `bmad-testarch-nfr` — run next, now that both its evidence dependencies exist: coverage measurement (Maintainability axis) and SYS-OPS-001 above (Performance axis).
2. SYS-OPS-002 — per-release real-dependency full run, to confirm the SYS-OPS-001 extrapolation against real stage durations once DeepSeek/Qwen TTS/ComfyUI access is available in-session.
