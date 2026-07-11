# Stories 6.3–6.4 Review and Runtime Evidence Report

Date: 2026-07-11
Scope: prompt prefix caching, token/cache observability, YAML parsing, and bounded retry

## Executive summary

- Review result: approved after fixes to evaluation trace isolation, YAML boundary validation, retry feedback sanitization, token-count validation, and review-prompt prefix ordering.
- Cache evidence (SCP-096, one production run vs one candidate run): overall prompt cache-hit rate improved from **5.0%** (`11,008 / 218,647`) to **26.4%** (`32,512 / 123,067`).
- Primary repeated stage: `visual_breakdown` improved from **4.3%** to **42.9%** cache hits.
- Post-fix live reliability evidence already available: five candidate end-to-end executions completed without an unhandled YAML/schema failure (**0 / 5 observed run failures, 0%**).
- Exact YAML parse-error and retry-fire rates are **not measurable from the historical runs** because retry attempts were not separately tagged. Reporting a parse-error percentage from those runs would be fabricated.

## Cache evidence

| Metric | Production | Candidate | Change |
|---|---:|---:|---:|
| Overall cache-hit tokens | 11,008 | 32,512 | +21,504 |
| Overall prompt tokens | 218,647 | 123,067 | -95,580 |
| Overall cache-hit rate | 5.0% | 26.4% | +21.4 pp |
| `visual_breakdown` hit rate | 4.3% | 42.9% | +38.6 pp |
| `structure` hit rate | 0.0% | 52.9% | +52.9 pp |

Interpretation limits:

- The production run fired the scenario-level rewrite pass while candidate did not, so total-token counts are not an apples-to-apples cost comparison.
- Per-stage hit rate is the more reliable signal. The intended repeated stage (`visual_breakdown`) shows the strongest improvement.
- This is one live A/B pair, useful evidence rather than a statistically stable estimate.

## YAML parsing and retry evidence

Historical pre-fix investigation confirmed three failure classes: truncation, JSON syntax failure with `finish_reason=stop`, and valid-serialization/wrong-shape output. No denominator was persisted, so a pre-fix error rate cannot be computed.

After YAML conversion and the fence/newline fixes:

| Evidence | Result |
|---|---:|
| Candidate end-to-end runs | 5 |
| Unhandled YAML/schema failures | 0 |
| Observed run-level failure rate | 0% (0/5) |
| Exact first-attempt parse-error rate | Not observable |
| Exact bounded-retry activation rate | Not observable |

The code now guarantees at most two calls per stage for parse/schema failures: one initial attempt and one corrective retry. A second failure propagates. Review hardening additionally ensures non-mapping scenes/shots, non-text narration, invalid sentence coverage, and non-boolean `overall_pass` enter this bounded retry path instead of escaping as unrelated runtime exceptions.

## Review fixes applied

1. Replaced concurrent mutation of global `_record_trace` in `eval_prompts.py` with an explicit per-run `trace_sink`.
2. Rejected boolean and negative token counts instead of corrupting usage totals.
3. Added YAML item/type/coverage validation for writing, visual breakdown, review, and TTS normalization.
4. Sanitized and capped validation feedback before reinserting it into the corrective prompt.
5. Moved generated review inputs after fixed review instructions/schema to preserve more of the retry prefix.

## Validation and release status

- Local focused verification: **269 passed**; Ruff clean.
- Initial review made no new LLM calls. A later user-approved single-item gate used SCP-096 only.
- Existing live evidence has SCP-049 and SCP-096 passing isolated candidate checks. SCP-173 remained judge-noisy despite a positive latest total delta; the combined three-item gate was not rerun.
- Candidate was not promoted to production. Promotion remains gated by the prompt policy's full golden-set requirement; this review does not claim that incomplete external gate passed.

### 2026-07-11 single-item gate attempt

The locally changed `scenario/review` prompt was reseeded under `candidate`, then SCP-096 alone was compared with production:

| Attempt | Candidate | Production | Verdict |
|---|---|---|---|
| Default `max_tokens=8192` | `visual_breakdown` truncated (`finish_reason=length`) | Not usable for comparison | Inconclusive / FAIL |
| `max_tokens=16000` | Timeout after 600s | Timeout after 600s | Inconclusive / FAIL |

Neither attempt demonstrates a candidate regression: the first hit the already-documented output limit, and the second failed symmetrically on candidate and baseline. The gate correctly blocks promotion because a broken baseline cannot justify moving the production label. No further live retries were made.

### 2026-07-11 full 3-item promotion re-attempt (post-6.6)

Story 6.6 raised the eval item timeout 600s→1200s specifically because the timeout above blocked this gate. Re-ran `scripts/eval_prompts.py --profile promotion` live, twice.

- **Timeout: confirmed fixed.** No timeout on either rerun, across 6 full scenario chains each.
- **Run 1**: `production` baseline crashed on SCP-096 and SCP-173 — `scenario/writing_scene_repair` (Story 6.5) had a `candidate` label only, never `production`, so any run needing the scene-repair path 404'd. This is a live production gap in an already-`done` story, not a 6-3/6-4 defect. Fixed: added `production` to the existing candidate version's labels via the Langfuse SDK (`update_prompt`, no content change, no new version).
- **Run 2** (after the fix):

  | Item | Verdict | Detail |
  |---|---|---|
  | SCP-096 | PASS | atmosphere +0.33, narrative_coherence +0.33, article_fidelity +0.00, total +0.67 |
  | SCP-049 | FAIL | narrative_coherence **-0.33** (single-axis regression; total +0.67 but zero-tolerance policy fails on any negative axis) |
  | SCP-173 | FAIL | `yaml.YAMLError: mapping values are not allowed here` — survived the bounded retry, propagated as a run failure |

