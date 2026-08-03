# Story 11.6: Hero-Shot Selective I2V — Wan 2.2 Camera Control (Conditional)

Status: ready-for-dev

> **CONDITIONAL / BLOCKED FOR IMPLEMENTATION:** `ready-for-dev` means the implementation guide exists. It does **not** waive the activation gate below. As of 2026-08-03, Story 11.5 is `backlog`, Story 13.3 is not implemented, and no Jay-approved post-11.5 E2E residual-motion verdict is recorded. A dev agent must complete Task 0 and stop without code/config changes when any condition is unmet.

<!-- Source epics provide draft scope prose but no formal user-story sentence or numbered ACs. The Story and ACs below are explicitly derived implementation contracts. -->

## Story

As Jay,
I want to animate only 1–3 explicitly selected hero shots from their fully composited frames,
so that moments requiring real environmental or character motion gain cinematic impact without making I2V the costly default for every shot.

## Acceptance Criteria

### AC1 — Blocking activation gate

**Given** Story 11.6 is conditional,
**when** a dev agent begins implementation,
**then** it verifies all of the following from repository evidence before changing code or configuration:

1. Stories 11.1–11.5 are `done`;
2. Story 13.3's title-manifest/provenance convention is implemented, or an equivalent non-node-ID workflow contract already exists;
3. Jay has reviewed an E2E render containing the 11.1–11.5 improvements and recorded that residual physical motion still justifies I2V; and
4. Jay has identified at least one representative hero-shot candidate.

**And** if any item is absent, the dev agent reports the unmet condition and stops without implementation changes.

### AC2 — Opt-in, explicit selection, and episode cap

**Given** activation is approved,
**when** scenario visual metadata is produced and parsed,
**then** `ShotData` supports an optional closed `hero_i2v_motion` value with vocabulary `none | ambient | breath | flicker | fabric`, where absent/invalid values resolve to `none`,
**and** `hero_i2v_enabled` defaults to `False`,
**and** only shots with a non-`none` value are candidates,
**and** a deterministic resolver retains at most the first three eligible surviving `ShotClip`s in narration order across the episode,
**and** extra, merged-away, unsupported, or over-duration candidates are skipped with an explicit reason,
**and** no keyword scoring of `image_prompt` and no hidden all-shot mode is introduced.

**Given** the feature is disabled or no eligible candidate survives clip planning,
**when** `video_node` runs,
**then** ComfyUI I2V is never called and the post-11.5 procedural path is preserved.

### AC3 — Fully composited input frame

**Given** a selected hero shot,
**when** its I2V input is prepared,
**then** the input is a single 16:9 still containing the resolved location/background plate, all resolved character cards in depth order, alpha feathering, and the active composite-harmonization tier (including relit card assets when available),
**and** it is produced from the shared composition implementation rather than duplicating overlay geometry,
**and** it contains no procedural zoom/pan, DepthFlow displacement, fBm shake, post-FX/grain/vignette, subtitles, chapter-card content, or other screen-space UI,
**and** raw `ShotData.image_path` is never used as the I2V input because it is background-only.

### AC4 — Pinned Wan workflow and honest feasibility contract

**Given** local I2V is enabled,
**when** the Wan workflow is loaded,
**then** the committed artifact is a ComfyUI **API-format** workflow under `data/workflows/`, not the upstream UI-format template,
**and** injectable nodes are resolved by unique `ytflow:<key>` titles/manifest keys rather than numeric node IDs,
**and** the workflow validates the required high-noise/low-noise model pair, `WanCameraEmbedding`, image input, prompt, VAE/text encoder, `KSamplerAdvanced` seed inputs, and video output before submission,
**and** model filenames, quantization/dtype, workflow hash, ComfyUI/core/custom-node versions, and license/source are documented in a neighboring README.

**Given** official Fun Camera fp8 and community base-I2V GGUF are different model/workflow families,
**when** backend feasibility is assessed,
**then** they are never represented as the same combination,
**and** a generic I2V GGUF without verified Fun Camera control cannot satisfy the camera-control AC,
**and** the production backend remains disabled unless an RX 9060 XT live gate proves the chosen Fun Camera workflow fits and completes reliably.

### AC5 — Closed camera and physical-motion mapping

**Given** an eligible selected shot,
**when** the workflow parameters are injected,
**then** existing `camera_movement` is mapped by a pure deterministic function:

