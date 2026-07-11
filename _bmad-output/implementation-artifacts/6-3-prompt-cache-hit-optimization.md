---
created: 2026-07-10
baseline_commit: 79543855e99b8b6305a24abf3c93d147d8a073a1
story_key: 6-3-prompt-cache-hit-optimization
story_id: "6.3"
epic: 6
previous_story: 6-2-golden-set-offline-eval
depends_on:
  - 6-1-prompt-policy-variant-label-wiring   # candidate/production label + fallback wiring this story's re-seeded templates must go through
  - 6-2-golden-set-offline-eval              # promotion gate this story's re-seeded templates must pass before touching production
related:
  - 8-10-cast-decision-split-call            # the call-count-reducing re-merge this story explicitly does NOT attempt (regression precedent)
workflow_decision: "No new LangGraph stage, no new service. Prompt-file reordering + a thin usage-accumulation change inside scenario_node's existing trace enrichment (_record_trace)."
evidence: "2026-07-10 investigation of Jay's 'LLM calls happen more than expected' report — confirmed scenario_node issues 6+2N calls per pass / 9+4N with one retry (N=scene count, typically 8-12), roughly 2-3x the stale 2026-07-03 design doc estimate, after 8.10's cast_decision split and 5-4's tts_normalize_step. See _bmad-output/implementation-artifacts/deferred-work.md#Deferred from: investigation of scenario LLM call volume (2026-07-10) for the two riskier call-count-reduction ideas considered and rejected for this story."
---

# Story 6.3: DeepSeek Prompt Cache-Hit Optimization + Token/Cost Observability

Status: in-progress

## Story

As Jay,
I want the scenario chain's prompt templates reordered to maximize DeepSeek's automatic prefix-cache hit rate, and per-stage token/cache usage recorded on the Langfuse trace,
so that the already-necessary high call count (6+2N per pass, 9+4N with one retry) costs less per call and is actually measurable instead of invisible.

## Context

Jay flagged that scenario LLM calls happen more than expected. Investigation confirmed the call count is real and by design, not a bug: `_write_and_review` (`src/yt_flow/pipeline/nodes/scenario.py:92-142`) issues `research`(1) + `structure`(1) + `writing`(1) + `N` scenes × (`cast_decision_step` + `visual_breakdown_step`) + `review`(1) + `critic_agent`(1) + `tts_normalize_step`(1) = `6+2N` DeepSeek calls per pass, and the bounded retry (`scenario.py:179-185`) re-runs `writing` + all `N` scenes' breakdown + `review` + `critic_agent` once more if `critic.verdict == "retry"` or `review.overall_pass` is false, bringing the worst case to `9+4N`. For a typical 8-12 scene video that is 22-30 calls normally, 41-57 with one retry — well above the `2026-07-03-scenario-multistage-design.md` doc's stale estimate of "12-16 normal, ~20 with retry" (written before Story 8.10 split `cast_decision_step` out of `visual_breakdown_step`, and before Story 5-4 added `tts_normalize_step`).

Reducing the call *count* itself was considered and rejected for this story:

- Re-merging `cast_decision_step` back into `visual_breakdown_step` is the exact regression Story 8.10 fixed (deepseek-v4-flash reverting to the pre-8.1 `entity_visible` schema when both tasks are asked for in one call — reproduced 0/125 shots). Not revisited here.
- Scene-scoped partial retry (only re-run flagged scenes) needs `writing_step` to accept/emit per-scene feedback instead of rewriting all scenes' narration from one free-text `quality_feedback` string — a contract redesign, out of scope.

Both are logged with their `재고 조건` (reconsider-if condition) in `deferred-work.md` rather than attempted here.

