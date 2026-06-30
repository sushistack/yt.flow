# Story 1.1: Langfuse Environment Verification

Status: ready-for-dev

<!-- Ultimate context engine analysis completed - comprehensive developer guide created -->

## Story

As Jay,
I want Langfuse homelab connectivity and all `YTFLOW_` environment variables verified before any node is built,
so that Prompt Hub migration and `@observe` instrumentation have a confirmed foundation.

## Acceptance Criteria

1. Given `YTFLOW_LANGFUSE_HOST`, `YTFLOW_LANGFUSE_PUBLIC_KEY`, and `YTFLOW_LANGFUSE_SECRET_KEY` are set in `.env`, when `python -c "from langfuse import Langfuse; Langfuse().auth_check()"` runs, then it returns `True` with no exception.
2. Given `config.py` uses Pydantic settings with the `YTFLOW_` prefix, when the settings object is instantiated, then all Langfuse fields are non-empty and type-validated.
3. Given the `.env` file is missing or a key is wrong, when `config.py` is loaded, then `ValidationError` is raised with the missing field name.

## Tasks / Subtasks

- [ ] Establish the minimum Python package substrate for this story only (AC: 1, 2, 3)
  - [ ] Create the smallest `pyproject.toml` needed for Python 3.12, `uv`, `langfuse`, `pydantic-settings`, `pydantic`, `pytest`, and `python-dotenv` or Pydantic dotenv loading.
  - [ ] Create only the package paths needed by this story: `src/yt_flow/__init__.py` and `src/yt_flow/config.py`.
  - [ ] Do not create the full `domain/`, `pipeline/`, `services/`, `db/`, or `api/` scaffold in this story; Story 1.2 owns that broader structure.
- [ ] Implement `src/yt_flow/config.py` (AC: 2, 3)
  - [ ] Define a settings class using `pydantic_settings.BaseSettings` and `SettingsConfigDict(env_prefix="YTFLOW_", env_file=".env", extra="ignore")`.
  - [ ] Require `langfuse_host`, `langfuse_public_key`, and `langfuse_secret_key` as non-empty strings.
  - [ ] Provide a tiny helper such as `get_settings()` only if useful; avoid speculative abstractions.
  - [ ] Ensure missing values raise Pydantic `ValidationError` that includes the missing field name.
- [ ] Verify Langfuse SDK authentication against the homelab instance (AC: 1)
  - [ ] Add a minimal verification command or script that loads `YTFLOW_` settings and calls `Langfuse(...).auth_check()`.
  - [ ] Preserve compatibility with the story's explicit smoke command, or document any unavoidable SDK v4 constructor requirement in the test/README notes.
  - [ ] Do not print secret values. Verification output may print only boolean status and host.
- [ ] Add focused tests (AC: 2, 3)
  - [ ] Test successful settings load from environment variables without requiring real Langfuse network access.
  - [ ] Test missing `YTFLOW_LANGFUSE_PUBLIC_KEY`, `YTFLOW_LANGFUSE_SECRET_KEY`, and `YTFLOW_LANGFUSE_HOST` produce `ValidationError` with field names.
  - [ ] Keep the real `auth_check()` as an explicit smoke check, not a default unit test, so CI/local tests do not depend on homelab availability.
- [ ] Update local developer docs minimally (AC: 1)
  - [ ] Add a `.env.example` with placeholder `YTFLOW_LANGFUSE_HOST`, `YTFLOW_LANGFUSE_PUBLIC_KEY`, and `YTFLOW_LANGFUSE_SECRET_KEY`.
  - [ ] Add or update a short run note in `CLAUDE.md` only if needed after implementation; avoid broad documentation churn.

## Dev Notes

### Scope Boundary

This is the blocker story for Epic 1. It proves Langfuse connectivity and configuration before Prompt Hub migration and pipeline node instrumentation begin. The repo currently has no Python source tree; only planning artifacts and BMAD files exist. Because Story 1.1 acceptance criteria require `config.py` to load, this story must create the minimal package substrate needed for config and tests, but must not take over Story 1.2's full scaffold/domain-type work.

### Architecture Compliance

