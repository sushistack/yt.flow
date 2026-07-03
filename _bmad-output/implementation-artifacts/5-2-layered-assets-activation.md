# Story 5.2: Layered Assets Activation

Status: ready-for-dev

<!-- Completion note: Ultimate context engine analysis completed - comprehensive developer guide created -->

## Story

As Jay,
I want the already-built layered-asset pipeline (Story 1.6b image split + Story 1.9c character idle-motion overlay) to actually run in real renders,
so that videos show an independently-moving character over a panning background instead of a single flat Ken-Burns image.

## Context

Live render review on 2026-07-03 for run `eb522cf9` / SCP-096 found that the transparent character overlay path never appeared in real output even though the code for layered image assets and video overlay already exists.

Confirmed causes:

- `.env` does not define `YTFLOW_COMFYUI_LAYERED`, so `Settings.comfyui_layered` remains its default `False`.
- The current baseline workflow `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` has only one `SaveImage` output node: node `"9"` with prefix `ytflow`.
- Current settings expect two output nodes when layered mode is on: `YTFLOW_COMFYUI_BACKGROUND_NODE` and `YTFLOW_COMFYUI_CHARACTER_NODE`, defaulting to `"9"` and `"10"`.

This is primarily an asset/config/live-verification story. Do not rewrite `image_node` or `video_node` unless the chosen ComfyUI workflow needs a second prompt injection path that the current code cannot express.

## Acceptance Criteria

1. Given a new layered ComfyUI workflow JSON, then it has two output nodes: one opaque background PNG and one transparent character PNG after background removal; the output node IDs match `Settings.comfyui_background_node` and `Settings.comfyui_character_node`.
2. Given local ComfyUI at `YTFLOW_COMFYUI_URL` (default `http://127.0.0.1:8188`), when the new workflow is submitted directly, then ComfyUI accepts it and produces the two expected outputs without validation rejection.
3. Given the character output, when `image_node` receives it, then `_has_alpha()` accepts it as PNG color type 4 or 6; an opaque character output is treated as an image-stage error.
4. Given `.env` contains `YTFLOW_COMFYUI_LAYERED=true`, the new workflow path, and the correct background/character node IDs, when a real run reaches the image stage, then `workspace/{run_id}/images/` contains per-shot `*_background.png`, optional `*_character.png`, and compatibility `*.png` files, and `ShotData.background_path` / `ShotData.character_path` are populated from the image-stage state.
5. Given at least one scene has `character_path`, when `video_node` renders the final video, then it uses the 1.9c layered path: background `zoompan`, character scale-to-motion-safe box, `overlay=...:eval=frame`, then subtitles; the final mp4 visibly shows independent character idle motion over the background.
6. Given background removal fails or no character output is produced for a shot, when `image_node` completes, then `character_path` is `None`, `background_path` remains set, and downstream video rendering continues with the background-only fallback.
7. Given the workflow JSON is added, then a README next to it documents required ComfyUI custom nodes, install steps, expected output node IDs, and the exact `.env` variables used for activation.
8. Given the story is complete, then a live validation note records the run ID, image-stage artifact check, video-stage overlay check, and any background-only fallbacks observed.

## Tasks / Subtasks

- [ ] Choose and install a background-removal custom node for the local ComfyUI environment. Prefer a maintained ComfyUI custom node that returns an RGBA image or image+mask suitable for alpha output. Document install commands and model/download requirements in the workflow README. (AC: 1, 2, 3, 7)
- [ ] Create `data/workflows/comfyui_sdxl_anime_lora_layered_api.json` from the existing SDXL+LoRA baseline, preserving positive/negative prompt injection at nodes `"6"` and `"7"` unless code changes are explicitly required. (AC: 1)
- [ ] Ensure the layered workflow has two real output nodes:
  - background: opaque PNG, recommended node ID `"9"` unless the workflow requires a different ID
  - character: RGBA PNG after background removal, recommended node ID `"10"` unless the workflow requires a different ID
  - If IDs differ, set `YTFLOW_COMFYUI_BACKGROUND_NODE` and `YTFLOW_COMFYUI_CHARACTER_NODE` accordingly. (AC: 1, 4)
- [ ] Submit the workflow directly to ComfyUI before running yt.flow. Confirm both output node IDs appear in the returned outputs/history payload and that the character PNG has an alpha channel. (AC: 2, 3)
- [ ] Add `data/workflows/README-layered-assets.md` documenting:
  - custom node name/repo and install method
  - required models and where ComfyUI expects them
  - workflow file path
  - output node ID mapping
  - `.env` variables for activation
  - direct ComfyUI validation procedure
  - known fallback behavior when character extraction fails (AC: 6, 7)
