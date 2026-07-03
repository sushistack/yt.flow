---
created: 2026-07-04
story_key: 5-5-visual-story-alignment
story_id: "5.5"
epic: 5
previous_story: 5-4-tts-korean-naturalization
depends_on:
  - 6-1-prompt-policy-variant-label-wiring
  - 5-2-layered-assets-activation
  - 5-3-motion-intensity
---

# Story 5.5: Visual Story Alignment - visual_breakdown Context + SCP Reference Image Option

Status: ready-for-dev

## Story

As Jay,  
I want generated images to depict the actual story beats and SCP entity being narrated,  
so that the final video feels like a coherent SCP story rather than generic horror imagery.

## Context

The 2026-07-03 live render review for `run eb522cf9 / SCP-096` found that generated images did not match the narration. The likely root cause is that `scenario/visual_breakdown` currently receives mostly scene-local fields plus `frozen_descriptor`; it does not receive a strong story-level logline, scene narrative role, or a reusable entity sheet that defines the target SCP consistently for every shot.

This story implements Phase 1 first: strengthen the scenario prompt/data contract so image prompts carry story-level and entity-level context. Phase 2 is conditional: if Phase 1 still fails A/B evaluation, add SCP Wiki official images as IPAdapter references with attribution metadata. General web-search image + LoRA/img2img remains deferred because copyright control, style consistency, and result quality are not reliable enough for YouTube monetization. [Source: `_bmad-output/implementation-artifacts/deferred-work.md#Deferred from: 첫 실전 렌더 품질 리뷰 (2026-07-03)`]

## Acceptance Criteria

### Phase 1 - Prompt Context Strengthening

1. Given the `scenario/research` prompt, when it produces the research packet, then it includes a non-empty `entity_sheet` suitable for repeated use in every shot prompt, derived only from the SCP source text and formatted as a stable visual definition.
2. Given the `scenario/structure` output, when `visual_breakdown_step` runs for a scene, then the step receives the story logline or equivalent global narrative premise plus that scene's narrative role or beat.
3. Given each `scenario/visual_breakdown` call, then the rendered prompt includes: story logline/global premise, scene role/beat, scene location/atmosphere/palette, `entity_sheet`, `frozen_descriptor`, and numbered narration sentences.
4. Given each generated shot prompt, then the prompt explicitly includes shot composition/camera framing (`wide`, `medium`, `close-up`, `POV`, or equivalent) and repeats the same entity visual phrase when the SCP should be visible.
5. Existing contracts stay intact: `visual_breakdown_step` still rejects sentence/shot count mismatches, empty `image_prompt` transition markers still merge/backfill in `build_scenes`, `ShotData` remains the image-generation unit, and `image_node` still consumes `ShotData.image_prompt`/`negative_prompt` without knowing prompt-internal fields.
6. Given `prompt_variant="B"`, then the new or updated scenario prompts are fetched with `label="candidate"` through the Story 6.1 path; Variant A/None continues production lookup unchanged.
7. Given candidate labels are missing for unrelated prompts, then production fallback remains allowed and logged by `prompt_service.get_prompt_with_fallback`; the story must not make fallback silent.
8. Given the prompt changes, then in-repo prompt source files exist under `prompts/scenario/` for every runtime prompt changed or introduced, and the developer documents the exact `scripts/migrate_prompts.py --label candidate --source ...` command used or required.

### Phase 2 - Conditional SCP Wiki Reference Image / IPAdapter

9. Given Phase 1 A/B results are insufficient, when the target SCP has an official SCP Wiki image with usable licensing, then the image can be downloaded or referenced as an IPAdapter conditioning input in a ComfyUI workflow variant.
10. Given no official image exists, download fails, or licensing cannot be verified, then the run falls back to Phase 1 prompts only and does not fail the pipeline.
11. Given a reference image is used, then run metadata records enough attribution data for the video description: source URL, page URL, license URL/name, author/attribution when available, and whether the image was transformed.
12. Given Phase 2 touches ComfyUI workflow configuration, then it must not regress existing `YTFLOW_COMFYUI_LAYERED`, `YTFLOW_COMFYUI_BACKGROUND_NODE`, `YTFLOW_COMFYUI_CHARACTER_NODE`, mock mode, or Story 5.2 layered-workflow activation.

### Validation - Epic 4 A/B

