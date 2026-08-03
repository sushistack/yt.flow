---
baseline_commit: 3393a2cfea91f4ec576dbe5c5f5e8aa2389a1c83
---

# Story 11.5: DepthFlow 2.5D Parallax — Background-Plate Motion Renderer

Status: done

<!-- The epic provides draft scope prose but no formal user-story sentence or numbered BDD acceptance criteria. The Story and ACs below are derived implementation contracts grounded in the epic, research, architecture, current code, and completed dependency evidence. -->

## Story

As Jay,
I want depth-aware 2.5D motion for background plates with separately moving character layers,
so that still-image scenes read as cinematic depth rather than quantized zoom-and-pan slides.

## Acceptance Criteria

### AC1 — Dependency truth and missing depth-contract repair

**Given** Stories 11.3 and 8.17 are marked `done`,
**when** implementation starts,
**then** the developer recognizes that 8.17 produced and approved 42 RGB plates but did not create a depth map, depth path, or depth provenance contract,
**and** Story 11.5 owns a non-destructive backfill for all 42 approved plates,
**and** every approved plate has one validated depth companion before the stock DepthFlow path is accepted,
**and** backfill never regenerates or modifies approved RGB bytes, DB approval state, timestamps, or existing provenance.

### AC2 — Versioned image/depth artifact pair

**Given** a STOCK plate or freely generated shot background,
**when** its depth companion is resolved,
**then** `ShotData` carries an optional `depth_map_path` alongside `image_path`, preserving old-checkpoint compatibility,
**and** STOCK image and depth always come from the same plate variant,
**and** a free background receives one Depth Anything V2 depth inference after image generation,
**and** a cached image with a missing or stale depth map regenerates only the depth map, never the source image,
**and** a valid image/depth pair performs zero depth inference on retry/resume.

**And** the depth cache key and atomically written sidecar include source-image SHA-256, estimator/model identity, checkpoint hash or immutable revision, preprocessing version, input/output dimensions, normalization/inversion convention, and depth SHA-256,
**and** a changed source or contract invalidates only the dependent depth/render cache.

### AC3 — Commercially usable, pinned depth estimator

**Given** Depth Anything V2 model licenses differ by size,
**when** the production estimator is selected,
**then** the default is Depth-Anything-V2-Small under Apache-2.0,
**and** Base/Large/Giant checkpoints licensed CC-BY-NC-4.0 are not silently used for a potentially monetized output path,
**and** model identity and acquisition instructions are config/documentation pinned rather than hidden in application code,
**and** model weights are not committed to the repository.

### AC4 — Deterministic numeric camera trajectory from Story 11.3

**Given** Story 11.3 currently emits closed-form FFmpeg expression strings,
**when** DepthFlow needs per-frame camera values,
**then** `camera_path.py` adds a pure numeric sampler for the same archetype/profile, `k`, trauma, duration, and FPS inputs,
**and** samples include the bounded channels needed by the renderer (x/y offset, rotation, zoom and/or depth height as explicitly mapped),
**and** the same input yields byte-stable samples across processes and retries with no use of Python `hash()` or unseeded randomness,
**and** adjacent shot indices decorrelate,
**and** `locked` with no trauma remains a no-motion path,
**and** existing `fbm_expr`, `camera_noise_exprs`, profile tables, analytic bounds, and legacy disabled behavior remain compatible.

### AC5 — DepthFlow primary renderer and exact clip contract

**Given** a surviving `ShotClip` has a valid source image/depth pair and DepthFlow is enabled,
**when** its background motion is rendered,
**then** a pinned standalone DepthFlow adapter consumes the image, explicit depth map, numeric trajectory, duration, and output settings,
**and** primary background motion does not call `_zoompan_filter`,
**and** output is a silent clip at exactly `COMP_W × COMP_H`, `FPS` (currently 25), the planned clip duration/frame count, H.264, and yuv420p,
**and** the output is validated with FFprobe before atomic promotion from a temporary path.

**And** DepthFlow runs out of process or behind an equally isolated adapter so OpenGL/context cleanup and its large optional dependency set cannot corrupt the pipeline process,
**and** the renderer has a positive configurable timeout and distinguishes unavailable runtime, headless OpenGL failure, render failure, timeout, malformed output, and validation failure.

### AC6 — Bounded displacement and artifact control

**Given** single-image displacement exposes disoccluded edges,
**when** the DepthFlow trajectory is mapped,
**then** visible x/y displacement is capped to 1–3% of frame width,
**and** depth edges are blurred/dilated using a versioned deterministic preprocessing contract,
**and** overscan/tiling settings prevent uncovered borders,
**and** DOF, vignette, lens distortion, or other effects are default-off unless the live quality gate explicitly accepts them,
**and** existing post-FX remains the sole owner of vignette/grain/color grade to prevent double application.

### AC7 — Layered character parallax with single motion ownership

**Given** a shot has resolved character cards,
**when** the DepthFlow background clip is composited,
**then** cards remain separate transparent layers and move in the same apparent direction at a closed server-owned ratio between 0.60 and 0.80 of plate displacement,
**and** the exact ratio is deterministic by the existing `near | mid | far` depth enum, not emitted as a free LLM number,
**and** cards retain stable far-to-near stacking, rule-of-thirds placement, size caps, alpha feathering, harmonization, movement mode, and micro-motion,
**and** the full combined excursion is proven not to clip the card or expose a background border.

**And** the DepthFlow path does not additionally apply the old Story 7.3 `_character_spec` macro parallax, `_zoompan_filter`, or Story 11.3 `_camera_shake_filter`,
**and** the numeric trajectory owns base movement, handheld noise, and trauma exactly once,
**and** the old renderer remains unchanged only behind the explicit DepthFlow kill-switch/last-resort fallback.

### AC8 — Existing video behavior is preserved end to end

**Given** `video.py` has fast/multi-clip and card/background-only branches,
**when** 2.5D rendering is enabled,
**then** all four branches use one shared motion-source seam rather than drifting implementations,
**and** a DepthFlow clip is assembled through the existing silent-shot pipeline,
**and** narration, sound design, hard shot cuts, post-FX, subtitle burn-in, scene duration, chapter cards, ending credit, and dip-to-black joins retain their current ownership and ordering,
**and** subtitles remain screen-space and never move with the plate,
**and** no new LangGraph stage, gate, API, or UI surface is introduced.

