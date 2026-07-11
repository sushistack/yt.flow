---
created: 2026-07-11
baseline_commit: 29f5a74f57258c0151e15816eac99ec3edc266e3
story_key: 6-6-tiered-prompt-evaluation-gates
story_id: "6.6"
epic: 6
previous_story: 6-5-scenario-scoped-repair-retry
depends_on:
  - 6-2-golden-set-offline-eval
related:
  - 6-5-scenario-scoped-repair-retry
evidence: "A single SCP-096 candidate-vs-production full comparison took over 20 minutes and still timed out symmetrically at 600s/item with max_tokens=16000; the default 8192 attempt truncated visual_breakdown. Running all three items on every prompt edit is not a viable inner development loop."
---

# Story 6.6: Tiered Prompt Evaluation Gates

Status: done

## Story

As Jay,
I want a fast one-item smoke gate for prompt iteration and a clearly separate promotion gate,
so that routine development gets useful feedback without paying for three full candidate/production scenarios on every edit while production safety remains explicit.

## Acceptance Criteria

1. **Given** `scripts/eval_prompts.py`, **then** it supports explicit `--profile smoke|promotion`. Existing invocations without `--profile` retain current promotion behavior for backward compatibility; no command may silently weaken an existing production gate.
2. **Given** `--profile smoke`, **then** exactly one documented canary (`SCP-049`) is selected unless `--scp-id` overrides it. The profile runs candidate only by default, writes the existing artifact/usage metadata, applies deterministic rule checks, and exits non-zero on scenario/scoring failure. `--baseline production` is optional for a one-item comparison.
3. **Given** `--profile promotion`, **then** all three golden items and candidate-vs-production comparison remain mandatory, and an explicit `--scp-id` is rejected. This is the only profile whose PASS may authorize moving the production label.
4. **Given** any smoke PASS, **then** CLI output and persisted artifact metadata visibly state `NOT A PROMOTION GATE`; docs forbid using it as production-label authority.
5. **Given** the observed runtime, **then** the eval default item timeout becomes `1200s` for full-scenario profiles, while stage-isolation retains a smaller explicit timeout where appropriate. Evaluation guidance requires `YTFLOW_DEEPSEEK_MAX_TOKENS=16000` for full scenario gates so default-8192 truncation cannot masquerade as prompt regression.
6. **Given** `--stage` isolation, **then** it remains a diagnostic tool and never a promotion authority. Smoke may combine one canary with one selected stage; promotion rejects stage isolation.
7. **Given** policy documentation, **then** the workflow is: local tests → optional stage isolation → one-item smoke during iteration → three-item promotion once before production. The three-item set is reduced in **frequency**, not silently reduced in safety coverage.
8. **Given** a promotion run fails because both candidate and production hit the same timeout/infrastructure class, **then** the report classifies it as `INCONCLUSIVE` while still exiting non-zero. Candidate-only failure remains `FAIL`. Neither result authorizes promotion.
9. **Given** tests, **then** they cover profile defaults/overrides, smoke labeling, promotion rejection of `--scp-id`/`--stage`, 1200s full timeout, unchanged comparison thresholds, symmetric infrastructure failure classification, and backward-compatible no-profile behavior.
10. **Given** implementation scope, **then** no CI service, scheduler, database, new dataset, or automatic Langfuse label mutation is added. Nightly/async promotion automation stays deferred until manual promotion frequency justifies it.

## Tasks / Subtasks

- [x] Task 1: Add profile resolution as a pure CLI/config helper (AC: 1-3, 6)
- [x] Task 2: Implement smoke execution and unmistakable non-promotion reporting (AC: 2, 4)
- [x] Task 3: Harden promotion argument validation and timeout/max-token preflight (AC: 3, 5, 6)
- [x] Task 4: Add `INCONCLUSIVE` comparison classification without changing non-zero gating (AC: 8)
- [x] Task 5: Update `docs/PROMPT_POLICY.md` examples and authority rules (AC: 4, 7)
- [x] Task 6: Add CLI, comparison, and artifact tests with no external calls (AC: 9)

