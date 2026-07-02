---
stepsCompleted: ['step-01-preflight', 'step-02-select-framework', 'step-03-scaffold-framework', 'step-04-docs-and-scripts', 'step-05-validate-and-summary']
lastStep: 'step-05-validate-and-summary'
lastSaved: '2026-07-02'
---

# Framework Setup Progress

## Step 1: Preflight

- **Detected stack**: fullstack (frontend: Vite + React 18 + TS + Vitest; backend: FastAPI + pytest)
- **Frontend package.json**: `frontend/package.json` — no existing E2E config found (no `playwright.config.*` / `cypress.config.*`)
- **Backend manifest**: `pyproject.toml` — pytest suite exists (`tests/`) but is unit/API-level, no conflict with E2E framework
- **Context docs**: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`, `_bmad-output/brainstorm-intent.md`
- **Prior test-design reference**: `_bmad-output/test-artifacts/test-design/test-design-qa.md` (SYS-E2E-002), `tea_use_playwright_utils: true` in `_bmad/tea/config.yaml`
- Prerequisites: PASS

## Step 2: Framework Selection

- **Selected**: Playwright (browser E2E). Backend framework: pytest — already established, no action needed.
- **Rationale**: fullstack repo, API+UI integration testing needed, `next-session-e2e-01-framework.md` and `_bmad/tea/config.yaml` (`tea_use_playwright_utils: true`) already commit to Playwright + `@seontechnologies/playwright-utils` convention. `config.test_framework` is `auto` (no override).

## Step 3: Scaffold

- **Location**: top-level `e2e/` + root `playwright.config.ts` + root `package.json` (new, Playwright-only — kept separate from `frontend/package.json`'s Vitest setup, same reasoning as the pre-existing `vitest.config.ts` split for story 3.2).
- **Base URL / target**: FastAPI-served build (`http://127.0.0.1:8000/app/`), NOT the Vite dev server. Same origin as production (`main.py` mounts `frontend/dist` at `/app`), so no CORS/proxy config needed. `webServer` in `playwright.config.ts` boots `uv run uvicorn yt_flow.api.main:app` and waits on `${BASE_URL}/app/`.
- **New backend dev dependency**: `uvicorn>=0.34` added to `pyproject.toml` `[dependency-groups].dev` — needed to actually run the ASGI app for E2E (previously only `TestClient` was used in pytest).
- **Config**: single local env, no `envConfigMap` (no staging/prod environments exist yet — ponytail: add per-env configs when those environments exist). Standard timeouts (action 15s / nav 30s / expect 10s / test 60s), HTML+JUnit+list reporters, trace/screenshot/video retained on failure.
- **Fixtures**: `e2e/support/fixtures/merged-fixtures.ts` merges only `api-request` + `log` from `@seontechnologies/playwright-utils` (ponytail: `auth-session`/`recurse`/`burn-in` deferred until a real test needs them).
- **Sample test**: `e2e/smoke.spec.ts` — one UI smoke (`/app/` loads, has a title) + one API smoke (`GET /docs` → 200). Both green locally: `npx playwright test` → 2 passed.
- **Verified**: `npm install` (root) + `npx playwright install --with-deps chromium` + `uv sync` (adds uvicorn) + `cd frontend && npm run build` (produces `dist/` for `/app` to mount) all run clean; `npx playwright test` passes using the real `.env` (Settings() picks up Langfuse keys via pydantic-settings/python-dotenv, same as existing pytest suite).
- **CI**: deferred to next session (stub-server-mode) per user decision — a nightly E2E job only makes sense once the server can run in stub mode; wiring it against the real backend/API keys now would be premature.
- **.gitignore**: added `node_modules/` (root), `/test-results/`, `/playwright-report/`.
- **.nvmrc**: `24` (matches existing frontend CI `node-version: 24`).
- **.env.example**: added `PORT`, `BASE_URL` for the E2E target.

## Step 4: Docs & Scripts

- **`e2e/README.md`**: setup, running (local/headed/debug/ui), architecture, conventions, CI plan (deferred), knowledge base pointers.
- **`test:e2e` script**: already added to root `package.json` in Step 3 (`npx playwright test` via `npm run test:e2e`).
- **Backend test commands**: unchanged — `uv run pytest` already established, out of scope for this session.
- **CI decision**: user confirmed — defer nightly E2E workflow wiring to the stub-server-mode session (file 2), since a meaningful nightly job needs the server running in stub mode rather than against the real backend/API keys.

## Step 5: Validation & Summary

**Validated against checklist.md** (generic template — deviations below are deliberate scope calls, not gaps):

- Preflight/selection/config/docs/scripts: PASS
- `npx playwright test` and `npm run test:e2e`: both green (2 passed), using the real `.env` (no CI-only overrides needed)
- `tsc --noEmit` on the three new `.ts` files: no errors
- No secrets in committed files; `.env.example` has placeholders only
- **Deliberately skipped** (checklist assumes a generic app with existing entities/auth):
  - Data factories (`@faker-js/faker`) — no domain entities to factory yet; add when file 3 (test generation) needs seeded run/SCP data
  - Page objects — YAGNI until real scenario tests exist
  - Auth helpers — yt.flow dashboard has no login/auth
  - `TEST_ENV`/`API_URL` env vars — single-environment project (`BASE_URL` covers it; API and UI share an origin)

**Framework**: Playwright + `@seontechnologies/playwright-utils` (backend: existing pytest, untouched).

**Artifacts created**:
- `package.json`, `package-lock.json` (root, Playwright-only)
- `playwright.config.ts` (root)
- `e2e/smoke.spec.ts`, `e2e/support/fixtures/merged-fixtures.ts`, `e2e/README.md`
- `.nvmrc` (24)
- `pyproject.toml` +uvicorn dev dep, `uv.lock` updated
- `.env.example` +`PORT`/`BASE_URL`, `.gitignore` +node_modules/test-results/playwright-report/yt_flow.db* patterns

**Next steps for the user**:
1. `git add` the new files and commit (not done automatically — awaiting user's explicit commit request)
2. Proceed to next session: `next-session-e2e-02-stub-mode.md` (design stub-server-mode for the backend)
3. Then: `next-session-e2e-03-generate-tests.md` (bmad-qa-generate-e2e-tests, real SYS-E2E-002 scenarios)

**Decisions for next session to build on** (per this session's own completion criteria):
- Directory: top-level `e2e/`, not `frontend/e2e/`
- Base URL: FastAPI-served build at `/app/` (not Vite dev server) — stub-mode session should keep this same-origin approach
- Fixtures: `e2e/support/fixtures/merged-fixtures.ts` is the single import point for all future E2E tests
