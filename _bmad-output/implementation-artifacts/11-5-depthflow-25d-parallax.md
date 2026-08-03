# Story 11.5: DepthFlow 2.5D Parallax — Background-Plate Motion Renderer

Status: ready-for-dev

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

- [ ] Task 0 — Pin feasibility and license decisions (AC: 3, 5, 11)
  - [ ] Spike standalone DepthFlow on the target headless/OpenGL host with an explicit depth input; record the immutable revision and command/API contract.
  - [ ] Record the AGPL compliance/distribution decision before enabling the production backend.
  - [ ] Pin Depth-Anything-V2-Small and its checksum/revision; reject non-commercial checkpoints from the default path.
  - [ ] Choose isolated subprocess/environment packaging and update `pyproject.toml`/`uv.lock` or a documented external-runtime manifest without relying on transitive dependencies accidentally.
- [ ] Task 1 — Establish the image/depth companion contract (AC: 1–3, 10)
  - [ ] Add optional `ShotData.depth_map_path` and update import/shape fixtures without invalidating legacy checkpoints.
  - [ ] Add a narrow depth service/injected callable with atomic cache + provenance sidecars.
  - [ ] Extend STOCK resolution to return image/depth from one variant and validate both hashes.
  - [ ] Add depth-only, resumable backfill for all 42 approved plates; preserve every approved image byte and lifecycle field.
  - [ ] Generate depth once for new and cached free backgrounds, including the cached-image/missing-depth repair path.
- [ ] Task 2 — Add the numeric Story 11.3 trajectory API (AC: 4, 6)
  - [ ] Implement numeric value-noise/fBm sampling from the existing constants and profiles.
  - [ ] Define the explicit channel-to-DepthFlow mapping and cap displacement by construction.
  - [ ] Unit-test determinism, bounds, phase decorrelation, locked behavior, trauma decay, and parity at representative timestamps with the legacy expressions.
- [ ] Task 3 — Implement the isolated renderer and fallback ladder (AC: 5, 6, 9, 10)
  - [ ] Add the DepthFlow adapter with timeout, failure classification, FFprobe validation, atomic output, cache, and provenance.
  - [ ] Add the supersampled float-affine fallback using the same numeric trajectory.
  - [ ] Preserve legacy zoompan as explicit final fallback/kill-switch behavior only.
  - [ ] Ensure optional renderer failures are shot-local but exhaustion of all renderers fails honestly.
- [ ] Task 4 — Integrate layered parallax into video assembly (AC: 7, 8)
  - [ ] Refactor one shared motion-source seam across fast/multi-clip × card/background-only paths.
  - [ ] Consume moving background clips while preserving the shared card/harmonization chain and silent-shot assembly contract.
  - [ ] Map card depth enum to closed 0.60–0.80 trajectory ratios and prove full-excursion bounds.
  - [ ] Prevent double zoompan, old macro parallax, and post-composite camera shake on a successful DepthFlow path.
  - [ ] Preserve audio, subtitles, post-FX, transitions, chapter cards, credits, and shot timing.
- [ ] Task 5 — Add observability and regression coverage (AC: 2, 4–10)
  - [ ] Trace depth/cache/renderer/fallback/version metrics and log exact shot-local degradation reasons.
  - [ ] Test pair caching, stale invalidation, depth-only repair, partial crash resume, atomicity, and source-image preservation.
  - [ ] Test all four video branches, no-zoompan primary behavior, no double motion, layer ratios, on-frame bounds, fallback selection, kill-switch rollback, and ordering through subtitles/post-FX.
  - [ ] Run targeted tests, Ruff, and `PYTHONPATH=$PWD/src pytest tests/`; real model/OpenGL work stays outside CI.
- [ ] Task 6 — Execute the target-host live gate (AC: 6, 7, 11)
  - [ ] Backfill and validate depth maps for 42/42 approved plates.
  - [ ] Render representative STOCK and free-background clips with and without cards.
  - [ ] Verify output probe, cache hit, forced primary failure → affine fallback, and forced dual failure → legacy fallback.
  - [ ] Record performance/quality evidence and Jay's visual verdict before marking the story done.

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

GPT-5

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Story source, PRD, architecture, UX, quality research, current code, completed dependency artifacts, recent Git history, and current upstream technical/license information were cross-checked.
- Critical correction captured: Story 8.17 has 42 approved RGB plates but no depth maps; Story 11.5 owns their non-destructive depth backfill.
- Critical integration guard captured: Story 11.3 exposes FFmpeg expressions, so a deterministic numeric trajectory API is required; successful DepthFlow clips must not receive zoompan/legacy macro parallax/post-composite camera shake again.

### File List

- `_bmad-output/implementation-artifacts/11-5-depthflow-25d-parallax.md` (NEW)
