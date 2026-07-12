---
title: 'Repair production baseline and run corrected 6.3/6.4 promotion gate'
type: 'bugfix'
created: '2026-07-12'
status: 'done'
baseline_commit: 'b81479b18805c5a674295f54d203f10c93926a45'
context:
  - '{project-root}/docs/PROMPT_POLICY.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The corrected paired-delta promotion gate cannot fairly decide Stories 6.3/6.4 because the production SCP-049 baseline hard-fails in scoped repair: repaired scenes discard required metadata, and the syntax-only YAML repair prompt is unavailable under `production`.

**Approach:** Preserve original scene metadata when applying narration repairs, bootstrap the already-versioned syntax-only repair prompt onto `production` without changing its content, verify the baseline, then run the authoritative corrected promotion gate and promote the tested 6.3/6.4 prompt versions only on PASS.

## Boundaries & Constraints

**Always:** Preserve candidate/production isolation; move labels only onto existing prompt versions; run `--profile promotion` with at least three repetitions and 16k tokens; record exact commands, artifact path, paired-median deltas, failures, and label actions. A PASS promotes exactly the nine 6.3/6.4 scenario prompt versions and closes both stories. FAIL/INCONCLUSIVE moves no 6.3/6.4 labels and leaves both stories `in-progress`.

**Ask First:** Any prompt-content edit, tolerance/median-policy change, gate repetition above 3, or attempt to fix a quality regression revealed by the corrected gate.

**Never:** Force promotion after non-PASS; seed repo text directly as `production`; silently use a `candidate` prompt in the production baseline; heuristic rewriting of arbitrary malformed YAML; close 6.3/6.4 without confirming the production label moves.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Scoped repair omits metadata | Repair returns only `scene_num` and `narration` | Original location, palette, atmosphere, and cast metadata survive; repaired fields win | Genuine coverage errors retain existing full-rewrite fallback |
| Production repair emits malformed YAML | Plain scalar contains an unquoted `: ` | Production syntax-repair prompt fixes syntax once with semantic content preserved | Second syntax/validation failure propagates and is logged |
| Corrected gate PASS | All paired median axis/total deltas are non-negative; no majority item failure | Move `production` onto the nine tested candidate versions; mark 6.3/6.4 done | Record every label move and verify resulting labels |
| Corrected gate non-PASS | Negative paired median, majority failure, or inconclusive infrastructure | No promotion; record the new blocker | Keep 6.3/6.4 in-progress |

</frozen-after-approval>

## Code Map

- `src/yt_flow/pipeline/nodes/scenario.py` -- `_repair_and_review` currently replaces complete scenes with minimal repair payloads.
- `src/yt_flow/pipeline/nodes/scenario_chain.py` -- bounded YAML syntax-repair routing and repaired-scene parsing.
- `prompts/scenario/yaml_syntax_repair.md` -- existing candidate syntax-only repair prompt whose version needs the production label bootstrap.
- `scripts/eval_prompts.py` -- authoritative paired-repetition statistical gate.
- `scripts/migrate_prompts.py` -- identifies the nine 6.3/6.4 repo prompt names; must not be used to author production versions.
- `_bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md` -- shared live evidence ledger.

## Tasks & Acceptance

**Execution:**
- [x] `src/yt_flow/pipeline/nodes/scenario.py` -- overlay repaired fields onto original scenes so minimal repair payloads cannot erase downstream metadata.
- [x] `tests/pipeline/nodes/test_scenario.py` -- cover metadata preservation and explicit repaired-field precedence.
- [x] `tests/pipeline/nodes/test_scenario_chain.py` -- reproduce the observed colon YAML failure and verify the syntax-only repair path preserves semantics.
- [x] Langfuse `scenario/yaml_syntax_repair` -- move `production` onto the existing tested candidate version, with no prompt-content mutation, and verify both labels resolve as intended.
- [x] Baseline validation -- run production SCP-049 smoke/diagnostic evidence before spending the full gate budget.
- [x] `scripts/eval_prompts.py` -- run `YTFLOW_DEEPSEEK_MAX_TOKENS=16000 uv run python scripts/eval_prompts.py --profile promotion --reps 3` and capture its exit code/artifacts.
- [x] Story/report/sprint artifacts -- apply the PASS or non-PASS branch exactly; on PASS move the nine tested prompt versions to production and verify them before closing 6.3/6.4.