### Review Findings

- [x] [Review][Patch] `--profile promotion`'s max-tokens preflight uses exact equality (`== _RISKY_DEFAULT_MAX_TOKENS`) instead of a threshold, so an explicit-but-still-risky value (e.g. 10000) silently bypasses the guard — contradicts the check's own error message ("requires ... >= 16000") [scripts/eval_prompts.py:main preflight] — fixed: check is now `< _MIN_MAX_TOKENS_FOR_PROMOTION` (16000), added regression test for an intermediate value
- [x] [Review][Patch] `write_profile_metadata`'s `"PROMOTION GATE"` authority string is a bare literal instead of a named constant beside `NOT_A_PROMOTION_GATE`, and no test asserts `_profile.json` contents for the `promotion` profile (only `smoke` is covered) [scripts/eval_prompts.py] — fixed: added `PROMOTION_GATE_AUTHORITY` constant + `test_main_promotion_profile_persists_authority_metadata`
- [x] [Review][Defer] `_is_infra_failure`'s substring match on `"timeout"` is fragile both ways (empty-message httpx timeouts go undetected; unrelated errors containing "timeout" text would be misclassified); a correct fix needs typed exception info preserved across `scenario_node`'s string-only error contract — deferred, out of scope
- [x] [Review][Defer] `DEFAULT_ITEM_TIMEOUT_SECONDS = 1200.0` is pinned to the worst observed run duration with zero margin — deferred pending more live-run data
- [x] [Review][Defer] `--profile promotion` doesn't reject an explicit `--timeout` override, so a short override can defeat the 1200s safety default; AC3 enumerates `--scp-id`/`--stage` as promotion's explicit rejections but not `--timeout` — deferred, policy decision beyond this review

## Dev Notes

### Policy Decision

- Three items are too expensive for the inner loop, but deleting two from the production gate would turn one stochastic judge result into the sole release signal.
- The chosen optimization reduces how often three items run: one canary for iteration, all three once for promotion.
- `SCP-049` is the smoke default because prior isolated runs completed successfully and it exercises the same full scenario contract. Keep the canary constant for score history; do not randomly rotate it.
- A smoke result may be useful even without a baseline, but it is health feedback—not regression proof. A one-item candidate-vs-production smoke is stronger but still not promotion authority.

### Existing Code To Reuse

- Reuse `GOLDEN_IDS`, `evaluate_label`, `run_stage`, `compare`, `write_artifact`, and `--scp-id`; do not create a second runner.
- Keep Langfuse Dataset experiment recording. Profiles only select items/authority and presentation.
- `compare` currently returns PASS/FAIL. Add `INCONCLUSIVE` only for symmetric infrastructure failures, preserving exit code 1.
- Artifacts already persist parsed state and stage token/cache metadata for passing and failing items.

### Expected Files

- UPDATE: `scripts/eval_prompts.py`
- UPDATE: `tests/test_eval_prompts.py`
- UPDATE: `docs/PROMPT_POLICY.md`
- Optional UPDATE: `_bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md` with measured smoke duration after implementation

### Testing Requirements

- Test `main(argv)` with fake datasets/scenario/judge seams; no network calls.
- Assert exit codes and exact authority labels in stdout.
- Preserve existing CLI tests and current per-axis/total zero-regression thresholds.

### Out of Scope

- Reducing the promotion set below three.
- Replacing the LLM judge or changing scoring axes/thresholds.
- Caching stale production scores across prompt/model/settings changes.
- Automatic production-label movement, CI, cron, or nightly infrastructure.

### References

