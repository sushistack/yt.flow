---
created: 2026-07-12
baseline_commit: 7c62973
story_key: 6-12-ab-promotion-gate-freeze-deferred-candidate
story_id: "6.12"
epic: 6
previous_story: 6-10-statistical-promotion-gate-repair-robustness
depends_on:
  - 6-10-statistical-promotion-gate-repair-robustness  # provided the corrected median gate whose FAIL confirms the candidate is a real (not noise) regression
related:
  - 6-3-prompt-cache-hit-optimization    # code done; only its production promotion is deferred here
  - 6-4-scenario-yaml-output-bounded-retry
evidence: "2026-07-12 corrected paired-delta authority gate (--profile promotion --reps 3, 16k; tmp/eval-prompts/20260712-105849-...-candidate-production/, exit 1): FAIL on quality deltas with NO majority hard-fail — SCP-049 total -1.00 (all axes negative), SCP-173 article_fidelity -0.33, SCP-096 coherence -0.83/article_fidelity -0.33/total -0.83. 6.10 already removed generation-noise as an explanation (median-of-3 + scoreable baseline repair), so the negative medians are a REAL candidate regression, not variance. Blocker reclassified from 'gate structurally un-passable' (6.9/6.10) to 'candidate prompt genuinely scores below production'. Jay decision: close 6-3/6-4 as code-done, carve the deferred promotion out here, and FREEZE the token-heavy A/B gate until the pipeline itself is complete."
---

# Story 6.12: A/B 승격 게이트 동결 + 6-3/6-4 후보 승격 보류

Status: done

## Story

As Jay,
I want the candidate-vs-production A/B promotion gate to stop running (and stop burning tokens) during pipeline development, and the still-unpromoted 6-3/6-4 candidate prompts to be tracked as deferred rather than blocking,
so that the team's effort and token budget go to **pipeline completeness** (Epic 8 등) now, and prompt-quality promotion resumes deliberately later when it actually matters.

## Context

The 6.6→6.7→6.8→6.9→6.10 chain removed every *crash-class* and *measurement-noise* reason the 6-3/6-4 promotion gate FAILed. With 6.10's statistical median gate and the repaired (scoreable) production baseline in place, the gate is now trustworthy — and it still returns **FAIL**, this time on pure paired-quality deltas with no majority hard-failure:

| item | signal |
|------|--------|
| SCP-049 | total −1.00, all three axes negative |
| SCP-173 | article_fidelity −0.33 |
| SCP-096 | narrative_coherence −0.83, article_fidelity −0.33, total −0.83 |

That reclassifies the blocker: it is no longer "the gate can't be passed" (measurement) — it is "the candidate prompt is genuinely worse than production on these items" (content). Forcing a promotion is off the table (Prompt Policy), and there is no authorization here to edit prompt content or loosen the gate tolerance.

Two decisions follow (Jay, 2026-07-12):

1. **6-3/6-4 are code-complete.** Their implementation shipped and is reviewed; only the *label move* remains, and that is gated on candidate quality — which is a quality-tuning concern, not a pipeline-completeness one. Close them `done`; track the deferred promotion here.
2. **The A/B gate is a quality-tuning tool, not a pipeline-build tool.** A full candidate-vs-production comparison regenerates the entire scenario chain × 2 labels × N reps — the single most token-expensive thing in the repo — and produces no pipeline-completeness value. It must not run (accidentally or on a cadence) until the pipeline is complete. Enforce that with a hard guard, not just a policy note.

## Acceptance Criteria

1. **Given** `scripts/eval_prompts.py` is invoked with a `--baseline` (a candidate-vs-production comparison — `--profile promotion` resolves a baseline too), **When** `YTFLOW_ALLOW_AB_GATE` is not `1`, **Then** it hard-errors before any client build / scenario run, naming the freeze and the override. Single-label runs (`--label X`, no `--baseline`) and `--profile smoke` stay available for diagnostics. **DONE.**
2. **Given** the freeze, **Then** `docs/PROMPT_POLICY.md` carries a prominent banner stating the freeze, the override env var, and the un-freeze condition (pipeline complete / quality-tuning resumes). **DONE.**
3. **Given** the guard, **Then** regression tests cover: override-absent `--baseline` and `--profile promotion` both blocked (with a `FROZEN` message), single-label run not blocked, and override-present runs behave exactly as before (an autouse fixture authorizes the existing gate-mechanics tests). **DONE.**
4. **(Deferred / future trigger — out of scope here.)** When the pipeline is complete and quality tuning resumes, un-freeze (`YTFLOW_ALLOW_AB_GATE=1`), re-run the median statistical gate, and promote 6-3/6-4 (and any Epic 8 candidate prompts deferred the same way — 8-5, 8-8, …) only on a genuine median-PASS. This AC records the trigger; it is not implemented by this story.

## Implementation

- `scripts/eval_prompts.py`: added `AB_GATE_OVERRIDE_ENV = "YTFLOW_ALLOW_AB_GATE"` and a guard in `main()` — `if args.baseline and os.environ.get(...) != "1": ap.error(...)`. Placed after existing arg validation and before the promotion max-tokens check, so it short-circuits before `Settings()`/`build_client()`.
- `docs/PROMPT_POLICY.md`: freeze banner at the top.
- `tests/test_eval_prompts.py`: autouse `_authorize_ab_gate` fixture (sets the override for the gate-mechanics suite) + 3 dedicated freeze tests (`test_baseline_comparison_frozen_without_override`, `test_promotion_profile_frozen_without_override`, `test_single_label_run_not_frozen`).
- `_bmad-output/implementation-artifacts/sprint-status.yaml`, `_bmad-output/planning-artifacts/epics.md`: 6-3/6-4 → done, 6-12 recorded.

Verification: `uv run pytest tests/test_eval_prompts.py -q` → 112 passed. Live CLI: `--profile promotion` and `--label candidate --baseline production` both hard-error with the FROZEN message; single-label runs proceed.

## Ponytail notes

- The nail is one env-gated `ap.error` branch + a doc banner — no scheduler/CI to disable (grep confirmed the gate has no automated invoker; it only ran when a human/session ran it). `# ponytail: freeze = one guard on --baseline; the override env is the un-freeze knob.`
- Guard keys on `--baseline` (the two-sided A/B), not on `--profile promotion` alone, so the bare `--label X --baseline Y` path can't sneak the expensive comparison past the freeze.
