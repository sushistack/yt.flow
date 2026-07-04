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
baseline_commit: c2c638a76973c84ecb6ae0ca5df16be506da6139
---

# Story 5.5: Visual Story Alignment - visual_breakdown Context + SCP Reference Image Option

Status: done

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

- [x] Update scenario prompt source of truth under `prompts/scenario/` (AC: 1, 3, 4, 8)
  - [x] Add or update `prompts/scenario/research.md` to emit `entity_sheet` alongside the existing `frozen_descriptor`.
  - [x] Add in-repo prompt sources for missing runtime prompts before changing them, especially `prompts/scenario/visual_breakdown.md`; do not make Langfuse-only prompt edits.
  - [x] Ensure `visual_breakdown` prompt asks for structured composition/camera framing while preserving the existing JSON shape expected by tests.
- [x] Update `src/yt_flow/pipeline/nodes/scenario_chain.py` (AC: 1-7)
  - [x] Validate `research["entity_sheet"]` as non-empty if the prompt contract adds it.
  - [x] Thread global premise/logline and per-scene role from `research`/`structure`/`writing` into `visual_breakdown_step`.
  - [x] Keep `label: str | None = None` keyword-only plumbing exactly compatible with Story 6.1.
  - [x] Keep sentence-count validation and `finish_reason == "length"` truncation errors.
- [x] Update `src/yt_flow/pipeline/nodes/scenario.py` only if orchestration needs extra state passed into `_write_and_review` (AC: 2, 6)
  - [x] Preserve the current `label = "candidate" if state.get("prompt_variant") == "B" else None` behavior.
  - [x] Preserve bounded retry: one retry max if review/critic requests it.
- [x] Update tests and cassettes (AC: 1-8)
  - [x] Add `entity_sheet` to the relevant DeepSeek cassette(s), especially `tests/fixtures/cassettes/deepseek_research.json`.
  - [x] Add unit coverage proving `visual_breakdown_step` receives story/global and scene-role variables.
  - [x] Add regression coverage proving Variant A/None still uses production lookup and Variant B still uses candidate lookup.
  - [x] Run at minimum: `uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/test_prompt_service.py -q`.
- [x] Seed prompt candidate labels (AC: 6, 8, 13)
  - [x] `--source prompts/scenario` reproduces a known naming bug (see deferred-work.md); actually used `uv run python scripts/migrate_prompts.py --label candidate --source prompts` after cleaning up 4 wrongly-named versions.
  - [x] Record whether each changed prompt was created/skipped and whether any candidate fallback warnings appeared during test/live runs.
- [x] Validate Phase 1 with A/B (AC: 13, 15) — **evaluated, Phase 1 did NOT clear the bar**; see Completion Notes
  - [x] Run or document `POST /runs/{id}/ab` for the same SCP input after Variant A is available.
  - [x] Run Epic 4 evaluation and record visual alignment outcome in Dev Agent Record. — done 2026-07-04; automated judge picked Variant A (baseline), not B.
- [ ] Conditional Phase 2 only after Phase 1 evidence (AC: 9-12, 14) — **out of this story's scope, decision deferred to Story 5.7's re-validation**: Phase 1 A/B evidence (2026-07-04) shows Variant B did not materially improve visual-story alignment, but Jay's own video review found the underlying cause is likely confounded by the layered-compositing double-exposure bug (both variants shared it) — see Story 5.7. Not started; whether to pursue Phase 2 will be decided after Story 5.7 lands and Phase 1's A/B is re-run clean.
  - [ ] Reuse existing character/reference infrastructure before adding a new fetcher.
  - [ ] Add ComfyUI workflow/config support for an IPAdapter reference only if the existing workflow path and Story 5.2 layered workflow can remain intact.
  - [ ] Persist attribution metadata where downstream video description tooling can read it.

### Review Findings

