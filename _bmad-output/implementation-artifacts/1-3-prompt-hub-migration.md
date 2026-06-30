# Story 1.3: Prompt Hub Migration

Status: ready-for-dev

<!-- Ultimate context engine analysis completed - comprehensive developer guide created -->

## Story

As Jay,
I want all pipeline prompts migrated from `yt.pipe/templates/` to Langfuse Prompt Hub,
so that every node fetches prompts at runtime with zero hardcoded strings from day one.

## Acceptance Criteria

1. Given prompt source files exist under `/mnt/work/projects/yt.pipe/templates/`, when the migration script runs, then Langfuse Prompt Hub contains production-labeled prompts for `scenario`, `image_prompt`, and every additional stage prompt found in the source tree.
2. Given prompts are in Prompt Hub, when `langfuse.get_prompt("scenario").compile(scp_text="...")` runs, then it returns a non-empty rendered string.
3. Given a prompt's text is edited in Langfuse UI and promoted to `production`, when the next Python process calls `langfuse.get_prompt("scenario")`, then the updated text is returned with no code change or service restart.
4. Given the migration is run more than once, when a prompt name already exists, then Langfuse creates a new version only when content changed and never creates duplicate prompt names.
5. Given any source prompt contains template placeholders, when it is migrated, then Python/Go-style `{name}` placeholders used by `yt.pipe` are converted to Langfuse `{{name}}` variables and verified by a compile smoke test.
6. Given future pipeline nodes need prompts, when they call the project prompt helper, then they fetch from Langfuse at runtime instead of embedding prompt text in node modules.

## Tasks / Subtasks

- [ ] Confirm prerequisites from Stories 1.1 and 1.2 (AC: 1, 2, 3, 6)
  - [ ] Verify `pyproject.toml`, `src/yt_flow/config.py`, and `src/yt_flow/services/` exist from Story 1.2; create only the files needed by this story if 1.2 has already established the scaffold.
  - [ ] Verify Langfuse connectivity and `YTFLOW_LANGFUSE_HOST`, `YTFLOW_LANGFUSE_PUBLIC_KEY`, `YTFLOW_LANGFUSE_SECRET_KEY` are valid from Story 1.1.
  - [ ] Ensure the Langfuse SDK can initialize from project settings; if SDK v4 expects `LANGFUSE_BASE_URL`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, map the `YTFLOW_` settings to the SDK constructor or process env in one small helper.

- [ ] Build the prompt source discovery and migration script (AC: 1, 4, 5)
  - [ ] Add `scripts/migrate_prompts.py`.
  - [ ] Discover source prompt files under `/mnt/work/projects/yt.pipe/templates/` recursively, accepting `.md` and `.tmpl`; the current source checkout uses `.md`, despite the epic's legacy `.tmpl` wording.
  - [ ] Fail fast with a clear message if the source directory is missing or no prompt files are found.
  - [ ] Convert single-brace placeholders such as `{scp_id}` to Langfuse double-brace variables such as `{{scp_id}}`; do not alter JSON examples or literal braces that are not template variables.
  - [ ] Create or update Langfuse text prompts with `labels=["production"]`.
  - [ ] Make the script idempotent: compare normalized content before creating a new prompt version if the SDK exposes current prompt content; otherwise document that reruns intentionally create Langfuse versions.

- [ ] Implement prompt naming and compatibility mapping (AC: 1, 2, 6)
  - [ ] Required runtime prompt names: `scenario` and `image_prompt`.
  - [ ] Additional migrated prompt names should preserve source intent using stable names:
    - `scenario/research` from `templates/scenario/01_research.md`
    - `scenario/structure` from `templates/scenario/02_structure.md`
    - `scenario/writing` from `templates/scenario/03_writing.md`
    - `scenario/visual_breakdown` from `templates/scenario/03_5_visual_breakdown.md`
    - `scenario/review` from `templates/scenario/04_review.md`
    - `scenario/critic_agent` from `templates/scenario/critic_agent.md`
    - `scenario/format_guide` from `templates/scenario/format_guide.md`
    - `image/shot_breakdown` from `templates/image/01_shot_breakdown.md`
    - `image/shot_to_prompt` from `templates/image/02_shot_to_prompt.md`
    - `tts/scenario_refine` from `templates/tts/scenario_refine.md`
    - `vision/descriptor_enrichment` from `templates/vision/descriptor_enrichment.md`
  - [ ] `scenario` must be a runtime entrypoint prompt that compiles with `scp_text`; it may be a migrated/adapted consolidated prompt, but it must not require node code to concatenate hardcoded prompt fragments.
  - [ ] `image_prompt` must be a runtime entrypoint prompt for the image prompt generation stage; it can wrap or mirror `image/shot_to_prompt`, but downstream nodes must fetch `image_prompt` by name.

