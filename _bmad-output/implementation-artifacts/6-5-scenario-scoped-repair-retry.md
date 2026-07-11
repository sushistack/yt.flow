---
created: 2026-07-11
story_key: 6-5-scenario-scoped-repair-retry
story_id: "6.5"
epic: 6
previous_story: 6-4-scenario-yaml-output-bounded-retry
depends_on:
  - 6-3-prompt-cache-hit-optimization
  - 6-4-scenario-yaml-output-bounded-retry
evidence: "SCP-096 candidate/production eval on 2026-07-11 exceeded the 600s item timeout. Completed stage latency was 480.590s candidate and 572.352s production; both entered the scenario-level full retry. visual_breakdown alone took 98.903-132.942s per pass."
baseline_commit: 66c8d2899d73b9945e5de4f7398b885eea78b01b
---

# Story 6.5: Scene-Scoped Scenario Repair Retry

Status: done

## Story

As Jay,
I want failed scenario quality checks to repair only the affected scenes and regenerate only their dependent visual work,
so that one review failure does not repeat writing and visual generation for every scene and push normal operations beyond ten minutes.

## Acceptance Criteria

1. **Given** the first `writing → cast/visual → review → critic` pass, **when** `review.overall_pass` is false or `critic.verdict == "retry"`, **then** the retry scope is the validated union of `review.issues[*].scene_num` and `critic.scene_notes[*].scene_num`; invalid, duplicate, boolean, zero, negative, or out-of-range identifiers are ignored and recorded in trace metadata.
2. **Given** at least one valid flagged scene, **then** a new `writing_scene_repair_step` performs one DeepSeek call for the flagged subset only, accepting the original scene objects plus scene-scoped review/critic feedback and returning exactly the same scene identifiers/count. It may change narration and scene metadata for those scenes only; unflagged writing objects remain byte-for-byte/equality unchanged.
3. **Given** repaired scenes, **then** `cast_decision_step` and `visual_breakdown_step` rerun only for those positional scene indexes. Existing `visual_by_scene` values for unflagged scenes are reused unchanged. Results are merged by validated positional index, never by an LLM-provided duplicate `scene_num`.
4. **Given** the partial repair completes, **then** `review_step` and `critic_step` run once against the merged complete scenario. The retry remains bounded: no third quality pass occurs even if the second review still requests retry, preserving the current single-retry contract.
5. **Given** retry is requested but no valid scene can be derived, **then** the code uses one explicit bounded full-rewrite fallback to preserve current quality behavior. It records `retry_scope="full-fallback"` and the reason; it must never silently skip requested repair.
6. **Given** `N` scenes and `k` flagged scenes, **then** the normal path remains `6+2N` DeepSeek calls and the scoped retry adds `3+2k` calls (one scene-repair writing call, `2k` cast/visual calls, one review, one critic), rather than the current `3+2N`. Unit tests prove `N=8,k=1` adds 5 calls rather than 19.
7. **Given** trace stage metadata, **then** it exposes `pass_index`, `retry_scope` (`none|scene|full-fallback`), `target_scene_count`, target positional indexes, latency, and the existing token/cache fields. Tracing remains best-effort and non-fatal under AD-10.
8. **Given** the new prompt, **then** `prompts/scenario/writing_scene_repair.md` is the repo source of truth, uses the existing YAML + `{{parse_error}}` bounded-retry contract, places invariant instructions before variable scene data for prefix caching, and follows candidate seeding/promotion policy.
9. **Given** local verification, **then** tests cover: one flagged scene, multiple/duplicate/invalid flags, critic-only flags, no-valid-flag full fallback, repaired output with missing/extra scene, preservation of unflagged writing/visual objects, second quality failure remaining bounded, and stage/token trace aggregation across both passes.
10. **Given** live validation, **then** one representative SCP run records total wall time, call count, retry scope, and cache/token usage. It must demonstrate scoped execution if a retry naturally fires or via a controlled local fake; live validation must not deliberately spend calls trying to force stochastic retry behavior.

## Tasks / Subtasks

- [x] Task 1: Extract pure retry-scope helpers from review/critic output (AC: 1, 5)
  - [x] Return positional indexes and rejected identifiers/reasons without mutating model output.
  - [x] Keep `_format_feedback` for full fallback; add scene-scoped feedback formatting.
- [x] Task 2: Add `writing_scene_repair_step` and prompt (AC: 2, 8)
  - [x] Reuse `_call_stage_with_retry`, YAML parsing, usage sink, prompt label fallback, and freetext normalization.
  - [x] Validate exact requested-scene coverage before merging.
