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

# Test Design for QA: yt.flow — SCP Content Pipeline

**Purpose:** Test execution recipe. Defines what to test, at which level, and what is needed from the Dev side first.

**Date:** 2026-07-02
**Author:** Murat (TEA) with User
**Status:** Draft
**Project:** yt.flow

**Related:** See `test-design-architecture.md` for testability concerns (B-1..B-3) and full risk detail.

---

## Executive Summary

**Scope:** System-level test plan across pipeline core, API/SSE, frontend, and A/B evaluation. All 4 epics are implemented with ~50 existing test files; this plan credits existing coverage and targets the gaps.

**Risk Summary:**

- Total Risks: 10 (5 high ≥6, 5 medium, 0 low)
- Critical Categories: TECH (gate state machine, contract drift), OPS (no CI, no E2E), DATA (concurrency)

**Coverage Summary:**

- P0: 6 scenario groups (gate matrix, resume, retry/edit, concurrency, stub-E2E, LLM hardening)
- P1: 8 scenario groups (projection sync, SSE, client contracts, degradation, security negatives, A/B verdict, frontend SSE, error visibility)
- P2: 4 scenario groups — P3: 2 runbooks
- **Total:** 20 scenario groups, ~40–70h (solo, part-time ~2–4 weeks)

---

## Not in Scope

| Item | Reasoning | Mitigation |
|------|-----------|------------|
| **Load/stress testing (k6)** | Single operator, one run at a time; no concurrency NFR | Performance measured operationally per release (SYS-OPS-001/002) |
| **Auth/authz testing** | No auth by design (local-only, PRD NFR) | Security scope limited to file-serving negatives (SYS-INT-009) |
| **Real-dependency E2E in CI** | 2h runtime + paid APIs (DeepSeek/Qwen) + local ComfyUI | Stub-profile E2E (SYS-E2E-001) + per-release manual run (SYS-OPS-002) |
| **Scene-level resume granularity** | Accepted PRD trade-off (node-level only) | Resume tests assert node-level behavior only |

---

## Dependencies & Test Blockers

**Source:** Architecture doc Quick Guide (B-1..B-3).

### Dev Dependencies (Pre-Test-Development) — decisions made 2026-07-02, implementation pending

1. **B-1: Concurrency guards (strict)** — Dev — before SYS-INT-004
   - Decision: retry/PATCH allowed only when `run.status ∈ {awaiting_approval, failed, complete}`; `running` → 409, checkpoint untouched
   - Implementation: add `status=running` check to `retry_stage()` and `edit_artifact()` in `run_service.py` (double approve + pending-stage retry already guarded)
2. **B-2: Stub seam (hybrid)** — Dev — before SYS-E2E-001
   - Decision: fake ComfyUI/FFmpeg (tiny deterministic artifacts) + recorded DeepSeek/Qwen cassette fixtures; wired via test fixtures/monkeypatch, no production stub flag
3. **B-3: Langfuse flag** — Dev — before SYS-INT-007 / SYS-OPS-001
   - Decision: `YTFLOW_LANGFUSE_ENABLED` (default `true`) in `config.py`; `false` → `@observe` no-op

### QA Infrastructure Setup

1. **Fixtures** — adversarial LLM-output fixtures (malformed JSON, missing camera fields, bad `sentence_indices`); DeepSeek/Qwen cassette recordings (B-2) — **must be re-recorded when Prompt Hub templates or pinned model IDs change**; temp-SQLite per-test fixture (exists in current suite — reuse)
2. **Test Environments** — Local: `uv run pytest` + `npm test` (frontend/). CI: same, PR-blocking (R-010). No staging tier.

**Example (only if the optional Playwright UI-smoke layer is built), with playwright-utils:**

```typescript
import { test } from '@seontechnologies/playwright-utils/api-request/fixtures';
import { expect } from '@playwright/test';

test('@P0 @API stub run reaches first gate', async ({ apiRequest }) => {
  const { status, body } = await apiRequest({
    method: 'POST',
    path: '/runs',
    body: { scp_id: 'SCP-096', scp_text: 'stub text' },
  });
  expect(status).toBe(201);

  const { body: run } = await apiRequest({ method: 'GET', path: `/runs/${body.id}` });
  expect(['running', 'awaiting_approval']).toContain(run.status);
});
```

Backend scenarios below use **pytest** (existing convention) — Playwright is not required for them.

---

## Risk Assessment

**Note:** Full detail in Architecture doc. Summary with QA coverage mapping:

### High-Priority Risks (Score ≥6)

| Risk ID | Category | Description | Score | QA Test Coverage |
|---------|----------|-------------|-------|------------------|
| **R-001** | TECH | Gate/retry state-machine corruption | **6** | SYS-INT-001/002/003 sequence matrix |
| **R-003** | TECH | External contract drift / malformed LLM output | **6** | SYS-UNIT-001/002 fixture suites |
| **R-005** | OPS | No CI-runnable full-graph E2E | **6** | SYS-E2E-001 stub-profile suite |
| **R-009** | DATA | Concurrent run mutations corrupt state | **6** | SYS-INT-004 guard tests |
| **R-010** | OPS | No CI enforcement | **6** | CI setup (process, not a test) |

### Medium-Priority Risks

| Risk ID | Category | Description | Score | QA Test Coverage |
|---------|----------|-------------|-------|------------------|
| R-002 | DATA | `runs` projection desync | 4 | SYS-INT-005 |
| R-004 | PERF | Trace overhead / 2h ceiling unmeasured | 4 | SYS-OPS-001 runbook |
| R-006 | SEC | Path traversal on file endpoints | 4 | SYS-INT-009 |
| R-007 | BUS | A/B verdict invalid | 4 | SYS-UNIT-003 |
| R-008 | TECH | SSE delivery gaps | 4 | SYS-INT-006, SYS-COMP-001 |

---

## NFR Test Coverage Plan

| NFR Category | Requirement / Threshold | Planned Validation | Tool / Level | Evidence Artifact | Priority |
|--------------|------------------------|--------------------|--------------|-------------------|----------|
| Reliability | Node-level resume; gates block until approved | SYS-INT-001/002 | pytest / INT | CI test report | P0 |
| Reliability | Langfuse down ⇒ pipeline unaffected + logged (AD-10) | SYS-INT-007 | pytest / INT | CI test report | P1 |
| Error visibility | Failed node surfaces stage/inputs/exception (FR-13) | SYS-INT-008 | pytest / INT | CI report + sample trace link | P1 |
| Security | No file outside `workspace/` served | SYS-INT-009 | pytest / INT | CI test report | P1 |
| Performance | E2E ≤2h; trace overhead ≤10% | SYS-OPS-001/002 | manual runbook | per-release run log + Langfuse durations | P3 |
| Maintainability | DoD adherence; ≥80% coverage core layers | CI coverage gate | CI | coverage report | P1 |

**Missing thresholds / evidence sources:** none remaining — B-1 (strict guard semantics) and B-3 (overhead measurement via `YTFLOW_LANGFUSE_ENABLED` on/off comparison) decided 2026-07-02; implementation pending. No PASS/CONCERNS/FAIL assigned here — that is `nfr-assess` scope.

---

## Entry Criteria

- [x] B-1, B-2, B-3 decided (2026-07-02); [ ] implementations landed (guard, cassettes, flag)
- [ ] CI pipeline live (R-010)
- [ ] Fixture set recorded (golden + adversarial)

## Exit Criteria

- [ ] All P0 passing (100%)
- [ ] P1 ≥95% (failures triaged and accepted)
- [ ] No open high-severity bugs against gate/resume/retry paths
- [ ] Coverage ≥80% on `services/`, `pipeline/`, `api/`

---

## Test Coverage Plan

**IMPORTANT:** P0/P1/P2/P3 = **priority and risk level**, NOT execution timing. See Execution Strategy for when tests run. **[verify-existing]** = confirm the named existing file covers the scenario; extend gaps only — do not duplicate.

### P0 (Critical)

**Criteria:** Blocks core functionality + high risk (≥6) + no workaround

| Test ID | Requirement | Test Level | Risk Link | Notes |
|---------|-------------|------------|-----------|-------|
| **SYS-INT-001** | Gate matrix: approve advances; reject(scenario)→END; reject(others)→re-run; gate node sole `gate_states` writer (AD-3) | INT (pytest) | R-001 | [verify-existing] `tests/pipeline/test_gates.py`, `tests/api/test_gate.py`; add full sequence matrix |
| **SYS-INT-002** | Resume re-runs only failed node from checkpoint; explicit restart from scenario (FR-7/8) | INT (pytest) | R-001 | [verify-existing] `tests/services/test_run_service_resume.py` |
| **SYS-INT-003** | Retry nullifies stage outputs + re-executes (AD-9); PATCH edit persists checkpoint + file (AD-8); subsequent approve uses edited state | INT (pytest) | R-001 | [verify-existing] `tests/api/test_stages.py`, `test_stage_artifacts.py` |
| **SYS-INT-004** | Invalid-state ops (retry/PATCH while running, double approve, approve non-pending) → 4xx, checkpoint untouched | INT (pytest) | R-009 | gap — B-1 decided (strict guard); implement then test |
| **SYS-E2E-001** | Stub-profile full run: POST /runs → 5× approve → complete; SSE order asserted; artifacts on disk | E2E (pytest, stub clients) | R-005 | gap — B-2 decided (hybrid stub); target <5 min |
| **SYS-UNIT-001** | Scenario output hardening: malformed JSON, None camera fields (AD-5 defaults), bad `sentence_indices`, empty shots | UNIT (pytest) | R-003 | partial — extend `tests/pipeline/nodes/test_scenario.py`, `test_image.py` |

