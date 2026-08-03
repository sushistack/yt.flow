---
created: 2026-08-03
baseline_commit: 7141707
story_key: 8-20-openpose-conditioned-action-poses
story_id: "8.20"
epic: 8
depends_on:
  - 8-4-on-demand-special-pose-cards
  - 8-6-asset-library-management
  - 13-3-comfyui-workflow-ops-hardening
related:
  - 8-4a-special-pose-prompt-gate-decomposition
  - 8-13-derived-entity-card-on-demand
  - spec-8-15-stock-face-mask-bias-fix
  - 8-18-cast-decision-diversity-validator
  - 13-1-surface-silent-degradations
---

# Story 8.20: OpenPose-Conditioned Action Poses

Status: ready-for-dev

## Story

As Jay,
I want special action-pose cards derived from an approved character card through identity-preserving reference editing and anatomy-appropriate structural conditioning,
so that shots show varied, readable actions without character drift, face-detector failures, or unbounded per-run generation cost.

## Context

The SCP-049 iteration contained 151 cast placements but only two base poses (`standing=105`, `sitting=46`). Ten placements requested `pose_hint`; the current per-run cap allowed at most three new hint cards, and Story 8.4 generated those cards through an ordinary text prompt plus front-card IPAdapter reference. The trigger, cache, cap, fallback, and resolver work; the generation mechanism does not provide reliable action geometry or identity preservation.

This story primarily replaces that generation mechanism and adds only the catalog metadata needed to choose a structural guide safely. Qwen-Image-Edit-2511 reference editing is the identity-preserving base. A curated OpenPose-style guide may additionally control humanoid geometry; non-humanoids must use a proven depth, lineart, or scribble route. OpenPose is not a universal route, and real-face embedding systems are explicitly excluded.

**Implementation prerequisite:** Story 13.3 must be complete so this story reuses the canonical `ytflow:*` workflow-node resolver and environment snapshot. If it is not complete, stop after the technology spike; do not create a second resolver.

## Acceptance Criteria

1. **Technology adoption gate.** Given the local 16 GB ROCm ComfyUI host, when the developer evaluates the current VNCCS one-pose path and the native Qwen-Image-Edit-2511 workflow, then the decision record includes exact ComfyUI/custom-node/model/LoRA versions and hashes, license, quantization, peak VRAM, wall time, output dimensions, and failure behavior. The adopted path must run locally on the target host. Model-file size alone is not accepted as proof of 16 GB viability.

2. **Minimal conditioned workflow.** Given the adoption decision passes, when the workflow is committed, then it is a minimal API-format workflow accepting one approved reference card, one action instruction, and optionally one structural guide. It must include and pin the existing proven InSPyReNet cutout stage (or a live-proven equivalent), then pass the resulting transparent sprite through the shared alpha cleanup/scale normalization. Flat RGB or opaque output is failure. Do not import VNCCS's broad character-management lifecycle, caches, UI, clothing/emotion pipeline, or multi-pose grid. If VNCCS is selected, pin the evaluated upstream revision and extract only the one-pose path.

3. **Narrow service boundary.** Given `src/yt_flow/services/pose_service.py`, when `CharacterService` requests a special pose, then the typed request contains the approved reference path, `pose_hint`, explicit conditioning profile/guide, deterministic seed, width, and height. The service deep-copies and validates the configured workflow; resolves nodes through Story 13.3's canonical `ytflow:*` resolver; uploads inputs through the existing ComfyUI client; injects every required parameter exactly once; and returns processed PNG bytes plus actual seed/provenance. It owns no DB, manifest, run, gate, or LangGraph state writes.

4. **Deterministic anatomy routing.** Given a `Character`, when a pose is requested, then routing reads a durable character-level `pose_conditioning` field: `openpose`, `depth`, `lineart`, `scribble`, or `edit_only`. Add an idempotent SQLite column migration through the repository's existing `db.init()` additive-migration pattern and explicitly backfill existing characters. All creation paths set the safe default `edit_only`; missing or invalid values warn and use `edit_only`. Card-key or descriptor keyword inference is forbidden.

