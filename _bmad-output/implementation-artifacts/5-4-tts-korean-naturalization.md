---
story_key: 5-4-tts-korean-naturalization
story_id: 5.4
epic: "Epic 5: Video Quality Improvements"
created: 2026-07-04
source_status_before: backlog
---

# Story 5.4: TTS Korean Naturalization

Status: ready-for-dev

## Story

As Jay,
I want scenario narration to be normalized for Korean speech synthesis before the TTS stage,
so that Qwen TTS reads Korean narration naturally without breaking subtitle sync or shot mapping.

## Context

The first live render review on 2026-07-03 (`run eb522cf9`, SCP-096) found Korean TTS misreadings caused by text phrasing, spacing, numbers, units, and abbreviation forms. This story fixes the text before it reaches `tts_node`.

The correct insertion point is the end of the `scenario` chain after review/critic acceptance and before `build_scenes()`. The normalized narration must become the single downstream `SceneState.narration` used by both `tts_node` and `subtitle_node`.

Do not implement a separate display subtitle text or a TTS-only text field. That would break the current `SceneState.narration -> TTS -> subtitle alignment` contract.

## Acceptance Criteria

1. Given scenario writing, visual breakdown, review, and critic have completed, when a new `tts_normalize` step runs, then every scene narration is rewritten into Korean speech-friendly text while preserving meaning, facts, tone, and scene order.
2. Given normalized narration is accepted, then TTS and subtitles use exactly the same text via `SceneState.narration`; there is no separate TTS-only or subtitle-only narration field.
3. Given a scene's normalized narration is returned, then its sentence count matches the original scene narration count as measured by the existing `split_sentences()` heuristic. If a scene would change sentence count, that scene keeps the original narration and logs/records a warning-quality signal; the whole scenario stage does not fail for this mismatch.
4. Given the normalizer prompt is added, then `prompts/scenario/tts_normalize.md` exists in the repo and Langfuse can serve it as `scenario/tts_normalize` under the existing prompt policy labels.
5. Given `prompt_variant="B"`, then the normalizer uses the existing Story 6.1 candidate-label fetch path just like the other scenario steps; candidate absence falls back to production through `get_prompt_with_fallback`.
6. Given DeepSeek or prompt fetch fails while running `tts_normalize`, then `scenario_node` follows the existing scenario error contract and returns `{"current_stage": "scenario", "error": "stage=scenario run_id=...: ..."}` instead of raising past the node.
7. Given tests run offline, then the new normalizer has cassette-shaped fixture coverage and unit tests for success, candidate-label propagation, sentence-count fallback, and scenario-node orchestration.

## Tasks / Subtasks

- [ ] Add the repository prompt file `prompts/scenario/tts_normalize.md`. (AC: 1, 4)
  - [ ] Define an input contract using `scenes: [{scene_num, narration}]`.
  - [ ] Define an output contract using the same structure, no extra prose, JSON object only.
  - [ ] Include Korean naturalization rules: disambiguate spacing/relations (`"한 연구원"` risk -> `"한 명의 연구원"` style rewrite), split long clauses with commas without adding sentence boundaries, expand numbers/units into Korean-readable forms, and spell English abbreviations phonetically where appropriate.
  - [ ] Explicitly forbid changing facts, scene order, scene count, sentence count, SCP terminology meaning, or horror register.
- [ ] Register the prompt name mapping in `scripts/migrate_prompts.py`. (AC: 4, 5)
  - [ ] Add `"scenario/tts_normalize.md": "scenario/tts_normalize"` to `SOURCE_TO_NAME`.
  - [ ] Do not create a new migration script; reuse `uv run python scripts/migrate_prompts.py --label candidate --source prompts/scenario` and the production-label flow from `docs/PROMPT_POLICY.md`.
- [ ] Add `tts_normalize_step()` to `src/yt_flow/pipeline/nodes/scenario_chain.py`. (AC: 1, 3, 5, 6)
  - [ ] Reuse `_call_stage("scenario/tts_normalize", ..., label=label)` so Story 6.1 label handling stays centralized.
  - [ ] Parse and validate a JSON object with non-empty `scenes`.
  - [ ] Match scenes positionally, not by LLM-provided `scene_num`, following the existing `build_scenes()` defensive pattern.
  - [ ] For each scene, compare `len(split_sentences(original))` with `len(split_sentences(normalized))`; if different, keep the original scene narration for that scene.
  - [ ] Return a full `writing`-shaped dict with only accepted `scene["narration"]` values changed. Preserve all other scene fields.
- [ ] Wire the step in `src/yt_flow/pipeline/nodes/scenario.py`. (AC: 1, 2, 5, 6)
  - [ ] Import `tts_normalize_step`.
  - [ ] Run it after the bounded review/critic retry has settled and before `build_scenes(writing, visual_by_scene)`.
  - [ ] Pass `label=label` to preserve variant B candidate behavior.
  - [ ] Append a `{"name": "tts_normalize", "latency_ms": ...}` entry to the existing `stages` trace metadata.
  - [ ] Do not add a new LangGraph stage, gate, API stage token, sidebar item, or `StageName` literal.