**Total P0:** 6 scenario groups

### P1 (High)

**Criteria:** Important flows + medium risk + workaround exists but costly

| Test ID | Requirement | Test Level | Risk Link | Notes |
|---------|-------------|------------|-----------|-------|
| **SYS-INT-005** | `runs` projection updates only after LangGraph events; `astream()` error → `failed` + `run_failed` SSE (AD-4) | INT (pytest) | R-002 | [verify-existing] `tests/services/test_run_service_gate.py` |
| **SYS-INT-006** | SSE lifecycle: `gate_pending` on interrupt, per-stage event order, queue cleanup on disconnect | INT (pytest) | R-008 | [verify-existing] `tests/api/test_sse.py` |
| **SYS-UNIT-002** | Client contracts from recorded fixtures: ComfyUI (nodes 6/7 injection, poll, errors), Qwen timings, DeepSeek errors | UNIT (pytest) | R-003 | partial — extend `test_comfyui_client.py`, `nodes/test_tts.py` |
| **SYS-INT-007** | Langfuse client raises → stage completes, error logged (AD-10) | INT (pytest) | R-004 | gap — B-3 decided (config flag); implement then test |
| **SYS-INT-008** | Failed node's trace payload carries stage, inputs, exception (FR-13) | INT (pytest) | — | gap |
| **SYS-INT-009** | File-serving negatives: `../`, absolute paths, symlink escape → 4xx | INT (pytest) | R-006 | [verify-existing] `tests/api/test_workspace_files.py` |
| **SYS-UNIT-003** | A/B verdict: order-reversal 2/3 majority, tie→rule tiebreaker, quality floor, no-winner; malformed judge output | UNIT (pytest) | R-007 | [verify-existing] `test_eval_service.py`, `test_ab_run.py` (stories 4.2/4.3) |
| **SYS-COMP-001** | Frontend SSE reconnect refetches run state; gate controls render/disable per state | COMP (Vitest) | R-008 | [verify-existing] `RunDetail.test.tsx` (story 3.5) |

**Total P1:** 8 scenario groups

### P2 (Medium)

**Criteria:** Secondary flows + low risk + regression prevention

| Test ID | Requirement | Test Level | Risk Link | Notes |
|---------|-------------|------------|-----------|-------|
| **SYS-INT-010** | Video download (FR-26); stage artifacts read from LangGraph state not DB (FR-28, AD-7) | INT (pytest) | — | [verify-existing] `test_stage_artifacts.py` |
| **SYS-INT-011** | `GET /scps` lifespan load + filter; A/B run linkage `ab_pair_id` + variant B (AD-6) | INT (pytest) | — | [verify-existing] `test_scps.py`, `test_ab_run.py` |
| **SYS-E2E-002** | UI smoke on stub backend: dashboard → create run → approve gate → artifact panel per stage type | E2E (Playwright) | R-005 | optional — build only if UI regressions recur |
| **SYS-INT-012** | Alembic migration roundtrip; SQLModel + checkpoint tables coexist in one file (AD-7) | INT (pytest) | — | gap |

**Total P2:** 4 scenario groups

### P3 (Low)

**Criteria:** Benchmarks, runbooks, exploratory

| Test ID | Requirement | Test Level | Notes |
|---------|-------------|------------|-------|
| **SYS-OPS-001** | Trace-overhead measurement: traced vs. disabled run, record stage durations | manual runbook | R-004; after B-3 flag lands |
| **SYS-OPS-002** | Per-release real-dependency full run with approval checklist | manual runbook | formalize existing practice |

**Total P3:** 2 runbooks

---

## Execution Strategy

**Philosophy:** Run everything in PRs unless expensive or long-running.

