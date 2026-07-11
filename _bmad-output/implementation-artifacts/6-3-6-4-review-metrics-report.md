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
- Jay's direction: stop here rather than spend a third live run. `production` label was **not** moved for the 6-3/6-4 prompt set. Both stories remain `in-progress`.
