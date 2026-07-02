---
workflowStatus: 'completed'
totalSteps: 5
stepsCompleted: ['step-01-detect-mode', 'step-02-load-context', 'step-03-risk-and-testability', 'step-04-coverage-plan', 'step-05-generate-output']
lastStep: 'step-05-generate-output'
nextStep: ''
lastSaved: '2026-07-02'
workflowType: 'testarch-test-design'
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/implementation-artifacts/sprint-status.yaml
---

# Test Design for Architecture: yt.flow — SCP Content Pipeline

**Purpose:** Architectural concerns, testability gaps, and NFR requirements for the Dev/Architecture side. Contract on what must be addressed before the remaining test development begins.

**Date:** 2026-07-02
**Author:** Murat (TEA) with User
**Status:** Architecture Review Pending
**Project:** yt.flow
**PRD Reference:** `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`
**ADR Reference:** `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` (AD-1..AD-10)

---

## Executive Summary

**Scope:** Full system — LangGraph pipeline (scenario→image→tts→subtitle→video, 5 interrupt gates), FastAPI + SSE API, React SPA, A/B evaluation. All 4 epics implemented; this design consolidates system-level quality strategy over existing + missing coverage.

**Business Context** (from PRD): Rewrite exists to enable stage-level diagnosis (≤30 min via Langfuse) and automated A/B prompt evaluation. Solo operator, local-only deployment.

**Architecture** (from spine):

- LangGraph checkpoint (`AsyncSqliteSaver`) is the single source of truth; `runs` table is a projection (AD-2/AD-4)
- Gates are LangGraph `interrupt()` nodes; retry/edit mutate the checkpoint in-place via `update_state()` (AD-3/AD-8/AD-9)
- External deps behind client modules: DeepSeek V4, Qwen TTS, ComfyUI (local HTTP), FFmpeg, Langfuse (non-fatal, AD-10)

**Expected Scale:** Single operator, one run at a time; E2E run ≤2h (ComfyUI-dominated).

**Risk Summary:**

- **Total risks:** 10
- **High-priority (≥6):** 5 (R-001, R-003, R-005, R-009, R-010)
- **Test effort:** ~40–70h total (see QA doc), most existing coverage credited

---

## Quick Guide

### 🚨 BLOCKERS — RESOLVED 2026-07-02 (decisions recorded, implementation pending)

1. **B-1: Concurrency guard semantics** — **DECIDED: strict guard.** `retry` and `PATCH artifact` are allowed only when `run.status` is `awaiting_approval`, `failed`, or `complete`; any request while `status=running` returns 409 and leaves the checkpoint untouched. (Double gate approve already returns 409 — `api/routes/runs.py:129`; retry of a pending stage already returns 409 — `run_service.py`.) Remaining work: add the `status=running` check to `retry_stage` and `edit_artifact`, then SYS-INT-004. (owner: Dev)
2. **B-2: Stub-profile injection seam** — **DECIDED: hybrid.** Stub only the heavy dependencies (ComfyUI, FFmpeg) with fakes producing tiny deterministic artifacts; DeepSeek and Qwen TTS use recorded cassette fixtures so response shapes stay realistic. Seam lives at test level (fixtures/monkeypatch), no production stub flag. (owner: Dev)
3. **B-3: Langfuse disable switch** — **DECIDED: config flag.** Add `YTFLOW_LANGFUSE_ENABLED` (default `true`) to `config.py`; when `false`, `@observe` becomes a no-op. Enables both the AD-10 degradation test and the ≤10% overhead comparison run. (owner: Dev)

### ⚠️ HIGH PRIORITY — Validate Recommendations

1. **R-001: Gate/retry state-machine integrity** — Approve the integration test matrix over gate-transition sequences (reject→retry→approve, edit→approve) asserting checkpoint/DB/SSE agreement. (Dev approves scope)
2. **R-003: External contract drift** — Approve recorded-fixture strategy per client + adversarial LLM-output fixtures for `scenario_node`. (Dev approves fixture set)
3. **R-010: No CI** — Approve standing up PR-blocking CI (pytest + Vitest); everything else in this plan assumes it. (Operator decision)

### 📋 INFO ONLY — Solutions Provided

1. **Test strategy:** Unit + API/graph integration carry the load; one stub-profile E2E suite; UI stays at component level (Vitest) unless regressions demand Playwright smoke.
2. **Tooling:** pytest (backend), Vitest (frontend), optional Playwright(+playwright-utils) for UI smoke; no k6 (performance is operational measurement, not load testing).
3. **CI tiers:** PR <10 min; nightly stub-E2E; per-release manual measured run.
4. **Coverage:** 20 planned scenario groups P0–P3, most mapped onto ~50 existing test files (see QA doc).
5. **Quality gates:** P0 100%, P1 ≥95%, coverage ≥80% on `services/`, `pipeline/`, `api/`.

---

## Risk Assessment

**Total risks identified:** 10 (5 high ≥6, 5 medium 3–5, 0 low)

### High-Priority Risks (Score ≥6)