5. **Explicit guide source.** Given the free-text `pose_hint`, the cast contract also carries an optional closed `pose_guide_key` selected from the approved guide catalog. The cast prompt, parser, `CastMember`, and artifact serialization validate the key without changing `pose_hint` or other cast semantics. Guides live under the configured asset root and use the existing `AssetService` manifest/lifecycle/integrity authority; no second manifest is introduced. Each entry records guide key, accepted pose schema, control type, anatomy, path, hash, source/license, aliases for operator discovery, and approval status. A missing, unapproved, integrity-failed, or profile-incompatible key falls back to `edit_only`; extracting the standing card's current skeleton is not treated as the requested action.

6. **Anatomy-appropriate conditioning.** Given an approved humanoid card and compatible guide, the adopted route applies the exact humanoid pose schema accepted by the pinned workflow and rejects incompatible keypoint schemas. Given a non-humanoid card, it never applies a human OpenPose/DWPose skeleton and uses at least one live-proven `depth`, `lineart`, or `scribble` route. If no non-humanoid structural route passes the live benchmark, the story remains incomplete rather than representing reference-only editing as conditioned success.

7. **Identity safety.** Given any pose generation, then the approved reference card remains the identity source. IPAdapter may be retained only as a style anchor. IPAdapter FaceID, InstantID, PuLID, InsightFace identity embedding, and any identity path that requires a detectable real human face are forbidden. Missing reference, failed workflow injection, detector miss, incompatible guide, or backend failure must never fall back to unanchored text-to-image generation.

8. **Story 8.4 behavior preserved.** Given scenario approval, when special poses are provisioned, then the existing first-seen `(card_key, pose_hint)` deduplication, deterministic `hint:*` key, cross-run cache, `special_pose_max_per_run` cap, mock-mode no-op, per-item failure isolation, and base-pose fallback remain. This story does not raise the cap, add a graph stage, alter cast placement/movement fields, or change the `pose_hint` prompt contract.

9. **Fresh cache semantics.** Given a cached hint card, when its manifest provenance fingerprint matches engine, workflow, model/LoRA, quantization, guide, conditioning profile, reference, preprocessor, postprocessor, custom-node/environment snapshot, dimensions, and seed-policy hashes, then generation is skipped. `CharacterService.get_fresh_special_pose_card(card_key, pose_hint, expected_fingerprint)` is the sole lookup and requires an approved DB row, approved matching manifest entry/path, valid integrity hash, and matching fingerprint. Provisioning and every resolver lookup, including resume/retry paths, use it. Legacy text-only hint cards, integrity failures, and mismatches are stale and fall back to the base card until replacement succeeds. Existing `pose_hint_key` and DB uniqueness remain compatible.

10. **Card and persistence invariants.** Given a successful generation, then output is a single-subject, full-body card at configured `character_image_width x character_image_height` (defaults `832x1216`). A shared validator decodes RGBA, requires both nonempty subject alpha and transparent background pixels, rejects full-frame opaque/empty masks, checks subject bounds/gutters without rejecting valid wide/lying poses, and preserves anti-aliased/feather-compatible edges. A replacement renders to a new fingerprinted staging path and validates completely while the previous approved bytes/manifest/DB row remain intact. Promotion updates the manifest and `CharacterCard` with compensating rollback: DB/manifest failure restores the previous entry and deletes only the new staged file. Add the required AssetService replace/restore/remove support and tests. Never overwrite the last good file in place; failures leave no approved orphan or permanently unretryable stub.

11. **Operational degradation.** Given missing models, ComfyUI validation errors, timeout/OOM/ROCm failures, invalid alpha/framing, or provider exceptions, then the issue is logged as a structured, contextual warning and the run continues with the existing base pose. Gate/UI-visible warnings remain owned by Story 13.1 and are not reimplemented here. The system must not auto-approve a broken card or fail the pipeline. Poll timeout is configuration-backed and long enough for measured Qwen cold-start/runtime behavior, with bounded tests.

12. **Configuration, licensing, and reproducibility.** Given all runtime model/workflow choices, then identifiers, paths, timeouts, and guide-registry location are `YTFLOW_` settings and documented in `.env.example`; no machine-specific absolute paths or node IDs are embedded in service code. Every workflow, custom node, model, quantization, LoRA, guide, and preprocessor has recorded commercial-use-compatible licensing and a content hash. Unclear licensing blocks adoption for this monetized channel.