- [Source: `scripts/eval_prompts.py` — `GOLDEN_IDS`, `DEFAULT_ITEM_TIMEOUT_SECONDS`, `evaluate_label`, `compare`, `main`]
- [Source: `docs/PROMPT_POLICY.md#Pass criteria`]
- [Source: `_bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md#2026-07-11 single-item gate attempt`]
- [Source: `_bmad-output/planning-artifacts/epics.md#Story 6.2: 골든셋 + 오프라인 프롬프트 회귀 평가 러너`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- `PYTHONPATH=$PWD/src uv run pytest tests/test_eval_prompts.py -q` → 91 passed
- `PYTHONPATH=$PWD/src uv run ruff check scripts/eval_prompts.py tests/test_eval_prompts.py` → All checks passed
- `PYTHONPATH=$PWD/src uv run pytest -q --ignore=tests/pipeline/nodes/test_character_service_generation.py` → 1226 passed, 1 skipped (that one file is a known slow/real-file-writing outlier per prior session notes, unrelated to this story; not touched)

### Completion Notes List

- Added `--profile smoke|promotion` to `scripts/eval_prompts.py` via a pure `resolve_profile()` helper: no `--profile` is an exact passthrough (backward compatible, AC1); `smoke` defaults to `SCP-049` + `candidate` label, allows `--scp-id`/`--stage`/optional `--baseline` override, never gains promotion authority; `promotion` forces `candidate`/`production`, rejects `--scp-id` and non-`full` `--stage`.
- `smoke` results (pass or fail) print `NOT A PROMOTION GATE` and persist it in a new `_profile.json` run-metadata file (kept separate from the existing per-item artifact schema so those files/tests stay unchanged) (AC4).
- Bumped the full-scenario default timeout to `1200s` (from `600s`) per observed real-run durations; stage isolation (`run_stage`) keeps its own smaller `600s` default (AC5).
- `--profile promotion` hard-fails preflight (before any dataset/LLM call) if `YTFLOW_DEEPSEEK_MAX_TOKENS` is at the risky `8192` default — promotion is the only profile with production-label authority, so it's the only one that blocks instead of warning (AC3, AC5).
- `compare()` now classifies a candidate+baseline pair that both fail with a timeout-shaped error as `INCONCLUSIVE` (still exits non-zero, still blocks promotion) instead of `FAIL`, so a broken/shared-infra failure isn't misreported as a candidate regression; any other failure (including timeout on one side only, or a genuine axis/total regression elsewhere in the run) still forces `FAIL` (AC8).
- Updated `docs/PROMPT_POLICY.md`: change protocol now references smoke/promotion by name, added a "Tiered evaluation profiles" section documenting the workflow order, authority rule, and runtime knobs, and folded the `INCONCLUSIVE` verdict into the pass-criteria note.
- Added 40 new tests covering profile-resolution defaults/overrides/rejections, smoke CLI behavior (canary default, banner, persisted metadata, stage-isolation combo), promotion CLI behavior (rejections, three-item run, 1200s default, max-tokens preflight), no-profile backward compatibility, and `INCONCLUSIVE` classification + printing. All existing tests pass unmodified.
- Out of scope items (CI/scheduler/DB, reducing promotion below three items, judge/axis changes, automatic label mutation) were not touched, per Dev Notes.

### File List

- UPDATE: `scripts/eval_prompts.py`
- UPDATE: `tests/test_eval_prompts.py`
- UPDATE: `docs/PROMPT_POLICY.md`

## Change Log

- 2026-07-11: Implemented `--profile smoke|promotion`, `INCONCLUSIVE` comparison classification, 1200s full-scenario timeout default, and promotion-only max-tokens preflight; updated `docs/PROMPT_POLICY.md`; added 40 tests. Status → review.
- 2026-07-11: Code review (bmad-code-review, joint with 6.5) complete — 2 findings fixed (promotion max-tokens preflight was exact-equality, not a `< 16000` threshold; `PROMOTION_GATE_AUTHORITY` named constant + missing promotion `_profile.json` metadata test), 3 deferred (fragile `_is_infra_failure` substring matching, zero-margin 1200s timeout, promotion not rejecting `--timeout` override). Full regression suite green (1232 passed, 1 skipped), ruff clean. Status → done.
