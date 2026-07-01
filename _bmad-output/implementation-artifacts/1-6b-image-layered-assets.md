---
baseline_commit: 10d39b31866a74c1c771cb928451d757da477194
---

# Story 1.6b: image_node layered assets for character compositing

Status: done

<!-- Origin: unblocker for Story 1.9c. This story narrows the 1.9c prerequisite into the image/state contract it actually needs. -->

## Story

As Jay,
I want `image_node` to emit separate background and transparent character image assets per shot,
so that `video_node` can later animate and composite the character independently from the Ken-Burns background.

## Acceptance Criteria

1. Given `image_node` runs for a shot, when layered-asset mode is enabled, then each `ShotData` contains `background_path` and `character_path` values pointing to existing files under `workspace/{run_id}/images/`, while preserving the existing `image_path` contract for downstream compatibility.
2. Given a shot has no usable character-layer output, when `image_node` completes, then `background_path` is set and `character_path` is `None`; downstream video rendering can treat the shot as background-only.
3. Given mock mode is enabled via `YTFLOW_COMFYUI_MOCK=true`, when `image_node` runs, then mock layered assets are materialized under the run workspace without calling ComfyUI.
4. Given ComfyUI returns an HTTP, validation, missing-output, or non-transparent character output error, when `image_node` encounters it, then `PipelineState.error` is set with `stage="image"` and `run_id`, and tracing records the concise root cause.
5. Given `image_node` succeeds, when the Langfuse `"image"` span is updated, then metadata includes layered asset counts: background count, character count, and whether layered mode was enabled.

## Tasks / Subtasks

- [x] Extend the domain state contract. (AC: 1, 2)
  - [x] Add optional `background_path: str | None` and `character_path: str | None` to `ShotData` in `src/yt_flow/domain/state.py`.
  - [x] Preserve `image_path: str | None` as the composed/backward-compatible preview image; do not remove or rename it.
  - [x] Update `tests/domain/test_state_imports.py` so the import-boundary/type-shape guard expects the new fields.
- [x] Extend `image_node` output handling. (AC: 1, 2, 4)
  - [x] Keep the current per-shot generation loop and pure copy/update style; never mutate input state in place.
  - [x] Write deterministic asset names under `workspace/{run_id}/images/`, for example `scene_001_s1_background.png`, `scene_001_s1_character.png`, and optionally `scene_001_s1.png` for the existing `image_path`.
  - [x] Set `image_path` to the composed/full-frame image if available; otherwise set it to `background_path` so Stories 1.9 and 1.9b remain usable.
  - [x] If the character layer is absent by design, set `character_path=None` rather than failing the stage.
- [x] Add a minimal layered ComfyUI contract. (AC: 1, 4)
  - [x] Prefer a workflow/output convention over a new ML segmentation dependency: one full/background output plus one transparent PNG character output.
  - [x] Make output selection explicit in code/tests; do not rely on fragile filename ordering from ComfyUI history.
  - [x] Validate that `character_path` files are PNGs with an alpha channel when present; fail clearly if a supposed character output is opaque.
  - [x] Keep the existing ComfyUI client generic; put workflow-output interpretation in `image_node` or a small helper only if needed.
- [x] Extend mock fixtures and tests. (AC: 2, 3, 4)
  - [x] Add tiny background and transparent-character fixtures under `tests/fixtures/images/`.
  - [x] Unit test mock mode sets `background_path`, optional `character_path`, and a backward-compatible `image_path` under `workspace/{run_id}/images/`.
  - [x] Unit test a background-only shot leaves `character_path=None` and does not fail.
  - [x] Unit test invalid/opaque character output produces image-stage error with `stage=image` and `run_id`.
- [x] Extend observability. (AC: 5)
  - [x] Update the current `"image"` span metadata with `layered_assets_enabled`, `background_count`, and `character_count`.
  - [x] Keep tracing failures non-fatal, matching Story 1.6.

## Dev Notes

### Why This Story Exists

Story 1.9c needs a character as its own transparent layer. The current Story 1.6 implementation writes only `ShotData.image_path`, and the existing video effect story 1.9b explicitly defers character idle motion because the single-image model cannot support independent character motion. This story creates the missing contract without growing 1.9c into an image-generation refactor.

### Required Existing Context

- Story 1.6 is done and established the `image_node` pattern: `@observe(name="image")`, `_settings()` test seam, deterministic files under `workspace/{run_id}/images/`, pure copied scene/shot dicts, and best-effort Langfuse metadata.
- `ShotData` currently contains only `image_path` for image artifacts. Add fields, but preserve the old field so Story 1.9 and 1.9b can still render background-only or composed output.
- Story 1.9c assumes Option A from its blocking decision: `image_node` emits `background_path` + transparent `character_path`; `video_node` later applies `zoompan` to the background and FFmpeg `overlay` with sinusoidal motion to the character.

### Architecture Guardrails

