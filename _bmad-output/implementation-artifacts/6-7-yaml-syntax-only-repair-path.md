---
created: 2026-07-11
baseline_commit: 1847ab4d364e60fd6746926c3dea4f25cf1792ee
story_key: 6-7-yaml-syntax-only-repair-path
story_id: "6.7"
epic: 6
previous_story: 6-6-tiered-prompt-evaluation-gates
depends_on:
  - 6-4-scenario-yaml-output-bounded-retry   # owns _call_stage_with_retry, _parse_yaml, _normalize_freetext this story extends
  - 6-6-tiered-prompt-evaluation-gates       # owns the --profile promotion gate this story's fix must pass before 6-3/6-4 can promote
related:
  - 6-3-prompt-cache-hit-optimization        # blocked promotion this story unblocks
  - 6-8-golden-set-judge-multi-sample        # sibling finding from the same 2026-07-11 gate rerun
evidence: "2026-07-11 live rerun of the 6-3/6-4 promotion gate (post-6.6 timeout fix): SCP-173's candidate run failed with yaml.YAMLError ('mapping values are not allowed here', a plain-scalar value containing an unescaped colon) that survived _call_stage_with_retry's bounded single retry and propagated as a run failure. Root cause traced statically (no further live calls): review.md's issues[].description/correction and corrections[].original/corrected, and critic_agent.md's scene_notes[].issue/suggestion, are free-text fields never added to Story 6.4's AC2 block-literal (|) list — they remain plain YAML scalars in both templates' schema examples, so any embedded colon in model-generated text breaks yaml.safe_load. Separately, _call_stage_with_retry (scenario_chain.py:265-299) catches (yaml.YAMLError, ValueError) identically and retries by re-running the entire stage prompt from scratch (e.g. visual_breakdown alone is 43k-89k tokens per the 6-3 Dev Agent Record's cache table) regardless of whether the failure was a pure syntax mistake or an actual content/schema problem. See _bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md#2026-07-11-full-3-item-promotion-re-attempt-post-66 and 6-4-scenario-yaml-output-bounded-retry.md for the full incident."
---

# Story 6.7: YAML Syntax-Only Repair Path

Status: done

## Story

As Jay,
I want scenario-stage output failures split by cause — a pure YAML syntax break gets a small, targeted repair call instead of a full stage regeneration — and the remaining free-text fields that can still break YAML parsing wrapped in block-literal style,
so that a single stray colon in a judge/critic free-text field stops being able to exhaust the entire bounded-retry budget and fail a whole `scenario_node` run.

## Context

Story 6.6 raised the eval item timeout 600s→1200s specifically to unblock the 6-3/6-4 promotion gate, which had been failing only on infra timeouts. Re-running `scripts/eval_prompts.py --profile promotion` live twice after that fix confirmed the timeout is gone, but the gate still fails — on content grounds this time. SCP-173's `candidate` run hit:

```
mapping values are not allowed here
  in "<unicode string>", line 117, column 25:
        content: Peak horror: a single involuntary reflex en ...
                            ^
```

This is a classic YAML plain-scalar problem: a value like `Peak horror: a single involuntary reflex...` contains its own `: ` sequence, which YAML's plain (unquoted) scalar grammar interprets as an attempt to open a nested mapping. Story 6.4 solved exactly this class of problem for the fields it enumerated in AC2 (`narration`, `image_prompt`, `negative_prompt`, `core_identity`, `frozen_descriptor`, `entity_sheet`, `story_logline`, `hooks`, `feedback`) by instructing the model to emit them as YAML block-literal (`|`) scalars, which take raw text verbatim with no colon/quote/escaping hazard. But two templates still have free-text fields left as plain scalars in their schema examples:

- `prompts/scenario/review.md`: `issues[].description`, `issues[].correction`, `corrections[].original`, `corrections[].corrected`, `storytelling_issues[].description`, `storytelling_issues[].correction`
- `prompts/scenario/critic_agent.md`: `scene_notes[].issue`, `scene_notes[].suggestion`

None of these are validated or normalized by `review_step`'s or `critic_step`'s `parse()` closures either (`scenario_chain.py:671-675`, `708-714` only check `overall_pass`/`verdict`), so nothing currently protects them.