13. **Automated verification.** Given unit/service tests, then they cover workflow non-mutation and required-input validation; explicit profile and guide selection; missing-metadata `edit_only`; humanoid OpenPose and non-humanoid conditioned routes; forbidden FaceID paths; approved-reference/integrity checks; fresh/stale cache behavior; cap/mock/no-hint compatibility; timeout/OOM/provider failure; no unanchored t2i fallback; RGBA rejection; manifest-before-row ordering; and retryability. Existing run-service, resolver, character-generation, and full regression tests remain green.

14. **Live quality and cost evidence.** Given a fixed benchmark, then the developer records the old text+IPAdapter baseline, Qwen reference-only edit, and adopted conditioned path for at least: one STOCK human, masked humanoid SCP-049, another humanoid anomaly, and two non-humanoid archetypes. Evidence includes the reference, guide, deterministic seed, output, identity/action/anatomy/alpha/framing human-review notes, actual asset/manifest/DB records, second-call cache hit, peak VRAM, render time, and recovery from one induced failure. Freeze and report representative production `pose_hint`/`pose_guide_key` outputs and their conditioned-routing coverage; cherry-picked guides alone do not pass. At least one humanoid OpenPose result and one non-humanoid conditioned result must be approved. A representative end-to-end run or a conservative measured render-count calculation proves the full automated run budget remains at or below two hours.

15. **Scope and architecture compatibility.** Given implementation completion, then the graph remains `scenario -> image -> tts -> subtitle -> video`; imports continue to follow `api -> services -> (pipeline | db) -> domain`; no UI, run-state schema, derived-entity generator, placement-diversity repair, or normal standing/multi-angle provider behavior changes. The only planned schema/prompt changes are the character-level `pose_conditioning` field and optional closed `pose_guide_key` cast field required by AC4-5.

## Tasks / Subtasks

- [ ] Task 1 — Run the adoption spike and freeze the operational contract (AC: 1, 2, 6, 12, 14)
  - [ ] Inspect and pin the current VNCCS revision; verify that the selected path does not use FaceID/InsightFace identity embedding.
  - [ ] Run a minimal one-pose VNCCS/Qwen workflow on the target 16 GB ROCm host; measure Q4 first and Q5 only if memory allows.
  - [ ] Prove or reject a non-humanoid depth/lineart/scribble path instead of assuming Qwen-Edit ControlNet compatibility.
  - [ ] Write a decision record with hashes, licenses, VRAM/time evidence, adopted route, and rejected alternatives.
  - [ ] Commit only the minimal API workflow(s), required model manifest/README, and reproducible parameter map.

- [ ] Task 2 — Add explicit morphology metadata and pose-guide registry (AC: 4, 5, 6, 9, 12)
  - [ ] Add the closed `Character.pose_conditioning` field, an idempotent `db.init()` additive column migration, and `scripts/backfill_pose_conditioning.py`; do not introduce a separate Alembic system for one column.
  - [ ] Seed the complete current mapping: `STOCK-d-class`, `STOCK-researcher`, `STOCK-security`, `SCP-049`, `SCP-049-2`, and `SCP-096` -> `openpose`; `SCP-682` -> adopted non-human route; ambiguous `SCP-1471` -> `edit_only` until separately approved. Unknown future characters default to `edit_only`.
  - [ ] Add `pose_guide_key` to the cast contract, state/parser/artifact serialization, and production prompt using the closed approved catalog; preserve free-text `pose_hint`.
  - [ ] Store the smallest approved humanoid/non-humanoid guide set under `assets/pose_guides/` through the existing AssetService manifest and lifecycle.
  - [ ] Resolve only explicit guide keys; verify hash, lifecycle status, anatomy, and control-type/schema compatibility.
  - [ ] Include every AC9 input in the pose-generation fingerprint, using Story 13.3's environment snapshot hash.

- [ ] Task 3 — Implement the narrow PoseService (AC: 2, 3, 5-7, 10-12)
  - [ ] Add `src/yt_flow/services/pose_service.py` with typed request/result/provenance values.
  - [ ] Reuse `comfyui_client.upload_image` and `submit_and_fetch`; support a configurable measured poll timeout.
  - [ ] Deep-copy the workflow; reuse Story 13.3's exact `ytflow:*` node resolver; inject reference, guide, prompt, deterministic seed, dimensions, and model parameters exactly once; fail closed on missing/ambiguous targets.
  - [ ] Implement reference-only, humanoid guide, and adopted non-humanoid guide routing without an unanchored t2i fallback.
  - [ ] Reuse/expose the existing alpha cleanup and subject-scale normalization rather than creating a second sprite postprocessor.