- [ ] Add fixture and tests. (AC: 3, 5, 6, 7)
  - [ ] Add `tests/fixtures/cassettes/deepseek_tts_normalize.json`.
  - [ ] Update `tests/fixtures/cassettes/README.md` to describe the new cassette.
  - [ ] Add `tests/pipeline/nodes/test_scenario_chain.py` coverage for normal output, invalid payload, candidate label propagation through `_call_stage`, positional scene matching, and sentence-count fallback.
  - [ ] Add `tests/pipeline/nodes/test_scenario.py` coverage proving `scenario_node` calls the normalizer after review/critic and before build output, including variant B label propagation.
- [ ] Verify the prompt policy flow. (AC: 4, 5)
  - [ ] Dry-run prompt discovery: `uv run python scripts/migrate_prompts.py --dry-run --source prompts/scenario`.
  - [ ] Seed candidate for testing: `uv run python scripts/migrate_prompts.py --label candidate --source prompts/scenario`.
  - [ ] Promote to production only after evaluation according to `docs/PROMPT_POLICY.md`.
- [ ] Run regression checks. (AC: 2, 6, 7)
  - [ ] `uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/test_prompt_migration.py -q`
  - [ ] Prefer full regression when time allows: `uv run pytest -q`.

## Dev Notes

### Source Documents

