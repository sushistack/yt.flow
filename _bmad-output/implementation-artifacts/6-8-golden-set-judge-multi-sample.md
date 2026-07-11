---
created: 2026-07-11
baseline_commit: 1847ab4d364e60fd6746926c3dea4f25cf1792ee
story_key: 6-8-golden-set-judge-multi-sample
story_id: "6.8"
epic: 6
previous_story: 6-6-tiered-prompt-evaluation-gates
depends_on:
  - 6-6-tiered-prompt-evaluation-gates       # owns the --profile promotion gate whose item failures this story reduces
related:
  - 6-3-prompt-cache-hit-optimization        # blocked promotion this story partially unblocks
  - 6-7-yaml-syntax-only-repair-path         # sibling finding from the same 2026-07-11 gate rerun
evidence: "2026-07-11 live rerun (run 1) of the 6-3/6-4 promotion gate: SCP-049's candidate run failed outright with 'unparseable judge response' — a raw judge JSON payload that failed json.loads (the printed error showed what looks like an unescaped literal control character inside a JSON string value, the judge-output analogue of Story 6.4's original scenario-output JSON-escaping problem). Traced statically (no further live calls) to eval_service.py: _judge_axis (L145-152) fires REPS_PER_AXIS=3 concurrent _post_chat calls per axis via asyncio.gather with no exception isolation; _parse_score (L128-140) raises EvalJudgeError immediately on any parse failure with no retry (_post_chat's own docstring, L102: 'Parse failures are not retried here'); a single bad judge response among 3 therefore aborts the entire axis (and, since _score_run awaits all three axes via its own gather at L157-159, the entire item). REPS_PER_AXIS=3 already averages judge noise per axis (Story 4.2/OQ-1) — the earlier hypothesis that judge scoring needed multi-sampling added was checked against this file and found already implemented; the real gap is the lack of bounded retry/graceful degradation when one of the three already-sampled calls fails to parse."
---

# Story 6.8: Judge-Scoring Bounded Retry — One Malformed Response Shouldn't Kill an Item

Status: done

## Story

As Jay,
I want a single malformed judge response (one of the three already-sampled calls per axis) to get a bounded retry — and gracefully degrade to the remaining samples' average if the retry also fails — instead of aborting the entire golden-set item's evaluation,
so that a transient judge JSON-parse failure stops masquerading as a promotion-gate item failure.

## Context

Re-running the 6-3/6-4 promotion gate live (2026-07-11, after Story 6.6's timeout fix) hit two distinct failures. This story addresses the first: SCP-049's `candidate` run failed outright with `unparseable judge response`, not a content regression.

The initial hypothesis was that the golden-set gate's judge only scores once per axis and needed multi-sampling to smooth out noise. Reading `src/yt_flow/services/eval_service.py` before writing this story disproved that: judge scoring already fires `REPS_PER_AXIS = 3` (`eval_service.py:37`) concurrent calls per axis via `_judge_axis` (`eval_service.py:145-152`) and averages them with `statistics.fmean` in `_score_run` (`eval_service.py:156-165`) — this has been true since Story 4.2's OQ-1 design. Adding a second layer of sampling on top of an already-averaged score would be redundant.

The actual gap: `_judge_axis`'s three `_post_chat` calls are wrapped in a bare `asyncio.gather` with no per-call exception isolation, and `_parse_score` (`eval_service.py:128-140`) raises `EvalJudgeError` immediately on any parse failure — `_post_chat`'s own docstring (`eval_service.py:102`) states this is deliberate: "Parse failures are not retried here — the caller raises `EvalJudgeError` immediately so a persistently malformed judge can't burn the time budget." That reasoning holds for a judge that's *persistently* malformed, but not for one bad response out of three independent samples — today, if even one of the three already-redundant calls returns malformed JSON (e.g. an unescaped control character inside a string value, the judge-output analogue of the scenario chain's own pre-6.4 JSON-escaping problem), `asyncio.gather` propagates that single failure and kills the entire axis, and because `_score_run` (`eval_service.py:157-159`) itself gathers across all three axes, it kills the entire item's evaluation. The redundancy `REPS_PER_AXIS=3` was built to provide (Story 4.2's design intent) is being thrown away by the failure path.