- [ ] Wire local `.env` for the live run:
  - `YTFLOW_COMFYUI_LAYERED=true`
  - `YTFLOW_COMFYUI_WORKFLOW_PATH=data/workflows/comfyui_sdxl_anime_lora_layered_api.json`
  - `YTFLOW_COMFYUI_BACKGROUND_NODE=<background SaveImage node id>`
  - `YTFLOW_COMFYUI_CHARACTER_NODE=<character SaveImage node id>`
  Do not commit secrets; if a checked-in example file exists, add only non-secret example keys there. (AC: 4)
- [ ] Run one real pipeline execution or image-stage retry with ComfyUI mock mode off. At the image gate, verify the workspace contains `*_background.png` and, where extraction succeeds, `*_character.png`; inspect the run state through the stage artifacts/API or checkpoint-derived artifact view. (AC: 4, 6)
- [ ] Run or retry the video stage and inspect the final mp4 frames. Confirm at least one scene uses character overlay motion; if no `character_path` exists, the story is not complete unless the validation note explains why background removal produced no characters and includes the corrective action. (AC: 5, 8)
- [ ] Run focused automated tests after asset/config changes:
  - `uv run pytest tests/pipeline/nodes/test_image.py tests/pipeline/nodes/test_video.py`
  - If config/example files change, also run `uv run pytest tests/test_config.py`
  - If API artifact presentation is touched, also run `uv run pytest tests/api/test_stage_artifacts.py tests/api/test_stages.py` (AC: 3, 4, 5, 6)

## Dev Notes

### Current Implementation State

- `src/yt_flow/config.py` already defines:
  - `comfyui_layered: bool = False`
  - `comfyui_background_node: str = "9"`
  - `comfyui_character_node: str = "10"`
  These map to `YTFLOW_COMFYUI_LAYERED`, `YTFLOW_COMFYUI_BACKGROUND_NODE`, and `YTFLOW_COMFYUI_CHARACTER_NODE` through the `YTFLOW_` env prefix.
- `src/yt_flow/pipeline/nodes/image.py` already implements layered mode:
  - `_generate_layered_shot()` writes `scene_{scene_num:03d}_{shot_id}_background.png`, optional `*_character.png`, and compatibility `scene_{...}.png`.
  - `_has_alpha()` accepts only PNG color type 4 or 6 for character outputs.
  - Missing character output is allowed and yields `character_path=None`; missing background output is an error.
  - Prompt injection currently targets workflow nodes `"6"` and `"7"` only.
- `src/yt_flow/pipeline/nodes/video.py` already implements the layered rendering path:
  - `_compose_scene()` prefers `background_path` over `image_path`.
  - If `character_path` exists, FFmpeg uses `filter_complex` with background zoompan, character downscale, `overlay=...:eval=frame`, and subtitles.
  - If `character_path` is `None`, it falls back to the non-layered Ken-Burns path.
  - A set-but-missing `character_path` fails loudly before FFmpeg.
- `src/yt_flow/domain/state.py` already includes `ShotData.background_path` and `ShotData.character_path`.
- Current `.env` key list does not include `YTFLOW_COMFYUI_LAYERED`, `YTFLOW_COMFYUI_WORKFLOW_PATH`, `YTFLOW_COMFYUI_BACKGROUND_NODE`, or `YTFLOW_COMFYUI_CHARACTER_NODE`; add them locally for validation.

### Files Expected To Change

- `data/workflows/comfyui_sdxl_anime_lora_layered_api.json` (new): layered workflow export in ComfyUI API format.
- `data/workflows/README-layered-assets.md` (new): install, node-ID, env, and validation instructions.
- `.env` (local only): activation values for the live run. Do not commit secrets.
- Optional checked-in example/config docs if the repo has an established example env file. Keep it non-secret.

### Files To Avoid Changing Unless Proven Necessary

- `src/yt_flow/pipeline/nodes/image.py`: already supports layered outputs. Modify only if the new workflow requires separate background and character positive prompts that cannot use the current node `"6"` / `"7"` injection pair.
- `src/yt_flow/pipeline/nodes/video.py`: already supports character overlay and fallback. Do not change motion constants in this story; intensity belongs to Story 5.3.
- `src/yt_flow/domain/state.py`: already has the required state fields.
- API/UI artifact code: only touch if the existing stage artifact view cannot expose `background_path` / `character_path` clearly enough for validation.

### Architecture Guardrails

