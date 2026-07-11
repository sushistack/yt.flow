---
created: 2026-07-11
baseline_commit: 68584373b91c5583b7d6e9fa54eeb6be3ff5edba
story_key: 6-9-scene-repair-truncation-axis-regression
story_id: "6.9"
epic: 6
previous_story: 6-8-golden-set-judge-multi-sample
depends_on:
  - 6-3-prompt-cache-hit-optimization      # this story's fixes unblock 6-3's promotion, not the reverse
  - 6-4-scenario-yaml-output-bounded-retry # same
related:
  - 6-5-scenario-scoped-repair-retry       # owns writing_scene_repair_step / _repair_and_review, the code this story's AC1/AC2 investigate
  - 6-7-yaml-syntax-only-repair-path       # sibling finding from the same 2026-07-11 gate rerun, different failure class (YAML syntax, not truncation)
  - 6-8-golden-set-judge-multi-sample      # precedent for "is this a real regression or run-to-run generation variance" triage (AC3 reuses that reasoning)
evidence: "2026-07-11 Story 6.7/6.8 review gate (see 6-3-6-4-review-metrics-report.md, '2026-07-11 Story 6.7/6.8 review gate' section): smoke passed at YTFLOW_DEEPSEEK_MAX_TOKENS=16000 (SCP-049 total 11.67), but the 3-item promotion gate FAILed with two findings unrelated to 6.7/6.8's own fixes: (1) SCP-049's candidate failed because scenario/writing_scene_repair truncated (finish_reason=length) even at the promotion-mandated 16000-token floor (scripts/eval_prompts.py:66, _MIN_MAX_TOKENS_FOR_PROMOTION); (2) SCP-173 regressed atmosphere -0.33 and narrative_coherence -0.33 vs production, and SCP-096 regressed article_fidelity -0.33 (despite +1.67 atmosphere) vs production. Static code reading (scenario.py:110-141 _retry_scope, scenario.py:252-266 _repair_and_review) found writing_scene_repair's per-call scene batch (the union of review.issues + critic.scene_notes valid scene_nums) has no upper bound — a plausible but unconfirmed truncation cause. The axis regressions have not been triaged against 6.8's precedent question (real content regression vs. run-to-run generation variance)."
---

# Story 6.9: writing_scene_repair Truncation Root Cause + SCP-173/096 Axis Regression Triage

Status: in-progress  # AC1/AC2/AC5 code-complete + verified; AC3/AC4 live gate deferred to Jay (2026-07-11)

## Story

As Jay,
I want the writing_scene_repair truncation and the SCP-173/096 judge-axis regressions investigated to a confirmed root cause and fixed (or explicitly triaged as out-of-scope generation variance, following the Story 6.8 precedent),
so that the 6-3/6-4 candidate prompts can pass the promotion gate and move to production instead of failing for reasons unrelated to their own content.

## Context

This is the third consecutive promotion-gate FAIL for the 6-3/6-4 candidate prompt set (`6-3-6-4-review-metrics-report.md` tracks all three: the original timeout, the 6.7/6.8-fixed YAML-syntax/judge-parse crashes, and now this). Each prior FAIL was root-caused and fixed by a dedicated story (6.6 for the timeout, 6.7 for YAML syntax errors, 6.8 for judge-response parse crashes). This story continues that pattern for the two findings from the most recent rerun, which are unrelated to what 6.7/6.8 fixed:

**Finding 1 — writing_scene_repair truncation.** `scripts/eval_prompts.py` enforces `YTFLOW_DEEPSEEK_MAX_TOKENS >= 16000` for `--profile promotion` specifically because the 8192 default truncates `visual_breakdown` (`_MIN_MAX_TOKENS_FOR_PROMOTION`, `eval_prompts.py:66`). The 2026-07-11 gate ran at 16000 and `visual_breakdown` was fine, but `scenario/writing_scene_repair` (Story 6.5's scene-scoped repair prompt) truncated anyway. Reading the call path: `_repair_and_review` (`scenario.py:252-266`) builds `originals = [writing["scenes"][idx] for idx in indexes]` and passes exactly that subset to `writing_scene_repair_step` — this is genuinely scoped (not the full scenario), matching Story 6.5's intent. `indexes` itself comes from `_retry_scope` (`scenario.py:110-141`), which unions every valid `scene_num` from both `review["issues"]` and `critic["scene_notes"]` with **no cap on how many scenes that union can contain**. If review and critic jointly flag most of an 8-12 scene scenario, one repair call must regenerate that many full narrations in a single YAML response — a plausible reason 16000 tokens isn't enough even though the per-scene prompt (`prompts/scenario/writing_scene_repair.md`) is short. This has not been confirmed live — the actual `len(indexes)` at the moment of truncation is unknown.

**Finding 2 — SCP-173/096 axis regressions.** Story 6.3's AC1 (prompt block reordering) and Story 6.4's AC2 (JSON→YAML serialization) both explicitly claimed "instruction content unchanged, only reordering/serialization changed." The gate's measured deltas (SCP-173 atmosphere -0.33, narrative_coherence -0.33; SCP-096 article_fidelity -0.33) contradict the assumption that format-only changes can't move judge scores — either the format change itself has a real (if unintended) effect on the model's narrative style, or these deltas are the same kind of run-to-run generation variance Story 6.8 already found and explicitly excluded from its scope (SCP-049's `narrative_coherence` -0.33 in the prior rerun, `6-3-6-4-review-metrics-report.md`'s "2026-07-11 promotion gate rerun" section). Which of the two it is has not been tested — it requires re-running the same candidate against the same golden item multiple times to see if the axis score is stable or noisy.

## Acceptance Criteria

1. **Given** a live repro of the SCP-049 promotion-gate run, **Then** capture `len(indexes)` (the number of scenes sent to `writing_scene_repair_step` in one call) and the actual completion token count/`finish_reason` at the point of truncation, to confirm or rule out "unbounded repair batch size" as the cause.
2. **Given** AC1 confirms batch size is the cause, **Then** before picking a fix, survey how established LLM-pipeline practice handles "structured multi-item output exceeds one completion's token budget" (candidates include, but aren't limited to: map-reduce-style per-item chunked calls, incremental/continuation prompting that resumes generation from a truncation point, or a hard cap that routes overflow to this project's existing `final_retry_scope="full-fallback"` full-rewrite path). Record at least 2 candidate approaches with their tradeoffs (call-count cost, complexity, consistency with this project's existing bounded-retry-once philosophy from 6.4/6.8/6.7) in Dev Notes before implementing the chosen one. **Given** AC1 rules out batch size (e.g. truncation reproduces even with 1-2 flagged scenes), **Then** investigate and fix the actual cause instead (e.g. the model echoing `original_scenes` verbatim into its own output) rather than forcing a batch-size fix that doesn't match the evidence.
3. **Given** the SCP-173/096 axis deltas, **Then** before concluding "regression" or "variance," survey how established LLM-eval/prompt-ops practice distinguishes the two from a single before/after delta (e.g. multiple-trial repeated comparison with a minimum repeat count, confidence-interval or paired-comparison statistics, rather than eyeballing one candidate-vs-production run) and apply that method — re-run the same candidate against the same golden item(s) enough times to judge stability rather than assuming a single rerun settles it. **Given** it's a real regression, **Then** identify the specific prompt change responsible (which file, which instruction) and apply a targeted fix — consider more than one remediation option (e.g. reverting the specific reordered/converted block vs. adjusting instruction wording vs. adding a stylistic guardrail) and record why the chosen one was picked over the alternatives. **Given** it's variance, **Then** follow Story 6.8's precedent: document it as out of scope in this story's Dev Notes and in `6-3-6-4-review-metrics-report.md`, do not chase a fix.
4. **Given** AC2/AC3's fixes (or confirmed out-of-scope determinations) are in place, **Then** re-run `scripts/eval_prompts.py --profile promotion` for all 3 golden items. **Given** it PASSes, **Then** promote the 6-3/6-4 candidate to `production` per `docs/PROMPT_POLICY.md`. **Given** it still FAILs, **Then** record the new failure detail in `6-3-6-4-review-metrics-report.md` — do not force promotion.
5. **Given** AC2 introduces a batch cap/chunking change, **Then** add a regression test covering: scenes-under-cap (single call, unchanged behavior), scenes-over-cap (chunked calls or fallback delegation, whichever AC2 chose).

## Tasks / Subtasks

- [x] Task 1: Live-reproduce the SCP-049 promotion-gate truncation; log `len(indexes)` and completion tokens/`finish_reason` at the failure point. (AC:1) — root-caused from the retained 2026-07-11 gate artifact (no new live run needed); batch size **ruled out**, see Dev Notes.
- [x] Task 2: Research and record ≥2 candidate fix approaches for over-budget structured multi-item output (chunked/map-reduce calls, continuation prompting, cap+fallback), compare tradeoffs against this project's existing bounded-retry precedents, then implement the selected approach in `_repair_and_review`/`_retry_scope` (or the alternate cause found if AC1 rules out batch size). (AC:2) — AC1 ruled out batch size, so implemented the evidence-matched alternate: route repair truncation to the existing full-rewrite fallback. 4 approaches recorded in Dev Notes.
- [ ] Task 3: Research how multi-trial statistical comparison is typically done for LLM-judge eval noise (minimum repeat count / confidence interval / paired comparison), then re-run the same candidate against SCP-173 and SCP-096 enough times to apply that method and determine whether the axis deltas are stable (real regression) or noisy (variance). (AC:3) — method researched + recorded (Dev Notes); **live multi-trial execution pending Jay's go-ahead** (real DeepSeek cost, ~20min/run).
- [ ] Task 4: If real regression, evaluate more than one remediation option for the responsible prompt instruction and record why the chosen fix was picked; if variance, document as out of scope (mirroring 6.8's Dev Notes pattern) in this story and in `6-3-6-4-review-metrics-report.md`. (AC:3) — gated on Task 3's live determination.
- [ ] Task 5: Re-run the full 3-item `--profile promotion` gate; promote to `production` on PASS per `docs/PROMPT_POLICY.md`, or record the new FAIL detail. (AC:4) — **live gate pending Jay's go-ahead**; production-label move is an outward, policy-governed action.
- [x] Task 6: Add regression test(s) for whatever AC2 chunking/cap logic is implemented. (AC:5) — `test_scene_repair_truncation_falls_back_to_full_rewrite` + `test_non_truncation_repair_error_still_surfaces_as_error` (scenario) + `test_call_stage_raises_truncation_error_with_evidence` (chain).

### Review Findings

_Code review of commit 243d1d4 (2026-07-11): 3 layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor). 1 decision-needed, 2 patch, 1 defer, 3 dismissed._

- [x] [Review][Fixed] `except TruncationError` wrapped all of `_repair_and_review`, not just the scoped-repair call — a `finish_reason=length` in the repair pass's `cast_decision`/`visual_breakdown`/`review`/`critic` sub-stages (all route through `_call_stage`, which raises `TruncationError`) was caught and mislabeled `"scene-repair-truncated"`, violating the "recovery is narrow: any other repair error still fails the run" contract and producing mixed `pass_index=2` trace. **Fix (Jay: option 1 — narrow the recovery):** `_call_stage` now stamps `TruncationError.prompt_name`; `scenario_node` re-raises unless `exc.prompt_name == "scenario/writing_scene_repair"`, so only the scoped-repair write recovers via full rewrite — every other stage's truncation fails the run as the contract states. New test `test_downstream_stage_truncation_in_repair_pass_fails_run`. [scenario.py:375-382, scenario_chain.py:_call_stage] — CONFIRMED by all 3 layers.
- [x] [Review][Fixed] `final_indexes` not cleared on the truncation-fallback branch — retained the flagged subset while `_full_rewrite` regenerated every scene, so the `tts_normalize` trace misreported the fallback as scoped. **Fix:** set `final_indexes = []` in the fallback branch (mirrors `full-fallback`). Asserted by the fallback test (`tts_normalize` stage `target_scene_count == 0`). [scenario.py:387-392] — CONFIRMED by all 3 layers.
- [x] [Review][Fixed] Completion Notes overclaimed AC5 test coverage — corrected the wording to stop claiming a new "under-cap unchanged" test (that happy path stays covered by the pre-existing `test_eight_scenes_one_flag_adds_exactly_five_calls_and_preserves_unflagged`). [6-9 story Completion Notes] — Auditor.
- [x] [Review][Defer] New fallback `rejected` dict shape `{"reason","completion_tokens","flagged_scene_count"}` diverges from every other producer's `{"source","scene_num","reason"}` / `{"reason","rejected"}` — lands verbatim in trace `rejected_scene_identifiers`. No `src/` consumer indexes those keys today (grep-verified), so latent-only. [scenario.py:390-392] — deferred, no consumer.



- Epic 6 goal: prompt lifecycle versioned + labeled + eval-gated using Langfuse's native features only. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 6: Prompt Ops — 프롬프트 버저닝·평가 정책`]
- This story's own epics.md entry has the same root-cause hypotheses. [Source: `_bmad-output/planning-artifacts/epics.md#Story 6.9: writing_scene_repair truncation 근본원인 + SCP-173/096 축 회귀 조사·수정`]
- The incident that surfaced this: [Source: `_bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md#2026-07-11 Story 6.7/6.8 review gate`]
- Story 6.5 introduced the scene-scoped repair this story investigates. [Source: `_bmad-output/implementation-artifacts/6-5-scenario-scoped-repair-retry.md`]
- Story 6.8's precedent for triaging "real regression vs. generation variance" before attempting a fix — do not re-derive that reasoning from scratch, reuse it. [Source: `_bmad-output/implementation-artifacts/6-8-golden-set-judge-multi-sample.md#Why Not Just Increase REPS_PER_AXIS`, `#Out Of Scope`]

### Research Before Fixing (do not jump to the first idea)

- **Truncation fix (AC2/Task 2):** Do not default to "add a cap" without comparing it against alternatives. Known industry patterns for this exact shape of problem ("N structured items, one call's output budget isn't enough") include: map-reduce-style per-item or per-chunk calls (generate a subset, merge results — this project already has the scaffolding for scene-scoped calls via `writing_scene_repair_step`), continuation/resume prompting (re-prompt with "continue from where you stopped" using the partial output + `finish_reason=length` signal), and hard caps that route overflow to a cheaper/safer fallback (this project's own `full-fallback` path). Pick based on the actual `len(indexes)` distribution found in Task 1 — a cap only makes sense if large batches are rare; if they're common, chunking preserves scene-scoped repair's cost savings (Story 6.5's whole point) better than falling back to full rewrites.
- **Axis regression triage (AC3/Task 3):** Do not conclude "regression" or "variance" from one before/after comparison. Standard practice for noisy LLM-eval deltas is repeated-trial comparison — run the same candidate against the same golden item N times (N≥3, matching this project's own `REPS_PER_AXIS=3` judge-sampling precedent in `eval_service.py`) and look at whether the delta sign/magnitude is consistent across runs versus within the noise band the repeated runs themselves display. If time/cost-constrained, at minimum re-run once more before calling it either way — one before/after pair is not enough evidence per Story 6.8's own reasoning about SCP-049's earlier -0.33.
- Record which alternatives were considered and why the chosen one won in this section (or a dated addendum) once the investigation concludes — this is what lets a future story (or a future rerun of this same problem) avoid re-deriving the comparison from scratch, the same way this story reused Story 6.8's variance-triage precedent instead of re-inventing it.

### Existing Code To Reuse / Modify

- `_retry_scope` (`src/yt_flow/pipeline/nodes/scenario.py:110-141`) — computes `indexes`, the union of valid `scene_num`s from `review["issues"]` and `critic["scene_notes"]`. No batch cap today; this is the likely site for AC2's cap if Task 1 confirms batch size as the cause.
- `_repair_and_review` (`scenario.py:252-266`) — calls `writing_scene_repair_step` with `originals = [writing["scenes"][idx] for idx in indexes]`. If chunking is chosen over cap+fallback, this is where multiple sequential calls would be issued.
- `writing_scene_repair_step` (`src/yt_flow/pipeline/nodes/scenario_chain.py:470-520`) and its prompt `prompts/scenario/writing_scene_repair.md` — do not change the prompt itself unless Task 2 rules out batch size and finds a prompt-content cause instead.
- `final_retry_scope="full-fallback"` (`scenario.py:363`) — the existing fallback path for when `indexes` is empty; AC2's option (b) would extend this path's trigger condition to "too many scenes flagged," not just "zero valid scenes flagged."
- `scripts/eval_prompts.py` (`_MIN_MAX_TOKENS_FOR_PROMOTION`, `_RISKY_DEFAULT_MAX_TOKENS`, lines 62-66, 590-608) — the promotion-gate token floor this story's truncation finding was measured against; do not raise this floor further as a substitute for root-causing the actual truncation cause (that was already tried in the 6.6/6.7 attempts per the metrics report and didn't hold).

### Out Of Scope

- Re-litigating Story 6.8's judge bounded-retry fix or the SCP-049 `narrative_coherence` -0.33 variance finding it already excluded — that finding stays out of scope exactly as 6.8 documented it. This story's SCP-173/096 deltas are a separate, fresh observation from a later rerun and must be triaged independently (AC3), not assumed to be the same phenomenon without checking.
- Changing `docs/PROMPT_POLICY.md`'s zero-tolerance promotion criterion (any negative axis delta = FAIL) — that policy is a deliberate Story 6.6 decision, unchanged here.
- Raising `YTFLOW_DEEPSEEK_MAX_TOKENS`'s promotion floor beyond 16000 as a first resort — already attempted in prior gate reruns per `6-3-6-4-review-metrics-report.md` and did not resolve the writing_scene_repair truncation, so Task 1 must find the actual cause rather than repeating that attempt.

### Project Structure Notes

- Modify: `src/yt_flow/pipeline/nodes/scenario.py` (`_retry_scope`, `_repair_and_review`) if AC2's batch-size hypothesis is confirmed; otherwise `src/yt_flow/pipeline/nodes/scenario_chain.py`/`prompts/scenario/writing_scene_repair.md` if a different cause is found.
- Any prompt file changed under AC3 follows `docs/PROMPT_POLICY.md`: candidate label first, gate must pass before production promotion.
- No new Settings fields expected for the batch cap unless the investigation finds a concrete reason the cap needs to be externally configurable (default to a fixed constant, matching this project's other bounded-retry precedents, e.g. 6.4/6.8's "exactly one extra attempt" pattern).

### References

- [Source: src/yt_flow/pipeline/nodes/scenario.py#L110-L141] — `_retry_scope`
- [Source: src/yt_flow/pipeline/nodes/scenario.py#L252-L305] — `_repair_and_review`, `_write_and_review`
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L470-L520] — `writing_scene_repair_step`
- [Source: scripts/eval_prompts.py#L62-L66,L590-L608] — `_RISKY_DEFAULT_MAX_TOKENS`, `_MIN_MAX_TOKENS_FOR_PROMOTION`
- [Source: _bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md#2026-07-11 Story 6.7/6.8 review gate] — the incident that surfaced this
- [Source: _bmad-output/implementation-artifacts/6-8-golden-set-judge-multi-sample.md] — precedent for the real-regression-vs-variance triage this story's AC3 reuses

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m]

### Debug Log References

- AC1 evidence source: `tmp/eval-prompts/20260711-164208-1783755728393879121-candidate-production/candidate-SCP-049-full.json` (retained gate artifact from the 2026-07-11 6.7/6.8 review gate).
- 2026-07-11 confirming smoke (Jay-authorized, single item): `YTFLOW_DEEPSEEK_MAX_TOKENS=16000 uv run python scripts/eval_prompts.py --profile smoke --label candidate` → SCP-049 completed, total 14.00 (atmosphere 4.00, narrative_coherence 5.00, article_fidelity 5.00), 9 scenes, error=None. Artifact `tmp/eval-prompts/20260711-201258-1783768378891649012-candidate/`. Review+critic passed on pass 1, so the scoped-repair path did not fire (stochastic) — the truncation was not reproduced this run, but the smoke confirms (a) the fix does not regress the happy path and (b) independently reconfirms AC1: full 9-scene writing = **4,296** completion tokens ≪ 16k, so no repair subset can legitimately need 16k. The fallback recovery itself is covered by unit tests, not this live run.

### AC1 — Root cause: batch size RULED OUT, it's runaway generation

The story's own tracing already persists the AC1 evidence — `_trace_fields` records `target_scene_count` (= `len(indexes)`) and `_usage_totals` records `completion_tokens` per stage. No new live run was needed; the retained SCP-049 candidate failure artifact contains it:

| Stage (pass 1) | scenes | completion_tokens |
|---|---:|---:|
| writing (ALL 8 scenes) | 8 | **2,846** |
| visual_breakdown | 8 | 70,057 (summed across 8 concurrent calls) |
| review | 8 | 10,664 |
| critic_agent | 8 | 2,508 |

The error: `scenario/writing_scene_repair response truncated (finish_reason=length)`. The `writing_scene_repair` stage never recorded because the truncation raises before `stages.append`.

**Decisive fact:** the scenario has only **8 scenes total**, and generating *all 8* narrations from scratch (the `writing` stage) costs **2,846 completion tokens**. `len(indexes)` for the repair is bounded by the scene count (≤ 8), so the largest possible repair batch is the same 8 scenes = ~2,846 tokens — nowhere near the 16,000 truncation ceiling. **No repair batch size can legitimately need > 16k tokens.** The scoped-repair call is emitting ~5.6× more tokens than regenerating the entire scenario. That is degenerate/runaway generation (the scoped-repair prompt asks the model to echo `original_scenes` and return them "mostly unchanged," a shape DeepSeek is prone to looping on), **not** a batch-volume problem. This is AC1's second branch: *batch size ruled out → fix the actual cause, don't force a batch-size fix.*

New instrumentation (`TruncationError.completion_tokens` / `.raw`) means the next time any stage truncates, the exact runaway output preview + token count are logged — so the specific degeneration pattern is confirmable live without re-deriving this.

### AC2 — Fix approaches considered (batch size ruled out)

| # | Approach | Matches evidence? | Cost / complexity | Verdict |
|---|---|---|---|---|
| 1 | **Full-rewrite fallback on truncation (CHOSEN)** — catch `TruncationError` from scoped repair, delegate to the existing `_write_and_review` full-rewrite path | Yes — full writing is proven to complete at ~2.8k tokens | +1 full generation only on the rare degeneration; reuses existing `full-fallback` scaffolding; matches the project's bounded-retry-once philosophy (6.4/6.7/6.8) | **Selected** |
| 2 | Per-scene chunked/map-reduce repair | No — batch size isn't the cause; a single scene can still degenerate | +N calls for a problem that isn't volume | Rejected |
| 3 | Continuation prompting ("resume from finish_reason=length") | No — a runaway generation just keeps running away on continuation; partial YAML is malformed mid-structure | High complexity, doesn't fix root behavior | Rejected |
| 4 | Hard batch cap → fallback (story's option b) | No sane cap triggers (8 scenes = 2.8k tokens); truncation slips below any cap | — | Rejected as a *count* cap; the chosen fix is effectively the *token*-cap form of this idea (finish_reason=length → fallback) |

Chosen #1 is the laziest correct fix: it reuses the proven full-rewrite path, preserves scene-scoped repair's cost savings for the common (non-degenerate) case, and is narrowly scoped — only `TruncationError` from the repair path recovers; every other repair failure still propagates as a run error (tested).

### AC3 — Variance-vs-regression triage method (execution pending)

Per the story's Dev Notes and Story 6.8's precedent: a single before/after delta cannot distinguish a real regression from run-to-run generation variance. Standard practice = repeated-trial comparison — re-run the same candidate against the same golden item **N ≥ 3** (matching this project's `REPS_PER_AXIS=3` judge-sampling precedent) and check whether the axis delta's sign/magnitude is stable across independent full-generation runs versus inside the noise band those repeats display. The SCP-173 (atmosphere −0.33, narrative_coherence −0.33) and SCP-096 (article_fidelity −0.33) deltas from the 2026-07-11 gate are each a single pair, which per this method is insufficient evidence either way. **This requires live full-scenario generation runs** and has not been executed — see the live-run decision surfaced to Jay.

### Completion Notes List

- ✅ AC1: Batch-size hypothesis **ruled out** from retained gate evidence (8-scene scenario, full writing = 2,846 tokens, repair truncated at 16k = runaway generation). Added `TruncationError` carrying `completion_tokens`/`raw` so future truncations self-document the degeneration.
- ✅ AC2: Implemented the evidence-matched fix — `scenario_node` catches `TruncationError` from `_repair_and_review` and routes to the proven full-rewrite path (new `retry_scope="scene-repair-truncated-fallback"`), instead of a batch cap that the evidence doesn't support. Recovery is narrow: other repair errors still fail the run.
- ✅ AC5: regression tests — truncation→full-rewrite fallback, non-truncation repair error still propagates, chain-level `TruncationError` evidence, and (added in code review) downstream-stage truncation in the repair pass fails the run (narrow-recovery guard). The scoped-repair happy path ("under-cap, single call, unchanged") stays covered by the pre-existing `test_eight_scenes_one_flag_adds_exactly_five_calls_and_preserves_unflagged` — no new test was added for it, and this story adds none claiming to.
- ⏳ AC3/AC4: method researched + recorded; live multi-trial and the 3-item promotion gate + production-label move are pending Jay's cost/authorization decision (every prior gate run has been Jay's explicit call — `6-3-6-4-review-metrics-report.md`).
- Full suite: **1246 passed, 1 skipped**; ruff clean.

### File List

- `src/yt_flow/pipeline/nodes/scenario_chain.py` (modified — `TruncationError`, `_call_stage` raises it with evidence)
- `src/yt_flow/pipeline/nodes/scenario.py` (modified — import `TruncationError`, `_full_rewrite` helper, truncation→full-rewrite fallback in `scenario_node`)
- `tests/pipeline/nodes/test_scenario.py` (modified — 2 fallback tests)
- `tests/pipeline/nodes/test_scenario_chain.py` (modified — 1 TruncationError evidence test)
- `_bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md` (modified — Story 6.9 addendum)

## Change Log

- 2026-07-11: Story created from the 2026-07-11 Story 6.7/6.8 review gate's promotion FAIL (writing_scene_repair truncation at 16k tokens + SCP-173/096 axis regressions), continuing the 6.6→6.7→6.8 root-cause-per-story pattern for 6-3/6-4's promotion blockers. Status: backlog.
- 2026-07-11: AC1 root-caused from retained gate artifact — batch size ruled out (8-scene scenario, full writing 2,846 tokens vs repair truncating at 16k = runaway generation). AC2 implemented evidence-matched fix (repair `TruncationError` → full-rewrite fallback; not a batch cap) with `TruncationError` evidence instrumentation. AC5 regression tests added (1246 passed/1 skipped, ruff clean). AC3/AC4 (live multi-trial + promotion gate + production promotion) pending Jay's live-run go-ahead. Status: in-progress.
- 2026-07-11: Code + docs committed to master as `243d1d4` (`feat(scenario): recover writing_scene_repair truncation via full-rewrite fallback`). Ready for code review; AC3/AC4 to be closed in a Jay-authorized live gate session (run `uv run python scripts/eval_prompts.py --profile promotion` with `YTFLOW_DEEPSEEK_MAX_TOKENS>=16000`).
- 2026-07-11: Code review (3-layer: Blind Hunter / Edge Case Hunter / Acceptance Auditor). 1 decision-needed + 2 patch fixed, 1 deferred, 3 dismissed. **High (Jay chose option 1 — narrow the recovery):** `except TruncationError` had wrapped the whole repair pass, so a truncation in its `cast/visual/review/critic` sub-stages fell back instead of failing the run — added structured `TruncationError.prompt_name` and made `scenario_node` recover *only* for `scenario/writing_scene_repair`, re-raising all other stages. **Medium:** clear `final_indexes` on the truncation-fallback branch so the `tts_normalize` trace stops advertising the pre-fallback scoped subset. **Low:** corrected the AC5 Completion Notes overclaim. Deferred: fallback `rejected` dict-shape divergence (no consumer). +1 regression test (`test_downstream_stage_truncation_in_repair_pass_fails_run`); 1247 passed/1 skipped, ruff clean. Status stays in-progress (AC3/AC4 live gate still pending Jay).
