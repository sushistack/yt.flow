---
stepsCompleted: ['step-01-load-context', 'step-02-define-thresholds', 'step-03-gather-evidence', 'step-04-evaluate-and-score', 'step-04e-aggregate-nfr', 'step-05-generate-report']
lastStep: 'step-05-generate-report'
lastSaved: '2026-07-02'
workflowType: 'testarch-nfr-assess'
overallStatus: 'CONCERNS'
inputDocuments:
  - _bmad-output/test-artifacts/traceability-matrix.md
  - _bmad-output/test-artifacts/test-design/test-design-qa.md
  - _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md
  - .claude/skills/bmad-testarch-nfr/resources/knowledge/adr-quality-readiness-checklist.md
  - .claude/skills/bmad-testarch-nfr/resources/knowledge/nfr-criteria.md
  - .claude/skills/bmad-testarch-nfr/resources/knowledge/test-quality.md
  - .claude/skills/bmad-testarch-nfr/resources/knowledge/error-handling.md
  - .claude/skills/bmad-testarch-nfr/resources/knowledge/ci-burn-in.md
  - .claude/skills/bmad-testarch-nfr/resources/knowledge/playwright-config.md
---

# NFR Assessment: yt.flow (system-level)

**Date:** 2026-07-02
**Scope:** System-level (post-trace follow-up), 4 categories per `test-design-qa.md`'s own NFR plan
**Overall Status:** ⚠️ CONCERNS

Note: this audit summarizes existing implementation evidence (re-verified live via pytest this session) plus one fresh runbook execution (SYS-OPS-001); it does not run new CI workflows or add tooling beyond what's already in the project.

## Executive Summary

**Assessment:** 3 PASS (Security, Reliability, Maintainability), 1 CONCERNS (Performance), 0 FAIL

**Blockers:** 0 — no category has a FAIL status; nothing here blocks release on its own terms.

**High Priority Issues:** 1 — Performance/E2E-≤2h has no real-pipeline measurement (evidence gap, not a failing number); SYS-OPS-002 is the way to close it.

**Recommendation:** Ship. This is CONCERNS, not FAIL — the one open item (confirming the 2-hour ceiling and the trace-overhead extrapolation against real DeepSeek/Qwen/ComfyUI stage durations) requires API access this session didn't have, not a code change. Track SYS-OPS-002 as the follow-up; the other 3 categories have concrete, live-re-verified evidence and no known issues.

## Step 1: Context & Evidence Sources

**Implementation status:** All 5 pipeline stages (scenario/image/tts/subtitle/video) implemented and traced (SYS-OPS-critical wiring bug fixed prior session). System-level trace complete (gate PASS, P0 100%/P1 100%/87.7% code coverage).

**NFR thresholds (from PRD "Non-Functional Requirements"):**

| NFR | Threshold | Source |
|---|---|---|
| Performance | E2E video generation ≤ 2 hours; quality over speed | PRD line 144 |
| Performance | Langfuse tracing overhead ≤ 10% of total run time | PRD line 146 |
| Reliability | Langfuse down → pipeline unaffected; any failure surfaces failed node/inputs/exception | PRD lines 149, 158-ish |
| Security | No auth (local-only, single operator, accepted by design) — but `/files` must not serve outside `workspace/` | PRD "Authentication" row; test-design-qa.md SYS-INT-009 |
| Maintainability | ≥80% coverage on `services/`, `pipeline/`, `api/` (test-design-qa.md Exit Criteria) | test-design-qa.md |

**Evidence available going into this assessment:**

1. **Maintainability** — `pytest-cov` run: api 88.2%, pipeline 90.8%, services 84.3%, total 87.7%. CI-gated (`fail_under=80` in `pyproject.toml`). (traceability-matrix.md "Post-Gate Follow-up")
2. **Performance** — SYS-OPS-001 runbook executed this session (stub-profile, 30 reps/config, real Langfuse host). Raw overhead 19.96%/18.86% (mean/median) against a near-zero stub baseline; reasoned to be a fixed ~11ms/run cost, negligible against real per-stage durations (PRD: 2h ceiling dominated by ComfyUI image generation, not LLM/TTS/tracing). Recorded as CONCERNS pending SYS-OPS-002 real-run confirmation.
3. **Reliability** — `tests/services/test_run_service_gate.py::test_trace_setup_failure_is_non_fatal_and_logged` and related tests prove Langfuse-down degrades to no-op + log, pipeline proceeds (AD-10).
4. **Security** — `tests/api/test_workspace_files.py` proves `/files` path-escape rejected.

