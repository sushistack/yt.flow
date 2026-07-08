---
created: 2026-07-08
story_key: 8-4a-special-pose-prompt-gate-decomposition
story_id: "8.4a"
epic: 8
previous_story: 8-4-on-demand-special-pose-cards
depends_on:
  - 8-4-on-demand-special-pose-cards
  - 8-10-cast-decision-split-call
related:
  - 6-2-golden-set-offline-eval
  - docs/PROMPT_POLICY.md
---

# Story 8.4a: Special-Pose Prompt Gate Decomposition

Status: ready-for-dev

## Story

As Jay,
I want the special-pose prompt rollout gate decomposed by SCP item and scenario stage, with explicit failure artifacts and timeouts,
so that `pose_hint` prompt quality can be evaluated and promoted without hiding JSON, truncation, baseline, or external-runner failures behind a single opaque `item failure`.

## Context

Story 8.4 delivered the runtime implementation for on-demand special-pose cards: `pose_hint` parsing, deterministic `hint:*` cache keys, special-pose card generation, scenario-approval provisioning, resolver hint lookup/fallback, cap/mock behavior, and regression coverage.

The remaining blocker is not the 8.4 runtime path. The prompt rollout gate is currently too coarse:

- `scripts/eval_prompts.py --label candidate --baseline production` collapses structural failures into `item failure`.
- At default `YTFLOW_DEEPSEEK_MAX_TOKENS=8192`, both candidate and production can fail from stage truncation.
- A `YTFLOW_DEEPSEEK_MAX_TOKENS=16000 --max-concurrency 1` retry still took too long and was interrupted while waiting in baseline evaluation.
- Candidate single-label evidence from 2026-07-08: `SCP-049` JSON parse failure, `SCP-173` `scenario/writing` truncation, `SCP-096` scored successfully.
- Production single-label evidence from 2026-07-08: all three items failed from stage truncation (`visual_breakdown`, `tts_normalize`, `writing`) at the default max-token setting.

This story owns the prompt/eval decomposition and the live validation that 8.4 deliberately transferred here. It must not reopen the already-closed 8.4 runtime implementation unless a decomposed failure proves a runtime bug.

## Acceptance Criteria

1. **Item targeting.** Given `scripts/eval_prompts.py`, then the CLI supports running a single golden item by SCP id, e.g. `--scp-id SCP-049`, for both single-label and baseline-comparison modes. Invalid ids fail fast with a readable error listing valid golden ids.
2. **Stage targeting.** Given the same script, then the CLI can run enough of the scenario chain to isolate a requested stage failure, at minimum `--stage full`, `--stage writing`, `--stage cast_decision`, and `--stage visual_breakdown`. Stage mode may reuse earlier real stages as prerequisites, but the output report must identify which stage failed and why.
3. **Failure artifacts.** Given any failed item/stage, then the script writes local debug artifacts under `tmp/eval-prompts/{timestamp-or-run-id}/...`: rendered output text/JSON where available, parsed scenario state where available, label, SCP id, stage, finish reason, and error text. Artifact paths are printed in the CLI output.
4. **Timeouts.** Given an external LLM/Langfuse run stalls, then the script enforces a configurable per-item timeout (default documented) and reports a timeout failure instead of waiting indefinitely. The timeout must apply to both candidate and baseline item evaluation.
5. **Comparison clarity.** Given candidate-vs-production mode, then each failed row prints candidate and baseline errors separately, including artifact paths when available. Existing item-failure detail from commit `a445ba8` is preserved and extended, not regressed.
6. **Token-budget gate.** Given golden-set evaluation for this story, then use an explicit eval token budget (`YTFLOW_DEEPSEEK_MAX_TOKENS=16000` or a documented better value) and record whether failures remain structural, quality-score regressions, or external timeouts. Do not silently depend on the default `8192`.
7. **Prompt rollout decision.** Given decomposed evidence, then rerun the `pose_hint` candidate gate on the three golden SCPs and record a clear PASS/FAIL/DEFER decision. If FAIL/DEFER, list exact failing SCP/stage pairs and whether the cause is prompt JSON validity, truncation, quality regression, or runner timeout.
8. **Live validation.** Given the prompt gate is structurally stable enough to produce a scenario with a `pose_hint`, then run one real ComfyUI validation for SCP-049 or a similarly suitable SCP: generate one special-pose card, verify RGBA/framing/readability, rerun to verify cache hit, and record paths/evidence. If live validation is blocked by prompt gate instability, document the blocker instead of pretending it passed.
9. **Tests.** Given automated verification, then add unit tests for `--scp-id`, invalid id handling, stage-report formatting, timeout reporting with fakes, and comparison rows containing separate candidate/baseline errors plus artifact paths. Existing eval tests remain green.