Separately, run 2 of the same gate rerun (after this specific SCP-049 crash didn't recur) showed a genuine `narrative_coherence` -0.33 delta on an otherwise-passing item. That is **not** addressed by this story: it's a difference between two already-3x-averaged scores, so it more likely reflects run-to-run variance in the underlying scenario *generation* (DeepSeek's narration text differs slightly each live run) than judge-scoring noise. Eliminating that would require repeating the full scenario generation multiple times per golden item — a cost increase that runs directly against Story 6.6's reason for existing (reducing how often the expensive full-scenario comparison runs). Explicitly out of scope here; see Story 6.6 for the cost/thoroughness tradeoff this project has already made.

## Acceptance Criteria

1. **Given** `_judge_axis`'s three `_post_chat` calls for one axis, **Then** any individual call that raises `EvalJudgeError` (parse failure, not a timeout — timeouts already retry once inside `_post_chat`) gets exactly one bounded retry (a fresh `_post_chat` call), isolated from the other two calls in flight (a failure in one must not cancel or fail the others).
2. **Given** a call whose retry also raises `EvalJudgeError`, **Then** that one sample is dropped and the axis score is computed from the remaining successful samples' average (e.g. 2 of 3) rather than raising — unless fewer than 2 of the 3 samples succeeded, in which case the axis (and therefore the item) fails exactly as it does today (this story does not make evaluation infinitely lenient — losing a majority of samples is still a real failure signal).
3. **Given** `AxisScores`/whatever result shape `_score_run` returns, **Then** it optionally records how many of the 3 samples succeeded per axis (for artifact/debug visibility) — not a hard requirement, but do not lose this information if it's cheap to keep.
4. **Given** `--profile smoke` and `--profile promotion`, **Then** both benefit automatically — this is a fix inside the shared judge-scoring path (`eval_service.py`), not something gated by CLI profile.
5. **Given** tests, **Then** they cover: one of three calls failing then succeeding on retry (full 3-sample average preserved); one of three calls failing on both the original and retry (2-of-3 average used, degradation is visible/logged); two or more of three calls failing (existing item-failure behavior preserved, unchanged from today).
6. **Given** the run-to-run generation-variance issue described in Context, **Then** it is explicitly documented as out of scope in this story's Dev Notes — not silently ignored, not accidentally implied to be fixed by this story.

## Tasks / Subtasks

- [x] Task 1: Add a bounded-retry wrapper around each `_post_chat` call inside `_judge_axis` — on `EvalJudgeError`, retry that one call exactly once; do not let one call's failure cancel the other two in-flight `asyncio.gather` members. (AC:1)
- [x] Task 2: Change `_judge_axis`'s aggregation so 1 permanently-failed-of-3 sample degrades to a 2-sample average instead of raising; 2+ permanently-failed samples still raise/fail as today. (AC:2)
- [x] Task 3: Thread through (or log) the per-axis successful-sample count for debug visibility, matching the project's existing artifact-persistence conventions (`scripts/eval_prompts.py`'s per-item artifacts). (AC:3)
- [x] Task 4: Unit tests for the three degradation scenarios in AC5, using the existing judge-call test-double seams. (AC:5)
- [x] Task 5: Update this story's Dev Notes / `6-3-6-4-review-metrics-report.md` with the out-of-scope generation-variance note (AC:6) — do not attempt to fix it here.

## Dev Notes

### Source Context

- Epic 6 goal: prompt lifecycle versioned + labeled + eval-gated using Langfuse's native features only. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 6: Prompt Ops — 프롬프트 버저닝·평가 정책`]
- This story's own epics.md entry has the same root-cause breakdown, including why the original multi-sample premise was wrong. [Source: `_bmad-output/planning-artifacts/epics.md#Story 6.8: judge 채점 bounded retry`]
- The incident that surfaced this: [Source: `_bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md#2026-07-11 full 3-item promotion re-attempt (post-6.6)`]
- Story 4.2's original OQ-1 judge design (`REPS_PER_AXIS=3`, quality floor, this story does not change either): referenced in `eval_service.py`'s own module docstring and dataclass comments.

### Existing Code To Reuse / Modify

- `_judge_axis` (`eval_service.py:145-152`) is the single call site this story changes — do not duplicate judge-calling logic elsewhere.
- `_post_chat` (`eval_service.py:100-124`) already has its own timeout-retry-once pattern (`for attempt in range(2)`) — this story's parse-failure retry is a *different* bounded-retry layer (parse failures, not timeouts) and should follow the same "exactly one extra attempt, then accept the outcome" philosophy already established there and in `scenario_chain.py`'s `_call_stage_with_retry` (Story 6.4).
- `_parse_score` (`eval_service.py:128-140`) and `EvalJudgeError` (`eval_service.py:44`) stay unchanged — this story retries around them, not inside them.
- `_score_run` (`eval_service.py:156-165`) is where the aggregate `AxisScores` is built — Task 2/3's degraded-average logic lives here or in `_judge_axis`, whichever keeps the existing `statistics.fmean` call simple (prefer computing the average over however many samples actually succeeded, rather than padding with a sentinel).

### Why Not Just Increase REPS_PER_AXIS

Raising `REPS_PER_AXIS` from 3 to, say, 5 was considered as an alternative and rejected as the primary fix here: it increases cost (more judge calls per axis, on every eval run — smoke and promotion both) without addressing the actual defect, which is that a **single already-sampled call's failure currently discards the other two successful samples too**. Fixing the aggregation to tolerate a dropped sample is a cheaper, more targeted fix than buying more redundancy to statistically outrun a bug in how existing redundancy is thrown away. If parse failures remain frequent even after this fix, revisit `REPS_PER_AXIS` then — separately, with its own cost/benefit case.

### Out Of Scope

- Multi-sampling judge scoring beyond what `REPS_PER_AXIS=3` already provides — already implemented (Story 4.2), not this story's concern.
- The `narrative_coherence`-type single-axis regression seen on an otherwise-successful item (run 2 of the 2026-07-11 rerun) — likely full-generation run-to-run variance, not a judge-scoring defect; fixing it would mean repeating full scenario generation per golden item, which conflicts with Story 6.6's cost-reduction goal. Not attempted here. Documented in `6-3-6-4-review-metrics-report.md`'s new "2026-07-11 promotion gate rerun (post-6.6, further re-attempt)" section alongside this story's fix (AC6).
- Any change to `docs/PROMPT_POLICY.md`'s zero-tolerance pass criteria (any negative axis = FAIL) — that policy stays exactly as Story 6.6 deliberately set it; this story only makes the *measurement* underneath it more robust to a single transient parse failure, not more lenient in what it accepts as a real regression.
- Story 6.7's YAML syntax-repair path — a different, unrelated failure class (scenario-stage output, not judge output).

### Project Structure Notes

- Modify: `src/yt_flow/services/eval_service.py` (`_judge_axis`, `_score_run`, possibly a small new bounded-retry helper local to this module — do not import `scenario_chain.py`'s helper across module boundaries for an unrelated domain).
- No new Settings fields expected (retry count is a fixed bound of 1, matching every other bounded-retry precedent in this project — not a new configurable knob unless review finds a concrete reason to make it one).

### References

- [Source: src/yt_flow/services/eval_service.py#L37-L165] — `REPS_PER_AXIS`, `EvalJudgeError`, `_post_chat`, `_parse_score`, `_judge_axis`, `_score_run`
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L265-L299] — `_call_stage_with_retry`, the project's established bounded-retry-once pattern this story's judge-side retry should mirror in spirit (not in code — different module, different failure shape)
- [Source: _bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md#2026-07-11 full 3-item promotion re-attempt (post-6.6)] — the incident that surfaced this

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Initial implementation used unit-level fake `_post_chat` calls only.
- Review regression: `uv run pytest -q` — 1243 passed, 1 skipped, 1 warning; focused review suite — 257 passed; Ruff clean.
- Live smoke and promotion exercised the shared judge path without another malformed-response item failure. Promotion still failed for generation truncation and real axis regressions; see the 6.7 record and metrics report.

### Completion Notes List

- Added `_judge_sample()`, a small helper local to `eval_service.py` that wraps one `_post_chat` + `_parse_score` pair with exactly one retry on `EvalJudgeError` (not on timeout — `_post_chat` already retries those). Returns `None` when both attempts fail to parse, instead of raising, so the failure never escapes into `_judge_axis`'s `asyncio.gather` and can't cancel/fail the other two in-flight samples (AC1).
- `_judge_axis` now gathers `_judge_sample` calls (never raises per-sample), filters out `None`s, and only raises `EvalJudgeError` when fewer than 2 of `REPS_PER_AXIS` samples parsed — otherwise it returns however many succeeded (2 or 3), and `_score_run`'s existing `statistics.fmean` call already averages over whatever length list it receives, so no changes were needed to `_score_run` itself (AC2).
- Chose logging (`logger.warning`, degraded-sample-count message) over adding a new field to `AxisScores`/threading a count through `store_evaluation_results`/Langfuse persistence — AC3 explicitly marks this "not a hard requirement," and the project has no existing per-axis sample-count consumer to wire it into; logging is the cheaper option that doesn't lose the information (AC3).
- AC4 required no code change: the fix lives entirely inside the shared `_judge_axis`/`_judge_sample` path in `eval_service.py`, which both `--profile smoke` and `--profile promotion` already call through `scripts/eval_prompts.py`'s `_score_evaluator`.
- Added deterministic task-scoped concurrent tests covering AC5's three scenarios, direct-call `EvalJudgeError` retry, non-finite score handling, and end-to-end degraded averaging.
- Updated `6-3-6-4-review-metrics-report.md` with a new dated section documenting the SCP-049 `unparseable judge response` incident that motivated this story, the root cause, and the fix — and explicitly restated that the separate `narrative_coherence` generation-variance finding from an earlier rerun is out of scope here (AC6).
- Full regression suite (`pytest -q`, whole repo) and `ruff check` both pass; see File List for everything touched.

### File List

- `src/yt_flow/services/eval_service.py` — added `_judge_sample()`; rewrote `_judge_axis()` for per-sample bounded retry, isolated-failure aggregation, and degraded-sample-count logging.
- `tests/services/test_eval_service.py` — added `_RawQueue` fake and 3 tests for the AC5 degradation scenarios.
- `_bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md` — added the incident write-up + explicit out-of-scope note (AC6).
- `_bmad-output/implementation-artifacts/6-8-golden-set-judge-multi-sample.md` — this story file (tasks, Dev Notes cross-reference, Dev Agent Record, Change Log, Status).

## Change Log

### Review Findings

- [x] [Review][Patch] Convert non-finite judge scores into retryable `EvalJudgeError` results [`src/yt_flow/services/eval_service.py`] — fixed by handling `OverflowError` in `_parse_score`.
- [x] [Review][Patch] Isolate `EvalJudgeError` raised directly by an individual judge call [`src/yt_flow/services/eval_service.py`] — fixed by moving `_post_chat` inside the bounded retry guard.
- [x] [Review][Patch] Exercise actual concurrent sample isolation and end-to-end degraded averaging [`tests/services/test_eval_service.py`] — fixed with task-scoped response scripts and `_score_run` coverage.

- 2026-07-11: Story created from a live finding during the 6-3/6-4 promotion gate re-attempt (SCP-049 judge-response parse crash). Initial "add judge multi-sampling" premise was checked against `eval_service.py` and found already implemented (`REPS_PER_AXIS=3`); rescoped to bounded retry + graceful degradation on a single failed sample. Status: backlog.
- 2026-07-11: Implemented bounded retry-once + isolated-failure degradation in `_judge_axis` (`eval_service.py`); added `_judge_sample()` helper. 3 new unit tests for the AC5 degradation scenarios. Updated `6-3-6-4-review-metrics-report.md` with the incident + out-of-scope generation-variance note (AC6). Full suite (1238 passed, 1 skipped) + ruff clean. Status: review.
- 2026-07-11: Code review completed; 3 patches applied, concurrent isolation strengthened, full regression green, live shared-path gate exercised. Status: done.