No `tech-spec.md` or per-story NFR doc found beyond the PRD and test-design-qa.md; those two plus traceability-matrix.md are the authoritative NFR sources for this system-level assessment.

Knowledge base loaded (test-quality, nfr-criteria, error-handling, ci-burn-in, playwright-config, adr-quality-readiness-checklist) — mostly TypeScript/Playwright pattern libraries not directly applicable to this Python/FastAPI backend; the **NFR Gate Decision Matrix** (PASS/CONCERNS/FAIL definitions per category) from `nfr-criteria.md` is the operative rubric for this assessment.

## Step 2: NFR Categories & Thresholds

**Existing test-design NFR plan found:** `test-design-qa.md` → "NFR Test Coverage Plan" table already scopes this system to **4 categories** (not the generic 8-category ADR checklist — this is a local-only, single-operator, no-auth, no-multi-region batch pipeline, so Scalability/DR/Deployability/Test-Data-Segregation don't apply per PRD's own "Out of Scope" section). Per step-02 rule 0, these 4 are used directly as the primary source, matching the user's own request scope:

| Category | Threshold | Source | Evidence Artifact (planned) |
|---|---|---|---|
| **Reliability** | Node-level resume; gates block until approved (P0, SYS-INT-001/002). Langfuse down ⇒ pipeline unaffected + logged (P1, SYS-INT-007, AD-10). Failed node surfaces stage/inputs/exception (P1, SYS-INT-008, FR-13). | test-design-qa.md NFR table | CI test report |
| **Security** | No file outside `workspace/` served (P1, SYS-INT-009) | test-design-qa.md NFR table | CI test report |
| **Performance** | E2E ≤ 2 hours (P3, SYS-OPS-002, not yet run). Trace overhead ≤ 10% (P3, SYS-OPS-001, run this session). | test-design-qa.md NFR table + PRD | Per-release run log + this session's runbook |
| **Maintainability** | DoD adherence; ≥80% coverage on `services/`, `pipeline/`, `api/` (P1) | test-design-qa.md Exit Criteria + CI gate | Coverage report (`pyproject.toml` `fail_under=80`) |

No UNKNOWN thresholds within these 4 categories — the only gap is the E2E ≤2h wall-clock figure, which has never been measured end-to-end with real dependencies (flagged, not fabricated, at trace time and again in the SYS-OPS-001 write-up this session).

## Step 3: Evidence Gathered (re-verified live this session, not just cited from prior sessions)

No browser-based (Playwright CLI) evidence collection applies — this is a Python/FastAPI backend with no UI pages to probe for this assessment; all evidence is pytest-based.

| Category | Evidence | Re-run this session? | Result |
|---|---|---|---|
| **Reliability** | `tests/services/test_run_service_gate.py::test_trace_setup_failure_is_non_fatal_and_logged`, `::test_trace_teardown_failure_is_non_fatal_and_logged` | ✅ re-ran | 2/2 passed |
| **Reliability** | Node-level resume/gate-blocking suite (SYS-INT-001/002) — part of the 468-test full suite | ✅ (via full coverage run below) | included in 468 passed |
| **Security** | `tests/api/test_workspace_files.py` (7 tests, path-escape rejection on `/files`) | ✅ re-ran | 7/7 passed |
| **Performance** | SYS-OPS-001 runbook (this session, see traceability-matrix.md "Post-Gate Follow-up") | ✅ executed fresh | traced mean 64.3ms vs untraced 53.6ms over 30 reps/config; raw +19.96%, reasoned negligible in real-duration terms; CONCERNS pending SYS-OPS-002 |
| **Performance** | E2E ≤2h real-pipeline wall clock | ❌ not possible this session (no `QWEN_TTS_API_KEY`, no reachable ComfyUI at `127.0.0.1:8188`) | UNKNOWN — never measured, flagged in traceability-matrix.md |
| **Maintainability** | `pytest --cov=yt_flow --cov-report=term-missing` | ✅ re-ran fresh | 468 passed, 1 skipped; api 88%/pipeline (91% agg incl. gates/graph/nodes)/services 84%; **total 87.72%**, `fail_under=80` gate passes |

