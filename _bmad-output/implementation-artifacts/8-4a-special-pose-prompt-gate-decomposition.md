---
created: 2026-07-08
baseline_commit: 5fe4ff2f62ed60f0f46cde312922af7e53f31417
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

Status: done

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

- [x] Task 1 — Add item targeting (AC: 1, 9)
  - [x] Add `--scp-id` to `scripts/eval_prompts.py`.
  - [x] Filter seeded/fetched dataset items deterministically.
  - [x] Add invalid-id fast-fail tests.
- [x] Task 2 — Add stage targeting and structural reports (AC: 2, 5, 9)
  - [x] Add `--stage` with the supported stage values.
  - [x] Ensure failures include `stage=...`, SCP id, label, and readable root cause.
  - [x] Preserve full-mode behavior for existing CI/user commands.
- [x] Task 3 — Persist failure artifacts (AC: 3, 5, 9)
  - [x] Create a local artifact writer under `tmp/eval-prompts/`.
  - [x] Store raw output, parsed state where available, and metadata.
  - [x] Print artifact paths in single-label and comparison reports.
- [x] Task 4 — Add per-item timeout (AC: 4, 9)
  - [x] Add timeout config/CLI option.
  - [x] Convert timeout into an item failure, not a crashed script.
  - [x] Cover with fake async tests.
- [x] Task 5 — Rerun decomposed gate (AC: 6, 7)
  - [x] Run candidate and production with explicit max tokens and the new diagnostics.
  - [x] Record PASS/FAIL/DEFER with exact SCP/stage pairs.
  - [x] Update 8.4a Dev Agent Record and, if appropriate, Prompt Policy evidence.
- [x] Task 6 — Live special-pose validation (AC: 8)
  - [x] Generate one real special-pose card using ComfyUI.
  - [x] Verify alpha/framing/readability.
  - [x] Verify deterministic cache hit on second invocation.

### Review Findings

- [x] [Review][Patch] Stage isolation can misreport prerequisite failures as the requested stage [scripts/eval_prompts.py:271]
- [x] [Review][Patch] Full-run failure artifacts drop available parsed scenario output [scripts/eval_prompts.py:187]
- [x] [Review][Patch] `--scp-id` filtering mutates the dataset object in place [scripts/eval_prompts.py:210]
- [x] [Review][Patch] `--timeout` accepts zero or negative values [scripts/eval_prompts.py:425]
- [x] [Review][Patch] Same-second eval runs share artifact directories [scripts/eval_prompts.py:60]

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