- [ ] Task 4 — Integrate conditioned generation without rewriting Story 8.4 (AC: 7-11, 15)
  - [ ] Replace the ordinary provider call inside `CharacterService.generate_special_pose_card` with PoseService delegation.
  - [ ] Resolve an integrity-verified, approved standing-front reference; do not rely on an unchecked legacy path alone.
  - [ ] Preserve deterministic key/path shape, RGBA validation, manifest-before-DB order, and existing auto-approval precedent for on-demand cards.
  - [ ] Record route, condition image, seed, engine/workflow/model/custom-node/LoRA hashes, settings, and source reference hash in manifest provenance.
  - [ ] Implement and exclusively use `get_fresh_special_pose_card(...)` in provisioning and all hint-card resolver branches.
  - [ ] Render replacements to fingerprinted staging paths and add compensating AssetService promotion/rollback so the last good card survives every failure point.
  - [ ] Leave `run_service` orchestration untouched except for the shared freshness-aware lookup; preserve cap/mock/failure behavior and ordering otherwise.

- [ ] Task 5 — Add configuration and operational documentation (AC: 1, 11, 12)
  - [ ] Add only the adopted workflow/model/guide/timeout settings to `Settings` and `.env.example`.
  - [ ] Document exact ComfyUI/custom-node/model layout, licenses, hashes, ROCm launch requirements, cold-start behavior, and recovery procedure.
  - [ ] Do not add Python dependencies for ComfyUI-side models/nodes and do not raise `special_pose_max_per_run`.

- [ ] Task 6 — Add automated regression coverage (AC: 3-13, 15)
  - [ ] Create isolated PoseService tests with fake uploads/submissions and real small PNG fixtures.
  - [ ] Update CharacterService/fakes at the new seam while retaining success, missing-reference, opaque-output, persistence-order, and retry tests.
  - [ ] Prove fresh cache hit and legacy/mismatched cache regeneration without changing `pose_hint_key`, including all resolver and resume/retry paths.
  - [ ] Prove staged replacement rollback at every file/manifest/DB failure point and shared RGBA/framing validation, including non-default configured dimensions.
  - [ ] Prove no-hint, cap, mock, resolver base fallback, derived-entity provisioning, and normal card generation remain unchanged.
  - [ ] Run targeted tests, the full backend suite, coverage gate, and Ruff.

- [ ] Task 7 — Produce live artifact evidence and operator approval (AC: 1, 6, 10-14)
  - [ ] Run the fixed five-subject benchmark with fixed references, hints, guides, and seeds.
  - [ ] Save contact sheets and a compact result table comparing old baseline, reference-only edit, and conditioned output.
  - [ ] Obtain Jay's approval for at least one humanoid OpenPose and one non-humanoid conditioned result.
  - [ ] Verify file + approved manifest + DB row + provenance hashes + second-call cache hit for each accepted path.
  - [ ] Induce one backend failure and prove warning + base-card fallback + later successful retry.
  - [ ] Record production `pose_guide_key` routing coverage and prove the measured worst-case render count remains inside the two-hour automated budget.

## Dev Notes

### Implementation Spine

Keep the existing flow and substitute only the generator:

`run_service._ensure_special_pose_cards` -> `CharacterService.generate_special_pose_card` -> **new `PoseService.generate`** -> existing file/manifest/DB persistence -> `resolve_cast_cards`

The service boundary is deliberate. `PoseService` understands ComfyUI workflows and conditioning. `CharacterService` continues to own character/card lookup and persistence. `run_service` continues to own post-scenario provisioning, cap, mock handling, and failure isolation.

### Explicit Design Decisions