| Risk ID | Category | Description | P | I | Score | Mitigation | Owner | Timeline |
|---------|----------|-------------|---|---|-------|------------|-------|----------|
| **R-001** | **TECH** | Gate/resume/retry state-machine corruption: in-place checkpoint mutation (AD-9) across approve/reject/retry/edit sequences leaves stale outputs or wrong `gate_states` | 2 | 3 | **6** | Integration test matrix over gate sequences; assert checkpoint + DB + SSE agree | Dev | before next release |
| **R-003** | **TECH** | External contract drift: DeepSeek response shape, ComfyUI workflow node IDs (6/7), Qwen timing format; malformed LLM scenario JSON | 3 | 2 | **6** | Schema-validation unit tests with adversarial + recorded fixtures; AD-5 `None` camera-field handling | Dev | immediate |
| **R-005** | **OPS** | No affordable full-graph E2E → stage-wiring/gate regressions ship undetected (real run = 2h + paid APIs) | 3 | 2 | **6** | Stub-profile E2E: fake clients + real graph + real FastAPI + temp SQLite (needs B-2) | Dev | high priority |
| **R-009** | **DATA** | Concurrent run mutations (retry/PATCH while running, double approve) corrupt checkpoint state | 2 | 3 | **6** | Specify guards (B-1), then API tests: invalid-state ops → 4xx, checkpoint untouched | Dev | before next release |
| **R-010** | **OPS** | No CI — ~50 existing test files not enforced on change | 3 | 2 | **6** | PR-blocking CI (pytest + Vitest + lint) via `testarch-ci` workflow | Operator | immediate |

### Medium-Priority Risks (Score 3–5)

| Risk ID | Category | Description | P | I | Score | Mitigation | Owner |
|---------|----------|-------------|---|---|-------|------------|-------|
| R-002 | DATA | `runs` projection desyncs from LangGraph checkpoint | 2 | 2 | 4 | Integration tests: DB updates only after LangGraph events (AD-2/AD-4) | Dev |
| R-004 | PERF | Trace overhead >10% or E2E >2h goes unnoticed (no harness) | 2 | 2 | 4 | Per-release traced-vs-untraced comparison run (needs B-3); not CI | Operator |
| R-006 | SEC | Path traversal via artifact/workspace file endpoints | 2 | 2 | 4 | Negative tests (`../`, absolute, symlink); verify existing coverage | Dev |
| R-007 | BUS | A/B verdict invalid (judge parsing, order-reversal, tie/floor bugs) promotes wrong prompt | 2 | 2 | 4 | Verify story 4.2/4.3 unit coverage; add malformed judge-output fixtures | Dev |
| R-008 | TECH | SSE delivery gaps (missed `gate_pending`, dropped reconnect) stall runs invisibly | 2 | 2 | 4 | SSE integration tests + frontend reconnect component test | Dev |

#### Risk Category Legend

- **TECH**: Technical/Architecture — **SEC**: Security — **PERF**: Performance — **DATA**: Data Integrity — **BUS**: Business Impact — **OPS**: Operations

---

## NFR Testability Requirements

| NFR Category | Threshold / Requirement | Current Design Support | Gap / Decision Needed | Planned Evidence |
|--------------|------------------------|------------------------|----------------------|------------------|
| Performance | E2E ≤2h (automated time only); trace overhead ≤10% | Partial — Langfuse captures durations | **Overhead measurement method UNKNOWN** → B-3 flag + comparison procedure | Per-release run log + Langfuse trace durations |
| Reliability | Node-level resume; gate blocks until approve; Langfuse-down must not fail pipeline (AD-10) | Supported — checkpoint design | Degradation path untested → B-3 | pytest integration reports |
| Security | No auth (accepted, local-only); no file served outside `workspace/` | Partial — threshold implied, not in PRD | Confirm path-normalization guarantee | pytest negative-test report |
| Maintainability | Test-quality DoD; coverage ≥80% core layers | Partial — tests exist, unenforced | CI missing (R-010) | CI coverage report |

**Unknown thresholds:** trace-overhead measurement procedure (R-004); concurrency guard semantics (B-1). Both converted to blockers/risks — not guessed.

**Assessment boundary:** Final PASS/CONCERNS/FAIL belongs to `nfr-assess` after evidence exists.

---

## Testability Concerns and Architectural Gaps

### 1. Blockers to Fast Feedback

| Concern | Impact | Resolution (decided 2026-07-02) | Owner | Timeline |
|---------|--------|--------------------------------|-------|----------|
| **No stub-profile for full graph** | No CI-runnable E2E; gate/wiring regressions found manually | B-2 hybrid: fake ComfyUI/FFmpeg + DeepSeek/Qwen cassettes at test level | Dev | pre-test-development |
| **Unspecified concurrency guards** | SYS-INT-004 tests unwritable | B-1 strict: retry/PATCH only when not `running`, else 409 | Dev | pre-test-development |
| **No Langfuse kill-switch** | AD-10 degradation and overhead NFR unverifiable | B-3: `YTFLOW_LANGFUSE_ENABLED` config flag (default true) | Dev | pre-test-development |

### 2. Architectural Improvements Needed