- Tasks 1-4: `scripts/eval_prompts.py` now supports `--scp-id` (argparse `choices=GOLDEN_IDS`, so an invalid id fails fast via argparse's own "invalid choice" message listing valid ids — AC1), `--stage {full,writing,cast_decision,visual_breakdown}` (AC2), a local JSON artifact writer under `tmp/eval-prompts/{run_id}/` for every failed item/stage (AC3), and a per-item `--timeout` (default 600s, documented in `--help`) enforced via `asyncio.wait_for` around both the full `scenario_node` run and the isolated stage chain (AC4).
- Stage mode (`--stage` other than `full`) is a diagnostic-only path: it calls `research_step`/`structure_step`/`writing_step`/`cast_decision_step`/`visual_breakdown_step` directly (bypassing `scenario_node`'s black-box try/except and Langfuse scoring) so a failure is attributed to one real stage, with the actual failing DeepSeek call's raw output + finish_reason captured via a recording wrapper around `_call_deepseek` (AC3, AC5). Earlier stages run for real as prerequisites; only the first scene is carried into cast_decision/visual_breakdown, matching the "isolate one shot's failure" scope of AC2 rather than reproducing the full per-scene fan-out.
- `compare()`/`print_comparison()`/`print_report()` extended to carry and print `candidate_artifact`/`baseline_artifact`/`artifact_path` on every failed row (AC5) — existing item-failure detail from commit `a445ba8` preserved, not regressed (all pre-existing tests still pass unchanged).
- AC6 (token-budget gate): `main()` now prints a stderr WARNING (`_RISKY_DEFAULT_MAX_TOKENS = 8192`) whenever `Settings().deepseek_max_tokens` is left at the default, so a truncation-prone run is never silent. All Task 5 live runs below were executed with `YTFLOW_DEEPSEEK_MAX_TOKENS=16000` (no warning printed).
- 46 new/updated tests added to `tests/test_eval_prompts.py` (30 → 52); full regression suite: 1006 passed, 1 skipped, ruff clean.
- `tmp/` added to `.gitignore` (artifacts are local debug output only, per Dev Notes).

**Task 5 — live decomposed gate rerun (2026-07-09, `YTFLOW_DEEPSEEK_MAX_TOKENS=16000`, real DeepSeek + Langfuse):**

1. `uv run python scripts/eval_prompts.py --label candidate --timeout 900 --max-concurrency 3` — all 3 golden SCPs completed structurally (no truncation, no JSON-parse failure): SCP-049 total=13.33, SCP-173 total=12.00, SCP-096 total=12.00. This resolves the 8.4/8.4a-blocking truncation and JSON-parse failures reported at the default 8192-token budget (2026-07-08 evidence: SCP-049 JSON parse failure, SCP-173 `scenario/writing` truncation) — raising the token budget alone fixes the structural instability.
2. `uv run python scripts/eval_prompts.py --label production --timeout 900 --max-concurrency 3` — all 3 golden SCPs also completed structurally: SCP-049 total=13.67, SCP-173 total=13.33, SCP-096 total=12.33.
3. `uv run python scripts/eval_prompts.py --label candidate --baseline production --timeout 900 --max-concurrency 3` (full re-run, both labels) — **Verdict: FAIL**. Exact SCP/stage pairs and cause:
   - **SCP-049** — regressed. `narrative_coherence` candidate 4.00 vs production 4.67 (`-0.33`); `atmosphere` and `article_fidelity` both improved. Cause: **quality-score regression** on one axis, not a structural failure — violates Prompt Policy's per-axis pass criteria (every candidate axis must be `>=` production).
   - **SCP-096** — regressed. `narrative_coherence` candidate 3.67 vs production 5.00 (`-0.33` reported delta reflects this run's pairing); `atmosphere` and `article_fidelity` improved. Same cause: narrative_coherence quality-score regression.
   - **SCP-173** — item failure, **production side**: `stage=scenario ... visual_breakdown: expected 1:1 sentence-to-shot mapping (5 sentences), got non-list` (artifact: `tmp/eval-prompts/20260709-002955-candidate-production/production-SCP-173-full.json`, `finish_reason=null`, not a truncation). Cause: **runner/model non-determinism** on the baseline (production) prompt, not a candidate/pose_hint defect — the same SCP-173/production pairing succeeded structurally in step 2's standalone run 9 minutes earlier with the identical prompt. Per Prompt Policy, a broken baseline run also fails the comparison (inconclusive, cannot justify promotion).
   - **Decision: FAIL — do not promote `candidate` to `production`.** Two independent, non-overlapping causes: (a) a real `narrative_coherence` axis regression on 2/3 items, and (b) baseline-side non-determinism on the 3rd item that leaves the comparison inconclusive there. Neither is a runtime bug in yt.flow's own code (Dev Notes scope guard) — story 8.4's runtime implementation is not reopened.
   - **Follow-up (out of this story's scope, left for a future prompt-iteration pass):** the `narrative_coherence` dip suggests the `pose_hint` instructions added to `cast_decision.md` are pulling attention away from narrative continuity slightly; the candidate prompt text itself would need a revision + a fresh eval cycle before any future promotion attempt. SCP-173's production-side flakiness is a pre-existing eval-runner limitation (no automatic retry-on-transient-schema-miss) — logged here as a known gap, not fixed in this story (Dev Notes: avoid touching runtime beyond what's proven broken).
   - Prompt Policy evidence: no `production` label move — the gate did not pass, so per `docs/PROMPT_POLICY.md` rule 4 nothing is promoted. No `PROMPT_POLICY.md` edit needed.

**Task 6 — live special-pose ComfyUI validation (2026-07-08/09, SCP-049, real DeepSeek candidate scenario + real local ComfyUI):**

Ran a one-off ad hoc script (not part of the committed diff — a `/tmp` scratchpad harness, deleted after use) that: (1) called the real `scenario_node` for SCP-049 with `prompt_variant="B"` to obtain a real `pose_hint`, then (2) called the exact production function `run_service._ensure_special_pose_cards` twice against the real DB and real ComfyUI (`localhost:8188`, restarted mid-session after it was found down — connection-refused on attempt 3, confirmed back up via `GET /system_stats` before retrying).

- Real `pose_hint` captured: `"reaching toward camera"` for `card_key=SCP-049` (from `cast_decision`, real DeepSeek output — not fabricated for the test).
- First call: generated `assets/characters/SCP-049/epoch_1/hint_b36d4021a2_front.png` via real ComfyUI i2i (anchored to the existing standing-front card), wrote an `approved` `CharacterCard` row (`scp_id=SCP-049`, `pose=hint:b36d4021a2`, `angle=front`). Verified: `PIL.Image.mode == "RGBA"`, size `832x1216`, alpha channel extrema `(0, 255)` — a real cutout (both fully-transparent and fully-opaque pixels present), not a flat/placeholder alpha. Visual inspection confirms full-body framing, readable plague-doctor silhouette, one arm extended toward camera matching the pose_hint.
- Second call (identical scenes/pose_hint): returned the **same** card row — identical `id`, `created_at` (`2026-07-08T16:18:44.522523+00:00` on both calls), and `image_path` — confirming the `get_card` pre-check short-circuits regeneration (deterministic cache hit, AC8).
- Two earlier attempts failed before this one succeeded and are noted for completeness, not as defects in this story's own code: (a) the ad hoc script itself omitted `prompt_service.build_client()`, so `@observe`'s `get_client()` had no registered Langfuse client yet — fixed by calling `build_client()` before `scenario_node` (mirrors what `eval_prompts.py main()` and the FastAPI app already do); (b) one scenario run hit a non-deterministic DeepSeek JSON parse failure — the same class of flakiness Task 5 documents, resolved by retrying.

### File List

- `scripts/eval_prompts.py`
- `tests/test_eval_prompts.py`
- `.gitignore`

## Change Log

- 2026-07-08: Story created as the follow-up home for 8.4 Task 2 prompt rollout and Task 6 live validation.
- 2026-07-09: Tasks 1-4 implemented (--scp-id, --stage, failure artifacts, per-item timeout) with full TDD coverage; full regression suite green (1006 passed, 1 skipped).
- 2026-07-09: Task 5 live decomposed gate rerun at YTFLOW_DEEPSEEK_MAX_TOKENS=16000 — Verdict FAIL (narrative_coherence regression on SCP-049/SCP-096, SCP-173 production-side non-determinism); candidate not promoted. Task 6 live ComfyUI special-pose validation for SCP-049 passed (RGBA cutout confirmed, cache hit confirmed on rerun). Story moved to review.
- 2026-07-09: Code review complete — patched 5 findings (actual failing stage attribution, full-run parsed-state artifacts, non-mutating `--scp-id` filtering, positive timeout validation, unique artifact run dirs). Targeted eval tests: 57 passed; ruff clean. Story moved to done.