- [x] Task 3: Split `_write_and_review` into reusable initial-pass and scoped-repair seams (AC: 3-6)
  - [x] Do not add a LangGraph node, DB state, service, or dependency.
  - [x] Preserve `build_scenes` positional contracts and existing normal-path output.
- [x] Task 4: Extend trace metadata without adding spans (AC: 7)
- [x] Task 5: Add focused orchestration/parser/prompt tests (AC: 9)
- [x] Task 6: Seed candidate and perform one cost-bounded validation (AC: 8, 10)

### Review Findings

- [x] [Review][Patch] `_retry_scope` trusts review/critic `scene_num` as a direct positional index without verifying it matches `writing["scenes"][idx]["scene_num"]`, contradicting the codebase's own "never trust LLM scene_num for lookups" rule enforced in `_breakdown_for` [src/yt_flow/pipeline/nodes/scenario.py:_retry_scope] — fixed: added a `scene_num-mismatch` rejection guard + regression test
- [x] [Review][Patch] `_format_scene_feedback`'s chained `.get(a, .get(b, .get(c, default)))` fallback doesn't fall through when a key is present but explicitly `None`; `critic_step` doesn't schema-validate `scene_notes` entries so this is reachable [src/yt_flow/pipeline/nodes/scenario.py:_format_scene_feedback] — fixed: switched to `or`-chained fallback
- [x] [Review][Patch] AC9 requires a "critic-only flags" test through the real `scenario_node` path; existing fixtures always have empty `scene_notes`, so no test exercises scoped repair triggered purely by critic feedback [tests/pipeline/nodes/test_scenario.py] — added `test_critic_only_flag_triggers_scene_scoped_repair`
- [x] [Review][Patch] AC9 requires proof that a second quality failure after scoped repair stays bounded (no third pass); only the full-fallback branch's boundedness is tested [tests/pipeline/nodes/test_scenario.py] — added `test_second_review_failure_after_scene_repair_remains_bounded`
- [x] [Review][Patch] AC9 requires trace/token aggregation coverage across both passes for the scene-scoped branch; only the full-fallback branch's trace fields are asserted via `trace_sink` [tests/pipeline/nodes/test_scenario.py] — added `test_scene_repair_trace_fields_and_usage_recorded`
- [x] [Review][Defer] If `writing_scene_repair_step` exhausts its own bounded retry and raises even with valid scenes identified, `scenario_node`'s top-level catch surfaces the whole run as failed rather than falling back to full rewrite — matches the pre-existing pattern for any exhausted per-stage bounded retry, not a new regression — deferred, pre-existing
- [x] [Review][Defer] `target_scene_count`/`target_scene_indexes` for the first pass and full-fallback are computed from `len(structure)` independent of the actual `writing_step` scene count, slightly inaccurate in the documented writing/structure-count-mismatch edge case; observability-only under AD-10 — deferred, pre-existing
- [x] [Review][Defer] `_retry_scope` silently drops an entire malformed (non-list) `review["issues"]`/`critic["scene_notes"]` source without a trace entry; AC1's rejection-recording guarantee is written at the per-identifier level, not source-shape level — deferred, out of AC1's literal scope

## Dev Notes

### Current State and Required Change

- `scenario_node` currently calls `_write_and_review` once, then calls the same function again with global free-text feedback. That repeats `writing_step`, every scene's `cast_decision_step`, every scene's `visual_breakdown_step`, `review_step`, and `critic_step`.
- `_write_and_review` already keys visual results by positional `idx`; retain that rule. LLM `scene_num` is not a safe merge key because duplicate scene numbers are already a tested failure mode.
- `review.issues` and `critic.scene_notes` are the existing sources for scene-local feedback. Do not add a separate classifier LLM call.
- `writing_step` is deliberately a whole-script call. Add a focused repair prompt/step rather than overloading its current contract with modes and optional shapes.

### Architecture and Guardrails

- Keep the change inside `pipeline/nodes`; pipeline nodes remain pure and must not touch DB/SSE (AD-1/AD-4).
- No new LangGraph stage or gate. This is internal work within the existing `scenario` node.
- Observability failures remain non-fatal (AD-10). Do not make trace metadata a control-flow dependency.
- Preserve Story 6.4's per-stage parse/schema bounded retry. The new scene quality retry is a separate outer bound; neither mechanism may become an open loop.
- Preserve Story 8.10's split `cast_decision` and `visual_breakdown` calls. Re-merging them reproduced the 0/125 cast regression and is out of scope.