- **Primary identity engine:** Qwen-Image-Edit-2511, selected by the current Epic 8 architecture. Qwen-Image 2.0 now exists, but upgrading models is outside this story; do not opportunistically substitute it.
- **First workflow candidate:** current VNCCS 3.x one-pose path. Upstream inspection found a 3D/OpenPose guide plus approved-character multi-image Qwen-Edit path and no FaceID/InsightFace identity dependency. Treat that as a spike result to reproduce and pin, not as an excuse to import the whole suite.
- **Q4/Q5:** planning notes called Q4 “~14 GB”; current published GGUF variants vary. Weight size is not peak VRAM. The target host decides through measurement.
- **Control compatibility:** Qwen-Image ControlNet Union supports pose/depth/canny for base Qwen-Image, but that does not prove direct compatibility with Qwen-Image-Edit-2511. VNCCS's pose-image + reference-image Qwen-Edit/LoRA route is the preferred first experiment. Any separate ControlNet route must prove itself live.
- **Morphology authority:** `Character.pose_conditioning` is durable catalog data. Current backfill is explicit; all unknown/ambiguous characters use warned `edit_only` until curated.
- **Guide selection:** `pose_guide_key` is an optional closed cast field backed by approved AssetService entries. Free `pose_hint` remains the action instruction and cache identity input; it is not heuristically mapped to a guide.
- **On-demand lifecycle:** preserve Story 8.4's immediate auto-approval only after technical validation and complete provenance. Redesigning per-card human approval during a run would require a separate workflow/UI decision.
- **Prompt policy:** retain the existing `pose_hint` instructions and add only the closed `pose_guide_key` catalog/selection rule. Seed the repo prompt to production under the active DEV MODE procedure in `docs/PROMPT_POLICY.md`, record the resulting version/label, and do not revive the failed Story 8.4a candidate wholesale.

### Current Files Being Modified

- `src/yt_flow/services/character_service.py`
  - **Current:** `generate_special_pose_card` resolves `Character.angle_front_path`, calls the ordinary character provider with text + front IPAdapter, checks alpha, writes the asset/manifest, auto-approves, and upserts the hint card. `resolve_cast_cards` prefers a cached hint card then falls back to a base pose.
  - **Change:** resolve an approved/integrity-verified canonical reference, delegate conditioned generation to PoseService, persist full fingerprint provenance, and reject stale hint cards.
  - **Preserve:** `pose_hint_key`, front-card output contract, path layout, RGBA guard, manifest-before-DB order, failure-to-`None`, resolver movement metadata, and base fallback.

- `src/yt_flow/services/asset_service.py`
  - **Current:** owns the single reusable-asset manifest, hashes, draft/approved/retired lifecycle, and atomic JSON-file replacement; `add_asset` overwrites a key and has no compensating remove/restore operation.
  - **Change:** support pose-guide entries plus staged card replacement/promotion with manifest snapshot restoration and removal of only new staged bytes on failure.
  - **Preserve:** one manifest authority, integrity semantics, existing asset keys, style epoch, and location-plate behavior.

- `src/yt_flow/db/models.py`, `src/yt_flow/db/__init__.py`, `src/yt_flow/domain/state.py`, `src/yt_flow/pipeline/nodes/scenario_chain.py`, and `prompts/scenario/cast_decision.md`
  - **Current:** `Character` has no morphology field; cast has free `pose_hint` but no structural-guide key.
  - **Change:** add durable `Character.pose_conditioning` and optional closed `pose_guide_key`; validate/serialize the latter without changing any existing placement/motion fields.
  - **Preserve:** safe defaults, tolerant parsing, existing prompt output shape for all old fields, and deterministic placement repair.

- `src/yt_flow/domain/png.py`
  - **Current:** `has_alpha` recognizes PNG alpha color type but allows a fully opaque alpha plane.
  - **Change:** add/reuse one decoded sprite validator that proves transparent background, nonempty subject, configured dimensions, and safe subject bounds.
  - **Preserve:** existing callers of `has_alpha` unless deliberately migrated with regression coverage.

- `src/yt_flow/services/character_image_provider.py`
  - **Current:** owns private `_clean_alpha_noise` and `_normalize_subject_scale`, including anti-aliased edge preservation, largest-component cleanup, bottom gutter, and wide-pose fit.
  - **Change:** expose/reuse these helpers at the PoseService seam if needed.
  - **Preserve:** normal standing/sitting/multi-angle provider protocol and IPAdapter behavior; do not add pose-specific arguments to the generic provider merely for convenience.