13. Given Phase 1 is implemented and seeded under `candidate`, when an A/B run is executed for the same SCP input, then Variant B must materially improve visual-story alignment by Epic 4 evaluation plus Jay's gate review.
14. Given Phase 2 is implemented, then it is validated by a second A/B or a documented before/after run showing improved SCP entity recognizability without breaking style consistency or attribution obligations.
15. Completion requires a recorded validation note in this story's Dev Agent Record. If live A/B cannot be run in-session, the dev must leave exact manual commands/API calls and mark the remaining validation gap honestly.

## Tasks / Subtasks

- [ ] Update scenario prompt source of truth under `prompts/scenario/` (AC: 1, 3, 4, 8)
  - [ ] Add or update `prompts/scenario/research.md` to emit `entity_sheet` alongside the existing `frozen_descriptor`.
  - [ ] Add in-repo prompt sources for missing runtime prompts before changing them, especially `prompts/scenario/visual_breakdown.md`; do not make Langfuse-only prompt edits.
  - [ ] Ensure `visual_breakdown` prompt asks for structured composition/camera framing while preserving the existing JSON shape expected by tests.
- [ ] Update `src/yt_flow/pipeline/nodes/scenario_chain.py` (AC: 1-7)
  - [ ] Validate `research["entity_sheet"]` as non-empty if the prompt contract adds it.
  - [ ] Thread global premise/logline and per-scene role from `research`/`structure`/`writing` into `visual_breakdown_step`.
  - [ ] Keep `label: str | None = None` keyword-only plumbing exactly compatible with Story 6.1.
  - [ ] Keep sentence-count validation and `finish_reason == "length"` truncation errors.
- [ ] Update `src/yt_flow/pipeline/nodes/scenario.py` only if orchestration needs extra state passed into `_write_and_review` (AC: 2, 6)
  - [ ] Preserve the current `label = "candidate" if state.get("prompt_variant") == "B" else None` behavior.
  - [ ] Preserve bounded retry: one retry max if review/critic requests it.
- [ ] Update tests and cassettes (AC: 1-8)
  - [ ] Add `entity_sheet` to the relevant DeepSeek cassette(s), especially `tests/fixtures/cassettes/deepseek_research.json`.
  - [ ] Add unit coverage proving `visual_breakdown_step` receives story/global and scene-role variables.
  - [ ] Add regression coverage proving Variant A/None still uses production lookup and Variant B still uses candidate lookup.
  - [ ] Run at minimum: `uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/test_prompt_service.py -q`.
- [ ] Seed prompt candidate labels (AC: 6, 8, 13)
  - [ ] Use `uv run python scripts/migrate_prompts.py --label candidate --source prompts/scenario`.
  - [ ] Record whether each changed prompt was created/skipped and whether any candidate fallback warnings appeared during test/live runs.
- [ ] Validate Phase 1 with A/B (AC: 13, 15)
  - [ ] Run or document `POST /runs/{id}/ab` for the same SCP input after Variant A is available.
  - [ ] Run Epic 4 evaluation and record visual alignment outcome in Dev Agent Record.
- [ ] Conditional Phase 2 only after Phase 1 evidence (AC: 9-12, 14)
  - [ ] Reuse existing character/reference infrastructure before adding a new fetcher.
  - [ ] Add ComfyUI workflow/config support for an IPAdapter reference only if the existing workflow path and Story 5.2 layered workflow can remain intact.
  - [ ] Persist attribution metadata where downstream video description tooling can read it.

## Dev Notes

### Critical Implementation Guardrails

