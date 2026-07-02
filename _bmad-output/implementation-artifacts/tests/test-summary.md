# Test Automation Summary

## Generated Tests

### E2E Tests

- [x] `e2e/dashboard-run-gate-artifacts.spec.ts` — SYS-E2E-002 (P0), Journey 1: dashboard → SCP search/select → create run → SSE-observed gate progression → approve all 5 stage gates → per-stage artifact panel (scenario text / image grid / tts audio / subtitle text / video) → completion.
- [x] `e2e/gate-reject-retry-edit-concurrency.spec.ts` — Journey 2 (P1): scenario inline edit + approve → image approve → explicit `재시도` retry trigger with B-1 concurrency-guard probes (API 409 + UI control hiding) → tts approve → subtitle gate reject (implicit backend retry loop) → subtitle inline edit + re-approve → video approve/download confirms the downstream stage re-runs cleanly → completion.

Config changes:
- `playwright.config.ts`'s `webServer.command` now boots `scripts/run_e2e_stub_server.py` instead of the real app (from Journey 1) — both journeys drive real gate/pipeline transitions and must not hit DeepSeek/Qwen/ComfyUI/ffmpeg for real.
- `playwright.config.ts`: `workers` pinned to `1` everywhere (was `undefined` locally). With two full-pipeline journey specs now sharing one stub-server process, default parallel workers reliably raced each other (SQLite writes, in-process LangGraph `_configs`), timing out unrelated requests. Confirmed via repeated runs before/after.
- `scripts/run_e2e_stub_server.py`: added a 0.5s artificial delay to the image-stage ComfyUI fake (E2E-only; `tests/stubs/fakes.py` itself is untouched so `pytest` stays fast). The stub pipeline re-executes a stage faster than two sequential real HTTP round-trips from Playwright, so without this the B-1 `run.status == "running"` window was unobservable over real HTTP even though it exists — confirmed by probing it directly (raced 2/3 attempts without the delay, 0/6+ with it).
- `e2e/support/helpers.ts` (new): extracted `stageSidebarButton`/`artifactSection`/`approveStage`/`createRun` shared across both specs. While extracting, hardened `createRun`: it now opens Run Detail via the SPA's own client-side `pushState`/`popstate` (mirroring `frontend/src/lib/navigate.ts`) instead of clicking the new dashboard row by SCP-label regex. The row-click was silently flaky — `Dashboard.tsx`'s `onCreated()` optimistically prepends the new run then fires an unawaited `getRuns()` refetch that can reorder the list before the click lands, so `.first()` could resolve to an older same-SCP row from a prior run instead of the new one. Confirmed directly: captured `runId` from the creation response diverged from `page.url()`'s actual run id under this exact race. This affected Journey 1 too (pre-existing, just never triggered before a second full-pipeline spec existed to expose it under repeat local runs).

## Coverage

- SYS-E2E-002 baseline journey (per `test-design-qa.md`): covered.
- Journey 2 from `next-session-e2e-03-generate-tests.md` (gate reject/retry/edit + B-1 concurrency guard): covered.
- Journeys 3–4 (A/B comparison, character management): not built this session — per that file's own guidance, do one journey per session.

## Findings (not fixed — out of scope for test generation)

1. **No SSE signal for run completion.** `run_service._consume` only publishes `stage_entry`/`stage_exit`/`gate_pending`/`run_failed`; after the last stage's gate is approved, the run flips to `status: "complete"` in the DB with no corresponding SSE event. `RunDetail`'s header badge never updates to "완료" without a manual page reload. Both specs verify completion via `GET /runs/{id}` instead of the live UI.
2. **No SPA history-fallback for nested `/app/...` paths.** `GET /app/runs/{id}` 404s directly (confirmed via curl) — the FastAPI `StaticFiles(html=True)` mount only serves `index.html` for `/app/` itself, not for arbitrary sub-paths. Deep-linking or refreshing a Run Detail page breaks.
3. **No frontend-level concurrency guard beyond the retried stage's own controls.** The B-1 backend guard (`run.status not in {awaiting_approval, failed, complete}` → 409) is enforced server-side only. While one stage is retrying, an *already-approved, different* stage's `재시도`/`편집` controls remain visible and clickable in the UI; clicking them surfaces the same generic inline API-error text used for any other failure rather than a proactive disabled state. Journey 2's test asserts the 409 + error text (the guard *is* enforced, correctly), not a UI-level disable, since none exists.
4. **Possible TOCTOU race in `retry_stage`/`edit_artifact`'s B-1 guard.** Reading code only (not exercised by this session's tests, which target a single actor): the `run.status` guard check and the eventual `status="running"` write are separated by `await`s (`_graph.aget_state`/`aupdate_state`), so two genuinely concurrent requests for the same run could both pass the check before either commits. This is a single-operator local app (no auth/multi-user per the PRD), so real-world exposure is low, but flagging for Dev awareness since SYS-INT-004's existing pytest coverage sets up `run.status="running"` via fixture rather than firing two live concurrent requests, so it wouldn't catch this.

## Next Steps

- Consider a backend `run_complete` SSE event (or have the frontend refetch `GET /runs/{id}` after the last gate's `approveGate()` resolves) to close finding #1.
- Consider adding a catch-all route (or `StaticFiles` fallback) so `/app/*` always serves `index.html` when no static asset matches, to close finding #2.
- Decide whether finding #3 (no proactive UI disable during a run-wide B-1 guard) is worth a frontend fix, or whether the current 409-surfaces-as-inline-error behavior is acceptable for a single-operator app.
- Have Dev assess finding #4's TOCTOU window; if real, the fix is likely moving the `status="running"` write earlier (before `aupdate_state`) or holding a per-run asyncio lock across the guard-check-and-write.
- Wire both specs into a nightly CI job (not PR-blocking), per `test-design-qa.md`'s Execution Strategy — not done this session.
- Run Journeys 3–4 in separate sessions per `next-session-e2e-03-generate-tests.md`.