- Keep dependency direction intact: `pipeline/nodes/image.py` may import `domain` and `services/comfyui_client.py`, but must not import `db`, `api`, or FastAPI code.
- `PipelineState` remains the source of truth for in-flight artifact paths. Do not add DB tables or artifact registries in this story.
- Preserve node purity: return partial state updates and rebuild nested scene/shot dicts rather than mutating input state.
- Do not add a segmentation/matting dependency such as `rembg`; that is the rejected Option B from Story 1.9c and violates the minimal-dependency posture.
- Keep graph wiring out of scope. `STAGE_NODES` rewiring is already deferred to the integration story that owns end-to-end graph execution.

### ComfyUI Contract Notes

The existing workflow asset was synthesized during Story 1.6 and is still unverified against a real ComfyUI export before non-mock runs. This story may require replacing or extending that workflow with a real layered-output export. Treat the workflow as configuration plus tests: if node IDs or output keys change, update code and tests together.

The implementation should make output interpretation deterministic. Good options:

- configure named SaveImage/output nodes for `background` and `character`;
- or parse known output node IDs from settings/constants and assert both are present when layered mode is enabled.

Avoid making the ComfyUI client know project-specific semantics; it should continue returning output bytes/metadata, while `image_node` maps those outputs to `ShotData` fields.

### Downstream Contract for 1.9c

After this story is done, 1.9c can be promoted from blocked once Story 1.9b is also done. 1.9c should consume:

```python
shot["background_path"]  # required for layered motion; fallback to image_path if absent
shot["character_path"]   # optional transparent PNG; None means background-only
```

`image_path` remains useful as a preview or compatibility fallback, but 1.9c should prefer `background_path` for Ken Burns and `character_path` for overlay motion.

### Testing Requirements

Run the established test command:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

At minimum, add/adjust focused tests for:

- `ShotData` shape includes `background_path` and `character_path`.
- Mock mode writes layered assets into the run workspace.
- Input state is not mutated.
- Background-only output is allowed.
- Opaque or missing character output fails only when the implementation expected a character layer.
- Existing single-image `image_path` consumers remain compatible.

## References

- `_bmad-output/implementation-artifacts/1-6-image-node.md`
- `_bmad-output/implementation-artifacts/1-9b-video-effects-kenburns-transitions.md`
- `_bmad-output/implementation-artifacts/1-9c-video-character-idle-motion.md`
- `src/yt_flow/domain/state.py`
- `src/yt_flow/pipeline/nodes/image.py`
- `_bmad-output/implementation-artifacts/deferred-work.md`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- Extended `ShotData` with `background_path` and `character_path`; preserved `image_path` for backward compat with stories 1.9/1.9b.
- Added `comfyui_layered`, `comfyui_background_node`, `comfyui_character_node` to `Settings`.
- Added `submit_and_fetch_outputs` + `_await_outputs` to `comfyui_client` — returns `dict[str, bytes]` keyed by output node ID; existing `submit_and_fetch` is unchanged.
- `_has_alpha` validates PNG color_type byte (offset 25) without Pillow — stdlib only.
- `_generate_layered_shot` encapsulates per-shot layered logic: mock copies fixtures, real mode fetches by node ID and validates alpha.
- Non-layered path sets `background_path=None` / `character_path=None` so `ShotData` always has all three image fields.
- `_record_trace` extended with `layered_assets_enabled`, `background_count`, `character_count` (defaults=False/0/0 for non-layered).
- 20 new tests added (layered mock, background-only, alpha validation, observability); all 130 tests pass.

### File List

- `src/yt_flow/domain/state.py`
- `src/yt_flow/config.py`
- `src/yt_flow/services/comfyui_client.py`
- `src/yt_flow/pipeline/nodes/image.py`
- `src/yt_flow/pipeline/nodes/scenario.py`
- `tests/domain/test_state_imports.py`
- `tests/pipeline/nodes/test_image.py`
- `tests/fixtures/images/mock_background.png`
- `tests/fixtures/images/mock_character.png`

### Review Findings

- [x] [Review][Patch] Replace `assert template is not None` with `raise ValueError` [image.py:166,235] — `assert` is a no-op under Python `-O`; use explicit `raise ValueError` instead. **Fixed.**
- [x] [Review][Patch] `scenario_node` constructs `ShotData` without `background_path`/`character_path` [scenario.py:119] — TypedDict contract violation causes `KeyError` on any pre-image-node access. **Fixed.**
- [x] [Review][Defer] `image_node` hardcodes `Path("workspace")` instead of `s.workspace_path` [image.py:204] — deferred, pre-existing from Story 1.6
- [x] [Review][Defer] `_await_outputs` partial result if ComfyUI is non-atomic [comfyui_client.py:138] — deferred, spec-compliant (AC2 allows background-only)
- [x] [Review][Defer] `_has_alpha` does not detect tRNS palette transparency [image.py:113] — deferred, ComfyUI outputs RGBA not indexed PNGs

## Change Log

- 2026-07-01: Story 1.6b implemented — layered asset mode for `image_node`. Added `background_path`/`character_path` to `ShotData`, `submit_and_fetch_outputs` to ComfyUI client, `_has_alpha` alpha validation, mock fixtures (1×1 RGB/RGBA PNGs), extended observability span, 20 new tests. All 130 tests pass.
- 2026-07-01: Code review complete — 2 patches applied (`assert`→`raise ValueError`, `scenario_node` ShotData init). 3 findings deferred (pre-existing or spec-compliant).