Separately — and independently of which field caused this specific incident — `_call_stage_with_retry` (`scenario_chain.py:265-299`) treats every parse/validate failure the same way regardless of cause: it catches `(yaml.YAMLError, ValueError)` in one `except` clause and retries by re-rendering and re-calling the **entire** stage prompt from scratch, once. For a stage like `visual_breakdown` (43k-89k tokens per call, per the 6-3 Dev Agent Record's live cache-comparison table), asking the model to redo the *whole* generation just to fix a stray colon in one nested field is both expensive and imprecise — the retry has to get the entire complex output right a second time, not just the syntax. A `ValueError` (schema violation — wrong shape, missing field, sentence-coverage mismatch) genuinely may need new content and justifies a full regeneration; a `yaml.YAMLError` (the model's own text broke the serialization, content was probably fine) does not.

This story does two things: (1) finish the block-literal conversion Story 6.4 started, for the fields it missed; (2) split the retry path so a pure `yaml.YAMLError` gets a narrow, cheap "fix only the syntax, keep the content" repair call instead of a full stage regeneration, while `ValueError` keeps the existing full-regeneration retry.

## Acceptance Criteria

1. **Given** `prompts/scenario/review.md`'s schema example, **Then** `issues[].description`, `issues[].correction`, `corrections[].original`, `corrections[].corrected`, `storytelling_issues[].description`, and `storytelling_issues[].correction` are shown as YAML block-literal (`|`) scalars, matching the existing convention for every other free-text field in this template family. No change to the underlying schema (field names/types/nesting) — only the serialization example and instruction text.
2. **Given** `prompts/scenario/critic_agent.md`'s schema example, **Then** `scene_notes[].issue` and `scene_notes[].suggestion` are shown as block-literal (`|`) scalars, same rule as AC1.
3. **Given** `scenario_chain.py`'s `_normalize_freetext` usage, **Then** `review_step`'s and `critic_step`'s `parse()` closures apply `_normalize_freetext` to the AC1/AC2 fields wherever present (degrading a missing/non-string field to leaving it absent, not raising — this story does not add new validation strictness, only normalization, consistent with AD-10 and the existing `feedback`/`narration` precedent at `scenario_chain.py:710-711`).
4. **Given** `_call_stage_with_retry`'s exception handling (`scenario_chain.py:284-298`), **Then** the single `except (yaml.YAMLError, ValueError)` clause is split: a `yaml.YAMLError` routes to a new syntax-only repair call; a `ValueError` keeps today's exact behavior (re-render and re-call the full stage prompt once, `parse_error` populated). Both remain bounded to exactly one extra attempt — a second failure of either kind propagates unchanged, same as today.
5. **Given** the new syntax-only repair path, **Then** it is a small, dedicated call (new Langfuse prompt `scenario/yaml_syntax_repair` or equivalent, seeded via `scripts/migrate_prompts.py`) whose input is the failing stage's raw broken output text plus the `yaml.YAMLError`'s message (including its line/column detail), and whose instruction is to return corrected YAML with the **same semantic content**, fixing only the syntax — not to regenerate content from the original stage inputs. It does not receive the original stage's full variables (fact sheet, format guide, etc.) — only the broken text and the error.
6. **Given** the new prompt, **Then** it follows `docs/PROMPT_POLICY.md`'s unchanged change protocol (candidate → `--profile smoke`/`--profile promotion` gate → promote). This story does not modify the policy document itself.
7. **Given** a stage whose syntax-repair attempt itself raises `yaml.YAMLError` or fails the original `parse()` validation, **Then** the exception propagates unchanged (bounded — no third attempt, no fallback to the old full-regeneration retry after syntax-repair has already been tried).
8. **Given** tests, **Then** they cover: a `yaml.YAMLError` from any of the 8 `*_step` functions' `parse()` routing to the syntax-repair path (not the full-regeneration path); a `ValueError` continuing to route to the existing full-regeneration path; the syntax-repair path succeeding on its one attempt; the syntax-repair path itself failing and propagating; and `_normalize_freetext` being applied to the AC1/AC2 fields when present in `review_step`/`critic_step` output.

## Tasks / Subtasks

