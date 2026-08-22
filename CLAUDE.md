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

**Seeding is only real if the name matches what the runtime fetches.** Langfuse prompt names are not derived uniformly from the file path: the scenario and evaluation families use slashes (`scenario/structure`), the character family uses hyphens (`character-generation`). `scripts/migrate_prompts.py` holds that mapping in `SOURCE_TO_NAME`, and `tests/test_prompt_migration.py::test_prompt_seeding_covers_runtime_names` fails if a `get_prompt("…")` literal in `src/` has no entry. Until 2026-08-16 the character entries were missing, so the command above printed `created` while writing to names nothing reads — a `character/generation.md` fix authored 2026-07-08 sat un-shipped for five weeks and three separate card defects were chased back to it. **After seeding, verify the name the runtime actually asks for**, e.g. `GET {langfuse_host}/api/public/v2/prompts/character-generation?label=production` — not the name the script printed. `scripts/seed_character_prompts.py` and `scripts/seed_eval_prompts.py` predate the mapping and target their own families directly; prefer the one documented command.

## Decision-bearing settings (`scripts/report_decision_drift.py`)

A setting whose value encodes a **product judgement** — motion on/off, voice source,
compositing strategy, a guard budget — belongs in the **code default in `config.py`,
with the dated verdict in the comment above it and `.env`/`.env.example` left
unpinned**. That is the rule, and it exists because both halves have already failed:
a decided value that only reached `.env` never shipped
(`gotcha_a-decision-that-only-reaches-env-never-ships` — Story 10.2's people-free
guard sat at `0` for 15 days and screened nothing), and a stale `.env` pin silently
re-applies an old value over a new code default
(`gotcha_env-file-beats-code-default`). `.env.example` is the sharper trap of the two,
because a pin there is a **revert a fresh checkout performs on day one** — four of them
were found and commented out in Story 14.4, plus a truthy `<YOUR_…>` credential
placeholder that made a guard run against a bogus key instead of reporting a missing one.
The fourth was found only by sweeping **every** assignment in `.env.example` against the
code default; sweeping the declared fields alone is blind exactly where it has not
already looked. `tests/test_report_decision_drift.py` now pins that sweep.

`config.DECISIONS` declares each such field with its deciding story, date, decided
value and a citation of the comment it was harvested from. It is an **index into the
prose, never a second place a decision is made**: if a row and the comment disagree,
the comment is right and the row is stale. A field with no *dated* verdict gets no row.

```
uv run python scripts/report_decision_drift.py
```

Prints, for every declared field: decided value, code default, effective value and the
**winning source** (`os.environ` > `.env` > code default — `Settings()` keeps no
provenance, so this is reconstructed and would start lying if `Settings` grew a third
source). Three buckets: effective-vs-decided drift, env-sourced (reported even when
the value matches), and latent `.env.example` pins.

**A non-empty result is a finding for the story that owns the feature, never a build
failure.** The report always exits 0 on a successful read; only a usage error exits
non-zero. Do not wire it into CI as a gate and do not "fix" someone else's flag to
empty it — half these flags are legitimately off pending live evidence. For the same
reason no test asserts that every decided value equals its default: that would make
the report a gate by proxy.

## Live-validation artifacts (`_bmad-output/implementation-artifacts/*-live-validation/`)

Stories in this project close on **rendered frames a human judged**, so those directories are evidence and not scratch. They are also the largest thing in the repo, so their contents split in two.

**Enforcement is the repo-root `.gitignore`, not per-directory files.** Per-directory `.gitignore`s were the model until 2026-08-17, and they failed the way opt-in rules fail: **12 of the `*-live-validation` dirs never got one**, and 293 MB of raw PNG reached the index anyway — 10-4 alone tracked 162 files. The root file now globs `*-live-validation/**/*.{png,mp4,wav,mp3}` so a NEW directory is covered without anyone remembering. 229 files / 273 MB were untracked that day (left on disk). Write a per-directory `.gitignore` only to record an **exception** or a warning about an irreplaceable payload.

- **Commit the adjudication images** — the side-by-side grids, pair sheets and single frames a story's verdict actually cites — plus every script and report that re-derives a number. Downscale to ~512 px on the long edge unless the judging criterion needs more; the criteria used so far (which way is the body facing, how many figures, is there a pupil) all survive it.
- **Ignore the raw renders those were built from** (per-plate sweeps, probe frames, extracted stills, full videos). They are regenerable from the committed scripts against the same run.
- **Never blanket-delete an ignored payload.** Read the directory's `.gitignore` header first: some hold the only surviving copy of something. `10-1-live-validation/off|on` is the pre-8.16 render Jay watched and `video.py` unlinks shot clips on re-render, so it cannot be rebuilt — it is **deliberately still tracked** as the root `.gitignore`'s only negation, precisely because untracking it would put it one `git clean -xdf` away from gone. Delete with an explicit exclusion, never with `git clean`.
- **Untracking is not reclaiming.** `git rm --cached` + ignore stops the growth; the 273 MB already in history stays there. Shrinking that needs a history rewrite, which is a separate decision nobody has made.
- `git status --porcelain <dir>` proves nothing here — these paths are ignored by design. Assert file state with `find` plus dates.

---

# BMAD Method v6.0.4

This project is managed with the BMAD methodology.
Config: `_bmad/_config/` and `_bmad/bmm/`
Artifacts: `_bmad-output/`
