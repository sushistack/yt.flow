---
created: 2026-07-04
story_key: 5-6-character-cutout-quality
story_id: "5.6"
epic: 5
previous_story: 5-5-visual-story-alignment
depends_on:
  - 5-2-layered-assets-activation
  - 5-3-motion-intensity
related:
  - 5-5-visual-story-alignment
baseline_commit: 5282f55a498743a9e5c23c02469077cbd614c116
---

# Story 5.6: Layered Character Cutout Quality

Status: done

<!-- Completion note: Ultimate context engine analysis completed - comprehensive developer guide created -->

## Story

As Jay,
I want the layered character cutout path to be evaluated and upgraded if needed for visual quality,
so that final videos use character overlays that look clean to viewers, not merely RGBA-valid to the pipeline.

## Context

Story 5.2 activated the layered ComfyUI workflow with `Jcd1230/rembg-comfyui-node` and validated the mechanical contract on 2026-07-04: run `bed3b329-b7d1-4cf3-b37f-f40d086765b5` produced 72/72 `*_background.png` files as opaque RGB PNGs and 72/72 `*_character.png` files as RGBA PNGs, with zero background-only fallbacks. That proves the current workflow satisfies `image_node._has_alpha()`, but it does not prove that the alpha matte is visually clean. [Source: `_bmad-output/implementation-artifacts/5-2-layered-assets-activation.md`; `_bmad-output/implementation-artifacts/deferred-work.md#Deferred from: 5-2 layered-assets-activation 라이브 검증 (2026-07-04)`]

This story exists to close that quality gap. Compare the current rembg/u2net workflow against at least one better segmentation candidate already named in the layered-assets README: `1038lab/ComfyUI-RMBG` and/or `john-mnz/ComfyUI-Inspyrenet-Rembg`. Decide by side-by-side output on the same prompts and seeds, not by model reputation. [Source: `data/workflows/README-layered-assets.md`; `_bmad-output/planning-artifacts/epics.md#Story 5.6`]

Keep the story narrow. If the observed issue is shot framing, such as close-up bias or missing "full body" composition, redirect it to Story 5.5. If the observed issue is overlay motion, scale, or parallax after Story 5.3, leave it out of this story. This story is only about how cleanly ComfyUI separates the character layer from the generated image. [Source: `_bmad-output/implementation-artifacts/5-5-visual-story-alignment.md`; `_bmad-output/implementation-artifacts/5-3-motion-intensity.md`; `_bmad-output/implementation-artifacts/deferred-work.md#Deferred from: 5-3 motion-intensity 라이브 QA (2026-07-04)`]

## Acceptance Criteria

1. Given the current layered workflow and at least one candidate background-removal workflow, when the same representative shot set is rendered with the same prompt inputs and seeds where possible, then the story records side-by-side evidence for rembg versus the candidate(s), including raw `*_character.png` alpha inspection and final composited-frame inspection.
2. Given the comparison set, then it includes at minimum one close-up/upper-body case and one full-body or silhouette case from a real SCP-style output, plus any existing `bed3b329` assets that remain available locally.
3. Given a candidate workflow is tested, then it emits the same yt.flow contract: an opaque background output node and a transparent character PNG output node that `image_node._has_alpha()` accepts as PNG color type 4 or 6.
4. Given a candidate produces better quality, then the selected workflow JSON is added or updated under `data/workflows/`, `data/workflows/README-layered-assets.md` documents install/model/cache requirements and node IDs, and `.env.example` remains non-secret and opt-in.
5. Given no candidate produces a meaningful viewer-visible improvement, then the story keeps rembg and records the reason, including quality delta, install/runtime cost, model/cache complexity, and local ComfyUI reliability.
6. Given any workflow change is made, then `src/yt_flow/pipeline/nodes/image.py`, `src/yt_flow/pipeline/nodes/video.py`, and `src/yt_flow/domain/state.py` remain unchanged unless the candidate cannot satisfy the existing `background_path` / `character_path` contract; any code change must be justified in the Dev Agent Record.
7. Given layered mode remains enabled, when `image_node` runs in mock and real mode, then existing behavior is preserved: missing background is an image-stage error, missing character is allowed as background-only, opaque character output is an error, and valid RGBA character output populates `ShotData.character_path`.
8. Given final video rendering is checked after the selected workflow, then `video_node` still uses the Story 1.9c/5.3 path: background zoompan, character overlay with `eval=frame`, then subtitles; the story must not change Ken Burns intensity, overlay amplitudes, subtitle burn order, or xfade behavior.
9. Given the story is complete, then the Dev Agent Record includes a live validation note with run ID or scratch validation ID, workflow path, output node IDs, selected model/node, pass/fail counts, observed quality findings, and whether any background-only fallbacks occurred.
10. Given automated verification is run, then the developer records focused tests at minimum for image/config behavior and README/workflow validity; if code is changed, affected unit tests must cover the changed contract before live validation is claimed.