- `src/yt_flow/services/run_service.py`
  - **Current:** scans first-seen `(card_key, pose_hint)` pairs, skips existing cards, enforces the cap, skips mock mode, and isolates failures before scenario resume.
  - **Change:** only the minimum call needed to distinguish fresh conditioned hint cards from stale legacy/mismatched cards.
  - **Preserve:** timing, iteration order, cap value, mock behavior, per-item/global exception envelope, and derived-entity provisioning.

- `src/yt_flow/config.py` and `.env.example`
  - **Current:** configure ComfyUI, character workflow/dimensions, and `special_pose_max_per_run=3`.
  - **Change:** add adopted pose workflow/model/guide/timeout settings.
  - **Preserve:** environment prefix, local defaults, and cap value.

- `tests/services/test_character_service_generation.py`, `tests/services/test_run_service_character_provisioning.py`, `tests/services/test_character_angle_selector.py`, `tests/services/test_asset_service.py`, `tests/pipeline/nodes/test_scenario_chain.py`, and `tests/stubs/fakes.py`
  - **Current:** assert special-pose success, missing-front fallback, opaque rejection, cap, cache, mock, and exception isolation through the old image-provider seam.
  - **Change:** patch the PoseService seam and add freshness/provenance/routing coverage.
  - **Preserve:** existing behavioral assertions and no network access in unit tests.

### Expected New Files

- `src/yt_flow/services/pose_service.py`
- `tests/services/test_pose_service.py`
- `scripts/backfill_pose_conditioning.py` and its tests
- `data/workflows/<adopted-minimal-pose-workflow>.json`
- `data/workflows/README.md` additions or a focused pose-workflow README
- `assets/pose_guides/...` entries governed by the existing `assets/manifest.json`
- A live-validation evidence directory under `_bmad-output/implementation-artifacts/8-20-live-validation/`

Do not modify frontend, run-state schema, API routes, graph topology, video composition, or the derived-entity generator unless a failing acceptance test proves it essential. The Character migration and cast/prompt additions above are planned scope, not incidental expansion.

### Architecture Compliance

- AD-1: services may import config/domain/db and other service adapters; no API or pipeline imports.
- AD-2/AD-4: no new in-flight pipeline truth or graph driver; reusable asset metadata stays in the asset manifest/DB library.
- AD-5: shot/camera and existing cast placement/motion metadata remain unchanged; `pose_guide_key` is an additive optional cast field.
- AD-10: local ComfyUI is checked at use time; conditioned-card failure is visible but non-fatal.
- No new LangGraph stage or UI gate. Existing image artifact review/retry remains the operator surface.

### Library and Framework Requirements

- Keep repository Python pins: Python 3.12, LangGraph 1.2.7, FastAPI 0.138.2, SQLModel 0.0.39, Langfuse 4.12.0, pytest 9.1.1, Ruff 0.15.20.
- Reuse `httpx` through the existing `comfyui_client`; do not add another HTTP client.
- ComfyUI-side dependencies are operational artifacts, not `pyproject.toml` dependencies.
- Candidate licenses observed during research: Qwen-Image/Qwen-Image-Edit and Unsloth GGUF Apache-2.0; VNCCS code MIT; VNCCS PoseStudio LoRA MIT; DWPose Apache-2.0; InstantX Qwen-Image ControlNet Union Apache-2.0. Verify the exact downloaded artifacts rather than copying these labels blindly.

### Testing Requirements

- Use pytest/pytest-asyncio and `tmp_path` for DB/assets/workflows/guides.
- Test API-workflow templates are deep-copied and required targets are injected exactly once; missing/ambiguous targets fail closed.
- Use small real RGBA/opaque/wide-pose fixtures for postprocessing and persistence tests.
- Unit tests must never require ComfyUI. Live tests must clearly identify hardware/model prerequisites and must not be reported as passed from mocks.
- Preserve the repository-wide coverage floor (`fail_under=80`) and run Ruff on touched files.

### Previous Story Intelligence

- Story 8.4 established the correct trigger, deterministic `hint:*` cache, cap, mock skip, base fallback, and non-fatal behavior. Reuse them.
- Story 8.4a proved a real `832x1216` SCP-049 RGBA hint card and second-call cache hit, but its `pose_hint` prompt candidate failed the quality gate. Do not treat that candidate as production or reopen prompt work casually.
- Story 8.13 showed that best-effort generation must not leave a stub `Character` that blocks future retries. Preserve rollback/retryability.
- Story 8.15 showed that identity descriptors must be retained, alpha must not be multiplied twice, and output staging/provenance matter. Do not overwrite canonical cards.
- Story 8.17 reinforced that schema/workflow code without real approved files and rows is not done.
- Story 8.18 changed only deterministic placement repair. Do not alter its `position`, `depth`, movement, or scenario-chain semantics.