### AC9 — Visible, deterministic fallback ladder

**Given** depth generation or DepthFlow can fail on the local host,
**when** the primary path cannot produce a valid clip,
**then** the shot falls back to a deterministic supersampled float-affine renderer using the same numeric trajectory and FFmpeg only for encoding/assembly,
**and** if that renderer also fails, the existing zoompan renderer is the final compatibility fallback,
**and** only failure of every validated renderer fails the video stage,
**and** every degradation logs run/scene/shot plus the reason and appears in Langfuse metadata—never as silent DepthFlow success.

**Given** the feature kill switch is off,
**when** the video stage runs,
**then** DepthFlow/depth rendering is not called and existing zoompan/Story 7.3 behavior is preserved for rollback.

### AC10 — Cache, provenance, tracing, and resume safety

**Given** motion clips may be reused after interruption,
**when** a cached clip is considered,
**then** a strict atomic sidecar verifies at least image/depth SHA-256, DepthFlow immutable revision/version, adapter version, `CAMERA_PATH_VERSION`, sampled-trajectory hash, archetype, `k`, trauma, duration, FPS, geometry, displacement limits, character-layer ratio contract, and output probe data,
**and** incomplete, legacy, non-dict, mismatched, undecodable, or `.tmp` artifacts are cache misses,
**and** no failed render overwrites a previously valid depth map or clip.

**And** trace metadata reports depth source/model/version, depth cache hit/miss/backfill, renderer counts (`depthflow | affine | legacy`), renderer latency, fallback reasons, displacement limits, and camera-path version.

### AC11 — Licensing, performance, and live quality gate

**Given** current upstream DepthFlow identifies version 1.0.0, Python `>=3.10`, and AGPL-3.0 licensing,
**when** the dependency is adopted,
**then** the exact tested commit/release and dependency lock are recorded,
**and** the repository documents the project's AGPL compliance/distribution decision before production enablement,
**and** a floating Git main branch or an unreviewed ComfyUI wrapper is not used as the production contract.

**And** a real target-host gate renders at least one approved STOCK plate and one freely generated background with cards,
**and** evidence records host/GPU/driver/OpenGL, dependency/model revisions, resolution/FPS/duration, wall time, output probe, cache behavior, and fallback drill,
**and** Jay reviews representative motion for correct direction, real depth cue, no rubber edges/borders/card clipping, and acceptable 60–80% layer motion,
**and** the automated E2E pipeline remains within the PRD's two-hour ceiling.

## Tasks / Subtasks

- [x] Task 0 — Pin feasibility and license decisions (AC: 3, 5, 11)
  - [x] Spike standalone DepthFlow on the target headless/OpenGL host with an explicit depth input; record the immutable revision and command/API contract.
  - [x] Record the AGPL compliance/distribution decision before enabling the production backend.
  - [x] Pin Depth-Anything-V2-Small and its checksum/revision; reject non-commercial checkpoints from the default path.
  - [x] Choose isolated subprocess/environment packaging and update `pyproject.toml`/`uv.lock` or a documented external-runtime manifest without relying on transitive dependencies accidentally.
- [x] Task 1 — Establish the image/depth companion contract (AC: 1–3, 10)
  - [x] Add optional `ShotData.depth_map_path` and update import/shape fixtures without invalidating legacy checkpoints.
  - [x] Add a narrow depth service/injected callable with atomic cache + provenance sidecars.
  - [x] Extend STOCK resolution to return image/depth from one variant and validate both hashes.
  - [x] Add depth-only, resumable backfill for all 42 approved plates; preserve every approved image byte and lifecycle field.
  - [x] Generate depth once for new and cached free backgrounds, including the cached-image/missing-depth repair path.
- [x] Task 2 — Add the numeric Story 11.3 trajectory API (AC: 4, 6)
  - [x] Implement numeric value-noise/fBm sampling from the existing constants and profiles.
  - [x] Define the explicit channel-to-DepthFlow mapping and cap displacement by construction.
  - [x] Unit-test determinism, bounds, phase decorrelation, locked behavior, trauma decay, and parity at representative timestamps with the legacy expressions.
- [x] Task 3 — Implement the isolated renderer and fallback ladder (AC: 5, 6, 9, 10)
  - [x] Add the DepthFlow adapter with timeout, failure classification, FFprobe validation, atomic output, cache, and provenance.
  - [x] Add the supersampled float-affine fallback using the same numeric trajectory.
  - [x] Preserve legacy zoompan as explicit final fallback/kill-switch behavior only.
  - [x] Ensure optional renderer failures are shot-local but exhaustion of all renderers fails honestly.
- [x] Task 4 — Integrate layered parallax into video assembly (AC: 7, 8)
  - [x] Refactor one shared motion-source seam across fast/multi-clip × card/background-only paths.
  - [x] Consume moving background clips while preserving the shared card/harmonization chain and silent-shot assembly contract.
  - [x] Map card depth enum to closed 0.60–0.80 trajectory ratios and prove full-excursion bounds.
  - [x] Prevent double zoompan, old macro parallax, and post-composite camera shake on a successful DepthFlow path.
  - [x] Preserve audio, subtitles, post-FX, transitions, chapter cards, credits, and shot timing.
- [x] Task 5 — Add observability and regression coverage (AC: 2, 4–10)
  - [x] Trace depth/cache/renderer/fallback/version metrics and log exact shot-local degradation reasons.
  - [x] Test pair caching, stale invalidation, depth-only repair, partial crash resume, atomicity, and source-image preservation.
  - [x] Test all four video branches, no-zoompan primary behavior, no double motion, layer ratios, on-frame bounds, fallback selection, kill-switch rollback, and ordering through subtitles/post-FX.
  - [x] Run targeted tests, Ruff, and `PYTHONPATH=$PWD/src pytest tests/`; real model/OpenGL work stays outside CI.
