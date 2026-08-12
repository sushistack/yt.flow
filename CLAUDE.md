# CLAUDE.md — yt.flow

## Project Overview

Python rewrite of the yt.pipe Go implementation. SCP Foundation YouTube content automation pipeline.
LangGraph orchestration + Langfuse Prompt Hub + runtime tracing.

**Source project reference**: `/mnt/work/projects/yt.pipe`

## Code Philosophy — Ponytail (always active)

This project runs **Ponytail full mode** by default. Follow the ladder on every implementation:

1. **Does this need to exist?** YAGNI — speculative need = skip it
2. **Stdlib does it?** Use it
3. **Native platform feature covers it?** Use it
4. **Already-installed dependency solves it?** Use it. Never add a new one
5. **Can it be one line?** One line
6. **Only then:** the minimum code that works

**Rules:**
- No interface with one implementation
- No boilerplate scaffolding "for later"
- Deletion over addition
- Mark deliberate simplifications with `# ponytail:` comment

## Build & Run

_TBD — fill in after initial project setup_

## Architecture

- **Orchestrator**: LangGraph (Python)
- **LLM tracing + prompt management**: Langfuse (self-hosted Docker)
- **Pipeline stages**: scenario → image → tts → subtitle → video
- **Design details**: see `_bmad-output/brainstorm-intent.md` and PRD

## Prompt Policy

Any change to a runtime prompt (human or AI session) follows `docs/PROMPT_POLICY.md` — repo file is the source of truth, `production`/`candidate` labels only, no direct edits in the Langfuse UI.

**DEV MODE (2026-08-03): quality gating is OFF.** Prompt edits seed straight to `production` (`uv run python scripts/migrate_prompts.py --label production --source prompts`). No A/B, no golden set, no promotion gate — do not run one or ask for one. Restored when quality tuning starts (Story 6-12).

## Live-validation artifacts (`_bmad-output/implementation-artifacts/*-live-validation/`)

Stories in this project close on **rendered frames a human judged**, so those directories are evidence and not scratch. They are also the largest thing in the repo, so each one carries its own `.gitignore` and splits its contents in two — `10-1b-live-validation/.gitignore` is the model to copy:

- **Commit the adjudication images** — the side-by-side grids, pair sheets and single frames a story's verdict actually cites — plus every script and report that re-derives a number. Downscale to ~512 px on the long edge unless the judging criterion needs more; the criteria used so far (which way is the body facing, how many figures, is there a pupil) all survive it.
- **Ignore the raw renders those were built from** (per-plate sweeps, probe frames, extracted stills, full videos). They are regenerable from the committed scripts against the same run.
- **Never blanket-delete an ignored payload.** Read the directory's `.gitignore` header first: some hold the only surviving copy of something (`*/off/` is the pre-8.16 render Jay watched, and `video.py` unlinks shot clips on re-render, so it cannot be rebuilt). Delete with an explicit exclusion, not with `git clean`.
- `git status --porcelain <dir>` proves nothing here — these paths are ignored by design. Assert file state with `find` plus dates.

---

# BMAD Method v6.0.4

This project is managed with the BMAD methodology.
Config: `_bmad/_config/` and `_bmad/bmm/`
Artifacts: `_bmad-output/`
