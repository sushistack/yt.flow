# Story 1.6: image_node

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want `image_node` to submit shot prompts to ComfyUI and write generated images to disk,
so that each `ShotData` has an `image_path` for downstream composition.

## Acceptance Criteria

1. Given ComfyUI running at `YTFLOW_COMFYUI_URL` and workflow JSON in config, when `image_node` runs with scenes containing `ShotData.image_prompt`, then each `ShotData.image_path` is set to an existing file under `workspace/{run_id}/images/`.
2. Given ComfyUI returns an HTTP error or workflow validation error for a prompt, when `image_node` encounters it, then `PipelineState.error` is set with `stage="image"` and `run_id`, and Langfuse captures the error detail.
3. Given `image_node` execution, when it completes, then a Langfuse span named `"image"` shows latency and ComfyUI request count.
4. Given `YTFLOW_COMFYUI_MOCK=true` in environment, when `image_node` runs, then it returns fixture images from `tests/fixtures/images/` instead of calling ComfyUI; all downstream contracts still pass.

## Tasks / Subtasks

- [ ] Add image-stage configuration and workflow asset handling (AC: 1, 4)
  - [ ] Add `YTFLOW_COMFYUI_URL`, `YTFLOW_COMFYUI_WORKFLOW_PATH`, and `YTFLOW_COMFYUI_MOCK` fields to `src/yt_flow/config.py`.
  - [ ] Create `data/workflows/` and copy `~/Documents/myWorkflows/comfyui_sdxl_anime_lora_workflow_api2.json` to `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json`.
  - [ ] Keep the workflow JSON as an API-format workflow, not UI-export-only format.
- [ ] Implement a small ComfyUI service client (AC: 1, 2)
  - [ ] Add `src/yt_flow/services/comfyui_client.py` for HTTP calls to local ComfyUI.
  - [ ] Submit workflow payloads to `POST /prompt`, poll or retrieve `GET /history/{prompt_id}`, and download image bytes via `GET /view`.
  - [ ] Surface validation failures from `error` / `node_errors` as image-stage failures.
- [ ] Implement `image_node` (AC: 1, 2, 3, 4)
  - [ ] Add `src/yt_flow/pipeline/nodes/image.py` with a pure async node function that accepts and returns `PipelineState`.
  - [ ] For every shot in every scene, inject `ShotData.image_prompt` into workflow node `"6"` and `ShotData.negative_prompt` into workflow node `"7"`.
  - [ ] Write outputs under `workspace/{run_id}/images/` with deterministic names such as `scene_{scene_num:03d}_{shot_id}.png`.
  - [ ] Return a new `PipelineState` value with updated `scenes`, `current_stage="image"`, and no in-place mutation of nested state.
  - [ ] In mock mode, copy or materialize fixture image files from `tests/fixtures/images/` into the run workspace and set the same `image_path` contract.
- [ ] Add Langfuse instrumentation and failure capture (AC: 2, 3)
  - [ ] Decorate or wrap the node so the stage span name is exactly `"image"`.
  - [ ] Record ComfyUI URL, workflow path, request count, output image count, and elapsed latency.
  - [ ] On failure, set `PipelineState.error` to a string carrying `stage=image`, `run_id`, and the root cause; also update the Langfuse observation with the exception detail.
- [ ] Add tests (AC: 1, 2, 3, 4)
  - [ ] Unit-test workflow prompt injection for nodes `"6"` and `"7"` without calling ComfyUI.
  - [ ] Unit-test `YTFLOW_COMFYUI_MOCK=true` produces existing image files and updates every shot image path.
  - [ ] Unit-test HTTP/validation failure creates image-stage error state.
  - [ ] Unit-test state immutability enough to catch accidental in-place edits of `PipelineState.scenes`.

## Dev Notes

### Story Context

Story 1.6 is the first real external-asset generation stage after `scenario_node`. It consumes the `SceneState.shots` emitted by Story 1.5 and prepares the image artifacts later consumed by `video_node` in Story 1.9. The image generation unit is a shot, not a scene. Do not collapse multiple shots into one image per scene.

This story covers FR-3 directly and must preserve the observability/error requirements shared by Epic 1: every node emits a Langfuse span, and failed nodes surface inputs plus exception details.

### Architecture Compliance

- Follow dependency direction: `pipeline/nodes/image.py` may import `domain` and a service helper, but must not import `db`, `api`, or FastAPI route code.
- `services/` owns orchestration, but the ComfyUI HTTP adapter can live in `src/yt_flow/services/comfyui_client.py` because it is an integration helper, not DB/SSE orchestration.
- `PipelineState` remains authoritative. Artifact paths live only in `PipelineState`; do not add image/artifact DB tables.
- Stage node return values replace state fields wholesale. Avoid mutating `state["scenes"]` or nested `shots` in place.
- `current_stage` must be set by the stage node return dict, not by `services/`.
- ComfyUI reachability is checked at `image_node` entry, not at app startup.
- Langfuse failures are non-fatal: log/record best-effort and continue pipeline work.

### Required Data Contracts

Expected domain shape from architecture:

```python
class ShotData(TypedDict):
    shot_id: str
    sentence_indices: list[int]
    image_prompt: str
    negative_prompt: str
    camera_angle: str | None
    camera_movement: str | None
    image_path: str | None
```