- `push_in` → `Zoom In`
- `pull_back` → `Zoom Out`
- `locked` or `None` → `Static`
- `drift` → `Pan Left` or `Pan Right`, selected from the stable per-shot seed
- `shake` → unsupported for this I2V path; use the procedural fallback and record the reason
- any legacy/unknown free text → `Static` plus a warning; never pass free text as a camera code

**And** `hero_i2v_motion` maps to a bounded prompt fragment describing only the requested physical motion (atmosphere/fog, breathing, light flicker, or fabric movement),
**and** the stable seed is injected into every active `KSamplerAdvanced` pass,
**and** high- and low-noise model/LoRA pairs cannot be crossed.

### AC6 — Exclusive motion ownership and exact assembly contract

**Given** a hero I2V clip succeeds,
**when** it joins the existing render,
**then** it replaces only that `ShotClip`'s procedural visual source,
**and** DepthFlow/zoompan/fBm/card procedural motion is not applied again to that clip,
**and** the existing scene assembly remains responsible for narration, sound design, color grade/post-FX, subtitle burn-in, hard shot cuts, chapter cards, ending credits, and scene transitions,
**and** subtitles remain screen-space and do not move with generated pixels.

**And** generation is sequential, never `gather`ed across hero shots on the single 16GB GPU,
**and** requested duration is converted to a supported frame count at the configured generation FPS,
**and** a clip longer than the validated maximum frame budget is ineligible rather than looped,
**and** the generated result is decoded and normalized by FFmpeg to `COMP_W × COMP_H`, 25 fps, H.264/yuv420p, silent, and exactly the planned `ShotClip.duration` by trimming surplus frames—never by looping a short clip or changing narration timing.

### AC7 — Video-aware ComfyUI adapter

**Given** the current ComfyUI adapter only discovers `images` outputs and uses a three-minute default poll budget,
**when** the I2V workflow is submitted,
**then** a video/file-aware adapter discovers the configured output collection and node, downloads the returned file reference through `/view`, and validates non-empty content and expected extension/content type,
**and** its timeout is a dedicated positive setting sized for measured I2V runtime rather than reusing the image timeout,
**and** history execution errors, cancellation, transport failures, validation failures, and timeout are distinguished in error messages,
**and** existing image adapter signatures and retry behavior remain backward compatible.

### AC8 — Visible shot-local fallback

**Given** one selected hero generation fails because of health, OOM, timeout, workflow validation, missing output, malformed video, duration/dimension validation, or unsupported control,
**when** the failure is handled,
**then** the entire video stage does not fail solely because this optional enhancement failed,
**and** that shot is rendered through the unchanged post-11.5 procedural path,
**and** a warning includes run, scene, shot, and reason,
**and** Langfuse trace metadata reports at least `selected`, `attempted`, `succeeded`, `fallback`, `skipped`, elapsed time, backend, and workflow/model identity,
**and** the fallback is never silent or reported as I2V success.

### AC9 — Deterministic cache, resume, and provenance

**Given** I2V is expensive,
**when** a completed hero clip is considered for reuse,
**then** an atomically written sidecar proves a cache hit using at least composite-frame SHA-256, workflow SHA-256, model filenames/dtype-or-quantization, ComfyUI/core/custom-node versions, ROCm/PyTorch versions, stable seed, physical-motion enum, camera code, width, height, source FPS, frame count, speed, steps/sampler settings, and normalized output contract,
**and** any changed key invalidates the clip,
**and** legacy/incomplete/non-dict sidecars, `.tmp` files, missing output, and undecodable output are cache misses,
**and** partial files are never treated as success.

### AC10 — Performance and live quality gate

**Given** the PRD's automated E2E ceiling is two hours and I2V is a known bottleneck,
**when** the feature is accepted,
**then** a real RX 9060 XT / supported ROCm environment generates at least one fully composited representative shot using the committed API workflow,
**and** evidence records resolution, frame count/FPS, wall time, peak VRAM, system RAM, model/workflow versions, output probe data, and whether character identity/composition and requested physical/camera motion are preserved,
**and** a mixed episode with procedural and I2V shots remains inside the two-hour automated budget or the feature stays disabled,
**and** a forced failure proves the procedural fallback end-to-end.

**And** reducing the production resolution below the planned 1280×720 target, enabling an acceleration LoRA that visibly reduces dynamics, or changing the selected backend requires a recorded Jay quality decision rather than an implicit code default.

### AC11 — Hosted providers are not silently added