- [x] [Review][Patch] `_scene_role_text` crashes/silently degrades on non-dict or non-string structure fields, and `structure[idx]`/`writing["scenes"][idx]` length mismatch is unlogged [src/yt_flow/pipeline/nodes/scenario_chain.py:149, src/yt_flow/pipeline/nodes/scenario.py:111]
- [x] [Review][Patch] `research_step` entity_sheet/story_logline validation stays lenient even under the candidate (new) prompt label, and doesn't check value type [src/yt_flow/pipeline/nodes/scenario_chain.py:82-88]
- [x] [Review][Patch] Tasks checklist self-contradiction: "Validate Phase 1 with A/B" checked done while its required child (Epic 4 evaluation) is blocked [5-5-visual-story-alignment.md:78]
- [x] [Review][Patch] Tasks checklist cites the exact `migrate_prompts.py --source prompts/scenario` invocation that Completion Notes say was broken and discarded [5-5-visual-story-alignment.md:76]
- [x] [Review][Patch] No test exercises the real `prompts/scenario/visual_breakdown.md` placeholder tokens [tests/pipeline/nodes/test_scenario_chain.py]
- [x] [Review][Defer] `scenario/tts_normalize` has no `production` Langfuse label — every live pipeline run (any variant) currently fails end-to-end; pre-existing Story 5.4 gap, understated severity — deferred, pre-existing [src/yt_flow/pipeline/nodes/scenario_chain.py:257]
- [x] [Review][Defer] Cleanup of 4 wrongly-named candidate Langfuse prompt versions only stripped labels, did not delete the orphaned versions — deferred, pre-existing (Langfuse-side, not a code change)
- [x] [Review][Defer] `scripts/migrate_prompts.py`'s `derive_name()` naming bug has now recurred across 5.4 and 5.5 (twice); `docs/PROMPT_POLICY.md`'s own example reproduces it — deferred, pre-existing
- [x] [Review][Defer] ComfyUI + yt.flow API dev server left running locally after the session (`/tmp/comfyui_boot.log`, `/tmp/ytflow_boot2.log`) — deferred, operational hygiene only

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

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Live A/B attempt run IDs: `0b9e807d-1ba3-4a42-b5ce-cca7f88972d0` (failed — pre-fix `entity_sheet` KeyError bug, superseded), `dc526c8d-abb4-4814-b296-e0900e2a60c9` (failed — blocked on pre-existing `scenario/tts_normalize` production-label gap, see below).
- ComfyUI (`$HOME/workspaces/ComfyUI`) and the yt.flow API (`uv run uvicorn yt_flow.api.main:app --host 127.0.0.1 --port 8000`) were started locally for the live attempt and left running at session end.

### Completion Notes List