`image_node` must preserve all existing shot fields and set only `image_path`. It must tolerate `camera_angle` and `camera_movement` being `None`; those fields are scenario/director hints and must never cause image generation to crash.

### ComfyUI Workflow Baseline

Use baseline workflow:

- Source: `~/Documents/myWorkflows/comfyui_sdxl_anime_lora_workflow_api2.json`
- Repo target: `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json`
- Model stack: `animagineXL_v31.safetensors`, `horror_and_creepy.safetensors` LoRA weight `0.6`, `darkness_sdxl_v2.safetensors` LoRA weight `0.5`
- Output shape: `1216x832`, 30 steps, `dpmpp_2m` + `karras`, CFG `7.5`
- Prompt injection: node `"6"` positive prompt, node `"7"` negative prompt

Local inspection confirmed the source workflow exists and node `"6"` / `"7"` are `CLIPTextEncode` nodes titled Positive Prompt and Negative Prompt. Treat those node IDs as part of this story's contract; if the workflow changes, update tests and config together.

### ComfyUI Client Guidance

Use the local ComfyUI Server API:

- ComfyUI defaults to `http://127.0.0.1:8188`; make it configurable via `YTFLOW_COMFYUI_URL`.
- Submit full workflow payloads to `POST /prompt`; successful response includes a `prompt_id`.
- If ComfyUI returns validation data in `error` or `node_errors`, fail the image stage explicitly.
- Retrieve generated output metadata from `GET /history/{prompt_id}`.
- Download generated images via `GET /view` using metadata from history.
- Do not require WebSocket for this story unless tests show polling is insufficient; HTTP-only keeps the node easier to test.

### Langfuse Requirements

Use the current Langfuse Python SDK style already targeted by the architecture (`langfuse` Python SDK 4.x). The latest docs show `get_client()` and context-manager/decorator instrumentation; avoid legacy v2/v3-only APIs. The span/observation name must be exactly `"image"` so Story 1.10 can verify a single trace tree with stage spans `scenario`, `image`, `tts`, `subtitle`, and `video`.

The image stage does not make an LLM call directly if Story 1.5 already produced prompts, so capture ComfyUI request count and latency rather than token counts. If implementation decides to enrich prompts here later, that would be scope creep unless it is explicitly added to the story.

### Mock Mode

`YTFLOW_COMFYUI_MOCK=true` is required for test isolation. In mock mode:

- Do not instantiate or call the ComfyUI HTTP client.
- Use files under `tests/fixtures/images/`.
- Ensure the final `image_path` values point to files under `workspace/{run_id}/images/`, not directly to fixtures, so downstream code sees the same artifact layout in mock and real modes.

### Error Handling

On image-stage failure, return a state update with:

- `current_stage="image"`
- `error` string containing at least `stage=image`, `run_id=<run_id>`, and a concise root cause

Do not partially advance to downstream stages. Node-level resume is the accepted granularity, so a mid-image failure may require rerunning the whole image stage.

### Project Structure Notes

This repository currently contains planning artifacts and no application source tree yet. If Stories 1.1-1.5 have not actually been implemented before this story is developed, the dev agent must first ensure the scaffold/domain/graph/scenario contracts from those stories exist rather than inventing incompatible local shapes.

Expected files for this story:

- `src/yt_flow/pipeline/nodes/image.py` (new)
- `src/yt_flow/services/comfyui_client.py` (new)
- `src/yt_flow/config.py` (update)
- `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` (new)
- `tests/fixtures/images/` (new if absent)
- Image-node tests under the existing project test layout from Story 1.2

### Previous Story Intelligence

No previous Epic 1 story files are present under `_bmad-output/implementation-artifacts/` at story creation time. Use the epics and architecture docs as the source of truth, and check the actual codebase before implementation because Stories 1.1-1.5 may be implemented after this story file was generated.

Recent git history is documentation-only:

- `2390ead` initialized sprint status tracking.
- `4be98ee` added epics and implementation readiness report.
- `6db2416` added UX specs and HTML mockups.
- Recent commits do not establish application code patterns yet.

### Testing Requirements

Run the project test command established by Story 1.2. If no test command exists yet, add minimal pytest coverage alongside the implementation and document the command in the Dev Agent Record.

At minimum, tests must cover:

- Prompt injection into workflow nodes `"6"` and `"7"`.
- Mock mode writes or copies existing images into `workspace/{run_id}/images/`.
- All `ShotData.image_path` fields become non-empty existing paths.
- HTTP error or ComfyUI validation error produces image-stage error state.
- The node returns copied/rebuilt state rather than mutating the input state in place.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 1.6, FR-3, FR-10, FR-13, workflow baseline and mock-mode AC.
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` — AD-1, AD-2, AD-5, AD-7, AD-10, structural seed, `PipelineState`, `ShotData`.
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md` — F1 Pipeline Core, F2 Observability, NFRs.
- `CLAUDE.md` — Ponytail mode: avoid speculative abstractions and new dependencies unless needed.
- ComfyUI Server API docs: https://docs.comfy.org/development/comfyui-server/comms_overview and https://docs.comfy.org/development/comfyui-server/comms_routes
- Langfuse Python SDK docs: https://langfuse.com/docs/observability/sdk/overview

## Dev Agent Record

### Agent Model Used

TBD by dev agent.

### Debug Log References

### Completion Notes List

- Story context created on 2026-07-01.
- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List