**Acceptance Criteria:**
- Given a scoped repair containing only identity and narration, when repaired scenes re-enter visual breakdown, then all required original metadata remains available and no `KeyError` occurs.
- Given the observed malformed `content: ...: ...` YAML, when production syntax repair runs, then it performs one bounded syntax-only correction without candidate fallback or semantic regeneration.
- Given the corrected authority gate, when it exits, then the recorded verdict is derived from paired per-repetition median deltas and includes all hard-failure provenance.
- Given PASS, when production labels are moved, then all nine target names resolve to the tested versions and Stories 6.3/6.4 become `done`; otherwise no target label moves and both remain `in-progress`.

## Spec Change Log

## Design Notes

The syntax-repair label move is a narrow bootstrap required to make the production baseline scoreable, matching the earlier `writing_scene_repair` label-gap precedent. It moves an existing tested version and does not create or edit prompt content. The nine gated 6.3/6.4 prompts are `scenario/format_guide`, `research`, `structure`, `writing`, `cast_decision`, `visual_breakdown`, `review`, `critic_agent`, and `tts_normalize`.

## Verification

**Commands:**
- `uv run pytest -q tests/pipeline/nodes/test_scenario.py tests/pipeline/nodes/test_scenario_chain.py tests/test_eval_prompts.py` -- targeted regressions pass.
- `uv run ruff check <changed Python files>` -- clean.
- `uv run pytest -q` -- full suite passes before live execution.
- `YTFLOW_DEEPSEEK_MAX_TOKENS=16000 uv run python scripts/eval_prompts.py --profile smoke --baseline production` -- SCP-049 baseline is scoreable.
- `YTFLOW_DEEPSEEK_MAX_TOKENS=16000 uv run python scripts/eval_prompts.py --profile promotion --reps 3` -- authoritative PASS/FAIL evidence.

## Implementation Record

- Local verification: 344 targeted tests passed; full suite 1266 passed/1 skipped; Ruff and `git diff --check` clean.
- Langfuse bootstrap: `scenario/yaml_syntax_repair` version 1 now carries both `candidate` and `production`; prompt content was not changed.
- Baseline smoke: PASS, artifact `tmp/eval-prompts/20260712-104225-1783820545768754809-candidate-production/`.
- Corrected authority gate: FAIL (exit 1), artifact `tmp/eval-prompts/20260712-105849-1783821529137928646-candidate-production/`. Paired medians: SCP-049 total −1.00; SCP-173 article_fidelity −0.33; SCP-096 total −0.83. Neither side had a majority hard failure.
- Non-PASS branch applied: no 6.3/6.4 production labels moved; both stories remain `in-progress`; report and sprint tracking updated.

## Suggested Review Order

**Runtime baseline repair**

- Preserve complete scene metadata while allowing repaired fields to override originals.
  [`scenario.py:272`](../../src/yt_flow/pipeline/nodes/scenario.py#L272)

**Live authority evidence and decision**

- Review the corrected paired-delta table, hard failures, and non-promotion verdict.
  [`6-3-6-4-review-metrics-report.md:166`](6-3-6-4-review-metrics-report.md#L166)

- Confirm Story 6.3 remains open because the authority gate failed quality deltas.
  [`6-3-prompt-cache-hit-optimization.md:183`](6-3-prompt-cache-hit-optimization.md#L183)

- Confirm Story 6.4 Task 8 and production promotion remain incomplete.
  [`6-4-scenario-yaml-output-bounded-retry.md:175`](6-4-scenario-yaml-output-bounded-retry.md#L175)

- Verify sprint tracking reflects the new quality blocker without closing either story.
  [`sprint-status.yaml:131`](sprint-status.yaml#L131)

**Regression coverage**

- Exercise metadata preservation and explicit repair-field precedence end to end.
  [`test_scenario.py:157`](../../tests/pipeline/nodes/test_scenario.py#L157)

- Reproduce the exact unquoted-colon syntax-repair case without semantic drift.
  [`test_scenario_chain.py:757`](../../tests/pipeline/nodes/test_scenario_chain.py#L757)
