---
created: 2026-07-05
story_key: 5-11-segmentation-failure-shot-fallback
story_id: "5.11"
epic: 5
previous_story: 5-9-transition-audio-continuity
depends_on:
  - 5-7-layered-background-double-exposure-fix
baseline_commit: c1e94d1d9b444c0f93b3fe3b557c2d55f09c8969
---

# Story 5.11: Segmentation-Failure Shot-Level Fallback

Status: review

## Story

As Jay,
I want a single shot's ComfyUI segmentation/inpaint failure to degrade just that shot to a flat (non-layered) image instead of failing the entire run,
so that one bad shot doesn't force a full re-run of every other shot in the run, matching the existing non-fatal-degrade pattern already used elsewhere in the pipeline.

## Context

Story 5.7 fixed the double-exposure defect by adding an in-graph ComfyUI inpaint pass: the background `SaveImage` node (`"9"`) now sources from a chain that depends on the segmentation node (`"12"`, `InspyrenetRembg`) via `VAEEncodeForInpaint`(`"16"`) → `KSampler`(`"17"`) → `VAEDecode`(`"18"`). Before 5.7, node `"9"` sourced directly from node `"8"` and was independent of segmentation — a segmentation failure only cost the character layer (AC2's existing background-only fallback in `_generate_layered_shot`/`image_node` still applied). After 5.7, if node `"12"` **errors during execution** (not just produces a low-quality cutout — an actual ComfyUI node crash), **both** the character output (`"13"`) and the background output (`"9"`, now downstream of `"12"`'s mask) are missing. `image.py`'s per-shot loop in `image_node` has no per-shot `try`/`except` around `_generate_layered_shot()`, so the resulting `ComfyUIError` propagates out of the whole `for shot in scene["shots"]` loop and fails the entire run's image stage — losing every other shot's already-generated images too (they exist on disk, but the stage returns `error` instead of `scenes`, so the state never advances and the gate is never reached).

This is 5.7's own documented, deliberately-deferred gap (`data/workflows/README-layered-assets.md` "Fallback behavior" section, and 5.7's Change Log: *"the image stage now fails the entire run if ComfyUI's segmentation node errors on any single shot... flagged in the README, not fixed at the Python level pending a decision on desired degrade-vs-fail behavior"*). AD-10 already establishes the project's precedent for this class of decision: *"pipeline must not fail due to [a non-critical subsystem's] unavailability"* (there: Langfuse tracing). Story 5.8 established the same per-shot degrade pattern in a sibling subsystem — `character_service.py`'s `_angle_fallback()` marks affected shots `{"fallback": True}` rather than failing. This story applies that same precedent to segmentation failures: **a failed shot loses its layered treatment, not the run.**

## Acceptance Criteria