**Given** the epic mentions Kling/Veo Fast only as a possible money-shot fallback,
**when** this story is implemented,
**then** no hosted provider, credentials, pricing assumption, upload policy, or network fallback is added without a separately approved provider contract,
**and** local failure falls back to the local procedural renderer,
**and** hosted fallback remains deferred follow-up scope.

## Tasks / Subtasks

- [ ] Task 0 — Satisfy or enforce the activation gate (AC: 1, 4, 10)
  - [ ] Verify 11.1–11.5 and 13.3 repository status and link their implementation evidence.
  - [ ] Record Jay's post-11.5 E2E residual-motion decision and representative shot.
  - [ ] Export the official Fun Camera template to API format and run a minimal RX 9060 XT feasibility spike without production wiring.
  - [ ] If any prerequisite or 16GB feasibility gate fails, stop without implementation changes and record the blocker; do not substitute generic I2V GGUF and claim Fun Camera compliance.
- [ ] Task 1 — Define closed hero metadata and deterministic selection (AC: 2, 5)
  - [ ] Add the closed `HeroI2VMotion` type and optional `ShotData.hero_i2v_motion` field.
  - [ ] Extend `visual_breakdown.md`, its parser, and scene construction with absent/invalid → `none` behavior.
  - [ ] Implement deterministic episode-cap resolution on surviving planned clips, with explicit skip reasons.
  - [ ] Implement and unit-test the closed camera/motion mapping and stable seed behavior.
- [ ] Task 2 — Author and validate the Wan workflow integration (AC: 4, 5, 7)
  - [ ] Commit one active-path API-format Fun Camera workflow plus setup/license/model README; do not commit model weights.
  - [ ] Use `ytflow:<key>` manifest titles and validate uniqueness, class types, inputs, high/low pairing, `KSamplerAdvanced` seed injection, and configured video output.
  - [ ] Extend `comfyui_client.py` with backward-compatible video/file output polling, download, execution-error reporting, and configurable long timeout.
  - [ ] Add feature-off, workflow-path, timeout, cap, target geometry/FPS/frame budget, and backend identity settings with `YTFLOW_` naming.
- [ ] Task 3 — Create the composed-still seam and selected visual branch (AC: 3, 6)
  - [ ] Refactor/reuse `_build_card_chain` so the exact static composite can be emitted without procedural movement, post-FX, or subtitles.
  - [ ] Hash/upload the emitted PNG and invoke the injected I2V adapter only for eligible clips.
  - [ ] Normalize successful video output to the existing silent-shot clip contract.
  - [ ] Force a one-clip hero scene through the two-pass assembly path so narration/subtitles/post-FX are preserved.
  - [ ] Keep selected and non-selected motion ownership mutually exclusive.
- [ ] Task 4 — Add fallback, cache, provenance, and trace metadata (AC: 8, 9)
  - [ ] Fall back per shot on every defined failure and log/trace the exact reason.
  - [ ] Add atomic output + sidecar writes and strict cache validation.
  - [ ] Include workflow/model/runtime provenance and aggregate result counts in Langfuse metadata.
  - [ ] Preserve retry/resume behavior and ensure a failed/partial attempt is retryable.
- [ ] Task 5 — Verify without introducing CI GPU dependence (AC: 2–10)
  - [ ] Add pure/unit tests for parsing, cap-after-merge, camera mapping, unsupported/over-duration routing, and disabled zero-call behavior.
  - [ ] Add adapter tests for `videos`/generic file output, history execution errors, empty/malformed output, cancellation, and timeout.
  - [ ] Add video tests proving composite-before-I2V, exact uploaded bytes, no subtitle/post-FX in input, no double motion, successful mixed assembly, and one-clip hero audio/subtitle preservation.
  - [ ] Add cache invalidation/atomicity/fallback/trace tests and an FFmpeg probe smoke test.
  - [ ] Run targeted tests, Ruff, and the complete suite; keep real Wan inference out of CI.
  - [ ] Execute and document the RX 9060 XT live gate and forced-fallback drill after code changes.

## Dev Notes

### Scope Decision and Current Blockers

- The source epic is draft prose, not a formal BDD contract. The ACs above make its conditional intent implementable without pretending they were copied verbatim.
- Current repository status is 11.1–11.4 `done`, 11.5 `backlog`, and 11.6 `ready-for-dev` only because this context file now exists (its source status was conditional `backlog`). There is no post-11.5 Jay verdict, so implementation remains blocked.
- Story 13.3 is a technical prerequisite because a new large ComfyUI workflow must not recreate hardcoded node-ID coupling. If 13.3 changes the exact manifest API, consume it rather than building a second resolver.
- No new LangGraph node/stage or UI is required. Keep the fixed scenario → image → TTS → subtitle → video graph and existing stage gates. Hero selection lives in shot metadata; I2V is an optional branch inside video rendering.
- Hosted Kling/Veo, per-shot UI selection, new gates, Diffusers bypass, all-shot I2V, and a new mega-workflow are out of scope.