## Tasks / Subtasks

- [ ] Task 1 — Add item targeting (AC: 1, 9)
  - [ ] Add `--scp-id` to `scripts/eval_prompts.py`.
  - [ ] Filter seeded/fetched dataset items deterministically.
  - [ ] Add invalid-id fast-fail tests.
- [ ] Task 2 — Add stage targeting and structural reports (AC: 2, 5, 9)
  - [ ] Add `--stage` with the supported stage values.
  - [ ] Ensure failures include `stage=...`, SCP id, label, and readable root cause.
  - [ ] Preserve full-mode behavior for existing CI/user commands.
- [ ] Task 3 — Persist failure artifacts (AC: 3, 5, 9)
  - [ ] Create a local artifact writer under `tmp/eval-prompts/`.
  - [ ] Store raw output, parsed state where available, and metadata.
  - [ ] Print artifact paths in single-label and comparison reports.
- [ ] Task 4 — Add per-item timeout (AC: 4, 9)
  - [ ] Add timeout config/CLI option.
  - [ ] Convert timeout into an item failure, not a crashed script.
  - [ ] Cover with fake async tests.
- [ ] Task 5 — Rerun decomposed gate (AC: 6, 7)
  - [ ] Run candidate and production with explicit max tokens and the new diagnostics.
  - [ ] Record PASS/FAIL/DEFER with exact SCP/stage pairs.
  - [ ] Update 8.4a Dev Agent Record and, if appropriate, Prompt Policy evidence.
- [ ] Task 6 — Live special-pose validation (AC: 8)
  - [ ] Generate one real special-pose card using ComfyUI.
  - [ ] Verify alpha/framing/readability.
  - [ ] Verify deterministic cache hit on second invocation.

## Dev Notes

- Do not weaken 8.4's runtime non-fatal contract. This story is about measuring and stabilizing prompt/eval behavior.
- `scenario/cast_decision` is now the authoritative cast emitter after Story 8.10. Do not put new `pose_hint` rules only in `visual_breakdown`.
- The failure mode to avoid is another opaque all-in-one gate where candidate, baseline, stage truncation, JSON parse, score regression, and runner timeout are indistinguishable.
- Keep artifacts local and git-ignored. Do not commit generated LLM outputs unless Jay explicitly asks for evidence snapshots.
- Prefer small, testable changes in `scripts/eval_prompts.py`; avoid changing production scenario runtime unless a decomposed result proves a runtime bug.

## References

- `_bmad-output/implementation-artifacts/8-4-on-demand-special-pose-cards.md` — runtime implementation and transfer decision.
- `scripts/eval_prompts.py` — current golden-set eval runner.
- `tests/test_eval_prompts.py` — existing eval-runner unit tests.
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — stage functions to isolate.
- `docs/PROMPT_POLICY.md` — prompt rollout and promotion policy.

## Dev Agent Record

### Debug Log References

- Created from Jay's 2026-07-08 decision to close 8.4 runtime scope and split prompt/eval/live validation into a dedicated follow-up story.

### Completion Notes List

### File List

## Change Log

- 2026-07-08: Story created as the follow-up home for 8.4 Task 2 prompt rollout and Task 6 live validation.