1. Given `YTFLOW_COMFYUI_LAYERED=true` and one shot's ComfyUI submission raises `comfyui_client.ComfyUIError` (segmentation/inpaint failure — background and/or character output missing), when `image_node` processes that shot, then it falls back to generating a **flat** (non-layered) image for that shot only — via a real second ComfyUI submission using a non-layered workflow — sets that shot's `character_path = None`, and does **not** raise: the run continues to every other shot and to the next stage.
2. Given the same failing shot, when the fallback flat generation ALSO fails (e.g. ComfyUI itself is unreachable), then the original error propagates and the run fails exactly as it does today — this story only degrades a real segmentation-specific failure, not a total ComfyUI outage.
3. Given a run where shot fails and falls back, when any other shot in the same run generates successfully, then that other shot is completely unaffected — normal `background_path`/`character_path` layered output, no fallback flag.
4. Given a shot falls back to flat, then `PipelineState`/`ShotData` records this fact (a new field) so it survives the checkpoint, and `GET /runs/{id}/stages/image/artifacts` exposes it per-shot so a human reviewing the image gate can see which shots were degraded (per the epic's "경고를 state에 기록해 image 게이트 아티팩트 패널에서 사람이 확인 가능하게" requirement) — a warning is also logged (`logger.warning`, matching the existing non-fatal-degrade pattern in `video.py:722`).
5. Given the non-layered path (`YTFLOW_COMFYUI_LAYERED=false`) or mock mode (`YTFLOW_COMFYUI_MOCK=true`), then behavior is completely unchanged — this story only touches the layered-and-real-ComfyUI branch.
6. Given the fix, then `data/workflows/README-layered-assets.md`'s "Fallback behavior" section (currently: *"treat a segmentation-node crash as a run-failing event... until a follow-up story revisits it"*) is updated to describe the new per-shot degrade behavior — this story IS that follow-up.
7. Given the fix, then it is validated against the existing regression suite plus new tests covering: one shot fails + falls back while others succeed (run does not fail, fallback flag set correctly), and the fallback-also-fails case (run fails as before).

## Tasks / Subtasks

- [x] Add a fallback workflow config setting (AC: 1) — `src/yt_flow/config.py`
  - [x] Add `comfyui_flat_fallback_workflow_path: str = "data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json"` next to the existing `comfyui_*` settings (line ~39-41). Reuses the already-existing, already-tested plain non-layered workflow file — do not author a new workflow JSON for this.
  - [x] Add `YTFLOW_COMFYUI_FLAT_FALLBACK_WORKFLOW_PATH=...` line to `.env.example` near the other `COMFYUI_*` lines (~line 25-34), following the existing comment style.
- [x] Add the per-shot fallback field (AC: 3, 4) — `src/yt_flow/domain/state.py`
  - [x] Add `layered_fallback: bool` to `ShotData` (after `character_path`, line ~34) — mirrors the naming of `character_service.py`'s existing `{"fallback": bool}` semantic from Story 5.8/1.13, not a new vocabulary.
  - [x] `TypedDict` isn't runtime-enforced, so most existing `ShotData` literal sites (`tests/api/test_stages.py`, `tests/services/test_character_angle_selector.py`, `tests/pipeline/test_stub_profile_smoke.py`, `tests/pipeline/nodes/test_video.py`) will keep working unmodified — only touch them if a test in that file happens to do exact-dict equality against a shot. The one site that WILL break is `tests/api/test_stage_artifacts.py`, because it asserts exact dict equality against `run_service.get_stage_artifacts()`'s output (see Tests subtask below) — grep `"character_path":` repo-wide before assuming any given file needs a change, don't blanket-edit every hit.
- [x] Implement per-shot fallback in `image_node` (AC: 1, 2, 3, 4) — `src/yt_flow/pipeline/nodes/image.py`
  - [x] Add `import logging` + `logger = logging.getLogger(__name__)` at module level (matches `video.py:12,31`; this module currently has no logger).
  - [x] In `image_node`'s scene/shot loop (line ~213-230, the `if s.comfyui_layered:` branch), wrap the `_generate_layered_shot(...)` call in `try`/`except comfyui_client.ComfyUIError as exc`.
  - [x] On catch: lazily load a second workflow template via `_load_workflow(s.comfyui_flat_fallback_workflow_path)` — load it once (e.g. a local `flat_template` variable initialized to `None` before the scene loop, populated on first failure) rather than re-reading the file per failed shot. Inject this shot's own `image_prompt`/`negative_prompt` via the existing `_inject_prompts()` helper, then call `comfyui_client.submit_and_fetch(s.comfyui_url, wf)` (the same non-layered call the `else` branch at line ~235+ already uses) to get flat image bytes. Write them to the shot's existing `img_dest`/`bg_dest` path convention (reuse `_generate_layered_shot`'s naming, e.g. write to the `*_background.png` destination so downstream `video.py` compositing — which reads `background_path` — needs no changes) and set `char_path = None`.
  - [x] `logger.warning("shot %s segmentation failed, falling back to flat image: %s", shot["shot_id"], exc)` before falling back.
  - [x] Set `new_shots.append({..., "background_path": <flat path>, "character_path": None, "layered_fallback": True})` for the fallback case; the success case must explicitly set `"layered_fallback": False` (don't rely on a default — TypedDict has none).
  - [x] The non-layered `else` branch (line ~231+) must also set `"layered_fallback": False` on its shot dict (AC5 — field must exist and be `False` everywhere layered mode isn't in play, for consistent downstream typing).
  - [x] If the fallback submission itself raises `ComfyUIError`, let it propagate uncaught (AC2) — do not catch twice.
  - [x] Track a `fallback_count` alongside the existing `request_count`/`image_count`/`background_count`/`character_count` locals and add it to `_record_trace()`'s metadata (mirrors the existing counters' pattern, line ~119-145).
- [x] Update `run_service.get_stage_artifacts`'s image branch (AC: 4) — `src/yt_flow/services/run_service.py:102-108`
  - [x] Add `"layered_fallback": sh.get("layered_fallback", False)` to each image dict in the list comprehension.
- [x] Update the frontend artifact type + panel (AC: 4) — `frontend/src/lib/api.ts:61-64`, `frontend/src/components/ArtifactPanel.tsx`
  - [x] Extend `ImageArtifacts.images` item type with `layered_fallback: boolean`.
  - [x] In `ImagePanel` (`ArtifactPanel.tsx:284+`), render a small warning indicator on thumbnails where `layered_fallback` is `true` — reuse the existing `text-status-awaiting` token (same one `stage-sidebar-item.tsx` uses for its pending/warning glyph) rather than inventing a new color; a short label is enough (e.g. "⚠ 플랫 폴백"), no new dependency or icon library.
- [x] Update documentation (AC: 6) — `data/workflows/README-layered-assets.md:207-227`
  - [x] Rewrite the "Fallback behavior" section's final paragraph (currently ends "...treat a segmentation-node crash as a run-failing event, not a soft per-shot fallback, until a follow-up story revisits it") to describe the new behavior: segmentation-node execution errors now degrade only the affected shot to a flat image via `comfyui_flat_fallback_workflow_path`, logged and recorded on the shot (`layered_fallback`); the run continues.
- [x] Tests (AC: 7)
  - [x] `tests/pipeline/nodes/test_image.py`: new test(s) — monkeypatch `comfyui_client.submit_and_fetch_outputs` to raise `ComfyUIError` for one shot's call and succeed for others (it's called once per shot in the layered branch); assert the run's `error` is `None`, the failed shot has `layered_fallback=True`, `character_path=None`, and a `background_path` pointing at the fallback image; assert unaffected shots have `layered_fallback=False` and their normal layered paths. Also add a test where the fallback `submit_and_fetch` ALSO raises — assert the run's `error` is set (existing whole-run-failure behavior, AC2).
  - [x] The existing layered-mode tests in `test_image.py` (`test_layered_mock_sets_background_and_character_paths`, `test_layered_mock_background_only_when_no_character_fixture`, `test_layered_real_background_only_allowed`, `test_layered_real_valid_rgba_character_accepted`, etc.) assert individual `shot["background_path"]`/`shot["character_path"]` values, not exact-dict equality — they should keep passing unmodified. Confirm this while implementing; only add assertions to them if it's cheap to also assert `layered_fallback is False` on the happy path.
  - [x] `tests/api/test_stage_artifacts.py::test_image_artifacts` (line ~97-105) asserts `body["images"][0] == {...}` with exact dict equality on 3 keys — this WILL fail once `layered_fallback` is added to the DTO; add the key to the expected dict, and update the `_scene()` test fixture helper (line ~20-34) which builds `ShotData`-shaped dicts to include `"layered_fallback": False`.
  - [x] `frontend/src/components/ArtifactPanel.test.tsx`: the existing image test (line ~61-80) builds `images` literals without `layered_fallback` — TypeScript will require the field once the type changes; add it (`false` for existing cases) and add one new case with `layered_fallback: true` asserting the warning indicator renders.
  - [x] Run `uv run pytest tests/pipeline/nodes/test_image.py tests/api/test_stage_artifacts.py -q` and `cd frontend && npm test -- ArtifactPanel` (or the project's actual vitest invocation — check `frontend/package.json` scripts).
  - [x] Live validation (matches 5.7/5.6/5.8's pattern): if there's a way to force a real ComfyUI segmentation error (e.g. a shot whose InspyrenetRembg step legitimately fails, or a temporarily-broken workflow JSON pointed at for one manual run), do a real (non-mock) validation confirming the run completes with a flat-fallback shot and the artifact panel shows the warning. If not practically reproducible live within this story's scope, say so explicitly rather than fabricating evidence (per this project's `verification-before-completion` norm) — synthetic/mocked test coverage (above) is the primary evidence either way, since this is a Python-level control-flow fix, not a ComfyUI-graph change.

## Dev Notes

### Critical Implementation Guardrails

- Do **not** touch the ComfyUI workflow JSON(s) under `data/workflows/` — this story is a pure Python control-flow fix (catch the failure, don't let it kill the run) plus a config addition pointing at an *already-existing* workflow file. 5.7 already tried the workflow-JSON-only approach for the double-exposure bug and explicitly deferred this exact coupling to "a Python-level decision" — this story is that decision, made in Python.
- `_overlay_filter()` in `video.py` already treats `character_path: None` as "background-only" (AC:3 of that function's existing contract, referenced repeatedly in 5.7's Dev Notes) — the fallback path here produces exactly that shape (`character_path=None`, `background_path=<flat image>`), so `video.py` needs **zero changes**. Verify this assumption by reading `_overlay_filter()`'s current handling of `character_path is None` before assuming it, but do not modify it.
- Keep the distinction between this story's fallback (a full ComfyUI **execution error**, `ComfyUIError`) and the pre-existing "character node produced no output" case (already handled today — `_generate_layered_shot` already sets `char_path = None` without raising when `char_bytes is None`, and separately when `not _has_alpha(char_bytes)` it DOES raise `ComfyUIError`). Both the alpha-check failure and a segmentation-node crash currently propagate as the same `ComfyUIError` type and should both be caught by this story's new per-shot `try`/`except` — no need to distinguish sub-cases in code, they get the same flat-fallback treatment.
- The two ComfyUI submissions (layered attempt, then flat fallback) are sequential, not concurrent — this doubles latency only for the failed shot, which is the same "extra ComfyUI compute" tradeoff 5.7 already accepted for its inpaint pass; document it in Dev Agent Record but do not try to optimize it away (e.g. no speculative pre-submission of both).

### Current Code State — Files To Read Before Editing

- `src/yt_flow/pipeline/nodes/image.py`
  - `_generate_layered_shot()` (lines 148-191): submits one ComfyUI prompt requesting both `s.comfyui_background_node` and `s.comfyui_character_node` outputs via `comfyui_client.submit_and_fetch_outputs()`; raises `ComfyUIError` if the background output is missing entirely, or if a character output exists but fails `_has_alpha()`. Returns `(bg_path, char_path, img_path)` — this story's fallback must produce the same tuple shape for its caller.
  - `image_node()` (lines 195+): the `if s.comfyui_layered:` branch (lines 213-230) calls `_generate_layered_shot()` with no exception handling — this is the exact call site to wrap. Note `template` (line 207) is loaded once outside the loop from `s.comfyui_workflow_path`, which in layered mode is operator-configured (via `.env`, see `.env.example:32`) to point at the layered inpaint workflow — it is NOT a plain workflow, so it cannot double as the fallback template. This is why a distinct `comfyui_flat_fallback_workflow_path` setting is needed, not reuse of `s.comfyui_workflow_path`.
  - The non-layered `else` branch (lines 231-249) is the existing reference implementation for "submit a plain workflow, get one image back" — the fallback path in the layered branch should call the same `comfyui_client.submit_and_fetch()` function this branch already uses, not invent a new submission helper.
- `src/yt_flow/services/comfyui_client.py`
  - `ComfyUIError` (line 17-18): the exception type raised on validation, transport, or timeout failures. `submit_and_fetch()` (lines 21-36) is the plain single-image call already used by the non-layered path — reuse it verbatim for the fallback, do not add a new client function.
- `src/yt_flow/domain/state.py`
  - `ShotData` (lines 25-34): TypedDict, no defaults — every construction site must supply every key or downstream `.get()`-free reads will `KeyError`. Grep the whole repo for `"character_path":` before touching this to find every literal construction site (production code AND test fixtures).
- `src/yt_flow/services/run_service.py`
  - `get_stage_artifacts()`'s `image` branch (lines 102-108): the only place that shapes `ShotData` into the API-facing DTO. This is the single seam between backend state and the frontend artifact panel — no other file needs to change to make the flag visible to Jay.
- `data/workflows/README-layered-assets.md`
  - Lines 207-227, "Fallback behavior" section: already accurately documents the current bug this story fixes, including the exact node-dependency chain (`"9"` now depends on `"12"` via `"16"`→`"17"`→`"18"`) — read it fully, it's effectively pre-written root-cause analysis for this story.

### Architecture Compliance

- AD-1 (layer boundaries): this story stays inside `pipeline/nodes/image.py` (pure function of state, no DB/SSE) plus its DTO-shaping counterpart in `services/run_service.py` (AD-4's "services/ owns DB sync" — `get_stage_artifacts` already lives there, this just adds one field to its existing output shape). No new layer-boundary violations.
- AD-10 precedent: "pipeline must not fail due to [a non-critical subsystem's] unavailability" (written for Langfuse tracing, line 99 of ARCHITECTURE-SPINE.md) — this story extends the same non-fatal-degrade philosophy to ComfyUI segmentation, consistent with the existing character-generation fallback (`character_service.py`) and video-node angle-selection fallback (`video.py:722`, `logger.warning("Angle selection failed, continuing with existing character_path...")`) already in the codebase.
- Config convention: new `YTFLOW_`-prefixed setting in `config.py`, per the "Config" row of ARCHITECTURE-SPINE.md's Consistency Conventions table and 5.7's own "Config additions... belong in `src/yt_flow/config.py`" guardrail.
- `PipelineState` mutation convention: "fields replaced wholesale per node return — no in-place mutation" — the fallback shot dict must be built as a fresh `{**shot, ...}` spread exactly like the existing success-path dict construction (line ~225-230), never mutating `shot` in place.

### Previous Story Intelligence

- Story 5.7 (immediate predecessor of this coupling, not the sequentially-previous story file) is the authoritative source for *why* this bug exists and *what NOT to re-decide*: it already chose and validated the in-graph inpaint approach for double-exposure, already confirmed `image_node`/`video.py`'s contracts don't need to change for that fix, and explicitly deferred exactly this story's scope as a Python-level decision. Do not revisit 5.7's Option A (inpaint) vs Option B (second background-only generation pass) choice — that's settled; this story is purely about *what Python does when the chosen ComfyUI graph errors on one shot*.
- Story 5.9 (the sequentially-previous story file) is unrelated in subject (audio/video join timing) but its Dev Agent Record demonstrates this project's expected live-validation rigor (real ffmpeg runs, ffprobe/RMS evidence, independent re-verification during review) — apply the same evidentiary standard to whatever live/synthetic validation this story's AC7 produces; don't claim "validated" without reproducible evidence.
- Story 5.8 established the `{"fallback": bool}` naming/semantic precedent in `character_service.py` (per-shot degrade flag, surfaced to callers) — `layered_fallback` in this story is the same idea applied to a different subsystem; keep naming consistent rather than inventing new vocabulary (e.g. don't call it `degraded` or `is_flat`).

### Testing Requirements

- `uv run pytest tests/pipeline/nodes/test_image.py tests/api/test_stage_artifacts.py -q`
- Full regression: `uv run pytest -q` (excluding the pre-existing network-dependent files already excluded by prior stories: `test_character_service_generation.py`, `test_comfyui_client.py`, `test_image_search.py` — confirm these exclusions are still accurate, don't assume stale).
- Frontend: whatever `npm test`/`vitest` command `frontend/package.json` defines, scoped to `ArtifactPanel`.
- This is a pure control-flow + DTO-field change with no new external dependency, no new ComfyUI graph — synthetic monkeypatched tests (forcing `ComfyUIError` from the client layer) are the primary and sufficient evidence for AC1-3,5,7. A real ComfyUI segmentation failure is not easily reproducible on demand; attempt it per the Tasks note above but do not block story completion on manufacturing a real crash if it isn't practical.

## Project Structure Notes

- Expected modified files:
  - `src/yt_flow/config.py`
  - `.env.example`
  - `src/yt_flow/domain/state.py`
  - `src/yt_flow/pipeline/nodes/image.py`
  - `src/yt_flow/services/run_service.py`
  - `frontend/src/lib/api.ts`
  - `frontend/src/components/ArtifactPanel.tsx`
  - `data/workflows/README-layered-assets.md`
  - `tests/pipeline/nodes/test_image.py`
  - `tests/api/test_stage_artifacts.py`
  - `frontend/src/components/ArtifactPanel.test.tsx`
- No new files, no new dependencies, no ComfyUI workflow JSON changes.

## References

- Epic/story source: `_bmad-output/planning-artifacts/epics.md#Epic 5: 영상 품질 고도화` (Story 5.11 section)
- Root-cause story: `_bmad-output/implementation-artifacts/5-7-layered-background-double-exposure-fix.md` (Dev Agent Record, Change Log, "Saved Questions" — all three sections independently document this exact deferred gap)
- Sibling fallback precedent: `src/yt_flow/services/character_service.py` (`_angle_fallback()`, `{"fallback": bool}` shape), `src/yt_flow/pipeline/nodes/video.py:717-722` (angle-selection non-fatal degrade)
- Architecture: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` AD-1, AD-4, AD-10, Consistency Conventions
- Workflow docs: `data/workflows/README-layered-assets.md` "Fallback behavior" section (lines 207-227)

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5), via bmad-dev-story, in an isolated git worktree (`story/5-11-segmentation-failure-shot-fallback`) to avoid colliding with concurrent in-progress work on Story 5.10 in the main worktree.

### Debug Log References

- `PYTHONPATH=$PWD/src uv run pytest tests/pipeline/nodes/test_image.py tests/api/test_stage_artifacts.py -q` → 37 passed.
- Full backend regression: `PYTHONPATH=$PWD/src uv run pytest -q --ignore=tests/services/test_character_service_generation.py --ignore=tests/services/test_comfyui_client.py --ignore=tests/services/test_image_search.py` (excluded files per existing project convention, confirmed still accurate) → 1 pre-existing, unrelated failure (`tests/api/test_e2e_stub_run.py::test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk`, confirmed via `git stash` to also fail against the story's own `baseline_commit`/current HEAD with zero code changes — not caused by this story). Re-run with that one test deselected: `557 passed, 1 skipped, 1 deselected`.
- Frontend: `npx vitest run ArtifactPanel` → 12 passed. `npx tsc -b` → clean, no type errors.

### Completion Notes List

- Implemented the per-shot flat-image fallback exactly as scoped: `image_node`'s layered branch now catches `comfyui_client.ComfyUIError` from `_generate_layered_shot` per shot, lazily loads `comfyui_flat_fallback_workflow_path` once, and retries with a plain (non-layered) submission via the already-existing `comfyui_client.submit_and_fetch`. Per the Dev Notes guidance, this deliberately also catches the pre-existing "opaque character output" `ComfyUIError` sub-case (previously a whole-run failure under AC4 of the original 1.6b story) — both sub-cases get the same flat-fallback treatment now, since they're the same exception type and the story explicitly said not to distinguish them in code.
- Updated the two existing tests that encoded the old "opaque character → whole run fails" and "missing background → whole run fails" behavior to reflect the new fallback-first behavior (the missing-background case still fails the *run* in its test, but now because the mocked *fallback* submission fails too, per AC2 — not because the original error propagated directly).
- `fallback_count` added as a new `_record_trace()` metadata field, following the existing counter pattern.
- Frontend: added the `layered_fallback` boolean end-to-end (DTO type → `ImagePanel` warning glyph reusing the existing `text-status-awaiting` token, no new dependency).
- Live validation: not attempted. Per the story's own Dev Notes/Testing Requirements, forcing a real ComfyUI segmentation-node crash on demand isn't practical, and the story explicitly says not to block completion on manufacturing one — this is a pure Python control-flow fix with no ComfyUI graph change, so the synthetic monkeypatched tests (`test_segmentation_failure_falls_back_to_flat_for_one_shot`, `test_segmentation_failure_fallback_also_fails_propagates`, `test_layered_real_opaque_character_falls_back_to_flat`) are the primary and, per the story, sufficient evidence for AC1-3, 5, 7.
- Also fixed `tests/domain/test_state_imports.py::test_type_hint_shapes` (an existing field-drift guard not called out in the story's Tasks list, but broken by adding `layered_fallback` to `ShotData` — added the field to its `EXPECTED_FIELDS` set).

### File List

- `src/yt_flow/config.py`
- `.env.example`
- `src/yt_flow/domain/state.py`
- `src/yt_flow/pipeline/nodes/image.py`
- `src/yt_flow/services/run_service.py`
- `frontend/src/lib/api.ts`
- `frontend/src/components/ArtifactPanel.tsx`
- `data/workflows/README-layered-assets.md`
- `tests/pipeline/nodes/test_image.py`
- `tests/api/test_stage_artifacts.py`
- `tests/domain/test_state_imports.py`
- `frontend/src/components/ArtifactPanel.test.tsx`

## Change Log

- 2026-07-05: Implemented per-shot flat-image fallback for segmentation-node ComfyUI errors in `image_node`; added `comfyui_flat_fallback_workflow_path` config, `layered_fallback` state field, `run_service`/frontend artifact exposure, and README update. Full regression suite green (557 passed, 1 pre-existing unrelated failure excluded) plus frontend tests/typecheck green. Live validation not practical per story's own guidance; synthetic test coverage is primary evidence. Status → review.