- [x] Task 1: Convert `review.md`'s remaining plain-scalar free-text fields to block-literal (`|`) examples; update surrounding instruction prose if it references the old style. (AC:1)
- [x] Task 2: Convert `critic_agent.md`'s `scene_notes[].issue`/`suggestion` the same way. (AC:2)
- [x] Task 3: Extend `review_step`'s and `critic_step`'s `parse()` closures to apply `_normalize_freetext` to the AC1/AC2 fields. (AC:3)
- [x] Task 4: Add a new `scenario/yaml_syntax_repair` prompt template (small — broken text + error in, corrected YAML out) and seed it under `candidate` via `scripts/migrate_prompts.py`. (AC:5, 6)
- [x] Task 5: Split `_call_stage_with_retry`'s except clause — `yaml.YAMLError` calls the new syntax-repair path; `ValueError` keeps the existing full-regeneration retry. Both bounded to one attempt; a syntax-repair failure does not fall back to full regeneration (AC7). (AC:4, 7)
- [x] Task 6: Unit tests for the routing split, the syntax-repair path's success/failure, and the AC3 normalization. (AC:8)
- [x] Task 7: Run `--profile smoke`, then `--profile promotion` once fixes land; record the result in this story's Dev Agent Record. Do not promote to `production` until it passes — this story does not change the gate's pass criteria (that is Story 6.8's scope, if pursued).

## Dev Notes

### Source Context

- Epic 6 goal: prompt lifecycle versioned + labeled + eval-gated using Langfuse's native features only. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 6: Prompt Ops — 프롬프트 버저닝·평가 정책`]
- This story's own epics.md entry has the same root-cause breakdown. [Source: `_bmad-output/planning-artifacts/epics.md#Story 6.7: YAML 문법 전용 경량 repair 경로 분리`]
- The incident that surfaced this: [Source: `_bmad-output/implementation-artifacts/6-3-6-4-review-metrics-report.md#2026-07-11 full 3-item promotion re-attempt (post-6.6)`]
- Story 6.4's original design and its AC2 field list (the list this story finishes): [Source: `_bmad-output/implementation-artifacts/6-4-scenario-yaml-output-bounded-retry.md`]

### Existing Code To Reuse / Modify

- `_call_stage_with_retry` (`scenario_chain.py:265-299`) is the single choke point for every stage's bounded retry — extend its except-handling here, do not duplicate the retry loop elsewhere.
- `_parse_yaml` (`scenario_chain.py:229-243`) and `_normalize_freetext` (`scenario_chain.py:251-263`) are the existing YAML-parsing and whitespace-normalization helpers this story reuses unchanged.
- `review_step` (`scenario_chain.py:659-693`) and `critic_step` (`scenario_chain.py:696-727`) are the two `parse()` closures this story extends with AC1-3's field normalization — do not touch their existing `overall_pass`/`verdict` validation.
- `scripts/migrate_prompts.py`'s `SOURCE_TO_NAME` mapping needs a new entry for the AC5 prompt if its filename doesn't already match the derived-name convention (`scenario/<filename-without-suffix>`).
- The new syntax-repair call should reuse `_call_stage` (`scenario_chain.py:203-220`) directly (fetch/compile/call), not `_call_stage_with_retry` — it is itself the one-shot repair attempt inside the existing bounded-retry budget, not a new nested retry loop.

### Why Not Just Widen the Existing Retry Instead

A simpler alternative — just bump `_call_stage_with_retry`'s bound from one retry to two — was considered and rejected here as the primary fix: it doesn't address the actual inefficiency (a 500-token syntax mistake still forces regenerating an 80k-token stage from scratch), and it doesn't reduce the *rate* of hitting `yaml.YAMLError` in the first place the way finishing the block-literal conversion (AC1/AC2) does. If this story's fix still leaves live `yaml.YAMLError` failures after both AC1/AC2 (fewer colons reaching the parser) and AC4/AC5 (cheaper, more targeted repair when one does), *then* widening the bound is a reasonable, much smaller follow-up — not a replacement for this story.

### Out Of Scope

- Changing `docs/PROMPT_POLICY.md`'s promotion criteria or gate script's pass/fail logic — that is Story 6.8's territory (judge-scoring noise), a different axis of the same incident.
- A general Pydantic-schema-repair or multi-pass validation pipeline — Story 6.4 already considered and rejected this as premature (YAGNI); this story's syntax-only repair is narrower and reuses the existing bounded-retry philosophy, not a new heavier mechanism.
- Re-running the full 6-3/6-4 promotion gate as *this* story's completion criterion — Task 7 runs it once as evidence, but 6-3/6-4 themselves are separate story files with their own Task 8/status.

### Project Structure Notes

- Modify: `prompts/scenario/review.md`, `prompts/scenario/critic_agent.md`, `src/yt_flow/pipeline/nodes/scenario_chain.py` (`_call_stage_with_retry`, `review_step`, `critic_step`).
- New file: `prompts/scenario/yaml_syntax_repair.md` (or similar name — AC5).
- No new Settings fields, no new dependency.

### References

- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L203-L299] — `_call_stage`, `_parse_yaml`, `_normalize_freetext`, `_call_stage_with_retry`
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#L659-L727] — `review_step`, `critic_step`
- [Source: prompts/scenario/review.md] — schema fields needing block-literal conversion
- [Source: prompts/scenario/critic_agent.md] — schema fields needing block-literal conversion
- [Source: _bmad-output/implementation-artifacts/6-4-scenario-yaml-output-bounded-retry.md] — original YAML/bounded-retry design this story extends
- [Source: docs/PROMPT_POLICY.md] — unchanged change protocol this story's new prompt must follow

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- RED: targeted routing/normalization tests initially failed 3 cases as expected.
- GREEN: `uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/test_prompt_migration.py -q` — 210 passed.
- Regression: `uv run pytest -q` — 1235 passed, 1 skipped, 1 warning.
- Quality: `uv run ruff check src/yt_flow/pipeline/nodes/scenario_chain.py tests/pipeline/nodes/test_scenario_chain.py scripts/migrate_prompts.py` — passed.
- Candidate seed: `scenario/review`, `scenario/critic_agent`, and `scenario/yaml_syntax_repair` created under `candidate`.
- Smoke: failed at `scenario/review` due to the known default 8192-token truncation; artifact `tmp/eval-prompts/20260711-161020-1783753820327222459-candidate/candidate-SCP-049-full.json`.
- Review regression: `uv run pytest -q` — 1243 passed, 1 skipped, 1 warning; focused review suite — 257 passed; Ruff clean.
- Review smoke (`YTFLOW_DEEPSEEK_MAX_TOKENS=16000`): SCP-049 completed, atmosphere 4.33 / narrative_coherence 5.00 / article_fidelity 2.33, total 11.67. Health feedback only.
- Review promotion: FAIL. SCP-049 candidate `scenario/writing_scene_repair` truncated even at 16000 tokens; SCP-173 regressed atmosphere -0.33 and narrative_coherence -0.33; SCP-096 regressed article_fidelity -0.33. Artifact: `tmp/eval-prompts/20260711-164208-1783755728393879121-candidate-production/`. `production` was not promoted.