1. **LLM output hardening at `scenario_node`**
   - Current problem: Director-pattern output (shots, `sentence_indices`, camera fields) is schema-critical; malformed output is the most probable runtime failure (R-003)
   - Required change: none structural — provide/keep a strict parse-and-validate boundary so unit tests can target it with adversarial fixtures
   - Impact if not fixed: runtime crashes mid-pipeline, wasted 2h runs
   - Owner: Dev — Timeline: immediate

---

## Testability Assessment Summary

### What Works Well

- Stage nodes are pure functions of `PipelineState` — unit-testable without LangGraph runtime
- 100% of business logic reachable via REST (FR-24–34); UI never required for critical-path testing
- Single SQLite file → cheap per-test temp-DB isolation; fixed 5-gate topology removes config combinatorics
- SSE events (`stage_entry/stage_exit/gate_pending/run_failed`) are deterministic assertion points
- ~50 test files already exist across backend and frontend; this plan credits them rather than duplicating

### Accepted Trade-offs (No Action Required)

- **Node-level (not scene-level) resume** — accepted in PRD; TTS failing at scene 8/20 re-runs the stage
- **No auth/multi-tenancy** — local single-operator deployment; security surface limited to file serving
- **Performance validated operationally, not by load tests** — one operator, no concurrency requirement; k6 out of scope

---

## Risk Mitigation Plans (High-Priority Risks ≥6)

#### R-001: Gate/retry state-machine corruption (Score: 6)

1. Enumerate gate-transition sequences: approve-all; reject(scenario)→END; reject(stage)→retry→approve; edit→approve; retry-after-complete
2. Integration tests drive sequences through real graph + `AsyncSqliteSaver` on temp DB
3. After each step assert: checkpoint state, `runs` projection, SSE event order all agree

**Owner:** Dev — **Timeline:** before next release — **Status:** Planned — **Verification:** SYS-INT-001/003 green in CI

#### R-003: External contract drift (Score: 6)

1. Record one golden response fixture per client (DeepSeek scenario, ComfyUI submit/poll, Qwen TTS timings)
2. Add adversarial fixtures: malformed JSON, missing camera fields, out-of-range `sentence_indices`, empty shots
3. Unit tests on parse/validate boundaries; `image_node` default-handling per AD-5

**Owner:** Dev — **Timeline:** immediate — **Status:** Planned — **Verification:** SYS-UNIT-001/002 green in CI

#### R-005: No CI-runnable full-graph E2E (Score: 6)

1. Per B-2 decision: fake ComfyUI/FFmpeg (tiny deterministic image/video artifacts) + recorded DeepSeek/Qwen cassettes, wired via test fixtures
2. Suite: POST /runs → SSE-observe → approve 5 gates → assert completion, artifacts, trace linkage stubbed
3. Run nightly (and on-demand); target <5 min

**Owner:** Dev — **Timeline:** high priority — **Status:** Planned — **Verification:** SYS-E2E-001 nightly green

#### R-009: Concurrent run mutations (Score: 6)

1. Implement strict guard per B-1 decision: `retry`/`PATCH` require `run.status in {awaiting_approval, failed, complete}`, else 409
2. API tests: each invalid-state operation returns documented 4xx and leaves checkpoint byte-identical

**Owner:** Dev — **Timeline:** before next release — **Status:** Planned (B-1 decided 2026-07-02) — **Verification:** SYS-INT-004 green in CI

#### R-010: No CI (Score: 6)

1. Run `testarch-ci` workflow: pytest + Vitest + lint, PR-blocking, coverage report
2. Add nightly job for stub-E2E once R-005 lands

**Owner:** Operator — **Timeline:** immediate — **Status:** Planned — **Verification:** first PR blocked on red tests

---

## Assumptions and Dependencies

### Assumptions

1. ComfyUI/FFmpeg fakes and DeepSeek/Qwen cassettes can be wired at test level (fixtures/monkeypatch) without production-code stub branches (B-2 decision)
2. Trace-overhead measurement = same SCP input, `YTFLOW_LANGFUSE_ENABLED` on vs. off, comparing wall-clock (B-3 decision)
3. Solo operator acts as Dev, QA, and PM; "owner" labels map to the same person wearing different hats

### Dependencies

1. B-1/B-2/B-3 **decisions made 2026-07-02**; implementation (strict guard, cassette recording, config flag) required before SYS-INT-004 / SYS-E2E-001 / SYS-INT-007 respectively
2. CI runner available for the repo (R-010) — required immediately

### Risks to Plan

- **Risk:** Cassette fixtures (B-2 hybrid) go stale when prompts or model versions change
  - **Impact:** Stub-E2E passes while real runs break
  - **Contingency:** Re-record cassettes whenever Prompt Hub templates or pinned model IDs change; per-release real run (SYS-OPS-002) is the backstop

---

**Next Steps for Dev/Architecture:**

1. Resolve B-1/B-2/B-3 (Quick Guide blockers)
2. Approve R-001/R-003 test-matrix scope
3. Stand up CI (R-010)

**Next Steps for QA (same person, QA hat):**

1. See companion `test-design-qa.md` for the scenario-level recipe
2. Build stub fakes + fixtures once B-2 lands