- [x] Task 6 — Execute the target-host live gate (AC: 6, 7, 11)
  - [x] Backfill and validate depth maps for 42/42 approved plates.
  - [x] Render representative STOCK and free-background clips with and without cards.
  - [x] Verify output probe, cache hit, forced primary failure → affine fallback, and forced dual failure → legacy fallback.
  - [x] Record performance/quality evidence and Jay's visual verdict before marking the story done.

## Dev Notes

### Scope and Ground-Truth Corrections

- The source epic is draft prose, so the numbered ACs above are derived contracts rather than copied acceptance criteria.
- The declared dependencies are satisfied in sprint tracking: 11.3 and 8.17 are `done`. However, repository evidence disproves the epic's assumption that 8.17 saved depth maps. Its 42 approved assets are RGB 1920×1080 plates; `LocationPlate`, `ShotData`, resolver payloads, seed script, and manifest have no depth field. Do not code against imaginary artifacts.
- This is not a new pipeline stage. Depth inference belongs to the existing image-stage artifact lifecycle; 2.5D motion belongs to the video-stage renderer. Existing five-stage graph and gates remain fixed.
- 8.16 may later consume the same depth artifacts for placement/occlusion. Create one reusable depth-companion contract; do not add an 11.5-only file naming convention that 8.16 must reverse-engineer.
- No frontend work is required. Degradation visibility should use structured logs/trace now and the existing warning surface when Story 13.1 is implemented.

### Architecture Decision: Integration Shape

- Keep AD-1: `api → services → (pipeline | db) → domain`. A pipeline node must not import a service, DB model, or ComfyUI client.
- Recommended shape:
  - `services/depth_service.py`: estimator execution, depth preprocessing, cache/provenance, asset backfill helper.
  - `services/parallax_service.py`: isolated DepthFlow + affine fallback adapter returning a validated silent clip and structured renderer metadata.
  - Inject narrow callables into image/video using the existing location/cast/relight patterns; wire them from the service/lifespan layer.
  - Keep trajectory generation in `pipeline/nodes/camera_path.py` because it is pure renderer-independent motion data already shared by video concerns.
- Do not put DepthFlow/torch/OpenGL setup directly inside the 1,900-line `video.py`. Keep integration local to a narrow adapter and make `video.py` own only routing/assembly.
- Prefer manifest `source` metadata for depth path/hash/model provenance, matching current asset provenance and avoiding an unnecessary SQLite migration. If a DB column is chosen instead, an actual migration/backfill is mandatory—`create_all()` does not add columns to existing tables.

### Current Code: UPDATE Files

#### `src/yt_flow/domain/state.py`

- **Current:** `ShotData.image_path` is the background-only render; `cast` remains separate; `location_key` identifies STOCK lookup.
- **Change:** add optional/not-required `depth_map_path` so old checkpoints deserialize and a shot can carry an image/depth pair.
- **Preserve:** plain JSON-serializable TypedDict state, stable shot IDs, existing closed enums, no upper-layer imports.

#### `src/yt_flow/pipeline/nodes/camera_path.py`

- **Current:** deterministic two-band fBm + trauma is emitted only as FFmpeg expressions in `t`; profile keys lockstep with `CAMERA_ARCHETYPES`; `CAMERA_PATH_VERSION = "1"` supports provenance.
- **Change:** add a numeric sampler and bump the path version only if the motion contract changes. Expose normalized samples, not DepthFlow-specific objects.
- **Preserve:** `fbm_expr`, `camera_noise_exprs`, `max_excursion`, `overscan_margin`, all profile constants, no randomness, and legacy tests/kill-switch behavior.

#### `src/yt_flow/pipeline/nodes/image.py`

- **Current:** deterministic per-shot seed/sidecar, resume fast path, optional STOCK resolver, lazy ComfyUI check, input-state copies.
- **Change:** resolve/generate and attach depth companions; cached image + missing depth must not be considered permanently complete.
- **Preserve:** image bytes, source seed contract, same-variant STOCK selection, no DB imports, no in-place state mutation, and zero image generation for a cached valid source.

#### `src/yt_flow/services/location_service.py` and `src/yt_flow/services/asset_service.py`

- **Current:** approved DB rows gate usage; location resolution returns `{variant, path}`; manifest stores free-form `source` provenance plus image SHA.
- **Change:** return and verify the approved variant's depth companion; update provenance atomically only after depth success.
- **Preserve:** approval semantics, deterministic variant order, assets/workspace separation, and non-destructive failure behavior.

#### `scripts/seed_location_plates.py`

- **Current:** approved plates short-circuit, rerolls are deterministic, generation writes RGB 1920×1080, and replacement occurs only after successful output.
- **Change:** generate depth for new plates and provide a depth-only backfill path that runs before the approved-image early return.
- **Preserve:** all 42 approved image bytes, DB rows/status, existing provenance, per-item failure isolation, and resumability.

#### `src/yt_flow/pipeline/nodes/video.py`

- **Current:** `_zoompan_filter` owns background motion; `_build_card_chain` is shared; `_camera_shake_filter` applies 11.3 motion after full composition; `_compose_scene` chooses fast vs per-shot assembly; FFmpeg owns overlays/audio/subtitles/post/concat.
- **Change:** obtain a validated moving-background clip through one seam, overlay cards using numeric trajectory ratios, and force the existing silent-shot assembly where needed.
- **Preserve:** `shot_timing.plan_shot_clips`, cast resolution, alpha hard-fail, far→near order, feather/harmonization/micro-motion/movement, audio duration, hard cuts, post-FX→subtitle order, chapter cards, attribution, and final joins.

#### `src/yt_flow/config.py`, `src/yt_flow/services/run_service.py`, `src/yt_flow/api/main.py`

- **Current:** `YTFLOW_` settings and injected expensive-service seams prevent layer cycles.
- **Change:** add validated DepthFlow/depth model paths, feature kill switch, timeout, displacement/fallback settings, and inject the narrow adapters.
- **Preserve:** existing `parallax_enabled` rollback semantics, lazy external-runtime use, graph topology, DB/SSE ownership, and test stubs.

#### Dependency and documentation files

- Update `pyproject.toml` and `uv.lock` only after the target-host spike identifies the compatible pin. Document the isolated runtime, licenses, model/source paths, headless OpenGL requirements, and live-gate command in a neighboring operational README.
- Do not assume the ComfyUI Depthflow node pack is safer. It is also AGPL-3.0 and introduces custom-node/version coupling; use it only after an explicit architecture change and Story 13.3-compatible manifest contract.