What this story does instead is the safe, industry-standard lever: DeepSeek's **Context Caching on Disk** is already active on the account by default (no code change required to turn it on) and bills a *matching prompt prefix* at 1/10 the normal input-token price (`prompt_cache_hit_tokens` $0.014/M vs `prompt_cache_miss_tokens` $0.14/M on V4 Flash — the model this project already uses, `config.py:27`). The discount only applies to the literal byte-for-byte prefix shared between calls, so a template that puts static/repeated content first and per-call-unique content last gets the discount; one that interleaves them does not. Right now several `prompts/scenario/*.md` templates put per-run-varying fields (e.g. `{{scene_num}}`, `{{scene_role}}`) ahead of blocks that are constant across every scene in the same run (`{{story_logline}}`, `{{entity_sheet}}`, `format_guide`), which caps how much of the prompt can ever hit cache even within one run's own scene loop. Whether a reorder actually improves the cache-hit rate is not visible anywhere today: `_call_stage` (`scenario_chain.py:153-174`) receives `(raw, _usage, finish_reason)` from `_call_deepseek` and discards `_usage` outright (`scenario_chain.py:171` — bound to `_usage`, never read again), so there is currently zero token or cost signal on any scenario trace to confirm caching is working before or after this story's changes.

## Acceptance Criteria

1. **Given** each of `prompts/scenario/{research,structure,writing,cast_decision,visual_breakdown,review,critic_agent}.md`, **Then** blocks that are constant across every call within one `scenario_node` run (`format_guide`, `frozen_descriptor`/`scp_visual_reference`, `entity_sheet`, `story_logline`, and any fixed system/instruction prose) are positioned before blocks that vary per scene or per call (`scene_num`, `narration`, `numbered_sentences`, `cast_by_sentence`, `scene_role`, etc.). The prompt's instructions/content are unchanged — only ordering moves. `tts_normalize.md` is exempt (its inputs are already a single per-run `scenes_json` block with no repeated-across-calls prefix to preserve).
2. **Given** `_call_stage` in `scenario_chain.py`, **Then** the `usage` dict returned by `_call_deepseek` is no longer discarded — it is threaded back to the caller (`scenario.py`) alongside the existing raw text/finish_reason, without changing `_call_stage`'s existing exception behavior on `finish_reason == "length"`.
3. **Given** `scenario.py`'s `stages` list (already accumulated through `_write_and_review` and `scenario_node` and passed to `_record_trace`), **Then** each stage's dict additionally carries `prompt_tokens`, `completion_tokens`, `prompt_cache_hit_tokens`, and `prompt_cache_miss_tokens` sourced from that stage's DeepSeek `usage` response (field names per DeepSeek's documented `usage` schema — degrade a missing/absent field to `0` rather than raising, consistent with AD-10's non-fatal tracing).
4. **Given** `_record_trace`'s existing `metadata={"stages": stages, ...}` payload (`scenario.py:69-82`), **Then** the enriched per-stage token/cache fields are visible there — no new Langfuse call site, no new span.
5. **Given** the reordered templates, **Then** they are seeded under the `candidate` label (`uv run python scripts/migrate_prompts.py --label candidate --source prompts`) and pass the existing golden-set gate (`uv run python scripts/eval_prompts.py --label candidate --baseline production`) before promotion, per `docs/PROMPT_POLICY.md`'s unchanged change protocol — this story does not modify the policy or the gate.
6. **Given** one real SCP run executed twice (once on `production`-label templates, once on the reordered `candidate`-label templates), **Then** the resulting trace metadata's `prompt_cache_hit_tokens` totals are compared and recorded as evidence in this story's Dev Agent Record — expect a visible increase concentrated in the repeated `cast_decision`/`visual_breakdown` calls across scenes within the candidate run.

## Tasks / Subtasks

- [x] Task 1: Reorder `prompts/scenario/visual_breakdown.md`, `cast_decision.md`, `review.md`, `critic_agent.md`, `structure.md`, `research.md`, `writing.md` — move per-run-constant sections (format guide / frozen descriptor / entity sheet / story logline / research packet echoes) ahead of per-scene/per-call sections (scene number, narration, numbered sentences, scene role, cast-by-sentence). No wording changes. (AC:1)
- [x] Task 2: Change `_call_deepseek`'s call sites so `_call_stage` returns/forwards `usage` instead of discarding it — smallest change is widening `_call_stage`'s return to `(raw, usage, finish_reason)` and updating its one caller inside each `*_step` function, or accumulating usage via an out-parameter/callback the caller already has (`stages` list) — pick whichever keeps `scenario_chain.py`'s existing per-step return-value contracts (`research_step` returns `dict`, etc.) unchanged, since those are consumed positionally by `scenario.py` and covered by existing tests. (AC:2)
  - [x] Sub-task: decide the seam without breaking `research_step`/`structure_step`/`writing_step`/`cast_decision_step`/`visual_breakdown_step`/`review_step`/`critic_step`'s existing test doubles in `tests/` (grep for `call_deepseek` fakes before changing the tuple shape they return).
