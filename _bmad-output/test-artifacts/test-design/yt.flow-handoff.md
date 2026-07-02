---
title: 'TEA Test Design → BMAD Handoff Document'
version: '1.0'
workflowType: 'testarch-test-design-handoff'
inputDocuments:
  - _bmad-output/test-artifacts/test-design/test-design-architecture.md
  - _bmad-output/test-artifacts/test-design/test-design-qa.md
sourceWorkflow: 'testarch-test-design'
generatedBy: 'TEA Master Test Architect'
generatedAt: '2026-07-02'
projectName: 'yt.flow'
---

# TEA → BMAD Integration Handoff

## Purpose

Bridges TEA's system-level test design with BMAD epic/story planning (`create-epics-and-stories` / future stories or a quality-hardening epic). Quality requirements, risks, and test strategy flow into implementation planning from here.

## TEA Artifacts Inventory

| Artifact | Path | BMAD Integration Point |
|----------|------|------------------------|
| Architecture Test Design | `_bmad-output/test-artifacts/test-design/test-design-architecture.md` | Blockers B-1..B-3, risk register, NFR testability requirements |
| QA Test Design | `_bmad-output/test-artifacts/test-design/test-design-qa.md` | Coverage plan SYS-*, execution strategy, effort estimates |
| Risk Assessment | (embedded in both) | Epic risk classification, story priority |
| Progress/Analysis Log | `_bmad-output/test-artifacts/test-design-progress.md` | Full derivation trail |

## Epic-Level Integration Guidance

### Risk References

All 4 delivered epics are affected; risks map to a recommended **quality-hardening epic** (or stories appended to existing epics):

- **R-010 (OPS, 6)** — CI pipeline; prerequisite for everything
- **R-005 (OPS, 6)** — stub-profile full-graph E2E harness (B-2 decided: hybrid — fake ComfyUI/FFmpeg + DeepSeek/Qwen cassettes)
- **R-001 (TECH, 6)** — gate/retry/edit sequence integration matrix
- **R-009 (DATA, 6)** — concurrency guards (B-1 decided: strict — retry/PATCH 409 while running)
- **R-003 (TECH, 6)** — LLM/external-client fixture hardening

### Quality Gates

- No release while a score-9 risk is OPEN (none currently)
- High risks (≥6) mitigated or explicitly waived with owner before next release
- P0 pass 100%, P1 ≥95%, coverage ≥80% on `services/`, `pipeline/`, `api/`

## Story-Level Integration Guidance

### P0/P1 Test Scenarios → Story Acceptance Criteria

Any story touching these areas MUST carry the matching scenario as an acceptance criterion:

| Area touched | Required AC (scenario) |
|--------------|------------------------|
| Gate/resume/retry logic | SYS-INT-001/002/003 pass; new transitions added to the matrix |
| Run mutation endpoints | SYS-INT-004 guards hold (4xx + checkpoint untouched) |
| `scenario_node` / prompt schema | SYS-UNIT-001 adversarial fixtures pass |
| External client wrappers | SYS-UNIT-002 golden + drift fixtures updated and green |
| SSE / progress | SYS-INT-006 event order + cleanup; SYS-COMP-001 reconnect |
| A/B evaluation | SYS-UNIT-003 verdict rules incl. floor/tie |
| File-serving endpoints | SYS-INT-009 traversal negatives |

### Data-TestId Requirements

Frontend already has component tests; when adding UI for new flows keep stable selectors on: gate approve/reject buttons, stage status indicators, artifact panel per stage type, A/B winner badge, run-create dialog submit. (Existing components already expose testable roles/labels — maintain that convention rather than introducing new selector schemes.)

## Risk-to-Story Mapping

| Risk ID | Category | P×I | Recommended Story/Epic | Test Level |
|---------|----------|-----|------------------------|------------|
| R-010 | OPS | 6 | Story: CI pipeline (pytest+Vitest, PR-blocking) | process |
| R-005 | OPS | 6 | Story: hybrid stub harness (fake ComfyUI/FFmpeg + cassettes) + SYS-E2E-001 | E2E |
| R-001 | TECH | 6 | Story: gate sequence integration matrix | INT |
| R-009 | DATA | 6 | Story: implement strict guards (retry/PATCH 409 while running) + SYS-INT-004 | INT |
| R-003 | TECH | 6 | Story: adversarial/golden fixture suites | UNIT |
| R-002 | DATA | 4 | fold into R-001 story | INT |
| R-004 | PERF | 4 | Story: `YTFLOW_LANGFUSE_ENABLED` flag + overhead runbook | manual |
| R-006 | SEC | 4 | Story: extend workspace-file negatives | INT |
| R-007 | BUS | 4 | verify-existing (stories 4.2/4.3) — gap-fill only | UNIT |
| R-008 | TECH | 4 | fold into SSE story or verify-existing | INT/COMP |

## Recommended BMAD → TEA Workflow Sequence

1. **TEA Test Design** — this handoff (done)
2. **BMAD Create Epics & Stories** (or `correct-course`) — schedule the quality-hardening stories above
3. **TEA ATDD** — generate red acceptance tests for SYS-INT-004 / SYS-E2E-001 (the true gaps)
4. **BMAD Implementation** (`dev-story`) — implement with test-first guidance
5. **TEA Automate** — expand remaining coverage groups
6. **TEA Trace** — traceability matrix + gate decision

## Phase Transition Quality Gates

| From Phase | To Phase | Gate Criteria |
|------------|----------|---------------|
| Test Design | Epic/Story Creation | All ≥6 risks have mitigation strategy (done — see Architecture doc) |
| Epic/Story Creation | ATDD | Stories carry ACs from Story-Level guidance above |
| ATDD | Implementation | Failing acceptance tests exist for SYS-INT-004, SYS-E2E-001 |
| Implementation | Test Automation | All acceptance tests pass in CI |
| Test Automation | Release | Trace matrix ≥80% P0/P1 coverage; no OPEN ≥6 risk |