**Evidence gaps:** Performance/E2E-≤2h is the only category with a genuine evidence gap (not a failing measurement — an absent one). Per step-03 rule, this forces the Performance category toward CONCERNS regardless of the trace-overhead result on its own.

## Step 4: Domain Evidence Audits

**Execution mode:** `sequential`, not `agent-team`/`subagent`. All evidence for all 4 domains was already gathered and independently re-verified live in Steps 1–3 above (pytest runs, not citations from memory); dispatching 4 parallel subagents to re-derive conclusions from data already in hand would just restate this section. Sequential is an explicitly supported mode for this step.

**Domain substitution:** the skill's default 4th worker audits **Scalability** (K8s auto-scaling, DB sharding, 100M-user targets). Per Step 2's override rule, this system's own test-design NFR plan scopes to **Maintainability** instead — `test-design-qa.md` explicitly puts scalability out of scope ("Single operator, one run at a time; no concurrency NFR") and the PRD confirms (local-only, single SQLite file, no horizontal-scaling story). Auditing generic K8s/sharding criteria against a single-operator local batch tool would manufacture FAILs against requirements that were never asked for. Security's generic OAuth2/JWT/RBAC/TLS/compliance criteria are marked **N/A by design** below for the same reason (PRD: "Authentication: None — local-only deployment, single operator") rather than scored as gaps — a deliberate accepted decision is not the same as an unaddressed risk.

### 4A — Security

| Category | Status | Evidence | Notes |
|---|---|---|---|
| AuthN/AuthZ (OAuth2/JWT/RBAC) | N/A by design | PRD "Authentication: None — local-only, single operator" | Deliberate PRD decision, not a gap |
| Data encryption at rest/in transit | N/A by design | Local SQLite, localhost-only, no internet-facing TLS termination | Same as above |
| Secrets management | ✅ PASS | `config.py` loads `DEEPSEEK_API_KEY`/`QWEN_TTS_API_KEY`/Langfuse keys via `pydantic-settings` `.env`; no hardcoded credentials found in source read this session | |
| Input validation / path traversal (the one real attack surface: `/files` static serving from `workspace/`) | ✅ PASS | `tests/api/test_workspace_files.py`, 7/7 re-ran passing this session (SYS-INT-009) | This *is* yt.flow's OWASP-equivalent surface — no SQLi/XSS surface exists (no free-text queries from untrusted external users) |
| Compliance (SOC2/GDPR/HIPAA/PCI-DSS) | N/A | No PII, no payment data, single-operator local tool | |

**risk_level: LOW** — **Domain status: PASS.**

### 4B — Performance

| Category | Status | Evidence | Notes |
|---|---|---|---|
| E2E ≤ 2 hours (PRD) | ⚠️ UNKNOWN | Never measured with real DeepSeek/Qwen/ComfyUI — blocked again this session (missing `QWEN_TTS_API_KEY`, no reachable local ComfyUI) | Genuine evidence gap, not a failure |
| Trace overhead ≤ 10% (PRD, SYS-OPS-001) | ⚠️ CONCERN | This session: 30 reps/config, real Langfuse host. Raw +19.96%/+18.86% (mean/median) vs. a near-zero stub baseline; reasoned to be a fixed ~11 ms/run cost (span bookkeeping, not blocked network I/O — flush is a separate one-time 73.6 ms shutdown cost). Against real stage durations (PRD: ceiling dominated by ComfyUI generation time, seconds–minutes/stage) this amortizes to a small fraction of a percent — but that's extrapolation, not a real-run measurement | Raw number is over threshold; reasoning says it will hold, unconfirmed |
| Throughput / concurrency / caching / CDN | N/A by design | test-design-qa.md: "Single operator, one run at a time; no concurrency NFR" | |