### Expected Files

- UPDATE: `src/yt_flow/pipeline/nodes/scenario.py`
- UPDATE: `src/yt_flow/pipeline/nodes/scenario_chain.py`
- NEW: `prompts/scenario/writing_scene_repair.md`
- UPDATE: `scripts/migrate_prompts.py` only if prompt discovery is explicit rather than recursive
- UPDATE: `tests/pipeline/nodes/test_scenario.py`
- UPDATE: `tests/pipeline/nodes/test_scenario_chain.py`

### Testing Requirements

- Use fakes/cassettes; local tests must make zero external LLM requests.
- Assert object preservation for unflagged scenes, exact call counts, and bounded behavior—not just final success.
- Run focused scenario tests and Ruff first. A full suite is proportional only if shared contracts changed.

### Out of Scope

- Combining `review_step` and `critic_step`.
- Re-merging cast decision with visual breakdown.
- Persistent cross-run response caching or provider/model replacement.
- Changing the golden-set policy; Story 6.6 owns evaluation tiers.

### References

- [Source: `src/yt_flow/pipeline/nodes/scenario.py` — `_write_and_review`, `_format_feedback`, `scenario_node`]
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md#Deferred from: investigation of scenario LLM call volume (2026-07-10)`]
- [Source: `_bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10 — Operational envelope`]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Implementation Plan

- Extract deterministic retry-scope and feedback helpers before changing orchestration.
- Add a bounded YAML repair stage that validates exact ordered scene coverage.
- Merge repaired writing and regenerated visuals by validated positional index, then rerun quality once.
- Preserve the full-rewrite fallback and enrich existing stage metadata without new spans.
- Prove call-count, preservation, parser, fallback, and bounded-retry contracts with local fakes.

### Debug Log References

- Focused scenario suite: `219 passed in 0.56s`; Ruff: clean.
- Full regression suite: `1191 passed, 1 skipped` in 255.41s.
- Controlled SCP-173 fake (`N=8`, `k=1`): 0.91s wall time; scoped retry added 5 calls (repair + cast + visual + review + critic), `retry_scope=scene`; fake usage/cache values remain zero and all token/cache fields were present.
- Candidate seed: `scenario/writing_scene_repair` created via `scripts/migrate_prompts.py`; production label not moved.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Implemented validated review/critic scene-scope extraction with duplicate and invalid identifier evidence.
- Added exact-coverage scene writing repair and positional writing/visual merge while preserving unflagged objects.
- Kept one explicit full fallback when no valid scene is derivable and retained the two-pass quality bound.
- Added pass/scope/target/rejection metadata alongside latency and existing token/cache totals on existing stages.
- Added focused parser and orchestration coverage, including the `N=8,k=1` five-call proof and controlled validation.

### File List

- `_bmad-output/implementation-artifacts/6-5-scenario-scoped-repair-retry.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `prompts/scenario/writing_scene_repair.md`
- `src/yt_flow/pipeline/nodes/scenario.py`
- `src/yt_flow/pipeline/nodes/scenario_chain.py`
- `tests/pipeline/nodes/test_scenario.py`
- `tests/pipeline/nodes/test_scenario_chain.py`

## Change Log

- 2026-07-11: Implemented scene-scoped scenario repair retry, bounded full fallback, trace metadata, candidate prompt seeding, and regression coverage. Status moved to review.
- 2026-07-11: Code review (bmad-code-review, joint with 6.6) complete — 5 findings fixed (scene_num-position mismatch guard in `_retry_scope`, `_format_scene_feedback` None-fallback bug, 3 missing AC9 tests: critic-only flags, second-failure-bounded scoped repair, scoped-repair trace/token coverage), 3 deferred (exhausted-repair-retry fallback gap, structure-vs-writing scene-count trace mismatch, malformed-source rejection recording), 12 dismissed as noise/false-positive/matches-existing-pattern. Full regression suite green (1232 passed, 1 skipped), ruff clean. Status → done.
- 2026-07-11: Post-hoc gap found while re-running the 6-3/6-4 promotion gate: `scenario/writing_scene_repair` had only ever been seeded under `candidate` (line 128 above), never `production`. Since `writing_scene_repair_step` fetches the prompt under whichever label the active run uses, any `production`-label run that hit the scene-repair path would have failed with a Langfuse 404 — a live gap in this already-`done` story, not just an eval artifact. Fixed by adding `production` to the existing version 1's labels via `Langfuse.update_prompt` (no content change, no new version — same content promoted, not edited).
