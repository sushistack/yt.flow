---
created: 2026-07-11
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

Status: ready-for-dev

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

- [ ] Task 1: Add profile resolution as a pure CLI/config helper (AC: 1-3, 6)
- [ ] Task 2: Implement smoke execution and unmistakable non-promotion reporting (AC: 2, 4)
- [ ] Task 3: Harden promotion argument validation and timeout/max-token preflight (AC: 3, 5, 6)
- [ ] Task 4: Add `INCONCLUSIVE` comparison classification without changing non-zero gating (AC: 8)
- [ ] Task 5: Update `docs/PROMPT_POLICY.md` examples and authority rules (AC: 4, 7)
- [ ] Task 6: Add CLI, comparison, and artifact tests with no external calls (AC: 9)

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

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List