### Current Code: UPDATE Files

#### `src/yt_flow/domain/state.py`

- **Current:** `CAMERA_ARCHETYPES` is the shared closed camera contract. `ShotData.image_path` is explicitly a background-only render; `cast` owns overlays.
- **Change:** add `HeroI2VMotion` and optional `hero_i2v_motion` without making old checkpoints invalid.
- **Preserve:** JSON-serializable TypedDict state, existing camera enum, absent-field compatibility, AD-1 pure-domain imports.

#### `prompts/scenario/visual_breakdown.md` and `src/yt_flow/pipeline/nodes/scenario_chain.py`

- **Current:** visual breakdown produces per-shot visual/camera/cast fields; `build_scenes` constructs `ShotData`. Story 11.2 already established closed-enum parsing and deterministic repair.
- **Change:** add the closed physical-motion nomination and deterministic invalid/default/cap behavior.
- **Preserve:** current visual/cast schema, stable shot IDs, camera-archetype diversity repair, prompt source-of-truth policy. Do not infer selection from prompt keywords.

#### `src/yt_flow/config.py`

- **Current:** Pydantic Settings uses the `YTFLOW_` prefix; ComfyUI and motion features have explicit kill switches and validated numeric fields.
- **Change:** add opt-in I2V settings. Recommended minimum: enabled, API-workflow path, timeout, max shots (bounded 1–3), target generation width/height/FPS/max frames, and backend identifier.
- **Preserve:** default-off behavior, current Comfy image settings, no hardcoded production model identity in Python.

#### `src/yt_flow/pipeline/nodes/video.py`

- **Current:** `_build_card_chain` is shared by the single-pass and per-shot renderers. `_compose_scene` gets narration-aligned `ShotClip`s. `_compose_shot_clip` creates silent clips; `_assemble_scene_from_clips` adds post-FX/subtitles/audio. The fast one-clip path combines everything in one pass. Card resolution/optional relighting happens before scene composition.
- **Change:** expose a static fully-composited frame seam, route selected clips through injected I2V, and normalize them into the silent-clip contract. A selected one-clip scene must bypass the fast path and use assembly.
- **Preserve:** `shot_timing.plan_shot_clips`, audio duration, hard cuts, card order/placement, harmonization, shake→post-FX→subtitle ordering, sound design, chapter cards, ending credit, transitions, and every disabled/non-selected branch.

#### `src/yt_flow/services/comfyui_client.py`

- **Current:** submission/polling is HTTP-only and backward-compatible image methods search only `outputs[*].images`; default polling is 180 seconds. Uploading a PNG already works.
- **Change:** add generic/video output discovery and long bounded polling with execution-error awareness.
- **Preserve:** existing image method signatures, connection-only retry policy, `/upload/image`, `/view`, and validation error detail.

#### `src/yt_flow/services/run_service.py` and `src/yt_flow/api/main.py`

- **Current:** expensive video helpers such as card relighting are injected through service/lifespan seams rather than importing upper layers directly into the pipeline.
- **Change:** wire the I2V callable through the same established seam if required by the final post-13.3 shape.
- **Preserve:** service-owned orchestration, graph topology, DB/SSE contracts, and test stub profile.

#### Tests

- Update `tests/domain/test_state_imports.py`, `tests/test_config.py`, `tests/pipeline/nodes/test_scenario_chain.py`, `tests/pipeline/nodes/test_video.py`, and `tests/services/test_comfyui_client.py`.
- Add a focused `tests/pipeline/nodes/test_i2v.py` if orchestration is extracted to `src/yt_flow/pipeline/nodes/i2v.py`.
- Use a small API-format fixture for unit tests; do not make CI download models or run ComfyUI/Wan.

### Likely NEW Files

- `src/yt_flow/pipeline/nodes/i2v.py` — recommended home for closed mapping, workflow validation/injection, cache/provenance, and injected orchestration. It must not own DB/SSE or create a LangGraph stage.
- `data/workflows/comfyui_wan22_fun_camera_i2v_api.json` — one active API-format path; no disabled duplicate graphs.
- `data/workflows/README-wan22-i2v.md` — exact sources, licenses, filenames, installation locations, export process, manifest keys, tested environment, and live-gate procedure.
- `tests/pipeline/nodes/test_i2v.py` — pure and mocked behavior.