### Likely NEW Files

- `src/yt_flow/services/depth_service.py`
- `src/yt_flow/services/parallax_service.py`
- `scripts/backfill_location_depth_maps.py` (or an explicit non-destructive `--depth-only` mode in the existing seed script)
- `tests/services/test_depth_service.py`
- `tests/services/test_parallax_service.py`
- `tests/test_backfill_location_depth_maps.py` when a separate script is used
- An operational README for exact runtime/model/license/provenance setup

### Testing Requirements

- Update `tests/domain/test_state_imports.py`, `tests/test_config.py`, `tests/pipeline/nodes/test_camera_path.py`, `tests/pipeline/nodes/test_image.py`, `tests/pipeline/nodes/test_video.py`, `tests/services/test_location_service.py`, `tests/services/test_asset_service.py`, `tests/test_seed_location_plates.py`, and injection/lifespan tests as required.
- CI tests must use tiny generated fixtures and fake renderer/estimator callables; they must not download weights, open a real OpenGL context, contact ComfyUI, or require a GPU.
- Pin invariants, not only function calls: same variant pair, exact once depth creation, source bytes unchanged, atomic failure, deterministic samples, 1–3% displacement bound, 0.60–0.80 closed ratios, no primary-path `zoompan`, no double camera stage, output probe contract, visible fallback, and correct assembly ordering.
- Live evidence is mandatory because FFmpeg/OpenGL/driver behavior and visual rubber-edge quality cannot be proven by mocks.

### Previous Story Intelligence

- 11.4 established the rule that quality degradation must be warning+trace visible, tests should prove pure invariants, and live evidence is required before `done`.
- 11.3's most important reusable patterns are deterministic pure motion data, `CAMERA_PATH_VERSION`, explicit kill-switch byte identity, `k = scene_index` or `scene_index * 97 + local_i`, and live validation of every actual filter-graph shape.
- 11.3's numeric-path gap is intentional scope, not a bug: it emitted FFmpeg expressions. Do not parse those strings or duplicate a second unrelated noise implementation; share the mathematical source/constants and cross-test representative samples.
- 8.17's review caught destructive replacement before success. Depth backfill must write temp → validate → atomic rename → metadata update, never delete first.
- Working-tree runs should use `PYTHONPATH=$PWD/src`; prior full-suite baselines were 1452 passed/1 skipped after 11.4 and later grew with other stories, so compare against the current suite rather than hardcoding that count as acceptance.

### Git Intelligence

- `dafe436` (11.3): `camera_path.py`, four video integration branches, deterministic fBm/trauma, versioned trace metadata, live FFmpeg validation.
- `6aa795a` (11.4): always-on alignment, visible provisional fallback, rule metric, live gate.
- `8ae36a6`, `b5a2b35`, `eb17118`, `76da474` (8.17): generator/labeler, 42 real plates, failure-safe review fixes, 42/42 approval. These commits confirm RGB plates only and provide the non-destructive backfill precedent.
- Recent commits after these are mostly planning/prompt-policy changes and do not add a hidden 11.5 implementation.

### Latest Technical Information (verified 2026-08-03)

- Upstream DepthFlow `main` identifies package version `1.0.0`, Python `>=3.10`, AGPL-3.0, and direct dependencies including numpy, Pillow, scipy, ShaderFlow, torch, torchvision, and transformers. Pin the exact tested commit rather than floating `main`.
- Its public state exposes depth height/focus/steady/zoom/offset controls and accepts explicit image+depth input; that supports a numeric trajectory adapter, but exact sign/unit mapping must be proven by the live gate.
- The upstream project advertises optimized ray-marching GLSL, explicit external depth maps, native supersampling, and FFmpeg piping. Treat performance claims as hypotheses until measured on the target host.
- Official Depth Anything V2 provides Small (24.8M), Base (97.5M), and Large (335.3M) relative-depth models. The Small model is Apache-2.0; Base/Large/Giant weights are CC-BY-NC-4.0. Small is therefore the safe default for this potentially monetized pipeline.
- The ComfyUI wrapper exposes image, depth map, motion, effects, frames/FPS, quality, supersampling, inversion, and tiling inputs, but it adds custom-node/Flex dependencies and shares AGPL licensing. It is not the default production adapter for this story.

### Project Structure Notes