### Git Intelligence

Recent relevant commits are `6f7238b`, `213a087`, `6837be5`, `868323a`, and `22cde81` (Story 8.15 identity/alpha/staging fixes), `3bd41aa` (Story 11.1 anti-aliased alpha hardening), and `76da474` (Story 8.17 real asset approval). Read these diffs before implementation; they encode regressions this story must not reintroduce.

### Latest Technical Information

- The official [Qwen-Image repository](https://github.com/QwenLM/Qwen-Image) describes Qwen-Image-Edit-2511 character-consistency and image-drift improvements and carries Apache-2.0 licensing.
- The official [ComfyUI Qwen-Image-Edit-2511 workflow](https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511) is the native baseline; it documents current model components but does not prove this project's ROCm memory envelope.
- [ComfyUI_VNCCS](https://github.com/AHEKOT/ComfyUI_VNCCS) is the first integration candidate. Pin the evaluated revision because its workflow and required nodes evolve independently of this repository.
- [VNCCS PoseStudio](https://huggingface.co/MIUProject/VNCCS_PoseStudio) supplies the pose-focused LoRA used by the current candidate path; verify the exact file/license/hash.
- [DWPose](https://github.com/IDEA-Research/DWPose) provides human whole-body pose estimation under Apache-2.0; its human ontology is why it is not the default for creatures.
- [InstantX Qwen-Image ControlNet Union](https://huggingface.co/InstantX/Qwen-Image-ControlNet-Union) supports pose/depth/canny on base Qwen-Image. Treat Edit-2511 compatibility as unproven until live workflow validation.

### Project Context Reference

No repository `project-context.md` file exists. The controlling project sources for this story are:

- `_bmad-output/planning-artifacts/epics.md` — Epic 8 and Story 8.20 rationale/technique correction.
- `_bmad-output/implementation-artifacts/epic-8-context.md` — compiled Epic 8 invariants and cross-story dependencies.
- `_bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md` — current source-set and pose-conditioning research.
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` — layer/state/gate invariants.
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md` — local ComfyUI, five-stage graph, observability, and two-hour NFR.
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md` — retain stage-level image review/retry; no per-card UI in scope.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-820-OpenPose-골격-조건화-액션-포즈-생성`]
- [Source: `_bmad-output/implementation-artifacts/epic-8-context.md#Technical-Decisions`]
- [Source: `_bmad-output/implementation-artifacts/8-4-on-demand-special-pose-cards.md#Dev-Notes`]
- [Source: `_bmad-output/implementation-artifacts/8-4a-special-pose-prompt-gate-decomposition.md#Completion-Notes-List`]
- [Source: `_bmad-output/implementation-artifacts/8-18-cast-decision-diversity-validator.md#Dev-Notes`]
- [Source: `_bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#Area-3--Source-Set-Asset-Strategy-Character-Consistency-Angle-Diversification-Compositing-research-findings`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Invariants--Rules`]
- [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Non-Functional-Requirements`]

## Dev Agent Record

### Agent Model Used

OpenAI Codex (GPT-5)

### Debug Log References

- Story context generated from exhaustive planning, architecture, current-code, previous-story, Git, and current primary-source research on 2026-08-03.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Story statement and acceptance criteria were synthesized because `epics.md` contains a draft rationale rather than a canonical user-story/BDD block.
- Key design ambiguities resolved: durable character-level conditioning profile; explicit closed `pose_guide_key`; one AssetService authority; safe `edit_only` fallback; transaction-safe fingerprinted replacement; one freshness lookup; no anatomy keyword inference; live proof required for non-humanoid conditioning and 16 GB ROCm fit.

### File List

- `_bmad-output/implementation-artifacts/8-20-openpose-conditioned-action-poses.md`

## Change Log

- 2026-08-03: Created implementation-ready Story 8.20 with conditioned-pose adoption gate, deterministic routing and guide contracts, Story 8.4 preservation requirements, cache freshness, live GPU evidence, and disaster-prevention guardrails.