- Do not bypass `docs/PROMPT_POLICY.md`: the repo prompt file is the source of truth, Langfuse serves labels and versions only. `production` protected labels are not available on the current self-hosted OSS instance; enforcement is policy-based. [Source: `docs/PROMPT_POLICY.md`; Langfuse protected-label availability: https://langfuse.com/changelog/2025-04-02-protected-prompt-labels]
- Do not reimplement A/B prompt routing. Story 6.1 already added `get_prompt_with_fallback`, candidate label lookup, production fallback logging, and scenario-chain label plumbing. Reuse it exactly. [Source: `_bmad-output/implementation-artifacts/6-1-prompt-policy-variant-label-wiring.md`; `src/yt_flow/services/prompt_service.py`; `src/yt_flow/pipeline/nodes/scenario.py`; `src/yt_flow/pipeline/nodes/scenario_chain.py`]
- Keep `image_node` ignorant of visual prompt internals. This story should improve the prompt content that becomes `ShotData.image_prompt`; it should not force `image_node` to understand `entity_sheet`, scene role, or story logline. [Source: `src/yt_flow/pipeline/nodes/image.py`]
- Avoid adding a new pipeline stage. PRD explicitly excludes new pipeline stages beyond `scenario -> image -> tts -> subtitle -> video`; prompt/context work belongs inside `scenario`. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Out of Scope`]
- Be careful with token growth. The existing chain raises on `finish_reason == "length"` and the draft noted real `visual_breakdown` truncation at 8192 tokens. Prefer compact `entity_sheet` and scene-role strings over dumping large research packets into every scene call. [Source: current draft; `src/yt_flow/pipeline/nodes/scenario_chain.py`]

### Current Code State - Files To Read Before Editing

- `src/yt_flow/pipeline/nodes/scenario_chain.py`
  - Current state: `_call_stage()` fetches Langfuse prompts, compiles variables, calls DeepSeek, and rejects truncated responses. `research_step()` validates `frozen_descriptor`. `visual_breakdown_step()` receives scene-local fields, `frozen_descriptor`, narration, numbered sentences, and `label`; it enforces one visual description per sentence. `build_scenes()` merges empty image prompts into previous shots or backfills a leading transition prompt.
  - This story changes: add/validate `entity_sheet`; thread global story context and scene role into `visual_breakdown_step` variables; update tests/cassettes.
  - Preserve: keyword-only `label`, production lookup seam when label is `None`, candidate fallback only when label is set, sentence-count mismatch error, empty-prompt merge/backfill behavior.
- `src/yt_flow/pipeline/nodes/scenario.py`
  - Current state: orchestrates research -> structure -> writing -> visual_breakdown per scene -> review -> critic, with one bounded retry. Computes `label="candidate"` only for Variant B and passes it to all chain calls.
  - This story changes: likely only `_write_and_review()` argument flow if `visual_breakdown_step` needs `research`/`structure` context beyond `frozen_descriptor`.
  - Preserve: no DB/SSE side effects, `PipelineState.error` formatting, one retry max, label behavior for A/None/B.
- `prompts/scenario/research.md`
  - Current state: in-repo prompt source asks for `core_identity`, `frozen_descriptor`, `dramatic_beats`, `environment`, and `hooks`.
  - This story changes: include `entity_sheet` and possibly a compact story premise/logline field.
  - Preserve: all fields non-empty; `frozen_descriptor` remains the existing visual source for later prompts.
- `prompts/scenario/visual_breakdown.md`
  - Current state: missing from repo even though runtime fetches `scenario/visual_breakdown` from Langfuse. This is a source-of-truth gap under the prompt policy.
  - This story changes: create the in-repo source before seeding candidate, using the runtime JSON contract in tests/cassettes.
- `tests/pipeline/nodes/test_scenario_chain.py`
  - Current state: covers prompt fetch seams, research validation, visual sentence-count validation, empty prompt merging, and Variant B candidate lookup through `_call_stage`.
  - This story changes: add `entity_sheet` validation and variable-threading assertions without weakening existing tests.

### Architecture Compliance

- Architecture AD-5 says `ShotData` is the image-generation unit and sentence mapping is N:M at the state level. Current code still enforces 1:1 visual descriptions per sentence then merges empty prompts; this story must preserve that local contract unless a separate timing-model story changes it. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-5`]
- Architecture AD-6 says A/B is two independent runs linked by `ab_pair_id`; do not add graph branching for visual alignment. [Source: architecture spine AD-6]
- Architecture AD-10 says Langfuse tracing failures are non-fatal, but prompt fetch failures are required input failures. Preserve current prompt-service error behavior. [Source: architecture spine AD-10; `src/yt_flow/services/prompt_service.py`]
- Config belongs in `src/yt_flow/config.py` with `YTFLOW_` prefix. If Phase 2 needs IPAdapter workflow paths or attribution toggles, add settings there rather than hardcoding.

### Previous Story Intelligence