### Completion Notes List

- Converted all specified review/critic free-text schema examples to YAML block literals and normalized their parsed string values without adding validation strictness.
- Split bounded retry routing: `yaml.YAMLError` gets one syntax-only repair call with only broken YAML + parser error; `ValueError` retains one full-stage regeneration.
- Added bounded success/failure, routing, usage, and nested normalization coverage; full regression suite is green.
- Code review fixed the production-baseline dependency on the not-yet-promoted repair prompt by preserving the old full-stage retry until the repair prompt has a production label; the live promotion run exercised this fallback three times successfully.
- Smoke and promotion were executed during review. The implementation review is complete, but the unrelated/generative gate failures still block moving the changed prompts to `production`.

### File List

- `_bmad-output/implementation-artifacts/6-7-yaml-syntax-only-repair-path.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `prompts/scenario/critic_agent.md`
- `prompts/scenario/review.md`
- `prompts/scenario/yaml_syntax_repair.md`
- `src/yt_flow/pipeline/nodes/scenario_chain.py`
- `tests/pipeline/nodes/test_scenario_chain.py`

## Change Log

### Review Findings

- [x] [Review][Patch] Preserve the production baseline when the candidate-only repair prompt is not yet promoted [`src/yt_flow/pipeline/nodes/scenario_chain.py`] — fixed with an explicit prompt-fetch fallback to the prior full-stage retry; a missing candidate seed still fails loudly.

- 2026-07-11: Story created from a live finding during the 6-3/6-4 promotion gate re-attempt (SCP-173 YAML crash surviving bounded retry). Status: backlog.
- 2026-07-11: Implemented YAML syntax-only repair routing, block-literal prompt hardening, normalization, and tests. Moved to review with the authority promotion gate explicitly deferred to review by Jay.
- 2026-07-11: Code review completed; 1 patch applied, full regression green, smoke completed, promotion gate FAIL recorded, production unchanged. Status: done.
