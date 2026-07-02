# Test Automation Summary

## Generated Tests

### E2E Tests

- [x] `e2e/dashboard-run-gate-artifacts.spec.ts` — SYS-E2E-002 (P0), Journey 1: dashboard → SCP search/select → create run → SSE-observed gate progression → approve all 5 stage gates → per-stage artifact panel (scenario text / image grid / tts audio / subtitle text / video) → completion.

Config change: `playwright.config.ts`'s `webServer.command` now boots `scripts/run_e2e_stub_server.py` instead of the real app — SYS-E2E-002 scenarios drive real gate/pipeline transitions and must not hit DeepSeek/Qwen/ComfyUI/ffmpeg for real.

## Coverage

- SYS-E2E-002 baseline journey (per `test-design-qa.md`): covered.
- Journeys 2–4 from `next-session-e2e-03-generate-tests.md` (gate reject/retry/edit, A/B comparison, character management): not built this session — per that file's own guidance, do one journey per session.

## Findings (not fixed — out of scope for test generation)

1. **No SSE signal for run completion.** `run_service._consume` only publishes `stage_entry`/`stage_exit`/`gate_pending`/`run_failed`; after the last stage's gate is approved, the run flips to `status: "complete"` in the DB with no corresponding SSE event. `RunDetail`'s header badge never updates to "완료" without a manual page reload. The test verifies completion via `GET /runs/{id}` instead of the live UI.
2. **No SPA history-fallback for nested `/app/...` paths.** `GET /app/runs/{id}` 404s directly (confirmed via curl) — the FastAPI `StaticFiles(html=True)` mount only serves `index.html` for `/app/` itself, not for arbitrary sub-paths. Deep-linking or refreshing a Run Detail page breaks. The test navigates via clicking the dashboard row instead of `page.goto()`.

## Next Steps

- Consider a backend `run_complete` SSE event (or have the frontend refetch `GET /runs/{id}` after the last gate's `approveGate()` resolves) to close finding #1.
- Consider adding a catch-all route (or `StaticFiles` fallback) so `/app/*` always serves `index.html` when no static asset matches, to close finding #2.
- Wire this spec into a nightly CI job (not PR-blocking), per `test-design-qa.md`'s Execution Strategy — not done this session.
- Run Journeys 2–4 in separate sessions per `next-session-e2e-03-generate-tests.md`.
