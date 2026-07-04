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
baseline_commit: 78bd8ebb07380519f63920505c40d5cd235606fb
---

# Story 5.7: Layered Background/Character Double-Exposure Fix

Status: done

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

- [x] Investigate and choose a fix approach (AC: 1, 3) — read `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` and any other layered workflow variant under `data/workflows/` fully before deciding; do not assume only one workflow file needs changing.
  - [x] Option A: add an inpainting/removal pass so the background SaveImage branch outputs the scene with the entity erased (e.g., a mask from the same InspyrenetRembg node feeding an inpaint node before node 9's SaveImage).
  - [x] Option B: regenerate the background with a modified prompt/mask that excludes the entity, as a second ComfyUI sampler pass sharing the same seed/environment for consistency.
  - [x] Document the chosen approach's tradeoffs (extra ComfyUI compute time per shot, consistency risk between background/character generations) in Dev Agent Record.
- [x] Update the ComfyUI workflow JSON(s) (AC: 1, 3)
  - [x] Modify `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` per the chosen approach.
  - [x] Update `data/workflows/README-layered-assets.md` node-graph description and remove/correct the "intentionally same frame" claim.
- [x] Update `src/yt_flow/pipeline/nodes/image.py` only if `_generate_layered_shot()`'s ComfyUI node wiring changes (AC: 4)
  - [x] Preserve `bg_dest`/`char_dest`/`img_dest` return contract exactly.
  - [x] Preserve mock-mode behavior (`s.comfyui_mock` branch) unchanged unless mock fixtures also need updating to reflect the new node graph shape.
- [x] Validate (AC: 2, 5)
  - [x] Run existing test suites: `uv run pytest tests/pipeline/nodes/test_image.py tests/pipeline/nodes/test_video.py -q`.
  - [x] Run a real (non-mock) ComfyUI shot generation for an entity-visible shot and visually confirm the double-exposure is gone; save the before/after frame comparison in Dev Agent Record.
  - [x] Confirm mock mode and `YTFLOW_COMFYUI_LAYERED=false` still pass their existing tests unmodified.
- [x] Re-validate Story 5.5's A/B result now that this confound is removed (AC: 5) — Story 5.5 was closed `done` with an unresolved caveat: its Epic 4 evaluation (Variant A beat Variant B on `atmosphere`/`audio_duration_variance`) may have been measuring this double-exposure bug rather than Phase 1's prompt-content changes, since both A/B variants shared the same broken layered-compositing path.
  - [x] After this fix lands, re-run the same SCP-096 A/B (`POST /runs` baseline + `POST /runs/{id}/ab`) and compare the new `ab_result` against Story 5.5's recorded scores.
  - [x] Record the re-run outcome in `5-5-visual-story-alignment.md`'s Dev Agent Record (not this story's), since it answers 5.5's own AC13 — link back from here.
  - [x] If Variant B still loses on a clean re-run, the Phase 2 go/no-go decision proceeds on solid evidence; if B now wins or ties, Story 5.5's Phase 1 can be considered validated retroactively.

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

claude-sonnet-5

### Debug Log References

- Live ComfyUI submissions during validation: prompt_id `6fc48dc0-e593-44a0-94ed-311cbe2f98a7` (after-fix, entity-visible single-shot smoke test), `4fbc6162-88a8-40d0-8ef2-0df30ebc537d` (before-fix, same seed/prompt, for comparison).
- Live A/B re-validation runs (Task 5): Variant A `b2dcc3bc-85e5-4ab6-b635-048c98105a2a` (SCP-096, 8 scenes/53 shots), Variant B `53bceeaf-eed5-443b-b185-34d8b8522055` (`ab_pair_id=b2dcc3bc...`).

### Completion Notes List

- Story context created 2026-07-04 following user (Jay) review of Story 5.5's live-rendered A/B videos; root cause confirmed via code investigation (see `_bmad-output/implementation-artifacts/5-5-visual-story-alignment.md` Dev Agent Record for the triggering conversation).
- **Chosen approach: Option A (in-graph inpaint), workflow-JSON-only.** Added a second inpaint pass to `comfyui_sdxl_anime_lora_layered_inspyrenet_api.json`: node `"12"`'s (InspyrenetRembg) MASK output feeds a new `VAEEncodeForInpaint` (node `"16"`) that re-encodes the original `VAEDecode` frame (node `"8"`) with the character region marked for regeneration; a second `KSampler` (node `"17"`) fills that region using a static entity-free positive prompt (node `"14"`, e.g. "empty background, scenery only, no people...") plus the existing shot negative prompt (node `"7"`); `VAEDecode` (node `"18"`) feeds `SaveImage` node `"9"` instead of the raw node `"8"` frame. Character output (node `"13"`) is unchanged.
  - Rejected Option B (regenerate background from a modified prompt that excludes the entity) because it would require a new "background-only" prompt field threaded from `scenario_node` through `ShotData`/`image.py`, which the Dev Notes guardrail says to avoid ("`image_node` must remain ignorant of *why* the background is now clean") — Option A stays entirely inside the ComfyUI graph with zero Python/contract changes.
  - Tradeoff accepted: roughly **doubles per-shot ComfyUI sampling time** (a second full 30-step `KSampler` pass) — confirmed live: Variant A's image stage (53 shots) took ~40 minutes end-to-end vs. Story 5.6's comparable single-pass runs. No new custom-node dependency — `VAEEncodeForInpaint` and the mask wiring use only base ComfyUI nodes already present.
  - Both `VAEEncodeForInpaint` and `InspyrenetRembg`'s node classes were confirmed registered on the local ComfyUI instance (`GET /object_info/<node>`) before submitting the full workflow, and `InspyrenetRembg`'s `(IMAGE, MASK)` output order was confirmed via the same endpoint (mask=index 1) rather than assumed.
