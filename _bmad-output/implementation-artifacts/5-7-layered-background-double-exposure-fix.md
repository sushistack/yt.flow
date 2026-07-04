---
created: 2026-07-04
story_key: 5-7-layered-background-double-exposure-fix
story_id: "5.7"
epic: 5
previous_story: 5-6-character-cutout-quality
depends_on:
  - 1-6b-image-layered-assets
  - 5-2-layered-assets-activation
  - 5-6-character-cutout-quality
---

# Story 5.7: Layered Background/Character Double-Exposure Fix

Status: ready-for-dev

## Story

As Jay,
I want the background layer to NOT contain the same entity/character that the animated character overlay also renders,
so that the final video doesn't show the SCP entity twice (once static and blurred in the background, once sharp and moving as the overlay).

## Context

Jay reviewed the live-rendered video from Story 5.5's A/B validation (2026-07-04, SCP-096, both variants) and observed a clear visual defect: in shots where the entity is visible, it appears twice in the same frame — once baked into the static background image, and again as the separately-animated character cutout layered on top.

Root cause, confirmed by reading the code: the "layered" ComfyUI workflow generates background and character from **the exact same single generation** — there is no step that removes the character from the background before saving it as `background_path`. This was an explicit, documented design choice (`data/workflows/README-layered-assets.md:170-172`: "Both layered workflows intentionally derive the character cutout from the same generated frame as the background"), made across Story 1.6b (which originally rejected `rembg`-style segmentation, see 1-6b Dev Notes) and Story 5.6 (which reversed that and adopted InSPyReNet segmentation from that same frame). Nobody caught the resulting double-exposure until a real end-to-end video was watched — Story 5.2's "라이브 검증 완료" and Story 5.6's "라이브 검증 완료" both verified pixel/format correctness (RGBA, alpha channel present) but not the composited visual result.

This is purely a visual-compositing defect; it is orthogonal to Story 5.5's prompt-content work and to Story 5.8 (which addresses whether the character overlay should come from a search-informed reference image instead of a same-frame cutout at all — a bigger architecture question). This story's job is narrower: **whatever the character overlay's source ends up being, the background must not also show that same entity.**

## Acceptance Criteria

