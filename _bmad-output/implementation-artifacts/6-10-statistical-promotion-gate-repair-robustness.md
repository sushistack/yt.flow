---
created: 2026-07-11
baseline_commit: 89402bd
story_key: 6-10-statistical-promotion-gate-repair-robustness
story_id: "6.10"
epic: 6
previous_story: 6-9-scene-repair-truncation-axis-regression
depends_on:
  - 6-9-scene-repair-truncation-axis-regression  # 6.9's AC3/AC4 live multi-trial produced the evidence (variance-confirmed, gate structurally un-passable) that scopes this story
unblocks:
  - 6-3-prompt-cache-hit-optimization   # this story's statistical gate is the mechanism that finally promotes 6-3/6-4
  - 6-4-scenario-yaml-output-bounded-retry
related:
  - 6-6-tiered-prompt-evaluation-gates  # owns the zero-tolerance policy this story revises; its rationale must be respected/carried forward
  - 6-8-golden-set-judge-multi-sample   # REPS_PER_AXIS=3 judge-sampling precedent that AC1's N≥3 mirrors; judge-noise handling precedent
evidence: "2026-07-11 Story 6.9 AC3/AC4 live 3-run multi-trial (6-3-6-4-review-metrics-report.md, '2026-07-11 Story 6.9 — AC3/AC4 live multi-trial'): the SCP-173/096 axis regressions that blocked 6-3/6-4 are VARIANCE, not a real content regression — across the original gate plus 3 runs no (item,axis) delta cell stays negative (SCP-173 atmosphere −0.33→0→+1.00→0; SCP-096 article_fidelity −0.33→+0.33→+0.67→0). Yet every 3-item run's Verdict=FAIL, each on a different noise cell, because the promotion gate is zero-tolerance (any negative delta = FAIL, a deliberate Story 6.6 policy) over a 9-cell comparison and generation noise reliably drives some cell slightly negative every run. A candidate statistically equivalent to production therefore FAILs by chance every time — the gate is structurally un-passable, a policy/measurement problem 6.9 was explicitly scoped out of fixing. Separately, SCP-049's scoped writing_scene_repair hard-failed intermittently (truncation on the original gate; a `scene coverage mismatch` ValueError on run 2 — repair returned scenes [1,2,3,4,5,6] when [3,2,4,1,5,6] were requested), leaving the item unscoreable regardless of gate criterion. Jay's decision (2026-07-11): fix both — statistical gate + repair robustness — in one story."
---

# Story 6.10: Statistical promotion gate + SCP-049 scoped-repair robustness (unblock 6-3/6-4)

Status: done

## Story

As Jay,
I want the promotion gate to judge a candidate on the median of repeated trials (so run-to-run generation noise no longer FAILs a candidate that is statistically equivalent to production) and the SCP-049 scoped-repair hard-failure (`scene coverage mismatch`) to recover instead of killing the item,
so that the 6-3/6-4 candidate prompt set — whose only remaining blocker is measurement noise, not content quality — can finally pass the gate and promote to production.

## Context

This closes the loop the 6.6→6.7→6.8→6.9 chain opened. Each of those stories removed a distinct *crash-class* cause of the 6-3/6-4 promotion-gate FAIL (timeout, YAML syntax, judge-parse crash, writing_scene_repair truncation). Story 6.9's Jay-authorized live multi-trial then proved that **no crash cause remains** and the SCP-173/096 axis regressions are generation **variance**, not a real regression — yet the gate still FAILs every run. The root cause is now measurement/policy, not candidate quality:

**Finding 1 — the zero-tolerance gate is structurally un-passable under generation noise.** `docs/PROMPT_POLICY.md`'s promotion criterion (Story 6.6) fails the gate on *any* single negative axis delta. Over a 3-item × 3-axis = 9-cell candidate-vs-production comparison, full-scenario generation variance reliably drives some cell slightly negative on every run (Story 6.9's 4-data-point table shows the negatives wandering item-to-item and axis-to-axis). A candidate that is statistically indistinguishable from production therefore FAILs by chance every single run. The fix is a statistical judgement (median of N≥3 trials per item) rather than a single-run zero-tolerance snapshot — matching the project's own `REPS_PER_AXIS=3` judge-sampling precedent for handling scoring noise (Story 6.8), extended from *judge* noise to *generation* noise.

