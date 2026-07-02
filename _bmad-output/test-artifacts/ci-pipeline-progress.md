---
stepsCompleted: ['step-01-preflight', 'step-02-generate-pipeline', 'step-03-configure-quality-gates', 'step-04-validate-and-summary']
lastStep: 'step-04-validate-and-summary'
lastSaved: '2026-07-02'
---

# CI Pipeline Setup Progress

## Step 1: Preflight

- **Git repository**: OK — remote `origin` → https://github.com/sushistack/yt.flow
- **test_stack_type**: `fullstack` (auto-detected)
  - Backend: Python 3.12 (`pyproject.toml`, pytest 9.x, uv lockfile)
  - Frontend: Vite + React 18 + Vitest 3 (`frontend/`)
- **test_framework**: pytest (backend), vitest (frontend)
- **Local test status**: PASS
  - Backend: `uv run pytest` — 443 passed, 1 skipped
  - Frontend: `npm test` (vitest run) — 94 passed (17 files)
  - Fixes applied during preflight:
    - Added missing dependency `@tanstack/react-virtual` to `frontend/package.json` (imported by `SCPPickerDialog.tsx` but never declared — would break `npm ci` in CI)
    - Fixed fetch mocks in 7 test files: success-path mocks now implement `text()` (used by the shared `json()` helper in `api.ts`); artifacts-endpoint mocks keep `json()` (used directly by `getStageArtifacts`)
- **ci_platform**: `github-actions` (no existing CI config; git remote is github.com)
- **Environment context**:
  - Python: 3.12 (`requires-python >=3.12,<3.13`), package manager `uv` (uv.lock) → cache uv
  - Node: no `.nvmrc` / no `engines` field → default Node 24 LTS; `frontend/package-lock.json` present → `npm ci` + npm cache
  - Caveat: tests emit Langfuse OTEL export noise when local Langfuse (localhost:3000) is down — CI must disable/neutralize Langfuse tracing env

## Step 2: Generate Pipeline

- **Execution mode**: sequential (single YAML output; no parallel work units needed)
- **Output**: `.github/workflows/test.yml` (github-actions template, adapted)
- **Stages**: lint (ruff + tsc, parallel per stack) → test (pytest + vitest, parallel per stack) → burn-in (10x both suites, schedule/dispatch only) → report (step summary + artifact aggregation)
- **Adaptations from template**:
  - Branches `[master]` (repo default; no main/develop)
  - No Playwright/browser steps — no E2E framework in this project
  - Sharding skipped (`# ponytail:` comment in YAML) — backend ~35s, frontend ~2s; upgrade path: pytest-xdist / `vitest --shard`
  - Dependency caching: `astral-sh/setup-uv@v5` (enable-cache) + `actions/setup-node@v4` npm cache keyed on `frontend/package-lock.json`
  - Required env injected workflow-wide: `YTFLOW_LANGFUSE_HOST=http://localhost:9` (+ dummy keys) — Settings() has no defaults for these; port 9 makes the OTEL exporter fail fast
  - JUnit XML artifacts: `pytest --junitxml`, `vitest --reporter=junit`; uploaded `if: always()`, 30-day retention
  - Burn-in runs weekly (cron) + `workflow_dispatch`, not per-PR — suites are deterministic unit tests
- **Local verification**: `ruff check` clean, `tsc -b` clean, pytest 443 passed with `.env` removed + dummy env (CI simulation), vitest junit reporter produces `test-results/vitest-junit.xml`, workflow YAML parses
- **Contract testing**: skipped (`tea_use_pactjs_utils: false`)
- **Fixes applied to make gates green**:
  - `ruff check --fix` (23 unused imports/vars) + 4 manual F841 fixes (`characters.py`, 2 test files)
  - Removed 2 unused TS imports (`CharacterDetailPage.tsx`, `CharacterListPage.tsx`)

## Step 3: Quality Gates & Notifications

- **Burn-in** (fullstack → enabled by default, per `ci-burn-in.md`):
  - `burn-in-changed` (per-PR): diffs against `origin/${base_ref}` (`--diff-filter=d` to skip deleted files), runs only changed `tests/**/test_*.py` and `frontend/src/**/*.test.ts(x)` files 10x each. `base_ref` passed through `env:` intermediary (script-injection guard).
  - `burn-in-full` (weekly cron + `workflow_dispatch`): both full suites 10x.
- **Quality gates**:
  - Tests are not priority-tagged (no P0/P1 markers) → effective gate is **100% pass**: any lint/typecheck/test/burn-in failure fails the workflow. This satisfies P0=100%, P1≥95% trivially; introduce pytest/vitest tag-based priority gating only when the suite gains priority markers.
  - Merge enforcement requires **branch protection on `master`** (manual, repo admin): require status checks `Lint (backend / ruff)`, `Lint (frontend / tsc)`, `Test (backend / pytest)`, `Test (frontend / vitest)`, `Burn-In (changed tests, 10x)`.
  - Contract-testing gates: N/A (`tea_use_pactjs_utils: false`).
- **Notifications**:
  - GitHub default failure emails + PR status checks + `$GITHUB_STEP_SUMMARY` report job (aggregated per-stage results, flaky-test warning, artifact links on the run page).
  - Slack: not configured — no webhook secret exists. To add later: `SLACK_WEBHOOK_URL` secret + a `if: failure()` notify step in `report`.

## Step 4: Validate & Summary

Checklist validation (`checklist.md`) — PASS with documented deviations:

- ✅ Config file at `.github/workflows/test.yml`, YAML valid, correct commands per stack, triggers (push/PR/schedule/dispatch), caching keyed on lockfiles, timeouts set, no secrets in config, no unsafe `${{ }}` interpolation (`base_ref` via `env:`)
- ✅ Burn-in: changed-tests 10x on PRs (`|| exit 1`), full-suite 10x weekly — matches `ci-burn-in.md`
- ✅ Helper script: `scripts/ci-local.sh` (executable, syntax-checked)
- ✅ Docs: `docs/ci.md` (pipeline guide, secrets = none, merge-gate setup, troubleshooting)
- ⚠️ Deviations (deliberate, ponytail):
  - No matrix sharding — suites are 35s/2s; parallelism comes from per-stack jobs. Upgrade path documented.
  - JUnit artifacts uploaded `if: always()` (not failure-only) — small XML, enables trend tracking.
  - No retry action — deterministic unit suites; retries would mask flakiness that burn-in is meant to surface.
  - Helper scripts reduced to one (`ci-local.sh`); test-changed/burn-in logic lives in the workflow itself.
- `workflow.on_complete` resolved empty at activation → no completion hook.

**Remaining user actions**: commit + push, enable branch protection on `master` with the five required checks, optionally trigger `workflow_dispatch` for a first full burn-in.
