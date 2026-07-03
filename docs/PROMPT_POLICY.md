# Prompt Policy

One page. Read this before touching any runtime prompt (human or AI session).

## Rules

1. **Source of truth is the repo.** Every runtime prompt lives at `prompts/<stage>/<name>.md`, seeded into Langfuse via `scripts/migrate_prompts.py` (evaluation/character prompts via `scripts/seed_eval_prompts.py`). Langfuse serves the prompt, holds the label, and records metrics — it is never the place you author a prompt.
2. **Two labels only.** `production` (default, live traffic) and `candidate` (the A/B challenger). `production` changes only by moving the label onto a version that already passed evaluation — never by editing prompt text in place.
3. **Change protocol**, in order:
   1. Edit the prompt file in `prompts/<stage>/<name>.md`.
   2. Seed the new version under `candidate`: `uv run python scripts/migrate_prompts.py --label candidate --source prompts/<stage>`.
   3. Run an A/B (`POST /runs/{id}/ab`) against the same SCP so `candidate` and `production` render on identical input.
   4. Run the Epic 4 evaluation and eyeball the gate output for both variants.
   5. Promote the winner by moving the `production` label onto its version in the Langfuse UI. Commit the prompt file change with the evaluation scores as the rationale.
   6. Discard the loser (leave its version unlabeled — no separate archival step needed).
4. **Golden-set regression before promotion.** A candidate must pass the golden set (Story 6.2) before its label moves to `production`.
5. **No editing `production` prompt text directly in the Langfuse UI.** Any content change starts at the repo file (rule 1) — the UI's only write action here is dragging a label.

## `--label` usage

`scripts/migrate_prompts.py` already supports `--label` (default `production`). Seed a candidate with:

```
uv run python scripts/migrate_prompts.py --label candidate --source prompts/scenario
```

## `production` label protection — not available on this instance

Langfuse's "Protected Labels" feature (Project Settings → Prompts) requires an Enterprise license. The self-hosted instance at `langfuse.eli.kr` runs OSS (v3.201.1) — confirmed 2026-07-04, Project Settings has no "Prompts" tab at all, so there is no technical lock available.

There is no substitute enforcement to configure: the project is single-operator, so a Members-role restriction would only add friction with no one else to restrict. Rule 5 above (no direct `production` edits in the UI) is enforced by policy only — CLAUDE.md points every AI session at this document, and that's the actual control here. If the project ever adds a second operator, revisit Members roles as the fallback (Project Settings → Members — coarse, project-wide write access, not per-label).