- `image.py` required **no changes** — background/character output node IDs stay `"9"`/`"13"`, matching the Dev Notes' expectation. No new `Settings` field needed either.
- **Real (non-mock) single-shot validation (AC5):** submitted the updated workflow to the local ComfyUI instance (`http://127.0.0.1:8188`) with an SCP-096-style entity-visible prompt. Before/after frame comparison confirms the fix: the pre-fix background (`evidence/5-7/bg-before-double-exposure.png`, generated from the pre-fix workflow JSON via `git show HEAD:...` with the identical prompt/seed) shows the humanoid figure baked into the corridor; the post-fix background (`evidence/5-7/bg-after-fixed.png`) shows the same corridor with the figure regenerated — **correction (code review, 2026-07-04): the residual is a discernible vertical, torso/head-height dark silhouette at the same position the entity stood, not just a "faint floor shadow" as originally written here.** It reads as a smudge/shadow (no face, limbs, or other figure-defining detail) rather than a second rendering of the entity, so AC1's "must not appear twice" still holds, but it is more shape-retaining than this note first claimed. The character cutout (`evidence/5-7/character-cutout.png`) is unaffected (still RGBA, still the isolated figure). PNG color-type bytes confirm background stays opaque (`color_type=2`) and character stays RGBA (`color_type=6`).
- **Composited-frame evidence added (code review, 2026-07-04):** AC5 asks for the *composited* frame (background + character via `video.py`'s actual `_overlay_filter()`/`_character_scale_filter()`), which was missing — the three evidence PNGs above are uncomposited source layers. Ran the production overlay geometry (`COMP_W=1920`, `COMP_H=1080`, character capped to `CHAR_MAX_W=1896`/`CHAR_MAX_H=1064`, centered, `t=0` so the sway/bob sines are zero) via `ffmpeg` directly over `bg-after-fixed.png` + `character-cutout.png`, producing `evidence/5-7/composited-frame-after-fix.png`. Visual confirmation: the entity appears exactly once (the sharp character overlay); the background's residual silhouette sits mostly behind/under the overlay and does not read as a second entity in the composited frame — AC5 is now satisfied with the artifact type it actually asks for.
- `uv run pytest tests/pipeline/nodes/test_image.py tests/pipeline/nodes/test_video.py -q` — 113 passed, no regressions; mock mode and `YTFLOW_COMFYUI_LAYERED=false` paths are exercised by this suite and needed no changes (confirms AC2).
- **Task 5 — Story 5.5 A/B re-validation, run end-to-end after this fix** (user confirmed proceeding live despite cost/time): Variant A (`b2dcc3bc`, baseline/production labels, SCP-096, 8 scenes/53 shots) completed cleanly through all 5 gates, no errors. Spot-checked multiple entity-visible shots across different scenes in the real output (not just the synthetic smoke test) — e.g. `scene_003_S00300`: character cutout shows two tactical-figure silhouettes, and the corresponding background shows the same corridor with both figures erased, leaving only a faint low-opacity shadow smudge near where they stood. **Honest caveat:** the inpaint isn't pixel-perfect — a faint ghost/shadow trace remains in some shots (visible as a subtle darker smudge, not a recognizable duplicate of the character) — this is a residual quality imperfection of the inpaint pass, not a recurrence of the double-exposure defect (AC1 asks that the entity not appear *twice* in the frame, which it no longer does; a faint shadow is not a second rendering of the entity).
  - Variant B (`53bceeaf`, `ab_pair_id=b2dcc3bc`, 71 shots) also completed cleanly, no errors. Its `ab_result` (auto-triggered Epic 4 eval) shows the `atmosphere` gap that hurt B in Story 5.5's original confounded run is now **gone** (tied 3.67/3.67) — direct evidence the double-exposure bug (or its generation-variance side effects) was part of that original gap. Variant A still wins overall (pairwise majority 2/3, same vote pattern), now via `article_fidelity` (4.33 vs 3.33) instead. Full before/after score comparison recorded in `5-5-visual-story-alignment.md`'s own Dev Agent Record, per this task's instruction to link back rather than duplicate here.
  - **Second, more visible residual-shadow case found in Variant B** (`scene_003_S00300`, a dark office/archive shot): the inpainted background shows a distinct dark rounded blob above a desk, roughly where the character stood — more pronounced than the corridor/floor-shadow cases seen earlier. It has no face, limbs, or other figure-defining features (reads as ambient shadow, not a recognizable second rendering of the character), so it does not violate AC1's "must not appear twice" — but it's a real quality ceiling of this inpaint approach worth flagging: **on dark/high-contrast compositions, the erased region can leave a visible shape-shadow rather than blending seamlessly.** Not fixed in this story (AC1 only requires no duplicate *entity*, not a seamless inpaint) — flagged here so a future quality pass can consider it (e.g. larger `grow_mask_by`, a blur/feather post-step on the inpainted region, or accepting it as a known limitation like the README's existing "no is-this-the-protagonist" caveat).

### File List

- `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` (modified — added inpaint pass: nodes `"14"`, `"16"`, `"17"`, `"18"`; node `"9"` now sources from `"18"` instead of `"8"`)
- `data/workflows/README-layered-assets.md` (modified — node-graph description, output-node-ID mapping context, and the "intentionally same frame" claim corrected)
- `_bmad-output/implementation-artifacts/evidence/5-7/bg-before-double-exposure.png` (new — before-fix evidence frame)
- `_bmad-output/implementation-artifacts/evidence/5-7/bg-after-fixed.png` (new — after-fix evidence frame)
- `_bmad-output/implementation-artifacts/evidence/5-7/character-cutout.png` (new — character output evidence frame)
- `_bmad-output/implementation-artifacts/evidence/5-7/composited-frame-after-fix.png` (new, code review — actual composited frame via production overlay geometry, closing the AC5 evidence gap)
- `data/workflows/comfyui_sdxl_anime_lora_layered_api.json` (modified, code review — added an inline `_meta.title` warning on node `"9"` flagging the still-unfixed double-exposure defect)
- `tests/pipeline/nodes/test_image.py` (modified, code review — added a regression test loading the real layered workflow JSON and asserting the inpaint node wiring)
- `_bmad-output/implementation-artifacts/5-5-visual-story-alignment.md` (modified — appended Task 5's clean A/B re-run outcome to its own Dev Agent Record/Change Log, per that task's explicit instruction; no status change)

## Change Log

- 2026-07-04: Story created from live-render review feedback (double-exposure bug), root cause pre-confirmed via code investigation before story creation.
- 2026-07-04: Implemented Option A (in-graph ComfyUI inpaint pass), updated workflow JSON + README, validated with real ComfyUI single-shot before/after comparison and the full existing test suite (113 passed, no regressions). Ran live A/B re-validation of Story 5.5's SCP-096 comparison (Task 5); Variant A completed clean with the fix confirmed across multiple real shots; Variant B result and score comparison recorded in Story 5.5's own file.
- 2026-07-04: Code review (3-layer adversarial: Blind Hunter, Edge Case Hunter, Acceptance Auditor). Patched: added a dedicated inpaint negative prompt (node `"15"`) instead of reusing the per-shot node `"7"`; generated and committed the missing composited-frame evidence (`composited-frame-after-fix.png`) to actually satisfy AC5's wording; corrected the Dev Agent Record's "faint floor shadow" characterization to match what the evidence image shows; corrected the README's Fallback-behavior section (background output now transitively depends on segmentation succeeding — a new, previously-undocumented coupling); softened an overstated VAE-round-trip-fidelity claim; documented the `grow_mask_by`/`denoise` rationale; added an inline deprecation warning to the legacy rembg workflow's node `"9"` title; added a regression test loading the real workflow JSON to guard the new node wiring. Deferred (needs a design decision, not a doc/JSON fix): the image stage now fails the *entire run* if ComfyUI's segmentation node errors on any single shot (previously only that shot's character layer was lost) — flagged in the README, not fixed at the Python level pending a decision on desired degrade-vs-fail behavior. Also deferred as pre-existing/out-of-scope quality-ceiling items already tracked above: LoRAs remaining active during the inpaint pass, and the inpaint prompt/seed being scene-agnostic. Fixes committed as 4 split commits (feat/fix/test/docs); 114/114 tests pass.
- 2026-07-04: Status set to `done` — all findings from the code review are either patched (committed) or explicitly deferred with rationale above; no outstanding blocking issues against AC1-AC5.

## Saved Questions / Clarifications

- Option A (inpaint) vs Option B (second generation pass) tradeoff — extra ComfyUI compute cost per shot needs measuring before committing; not decided at story-creation time.
- **Open from code review:** should a ComfyUI segmentation-node error on one shot fail the whole run (current behavior after 5.7) or degrade that shot to background-only (pre-5.7 behavior)? Needs a product decision, not just a code fix — see README's Fallback behavior section.