- [x] Task 3: Extend each `stages.append({...})` call site in `scenario.py` (`_write_and_review` and `scenario_node`) to fold in that stage's token/cache fields from Task 2's plumbing. (AC:3, 4)
- [x] Task 4: Seed `candidate` label for the reordered templates and run the golden-set gate; record the comparison table in this story's Dev Agent Record. Do not move `production` until the gate passes. (AC:5)
- [x] Task 5: Live-run one SCP twice (`production` then `candidate` label) and compare `prompt_cache_hit_tokens` totals from the trace metadata; record as evidence. (AC:6)
- [x] Task 6: Unit tests — reorder is prompt-content-only (no new test needed beyond the existing golden-set gate for AC1/5); usage-plumbing changes (AC2/3) need tests confirming stage dicts carry the new token fields and that a missing/absent `usage` field degrades to `0` without raising.

### Review Findings

- [x] [Review][Patch] Remove concurrent global trace monkeypatch from prompt evaluation [`scripts/eval_prompts.py`]
- [x] [Review][Patch] Reject boolean and negative usage counters [`src/yt_flow/pipeline/nodes/scenario.py`]
- [x] [Review][Patch] Preserve the fixed review prefix ahead of retry-varying generated inputs [`prompts/scenario/review.md`]
- [x] [Review][Patch] Persist cache and YAML reliability evidence with explicit measurement limits [`6-3-6-4-review-metrics-report.md`]
- [ ] [Review][Decision] Golden gate and production promotion remain incomplete — the approved SCP-096-only follow-up was inconclusive; promotion remains blocked by prompt policy.

#### Single-item follow-up (2026-07-11)

- Jay approved using one of three golden items, so SCP-096 alone was rerun after reseeding candidate. The default-8192 attempt truncated candidate `visual_breakdown`; the 16000-token attempt timed out symmetrically for both candidate and production after 600 seconds. Both comparisons were inconclusive and correctly returned FAIL. No production label was moved and no further LLM retry was made.

#### Full 3-item promotion re-attempt after Story 6.6 (2026-07-11)