- **Verdict: FAIL.** SCP-173 has flipped between different failing axes/errors across every 6-3/6-4/6-6 gate attempt to date — consistent with LLM-judge/generation stochastic noise on that specific golden item rather than a deterministic code defect, but this was not re-run a third time to confirm (live-API cost). SCP-049's axis regression is new to this run.

### 2026-07-11 promotion gate rerun (post-6.6, further re-attempt)

A further live rerun of `--profile promotion` failed outright on SCP-049 with `EvalJudgeError: unparseable judge response` — one of the three concurrent `_judge_axis` samples for an axis returned malformed JSON (an unescaped control character inside a string value, the judge-output analogue of Story 6.4's scenario-output JSON-escaping problem). Traced to `eval_service.py`: `REPS_PER_AXIS=3` already averages judge noise per axis (Story 4.2/OQ-1), but a bare `asyncio.gather` propagated any single sample's parse failure and discarded the other two already-successful samples, killing the axis and the whole item. Fixed by Story 6.8 (bounded retry-once per sample, degrade to a 2-of-3 average when one sample permanently fails to parse; still fail the axis when 2+ of 3 fail, unchanged from before).

Out of scope for 6.8: the earlier "Run 2" `narrative_coherence` **-0.33** delta on SCP-049 (above) is a difference between two already-3x-averaged scores from two separate scenario-generation runs — more likely full-generation run-to-run variance (DeepSeek's narration text differs slightly on every live run) than a judge-scoring defect. Confirming/fixing that would require repeating full scenario generation multiple times per golden item, which runs directly against Story 6.6's cost-reduction goal. Not attempted here; see Story 6.8's Dev Notes for the same reasoning.
- Jay's direction: stop here rather than spend a third live run. `production` label was **not** moved for the 6-3/6-4 prompt set. Both stories remain `in-progress`.

### 2026-07-11 Story 6.7/6.8 review gate

- Local review verification: **1243 passed, 1 skipped**; Ruff clean.
- Smoke at `YTFLOW_DEEPSEEK_MAX_TOKENS=16000`: SCP-049 completed with atmosphere 4.33, narrative_coherence 5.00, article_fidelity 2.33, total 11.67.
- Promotion artifact: `tmp/eval-prompts/20260711-164208-1783755728393879121-candidate-production/`.
- Promotion verdict: **FAIL**. SCP-049 candidate failed because `scenario/writing_scene_repair` truncated at 16000 tokens; SCP-173 regressed atmosphere -0.33 and narrative_coherence -0.33; SCP-096 improved atmosphere +1.67 but regressed article_fidelity -0.33.
- The review fallback for the not-yet-promoted `scenario/yaml_syntax_repair` prompt was exercised three times by production baselines and correctly retained the prior full-stage retry. No malformed judge response killed an item after the 6.8 fix.
- `production` labels were not moved. The authority gate remains failed for generation truncation/content-score reasons, not for unresolved 6.7/6.8 review findings.

### 2026-07-11 Story 6.9 — writing_scene_repair truncation root cause + fix

Story 6.9 root-caused the `writing_scene_repair` 16k truncation from the retained gate artifact (`tmp/eval-prompts/20260711-164208-.../candidate-SCP-049-full.json`) without a new live run — the per-stage trace already records `target_scene_count` (= `len(indexes)`) and `completion_tokens`:

- SCP-049 has **8 scenes total**. Generating *all 8* narrations from scratch (the `writing` stage) cost only **2,846 completion tokens**. The repair's `len(indexes)` is bounded by the scene count (≤ 8), so the largest possible repair batch is the same ~2,846 tokens — far below the 16,000 ceiling.
- **Batch size is ruled out.** The scoped-repair call emitted > 5× more tokens than regenerating the entire scenario → degenerate/runaway generation (the repair prompt asks the model to echo `original_scenes` and return them mostly-unchanged, a shape DeepSeek loops on), not a batch-volume problem. A batch cap would not have helped.
- **Fix:** `scenario_node` now catches the repair `TruncationError` and routes to the existing full-rewrite fallback path (`retry_scope="scene-repair-truncated-fallback"`) — the full rewrite is proven to complete at ~2.8k tokens. Recovery is narrow: any other repair error still fails the run. `TruncationError` now carries `completion_tokens`/`raw` so future truncations self-document.

Confirming smoke (2026-07-11, Jay-authorized single item, `--profile smoke --label candidate` at 16k): SCP-049 completed clean, total 14.00, 9 scenes. Full 9-scene writing = 4,296 completion tokens — independently reconfirms batch size is not the cause. Review+critic passed on pass 1 so the repair path did not fire this run (stochastic); the fix's happy path is confirmed live and the fallback recovery is unit-tested.

Still **pending live execution** (Jay's cost/authorization decision, as with every prior gate run):

- **SCP-173/096 axis regression triage (AC3):** not yet triaged. Method to apply = repeated-trial comparison (N ≥ 3, matching `REPS_PER_AXIS=3`); a single before/after pair per item is insufficient to call regression vs variance (Story 6.8 precedent).
- **3-item promotion gate rerun (AC4):** not rerun; `production` labels **not** moved for the 6-3/6-4 set.
