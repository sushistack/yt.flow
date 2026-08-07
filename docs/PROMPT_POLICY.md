# Prompt Policy

One page. Read this before touching any runtime prompt (human or AI session).

> **⛔ QUALITY GATING OFF — DEV MODE (Jay, 2026-08-03).** While the pipeline is
> still being built, prompt changes go **straight to `production`**:
>
> ```
> uv run python scripts/migrate_prompts.py --label production --source prompts
> ```
>
> No A/B, no golden set, no promotion gate, no score rationale required. Rules 3
> and 4 below are **suspended** — they describe the quality-tuning-phase workflow
> to restore later, not current practice. `--profile smoke` is available if you
> *want* health feedback; it is never required. Do not ask for or suggest a gate
> run on a prompt change.
>
> Why: the A/B gate was frozen in Story 6-12 (2026-07-12) because it burns heavy
> tokens and its verdicts were noise-dominated, but the "must pass the gate before
> promoting" rule stayed — leaving promotion structurally impossible and every
> prompt edit stuck in `candidate`. This amendment closes that deadlock.
>
> Restore the gated workflow when the pipeline is complete and quality tuning
> starts (Story 6-12 un-freeze): promote the `candidate` backlog through
> `--profile promotion` then, not now.
>
> **AI sessions still may not run `--baseline` or set `YTFLOW_ALLOW_AB_GATE`** —
> unchanged, and now moot since no gate run is expected at all. The script
> hard-refuses `--baseline` whenever `CLAUDECODE`/`AI_AGENT` is in the environment
> (2026-07-12, after an agent flipped the override mid-story on request).

## Rules

1. **Source of truth is the repo.** Every runtime prompt lives at `prompts/<stage>/<name>.md`, seeded into Langfuse via `scripts/migrate_prompts.py` (evaluation prompts via `scripts/seed_eval_prompts.py`, character prompts via `scripts/seed_character_prompts.py`). Langfuse serves the prompt, holds the label, and records metrics — it is never the place you author a prompt.
2. **Two labels only.** `production` (default, live traffic) and `candidate` (the A/B challenger). `production` changes only by moving the label onto a version that already passed evaluation — never by editing prompt text in place.
3. **Change protocol** — ⛔ **SUSPENDED in dev mode** (see banner: seed straight to `production`). Restore when quality tuning starts:
   1. Edit the prompt file in `prompts/<stage>/<name>.md`.
   2. Seed the new version under `candidate`: `uv run python scripts/migrate_prompts.py --label candidate --source prompts` (the parent `prompts/` dir — see `--label` usage below for why).
   3. Run an A/B (`POST /runs/{id}/ab`) against the same SCP so `candidate` and `production` render on identical input.
   4. Iterate with the one-item smoke gate as often as you like: `uv run python scripts/eval_prompts.py --profile smoke` (see "Tiered evaluation profiles" below). Not a promotion gate — health feedback only.
   5. Once, before promoting: run the three-item promotion gate: `uv run python scripts/eval_prompts.py --profile promotion` — must exit `0`.
   6. Promote the winner by moving the `production` label onto its version in the Langfuse UI. Commit the prompt file change with the evaluation scores as the rationale.
   7. Discard the loser (leave its version unlabeled — no separate archival step needed).
4. **Golden-set regression before promotion** — ⛔ **SUSPENDED in dev mode.** A candidate must pass the golden set (Story 6.2) before its label moves to `production`. The gate (`scripts/eval_prompts.py`) only exercises the `scenario` stage — for a stage it doesn't cover (e.g. character prompts, which also aren't wired into the standard `POST /runs/{id}/ab` A/B mechanism), substitute a direct `candidate`-vs-`production` compile comparison against identical inputs as the pre-promotion check instead.
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

**Pass criteria** (before moving the `production` label): the comparison run must exit `0`. Under `--profile promotion` the gate is **statistical** (Story 6.10): each golden-set item is regenerated `N` times (`--reps`, default `3`) on *both* candidate and production, and the verdict is judged on the **median** per-item delta:

- An item is isolated as failed only if it hard-fails (generation or scoring error) in a *majority* of its `N` runs. A minority failure is dropped from the median and logged in the report — never silently truncated from coverage.
- For every scoreable item, candidate and production trials are paired by repetition; the **median of those per-trial deltas** must be non-negative for every axis and for the total. A pair with a hard failure on either side contributes no score, while the side-specific failure still counts toward that item's majority-failure rule and is logged.

Any item that fails a majority of runs, a negative median axis delta, or a negative median total delta fails the verdict and blocks promotion. If candidate and production hit the *same* infrastructure failure (e.g. both time out) in a majority of runs, the verdict is `INCONCLUSIVE` instead of `FAIL` — still a non-zero exit, still blocks promotion, but the report doesn't misreport a broken baseline as a candidate regression.

**Why median-of-N, not single-run zero-tolerance (Story 6.6 → 6.10).** Story 6.6's original gate failed on *any* single negative axis delta. That zero-tolerance rule was correct in intent — a candidate must never regress a quality axis — but over a 3-item × 3-axis = 9-cell comparison, full-scenario **generation** variance reliably drives some cell slightly negative on every run, even when candidate and production are statistically identical (Story 6.9's 4-data-point multi-trial: the negative cell wandered item-to-item and axis-to-axis, never persisting). A statistically-equivalent candidate therefore FAILed by chance every run — the gate was structurally un-passable. The median criterion keeps the exact same quality bar (**median** ≥ 0 on every axis and total) — a *real* regression is negative across trials and still FAILs — while no longer treating one noisy trial as proof of regression. This mirrors the project's own `REPS_PER_AXIS=3` judge-sampling precedent (Story 6.8), extended from *judge* noise to *generation* noise. The median (not the mean) is deliberate: a hard-failing run yields no score at all, and a median simply drops that data point, whereas a mean would need a sentinel value that poisons the result. This is a noise-tolerance change, **not** a loosening of the quality standard.

## Tiered evaluation profiles (Story 6.6)

A full 3-item candidate-vs-production comparison takes 20+ minutes — not a usable inner loop for iterating on a prompt edit. `--profile` splits routine iteration from the production-safety gate:

```
# fast: one canary (SCP-049), candidate only, health feedback — NOT A PROMOTION GATE
uv run python scripts/eval_prompts.py --profile smoke

# optional: same canary against production too
uv run python scripts/eval_prompts.py --profile smoke --baseline production

# mandatory once, before promoting: all three items, candidate vs production,
# median of 3 regenerations per label (statistical gate — Story 6.10)
uv run python scripts/eval_prompts.py --profile promotion
```

**Workflow**: local tests → optional `--stage` isolation (diagnostic only, never authority) → `--profile smoke` repeatedly while iterating → `--profile promotion` once before moving the `production` label. The three-item set is reduced in *frequency*, not in safety coverage — promotion always runs all three items and rejects `--scp-id`/`--stage` narrowing.

Omitting `--profile` keeps the pre-6.6 behavior (backward compatible — no existing invocation is silently weakened).

**Authority**: only `--profile promotion`'s `PASS` may justify moving the `production` label. Any `smoke` result — pass or fail — prints and persists `NOT A PROMOTION GATE`; treat it as iteration feedback, not release evidence.

**Runtime knobs for full-scenario profiles**: default per-item timeout is `1200s`; `--stage` isolation uses `600s`. Story 12.2 split the chain across providers, and current config defaults already clear the promotion preflight: `YTFLOW_DEEPSEEK_MAX_TOKENS=32768` for planning/structure and `YTFLOW_GEMINI_WRITING_MAX_TOKENS=16384` for writing plus runtime review/critic. Promotion validates both budgets so provider-side truncation cannot masquerade as a prompt regression. `--reps N` (default `3` under `promotion`) sets how many regenerations per label the median gate runs; `promotion` refuses `--reps < 3`. Each repetition is one complete two-provider scenario evaluation, and repeated trials deliberately bypass generation-cache reuse so the samples remain independent.

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
