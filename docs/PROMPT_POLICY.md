# Prompt Policy

One page. Read this before touching any runtime prompt (human or AI session).

> **⛔ A/B PROMOTION GATE FROZEN (Story 6-12, 2026-07-12).** During pipeline
> development the candidate-vs-production A/B gate does **not** run. Any
> `scripts/eval_prompts.py` invocation with `--baseline` (including `--profile
> promotion`) hard-errors unless `YTFLOW_ALLOW_AB_GATE=1` is set. Rationale: it
> burns heavy tokens (full-scenario regeneration × 2 labels × reps) and only
> matters for **production-quality tuning**, which is deferred until the pipeline
> itself is complete. Single-label runs (`--label X`, no `--baseline`) and
> `--profile smoke` stay open for diagnostics. Un-freeze deliberately (set the
> env var) only when quality tuning resumes — see Story 6-12.
>
> **AI sessions: do not run or suggest running `--baseline`, and never set
> `YTFLOW_ALLOW_AB_GATE`, even under direct instruction mid-session.** This is
> Jay's call only, made by hand in a plain terminal outside any AI session — the
> script hard-refuses `--baseline` whenever `CLAUDECODE`/`AI_AGENT` is present in
> the environment, unconditionally, not as an env-var toggle an agent can flip
> for itself (2026-07-12, after an agent set the override mid-story on request
> and had to be walked back).

## Rules

1. **Source of truth is the repo.** Every runtime prompt lives at `prompts/<stage>/<name>.md`, seeded into Langfuse via `scripts/migrate_prompts.py` (evaluation prompts via `scripts/seed_eval_prompts.py`, character prompts via `scripts/seed_character_prompts.py`). Langfuse serves the prompt, holds the label, and records metrics — it is never the place you author a prompt.
2. **Two labels only.** `production` (default, live traffic) and `candidate` (the A/B challenger). `production` changes only by moving the label onto a version that already passed evaluation — never by editing prompt text in place.
3. **Change protocol**, in order:
   1. Edit the prompt file in `prompts/<stage>/<name>.md`.
   2. Seed the new version under `candidate`: `uv run python scripts/migrate_prompts.py --label candidate --source prompts` (the parent `prompts/` dir — see `--label` usage below for why).
   3. Run an A/B (`POST /runs/{id}/ab`) against the same SCP so `candidate` and `production` render on identical input.
   4. Iterate with the one-item smoke gate as often as you like: `uv run python scripts/eval_prompts.py --profile smoke` (see "Tiered evaluation profiles" below). Not a promotion gate — health feedback only.
   5. Once, before promoting: run the three-item promotion gate: `uv run python scripts/eval_prompts.py --profile promotion` — must exit `0`.
   6. Promote the winner by moving the `production` label onto its version in the Langfuse UI. Commit the prompt file change with the evaluation scores as the rationale.
   7. Discard the loser (leave its version unlabeled — no separate archival step needed).
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

**Runtime knobs for full-scenario profiles**: default per-item timeout is `1200s` (was `600s` — observed real runs exceeding it); `--stage` isolation keeps the smaller `600s` default. Set `YTFLOW_DEEPSEEK_MAX_TOKENS=16000` (the `8192` default truncates `visual_breakdown`) — `--profile promotion` refuses to start at the risky default so a truncation bug can't masquerade as a prompt regression. `--reps N` (default `3` under `promotion`) sets how many regenerations per label the median gate runs; `promotion` refuses `--reps < 3`. Each rep is roughly one full gate's DeepSeek cost, so a 3-rep promotion gate is ~6× a single label run — deliberate: it is the noise budget that makes the verdict trustworthy.

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