- Preserve AD-1 layering: pipeline nodes may import `domain` and `config`, but not `db`, `api`, or service-layer orchestration.
- Preserve AD-2 state authority: artifact paths live in `PipelineState`; do not add a DB table for layered assets.
- Preserve AD-4 node purity: `image_node` and `video_node` return state updates and trace metadata only; they do not emit SSE, write DB rows, or handle gate approval.
- Preserve AD-10: ComfyUI reachability remains an image-stage concern, not app startup; Langfuse tracing failures must remain non-fatal.

### Workflow Design Guidance

- Start from `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json`; it currently has `CLIPTextEncode` nodes `"6"` / `"7"` and a single `SaveImage` node `"9"`.
- The safest first version is one shared generation branch feeding:
  - a background output, and
  - a background-removal branch that extracts the character as RGBA.
- If that produces poor character isolation because the generated full image contains too much background, document it and consider a small code follow-up for separate character prompt injection. Do not silently expand this story into prompt-chain redesign.
- If the selected custom node outputs image+mask rather than direct RGBA, add the necessary ComfyUI image/mask combine nodes inside the workflow so yt.flow still receives PNG bytes with alpha at the configured character output node.

### Previous Story Intelligence

Story 5.1 exists as a draft and is not marked complete in `sprint-status.yaml`. It targets `video.py` transitions/chapter cards, while this story targets ComfyUI workflow activation and existing layered overlay behavior. Do not assume Story 5.1 changes are present.

Adjacent implementation history matters more:

- Story 1.6b implemented `image_node` layered asset support and tests in `tests/pipeline/nodes/test_image.py`.
- Story 1.9c implemented character idle-motion overlay support and tests in `tests/pipeline/nodes/test_video.py`.
- Story 1.13 added optional LLM character angle pre-selection in `video_node`; it may overwrite `character_path` when an angle selector is injected. This story should verify live overlay behavior with that existing path, not remove it.

### Git Intelligence

Recent commits are focused on Prompt Ops and variant-label wiring (`6-1`) plus dependency/test housekeeping. No recent commit changes the layered image/video code path. Treat the existing layered implementation and tests as stable unless focused validation proves otherwise.

### Latest Technical Notes

- Official ComfyUI documentation confirms output node IDs in API responses correspond to output nodes such as `SaveImage` in the workflow JSON. Use this to validate that `YTFLOW_COMFYUI_BACKGROUND_NODE` and `YTFLOW_COMFYUI_CHARACTER_NODE` match the workflow outputs. Source: https://docs.comfy.org/development/cloud/overview
- Candidate background-removal custom node families to evaluate:
  - `1038lab/ComfyUI-RMBG`: broad background removal / segmentation support including RMBG, BiRefNet, SAM-family options. Source: https://github.com/1038lab/ComfyUI-RMBG
  - `Jcd1230/rembg-comfyui-node`: simple rembg node, with `rembg[gpu]` recommended where supported. Source: https://github.com/Jcd1230/rembg-comfyui-node
  - `john-mnz/ComfyUI-Inspyrenet-Rembg`: InSPyReNet-based background removal, installable through ComfyUI-Manager per project docs. Source: https://github.com/john-mnz/ComfyUI-Inspyrenet-Rembg
- Pick the node that works reliably in Jay's local ROCm/ComfyUI environment; story success depends on live output correctness, not on choosing the most complex segmentation model.

## Project Structure Notes

- Runtime artifacts stay under `workspace/{run_id}/images/` and `workspace/{run_id}/video.mp4`.
- Workflow assets belong under `data/workflows/`.
- Tests remain under `tests/pipeline/nodes/` for node behavior and `tests/api/` only if artifact API/UI display changes.
- No `project-context.md` file was found from the workflow persistent-facts glob during story creation.

## References

- `_bmad-output/planning-artifacts/epics.md#Story-5.2` - Epic 5 scope and ordering.
- `_bmad-output/planning-artifacts/epics.md#Story-1.6b` - layered image asset contract.
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Invariants-&-Rules` - AD-1, AD-2, AD-4, AD-10.
- `src/yt_flow/config.py` - existing layered settings and env prefix.
- `src/yt_flow/pipeline/nodes/image.py` - layered image generation, alpha validation, trace metadata.
- `src/yt_flow/pipeline/nodes/video.py` - background/character composition path and fallback behavior.
- `tests/pipeline/nodes/test_image.py` - layered image behavior tests.
- `tests/pipeline/nodes/test_video.py` - character overlay behavior tests.

## Dev Agent Record

### Agent Model Used

TBD by dev-story agent.

### Debug Log References

### Completion Notes List

### File List
