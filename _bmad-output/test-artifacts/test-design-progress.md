---
workflowStatus: 'completed'
totalSteps: 5
stepsCompleted: ['step-01-detect-mode', 'step-02-load-context', 'step-03-risk-and-testability', 'step-04-coverage-plan', 'step-05-generate-output']
lastStep: 'step-05-generate-output'
nextStep: ''
lastSaved: '2026-07-02'
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/epics.md (outline)
  - _bmad-output/implementation-artifacts/sprint-status.yaml
  - _bmad/tea/config.yaml
  - knowledge/risk-governance.md
  - knowledge/test-levels-framework.md
  - knowledge/adr-quality-readiness-checklist.md
  - knowledge/nfr-criteria.md
  - knowledge/test-quality.md
---

# Test Design Progress — yt.flow

## Step 1: Mode Detection

- **Mode**: System-Level (user explicit choice; PRD + Architecture available)
- **Rationale**: Both PRD/architecture and epic/sprint artifacts exist. User selected System-Level to produce a whole-system test strategy (pipeline + API + UI).
- **Inputs confirmed**:
  - PRD: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`
  - Architecture: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
  - Architecture reviews (ADR-like decision records): `reviews/review-adversary.md`, `reviews/review-rubric-walker.md`, `reviews/review-tech-currency.md`
  - Supplementary: `_bmad-output/planning-artifacts/epics.md`, `sprint-status.yaml` (all stories epics 1–4 done)

## Step 2: Context Loaded

- **Config**: `tea_use_playwright_utils: true`, `tea_use_pactjs_utils: false`, `tea_pact_mcp: none`, `tea_browser_automation: auto`, `test_stack_type: auto` → **detected: fullstack** (Python 3.12/FastAPI/LangGraph backend + React 18/Vite/Vitest frontend)
- **Key extractions from PRD/Architecture**:
  - 44 FRs across F1–F7; NFRs: E2E ≤2h, trace overhead ≤10%, no auth (local-only), SQLite single file, node-level resume, SSE transport
  - External deps: DeepSeek V4, Qwen TTS (cloud), ComfyUI (local HTTP), Langfuse (homelab), FFmpeg subprocess
  - 10 architecture invariants AD-1..AD-10 (layer direction, LangGraph state SoT, interrupt() gates, services-owns-sync, N:M shots, ab_pair_id, single SQLite, update_state edits/retry, ops envelope)
- **Existing test coverage**: substantial — backend `tests/` (api, services, pipeline/nodes, domain, ~30 files), frontend Vitest component tests (~20 files). No E2E/Playwright suite. No load/perf tests. No CI pipeline detected yet.
- **Knowledge fragments loaded**: risk-governance (core), test-levels-framework (core), adr-quality-readiness-checklist (extended, full 29 criteria), nfr-criteria (core sections), test-quality (DoD principles). Playwright-utils fragments deferred to on-demand (design phase needs patterns, not APIs).

## Step 3: Testability Review & Risk Assessment

### 🚨 Testability Concerns (actionable first)

1. **No CI-runnable full-pipeline E2E path.** A real end-to-end run costs up to 2h (ComfyUI-dominated) and consumes paid APIs (DeepSeek, Qwen). There is no defined "stub profile" (fake LLM / fake TTS / fake ComfyUI / fake FFmpeg) to drive the full LangGraph graph (5 stages + 5 gates) in minutes. Without it, gate/resume/retry regressions surface only in manual runs. → drives R-005.
2. **Trace-overhead NFR (≤10%) has no measurement harness.** No defined traced-vs-untraced comparison method; threshold exists but evidence source is UNKNOWN. → NFR gap, R-004.
3. **LLM output non-determinism at `scenario_node`.** Director-pattern output (shots, `sentence_indices`, camera fields, `None` handling per AD-5) is schema-critical; malformed LLM output is the most probable runtime failure. Needs adversarial fixture tests (missing fields, empty shots, out-of-range indices), not just happy-path.
4. **Silent observability degradation (AD-10).** Langfuse failures are non-fatal by design — a test must prove the pipeline continues AND the error is logged; otherwise the "30-minute diagnosis" goal silently dies.
5. **Concurrent mutation of a run is under-specified.** Retry-while-running, PATCH-while-running, double gate approve: API-level guard behavior (expected 409/conflict) is not specified in the PRD; tests must pin it down. → R-009.
6. **No CI pipeline detected.** ~50 test files exist (backend pytest + frontend Vitest) but nothing enforces them. → R-010.

### ✅ Testability Assessment Summary (strengths)

- **Controllability**: Stage nodes are pure functions of `PipelineState` (spine) — unit-testable without LangGraph runtime; external services isolated behind client modules (mockable, `test_comfyui_client.py` exists); 100% of business logic reachable via REST (FR-24–34) — no UI dependency for critical paths; single SQLite file → per-test temp DB gives cheap isolation.
- **Observability**: Langfuse span per node + linked trace tree (FR-10–12); failed node carries inputs+exception (FR-13); SSE events (`stage_entry/stage_exit/gate_pending/run_failed`) are deterministic assertion points for integration and E2E tests.
- **Reliability**: `AsyncSqliteSaver` checkpoints enable reproducible resume tests; fixed graph topology (5 gates always present, AD-3) removes combinatorial config space; no auth/multi-tenancy shrinks the security surface.

### ASRs (Architecturally Significant Requirements)

| ID | ASR | Source | Class |
|----|-----|--------|-------|
| ASR-1 | Gate interrupt/resume correctness: approve advances, reject loops/ends, gate node is sole `gate_states` writer | AD-3, FR-9/29 | **ACTIONABLE** |
| ASR-2 | Resume-from-last-node after failure & explicit full restart | FR-7/8, AD-7 | **ACTIONABLE** |
| ASR-3 | `runs` projection never leads LangGraph state; DB write only after confirmation event | AD-2, AD-4 | **ACTIONABLE** |
| ASR-4 | Artifact edit & stage retry via `graph.update_state()` keep checkpoint/file/DB coherent | AD-8, AD-9, FR-30/34 | **ACTIONABLE** |
| ASR-5 | E2E run ≤2h, ComfyUI-dominated; excluded from CI, measured operationally | NFR | FYI |
| ASR-6 | A/B winner determination deterministic (pairwise + tiebreaker + quality floor, OQ-6) | FR-23 | **ACTIONABLE** (covered by 4.3 tests — verify in trace step) |
| ASR-7 | No auth by design; only file-serving endpoints carry security exposure | NFR | FYI |

### Risk Register (P×I, 1–3 scale)

| ID | Cat | Risk | P | I | Score | Mitigation | Owner | Timeline |
|----|-----|------|---|---|-------|------------|-------|----------|
| R-001 | TECH | Gate/resume/retry state machine corruption — in-place checkpoint mutation (AD-9) across approve/reject/retry/edit sequences leaves stale stage outputs or wrong `gate_states` | 2 | 3 | **6** | Integration test matrix over gate-transition sequences incl. reject→retry→approve and edit→approve; assert checkpoint + DB + SSE agree | dev | before next release |
| R-002 | DATA | `runs` table desyncs from LangGraph checkpoint (dual representation) | 2 | 2 | 4 | Integration tests asserting projection updates only after LangGraph events (ASR-3) | dev | with R-001 suite |
| R-003 | TECH | External-dependency contract drift: DeepSeek response shape, ComfyUI workflow node IDs (6/7), Qwen timing format; LLM emits malformed scenario JSON | 3 | 2 | **6** | Schema-validation unit tests with adversarial fixtures; recorded-response contract fixtures per client; `None` camera-field handling (AD-5) | dev | immediate |
| R-004 | PERF | Trace overhead >10% or E2E >2h goes unnoticed (no harness) | 2 | 2 | 4 | Stage-duration capture via Langfuse; one measured traced-vs-untraced comparison run per release; NOT in CI | operator | per release |
| R-005 | OPS | No affordable full-graph E2E → regressions in stage wiring/gates ship undetected | 3 | 2 | **6** | Build stub-profile E2E: fake clients driving real LangGraph graph + real FastAPI + real SQLite in minutes | dev | high priority |
| R-006 | SEC | Path traversal / arbitrary file read via artifact & workspace file endpoints | 2 | 2 | 4 | Path-normalization negative tests (`../`, absolute paths, symlinks); verify existing `test_workspace_files.py` covers these | dev | with coverage plan |
| R-007 | BUS | A/B verdict invalid (judge parsing, position-bias reversal, tie/floor logic errors) → wrong prompt promoted | 2 | 2 | 4 | Unit tests over aggregation/tiebreaker/floor (largely done in story 4.3); judge-output parsing fixtures incl. malformed | dev | verify existing |
| R-008 | TECH | SSE delivery gaps (missed `gate_pending`, dropped reconnect) → run stalls invisibly in UI | 2 | 2 | 4 | SSE integration tests (event order, queue cleanup); frontend reconnection/refetch-on-reconnect test | dev | with coverage plan |
| R-009 | DATA | Concurrent run mutations (retry while running, PATCH while running, double approve) corrupt state | 2 | 3 | **6** | Specify + test API guards: invalid-state operations return 4xx and never touch checkpoint | dev | before next release |
| R-010 | OPS | No CI — existing ~50 test files not enforced on change | 3 | 2 | **6** | Stand up CI (pytest + vitest + lint) via `testarch-ci` workflow; PR-blocking | operator | immediate |

**High risks (score ≥ 6): R-001, R-003, R-005, R-009, R-010.** No score-9 critical blocker.

### NFR Planning Assessment

| NFR | Threshold | Status | Planned evidence |
|-----|-----------|--------|------------------|
| Performance — E2E duration | ≤ 2h (automated time only, human gate wait excluded) | Defined | Langfuse trace duration per run; operational measurement, not CI (ASR-5) |
| Performance — trace overhead | ≤ 10% of run time | Defined, **measurement method UNKNOWN** | Clarification item → traced vs. Langfuse-disabled comparison run; feeds R-004 |
| Reliability — resume | Node-level resume after failure | Defined | Integration tests: kill mid-stage → resume from checkpoint (ASR-2) |
| Reliability — observability degradation | Langfuse down ⇒ pipeline unaffected + error logged | Defined (AD-10) | Integration test with Langfuse client stubbed to raise |
| Security — file serving | No file outside `workspace/` served | Implied (not in PRD) | API negative tests (R-006); no auth NFR by design (accepted) |
| Error visibility | Failed node surfaces node, inputs, exception in trace | Defined (FR-13) | Integration test asserting trace error payload |
| Scalability | N/A — single operator, local | Out of scope | — |
| Maintainability | Tests follow quality DoD (deterministic, isolated, <1.5min, cleanup) | Adopted from knowledge base | Test review workflow post-implementation |

**Boundary note**: this plans NFR validation only; PASS/CONCERNS/FAIL assessment happens in `nfr-assess` after evidence exists.

### Highest-priority findings

1. **R-010 (CI)** — cheapest, unlocks everything else.
2. **R-005 (stub-profile E2E)** — the single biggest structural gap; makes ASR-1/2/3/4 testable end-to-end.
3. **R-001 + R-009 (gate/retry/concurrency integration matrix)** — protects the core product invariant (checkpoint is truth).
4. **R-003 (LLM/external contract fixtures)** — highest-probability runtime failure.

## Step 4: Coverage Plan & Execution Strategy

**Convention**: IDs `SYS-{LEVEL}-{SEQ}`. Levels: UNIT / INT (API+graph integration, pytest) / COMP (frontend Vitest) / E2E (stub-profile full graph). Existing coverage is credited — scenarios marked **[verify-existing]** mean: confirm the named test file covers it, extend only the gaps. No duplicate coverage across levels.

### Coverage Matrix

| ID | Priority | Scenario | Level | Risk/ASR | Existing? |
|----|----------|----------|-------|----------|-----------|
| SYS-INT-001 | P0 | Gate transition matrix: approve advances stage; reject(scenario)→END; reject(image/tts/subtitle/video)→re-run stage; gate node is sole `gate_states` writer | INT | R-001, ASR-1 | [verify-existing] `tests/pipeline/test_gates.py`, `tests/api/test_gate.py` |
| SYS-INT-002 | P0 | Resume after mid-stage failure re-executes only the failed node from checkpoint; explicit restart re-runs from scenario | INT | ASR-2 | [verify-existing] `tests/services/test_run_service_resume.py` |
| SYS-INT-003 | P0 | Retry nullifies stage outputs via `update_state(as_node=stage)` then re-executes; PATCH edit persists to checkpoint + rewrites file; subsequent approve proceeds with edited/retried state | INT | ASR-4, R-001 | [verify-existing] `tests/api/test_stages.py`, `test_stage_artifacts.py` |
| SYS-INT-004 | P0 | Concurrency guards: retry-while-running, PATCH-while-running, double approve, approve on non-pending stage → 4xx, checkpoint untouched | INT | R-009 | gap — behavior must first be specified |
| SYS-E2E-001 | P0 | Stub-profile full-graph run: fake DeepSeek/ComfyUI/Qwen/FFmpeg clients + real graph + real FastAPI + temp SQLite; POST /runs → 5× gate approve via API → complete; SSE event order asserted; artifacts on disk | E2E | R-005, ASR-1/2/3 | gap — **the** structural investment |
| SYS-UNIT-001 | P0 | Scenario output hardening: malformed LLM JSON, missing/None camera fields (AD-5 defaults in image_node), out-of-range `sentence_indices`, empty shots | UNIT | R-003 | partial — `tests/pipeline/nodes/test_scenario.py`, `test_image.py`; add adversarial fixtures |
| SYS-INT-005 | P1 | Projection sync: `runs` row updates only after LangGraph event; `astream()` exception → `status=failed` + `run_failed` SSE before loop close | INT | R-002, ASR-3 | [verify-existing] `tests/services/test_run_service_gate.py` |
| SYS-INT-006 | P1 | SSE lifecycle: `gate_pending` emitted on interrupt; event order per stage; queue cleanup on client disconnect; reconnect → client can recover current state | INT | R-008 | [verify-existing] `tests/api/test_sse.py` |
| SYS-UNIT-002 | P1 | External client contracts from recorded fixtures: ComfyUI (prompt injection at workflow nodes 6/7, poll loop, error paths), Qwen TTS (word-timing parse), DeepSeek (error/timeout) | UNIT | R-003 | partial — `test_comfyui_client.py`, `test_tts.py`; add drift fixtures |
| SYS-INT-007 | P1 | Langfuse degradation: tracing client raises → stage completes, run unaffected, error logged | INT | AD-10 | gap |
| SYS-INT-008 | P1 | Error visibility: failed node's trace payload carries stage, inputs, exception (FR-13) | INT | NFR | gap |
| SYS-INT-009 | P1 | File-serving negatives: `../`, absolute paths, symlink escape on artifact/workspace endpoints → 4xx | INT | R-006 | [verify-existing] `tests/api/test_workspace_files.py` |
| SYS-UNIT-003 | P1 | A/B verdict: pairwise + order-reversal 2/3 majority, tie→rule tiebreaker, quality floor (all axes ≥2), no-winner path; malformed judge output fixtures | UNIT | R-007, ASR-6 | [verify-existing] story 4.2/4.3 tests (`test_eval_service.py`, `test_ab_run.py`) |
| SYS-COMP-001 | P1 | Frontend SSE client: reconnect after drop refetches run state; gate controls render/disable per gate state | COMP | R-008 | [verify-existing] story 3.5 tests in `RunDetail.test.tsx` |
| SYS-INT-010 | P2 | Artifact retrieval content types: video download (FR-26), per-stage artifacts read from LangGraph state not DB (FR-28, AD-7) | INT | AD-7 | [verify-existing] `test_stage_artifacts.py` |
| SYS-INT-011 | P2 | `GET /scps` lifespan in-memory load + filter; A/B run creation linkage `ab_pair_id` + variant B config (AD-6) | INT | — | [verify-existing] `test_scps.py`, `test_ab_run.py` |
| SYS-E2E-002 | P2 | UI smoke on stub backend (Playwright): dashboard → create run → approve a gate → artifact panel renders per stage type | E2E | R-005 (UI wiring) | gap — only if UI regressions start hurting; component tests carry most weight |
| SYS-INT-012 | P2 | Alembic migration roundtrip on temp DB; SQLModel/checkpoint tables coexist in one file | INT | AD-7 | gap |
| SYS-OPS-001 | P3 | Trace-overhead measurement runbook: one traced vs Langfuse-disabled comparison run per release; record stage durations | manual | R-004 | gap — runbook, not code |
| SYS-OPS-002 | P3 | Real-dependency full run per release (manual gate approval, real ComfyUI/DeepSeek/Qwen) with checklist | manual | ASR-5 | existing practice, formalize checklist |

### NFR Coverage & Evidence Plan (for later `nfr-assess`)

| NFR | Validation | Evidence artifact |
|-----|-----------|-------------------|
| Reliability (resume, gates, degradation) | SYS-INT-001/002/007 | pytest CI report |
| Error visibility (FR-13) | SYS-INT-008 | pytest report + sample Langfuse trace link |
| Security (file serving) | SYS-INT-009 | pytest report |
| Performance (≤2h, ≤10% overhead) | SYS-OPS-001/002 | run log + Langfuse trace durations, per release |
| Maintainability | test-quality DoD adherence | `test-review` workflow output; CI green history |

Blockers/assumptions: R-009 guard behavior unspecified in PRD (must specify before SYS-INT-004); trace-overhead method assumed = env-flag disable comparison.

### Execution Strategy

- **PR (blocking)**: backend pytest (unit+INT) + frontend Vitest — target <10 min. Requires CI (R-010) first.
- **Nightly**: SYS-E2E-001 stub-profile suite (+ SYS-E2E-002 if built); burn-in new tests.
- **Per release (manual)**: SYS-OPS-001 overhead measurement, SYS-OPS-002 real-dep run.

### Resource Estimates (ranges)

- P0: ~20–35h (SYS-E2E-001 stub harness is the bulk, ~10–18h)
- P1: ~12–20h (mostly verify-existing + targeted gap tests)
- P2: ~6–12h
- P3: ~2–4h (runbooks)
- **Total: ~40–70h, 2–4주 (파트타임 기준)**

### Quality Gates

- P0 pass rate = 100%; P1 ≥ 95%
- High risks (R-001/003/005/009/010) mitigated or waived-with-owner before next release
- Line coverage ≥ 80% on `services/`, `pipeline/`, `api/` (frontend: component-test coverage on interactive components)
- CI blocking on PR (closes R-010)
- Every in-scope NFR has an identified evidence artifact (table above); PASS/FAIL deferred to `nfr-assess`

## Step 5: Outputs Generated

- Execution mode: `auto` → resolved **sequential** (both docs derive from one in-context analysis; parallel workers add no value)
- Outputs (per `test_design_output` config dir):
  - `_bmad-output/test-artifacts/test-design/test-design-architecture.md`
  - `_bmad-output/test-artifacts/test-design/test-design-qa.md`
  - `_bmad-output/test-artifacts/test-design/yt.flow-handoff.md` (BMAD handoff)
- Checklist validation: risk matrix (IDs/categories/P×I/mitigations/owners) ✓; NFR planning with UNKNOWNs as blockers (B-1/B-3), no PASS/FAIL assigned ✓; coverage matrix no cross-level duplication, existing ~50 test files credited via [verify-existing] ✓; execution strategy simple PR/Nightly/Per-release ✓; interval estimates only ✓; no test code in architecture doc ✓; playwright-utils example with assertions in QA doc ✓; cross-doc risk IDs/blockers consistent ✓; no browser sessions opened ✓
- Open assumptions: client seam injectable via config (B-2 to confirm); overhead measurement = on/off wall-clock comparison (pending B-3); solo operator holds all owner roles
- `workflow.on_complete` resolved empty at activation → hook skipped

## Post-Design Update (2026-07-02): Blocker Decisions

User resolved all three pre-test-development blockers:

- **B-1 → strict guard**: `retry`/`PATCH artifact` allowed only when `run.status ∈ {awaiting_approval, failed, complete}`; `status=running` → 409, checkpoint untouched. Code check confirmed double-approve (runs.py:129) and pending-stage retry (run_service.py `_RETRYABLE`) already guarded; the gap is the missing `status=running` check in `retry_stage()`/`edit_artifact()`.
- **B-2 → hybrid stub**: fake ComfyUI/FFmpeg (deterministic tiny artifacts) + recorded DeepSeek/Qwen cassette fixtures, wired at test level (fixtures/monkeypatch); no production stub flag. Cassettes must be re-recorded when Prompt Hub templates or pinned model IDs change; per-release real run (SYS-OPS-002) is the backstop.
- **B-3 → config flag**: add `YTFLOW_LANGFUSE_ENABLED` (default true) to config.py; false → `@observe` no-op. Enables AD-10 degradation test and on/off overhead comparison.

All three design docs updated to reflect decisions (blockers → resolved, R-005/R-009 mitigation plans, dependencies, entry criteria).