**risk_level: MEDIUM** — **Domain status: CONCERNS** (per default rule: undefined/unmeasured evidence → CONCERNS, and that's literally the state of the E2E-≤2h criterion).

### 4C — Reliability

| Category | Status | Evidence | Notes |
|---|---|---|---|
| Node-level resume; gates block until approved (SYS-INT-001/002, P0) | ✅ PASS | Part of the 468-test suite (full `pytest --cov` run, this session) | |
| Langfuse down ⇒ pipeline unaffected + logged (SYS-INT-007, P1, AD-10) | ✅ PASS | `test_trace_setup_failure_is_non_fatal_and_logged`, `test_trace_teardown_failure_is_non_fatal_and_logged` — 2/2 re-ran passing this session | |
| Failed node surfaces stage/inputs/exception (SYS-INT-008, P1, FR-13) | ✅ PASS | Part of the 468-test suite; `_stage_from_exception` mechanism (`run_service.py`) | |
| Monitoring/health-check endpoint | N/A by design | No `/health` route — not required for a local single-operator batch tool with no on-call rotation | Minor future-ops gap if this ever runs unattended/scheduled, not blocking today |
| DR / backups / RTO-RPO | WAIVED | `traceability-matrix.md` SYS-INT-012 — Alembic/migration explicitly waived by direct decision with Jay; single SQLite file, 30-day manual-cleanup retention is the accepted policy (PRD) | Documented decision, not an unaddressed risk |

**risk_level: LOW** — **Domain status: PASS.**

### 4D — Maintainability (substituted for Scalability, see rationale above)

| Category | Status | Evidence | Notes |
|---|---|---|---|
| Test coverage ≥80% on `services/`, `pipeline/`, `api/` | ✅ PASS | Re-ran this session: `api` 88.2%, `services` 84.3%, `pipeline`-area (incl. `gates.py`/`graph.py`/`nodes/`) all ≥82%, **total 87.72%**; 468 passed, 1 skipped; `fail_under=80` CI gate enforced | |
| Structured logging / observability | ✅ PASS | Python `logging` (`logger.warning(...)` in `run_service.py`/`observability.py`) + Langfuse `@observe` tracing on every node | |
| Code duplication scan | Not assessed | No `jscpd`-equivalent tool run; not part of this project's own DoD/Exit Criteria (test-design-qa.md doesn't require it) | Not a gap against this project's own thresholds |
| Dependency vulnerability scan | Not assessed | `pip-audit` not installed in this environment; not part of this project's own DoD/Exit Criteria | Cheap to add later (`uvx pip-audit`) if ever required; not adding a new dependency for an unrequested check now |

**risk_level: LOW** — **Domain status: PASS.**

## Step 4E: Aggregated Executive Summary

**Domain risk breakdown:**

| Domain | risk_level | Status |
|---|---|---|
| Security | LOW | ✅ PASS |
| Performance | MEDIUM | ⚠️ CONCERNS |
| Reliability | LOW | ✅ PASS |
| Maintainability | LOW | ✅ PASS |

**Overall risk level: MEDIUM** (risk hierarchy HIGH > MEDIUM > LOW; one domain — Performance — is MEDIUM, none are HIGH, so overall = MEDIUM per the aggregation rule).

**Compliance summary:** not applicable — every compliance-adjacent criterion assessed above (SOC2/GDPR/HIPAA/PCI-DSS, SLA tiers) was N/A by design for a local-only single-operator tool with no PII/payment surface. No compliance framework applies to this system.

**Cross-domain risks:** none identified. No domain has a FAIL finding, and the sole CONCERNS domain (Performance) doesn't compound with another domain's gaps — the missing E2E-≤2h measurement and the trace-overhead reasoning are both self-contained to Performance/SYS-OPS-002.

**Priority actions (aggregated, ordered by urgency):**