### Architectural Compliance

- AD-1: preserve `api → services → (pipeline | db) → domain`; use existing injection patterns rather than a pipeline-to-service import cycle.
- AD-2: `ShotData` metadata remains checkpointed state; cache sidecars are derived artifacts, not competing authority.
- AD-4: do not move DB/SSE ownership into video/I2V helpers.
- AD-5: `ShotClip` planning remains sentence/narration-driven; I2V cannot alter shot timing.
- AD-10: ComfyUI is checked lazily, tracing failures remain non-fatal, and optional enhancement failures are visible but shot-local.
- No new stage: the PRD explicitly limits the v1 stage list. This is a video-stage rendering branch.

### Library and Framework Requirements

- Repository-pinned stack: Python `>=3.12,<3.13`, LangGraph `1.2.7`, `langgraph-checkpoint-sqlite 3.1.0`, FastAPI `0.138.2`, SQLModel `0.0.39`, Langfuse `4.12.0`, pydantic-settings `2.14.2`, pytest `9.1.1`, Ruff `0.15.20`.
- No Python dependency is expected: use current `httpx`/ComfyUI HTTP and FFmpeg assembly.
- Do not add model weights to Git. Pin the external ComfyUI/core/custom-node/model environment through the Story 13.3 snapshot/provenance mechanism.
- The upstream official Wan reference implementation requires far more VRAM for unquantized A14B than this machine has; low-memory success is a ComfyUI offload/quantization hypothesis until the live gate proves it.

### Previous Story Intelligence

- 11.5 has no story file yet, so the highest completed prior story is 11.4. Re-read 11.5 after it is implemented; its final renderer interface overrides this pre-11.5 analysis.
- 11.1 precedent: deterministic SHA-256 per-shot seed, deep-copied workflow mutation, cache sidecar keys, legacy sidecar invalidation, and a real ComfyUI spot-render gate. Important difference: Fun Camera uses `KSamplerAdvanced`, not the `KSampler` branch covered by 11.1.
- 11.2 precedent: closed enum in `domain/state.py`, deterministic mapping/repair, producer/consumer shared contract, and a fallback for legacy metadata.
- 11.3 precedent: camera motion attaches after full composition but before post-FX/subtitles. I2V must replace—not stack with—the procedural motion owner.
- 11.4 precedent: optional expensive processing falls back explicitly, writes real downstream state, emits trace evidence, avoids model inference in CI, and proves the integrated path in one live gate.

### Git Intelligence

- `3bd41aa` (11.1) touched image workflow seed/cache, config, compositor feathering, and parameter tests.
- `ce4bcef` (11.2) established the domain camera enum, visual-breakdown prompt wiring, deterministic scenario repair, and render mapping tests.
- `dafe436` (11.3) added the leaf `camera_path.py`, config kill switch, video integration, and FFmpeg-expression tests.
- `6aa795a` (11.4) established visible optional fallback, downstream timing write-back, rule metrics, and a live integration gate.
- Current recent commits are mostly Epic 12/13 documentation and prompt-policy work; expect `sprint-status.yaml` merge friction and stage only the target status line when implementing.

### Latest Technical Information (verified 2026-08-03)