**Finding 2 — SCP-049's scoped repair hard-fails intermittently, leaving the item unscoreable.** Across Story 6.9's runs, SCP-049's `writing_scene_repair` failed two different ways: 16k truncation (fixed by 6.9's full-rewrite fallback) and a `scene coverage mismatch` ValueError (the repair returned its scenes in sorted order `[1,2,3,4,5,6]` when `[3,2,4,1,5,6]` were requested). The mismatch is not a truncation, so 6.9's *narrow* recovery correctly let it fail the run — but that means the item cannot be scored, and no gate criterion (statistical or otherwise) can compare an item that errors out. This robustness gap must be closed so SCP-049 reliably produces a scoreable result.

## Acceptance Criteria

1. **Given** the promotion gate currently fails on any single negative delta, **Then** replace the zero-tolerance verdict in `scripts/eval_prompts.py --profile promotion` with a **statistical criterion**: re-generate each golden item N times (N≥3, mirroring `REPS_PER_AXIS=3`) for both candidate and production, and judge PASS/FAIL on the **median** per-item delta so a single noisy negative cell no longer fails the gate. Record in Dev Notes why median/best-of-N is chosen over a plain mean (a hard-failing run — AC3's SCP-049 case — poisons a mean but not a median). Revise `docs/PROMPT_POLICY.md`'s promotion criterion to match, explicitly relating it to Story 6.6's original zero-tolerance rationale (why the noise-tolerance change is safe, not a loosening of quality standards).
2. **Given** some of the N runs may hard-fail an item (an error, not a score), **Then** the gate must not crash: judge on the median of the *successful* runs, isolate an item as FAIL only if it fails in a majority of runs, and **log** the count/reason of failed runs to the metrics report (no silent truncation of coverage).
3. **Given** SCP-049's scoped `writing_scene_repair` intermittently raises `scene coverage mismatch` when it returns the requested scenes in a different order/set, **Then** make that path recover instead of hard-failing — verify coverage order-independently (or delegate to the full-rewrite fallback as truncation does) — while preserving Story 6.9's narrow-recovery contract (state exactly which repair failure classes now recover vs. still fail the run).
4. **Given** AC1–AC3 are in place, **Then** run the new statistical gate against the 6-3/6-4 candidate — **Given** the median verdict PASSes, promote 6-3/6-4 to `production` per `docs/PROMPT_POLICY.md` and close both stories `done`; **Given** it still FAILs, record the detail in `6-3-6-4-review-metrics-report.md` (no forced promotion).
5. **Given** the new gate and repair logic, **Then** add regression tests for: (a) median verdict — a single noisy negative cell still PASSes, a consistently-negative cell still FAILs; (b) item hard-failure isolation — one failing run does not crash the whole gate; (c) SCP-049 `scene coverage mismatch` recovery.

## Tasks / Subtasks

- [x] Task 1: Implement the statistical (median-of-N) verdict in `scripts/eval_prompts.py` `compare`/`print_comparison`, N≥3 regeneration per item for candidate+production. (AC:1)
- [x] Task 2: Harden the gate against per-run item hard-failures — median of successful runs, majority-fail isolation, failed-run logging. (AC:2)
- [x] Task 3: Fix SCP-049 scoped-repair `scene coverage mismatch` in `writing_scene_repair_step` / its coverage validation — order-independent match or full-rewrite fallback, preserving 6.9's narrow-recovery contract. (AC:3)
- [x] Task 4: Revise `docs/PROMPT_POLICY.md` promotion criterion (zero-tolerance → statistical), relating to 6.6's rationale. (AC:1)
- [x] Task 5: Live-run the new gate for 6-3/6-4; promote on median PASS + close 6-3/6-4, else record. (AC:4) — outward/policy action, Jay-authorized (2026-07-12). **Verdict FAIL → recorded, no promotion** (AC4 FAIL branch): SCP-049 isolated as FAIL because *production* (baseline) hard-failed 2/3 on new YAML-syntax + `'location'` errors (distinct from AC3's coverage-mismatch). Review later corrected the axis calculation from difference-of-medians to paired-delta median; the historical verdict remains FAIL because the SCP-049 majority failure independently blocks promotion. 6-3/6-4 stay `in-progress`, un-promoted. Detail in `6-3-6-4-review-metrics-report.md#2026-07-12 Story 6.10`.
- [x] Task 6: Regression tests for median verdict, item-failure isolation, coverage-mismatch recovery. (AC:5)

### Review Findings

- [x] [Review][Patch] Count missing per-run item results as hard failures instead of silently dropping coverage [scripts/eval_prompts.py:474]
- [x] [Review][Patch] Compute the median of paired candidate-vs-production deltas, not the difference of independently aggregated medians [scripts/eval_prompts.py:498]
- [x] [Review][Patch] Route missing/extra repair scenes through `SceneCoverageError` so genuine coverage mismatches reach full-rewrite recovery [src/yt_flow/pipeline/nodes/scenario_chain.py:533]

## Dev Notes

### Existing Code To Reuse / Modify

- `scripts/eval_prompts.py` `compare` (lines ~440-489) — the zero-tolerance verdict (`regressed = any(d < 0 ...) or total_delta < 0; _downgrade("FAIL")`, line ~475) is exactly what AC1 replaces with a median-of-N criterion. `print_comparison` (line ~492) and `main` (line ~545, `return 0 if verdict == "PASS" else 1`) also touch the verdict.
- `_MIN_MAX_TOKENS_FOR_PROMOTION` / `resolve_profile` — the promotion profile plumbing (all 3 golden items mandatory) is unchanged; AC1 adds N-run repetition on top of it, not a new profile.
- `eval_service.py` `REPS_PER_AXIS=3` — the judge-noise precedent AC1 mirrors for generation noise. Do not conflate: REPS_PER_AXIS averages *judge* samples per axis within one generation; AC1 repeats the *generation* itself.
- `src/yt_flow/pipeline/nodes/scenario_chain.py` `writing_scene_repair_step` (lines ~493-530) and its coverage/identity validation — AC3's `scene coverage mismatch` originates here. Reuse Story 6.9's `TruncationError`/full-rewrite fallback pattern (`scenario.py` `scenario_node`) if delegating recovery.

### Constraints / Precedent

- Preserve Story 6.9's **narrow-recovery contract**: recovery is opt-in per failure class (6.9: only `scenario/writing_scene_repair` truncation falls back; every other repair error fails the run). AC3 must state explicitly whether `scene coverage mismatch` joins the recover set or is fixed at the validation site so it never raises.
- `docs/PROMPT_POLICY.md` zero-tolerance was a deliberate Story 6.6 decision — AC1/AC4 *revise* it with rationale, they do not silently drop it. The statistical gate must still catch a *real* regression (a consistently-negative cell across trials), only tolerate single-run noise.
- N≥3 generation runs are real DeepSeek cost (~one full promotion gate per run); Task 5's live promotion is an outward, policy-governed action — Jay-authorized, as every prior gate run has been.

### References

- [Source: _bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md#2026-07-11 Story 6.9 — AC3/AC4 live multi-trial] — the variance evidence + un-passable-gate finding that scopes this story
- [Source: _bmad-output/implementation-artifacts/6-9-scene-repair-truncation-axis-regression.md#New Blocker] — the blocker re-definition
- [Source: scripts/eval_prompts.py#L440-L489] — `compare` zero-tolerance verdict to replace
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L493-L530] — `writing_scene_repair_step` (coverage-mismatch origin)
- [Source: docs/PROMPT_POLICY.md] — promotion criterion to revise

## Dev Agent Record

### Implementation Plan / Approach

- **AC1/AC2 (statistical gate, `scripts/eval_prompts.py`)** — added `PROMOTION_REPS=3` and a `--reps N` knob; `resolve_profile` now carries `reps` (default 3 under `promotion`, 1 otherwise; `promotion` rejects `--reps<3`). New `aggregate_runs(runs)` collapses N per-item runs into one median-based `ItemResult`: median of the *successful* runs per axis/total, an item isolated as failed only when it hard-fails a **majority** of runs (`n_fail*2 > reps`), and minority failures recorded in new `ItemResult.n_runs/n_failed_runs/failed_run_reasons` fields for logging. `compare` was left structurally unchanged — the aggregated `ItemResult` duck-types the single-run one, so the same zero-tolerance-on-the-**median** logic (any negative median axis/total delta = FAIL) preserves 6.6's quality bar while absorbing generation noise. `main`'s baseline branch runs `reps` regenerations per label (per-rep artifact subdirs) and aggregates; `reps==1` stays byte-identical to the pre-6.10 path. `print_comparison` surfaces per-run hard-failures (`_print_run_provenance`) so no coverage is silently truncated.
  - **Why median, not mean (AC1):** a hard-failing run (AC3's SCP-049 case) yields no score at all; a median simply drops that data point, whereas a mean would need a sentinel that poisons the aggregate.
- **AC3 (SCP-049 scoped-repair robustness, `scenario_chain.py` + `scenario.py`)** — split the old blanket `scene coverage mismatch` `ValueError` into two paths at the validation site: (1) a **reorder** of the same scene set (the observed SCP-049 habit — model returns the requested scenes sorted by `scene_num`) is silently reordered to the requested positional order and never raises; (2) a **genuinely different set** (unmappable ids) raises the new `SceneCoverageError(ValueError)`, which `_repair_and_review`'s caller catches and routes to the proven full-rewrite fallback, mirroring 6.9's truncation recovery.
  - **Narrow-recovery contract (AC3, per 6.9):** recovery is opt-in per failure class. **Reorder** → recovered in-place (no fallback needed). **Genuine coverage mismatch** → `SceneCoverageError` → full-rewrite fallback. **Truncation of the repair write** (6.9) → full-rewrite fallback. **Every other repair error** (empty narration, downstream-stage truncation, count mismatch, etc.) → still fails the run, unchanged.

### Completion Notes

- AC1, AC2, AC3, AC5 implemented and verified; AC4 completed via a Jay-authorized live gate run (2026-07-12).
- **AC4 live outcome: Verdict FAIL → recorded, no promotion.** The run verified AC2 end-to-end by isolating SCP-049 after production hard-failed 2/3 trials. Review found that the original axis table used a difference of independently aggregated medians; AC1's paired-delta calculation is now corrected and regression-tested. The historical verdict remains FAIL because SCP-049's majority failure independently blocks promotion, but the SCP-173/SCP-096 axis rows require a future live rerun before they can be treated as paired-delta evidence. Two out-of-scope follow-ups surfaced: (1) the production-label SCP-049 baseline-robustness gap and (2) whether N=3 is sufficient at 0.33-point judge granularity. Full detail in `6-3-6-4-review-metrics-report.md#2026-07-12 Story 6.10`.
- Post-review full regression suite green: **1265 passed, 1 skipped** (pre-existing unrelated skip), `ruff` clean on all changed files.

## Notes for Code Review (handle in one pass)

The code-review pass for this story should also weigh in on the items below so nothing is lost between sessions. These are surfaced *by* Story 6.10's work but were out of its implementation scope — the reviewer should confirm the scoping call and recommend whether each becomes its own story.

**A. Decide the two out-of-scope follow-ups from the live gate (2026-07-12):**
1. **Production baseline robustness (new).** In the live gate, `production`-label SCP-049 hard-failed 2/3 runs on (a) a YAML `mapping values are not allowed here` parse error — the model emitted an unquoted colon inside a `content:` value — and (b) a `'location'` `KeyError` path. These are *production* (baseline) failures, distinct from AC3's `scene coverage mismatch` (which is fixed) and from 6.9's truncation. `scenario/yaml_syntax_repair` is still unpromoted, so production fell back to a full-stage retry that also failed. → Should this become a story (YAML-safe `content:` serialization / promote `yaml_syntax_repair` / harden the `location` path)?
2. **N=3 median sufficiency.** SCP-096 shows a consistent negative median (total −1.00) across 3 clean runs. This is either a real candidate regression or N=3 medians are still noisy at 0.33-pt judge granularity. `--reps 5` is the cheap disambiguator (Jay cost/authorization decision). → Rerun at higher N before any 6-3/6-4 verdict is treated as final?

**B. Design points worth a focused review look (this story's code):**
- The median criterion is still *zero-tolerance on the median* (any negative median axis/total delta = FAIL). This was deliberate (AC1/AC4: absorb noise, don't loosen the bar). Confirm that's the intended semantics vs. a tolerance band inside judge granularity — if a band is wanted, it's a follow-up, not a bug here.
- `aggregate_runs` majority rule is `n_fail * 2 > reps` (strict majority; an even split is *not* isolated as failed, judged on the surviving successes). Confirm that tie-handling is acceptable.
- `SceneCoverageError` recovery is narrow by design: only a genuine set mismatch (not a reorder, not any other repair error) falls back to full rewrite. Confirm the narrow-recovery contract reads correctly against Story 6.9's.

**C. Cross-story status:** 6-3/6-4 remain `in-progress` (un-promoted). Their promotion is gated on resolving A.2 (and A.1 for SCP-049 scoreability). Do not close 6-3/6-4 as part of this review.

## Change Log

- 2026-07-11: Story created from Story 6.9's AC3/AC4 live multi-trial finding (axis regressions = variance; zero-tolerance gate structurally un-passable under generation noise + SCP-049 scoped-repair intermittent hard-failure). Jay's decision: statistical gate + repair robustness in one story to unblock 6-3/6-4. Status: backlog.
- 2026-07-11: Implemented AC1/AC2 (median-of-N statistical promotion gate + majority-fail item isolation + failed-run logging in `eval_prompts.py`), AC3 (SCP-049 scoped-repair reorder recovery + `SceneCoverageError` full-rewrite fallback), AC4-doc (`PROMPT_POLICY.md` zero-tolerance → statistical, with 6.6 rationale), AC5 (regression tests). Full suite 1263 passed/1 skipped, ruff clean.
- 2026-07-12: Ran the live median-of-3 promotion gate (AC4, Jay-authorized). Verdict FAIL → recorded, `production` labels NOT moved, 6-3/6-4 stay `in-progress`. Review corrected difference-of-medians to paired-delta median; the live FAIL remains valid due SCP-049 production majority failure, while axis evidence awaits a future corrected-gate rerun. All tasks complete. Status: in-progress → review.
- 2026-07-12: Adversarial code review completed. Fixed 3 findings: missing/duplicate run coverage now counts as hard failure, paired per-repetition deltas are medianed directly, and missing/extra repair scenes use `SceneCoverageError` recovery. Updated policy/evidence wording; 1265 passed/1 skipped, ruff clean. Status: review → done.

## File List

- `scripts/eval_prompts.py` — modified: `PROMOTION_REPS`, `positive_int`, `--reps`, `ResolvedProfile.reps` + `resolve_profile` reps logic, `ItemResult` run-provenance fields, `aggregate_runs`, `compare` row provenance, `print_comparison`/`_print_run_provenance`, `main` reps-aware baseline branch (AC1/AC2)
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — modified: `SceneCoverageError` class, `writing_scene_repair_step` reorder-recovery + coverage-mismatch raise (AC3)
- `src/yt_flow/pipeline/nodes/scenario.py` — modified: import `SceneCoverageError`, `_repair_and_review` caller full-rewrite fallback branch (AC3)
- `docs/PROMPT_POLICY.md` — modified: statistical promotion criterion + median-vs-zero-tolerance rationale + `--reps` knob (AC1/AC4)
- `tests/test_eval_prompts.py` — modified: `aggregate_runs`/median-verdict/isolation/reps-resolution/reps-run tests (AC5)
- `tests/pipeline/nodes/test_scenario_chain.py` — modified: permutation-reorder recovery + genuine-mismatch `SceneCoverageError` tests (AC5)
- `tests/pipeline/nodes/test_scenario.py` — modified: coverage-mismatch full-rewrite fallback test + narrowed non-recoverable-error test (AC5)