### Every PR (blocking, target <10 min)

- All backend pytest (unit + INT) and frontend Vitest — includes P0/P1/P2 functional scenarios
- Requires CI (R-010) first

### Nightly

- SYS-E2E-001 stub-profile suite (<5 min, but isolated from PR path until stable); burn-in for newly added tests
- SYS-E2E-002 Playwright smoke, if built

### Per Release (manual)

- SYS-OPS-001 trace-overhead measurement
- SYS-OPS-002 real-dependency full run

No k6/chaos tier — out of scope (see Not in Scope).

---

## QA Effort Estimate

| Priority | Count | Effort Range | Notes |
|----------|-------|--------------|-------|
| P0 | 6 groups | ~20–35h | SYS-E2E-001 stub harness dominates (~10–18h) |
| P1 | 8 groups | ~12–20h | mostly verify-existing + targeted gaps |
| P2 | 4 groups | ~6–12h | SYS-E2E-002 optional |
| P3 | 2 runbooks | ~2–4h | documentation |
| **Total** | 20 groups | **~40–70h (~2–4 weeks part-time, solo)** | |

**Assumptions:** existing temp-DB fixtures reusable; B-1..B-3 resolved by Dev before dependent scenarios; maintenance excluded (~10%).

---

## Implementation Planning Handoff

| Work Item | Owner | Target Milestone | Dependencies/Notes |
|-----------|-------|------------------|--------------------|
| CI pipeline (pytest + Vitest, PR-blocking) | Operator | immediate | R-010; enables everything |
| B-1/B-2/B-3 implementation (guard, cassettes, flag) | Dev | pre-test-development | decisions recorded in Architecture doc |
| Stub-profile E2E harness + SYS-E2E-001 | Dev | after B-2 impl | hybrid: fake ComfyUI/FFmpeg + cassettes; largest single item |
| Gate sequence matrix (SYS-INT-001/003/004) | Dev | after B-1 impl | R-001/R-009 |
| Fixture suites (SYS-UNIT-001/002) | Dev | immediate | R-003; no blockers |
| Runbooks (SYS-OPS-001/002) | Operator | per release | after B-3 impl |

---

## Interworking & Regression

| Service/Component | Impact | Regression Scope | Validation Steps |
|-------------------|--------|------------------|------------------|
| **LangGraph checkpoint schema** | retry/edit mutate in-place | All INT tests over gate/resume/retry | PR suite green |
| **Langfuse (homelab)** | non-fatal dependency | SYS-INT-007 degradation | nightly + per-release trace check |
| **ComfyUI workflow JSON** | node IDs 6/7 injection contract | SYS-UNIT-002 fixtures | fixture refresh when workflow file changes |
| **frontend ↔ API** | SSE + REST shapes | Vitest component suite + SYS-E2E-002 (optional) | PR suite green |

**Regression strategy:** the existing ~50-file suite is the regression base; every PR runs it fully. Fixture refresh is mandatory when `data/workflows/*.json` or prompt schemas change.

---

## Appendix A: Code Examples & Tagging

Backend (pytest) — mark priorities with markers:

```python
import pytest

@pytest.mark.p0
async def test_reject_then_retry_then_approve_reaches_next_stage(graph, temp_db):
    run = await start_stub_run(graph)
    await resolve_gate(run, "scenario", "rejected")
    await retry_stage(run, "scenario")
    await resolve_gate(run, "scenario", "approved")
    state = await graph.aget_state(run.config)
    assert state.values["gate_states"]["scenario"] == "approved"
    assert state.values["current_stage"] == "image"
```

```bash
uv run pytest -m p0            # P0 only
uv run pytest -m "p0 or p1"    # P0 + P1
npm test --prefix frontend      # frontend component suite
```

Playwright tags (optional UI layer): `npx playwright test --grep @P0` — see example in Dependencies section.

## Appendix B: Knowledge Base References

- **Risk Governance**: `risk-governance.md` — scoring methodology and gate rules
- **Test Levels Framework**: `test-levels-framework.md` — E2E vs API vs Unit selection
- **ADR Quality Readiness Checklist**: `adr-quality-readiness-checklist.md` — testability criteria source
- **Test Quality**: `test-quality.md` — DoD (deterministic, isolated, <300 lines, <1.5 min, cleanup)
- **NFR Criteria**: `nfr-criteria.md` — evidence-based NFR validation

---

**Generated by:** BMad TEA Agent — **Workflow:** `bmad-testarch-test-design` — **Version:** 4.0 (BMad v6)