- Official Wan2.2 supports I2V-A14B at 480p/720p, but its upstream single-GPU reference path states an 80GB VRAM minimum. This does not prove consumer-card viability. [Wan2.2 official repository](https://github.com/Wan-Video/Wan2.2)
- Official ComfyUI Fun Camera uses separate high-noise and low-noise fp8-scaled models, UMT5, Wan VAE, `WanCameraEmbedding`, and an 81-frame default. Its published RTX 4090D 24GB figures at 640×640 are roughly 513–536 seconds without acceleration and 71–108 seconds with a 4-step LoRA, with an explicit warning that acceleration may reduce dynamics. [ComfyUI Fun Camera guide](https://docs.comfy.org/tutorials/video/wan/wan2-2-fun-camera)
- The official downloadable workflow is UI format and must be exported to API format for this repository. [ComfyUI official workflow template](https://raw.githubusercontent.com/Comfy-Org/workflow_templates/refs/heads/main/templates/video_wan2_2_14B_fun_camera.json)
- VideoX-Fun documents the Fun Camera model family and its camera-control inputs; use it to verify model lineage rather than assuming a base-I2V quant is equivalent. [VideoX-Fun official repository](https://github.com/aigc-apps/VideoX-Fun)
- ComfyUI documents base Wan2.2 GGUFs as community resources, not the official Fun Camera fp8 workflow. [ComfyUI Wan2.2 guide](https://docs.comfy.org/tutorials/video/wan/wan2_2)
- AMD documents ROCm/ComfyUI and Wan 2.2 support, while its Radeon known-issues page also records video-generation corruption on some cards. Hardware/PyTorch support is not proof that this exact Fun Camera workflow works on RX 9060 XT. [AMD ComfyUI on ROCm](https://rocm.docs.amd.com/projects/comfyui/en/docs-26.04/) and [Radeon limitations](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.2/docs/limitations/limitationsrad.html)
- Generic GGUF loading through ComfyUI-GGUF is a community/custom-node path with its own compatibility and LoRA limitations. Do not silently choose it as the camera-control backend. [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF)

### Testing Requirements

- Unit tests must cover closed metadata parsing, deterministic cap after clip merging, disabled zero-call behavior, camera mapping, unsupported shake/legacy handling, stable seed, and frame-budget eligibility.
- Workflow tests must validate title keys, uniqueness, node class/inputs, high/low pairing, every `KSamplerAdvanced` seed, active-path output, and fail-fast behavior for malformed exports.
- Adapter tests must cover `videos`/generic file collections, `/view` parameters, execution-error history, timeout/cancel, transport behavior, empty bodies, and backward-compatible image paths.
- Video tests must prove exact composed PNG input, static composition contents, no post-FX/subtitle in input, no double motion, correct one-clip routing, mixed clip assembly, exact output probe, and preserved audio/subtitles.
- Fallback/cache tests must cover every AC8 class, aggregate trace counts, atomic output/sidecar, partial/legacy artifacts, and invalidation for every key class.
- Run targeted tests with `PYTHONPATH=$PWD/src`, Ruff on changed Python files, then the full suite. Prior Story 11.4 baseline was 1452 passed + 1 skipped; use the current branch baseline, not that historical count, as the comparison.
- Live evidence is mandatory after implementation; a mocked unit suite cannot establish 16GB feasibility, visual identity preservation, or the two-hour NFR.

### Project Structure Notes

- Extend the existing video-stage seam; do not create `hero_i2v` as a sixth graph stage.
- Keep workflow/model configuration in `data/workflows/` plus Settings; keep executable logic under the existing domain/pipeline/services boundaries.
- Reuse the post-11.5 composition/render API once available. Current line-level guidance against `video.py` is provisional because 11.5 is expected to refactor this exact area.
- No frontend, database migration, API route, prompt-evaluation gate, or hosted-provider file should be touched.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic 11]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 11.6]
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#Area 4]
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#Phased Prioritized Recommendations]
- [Source: _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Goals & Success Metrics]
- [Source: _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Out of Scope]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Invariants & Rules]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Structural Seed]
- [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Component Patterns]
- [Source: _bmad-output/implementation-artifacts/11-4-whisperx-always-on-beat-cuts.md]
- [Source: _bmad-output/implementation-artifacts/13-3-comfyui-workflow-ops-hardening.md]
- [Source: src/yt_flow/domain/state.py#ShotData]
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py#build_scenes]
- [Source: src/yt_flow/pipeline/nodes/video.py#_build_card_chain]
- [Source: src/yt_flow/pipeline/nodes/video.py#_compose_shot_clip]
- [Source: src/yt_flow/pipeline/nodes/video.py#_compose_scene]
- [Source: src/yt_flow/services/comfyui_client.py]
- [Source: pyproject.toml]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex — BMad create-story workflow, 2026-08-03

### Debug Log References

- Story-context creation only; no implementation or live GPU inference was performed.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Source epic's missing formal story/BDD contract was made explicit as derived requirements.
- Conditional activation, unmet 11.5/13.3 dependencies, and absent Jay verdict are surfaced as a hard stop.
- Official current sources corrected the draft's conflation of Fun Camera and generic GGUF model sizes/workflows.
- Existing video composition, ComfyUI adapter, prior Epic 11 patterns, test seams, and regression boundaries were analyzed.

### File List

- `_bmad-output/implementation-artifacts/11-6-hero-shot-selective-i2v.md` — created story context.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — story status changed from `backlog` to `ready-for-dev`; date/comment updated.
