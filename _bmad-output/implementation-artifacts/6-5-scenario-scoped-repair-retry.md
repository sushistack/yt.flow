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
---

# Story 6.5: Scene-Scoped Scenario Repair Retry

Status: ready-for-dev

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

- [ ] Task 1: Extract pure retry-scope helpers from review/critic output (AC: 1, 5)
  - [ ] Return positional indexes and rejected identifiers/reasons without mutating model output.
  - [ ] Keep `_format_feedback` for full fallback; add scene-scoped feedback formatting.
- [ ] Task 2: Add `writing_scene_repair_step` and prompt (AC: 2, 8)
  - [ ] Reuse `_call_stage_with_retry`, YAML parsing, usage sink, prompt label fallback, and freetext normalization.
  - [ ] Validate exact requested-scene coverage before merging.
- [ ] Task 3: Split `_write_and_review` into reusable initial-pass and scoped-repair seams (AC: 3-6)
  - [ ] Do not add a LangGraph node, DB state, service, or dependency.
  - [ ] Preserve `build_scenes` positional contracts and existing normal-path output.
- [ ] Task 4: Extend trace metadata without adding spans (AC: 7)
- [ ] Task 5: Add focused orchestration/parser/prompt tests (AC: 9)
- [ ] Task 6: Seed candidate and perform one cost-bounded validation (AC: 8, 10)

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

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List