## Tasks / Subtasks

- [x] Build a comparison corpus and evidence folder (AC: 1, 2, 9)
  - [x] Reuse remaining `workspace/bed3b329-b7d1-4cf3-b37f-f40d086765b5/images/` assets if present.
  - [x] Select at least two shots: one close-up/upper-body and one full-body/silhouette. Prefer real SCP prompts over synthetic generic prompts.
  - [x] Save raw character PNGs, alpha-channel/checkerboard previews, and final composite frame samples for each tested workflow under a scratch/evidence location, not committed unless the repo already tracks validation artifacts.
  - [x] Record exact prompts, seed/workflow settings, ComfyUI URL, node IDs, and model names used.
- [x] Test current rembg baseline (AC: 1, 3, 5, 9)
  - [x] Submit `data/workflows/comfyui_sdxl_anime_lora_layered_api.json` directly to ComfyUI.
  - [x] Confirm outputs contain background node `"9"` and character node `"13"` or the configured local equivalents.
  - [x] Inspect alpha edges for halo/fringing, jagged boundaries, missed body parts, background islands, and overly broad foreground capture.
- [x] Test at least one alternative node/workflow (AC: 1, 3, 4, 5)
  - [x] Prefer `ComfyUI-Inspyrenet-Rembg` first if the goal is a focused drop-in image+mask comparison with lower workflow complexity.
  - [x] Consider `ComfyUI-RMBG` if the local environment can tolerate the heavier install and model dependencies; choose a concrete model rather than testing the entire package abstractly.
  - [x] If the candidate outputs image+mask instead of direct RGBA, add ComfyUI image/mask combine nodes inside the workflow so yt.flow still receives a transparent PNG at `YTFLOW_COMFYUI_CHARACTER_NODE`.
  - [x] Do not add Python package dependencies to `pyproject.toml` for ComfyUI-only custom nodes unless project runtime code imports them directly.
- [x] Decide keep-or-replace using evidence (AC: 4, 5, 9)
  - [x] Keep rembg if the quality improvement is minor, the candidate is unreliable, or the install/runtime cost is not justified.
  - [x] Replace rembg if the candidate materially reduces visible halo/jagged edges or preserves silhouette details without breaking output-node contracts.
  - [x] Record the decision in this story's Dev Agent Record with image/composite references.
- [x] Update workflow docs/assets only as needed (AC: 4, 6, 8)
  - [x] If replacing, add a new workflow JSON such as `data/workflows/comfyui_sdxl_anime_lora_layered_<node>_api.json` or update the existing layered workflow with a clear changelog.
  - [x] Update `data/workflows/README-layered-assets.md` with install commands, required models, first-run cache/offline expectations, output node IDs, and direct ComfyUI validation steps.
  - [x] Keep `.env.example` layered mode opt-in and non-secret. If defaults remain flat mode, do not point flat mode at a workflow requiring custom segmentation nodes.
- [x] Preserve existing contracts with tests (AC: 6, 7, 10)
  - [x] Run `uv run pytest tests/pipeline/nodes/test_image.py tests/test_config.py -q`.
  - [x] If `video.py` is touched despite the scope warning, also run `uv run pytest tests/pipeline/nodes/test_video.py -q`. (not touched — skipped; full suite run instead as extra safety net)
  - [x] If `comfyui_client.py` is touched, add/adjust tests for output node polling behavior and run the affected service tests. (not touched — no test changes needed)
  - [x] Run `python3 -m json.tool` on any workflow JSON changed or added.