- Epic source: `_bmad-output/planning-artifacts/epics.md`, "Epic 5: 영상 품질 고도화" and "Story 5.4: TTS 한국어 자연화".
- PRD source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`, FR-4, FR-5, NFR-8, NFR-10.
- Architecture source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`, AD-1, AD-2, AD-4, AD-5, AD-6, AD-10, stack, graph structure, `PipelineState`.
- UX source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md`, artifact panel behavior for `scenario`, `tts`, and `subtitle`.
- Prompt policy source: `docs/PROMPT_POLICY.md`.
- Previous story intelligence: `_bmad-output/implementation-artifacts/5-3-motion-intensity.md` is a draft and mostly video-only. The more relevant completed predecessor is `_bmad-output/implementation-artifacts/6-1-prompt-policy-variant-label-wiring.md`.

No `project-context.md` file was found under the project root even though the workflow persistent-facts glob requested it.

### Architecture Guardrails

- Keep the dependency direction: `pipeline` may use `domain` and `services.prompt_service`; it must not import `api` or `db`.
- `PipelineState` remains the source of truth. The normalized narration must be stored by returning updated `scenes` from `scenario_node`, not by writing a side file or DB row.
- This is not a new pipeline stage in the LangGraph graph. The public stage order remains `scenario -> image -> tts -> subtitle -> video`.
- Do not update `StageName` in `src/yt_flow/domain/state.py`; `tts_normalize` is an internal scenario-chain substep, not a stage token.
- Do not modify `tts_node` to transform text. `tts_node` should continue to synthesize `scene["narration"]` and attach `audio_path`, `audio_duration`, and `word_timings`.
- Do not modify `subtitle_node` to compensate for separate text. It should continue aligning against the same `scene["narration"]`.
- Preserve the existing bounded review retry behavior. Normalization runs once after the retry decision, not inside every writing/review attempt.
- Langfuse tracing is best-effort and non-fatal. Prompt/DeepSeek failures are stage input failures and should surface through `PipelineState.error`.

### Existing Code To Read Before Implementing

- `src/yt_flow/pipeline/nodes/scenario_chain.py`
  - Current state: owns all scenario substeps, prompt fetch via `_call_stage`, `split_sentences()`, and `build_scenes()`.
  - Change needed: add `tts_normalize_step()` near the other step functions and reuse `_call_stage`.
  - Preserve: label behavior from Story 6.1, positional scene handling, `split_sentences()` heuristic, and no exception swallowing in the chain layer.
- `src/yt_flow/pipeline/nodes/scenario.py`
  - Current state: orchestrates research, structure, writing, visual breakdown, review, critic, one bounded retry, then `build_scenes()`.
  - Change needed: call `tts_normalize_step()` after the retry branch and before `build_scenes()`.
  - Preserve: `label = "candidate" if prompt_variant == "B" else None`, format-guide fallback behavior, `_record_trace()`, and `except Exception` conversion to `PipelineState.error`.
- `src/yt_flow/services/prompt_service.py`
  - Current state: `get_prompt_with_fallback()` catches `langfuse.api.NotFoundError`, logs fallback, and fetches production.
  - Change needed: none expected.
  - Preserve: do not bypass fallback by fetching Langfuse directly in the new step.
- `scripts/migrate_prompts.py`
  - Current state: maps known prompt source filenames to stable Langfuse names and supports `--label`.
  - Change needed: add the stable name mapping for `scenario/tts_normalize.md`.
  - Preserve: `--label` behavior; no new CLI flag.
- `tests/pipeline/nodes/test_scenario_chain.py` and `tests/pipeline/nodes/test_scenario.py`
  - Current state: established monkeypatch seams require label `None` to call `get_prompt` directly and label `"candidate"` to call `get_prompt_with_fallback`.
  - Change needed: additive tests only.
  - Preserve: existing tests should pass without changing their fixtures.

### Prompt Contract For `scenario/tts_normalize`

The prompt should instruct DeepSeek to return JSON in this shape:

```json
{
  "scenes": [
    {
      "scene_num": 1,
      "narration": "normalized Korean narration"
    }
  ]
}
```

Implementation should not trust `scene_num` for indexing. Use the returned list position and validate length against the input writing scenes.

Recommended prompt variables:

- `scenes_json`: JSON string of `[{scene_num, narration}]`.
- `format_guide`: existing scenario format guide, if useful.

Avoid sending shots, prompts, audio paths, or subtitles. The normalizer only needs narration text.

### Sentence Count Fallback

Use the existing `split_sentences()` function as the canonical count heuristic. It only splits on `.`, `?`, `!` followed by whitespace. That means Korean narration without those marks may count as one sentence; this is already the project heuristic and should not be replaced in this story.

Scene fallback should be per-scene:

- If the normalized scene count list length is wrong, raise `ValueError`; that is malformed output.
- If one scene has changed sentence count, keep that original scene narration and continue with other accepted scenes.
- Record enough signal to debug the fallback. A `logger.warning(...)` in `scenario_chain.py` is sufficient; if trace metadata is easy, include a count in the `tts_normalize` stage metadata, but do not overbuild.

### Previous Story Intelligence

Story 6.1 is the critical predecessor:

- Variant B now means `label="candidate"` for scenario prompts.
- `label=None` must keep calling `get_prompt` directly because existing tests monkeypatch that seam.
- `get_prompt_with_fallback()` is the only place to implement candidate-missing fallback; do not duplicate fallback logic in the normalizer.
- `scripts/migrate_prompts.py --label` already exists.
- Langfuse protected labels are unavailable on the current OSS self-host instance; policy is enforced through `docs/PROMPT_POLICY.md`.

Recent git commits confirm this:

- `13640bc` wired prompt A/B variant B to the candidate label with production fallback.
- `8946828` added prompt policy documentation and updated the Story 6.1 record.

### Latest Technical Notes

- Qwen-TTS non-real-time API documentation, last updated 2026-06-22, still describes request input as `model` plus `input.text` and `input.voice`, with non-streaming responses providing an audio URL. This story should not change the Qwen client call shape.
- Qwen-TTS documentation says explicit `language_type` can improve pronunciation for single-language text, with `Korean` listed. The current code does not send `language_type`; this story focuses on upstream text naturalization. Add a follow-up only if live A/B shows text normalization is insufficient.
- Langfuse prompt versioning uses labels such as `production`, and protected prompt labels require paid/enterprise tiers for self-hosted environments. This matches the local Story 6.1 finding that protected labels are unavailable on the current OSS instance.

References:

- Qwen-TTS API reference: https://www.alibabacloud.com/help/en/model-studio/qwen-tts-api
- Langfuse prompt versioning/protected labels: https://langfuse.com/docs/prompt-management/features/prompt-version-control
- Langfuse prompt management concepts: https://langfuse.com/docs/prompt-management/data-model

### Testing Guidance

- Test `tts_normalize_step()` at the chain level first. It should be a pure async function driven by fake prompt fetch and fake DeepSeek response, consistent with existing scenario-chain tests.
- Include one response that changes `"한 연구원"` into a clearer spoken form without changing sentence count.
- Include one response that adds or removes a sentence boundary and verify only that scene falls back to original narration.
- Include one malformed response to prove a bad top-level shape fails loudly.
- Test scenario orchestration with stubbed chain functions so failures point to sequencing, not DeepSeek JSON details.
- Do not add live network tests. Existing external API strategy uses cassette-shaped fixtures and monkeypatches.

## Project Structure Notes

Expected file changes:

- `prompts/scenario/tts_normalize.md` (new)
- `scripts/migrate_prompts.py` (update mapping)
- `src/yt_flow/pipeline/nodes/scenario_chain.py` (update)
- `src/yt_flow/pipeline/nodes/scenario.py` (update)
- `tests/fixtures/cassettes/deepseek_tts_normalize.json` (new)
- `tests/fixtures/cassettes/README.md` (update)
- `tests/pipeline/nodes/test_scenario_chain.py` (update)
- `tests/pipeline/nodes/test_scenario.py` (update)

Files that should not need changes:

- `src/yt_flow/domain/state.py`
- `src/yt_flow/pipeline/graph.py`
- `src/yt_flow/pipeline/nodes/tts.py`
- `src/yt_flow/pipeline/nodes/subtitle.py`
- Frontend files and stage navigation UI

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

- Story context generated by BMad create-story workflow on 2026-07-04.
- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List
