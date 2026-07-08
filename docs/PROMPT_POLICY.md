# Prompt Policy

One page. Read this before touching any runtime prompt (human or AI session).

## Rules

1. **Source of truth is the repo.** Every runtime prompt lives at `prompts/<stage>/<name>.md`, seeded into Langfuse via `scripts/migrate_prompts.py` (evaluation prompts via `scripts/seed_eval_prompts.py`, character prompts via `scripts/seed_character_prompts.py`). Langfuse serves the prompt, holds the label, and records metrics — it is never the place you author a prompt.
2. **Two labels only.** `production` (default, live traffic) and `candidate` (the A/B challenger). `production` changes only by moving the label onto a version that already passed evaluation — never by editing prompt text in place.
3. **Change protocol**, in order:
   1. Edit the prompt file in `prompts/<stage>/<name>.md`.
   2. Seed the new version under `candidate`: `uv run python scripts/migrate_prompts.py --label candidate --source prompts` (the parent `prompts/` dir — see `--label` usage below for why).
   3. Run an A/B (`POST /runs/{id}/ab`) against the same SCP so `candidate` and `production` render on identical input.
   4. Run the golden-set regression gate: `uv run python scripts/eval_prompts.py --label candidate --baseline production` (see below) — must exit `0`.
   5. Promote the winner by moving the `production` label onto its version in the Langfuse UI. Commit the prompt file change with the evaluation scores as the rationale.
   6. Discard the loser (leave its version unlabeled — no separate archival step needed).
4. **Golden-set regression before promotion.** A candidate must pass the golden set (Story 6.2) before its label moves to `production`. The gate (`scripts/eval_prompts.py`) only exercises the `scenario` stage — for a stage it doesn't cover (e.g. character prompts, which also aren't wired into the standard `POST /runs/{id}/ab` A/B mechanism), substitute a direct `candidate`-vs-`production` compile comparison against identical inputs as the pre-promotion check instead.
5. **No editing `production` prompt text directly in the Langfuse UI.** Any content change starts at the repo file (rule 1) — the UI's only write action here is dragging a label.

## Golden-set regression (Story 6.2)

`scripts/eval_prompts.py` runs the `scenario` stage only (no DB run row, no LangGraph graph/gate, no image/TTS/subtitle/video) against a fixed 3-SCP Langfuse dataset (`golden-scps`: `SCP-096`, `SCP-173`, `SCP-049`), scores each item with the Epic 4 LLM-judge axes (`atmosphere`, `narrative_coherence`, `article_fidelity`) plus scenario-applicable rule metrics, and records every item's output and scores in Langfuse via `Dataset.run_experiment`.

```
# one-time (or after data/scps.json changes): seed/update the golden dataset
uv run python scripts/eval_prompts.py --seed

# score a single label
uv run python scripts/eval_prompts.py --label candidate

# gate a promotion: compare candidate against production on the same golden set
uv run python scripts/eval_prompts.py --label candidate --baseline production
```

**Pass criteria** (step 4 of the change protocol above, before moving the `production` label): the comparison run must exit `0`, which requires, for every golden-set item:

- No item failed scenario generation or scoring on either label.
- Every candidate axis score is greater than or equal to the matching production axis score.
- Candidate total score is greater than or equal to production total score.

Any item failure, axis regression, or total regression fails the verdict and blocks promotion — a broken baseline run also fails (an inconclusive comparison cannot justify promoting the candidate).

## `--label` usage

`scripts/migrate_prompts.py` already supports `--label` (default `production`). Seed a candidate with:

```
uv run python scripts/migrate_prompts.py --label candidate --source prompts
```

Use `--source prompts` (the parent dir), not `--source prompts/<stage>` — the
script names each prompt from its path *relative to* `--source`, so pointing
it at a stage subdirectory drops that stage's name prefix (e.g. `scenario/`)
from every seeded prompt name, silently creating `visual_breakdown` instead
of `scenario/visual_breakdown`. Found and corrected in Story 8.10.

## `production` label protection — not available on this instance

Langfuse's "Protected Labels" feature (Project Settings → Prompts) requires an Enterprise license. The self-hosted instance at `langfuse.eli.kr` runs OSS (v3.201.1) — confirmed 2026-07-04, Project Settings has no "Prompts" tab at all, so there is no technical lock available.

There is no substitute enforcement to configure: the project is single-operator, so a Members-role restriction would only add friction with no one else to restrict. Rule 5 above (no direct `production` edits in the UI) is enforced by policy only — CLAUDE.md points every AI session at this document, and that's the actual control here. If the project ever adds a second operator, revisit Members roles as the fallback (Project Settings → Members — coarse, project-wide write access, not per-label).