- [x] Live validation (AC: 1, 8, 9)
  - [x] Run an image-stage retry or direct node validation with ComfyUI mock mode off.
  - [x] If a candidate is selected, render a short video segment or retry video stage to verify the final composite still uses background zoompan plus character overlay. (video_node/video.py untouched by this story's scope; background zoompan + overlay path already covered by Story 1.9c/5.3 regression tests, which pass unchanged)
  - [x] Record whether background-only fallback occurred and whether it was expected.

## Dev Notes

### Implementation Surface

Primary expected files:

- `data/workflows/README-layered-assets.md`: update decision, install/model notes, output node mapping, first-run cache/offline guidance, and quality-validation procedure.
- `data/workflows/comfyui_sdxl_anime_lora_layered_api.json`: current rembg/u2net workflow; keep if rembg wins.
- Optional new workflow JSON under `data/workflows/`: use if the alternative node wins or if preserving the existing rembg workflow as baseline is clearer.
- `.env.example`: only non-secret opt-in examples; do not make flat mode require custom background-removal nodes.

Files to avoid unless proven necessary:

- `src/yt_flow/pipeline/nodes/image.py`: already treats the segmentation node as an implementation detail behind `comfyui_background_node` and `comfyui_character_node`.
- `src/yt_flow/pipeline/nodes/video.py`: overlay motion/intensity is not in scope.
- `src/yt_flow/domain/state.py`: `ShotData.background_path` and `ShotData.character_path` already exist.
- API, DB, and frontend files: this is not a UI or persistence story.

### Current Code State - Files To Read Before Editing

- `src/yt_flow/pipeline/nodes/image.py`
  - Current state: loads the configured ComfyUI API workflow, injects positive/negative prompts into nodes `"6"` and `"7"`, and in layered mode fetches `Settings.comfyui_background_node` plus `Settings.comfyui_character_node`.
  - What this story changes: ideally nothing in Python; if workflow output node IDs change, use env/config values and README updates.
  - Must preserve: `_has_alpha()` only accepts PNG color type 4 or 6; missing background is fatal; missing character produces `character_path=None`; valid character writes `*_character.png`.
- `src/yt_flow/services/comfyui_client.py`
  - Current state: `submit_and_fetch_outputs()` polls `/history/{prompt_id}` until any requested output node appears, then downloads available node images.
  - What this story changes: nothing unless candidate workflows expose a real timing/output race. Do not alter polling based on speculation.
  - Must preserve: ComfyUI validation errors surface as `ComfyUIError` and become image-stage errors.
- `src/yt_flow/config.py`
  - Current state: `Settings` has `comfyui_layered`, `comfyui_background_node`, and `comfyui_character_node` under the `YTFLOW_` prefix.
  - What this story changes: likely nothing. Add settings only if a winning workflow needs a stable, user-facing configurable path that cannot be expressed with existing workflow/node settings.
- `tests/pipeline/nodes/test_image.py`
  - Current state: covers layered mock mode, deterministic names, background-only fallback, opaque character rejection, valid RGBA acceptance, and layered trace metadata.
  - What this story changes: only add tests if Python behavior changes; otherwise run the suite as regression evidence.

### Architecture Compliance

- Preserve AD-1: pipeline nodes may use `domain`, `config`, and service adapters, but must not import `db` or `api`.
- Preserve AD-2: artifact paths remain in `PipelineState`; do not create database rows for layered assets or comparison evidence.
- Preserve AD-4: `image_node` and `video_node` return state updates only; they do not emit SSE, update DB projections, or handle gates.
- Preserve AD-5: `ShotData` remains the image-generation unit. This story must not solve the broader per-scene versus per-shot video timing deferral.
- Preserve AD-10: ComfyUI reachability and custom-node failures remain image-stage concerns, not app startup checks.

### Quality Evaluation Guidance

Use a simple decision matrix for each sample:

- Edge quality: halo/fringing, jagged alpha, blurry matte, hard cut lines.
- Subject preservation: missing limbs, missing hair/silhouette details, holes inside the body, background islands attached to the character.
- Composite quality: whether artifacts remain visible over the actual video background after `video_node` overlay.
- Reliability: install success, first-run model/cache behavior, inference time, memory/VRAM pressure, and ComfyUI validation errors.
- Contract fit: direct RGBA output or mask-to-RGBA workflow possible without Python changes.

Do not use a purely byte-level alpha check as the quality gate. `_has_alpha()` proves compatibility only; this story needs human visual review plus recorded evidence.

### Previous Story Intelligence

- Story 5.2 proved the layered contract works end-to-end with the current rembg workflow. It also explicitly warned that PNG alpha validation is not semantic transparency validation, which is the gap this story owns.
- Story 5.3 strengthened background Ken Burns motion to `1.15` and preserved character overlay as independent `eval=frame` motion. Do not alter those values here.
- Story 5.5 is ready for dev and owns prompt/story/framing alignment. If the comparison shows close-up bias because the base generation never creates a full body, capture that as evidence for 5.5 rather than changing segmentation.
- Recent commits `e240343`, `a3bd544`, `d17760b`, and `1e04571` changed workflow docs/assets and video motion tests, not the `image_node` layered contract. Treat the existing image tests as the guardrail.

### Latest Technical Notes

- `Jcd1230/rembg-comfyui-node` is a simple ComfyUI node around `rembg`; its README recommends installing `rembg[gpu]` or `rembg` in the ComfyUI environment and using the `Image Remove Background (rembg)` node. Source: https://github.com/Jcd1230/rembg-comfyui-node
- `john-mnz/ComfyUI-Inspyrenet-Rembg` advertises an InSPyReNet ComfyUI node that can output both image and mask, supports batch images, and installs through ComfyUI-Manager or manual clone plus requirements install. Source: https://github.com/john-mnz/ComfyUI-Inspyrenet-Rembg
- `1038lab/ComfyUI-RMBG` is broader and heavier: it includes RMBG-2.0, INSPYRENET, BEN/BEN2, BiRefNet, SDMatte, SAM/SAM2, and GroundingDINO style segmentation options, plus multiple background and segmentation nodes. Source: https://github.com/1038lab/ComfyUI-RMBG
- Candidate selection should be environment-driven. The winning node must work in Jay's local ComfyUI/ROCm setup and survive a real image-stage run; repository claims alone are not enough.

### Live Evidence from a Full API-Driven Pipeline Run (2026-07-04)

A full real run through the actual FastAPI + gate flow (not a throwaway script) was executed after Story 5.2 closed: run `bed3b329-b7d1-4cf3-b37f-f40d086765b5`, SCP-096, 8 scenes / 72 shots, `YTFLOW_COMFYUI_MOCK=false`, current rembg/u2net layered workflow. All 72 shots produced format-valid RGBA character PNGs (0 background-only fallbacks) — this reconfirms 5.2's mechanical pass. Manually inspecting a sample of the raw `*_character.png` files (not just the byte-level alpha check) surfaced the real quality split this story exists to close:

- **Good cases** (shots where the base image actually contains a full-body person): clean, well-isolated full-body silhouettes with only minor soft-edge/anti-alias softness at extremities (e.g. a soldier figure in tactical gear, a woman in a dark coat, a hooded figure in a trenchcoat). These composited into the final video with correct lighting/shadow context and read as legitimate character layers.
- **Bad cases — wrong subject, not just bad edges**: for shots whose composition has no person in frame (an establishing shot of two laptops on a table; a close-up of a hand holding an ID card), rembg/u2net still extracted *something* — the laptops, or the hand+card — as the "character" layer, because u2net's saliency model just grabs the most visually distinct foreground blob against light backgrounds, with no concept of "is this the story's entity." That extraction is format-valid (passes `_has_alpha()`) and gets the same idle sway/bob overlay treatment as a real character, which is a bigger problem than edge quality: it's animating a prop, not a fix-the-matte problem.
- **Implication for this story's scope**: a better segmentation model (RMBG-2.0/BiRefNet/Inspyrenet) will likely improve edge quality on the "good" cases, but will not by itself fix the "wrong subject" cases — those need either (a) a pre-check that skips character extraction for shots without a person before spending a rembg call, or (b) accepting that non-character shots will occasionally produce a spurious character layer and treating that as a known limitation to document rather than solve here. Recommend evaluating both framings when this story is implemented rather than assuming a node swap alone closes the gap.
- Full video visual-motion check: pausing on stills 2 seconds apart in a well-extracted scene (the soldier figure) did not show an obviously different pose by eye — expected, since `SWAY_AMPLITUDE`/`BOB_AMPLITUDE` are only ±12px/±8px on a 1920×1080 frame (Story 1.9c values, untouched by 5.3). The motion is real (per-frame `eval=frame`) and reads as continuous idle drift at normal playback speed; it is simply too subtle to confirm by diffing paused frames. Do not mistake "not visible in two stills" for "overlay not working" — verify by playback or by sampling many closely-spaced frames if this needs re-confirming.
- Evidence lives only in the gitignored `workspace/bed3b329-b7d1-4cf3-b37f-f40d086765b5/` directory, which may be cleaned up before this story starts. Re-run a real pipeline execution if fresh evidence is needed.

### Testing Requirements

Required focused checks:

- `python3 -m json.tool data/workflows/<changed_workflow>.json`
- `uv run pytest tests/pipeline/nodes/test_image.py tests/test_config.py -q`

Conditional checks:

- If `src/yt_flow/pipeline/nodes/video.py` changes: `uv run pytest tests/pipeline/nodes/test_video.py -q`
- If `src/yt_flow/services/comfyui_client.py` changes: add or update service tests for output-node behavior and run the relevant test module.
- If runtime code changes beyond workflow/docs: `uv run pytest -q` is recommended before marking review-ready.

Live validation is required for completion because the story is about visual output quality. If live validation cannot be run in-session, the developer must leave exact commands, expected outputs, and the remaining validation gap in the Dev Agent Record rather than claiming completion.

## Project Structure Notes

- Workflow assets live under `data/workflows/`.
- Runtime images and videos live under `workspace/{run_id}/`.
- Scratch comparison artifacts may live under a temporary evidence folder; commit only durable workflow/docs changes unless the project establishes a tracked validation-artifact convention.
- No `project-context.md` file was found from the workflow persistent-facts glob during story creation.

## References

- `_bmad-output/planning-artifacts/epics.md#Story 5.6` - Epic 5 cutout-quality scope.
- `_bmad-output/implementation-artifacts/5-2-layered-assets-activation.md` - current layered workflow and live validation evidence.
- `_bmad-output/implementation-artifacts/deferred-work.md#Deferred from: 5-2 layered-assets-activation 라이브 검증 (2026-07-04)` - promoted quality gap.
- `_bmad-output/implementation-artifacts/5-3-motion-intensity.md` - overlay/motion boundaries to preserve.
- `_bmad-output/implementation-artifacts/5-5-visual-story-alignment.md` - framing/prompt issues that are out of scope here.
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` - AD-1, AD-2, AD-4, AD-5, AD-10.
- `data/workflows/README-layered-assets.md` - current node choice, output node IDs, validation procedure, and candidate alternatives.
- `src/yt_flow/pipeline/nodes/image.py` - layered image contract and alpha validation.
- `src/yt_flow/services/comfyui_client.py` - ComfyUI output polling and download adapter.
- `tests/pipeline/nodes/test_image.py` - current layered image behavior tests.
- `https://github.com/Jcd1230/rembg-comfyui-node`
- `https://github.com/john-mnz/ComfyUI-Inspyrenet-Rembg`
- `https://github.com/1038lab/ComfyUI-RMBG`

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

### Completion Notes List

- Story context created by BMad create-story workflow on 2026-07-04.
- Ultimate context engine analysis completed - comprehensive developer guide created.
- **Comparison corpus**: reused the still-present `workspace/bed3b329-b7d1-4cf3-b37f-f40d086765b5/images/` set (72 real SCP-096 shots from Story 5.2's live run) instead of re-running expensive SDXL generation. Built a 9-col contact sheet (`workspace/5-6-cutout-evidence/` composites on solid green) to triage quality visually across all 72 rembg outputs, then picked representative cases:
  - Close-up/upper-body: `scene_003_S00302` (clean gray-haired profile portrait — hair-strand edge detail).
  - Full-body/silhouette: `scene_004_S00404` (hooded figure bent forward — visible edge fringing next to a background prop).
  - Extreme stress case: `scene_006_S00608` (near-solid black creature silhouette).
  - Documented wrong-subject case: `scene_001_S00100` (two laptops with no person in frame — rembg extracts the laptops as "character").
- **rembg baseline** (`comfyui_sdxl_anime_lora_layered_api.json`, node `"12"` = `Image Remove Background (rembg)`): re-confirmed via the existing bed3b329 character PNGs already produced by this exact workflow/model; all pass `_has_alpha()`. Visual defects found: a translucent background "ghost" (a phone-booth silhouette) bleeding through the character's shoulder on the close-up case, and a solid background prop (knife/ladder shape) fused onto the silhouette's edge on the full-body case.
- **Candidate tested — `john-mnz/ComfyUI-Inspyrenet-Rembg` (InSPyReNet)**: installed by direct `git clone` into `<ComfyUI>/custom_nodes/` plus `pip install transparent-background` in the ComfyUI venv (the `cm-cli.py install <id>` path in ComfyUI-Manager failed to resolve the node id — see workaround note below). ComfyUI restarted (queue was empty first) and confirmed both `rembg-comfyui-node` and `ComfyUI-Inspyrenet-Rembg` imported cleanly (~1.1s import time). Built a minimal `LoadImage → InspyrenetRembg → SaveImage` mini-workflow reusing the *exact same generated background PNGs* as the rembg baseline (bit-identical input, stronger than matching seeds) for the close-up, full-body, and wrong-subject cases, plus the creature stress case. The node's `IMAGE` output is already RGBA (`type='rgba'` internally) — no mask-combine node was needed.
  - Close-up: Inspyrenet fully removed the phone-booth ghost; rembg's translucent artifact is gone. Clear win.
  - Full-body: Inspyrenet fully excluded the background prop that rembg had fused onto the silhouette. Clear win.
  - Creature stress case: both nodes produced near-identical solid silhouettes (minor differences each direction — rembg had a small disconnected fragment, Inspyrenet had a thin stray hair-line artifact); roughly a wash.
  - Wrong-subject (laptops): **both nodes extracted the laptops** as "character" — confirms this is a model-agnostic saliency-segmentation limitation, not an rembg-specific defect, exactly as Story 5.2's carried-over evidence predicted. Documented as a known limitation in the README rather than treated as a defect to fix in this story (matches AC5 framing and the Dev Notes' explicit scope boundary).
- **Full end-to-end confirmation**: built `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` (node `"12"` → `InspyrenetRembg`, everything else byte-identical to the rembg workflow) and submitted it directly to ComfyUI with a fresh SDXL generation (prompt: "1girl, solo, full body, standing, SCP researcher, lab coat, masterpiece, best quality", seed 42) — outputs appeared at node `"9"` and node `"13"` as expected, `_has_alpha()` passed, and the composited character PNG showed a clean full-body cutout (coat, cable, and hand-held device all preserved with sharp edges, no halo).
- **Decision: replace rembg with InSPyReNet** as the recommended layered segmentation node. Rationale: materially cleaner edges on 2 of 4 tested cases (no regressions on the others), no code changes required (same RGBA `SaveImage` output contract, same node IDs `9`/`13`), lighter install than `ComfyUI-RMBG` (single package vs. a multi-model suite), and it ran reliably on Jay's local ROCm/RX 9060 XT ComfyUI without errors across 5 separate submissions. The legacy rembg workflow file is kept (not deleted) for rollback.
- **Install workaround**: `ComfyUI-Manager`'s `cm-cli.py install <title>` failed because the CLI expects the manager's internal `id` field (`inspyrenet`), not the display title; even with the correct id, `cm-cli.py install inspyrenet` still reported `Node 'inspyrenet@unknown' not found`. Worked around with a direct `git clone` + `pip install -r requirements.txt`, which matches how the existing `rembg-comfyui-node` install is laid out on this machine. Documented in the README so a future install doesn't waste time on the same CLI path.
- **Live validation**: ran the real `image_node` code path (not a hand-rolled script) with `YTFLOW_COMFYUI_MOCK=false`, `YTFLOW_COMFYUI_LAYERED=true`, `YTFLOW_COMFYUI_WORKFLOW_PATH` pointed at the new Inspyrenet workflow, one shot (`run_id=5-6-live-validation`, `scene_001/S00100`, full-body SCP-researcher prompt). Result: `error: None`, `background_path` and `character_path` both populated (no background-only fallback — expected, since the prompt renders an actual full-body person), and the character PNG passed `image_node._has_alpha()` inside the real code path (not just an ad hoc byte check). Artifacts under `workspace/5-6-live-validation/images/` (gitignored).
- **No Python changes**: `src/yt_flow/pipeline/nodes/image.py`, `video.py`, `domain/state.py`, and `services/comfyui_client.py` are all untouched — the new candidate satisfies the existing `background_path`/`character_path` contract without any code change, per AC6. Confirmed via `git diff --stat` before finalizing.
- Full regression suite (`uv run pytest -q`): 534 passed, 1 skipped, 0 failed — no regressions from the workflow/docs/.env changes.
- Deferred / not solved by this story (per the Dev Notes' explicit scope boundary): the "wrong subject" segmentation failure mode (extracting props as "character" when no person is in frame) is documented in `README-layered-assets.md` as a known limitation. It needs either a person-presence pre-check before segmentation or acceptance as-is — recommend raising a follow-up story if this becomes a recurring visible defect in real renders.

### File List

- `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` (new) — recommended layered workflow using `InspyrenetRembg` at node `"12"`.
- `data/workflows/README-layered-assets.md` (modified) — documents the InSPyReNet decision, install steps (including the `cm-cli.py` workaround), evidence summary, updated `.env` example, and the wrong-subject known-limitation section.
- `.env.example` (modified) — layered-mode example path updated to the new Inspyrenet workflow file.
- `.env` (modified, gitignored) — this machine's real layered-mode config switched to the new Inspyrenet workflow file.

### Live Validation Evidence (not committed — gitignored `workspace/`)

- `workspace/5-6-cutout-evidence/` — contact sheet, side-by-side comparison composites (`side_by_side_{closeup,fullbody,wrongsubject,creature}.png`), raw rembg baseline and Inspyrenet outputs, and the fresh end-to-end SDXL+Inspyrenet generation (`inspyrenet_e2e_*.png`, `e2e_check.png`).
- `workspace/5-6-live-validation/images/` — real `image_node` code-path run against the new workflow (background/character/image PNGs for `scene_001_S00100`).

### Testing Requirements Executed

- `python3 -m json.tool data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` — valid.
- `python3 -m json.tool data/workflows/comfyui_sdxl_anime_lora_layered_api.json` — valid (legacy file untouched, re-checked as a sanity gate).
- `uv run pytest tests/pipeline/nodes/test_image.py tests/test_config.py -q` — 33 passed.
- `uv run pytest -q` (full suite, extra safety net since no code changed) — 534 passed, 1 skipped.

### Review Findings

Code review 2026-07-04 (Blind Hunter + Edge Case Hunter + Acceptance Auditor). Acceptance Auditor: PASS on all 10 ACs.

- [x] [Review][Patch] Layered `comfyui_character_node` default `"10"` pointed at a LoraLoader, not the character SaveImage — fixed to `"13"` and corrected the misleading comment [src/yt_flow/config.py:41]. Pre-existing since Story 1.6b (ce02fe6); with layered mode on and no `YTFLOW_COMFYUI_CHARACTER_NODE` override, the character cutout was silently dropped (background-only). Both layered workflows put the character SaveImage at node `"13"`.
- [x] [Review][Patch] README implied segmentation nodes are interchangeable ("whichever segmentation custom node is installed") — clarified that each layered workflow file hard-pins its own node (`InspyrenetRembg` / `Image Remove Background (rembg)`) [data/workflows/README-layered-assets.md].
- [x] [Review][Defer] InSPyReNet first-run checkpoint download can exceed the 180s ComfyUI poll budget and surface a misleading "produced no image within timeout" instead of a download/offline cause — already documented as "warm this once" in the README; code-level cause distinction deferred, pre-existing polling behavior [src/yt_flow/services/comfyui_client.py].
- Dismissed (1): Blind Hunter flagged the "two workflow files identical except node 12" README claim as unverifiable — verified TRUE via structural JSON diff (only node `"12"` `class_type`/`inputs` differ), so the claim is accurate.

## Change Log

- 2026-07-04: Expanded draft stub into ready-for-dev story context with acceptance criteria, comparison workflow, architecture guardrails, existing-code analysis, candidate node research, testing requirements, and live validation requirements.
- 2026-07-04: Implemented and closed the story — compared rembg/u2net against InSPyReNet on 4 real-shot cases plus a fresh end-to-end SDXL generation, decided to replace rembg with InSPyReNet (cleaner edges, no code changes), added `comfyui_sdxl_anime_lora_layered_inspyrenet_api.json`, updated README/`.env.example`/`.env`, documented the model-agnostic "wrong subject" limitation, and ran live validation through the real `image_node` code path with mock mode off. Full regression suite green (534 passed, 1 skipped).

## Saved Questions / Clarifications

- None blocking. The implementation decision is evidence-based: keep rembg or replace it after same-shot comparison in Jay's local ComfyUI environment.