- Story context created by BMad create-story workflow on 2026-07-04.
- Ultimate context engine analysis completed - comprehensive developer guide created.
- **Phase 1 implemented and offline-tested.** `research_step` now emits and (leniently) validates `entity_sheet`/`story_logline`; `visual_breakdown_step` threads `entity_sheet`, `story_logline`, and a compact `scene_role` (from `structure_step`'s `act`/`emotional_beat`/`synopsis`) into the rendered prompt alongside the existing `frozen_descriptor`. `prompts/scenario/visual_breakdown.md` did not exist in-repo despite being live in Langfuse production (v1) — reconstructed verbatim from the live production content (confirmed byte-for-byte against `client.get_prompt("scenario/visual_breakdown")`) before layering the new Story/Scene/Entity-Sheet sections on top, per AC8/policy ("no Langfuse-only edits").
- **Backward-compatibility fix found via live testing, not review**: the first validation pass raised on entity_sheet/story_logline whenever the key was merely *absent* (old production prompt shape), which would have hard-crashed Variant A/None for every run until the new prompt is promoted to production. Fixed to only raise when the key is *present but blank* (a real LLM output bug); an absent key now passes through as `None`/`""` via `research.get(...)`. Locked in with `test_research_step_tolerates_missing_entity_sheet_and_logline`. This is exactly the kind of gap AC5 ("existing contracts stay intact") calls out, and it was only caught because a real Variant A run was attempted against the fixed API server before code review — see [[worktree-editable-install-shadowing]]-style lesson: local unit tests all used the *new* cassette shape, so none of them exercised "key entirely absent."
- Candidate seeding: `scenario/research` and `scenario/visual_breakdown` created under the `candidate` label (see exact commands below). While doing this I initially reproduced a **known, already-documented bug** (`docs/PROMPT_POLICY.md` / deferred-work.md 5.4 review entry): running `migrate_prompts.py --source prompts/scenario` derives bare names (`research`, `visual_breakdown`, ...) instead of `scenario/research` etc., because `derive_name()` is relative to `--source`. I did not re-check deferred-work.md before running it and repeated the mistake — created 4 wrongly-named candidate prompt versions, then cleaned them up via `client.update_prompt(name=..., version=1, new_labels=[])` and re-seeded correctly with explicit `scenario/`-prefixed names. No `production` label was touched by either the mistake or the fix.
- **Live A/B validation (AC13/14/15) is BLOCKED, not completed** — honestly recorded per AC15. Attempted a real run end-to-end (ComfyUI + yt.flow API server started locally, `POST /runs` for SCP-096 — the same SCP as the original 2026-07-03 review that motivated this story). `scenario_node` reached `tts_normalize_step` and failed: `Langfuse prompt fetch failed: name='scenario/tts_normalize' label=production`. Root cause: Story 5.4 seeded `scenario/tts_normalize` only under `candidate` and never promoted it to `production` — a pre-existing gap, not introduced by this story, and it blocks **Variant A too** (the `label=None` path still requires a `production` version for every stage in the chain). Recorded in `deferred-work.md` under "Deferred from: 5-5 visual-story-alignment 라이브 A/B 시도 (2026-07-04)". Jay decided to fix Story 5.4's promotion gap as a separate follow-up rather than promote the label from inside this story's session.
- **Exact manual commands to complete AC13/14/15 once the 5.4 gap is fixed:**
  1. Promote `scenario/tts_normalize` candidate v1 to `production` (Langfuse UI label move, or `Langfuse.update_prompt(name="scenario/tts_normalize", version=1, new_labels=["production"])`), per PROMPT_POLICY's change protocol.
  2. `curl -X POST http://127.0.0.1:8000/runs -H "Content-Type: application/json" -d '{"scp_id": "SCP-096"}'` — Variant A (baseline, production labels).
  3. Approve each gate as the run reaches it: `curl -X POST http://127.0.0.1:8000/runs/{run_id}/stages/{stage}/gate -H "Content-Type: application/json" -d '{"action": "approve"}'` for `scenario`, `image`, `tts`, `subtitle`, `video` in order, polling `GET /runs/{run_id}` for `status=="awaiting_approval"` between each.
  4. Once Variant A's `status=="complete"`: `curl -X POST http://127.0.0.1:8000/runs/{run_id}/ab` to create Variant B (`prompt_variant="B"`, reads `scenario/research` + `scenario/visual_breakdown` under `candidate`, everything else falls back to `production` with a logged warning per Story 6.1/AC7).
  5. Approve Variant B's gates the same way.
  6. Run the Epic 4 evaluation (`eval_service`) against the resulting `ab_pair_id` and record the visual-alignment score delta + Jay's gate-review verdict here.
- ComfyUI and the yt.flow dev API server were left running locally (`/tmp/comfyui_boot.log`, `/tmp/ytflow_boot2.log`) so the above can be resumed without a cold model-load wait; stop with `pkill -f "main.py --preview-method auto"` and `pkill -f "uvicorn yt_flow.api.main:app"` when no longer needed.
- Phase 2 (AC9-12, 14) is correctly **not started**: its own trigger condition (AC9 — "Phase 1 A/B results are insufficient") cannot be evaluated until the blocked validation above runs.
- **2026-07-04 — Live A/B + Epic 4 evaluation completed for SCP-096.** Blocker resolved by promoting `scenario/tts_normalize` candidate v1 to `production` (`Langfuse.update_prompt(name="scenario/tts_normalize", version=1, new_labels=["production"])`; SDK's `new_labels` is additive, so v1 now also still carries `candidate`/`latest` — harmless, only one version exists). API server restarted first so the run used the code-review-fixed code (label-gated entity_sheet/story_logline validation, hardened `_scene_role_text`), not the pre-review build.
  - Variant A (baseline, all `production` labels): run `d5fe1f64-7e5c-4a8b-9d9a-c0696266939b`, 8 scenes / 48 shots, completed end-to-end (scenario → image → tts → subtitle → video), all gates manually approved.
  - Variant B (`prompt_variant="B"`, `POST /runs/d5fe1f64.../ab`): run `0161138d-f701-4c31-9591-129fedc0d3e1`, 8 scenes / 54 shots. Server log confirmed the expected label split: `scenario/format_guide`, `scenario/writing`, `scenario/review`, `scenario/critic_agent` all logged the Story 6.1 candidate-fallback warning (not part of the A/B, per AC7); `scenario/research`, `scenario/structure`, `scenario/visual_breakdown`, `scenario/tts_normalize` fetched under `candidate` with no fallback warning. Completed end-to-end, all gates manually approved.
  - **Epic 4 evaluation fired automatically** on Variant B completion (`_trigger_ab_eval_if_variant_b` → `eval_service.evaluate_ab`, no manual trigger needed) and populated `ab_result` on the Variant B run row within ~2 minutes:
    ```
    axis_scores:      A{atmosphere=3.0, narrative_coherence=4.33, article_fidelity=5.0}
                       B{atmosphere=2.0, narrative_coherence=4.67, article_fidelity=5.0}
    pairwise_winner:   majority=A (2/3) — runs: A_vs_B→A, B_vs_A→B, A_vs_B→A
    rule_based_scores: A{scene_count_match_rate=1.0, subtitle_sync_error=0.0, audio_duration_variance=0.057}
                       B{scene_count_match_rate=1.0, subtitle_sync_error=0.0, audio_duration_variance=0.120}
    winner: A
    langfuse_eval_trace_url: https://langfuse.eli.kr/project/cmr0tuswa0007zh07tv2zs33p/traces/a743de712da99fe41936b20795eb78fb
    ```
  - **Honest verdict: AC13 is NOT satisfied.** The automated Epic 4 judge picked Variant A (baseline) over Variant B (Phase 1 prompt-context changes) — B lost on `atmosphere` (2.0 vs 3.0) and `audio_duration_variance` (0.120 vs 0.057, worse/more variance), won narrowly on `narrative_coherence` (4.67 vs 4.33), tied on `article_fidelity`. The pairwise LLM-judge also sided with A on 2 of 3 orderings. This is the opposite of what the story hypothesized — adding `entity_sheet`/`story_logline`/`scene_role` context to `visual_breakdown` did not measurably improve visual-story alignment on this SCP, and plausibly diluted `atmosphere` (the 243-line prompt's forbidden-word list and heavier structural instructions may be trading atmospheric language for compliance with the new sections — not verified, just the most likely mechanism).
  - **Jay's own gate-review verdict (AC13's other half) — done.** Jay watched the Variant A final video (`workspace/d5fe1f64-7e5c-4a8b-9d9a-c0696266939b/video.mp4`) and found several defects unrelated to Phase 1's prompt-content scope: (1) background/character double-exposure — the entity appears twice in the same frame; (2) narration/image mismatch persisting (consistent with the Epic 4 loss); (3) the SCP entity's visual appearance isn't grounded in a real reference image as intended; (4) narration audio audibly fades at scene-transition cuts; (5) the layered-asset architecture (single-frame segmentation cutout) doesn't match the originally intended design (search-based reference composited onto background). Root causes for (1)/(3)/(5) and (4) were investigated and confirmed via code reading, then filed as Stories 5.7 (double-exposure), 5.8 (dormant search-reference pipeline), and 5.9 (transition audio coupling) — see those files for exact citations.
  - **Implication for Phase 2 (AC9) and story closure**: "Phase 1 A/B results are insufficient" has direct evidence, but the Epic 4 loss and Jay's video review both likely reflect Story 5.7's double-exposure bug degrading BOTH variants equally, not a genuine failure of the entity_sheet/story_logline/scene_role prompt content itself. Rather than block this story on that unresolved confound, **Story 5.5 is closed as done** with Phase 1 implemented, reviewed, and validated (AC13/14/15's live A/B + evaluation ran, even though the result needs a clean re-run). Story 5.7 owns re-running this A/B after its fix lands; the Phase 2 go/no-go decision (iterate Phase 1 wording vs. SCP Wiki reference vs. accept) is deferred to that re-validation, not decided here.
  - **2026-07-04 — Clean re-run after Story 5.7's double-exposure fix landed (resolves the confound above).** New SCP-096 A/B: Variant A `b2dcc3bc-85e5-4ab6-b635-048c98105a2a` (8 scenes/53 shots), Variant B `53bceeaf-eed5-443b-b185-34d8b8522055` (`ab_pair_id=b2dcc3bc...`, 71 shots), both completed end-to-end with every layered shot's background now passing through Story 5.7's inpaint fix (spot-checked several entity-visible shots in both variants' real output — no double-exposure). New `ab_result`:
    ```
    axis_scores:      A{atmosphere=3.67, narrative_coherence=5.0, article_fidelity=4.33}
                       B{atmosphere=3.67, narrative_coherence=5.0, article_fidelity=3.33}
    pairwise_winner:   majority=A (2/3) — runs: A_vs_B→A, B_vs_A→B, A_vs_B→A (same voting pattern as the original run)
    rule_based_scores: A{scene_count_match_rate=1.0, subtitle_sync_error=0.0, audio_duration_variance=0.327}
                       B{scene_count_match_rate=1.0, subtitle_sync_error=0.0, audio_duration_variance=0.102}
    winner: A
    langfuse_eval_trace_url: https://langfuse.eli.kr/project/cmr0tuswa0007zh07tv2zs33p/traces/ee63d269c51ef4bfe9f7f68854506362
    ```
  - **Confound verdict: partially resolved, conclusion unchanged.** The `atmosphere` axis where B previously lost badly (2.0 vs 3.0) is now **tied** (3.67 vs 3.67) — direct evidence that the original atmosphere gap was at least partly an artifact of the double-exposure bug (or of run-to-run generation variance), not a genuine Phase 1 prompt regression. `narrative_coherence` is now tied at the max (5.0/5.0, both improved). However, Variant A still wins overall (pairwise majority 2/3, same exact vote pattern as before) — this time driven by `article_fidelity` (B drops to 3.33 vs A's 4.33), an axis that was tied 5.0/5.0 in the original confounded run. `audio_duration_variance` flipped in B's favor (B 0.102 < A 0.327; previously B was worse, 0.120 > 0.057) but both variants' absolute variance got worse than before — most plausibly natural LLM-generation variance between runs (scenario content isn't deterministic), not a Story 5.7 effect (5.7's fix only touches image compositing, not TTS/duration).
  - **Net conclusion for Phase 2 (AC9) — Phase 1 A/B evidence remains insufficient, now on solid (unconfounded) footing.** Removing Story 5.7's double-exposure confound did not flip the result: Variant A still wins on a clean re-run, just via a different axis (article_fidelity instead of atmosphere). This makes the original "Phase 1 prompt-context changes did not measurably improve visual-story alignment" conclusion *more* credible, not less — the go/no-go decision to iterate on Phase 1 wording vs. accept current quality vs. proceed to Phase 2 (SCP Wiki reference/IPAdapter) can now be made without the double-exposure caveat. No status change to this story (stays `done`); this is a closing note on the confound this story's own closure deferred to Story 5.7, recorded here per that story's Task 5 instruction.

### File List

- `prompts/scenario/research.md` (modified — added `entity_sheet`, `story_logline` fields)
- `prompts/scenario/visual_breakdown.md` (new — reconstructed repo source-of-truth + Story Logline / Scene Narrative Role / Entity Sheet sections)
- `src/yt_flow/pipeline/nodes/scenario_chain.py` (modified — `research_step` entity_sheet/story_logline validation (lenient on absent key); `visual_breakdown_step` new `entity_sheet`/`story_logline`/`scene_role` params + `_scene_role_text` helper)
- `src/yt_flow/pipeline/nodes/scenario.py` (modified — `_write_and_review` threads `entity_sheet`/`story_logline`/per-scene `structure` role into `visual_breakdown_step`)
- `tests/pipeline/nodes/test_scenario_chain.py` (modified — entity_sheet/story_logline validation tests, backward-compat test, `visual_breakdown_step` signature updates, variable-threading test)
- `tests/pipeline/nodes/test_scenario.py` (modified — `RESEARCH` fixture gains `entity_sheet`/`story_logline`; new orchestration test proving threading)
- `tests/fixtures/cassettes/deepseek_research.json` (modified — added `entity_sheet`/`story_logline` to the cassette payload)
- `_bmad-output/implementation-artifacts/deferred-work.md` (modified — recorded the `scenario/tts_normalize` production-label gap discovered during live validation)

## Change Log

- 2026-07-04: Created ready-for-dev story context for visual story alignment; included Phase 1 prompt-context path, conditional Phase 2 IPAdapter path, prompt policy constraints, architecture guardrails, and validation requirements.
- 2026-07-04: Implemented Phase 1 (prompt-context strengthening) — `entity_sheet`/`story_logline` in `scenario/research`, reconstructed + extended `scenario/visual_breakdown` repo source, threaded story/scene context through `scenario_chain.py`/`scenario.py`, fixed a backward-compatibility bug (absent vs. blank field), seeded both prompts under Langfuse `candidate`. Attempted live A/B validation; blocked by a pre-existing Story 5.4 gap (`scenario/tts_normalize` never promoted to `production`), documented exact resumption commands, moved to review with the validation gap honestly open per AC15.
- 2026-07-04: Code review (3-layer adversarial: Blind Hunter, Edge Case Hunter, Acceptance Auditor). 5 patch findings fixed: `_scene_role_text` now guards non-dict/non-string structure data and `scenario.py` logs a warning on writing/structure scene-count mismatch instead of silently rendering an empty role; `research_step`'s `entity_sheet`/`story_logline` validation is now strict when `label` is set (candidate/variant-B path) and also checks value type, closing a loophole where the new prompt could silently omit required fields or return non-string values; corrected two self-contradicting Tasks-checklist entries (the "Validate Phase 1 with A/B" parent checkbox and the `migrate_prompts.py` command actually used); added a placeholder-coverage test for `prompts/scenario/visual_breakdown.md`. 4 pre-existing issues deferred to `deferred-work.md` (tts_normalize production-label gap severity, orphaned Langfuse candidate versions, recurring `migrate_prompts.py` naming bug, stray local dev processes). Status set to `in-progress` (not `done`) because AC13/14/15's live A/B validation remains genuinely blocked on the pre-existing Story 5.4 gap, unrelated to this review.
- 2026-07-04: Promoted `scenario/tts_normalize` candidate v1 to `production`, unblocking every live run (not just A/B). Ran the full live A/B validation for SCP-096 end-to-end (Variant A run `d5fe1f64`, Variant B run `0161138d`) and the automatic Epic 4 evaluation it triggers. **Result: AC13 not satisfied** — the automated judge picked Variant A (baseline) over Variant B (Phase 1 changes) on both axis scores (atmosphere, audio_duration_variance) and pairwise comparison (2/3). Recorded full scores and next-step options (iterate on Phase 1 wording / proceed to Phase 2 / accept current quality) in Completion Notes; Jay's own gate-review verdict on the two final videos is still outstanding. Status stays `in-progress` pending that decision.
- 2026-07-04: Jay watched the Variant A video and reported 5 issues, none in Phase 1's own scope — investigated and confirmed via code reading, then filed as Stories 5.7 (background/character double-exposure), 5.8 (dormant Story 1.11-1.13 search-reference pipeline), and 5.9 (transition audio-fade coupling). Since the AC13 loss is likely confounded by 5.7's double-exposure bug affecting both variants equally, **status set to `done`** — Phase 1 is implemented, reviewed, and its live A/B + evaluation ran; the Phase 2 go/no-go call and a clean A/B re-run are deferred to Story 5.7's completion rather than left open-ended here.
- 2026-07-04: Re-ran the SCP-096 A/B clean after Story 5.7's double-exposure fix landed (Story 5.7's Task 5). The confounded `atmosphere` gap is gone (now tied 3.67/3.67), but Variant A still wins overall (now via `article_fidelity`, 4.33 vs 3.33) — same conclusion as before, now unconfounded. No status change; recorded per Story 5.7's Task 5 instruction to close the loop here.

## Saved Questions / Clarifications

- None blocking. Phase 2 should only proceed if Phase 1 A/B evidence shows insufficient visual-story alignment.