1. Given a layered shot where `entity_visible: true` (or any shot that produces both `background_path` and `character_path`), when the final video composites `background_path` + `character_path` via `_overlay_filter()`, then the entity/character must not appear twice in the same composited frame.
2. Given the fix, then it must not regress the existing non-layered path: `YTFLOW_COMFYUI_LAYERED=false` or mock mode (`YTFLOW_COMFYUI_MOCK=true`) continue to work exactly as today (background-only compositing, `character_path` may be `None`, AC:3 of `video.py`'s existing `_overlay_filter` contract).
3. Given the fix touches the ComfyUI workflow JSON(s) under `data/workflows/`, then `data/workflows/README-layered-assets.md` is updated to reflect the new node graph and the "intentionally derive the character cutout from the same generated frame as the background" claim is corrected or removed.
4. Given `image.py`'s `_generate_layered_shot()` changes (if any), then `ShotData`'s existing `background_path`/`character_path`/`image_path` contract stays intact — `image_node` callers (`video.py`) must not need to know how the background was cleaned.
5. Given the fix, then it is validated by a real (non-mock) ComfyUI run producing at least one entity-visible shot, with the resulting composited frame visually confirmed (screenshot or frame-extract) to show the entity only once.

## Tasks / Subtasks

- [ ] Investigate and choose a fix approach (AC: 1, 3) — read `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` and any other layered workflow variant under `data/workflows/` fully before deciding; do not assume only one workflow file needs changing.
  - [ ] Option A: add an inpainting/removal pass so the background SaveImage branch outputs the scene with the entity erased (e.g., a mask from the same InspyrenetRembg node feeding an inpaint node before node 9's SaveImage).
  - [ ] Option B: regenerate the background with a modified prompt/mask that excludes the entity, as a second ComfyUI sampler pass sharing the same seed/environment for consistency.
  - [ ] Document the chosen approach's tradeoffs (extra ComfyUI compute time per shot, consistency risk between background/character generations) in Dev Agent Record.
- [ ] Update the ComfyUI workflow JSON(s) (AC: 1, 3)
  - [ ] Modify `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` per the chosen approach.
  - [ ] Update `data/workflows/README-layered-assets.md` node-graph description and remove/correct the "intentionally same frame" claim.
- [ ] Update `src/yt_flow/pipeline/nodes/image.py` only if `_generate_layered_shot()`'s ComfyUI node wiring changes (AC: 4)
  - [ ] Preserve `bg_dest`/`char_dest`/`img_dest` return contract exactly.
  - [ ] Preserve mock-mode behavior (`s.comfyui_mock` branch) unchanged unless mock fixtures also need updating to reflect the new node graph shape.
- [ ] Validate (AC: 2, 5)
  - [ ] Run existing test suites: `uv run pytest tests/pipeline/nodes/test_image.py tests/pipeline/nodes/test_video.py -q`.
  - [ ] Run a real (non-mock) ComfyUI shot generation for an entity-visible shot and visually confirm the double-exposure is gone; save the before/after frame comparison in Dev Agent Record.
  - [ ] Confirm mock mode and `YTFLOW_COMFYUI_LAYERED=false` still pass their existing tests unmodified.

## Dev Notes

### Critical Implementation Guardrails

- Do not touch `src/yt_flow/pipeline/nodes/video.py`'s `_overlay_filter()` contract (AC:3 there — `character_path` optional, `None` = background-only) unless the chosen fix requires it; the compositing logic itself is not wrong, the INPUT to it is. [Source: `src/yt_flow/pipeline/nodes/video.py:395-471`]
- `image_node` must remain ignorant of *why* the background is now clean — it just receives `background_path`/`character_path` from ComfyUI outputs as it does today. [Source: `src/yt_flow/pipeline/nodes/image.py:148-191`]
- Keep `s.comfyui_background_node` / `s.comfyui_character_node` config settings (`src/yt_flow/config.py:39-41`) as the seam for which ComfyUI node IDs to read — if the new workflow needs an additional node output, add a new named setting rather than hardcoding a node ID in `image.py`.
- This story does NOT decide whether the character overlay should come from a search-based reference image instead of a same-frame cutout — that is Story 5.8's scope. This story assumes the current same-frame-cutout architecture stays, and only fixes the background leaking the entity.

### Current Code State — Files To Read Before Editing

- `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json`
  - Current state: node `"8"` (`VAEDecode`) feeds both node `"9"` (`SaveImage`, `ytflow_bg` prefix — background) and node `"12"` (`InspyrenetRembg`, `image=["8",0]`) → node `"13"` (`SaveImage`, `ytflow_char` prefix — character cutout). No removal/inpaint step exists between node 8 and node 9.
  - This story changes: insert whatever nodes the chosen fix approach requires between node 8 and node 9's background save, so the background output no longer contains the entity.
- `data/workflows/README-layered-assets.md`
  - Current state: lines 170-172 document the same-frame derivation as intentional.
  - This story changes: correct this documentation to match the new graph.
- `src/yt_flow/pipeline/nodes/image.py`
  - Current state: `_generate_layered_shot()` (lines 148-191) submits one ComfyUI prompt, fetches outputs keyed by `s.comfyui_background_node` and `s.comfyui_character_node`, writes both, and validates the character output has an alpha channel (`_has_alpha`).
  - This story changes: likely only the ComfyUI submission side (workflow JSON), not this function — read fully to confirm before touching.
- `src/yt_flow/pipeline/nodes/video.py`
  - Current state: `_overlay_filter()` (lines 226+) composites `character_path` over `background_path`. `character_path` is optional per AC:3 (line 449, `shot.get("character_path")`).
  - This story changes: none expected, listed for context only.

### Architecture Compliance

- AD-1 (layer boundaries): this story stays inside `pipeline`/data-asset concerns; no `db`/`api` changes needed.
- Config additions (if any new ComfyUI node ID setting is needed) belong in `src/yt_flow/config.py` with `YTFLOW_` prefix, per project convention.

### Previous Story Intelligence

- Story 5.6 confirmed rembg/InSPyReNet cutout format correctness (RGBA, alpha present) across 72/72 shots on a real run, but explicitly scoped itself to cutout *quality* (halo/jaggies, framing) — not to whether the background also contains the entity. This story fills that gap. [Source: `_bmad-output/implementation-artifacts/5-6-character-cutout-quality.md`]
- Story 1.6b originally rejected `rembg`-style segmentation ("Option B") for reasons documented in its own file — read that rationale before assuming the segmentation approach itself should be abandoned; this story does not revisit that decision, only the background-cleanliness gap it left behind. [Source: `_bmad-output/implementation-artifacts/1-6b-image-layered-assets.md:67`]

### Testing Requirements

- `uv run pytest tests/pipeline/nodes/test_image.py tests/pipeline/nodes/test_video.py -q`
- A real (non-mock, non-CI) ComfyUI validation run is required per AC5 — record the exact shot/run ID and a visual before/after in Dev Agent Record, same pattern as Story 5.6's live validation.

## Project Structure Notes

- Expected modified files:
  - `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json`
  - `data/workflows/README-layered-assets.md`
  - `src/yt_flow/pipeline/nodes/image.py` (only if node wiring requires code changes)
  - `tests/pipeline/nodes/test_image.py` (if new node IDs/mock fixtures are introduced)

## References

- Epic/story source: `_bmad-output/planning-artifacts/epics.md#Epic 5: 영상 품질 고도화`
- Related stories: `_bmad-output/implementation-artifacts/1-6b-image-layered-assets.md`, `5-2-layered-assets-activation.md`, `5-6-character-cutout-quality.md`
- Discovered during: `_bmad-output/implementation-artifacts/5-5-visual-story-alignment.md` live A/B review (2026-07-04)
- Workflow docs: `data/workflows/README-layered-assets.md`

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

- Story context created 2026-07-04 following user (Jay) review of Story 5.5's live-rendered A/B videos; root cause confirmed via code investigation (see `_bmad-output/implementation-artifacts/5-5-visual-story-alignment.md` Dev Agent Record for the triggering conversation).

### File List

## Change Log

- 2026-07-04: Story created from live-render review feedback (double-exposure bug), root cause pre-confirmed via code investigation before story creation.

## Saved Questions / Clarifications

- Option A (inpaint) vs Option B (second generation pass) tradeoff — extra ComfyUI compute cost per shot needs measuring before committing; not decided at story-creation time.