- Story 5.4 is still a draft story, not an implemented precedent. It warns that narration text and downstream mappings must not diverge, and that sentence count must remain stable to protect visual breakdown mapping. This story should not alter sentence splitting or narration normalization behavior. [Source: `_bmad-output/implementation-artifacts/5-4-tts-korean-naturalization.md`]
- Story 6.1 is implemented/review and directly relevant. Its key implementation lesson: when `label=None`, tests depend on calling `prompt_service.get_prompt` directly; when `label="candidate"`, use `get_prompt_with_fallback`. Do not collapse those paths. [Source: `_bmad-output/implementation-artifacts/6-1-prompt-policy-variant-label-wiring.md`]
- Recent commits show the prompt A/B wiring was just added in `src/yt_flow/pipeline/nodes/scenario.py`, `src/yt_flow/pipeline/nodes/scenario_chain.py`, `src/yt_flow/services/prompt_service.py`, and related tests. Expect local code to already include that work. [Source: `git log --oneline -5`; commit `13640bc`]

### Phase 2 Technical Notes

- IPAdapter is a reference-image conditioning approach often used like a one-image LoRA for transferring subject/style from a reference image. If used, prefer an explicit ComfyUI workflow variant over ad hoc runtime graph mutation. [Source: https://github.com/cubiq/ComfyUI_IPAdapter_plus]
- SCP content is generally CC BY-SA; derivative use requires attribution and ShareAlike handling. The story must store attribution metadata when a wiki image is used, and must not silently use arbitrary search images. [Source: https://scp-wiki.wikidot.com/licensing-guide; https://creativecommons.org/licenses/by-sa/3.0/deed.en]
- Some SCP pages/images have special exceptions; verify per-image licensing before use. SCP-173 is especially called out by SCP licensing materials as a special case, so do not generalize from one page to all SCPs. [Source: SCP licensing guide]

### Testing Requirements

- Unit tests should run offline with fake prompts/DeepSeek cassettes, matching current test style.
- Required focused tests:
  - `uv run pytest tests/pipeline/nodes/test_scenario_chain.py -q`
  - `uv run pytest tests/pipeline/nodes/test_scenario.py -q`
  - `uv run pytest tests/test_prompt_service.py -q`
- Recommended if code touches config/image Phase 2:
  - `uv run pytest tests/pipeline/nodes/test_image.py tests/test_config.py -q`
- Full regression recommended after prompt contract changes:
  - `uv run pytest -q`

## Project Structure Notes

- Expected modified files:
  - `prompts/scenario/research.md`
  - `prompts/scenario/visual_breakdown.md` (new repo SoT if absent)
  - `src/yt_flow/pipeline/nodes/scenario_chain.py`
  - `src/yt_flow/pipeline/nodes/scenario.py` only if additional context needs orchestration changes
  - `tests/pipeline/nodes/test_scenario_chain.py`
  - `tests/pipeline/nodes/test_scenario.py`
  - `tests/fixtures/cassettes/deepseek_research.json`
  - `tests/fixtures/cassettes/deepseek_visual_breakdown.json`
- Conditional Phase 2 may also touch:
  - `src/yt_flow/config.py`
  - `src/yt_flow/pipeline/nodes/image.py`
  - `data/workflows/*`
  - tests for image/config/reference metadata

## References

- Epic/story source: `_bmad-output/planning-artifacts/epics.md#Epic 5: 영상 품질 고도화`
- Architecture: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
- PRD: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`
- Prompt policy: `docs/PROMPT_POLICY.md`
- Previous story: `_bmad-output/implementation-artifacts/5-4-tts-korean-naturalization.md`
- Prompt A/B story: `_bmad-output/implementation-artifacts/6-1-prompt-policy-variant-label-wiring.md`
- Deferred-work rationale: `_bmad-output/implementation-artifacts/deferred-work.md`
- Langfuse protected labels: https://langfuse.com/changelog/2025-04-02-protected-prompt-labels
- ComfyUI IPAdapter reference implementation: https://github.com/cubiq/ComfyUI_IPAdapter_plus
- SCP licensing guide: https://scp-wiki.wikidot.com/licensing-guide
- CC BY-SA 3.0 deed: https://creativecommons.org/licenses/by-sa/3.0/deed.en

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

- Story context created by BMad create-story workflow on 2026-07-04.
- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List

## Change Log

- 2026-07-04: Created ready-for-dev story context for visual story alignment; included Phase 1 prompt-context path, conditional Phase 2 IPAdapter path, prompt policy constraints, architecture guardrails, and validation requirements.

## Saved Questions / Clarifications

- None blocking. Phase 2 should only proceed if Phase 1 A/B evidence shows insufficient visual-story alignment.