- Follow AD-1 layering from the start: `config.py` sits at `src/yt_flow/config.py` and should not import future `api/`, `services/`, `pipeline/`, `db/`, or `domain/` modules. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1--Layer-dependency-direction`]
- Config convention is Pydantic settings with env prefix `YTFLOW_`; model identifiers and operational settings must be config-driven, not hardcoded. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions`]
- Langfuse observability failures must be non-fatal for later pipeline execution, but this story's explicit purpose is to fail fast when the environment is missing or credentials are invalid. Keep those concerns separate: settings validation should fail on missing env; future runtime tracing should catch/log Langfuse send failures. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10--Operational-envelope`]
- Use Python 3.12 and `uv`. Architecture current stack supersedes older version pins in the epic inventory where they conflict. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack`]

### Library / Framework Requirements

- Use `pydantic-settings`, not legacy `pydantic.BaseSettings`. Pydantic's current settings docs show `BaseSettings` and `SettingsConfigDict` imported from `pydantic_settings`, with `env_prefix` controlling environment variable names. [Source: `https://docs.pydantic.dev/latest/concepts/pydantic_settings/`]
- Use Langfuse Python SDK 4.x per the architecture stack. Official Langfuse docs now refer to SDK setup with public key, secret key, and a base URL/host for self-hosted instances; the project-facing env names remain `YTFLOW_LANGFUSE_HOST`, `YTFLOW_LANGFUSE_PUBLIC_KEY`, and `YTFLOW_LANGFUSE_SECRET_KEY`. Map the `YTFLOW_` settings into the SDK constructor instead of leaking raw `LANGFUSE_` env requirements through the app. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack`; `https://langfuse.com/docs/observability/sdk/overview`]
- The epic acceptance command is `python -c "from langfuse import Langfuse; Langfuse().auth_check()"`. If SDK 4.x requires explicit constructor arguments unless standard `LANGFUSE_*` env vars are set, add a project smoke command that instantiates `Langfuse(public_key=settings.langfuse_public_key, secret_key=settings.langfuse_secret_key, host/settings base URL=settings.langfuse_host)` and calls `auth_check()`, while clearly noting the reason in the story completion notes.

### File Structure Requirements

Expected new files for this story:

- `pyproject.toml` - minimal Python project metadata and dependencies required by Story 1.1.
- `.env.example` - placeholder Langfuse env names only; never commit `.env`.
- `src/yt_flow/__init__.py` - package marker.
- `src/yt_flow/config.py` - Pydantic settings.
- `tests/test_config.py` - validation-focused unit tests.
- Optional: `scripts/check_langfuse.py` or equivalent, only if it keeps the auth smoke check simple and reusable.

Existing files likely touched:

- `CLAUDE.md` - only if a short run command is needed.

Do not modify `_bmad-output/planning-artifacts/*` as part of implementation. Do not create future graph, domain, database, API, or frontend files in this story.

### Current Repository State

- Source tree does not exist yet; `rg --files -g '!_bmad-output/**'` currently returns only `CLAUDE.md`.
- `.gitignore` ignores `_bmad`, `.agents`, `.claude`, and `.github/agents`; it does not yet ignore `.env`, `yt_flow.db`, `workspace/`, `.venv/`, Python caches, or build outputs. The dev agent should update `.gitignore` only for immediate safety if implementing this story, especially to prevent committing `.env`.
- No previous story file exists because this is Epic 1 Story 1.

### Testing Requirements

- Unit tests should not require a live Langfuse server. Mock env via pytest `monkeypatch` or instantiate settings with controlled env inputs.
- Include at least one positive config load test and one missing-field validation test. The missing-field test must assert field names are visible in the `ValidationError`.
- Treat real `auth_check()` as a manual/local smoke test because it depends on Jay's homelab Langfuse instance and credentials.
- Do not print or snapshot secret values in tests, logs, exceptions, or docs.

### Previous Story Intelligence

No previous implementation story exists. Recent commits are documentation-only:

- `2390ead` initialized sprint status tracking.
- `4be98ee` added epic breakdown and implementation readiness report.
- Earlier commits added UX, architecture, and PRD artifacts.

Actionable implication: there are no established code patterns yet beyond the architecture spine and `CLAUDE.md` Ponytail rules. Keep the first code small, explicit, and easy for Story 1.2 to extend.

### Project Rules From CLAUDE.md

- Use the Ponytail ladder: avoid speculative abstractions, use installed/standard tools where enough, and prefer the minimum code that works.
- No one-implementation interfaces.
- No boilerplate scaffolding for later.
- Mark deliberate simplifications with `# ponytail:` only when it clarifies a trade-off.

### References

- `_bmad-output/planning-artifacts/epics.md#Story-1.1-Langfuse-환경-검증`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F2--Observability-Langfuse`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F3--Prompt-Management-Langfuse-Prompt-Hub`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10--Operational-envelope`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack`
- `CLAUDE.md#Code-Philosophy--Ponytail-always-active`
- `https://docs.pydantic.dev/latest/concepts/pydantic_settings/`
- `https://langfuse.com/docs/observability/sdk/overview`

## Dev Agent Record

### Agent Model Used

TBD by dev-story agent

### Debug Log References

TBD

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List

TBD by dev-story agent