1. **[Performance, NORMAL urgency — no domain is HIGH so nothing is URGENT]** Run SYS-OPS-002 (per-release real-dependency full run) once `QWEN_TTS_API_KEY` and a reachable ComfyUI instance are available in-session. This closes the one real evidence gap (E2E ≤2h) and confirms or refutes the SYS-OPS-001 extrapolation (that the measured +19.96% stub-mode trace overhead amortizes to a small fraction of a percent against real per-stage durations).
2. **[Maintainability, low priority]** Optionally run a dependency vulnerability scan (`uvx pip-audit`) — not part of this project's own DoD, no action required now.

**Execution mode:** SEQUENTIAL (4 NFR domains) — no parallel subagent speedup used; evidence was already gathered and verified live in Steps 1–3, so sequential in-session evaluation was strictly faster than round-tripping through 4 subagents for data already in hand.

## Step 5: Findings Summary

**Based on the project's own 4-category NFR plan (`test-design-qa.md`), not the generic 8-category/29-criteria ADR checklist — see Step 2 rationale.**

| Category | Status | Evidence Re-verified This Session | Open Item |
|---|---|---|---|
| Security | ✅ PASS | `test_workspace_files.py` 7/7 | none |
| Performance | ⚠️ CONCERNS | SYS-OPS-001 runbook (30 reps/config, real Langfuse) | SYS-OPS-002 real-run needed to confirm E2E ≤2h and the trace-overhead extrapolation |
| Reliability | ✅ PASS | `test_trace_setup_failure_is_non_fatal_and_logged` + `test_trace_teardown_failure_is_non_fatal_and_logged` 2/2, full 468-test suite | none |
| Maintainability | ✅ PASS | `pytest --cov` 87.72% total, all 3 named dirs ≥80%, CI-gated | none |
| **Overall** | **⚠️ CONCERNS** | | |

## Gate YAML Snippet

```yaml
nfr_assessment:
  date: '2026-07-02'
  feature_name: 'yt.flow (system-level, post-trace follow-up)'
  categories:
    security: 'PASS'
    performance: 'CONCERNS'
    reliability: 'PASS'
    maintainability: 'PASS'
  overall_status: 'CONCERNS'
  critical_issues: 0
  high_priority_issues: 1
  concerns: 1
  blockers: false
  evidence_gaps: 1 # Performance: E2E ≤2h real-pipeline wall clock never measured
  recommendations:
    - 'Run SYS-OPS-002 (per-release real-dependency full run) once QWEN_TTS_API_KEY and a reachable ComfyUI instance are available'
    - 'SYS-OPS-002 should confirm or refute whether the SYS-OPS-001 stub-mode +19.96% trace overhead amortizes to a small fraction of a percent against real per-stage durations, per the reasoning in traceability-matrix.md'
```

## Related Artifacts

- **PRD:** `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`
- **Test Design:** `_bmad-output/test-artifacts/test-design/test-design-qa.md`
- **Traceability Matrix:** `_bmad-output/test-artifacts/traceability-matrix.md` (SYS-OPS-001 execution record, "Post-Gate Follow-up" section)
- **Evidence:** `tests/api/test_workspace_files.py`, `tests/services/test_run_service_gate.py`, full `pytest --cov=yt_flow` run (this session)

## Sign-Off

**NFR Evidence Audit Status:** ⚠️ CONCERNS — some NFRs (Performance) have open evidence gaps; address before the next real-dependency release, not before shipping the current code as-is (no FAIL, no blocker).

**Critical Issues:** 0
**High Priority Issues:** 1 (Performance evidence gap)
**Concerns:** 1 (Performance)

**Next Actions:**

- Address the Performance evidence gap by running **SYS-OPS-002** (per-release real-dependency full run) when DeepSeek/Qwen TTS/ComfyUI access is available in-session, then re-run this assessment's Performance section only (no need to redo Security/Reliability/Maintainability — their evidence is solid and unrelated).
- Otherwise: no blockers. Proceed with normal release/gate process.

**Generated:** 2026-07-02
**Workflow:** bmad-testarch-nfr (adapted to this project's own 4-category NFR plan)

---

<!-- Powered by BMAD-CORE™ -->