- [ ] Add a small project prompt helper for runtime use (AC: 2, 3, 6)
  - [ ] Add `src/yt_flow/services/prompt_service.py`.
  - [ ] Keep it small: a function such as `get_prompt(name: str, *, label: str | None = None)` and `compile_prompt(name: str, **variables: object) -> str`.
  - [ ] Fetch on each call or construct a fresh SDK client per process boundary so FR-16 is true for the next run/process; do not cache rendered prompt text globally.
  - [ ] Return Langfuse prompt objects or compiled strings only; do not introduce a local template database or project-specific prompt override system from `yt.pipe`.

- [ ] Add validation and tests (AC: 1, 2, 4, 5, 6)
  - [ ] Unit-test placeholder conversion for source variables and literal JSON brace preservation.
  - [ ] Unit-test source discovery against a temporary prompt tree with `.md` and `.tmpl`.
  - [ ] Unit-test the prompt helper using a fake Langfuse client.
  - [ ] Add a guarded integration smoke test or documented manual command for live Langfuse:
    - `uv run python scripts/migrate_prompts.py --source /mnt/work/projects/yt.pipe/templates`
    - `uv run python -c "from langfuse import get_client; print(get_client().get_prompt('scenario').compile(scp_text='hello')[:80])"`
  - [ ] Ensure tests do not require live Langfuse unless explicitly enabled by an environment variable such as `YTFLOW_LANGFUSE_LIVE_TESTS=true`.

## Dev Notes

### Dependency Status

- This story depends on Story 1.1 for Langfuse connectivity and Story 1.2 for the Python project scaffold. In the current sprint file, Stories 1.1 and 1.2 are `ready-for-dev`, not `done`; do not assume their implementation outputs exist until checked locally.
- If implementing this story before those outputs exist, keep scaffolding minimal and compatible with the architecture structural seed. Do not build unrelated nodes, API routes, or DB tables.

### Source Prompt Inventory

The actual checked-out `yt.pipe` prompt sources are Markdown files, not `.tmpl` files:

- `/mnt/work/projects/yt.pipe/templates/scenario/01_research.md`
- `/mnt/work/projects/yt.pipe/templates/scenario/02_structure.md`
- `/mnt/work/projects/yt.pipe/templates/scenario/03_writing.md`
- `/mnt/work/projects/yt.pipe/templates/scenario/03_5_visual_breakdown.md`
- `/mnt/work/projects/yt.pipe/templates/scenario/04_review.md`
- `/mnt/work/projects/yt.pipe/templates/scenario/critic_agent.md`
- `/mnt/work/projects/yt.pipe/templates/scenario/format_guide.md`
- `/mnt/work/projects/yt.pipe/templates/image/01_shot_breakdown.md`
- `/mnt/work/projects/yt.pipe/templates/image/02_shot_to_prompt.md`
- `/mnt/work/projects/yt.pipe/templates/tts/scenario_refine.md`
- `/mnt/work/projects/yt.pipe/templates/vision/descriptor_enrichment.md`

The old Go system also has a local template CRUD/versioning implementation under `/mnt/work/projects/yt.pipe/internal/{domain,service,store}/template*.go`. Do not port that subsystem. Langfuse Prompt Hub replaces it for this project.

### Architecture Compliance

