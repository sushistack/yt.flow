# E2E Tests (Playwright)

Browser-level E2E for yt.flow, targeting the **FastAPI-served build** (`frontend/dist` mounted at `/app` — see `src/yt_flow/api/main.py`), not the Vite dev server. Same origin as production, so no CORS/proxy setup.

## Setup

```bash
npm install                      # root package.json — Playwright only, separate from frontend/'s Vitest
npx playwright install --with-deps chromium
uv sync                          # pulls in uvicorn (dev dep, used to serve the app for E2E)
(cd frontend && npm run build)   # produces dist/ so FastAPI can mount /app
```

## Running

```bash
npx playwright test              # headless, boots uvicorn automatically (webServer)
npx playwright test --headed
npx playwright test --debug
npx playwright test --ui
```

`playwright.config.ts`'s `webServer` starts `uv run uvicorn yt_flow.api.main:app` and waits for `${BASE_URL}/app/` to respond. Set `PORT`/`BASE_URL` env vars to point at a different port; real `.env` (Langfuse keys etc.) is picked up the same way the pytest suite picks it up (pydantic-settings).

## Architecture

- `playwright.config.ts` (root) — single local env (no staging/prod config map yet), standard timeouts (action 15s / nav 30s / expect 10s / test 60s), HTML+JUnit+list reporters, trace/screenshot/video retained on failure.
- `e2e/support/fixtures/merged-fixtures.ts` — `mergeTests` combining `@seontechnologies/playwright-utils`'s `api-request` + `log` fixtures. Import `test`/`expect` from here, not `@playwright/test` directly, so new fixtures merge in one place.
- `e2e/smoke.spec.ts` — framework verification only (UI loads, API reachable). Real scenarios (SYS-E2E-002: dashboard → create run → approve gate → artifact panel) come in a later session.

## Conventions

- Import `{ test, expect }` from `./support/fixtures/merged-fixtures`, not `@playwright/test`.
- Tag tests: `@P0`/`@P1`/... for priority, `@API` for pure-API (no browser) specs — see `test-design-qa.md`.
- `data-testid` selectors for anything not identifiable by role/text.
- No hard waits (`page.waitForTimeout`) — use `expect(...).toBeVisible()` / `recurse` polling instead.

## CI

Not wired yet. Planned as a **nightly** job (not PR-blocking) once stub-server-mode exists — see `_bmad-output/test-artifacts/next-session-e2e-02-stub-mode.md` (next session). Running E2E against the real backend in CI would require real provider API keys, which isn't the point of framework/regression smoke coverage.

## Knowledge base

`_bmad-output/test-artifacts/test-design/test-design-qa.md` (SYS-E2E-002), `.claude/skills/bmad-testarch-framework/resources/knowledge/{overview,playwright-config,api-request,fixtures-composition,log}.md`.