- The planned services are narrow infrastructure adapters, not a new domain layer or stage.
- Keep generated depth maps beside their source asset/run artifact with deterministic names and sidecars; keep reusable STOCK depth under `assets/`, free-run depth under `workspace/{run_id}/`, and never cross those cleanup boundaries.
- Story 11.6 consumes the fully composited post-11.5 frame/clip contract. Do not add I2V hooks here.
- Story 8.16 should later consume the same depth companion and estimator metadata; do not implement its ground-plane, occlusion, IC-Light, or libcom scope in 11.5.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 11.5]
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 11]
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#4.2]
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#4.5]
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#Phase 1]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10]
- [Source: _bmad-output/implementation-artifacts/11-3-fractal-noise-camera-paths.md]
- [Source: _bmad-output/implementation-artifacts/11-4-whisperx-always-on-beat-cuts.md]
- [Source: _bmad-output/implementation-artifacts/spec-8-17-location-plate-data-generation.md]
- [Source: src/yt_flow/pipeline/nodes/camera_path.py]
- [Source: src/yt_flow/pipeline/nodes/video.py]
- [Source: src/yt_flow/pipeline/nodes/image.py]
- [Source: src/yt_flow/domain/state.py]
- [Source: src/yt_flow/services/location_service.py]
- [Source: src/yt_flow/services/asset_service.py]
- [Source: scripts/seed_location_plates.py]
- [DepthFlow upstream](https://github.com/BrokenSource/DepthFlow)
- [ComfyUI Depthflow wrapper](https://github.com/akatz-ai/ComfyUI-Depthflow-Nodes)
- [Depth Anything V2 upstream](https://github.com/DepthAnything/Depth-Anything-V2)
- [3D Ken Burns Effect, Niklaus et al.](https://arxiv.org/abs/1909.05483)

## Dev Agent Record

### Agent Model Used

GPT-5 (story context) / Claude Opus 5 (implementation)

### Debug Log References

- `docs/PARALLAX_RUNTIME.md` — licensing decisions, external-runtime install, tunables, ops commands, measured performance table.
- Live gate evidence is inlined in the Completion Notes below. Review clips for Jay: `~/ytflow-11-5-review/` (A 2.5D+cards, B 2.5D bg-only, C 2.5D free background, D legacy zoompan for comparison, plus four extracted frames).

### Completion Notes List

**Two story premises were disproved by repository evidence before coding started.**

1. *"8.17 produced no depth map, no depth path, no depth provenance contract."* Story
   8.16 (`done`, `depth_placement_enabled=True`) already owned a content-addressed
   depth cache driven by ComfyUI `DepthAnythingV2Preprocessor`, and all 42 approved
   plates already had maps. So AC1/AC2 became *extend and correct* the existing
   contract, not build a parallel one — which is what the Dev Notes asked for
   ("one reusable depth-companion contract; do not add an 11.5-only convention").
2. *DepthFlow as the working primary renderer.* It is not installed, needs a
   GPU/headless-OpenGL spike, and is AGPL-3.0. Jay chose (decision recorded in
   session) to make the middle rung a **numpy depth-displacement warp** rather than
   AC9's literal "flat float-affine", so 2.5D depth actually renders today with zero
   new dependencies, and to keep the DepthFlow adapter as an off-by-default external
   subprocess runtime.

**A live licensing defect was found and fixed (AC3).** `comfyui_depth_anything_v2_api.json`
ran `depth_anything_v2_vitl.pth` — Large, **CC-BY-NC-4.0** — on a monetized output
path, and the depth cache was keyed on the plate's bytes *alone*, so swapping the
model would have served Large-model maps forever. Both fixed: the checkpoint and
resolution now come from config and are injected per call, the cache key covers the
estimator contract, and `depth_contract()` *raises* for any non-Apache-2.0 or
unrecognised checkpoint unless `depth_allow_noncommercial_model` is set.

**Architecture.** `services/depth_service.py` was NOT created — the Dev Notes'
"Likely NEW Files" list predated 8.16's existing depth infrastructure, and a second
depth service would have been the duplication the notes warned against. Depth work
extends `compositing_service`; `services/parallax_service.py` owns the renderer
ladder; `pipeline/nodes/camera_path.py` owns the numeric trajectory and the overscan
margin (single owner, passed to the renderer); `video.py` owns only routing/assembly
through one `MotionSource` seam.

**AC-by-AC live evidence** (target host: Linux 7.0.0, 16 cores, AMD RX 9060 XT
13.6GB free, ComfyUI 0.12.3, torch 2.11.0.dev+rocm7.1, ffmpeg 6.1.1, direct
rendering yes):

- **AC1** 42/42 approved plates backfilled with the Small model, live. Re-run: 42
  cache hits, **0 inference**. `git status assets/` clean — zero approved RGB bytes,
  DB rows, statuses or manifest entries touched. Per-plate failure isolation and
  missing-file reporting both covered by tests.
- **AC2** `ShotData.depth_map_path` added `NotRequired` (pre-11.5 checkpoints still
  deserialize). Resolved on all three image_node writer paths, so a cached image with
  a missing/stale depth map regenerates **only** the depth map. Sidecar carries source
  SHA-256, depth SHA-256, model ckpt + license, resolution, preproc version, in/out
  dimensions and the `relative-brighter-nearer` convention.
- **AC3** default is `depth_anything_v2_vits.pth` / Apache-2.0, enforced not
  documented. Weights not committed.
- **AC4** `camera_path.sample_path` proven to be the *same curve* as Story 11.3's
  ffmpeg expressions — the parity test `eval()`s the generated expression strings
  against the numeric sampler and matches to **1e-12** across every archetype and
  trauma value. Byte-stable across processes, no `hash()`, no unseeded randomness.
- **AC5** Output contract validated by FFprobe before atomic promotion:
  `1920x1080 / h264 / yuv420p / 25fps / exact frame count`. Verified live on a STOCK
  plate and a free background. A deliberately 320x180 render is rejected
  (`validation_failed`) and never promoted. Failure taxonomy distinguishes
  `unavailable / headless_gl_failure / render_failed / timeout / malformed_output /
  validation_failed / no_depth_map / disabled`.
- **AC6** Measured on the real plate + real Small depth map at the 2%-of-width
  budget (38.4px cap): nearer region displaced **34px**, farther region **23px** —
  an 11px depth differential, both inside the cap. Zero of 125 frames exposed a
  black border (worst frame's brightest edge pixel = 238). DOF/vignette/lens
  distortion are off; post-FX remains the sole owner of vignette/grain/grade.
- **AC7** Measured with a segmentable sprite through the real filtergraph: card
  travel **12.0 / 14.0 / 14.0 px** for far/mid/near against the trajectory's actual
  18.4px travel = ratios **0.65 / 0.76 / 0.76**, inside the 0.60–0.80 band (±1px
  pixel quantization). Card fully on-frame on every plane and every frame; card width
  constant per plane (279/381/507px), so no stray scaling. On a successful 2.5D clip
  `bg_chain == "null"` (no zoompan), `camera_shake == ""` (no post-composite shake)
  and `parallax_enabled is False` (no 7.3 macro parallax) — motion is owned exactly
  once. The motion-safe box now reserves the layer ceiling (46.08px/side vs 7.3's
  12px), which moved `CHAR_MAX_H` 796.34 → 743.28 and `_CARD_HEIGHT_FRAC` with it.
- **AC8** One `MotionSource` seam feeds all four branches (fast/multi-clip ×
  card/background-only); a test renders through each and asserts the clip is used and
  `zoompan` appears nowhere. Narration, sound design, hard cuts, post-FX, subtitle
  burn-in, chapter cards, credits and dip-to-black joins keep their ownership and
  ordering. No new stage, gate, API or UI surface.
- **AC9** Ladder drilled live: forced primary failure → `render_failed`, missing
  depth → `no_depth_map`, kill switch → `disabled`; every one logs run/scene/shot plus
  the reason and lands in `parallax_25d.renderer_counts` keyed `fallback_<reason>`.
  Kill switch off restores the pre-11.5 path (`bg_chain == _zoompan_filter(...)`,
  11.3 shake and 7.3 parallax both back on).
- **AC10** Clip sidecar carries image/depth SHA-256, adapter version, depth-edge
  version, `CAMERA_PATH_VERSION`, sampled-trajectory hash, archetype, k, trauma,
  duration, fps, geometry, displacement cap, overscan margin, layer-ratio contract
  and the FFprobe result. Cache hit on identical inputs: **0.01s**, zero rendering.
  Legacy/non-dict/malformed/`.tmp`/byte-changed artifacts are all misses. A forced
  failure provably left the previous valid clip and its sidecar byte-identical, with
  no `.tmp` residue. Re-render with identical inputs is **byte-identical**.
- **AC11** DepthFlow is documented as an external AGPL-3.0 runtime, never a project
  dependency (a test asserts `depthflow`/`shaderflow` are absent from
  `pyproject.toml`); the compliance reasoning is in `docs/PARALLAX_RUNTIME.md` §3.
  Performance: 250 → **53 ms/frame** warp after row-blocking + 4 threads,
  **~71 ms/frame** end-to-end including encode (7.1s for a 4s clip; ~14 min of
  warping for an 8-minute video), which keeps the run inside the PRD two-hour ceiling.

**Two items are explicitly NOT done and are Jay's:**

1. **DepthFlow rung-1 spike** (Task 0 / AC11). Not installed here, and the runner
   script drives upstream's documented `DepthScene` API *unverified*. `depthflow_enabled`
   stays `false`. An API mismatch exits 3 → classified `unavailable` → degrades to
   rung 2 with a warning, so a wrong guess costs a log line.
2. **Jay's visual verdict** (AC11) on direction, depth cue, rubber edges, borders,
   card clipping and the 60–80% layer read. Clips are in `~/ytflow-11-5-review/`.

**Recorded regression, deliberately not fixed here (belongs to 8.16, not 11.5).**
The Small checkpoint produces flatter depth maps than Large: plates with a readable
floor dropped **41 → 30 of 42**, so 12 plates now hit `_MIN_GROUND_SPREAD` and use the
fallback medians instead of their own measured floor. Ordering still holds
far≤mid≤near on 30/30. `_DEFAULT_GROUND` was re-measured on the same 42 plates with
the model actually in use (deltas far −0.005, mid +0.015, near +0.014) rather than
left pinned to Large-measured numbers.

**Test-quality finding.** Seeding a depth map without its provenance sidecar became a
deliberate cache miss under AC10, which silently degraded three existing
`resolve_placements` tests to `_DEFAULT_GROUND` — and they still passed, because the
fallback happens to satisfy `far < near`. The fixture now seeds a real pair through the
production writer, so those three assert what they claim again.

Suite: **1818 passed, 1 skipped** (baseline before this story: 1608 + the 102 this
work initially broke). Ruff clean.

### File List

**NEW**
- `src/yt_flow/services/parallax_service.py`
- `scripts/depthflow_render.py`
- `scripts/backfill_location_depth_maps.py`
- `docs/PARALLAX_RUNTIME.md`
- `tests/services/test_parallax_service.py`
- `tests/pipeline/nodes/test_video_parallax_25d.py`
- `tests/test_backfill_location_depth_maps.py`

**MODIFIED**
- `src/yt_flow/config.py`
- `src/yt_flow/domain/state.py`
- `src/yt_flow/api/main.py`
- `src/yt_flow/pipeline/nodes/camera_path.py`
- `src/yt_flow/pipeline/nodes/image.py`
- `src/yt_flow/pipeline/nodes/video.py`
- `src/yt_flow/services/compositing_service.py`
- `data/workflows/comfyui_depth_anything_v2_api.json`
- `tests/domain/test_state_imports.py`
- `tests/pipeline/nodes/test_camera_path.py`
- `tests/pipeline/nodes/test_image.py`
- `tests/pipeline/nodes/test_video.py`
- `tests/pipeline/nodes/test_video_depth_placement.py`
- `tests/pipeline/nodes/test_video_harmonization.py`
- `tests/services/test_compositing_service.py`
- `_bmad-output/implementation-artifacts/11-5-depthflow-25d-parallax.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

**MODIFIED BY REVIEW** (all already listed above except the last)
- `src/yt_flow/services/parallax_service.py` — `_cover_resize` shared framing, `DEPTH_EDGE_VERSION` 1→2, `warp_frame` is the production kernel, `DEPTHFLOW_RUNNER` anchored to `__file__`
- `src/yt_flow/pipeline/nodes/video.py` — `_GROUND_Y_MAX` reserve, contact-shadow layer terms, corrected rollback claims
- `src/yt_flow/api/main.py` — `_resolve_depth` uses `verify_depth_pair` for `cached`
- `docs/PARALLAX_RUNTIME.md` — §1/§4 kill-switch scope corrected
- `tests/services/test_parallax_service.py` — depth/plate framing test, `DEPTH_EDGE_VERSION` pin
- `tests/pipeline/nodes/test_video_parallax_25d.py` — ground-clamp reserve, on-frame excursion, contact-shadow ×2
- `tests/pipeline/nodes/test_video_depth_placement.py` — shadow-stage parse made spelling-independent

## Senior Developer Review (AI)

**Reviewer:** Jay · **Date:** 2026-08-03 · **Outcome:** Approve (7 findings fixed, 4 recorded)
**Suite after fixes:** 1826 passed, 1 skipped (1818 + 8 new). Ruff clean.

Every load-bearing claim in the Completion Notes was re-derived from primary
evidence rather than read. The dev's two explicit requests for independent
verification — the `MotionSource` seam and the hand-optimised warp math — both
hold. Seven defects were found and fixed; one of them is a real correctness bug
the offline tests could not see because every fixture is 1920×1080.

### Independently verified (not taken on trust)

| Claim | Method | Result |
|---|---|---|
| Warp direction + depth proportionality | Synthetic plate, two markers, half/half depth map, constant +x ramp, decoded and centroid-tracked | Near plane **+38.0px** vs the 38.4px budget; far plane **+10.0px** vs 9.6px expected (gain 0.25). Positive `dx` moves content right, and the card layer term shares that sign — the depth cue is real and the plate/card directions agree |
| Warp performance (250 → 53 ms/frame) | Re-benchmarked the kernel on the target host, 15 reps | **45.1 ms/frame** at 4 threads × 32 blocks vs **164.5 ms** whole-frame. End-to-end on a real plate **59 ms/frame**. Better than claimed, not inflated |
| Output contract | FFprobe on live renders, STOCK plate and a real 1216×832 free background | `1920x1080 / h264 / yuv420p / 25fps / exact frame count` on both |
| 42-plate backfill non-destructive + reproducible | Re-ran `--dry-run` | **42 cache hits, 0 inference**; `git status assets/` clean |
| License fix airtight | Read every reachable path; grepped the tree for `vitb/vitl/vitg` | No path can serve a CC-BY-NC map. The new key is `sha256(source:contract)` **and** requires a provenance sidecar, so the 42 pre-11.5 Large-model maps at the old bytes-only paths are permanently unreachable, not merely deprioritised. `depth_contract()` raises for non-Apache-2.0 **and** unknown names |
| 8.16 regression is real and correctly scoped | Re-measured `ground_plane` across all 42 approved plates with the shipped Small maps | **30/42 readable** (matches 41→30), **0 far≤mid≤near violations on 30/30**, medians **0.7634 / 0.8627 / 0.9453** vs the coded `0.763 / 0.863 / 0.945`. The model swap is forced by AC3; `_MIN_GROUND_SPREAD` tuning is 8.16's constant. Scope call upheld |
| No double motion, all four branches | Read every branch + adversarial test | `_render_scene_fast`×{cards, bg-only} and `_compose_shot_clip`×{cards, bg-only} all build from `motion.bg_input`/`motion.bg_chain`. On a 2.5D clip `bg_chain=="null"`, `camera_shake==""`, `parallax_enabled is False`. Confirmed |
| Ladder degrades, `depthflow_enabled=false` shipped | Read `render_motion_clip`'s backend loop | Rung 1 failure `continue`s to rung 2; rung 2 failure returns `path=None` → caller's rung 3 zoompan, which always moves. No silent still frame anywhere. Default confirmed `false` |
| Suite / lint | `PYTHONPATH=$PWD/src pytest tests/`, `ruff check .` | **1818 passed, 1 skipped** pre-fix (matches the claim); clean after fixes |

### Findings

**HIGH — 1. The depth field was misaligned with the plate on every freely generated background.**
`_load_overscan_source` cover-crops the plate; `depth_gain_field` plain-`resize`d
the depth map. Those agree only for an exactly-16:9 source. Stock plates are
1920×1080 so the bug was invisible there — but `comfyui_sdxl_anime_lora_layered_api`
generates **1216×832** and every real free background on disk is that size.
Measured on a matched horizontal split: **27px of misalignment at the 40% row,
~100px at the frame edges**, i.e. foreground pixels driven by the far-plane gain
and vice versa, with the disocclusion dilation applied to the wrong boundary.
Every offline fixture is 1920×1080, so no test could see it.
*Fixed:* one shared `_cover_resize` framing helper for both, `DEPTH_EDGE_VERSION`
bumped `1 → 2` to invalidate clips warped against the misaligned field, plus
`test_depth_field_is_framed_exactly_like_the_plate` parameterised over
1216×832 / 1344×768 / 1920×1080 / 900×1600. Post-fix misalignment ≤ `DEPTH_DILATE_PX`.

**MEDIUM — 2. `_GROUND_Y_MAX` kept 7.3's 12px pan reserve while cards gained a 46.08px layer term.**
`CHAR_MAX_W/H` were correctly widened to `_MACRO_PAN_RESERVE_PX`, but the ground
clamp — the *production* placement path, `depth_placement_enabled=True` — was not.
Analytic worst case ran **34.1px past the bottom edge at 3% displacement, 18.7px
at the shipped 2%**. Sampled trajectories only reached ~29px of the 46.08px
ceiling, so it survived by ~5px of coincidence rather than clipping outright —
which is the same "only by luck" that comment already warns about, and not a bound
this module accepts. AC7's "full combined excursion is **proven** not to clip" and
Task 4's "prove full-excursion bounds" were therefore only half met.
*Fixed:* clamp uses `_MACRO_PAN_RESERVE_PX`. Two tests: the analytic reserve
(fails pre-fix) and an observed-value companion sweeping `_PAN_POOL` so the
downward pans are covered.

**MEDIUM — 3. The contact shadow did not ride the layer translation.**
8.16's own comment says "the shadow has to slide with them or the card grows a
detached puddle", and `shadow_y` tracks `ground_expr`'s zoom — but the 2.5D layer
term was added to the card only. The shadow slid **up to 30.7px out from under the
character at the shipped 2%** (46.08px at 3%). The shadow is the card's own
footprint, so it belongs to the card's layer.
*Fixed:* layer terms applied to the shadow overlay's `x`/`y`, 2.5D path only
(legacy keeps `x=0`). Idle bob/sway still deliberately excluded — feet lift off a
stationary shadow, a whole layer does not. Two tests, one per path.

**MEDIUM — 4. `warp_frame` was tested but never shipped.**
`_render_depth_warp` inlined its own equivalent of `warp_frame`, which was
referenced only by tests — so the determinism, direction and shape invariants were
pinned on a copy of the production kernel.
*Fixed:* `_render_depth_warp` calls `warp_frame`. Output verified
**byte-identical** (`9687a3cd…` before and after).

**MEDIUM — 5. The trace could report `depth_hit` for a map that was actually re-inferred.**
`_resolve_depth` derived `cached` from `cache.is_file()`, not `verify_depth_pair` —
so a map without a valid sidecar (8.16's legacy maps, or a crash between map and
sidecar) reported a hit while `depth_map_file` re-ran inference. AC10 requires the
depth cache hit/miss signal to be accurate; this made it lie in exactly the case
that matters.
*Fixed:* `cached` asks the same strict question `depth_map_file` asks.

**MEDIUM — 6. Four "byte-identical rollback" claims are false.**
`_MACRO_PAN_RESERVE_PX` (so `CHAR_MAX_W/H` and `_GROUND_Y_MAX`),
`compositing_service._CARD_HEIGHT_FRAC`, and `_DEFAULT_GROUND` all moved
**unconditionally** — not gated on `parallax_25d_enabled`. A kill-switch-off run
gets ~6.7% shorter cards, a tighter ground clamp and Small-model ground medians.
The *filtergraph* is unchanged; the output is not. Asserted in
`inject_motion_renderer`'s comment, `MotionSource`'s docstring, `_legacy_motion`'s
docstring and `docs/PARALLAX_RUNTIME.md` §1/§4.
*Fixed:* all five sites now state what is actually true and name the three
constants. The switch rolls back the renderer, not the render.

**LOW — 7. `DEPTHFLOW_RUNNER` was resolved relative to the process CWD.**
Rung 1 would report `unavailable` for any server not launched from the repo root —
the most confusing possible outcome for the Task 0 spike, because "DepthFlow is
not installed" and "you started uvicorn elsewhere" look identical in the log.
*Fixed:* anchored via `__file__`.

### Recorded, deliberately not fixed

1. **Rung 2 has no timeout.** AC5's "positive configurable timeout" is satisfied
   for rung 1 (`depthflow_timeout_sec`). The warp is in-process numpy plus a local
   ffmpeg pipe; a second timeout knob for a hang that has no observed failure mode
   is speculative config. Revisit if one ever hangs.
2. **The "0 of 125 frames exposed a black border" evidence is unfalsifiable.**
   `_warp_block` clamps sample coordinates into the source, so an undersized
   overscan smears the edge pixel rather than showing black — the test cannot
   fail. The overscan *math* is independently sound (margin 0.061–0.071 against a
   27px observed excursion, large headroom), so the conclusion stands; the evidence
   just does not support it. A real border test would have to compare against the
   analytic requirement, not sample the output.
3. **`xy_gain` crushes the Ken Burns base move on high-energy archetypes.**
   Capping the *combined* peak means `gain = xy_peak / (|pan| + noise_xy)`, so
   `shake` at trauma 0.8 with a 3% budget delivers only **1.16% of width**
   observed — the depth cue is weakest on exactly the shots with the most camera
   energy. Sound by construction (the cap holds), but a deliberate trade worth
   Jay's eye at the visual gate. Not a defect.
4. **42 orphaned Large-model depth maps** remain in `workspace/cache/depth/`
   (85 `.png` vs 43 `.json`). Unreachable by construction and documented as safe to
   delete in `docs/PARALLAX_RUNTIME.md` §2. No cleanup written — deletion is
   Jay's call, not a script's.

### Effect of finding 1 on the recorded live evidence

None of the numbers in the Completion Notes are invalidated. AC6's 34px/23px
differential and AC7's 0.65/0.76/0.76 ratios were measured on a **1920×1080 stock
plate**, where the two framings agreed. AC5's free-background evidence validated
the output *contract* (geometry/codec/frame count), which the misalignment does
not touch — the depth *cue* on a free background was never separately measured, so
nothing was measured wrongly. Re-verified live post-fix on a real 1216×832
background from run `0161138d`: depth estimated (1497×1024), probe
`1920x1080/h264/yuv420p/25fps/100 frames`, no black border. What remains is that
free-background depth quality now differs from what is in
`~/ytflow-11-5-review/` clip C — fold that into the pending visual verdict.

### Still Jay's (unchanged by this review)

1. **DepthFlow rung-1 spike** (Task 0 / AC11) — not installed, runner API
   unverified, `depthflow_enabled=false`. An API mismatch exits 3 → `unavailable`
   → rung 2 with a warning, so a wrong guess costs a log line.
2. **Visual verdict** (AC11) on direction, depth cue, rubber edges, borders, card
   clipping and the 60–80% layer read. Clips in `~/ytflow-11-5-review/`; clip C
   (free background) should be re-rendered first — see above.

## Change Log

| Date | Change |
|---|---|
| 2026-08-03 | Depth companion contract: `ShotData.depth_map_path`, estimator identity in the cache key, atomic provenance sidecar, strict pair verification, `image_node` depth resolution on all three writer paths, non-destructive 42-plate backfill script (run live, 42/42). |
| 2026-08-03 | AC3 licensing fix: default depth checkpoint Large (CC-BY-NC-4.0) → Small (Apache-2.0), config-pinned and injected per call, with a hard refusal for non-commercial/unknown checkpoints. |
| 2026-08-03 | `camera_path`: numeric per-frame trajectory sampler sharing Story 11.3's constants (1e-12 expression parity), displacement clamp, xy gain, sample-derived overscan margin. |
| 2026-08-03 | `parallax_service`: renderer ladder (external DepthFlow → numpy depth warp → legacy), FFprobe validation, atomic promotion, clip cache + provenance, failure taxonomy. Warp optimised 250 → 53 ms/frame. |
| 2026-08-03 | `video.py`: one `MotionSource` seam across all four render branches; layered card parallax at closed 0.60/0.70/0.80 depth ratios; motion-safe box widened to the layer ceiling; 2.5D trace metadata. |
| 2026-08-03 | `_DEFAULT_GROUND` re-measured against the Small model; the 41 → 30 readable-floor regression recorded in-code for 8.16. |
| 2026-08-03 | Docs: `docs/PARALLAX_RUNTIME.md` (AGPL compliance decision, model licensing, external runtime install, tunables, ops, measured performance). |
| 2026-08-03 | **Review fixes (7).** HIGH: depth gain field was plain-resized while the plate was cover-cropped — ~100px depth/image misalignment on every 1216×832 free background; one shared `_cover_resize`, `DEPTH_EDGE_VERSION` 1→2. MEDIUM: `_GROUND_Y_MAX` reserved 12px not 46.08px (analytic 34.1px bottom-edge overrun); contact shadow did not ride the layer translation (30.7px detached); `warp_frame` was tested but not shipped (now called, byte-identical); `depth_hit` trace could report a hit for a re-inferred map; four false "byte-identical rollback" claims corrected. LOW: `DEPTHFLOW_RUNNER` was CWD-relative. 5 new tests, 1 existing parse updated. |