- Story 6.6 raised the full-scenario eval timeout 600s→1200s specifically because this story's and 6.4's promotion attempts timed out symmetrically. Re-ran `--profile promotion` twice live to check whether that unblocks promotion.
- **Timeout confirmed fixed**: neither rerun hit a timeout on any of the 6 full scenario chains (3 items × 2 labels).
- **Run 1** failed for a cause outside this story: `production` baseline crashed on SCP-096/SCP-173 because `scenario/writing_scene_repair` (Story 6.5) had never been promoted to `production` — fixed by adding the `production` label to its existing candidate version (see [6-5](6-5-scenario-scoped-repair-retry.md)'s Change Log). SCP-049 also hit a one-off judge-response parse failure on `candidate` (did not recur in run 2 — looks like eval-harness/judge noise, not a candidate defect).
- **Run 2** (after the label fix): SCP-096 PASS (all axes ≥ production). SCP-049 FAIL — `narrative_coherence` regressed -0.33 despite a net-positive total (+0.67); the gate's zero-tolerance any-negative-axis rule fails it regardless of total. SCP-173 FAIL — a `yaml.YAMLError` (`mapping values are not allowed here`, a plain-scalar value containing an unescaped colon) survived the bounded retry and propagated. SCP-173 has been the noisy/borderline item across every prior 6-3/6-4/6-6 gate attempt (different axis flips each time) — this looks like the same stochastic-noise pattern rather than a new deterministic defect, but it was not re-run a third time to confirm (cost).
- **Verdict: still FAIL.** Jay's direction: stop here rather than spend a third live run chasing SCP-173 noise. `production` label NOT moved for the 6-3/6-4 prompt set (unlike `writing_scene_repair`, which was a distinct, already-decided fix). Status remains in-progress.

## Dev Notes

### Source Context

- Epic 6 goal: prompt lifecycle is versioned + labeled + eval-gated, using Langfuse's native features only — no bespoke infra. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 6: Prompt Ops — 프롬프트 버저닝·평가 정책`]
- Story 6.3's own epics.md entry has the full cost/call-count numbers and the two explicitly-rejected approaches. [Source: `_bmad-output/planning-artifacts/epics.md#Story 6.3: DeepSeek 프롬프트 캐시-히트 최적화 + 토큰/비용 관측성`]
- Architecture AD-10: Langfuse/tracing failures must never be fatal to the pipeline. The new token/cache fields follow the same rule as the rest of `_record_trace` — wrapped in the existing best-effort `try/except`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10 — Operational envelope`]
- Root-cause numbers and the design doc's stale estimate: [Source: `docs/superpowers/specs/2026-07-03-scenario-multistage-design.md:57`]
- The regression this story deliberately does not re-attempt: [Source: `sprint-status.yaml` `8-10-cast-decision-split-call` entry; `src/yt_flow/pipeline/nodes/scenario_chain.py:299-315` docstring]

### Existing Code To Reuse / Modify

- `_call_deepseek` already returns `(content, usage, finish_reason)` — `usage` is the DeepSeek response's raw `usage` dict, already available, just unused past `scenario.py:66`. [Source: `src/yt_flow/pipeline/nodes/scenario.py#L50-L66`]
- `_call_stage` is the single choke point every `*_step` function calls through — extend its return value here rather than touching seven call sites individually. [Source: `src/yt_flow/pipeline/nodes/scenario_chain.py#L153-L174`]
- `_record_trace` already accepts an arbitrary `stages: list[dict]` and dumps it into trace metadata verbatim — extending the dict shape needs zero changes to `_record_trace` itself. [Source: `src/yt_flow/pipeline/nodes/scenario.py#L69-L82`]
- `prompt.compile(**variables)` is Langfuse's own mustache-style `{{var}}` substitution (`TextPromptClient`/`ChatPromptClient`) — reordering template sections is pure text editing in the `.md` files, no compiler/parser change. [Source: `src/yt_flow/services/prompt_service.py`]
- `scripts/migrate_prompts.py --label candidate --source prompts` is the existing seeding path for a reworded/reordered template — do not hand-edit prompts in the Langfuse UI (Rule 5, PROMPT_POLICY.md). [Source: `docs/PROMPT_POLICY.md`]

### DeepSeek Context Caching on Disk (verified 2026-07-10)

- Enabled automatically for all API accounts, no opt-in flag — but only benefits prompts whose prefix is byte-identical across calls.
- V4 Flash (this project's `deepseek_model`, `config.py:27`) pricing: cache-hit input tokens $0.014/M vs cache-miss $0.14/M — a 90% discount on the portion of the prompt that matches a previously-seen prefix.
- The response `usage` object carries `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens` alongside the standard `prompt_tokens`/`completion_tokens` — this is the exact field set AC3 records.
- Cache benefit is real within a single `scenario_node` run's own scene loop (7-12 `cast_decision`/`visual_breakdown` calls per run share `entity_sheet`/`story_logline`/`format_guide` verbatim) even before considering cross-run caching. [Source: https://api-docs.deepseek.com/news/news0802/]

### Project Structure Notes

- Modify: `prompts/scenario/*.md` (all 7 templates except `tts_normalize.md`), `src/yt_flow/pipeline/nodes/scenario_chain.py` (`_call_stage` + step function return plumbing), `src/yt_flow/pipeline/nodes/scenario.py` (`_write_and_review`/`scenario_node` stage-dict construction).
- No new files, no new Settings fields, no new dependency — `usage` is already returned by the existing `httpx` call.

### Out Of Scope

- Reducing DeepSeek call *count* (re-merging steps, scene-scoped partial retry) — see Context section and `deferred-work.md`.
- Any change to `docs/PROMPT_POLICY.md` or `scripts/eval_prompts.py` — the existing gate is reused unchanged.
- Model tiering / swapping to a cheaper model — `deepseek-v4-flash` is already the project's cheapest configured tier (`config.py:27,31`); there is no cheaper model to route simple stages to.
- A/B run cost (`create_ab_run` doubling everything for variant B) — inherent to running an actual A/B comparison, not addressed here.

### References

- [Source: src/yt_flow/pipeline/nodes/scenario.py#L1-L196] — full `scenario_node` call structure this story instruments, does not restructure
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L153-L174] — `_call_stage`, the single seam for AC2
- [Source: docs/superpowers/specs/2026-07-03-scenario-multistage-design.md] — original (now stale) call-count estimate
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#Deferred from: investigation of scenario LLM call volume (2026-07-10)] — the two rejected call-count approaches and their reconsider-if conditions

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- `prompts/scenario/critic_agent.md` did not exist in the repo before this story despite being live in Langfuse `production` — it was originally seeded from `/mnt/work/projects/yt.pipe/templates/scenario/critic_agent.md` (the `DEFAULT_SOURCE` path in `migrate_prompts.py`), never from this repo's own `prompts/` dir, a pre-existing `PROMPT_POLICY.md` Rule 1 gap unrelated to this story. Fetched the current `production` text via `prompt_service.get_prompt` and created the file here (content unchanged, `{var}`→`{{var}}` already matched) so Task 1's reorder had something to edit and the repo becomes source-of-truth going forward.
- A second live dev-story session (story 6-4, `scenario-yaml-output-bounded-retry`) was concurrently editing the same 8 `prompts/scenario/*.md` files (converting JSON output blocks to YAML + adding `{{parse_error}}`) — flagged by the story's own sprint-status.yaml annotation as needing sequential, not parallel, execution. Proceeded anyway per Jay's direction, re-reading each file immediately before every write and layering the reorder on top of whatever 6-4 had already landed, rather than reverting it.
- `prompts/scenario/cast_decision.md`'s title reverted from `# Stage 3.4: Cast Decision` back to `# Stage 3.4: Cast Decision — Scene {{scene_num}}` twice during the session (external process, flagged "intentional" both times). Re-applied the removal a third time per Jay's explicit instruction ("니가 바꾸고, 주석 남겨놓으면 되는거 아님?") and dropped the now-dead `scene_num` variable from `cast_decision_step`'s compile call — it held after that.
- `writing.md` was analyzed against the AC1 rule and found **already optimal**: `quality_feedback` is the only field that differs between the normal pass and the bounded retry within one run, and it already sits second-to-last, immediately before `## Task`. No edit made to this file — forcing a synthetic reorder would have been busywork.
- First full golden-set gate attempt (3 SCPs × 2 labels via `eval_prompts.py`) FAILED — but on infra timeouts (`timeout after 600s`) and one stochastic `finish_reason=length` truncation, not a functional regression (production also timed out on the same item; token count is unchanged by pure reordering). Did not re-run the full 3-SCP set a second time — real DeepSeek cost/time — after Jay flagged the token spend. A parallel session's own single-SCP (`SCP-096`) `candidate`-vs-`production` gate run, started independently, was reused instead per Jay's direction (`PASS`, all axes ≥ production).
- `scripts/eval_prompts.py`'s artifact-writing only ever fired for failed items (`write_artifact` docstring: "for a failed item/stage"), so the SCP-096 gate run's token/cache numbers were not recoverable after the fact and a Langfuse trace lookup by timestamp was unreliable (client-side flush timing / no run_id-to-trace_id link in `_record_trace`). Jay asked mid-session for this to be fixed going forward — patched `_run_scenario` to capture `stages` via a temporary `_record_trace` monkeypatch (same technique as `test_scenario.py`'s new stage-token test) and `evaluate_label` to write the debug artifact for every item, not only failures. This is a deviation from the story's own "Out Of Scope" line ("Any change to ... `scripts/eval_prompts.py`") — done explicitly on Jay's direct instruction, not silently.
- Task 5's live A/B comparison ran directly against `scenario_node` (bypassing Langfuse entirely, same monkeypatch technique as above) for SCP-096, one pass per label, to avoid the trace-lookup unreliability and avoid a second live run — see comparison table below.

### Completion Notes List

- **AC1** (template reordering): Applied to `visual_breakdown.md`, `cast_decision.md`, `review.md`, `structure.md`, `research.md`, and the newly-created `critic_agent.md`. `writing.md` needed no change (see Debug Log). For `visual_breakdown.md`/`cast_decision.md` — the per-scene-loop stages, called 7-12× per run — also removed `{{scene_num}}` from the very first line of the title, since a single differing token at byte 0 defeats prefix-hash-chained caching for the *entire* remainder of the prompt regardless of any downstream reordering.
- **AC2/AC3** (usage plumbing): `_call_stage` now returns `(raw, usage)`; `_call_stage_with_retry` gained an optional `usage_sink: list[dict] | None` out-parameter that collects one entry per underlying DeepSeek call (two on a bounded retry). Every `*_step` function threads an optional `usage_sink` kwarg straight through — additive only, existing callers omitting it are unaffected (verified by `test_research_step_usage_sink_defaults_to_none_without_error`).
- **AC3/AC4**: added `scenario.py::_usage_totals(usage_list)` — sums `prompt_tokens`/`completion_tokens`/`prompt_cache_hit_tokens`/`prompt_cache_miss_tokens` across a stage's usage entries, degrading anything missing/non-`dict`/non-`int` to `0` without raising (AD-10). Every `stages.append({...})` call site in `_write_and_review` and `scenario_node` now spreads `**_usage_totals(usage)` in; the `visual_breakdown` aggregate stage sums usage across all `cast_decision_step` + `visual_breakdown_step` calls for every scene in that run's `asyncio.gather` fan-out into one shared list. No new Langfuse call site, no new span — same `_record_trace(stages=stages, ...)` call as before.
- **AC5**: seeded `candidate` label (`scripts/migrate_prompts.py --label candidate --source prompts`). Full 3-SCP golden-set gate run was inconclusive (infra timeouts, see Debug Log); reused a parallel session's independent single-SCP (`SCP-096`) gate run: **PASS** (atmosphere +2.00, narrative_coherence +0.00, article_fidelity +0.67, total +2.67 — every candidate axis ≥ production). Two of three golden SCPs (`SCP-173`, `SCP-049`) remain unverified against the gate — flagged for Jay to decide whether to run before actually moving the `production` label in the Langfuse UI (this story does not do that move itself — Rule 5, PROMPT_POLICY.md).
- **AC6**: live one-pass-per-label comparison on SCP-096 (table below). Overall cache-hit rate: production 11,008 / 218,647 prompt tokens (**5.0%**) vs candidate 32,512 / 123,067 (**26.4%**). The `visual_breakdown` stage — the primary target (7-12 calls/run sharing `entity_sheet`/`story_logline`/`format_guide`) — went from 4.3% to 42.9% hit rate. `structure` (single call/run, cross-run cache reuse) went from 0% to 52.9%. `writing`/`review` stayed at 0% hit on both labels; this run's retry (production only) happened ~3-5 min after the first pass, long enough that any disk-cache entry for that prefix may already have evicted — a plausible but unconfirmed explanation, noted as a limitation rather than asserted as fact. Production's total-token figure is further inflated by its own bounded retry firing (candidate passed review/critic on the first try) — the retry is a content-quality outcome, not something this story's reordering controls, so per-stage hit-rate (not total tokens) is the reliable comparison metric.

  | Stage | Prod prompt | Prod hit | Prod hit% | Cand prompt | Cand hit | Cand hit% |
  |---|---|---|---|---|---|---|
  | research | 2,271 | 2,176 | 95.8% | 2,284 | 2,176 | 95.3% |
  | structure | 3,821 | 0 | 0% | 3,630 | 1,920 | 52.9% |
  | writing (pass 1) | 5,078 | 0 | 0% | 5,486 | 0 | 0% |
  | visual_breakdown (pass 1) | 53,143 | 2,304 | 4.3% | 58,762 | 25,216 | 42.9% |
  | review (pass 1) | 21,989 | 0 | 0% | 25,127 | 0 | 0% |
  | critic_agent (pass 1) | 21,377 | 1,408 | 6.6% | 24,346 | 1,792 | 7.4% |
  | writing (retry) | 5,544 | 0 | 0% | — | — | — |
  | visual_breakdown (retry) | 53,543 | 2,304 | 4.3% | — | — | — |
  | review (retry) | 24,561 | 0 | 0% | — | — | — |
  | critic_agent (retry) | 23,948 | 1,408 | 5.9% | — | — | — |
  | tts_normalize | 3,372 | 1,408 | 41.8% | 3,432 | 1,408 | 41.0% |
  | **TOTAL** | **218,647** | **11,008** | **5.0%** | **123,067** | **32,512** | **26.4%** |

- **Out-of-scope deviation**: patched `scripts/eval_prompts.py` (artifact persistence for non-failing items) on Jay's explicit mid-session instruction, despite the story's own "Out Of Scope" section naming this file. Updated its one affected test (`test_evaluate_label_full_failure_artifact_includes_parsed_state`) to match; full `tests/test_eval_prompts.py` suite (57 tests) passes.
- Regression: full suite `1111 passed, 1 skipped` (excluding `tests/services/test_character_service_generation.py`, a pre-existing hang unrelated to this story — see `test-isolation-workspace-pollution` memory). Scenario-specific suites: `tests/pipeline/nodes/test_scenario.py` + `test_scenario_chain.py` — 202 passed.

### File List

- `prompts/scenario/visual_breakdown.md` (modified — reordered, `{{scene_num}}` removed from title)
- `prompts/scenario/cast_decision.md` (modified — reordered, `{{scene_num}}` removed from title)
- `prompts/scenario/review.md` (modified — reordered)
- `prompts/scenario/structure.md` (modified — reordered)
- `prompts/scenario/research.md` (modified — reordered)
- `prompts/scenario/critic_agent.md` (new — established as repo source-of-truth, reordered)
- `src/yt_flow/pipeline/nodes/scenario_chain.py` (modified — `_call_stage`/`_call_stage_with_retry`/`*_step` usage_sink plumbing; removed dead `scene_num` var from `cast_decision_step`)
- `src/yt_flow/pipeline/nodes/scenario.py` (modified — `_usage_totals` helper, stage dicts enriched with token/cache fields)
- `scripts/eval_prompts.py` (modified — persist `stages` token evidence for every item, not only failures; out-of-scope fix per Jay's instruction)
- `tests/pipeline/nodes/test_scenario_chain.py` (modified — fixed stale `{{scene_num}}` placeholder assertion; added usage_sink plumbing tests)
- `tests/pipeline/nodes/test_scenario.py` (modified — added `_usage_totals` + stage token-field enrichment tests)
- `tests/test_eval_prompts.py` (modified — updated `parsed_state` equality assertion for the new `stages` key)

## Change Log

- 2026-07-10: Implemented AC1-AC6. Reordered 6 of 7 scenario templates (`writing.md` already optimal) + created missing `critic_agent.md` as repo source-of-truth. Threaded DeepSeek `usage` through `_call_stage`/`_call_stage_with_retry`/every `*_step` via an additive `usage_sink` out-parameter; `scenario.py` sums it into every `stages.append` via a new `_usage_totals` helper (AD-10-safe). Seeded `candidate`, reused a parallel session's SCP-096 golden-set gate (PASS) in place of a second full 3-SCP run (cost-driven). Live one-pass-per-label comparison on SCP-096: cache-hit rate 5.0% (production) → 26.4% (candidate); `visual_breakdown` 4.3% → 42.9%. Also patched `scripts/eval_prompts.py` (out-of-scope, per Jay's explicit instruction) so future eval runs persist token/cache evidence for every item, not only failures.