- Follow layer direction: `api -> services -> (pipeline | db) -> domain`. Prompt runtime access belongs in `services/prompt_service.py`; pipeline nodes may use the service/helper but must not own Langfuse setup details. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1`]
- Keep pipeline nodes free of hardcoded prompt text. The future `scenario_node` and `image_node` must fetch `scenario` and `image_prompt` from Langfuse at runtime. [Source: `_bmad-output/planning-artifacts/epics.md#Story-1.3-Prompt-Hub-migration`]
- Langfuse failures are non-fatal for tracing, but Prompt Hub fetch failures should fail the LLM stage clearly because the prompt is required input. Include prompt name and label/version in the error message. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10`]
- Use Ponytail rules from `CLAUDE.md`: no extra abstraction, no one-implementation interface, no local prompt DB, no speculative override layer.

### Langfuse SDK Notes

- Use Langfuse Python SDK 4.x per architecture. Official docs show `from langfuse import get_client`, `langfuse.create_prompt(name=..., type="text", prompt=..., labels=["production"])`, and `langfuse.get_prompt("name").compile(...)`.
- Langfuse variables use `{{variable_name}}`. Existing source prompts mostly use `{variable_name}`, so migration must convert placeholders.
- Prompt folders are represented by slashes in prompt names. Names such as `scenario/research` are valid with the planned SDK 4.x stack.
- Fetching a prompt without a label returns the version labeled `production`; `latest` is maintained separately. Use `production` for runtime, not `latest`, unless Jay deliberately changes the deployment policy.
- Prompt config can store model parameters and structured-output metadata, but do not move model identifiers out of `YTFLOW_` settings in this story unless architecture is updated.

### Implementation Guidance

- Suggested files:
  - `scripts/migrate_prompts.py`
  - `src/yt_flow/services/prompt_service.py`
  - `tests/test_prompt_migration.py`
  - `tests/test_prompt_service.py`
- The migration script should be a plain Python CLI using stdlib `argparse`, `pathlib`, and `re` plus the existing `langfuse` dependency. Avoid adding Typer/Click.
- Script defaults:
  - `--source /mnt/work/projects/yt.pipe/templates`
  - `--label production`
  - `--dry-run` to print discovered prompt names and variables without writing to Langfuse
- Preserve prompt body content as much as possible; only normalize leading/trailing whitespace and variable syntax.
- Any consolidated `scenario` prompt must compile with at least `scp_text`. If it needs additional variables, give them harmless defaults or document the exact required variables in the prompt metadata. AC 2 specifically exercises `scp_text`.
- Consider a manifest constant inside `scripts/migrate_prompts.py` for required aliases (`scenario`, `image_prompt`) and source-to-name mapping. Keep it data-only, easy to audit, and covered by tests.

### Testing Requirements

- Run unit tests with `uv run pytest` once Story 1.2 has established the project.
- Live Langfuse migration should be manual/guarded. Normal CI or local unit tests must not write to Jay's self-hosted Langfuse.
- Validate after live migration:
  - Prompt list includes `scenario`, `image_prompt`, and all discovered source prompts.
  - `get_prompt("scenario").compile(scp_text="smoke")` returns non-empty text.
  - Editing the production version in Langfuse UI is reflected in a new Python process with no code change.

### Previous Story Intelligence

- No previous story file exists yet in `_bmad-output/implementation-artifacts/`; only `sprint-status.yaml` and this story are present. There are no implementation learnings from Stories 1.1 or 1.2 to import.
- Recent git history is planning-only:
  - `2390ead` initialized sprint status tracking.
  - `4be98ee` added epic breakdown and implementation readiness report.
  - `6db2416` added UX design specs and HTML mockups.
  - `ca2fb1d` added architecture design and review docs.
  - `b9dc0b0` added PRD.

### Project Structure Notes

- Current repository has planning artifacts but no `src/` scaffold yet. If Story 1.2 is completed before implementation, use the structural seed exactly. If not, only create paths required by this story and keep them aligned with the structural seed.
- No existing UPDATE files were identified in `yt.flow` for this story. The only external source files to read are from `/mnt/work/projects/yt.pipe/templates/`; treat them as read-only source material.

### References

- Epic story and AC: `_bmad-output/planning-artifacts/epics.md`, lines 250-268.
- Epic sequence and dependencies: `_bmad-output/planning-artifacts/epics.md`, lines 184-196.
- PRD Prompt Management: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F3-Prompt-Management-Langfuse-Prompt-Hub`.
- Architecture stack and structure: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`, lines 118-173.
- Project coding philosophy: `CLAUDE.md`, lines 10-25.
- Langfuse Prompt Management get started: https://langfuse.com/docs/prompt-management/get-started
- Langfuse Variables: https://langfuse.com/docs/prompt-management/features/variables
- Langfuse Prompt Version Control: https://langfuse.com/docs/prompt-management/features/prompt-version-control
- Langfuse Prompt Config: https://langfuse.com/docs/prompt-management/features/config
- Langfuse Prompt Folders: https://langfuse.com/docs/prompt-management/features/folders

## Dev Agent Record

### Agent Model Used

TBD by dev agent.

### Debug Log References

### Completion Notes List

### File List
