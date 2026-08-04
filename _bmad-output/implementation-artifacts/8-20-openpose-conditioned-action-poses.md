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

Status: in-progress

> **Not `review`.** Tasks 1-2 are complete and green, but Tasks 3-7 are not started, so
> the definition of done is not met and marking this ready-for-review would be false.
> Two blockers, in order of severity:
> 1. **The adopted technique was rejected by its own live gate** (Task 1). AC6 says the
>    story stays incomplete rather than passing reference-only editing off as
>    conditioned success. A technique re-decision is needed before Tasks 3-7 mean
>    anything — see `8-20-live-validation/DECISION-RECORD.md` §6.
> 2. **Story 13.3 is still `ready-for-dev`**, and AC3/AC9 require its canonical
>    `ytflow:*` resolver and environment snapshot.

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

- [x] Task 1 — Run the adoption spike and freeze the operational contract (AC: 1, 2, 6, 12, 14)
  - [x] Inspect and pin the current VNCCS revision; verify that the selected path does not use FaceID/InsightFace identity embedding.
  - [x] Run a minimal one-pose VNCCS/Qwen workflow on the target 16 GB ROCm host; measure Q4 first and Q5 only if memory allows.
  - [x] Prove or reject a non-humanoid depth/lineart/scribble path instead of assuming Qwen-Edit ControlNet compatibility.
  - [x] Write a decision record with hashes, licenses, VRAM/time evidence, adopted route, and rejected alternatives.
  - [x] Commit only the minimal API workflow(s), required model manifest/README, and reproducible parameter map.

- [x] Task 2 — Add explicit morphology metadata and pose-guide registry (AC: 4, 5, 6, 9, 12)
  - [x] Add the closed `Character.pose_conditioning` field, an idempotent `db.init()` additive column migration, and `scripts/backfill_pose_conditioning.py`; do not introduce a separate Alembic system for one column.
  - [x] Seed the complete current mapping: `STOCK-d-class`, `STOCK-researcher`, `STOCK-security`, `SCP-049`, `SCP-049-2`, and `SCP-096` -> `openpose`; `SCP-682` -> adopted non-human route; ambiguous `SCP-1471` -> `edit_only` until separately approved. Unknown future characters default to `edit_only`.
  - [x] Add `pose_guide_key` to the cast contract, state/parser/artifact serialization, and production prompt using the closed approved catalog; preserve free-text `pose_hint`.
  - [x] Store the smallest approved humanoid/non-humanoid guide set under `assets/pose_guides/` through the existing AssetService manifest and lifecycle.
  - [x] Resolve only explicit guide keys; verify hash, lifecycle status, anatomy, and control-type/schema compatibility.
  - [~] Include every AC9 input in the pose-generation fingerprint, using Story 13.3's environment snapshot hash. — **PARTIAL:** `domain.pose.pose_fingerprint()` implements the complete AC9 field set and *requires* `env_snapshot_sha256`, but Story 13.3 does not exist so nothing can supply that value yet. No production caller (that is Task 3/4).

> **Tasks 3-7 are NOT STARTED and deliberately so.** Two independent reasons, both
> recorded before any of it was attempted:
> 1. This story's own Context says "Story 13.3 must be complete ... If it is not
>    complete, stop after the technology spike; do not create a second resolver."
>    13.3 is still `ready-for-dev` and no `ytflow:*` resolver exists in `src/`.
>    Jay's scope decision on 2026-08-04 was explicitly **Task 1 + Task 2, then stop**.
> 2. Task 1's measurements then **rejected the candidate route outright** (see
>    `8-20-live-validation/DECISION-RECORD.md`). Building Tasks 3-7 against a route
>    that does not condition geometry and does not fit 16 GB would be building the
>    wrong thing. AC6 explicitly says the story stays incomplete in this case rather
>    than reporting reference-only editing as conditioned success.

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

OpenAI Codex (GPT-5) — story context authoring, 2026-08-03
Claude Opus 5 (1M context) — Task 1 + Task 2 implementation, 2026-08-04

### Debug Log References

- Story context generated from exhaustive planning, architecture, current-code, previous-story, Git, and current primary-source research on 2026-08-03.
- 2026-08-04 dev attempt 2 (attempt 1's tmux session was lost mid-download on 2026-08-03).
  Live spike log: `8-20-live-validation/measurements.jsonl`.
  Decision record: `8-20-live-validation/DECISION-RECORD.md`.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.

#### 2026-08-04 — Task 1 + Task 2 delivered; route REJECTED; Tasks 3-7 not started

**Scope.** Jay chose "Task 1 + Task 2, then stop" when told 13.3 was incomplete and
that the story itself mandates stopping after the spike. Tasks 3-7 untouched.

**Task 1 verdict: ⛔ NO ADOPTION.** The candidate route (native Qwen-Image-Edit-2511
with the structural guide passed as `image2` of `TextEncodeQwenImageEditPlus`) runs on
the target host but fails two independent hard gates. Full evidence, hashes, licences
and per-run numbers in the decision record. Headlines:

- 🔴 **The guide does not condition geometry — it injects content.** `image2` is a
  *reference* image, so Qwen-Edit composites it as subject matter. A COCO-18 skeleton
  guide produced a literal articulated skeleton lying in frame
  (`049_openpose_kneel.png`); a creature silhouette guide produced a literal white
  bear-like animal overlaying SCP-682 (`682_scribble_lunge.png`). Identical failure for
  both schemas, so it is the mechanism, not the guide art.
- 🔴 **The pose effect is fully confounded.** The no-guide `edit_only` baseline
  (`049_editonly.png`) already produced the requested action from text alone. There is
  therefore **no evidence** the guide contributes structure. Per AC6 this may not be
  reported as conditioned success.
- 🔴 **Does not fit 16 GB.** 2 of 5 runs died of CUDA OOM; peak VRAM 15.20-16.18 GB
  against 15.92 GB usable. The OOM is at `InspyrenetRembg`, *after* sampling succeeds:
  the 13.24 GB GGUF stays resident (11.85 GiB allocated) and the cutout then asks for
  4.50 GiB. The node exposes only `torchscript_jit` — no device/resolution knob — so
  AC2's "cutout inside the workflow" is unsatisfiable at this model size. Q5 excluded
  outright (Q4 already at the ceiling).
- 🔴 **Budget not demonstrated (AC14).** 97-345 s warm per card, 1115.8 s cold start,
  with a 40% retry rate. No conservative calculation closes the 2-hour whole-run NFR.
- ✅ **Identity preservation is excellent** and vindicates the story's core technique
  correction: SCP-049's plague-doctor mask, hood, coat and boots survived, as did
  SCP-682's reptile body — precisely where FaceID/InstantID/PuLID/InsightFace fail.
- ✅ VNCCS rejection re-verified first-hand at pinned rev `1bb732eb` (MIT): all 5
  workflows are 1-5 node shells over monolithic nodes, ~28.9k LOC builds graphs in
  Python via `nodes.common_ksampler`, `requirements.txt` pins `llama-cpp-python`, and
  models auto-download via `huggingface_hub` — AC2 forbids all of it. Its Qwen use is a
  VL *captioner*. Grep for `faceid|insightface|instantid|pulid|antelopev2|buffalo_l`
  returns 0 hits, so AC7's ban premise holds.
- ⛔ **VNCCS's poseset is unusable as a guide source** — rendered and inspected all 12
  poses: every one is a standing character-sheet A-pose variant. Using one would
  restate the pose the approved card already has, which AC5 forbids. Only its
  limb-length *ratios* were reused for the Task 2 authored guides.

**Corrections to inherited claims** (attempt 1's notes, which were pre-measurement):
- "AC6 got SIMPLER than the story assumed ... ONE path, different guide raster ... which
  dissolves the Edit-2511 × ControlNet Union compatibility risk" — **disproven**. The
  ControlNet question is the only remaining structural candidate, and Q4_K_M already
  peaks at the ceiling *without* a ControlNet loaded, so it likely will not fit either.
  `data/workflows/README-qwen-pose-edit.md` has been corrected in place rather than
  left asserting it.
- The non-humanoid base-card defect was **confirmed independently**:
  `SCP-682/standing_front` and `SCP-1471/standing_front` are `status=approved` but are
  1664×928 **opaque RGB, no alpha**; the 6 humanoid cards are correct 832×1216 RGBA.
  Because the workflow takes its latent from `VAEEncode` of the reference, output
  resolution equals reference resolution — which is exactly why the non-humanoid run
  emitted 1664×928 and violated AC10. Regenerating those base cards is outside Task
  1/2 and needs its own story.

**Task 2 delivered (all subtasks except the fingerprint's 13.3 dependency).**
- `Character.pose_conditioning` (closed vocabulary) + idempotent additive migration in
  `db.init()` following the existing `_ensure_card_columns` precedent. Proven against a
  genuine hand-built pre-8.20 table, not just a fresh DB.
- `scripts/backfill_pose_conditioning.py` applied to the live dev DB: 7 changed, 1
  unchanged, re-run reports `changed=0`. Migration deliberately backfills everyone to
  safe `edit_only`; the curated anatomy mapping is the script's job because AC4 forbids
  inferring anatomy from card keys.
- `pose_guide_key` added to `CastMember`, `parse_cast`, and the production prompt as a
  closed catalog. Two rules beyond the other cast fields: a guide with no `pose_hint`
  is dropped (nothing to constrain), and an out-of-catalog key warns.
- 6 guides authored, rendered, registered and approved through the **existing**
  AssetService manifest (namespaced `pose_guide/*`, no second registry): 4 humanoid
  COCO-18 + 2 creature silhouette. Guide set is demand-driven from real production
  data — 2075 checkpoints scanned yielded 8 distinct `pose_hint` values ("lying on
  floor" 24, "reaching toward camera" 24, "collapsed"/"extending hand"/"head
  bowed"/"shaking head"/"looking at camera"/"kneeling over a corpse" 12 each). The
  three head/gaze-only hints intentionally get **no** guide.
- Poses are authored as joint **angles** resolved by forward kinematics from one
  limb-length table, so limb lengths are correct by construction; a hand-typed (x, y)
  table can silently grow a 400px femur. Guide PNGs are gitignored per repo policy
  (manifest is the audit trail) but are deterministic, so their sha256 values are
  pinned in `tests/test_render_pose_guides.py` — that is what holds the content in git.
- `domain/pose.py` also carries the complete AC9 fingerprint field set. It *requires*
  `env_snapshot_sha256` so Story 13.3's wiring cannot be silently forgotten; it has no
  production caller yet (Task 3/4).

**Measured trap worth carrying forward:** InSPyReNet saturates subject alpha at **254,
not 255** (only 2.07% of the frame is exactly 255). An AC10 validator requiring
`alpha == 255` for subject pixels would reject every card this workflow produces.

**Tests:** 110 new tests. Full suite **1936 passed, 1 skipped, 0 failed** (clean-tree
control: 1826 passed). Ruff clean on all touched files. One transient
`test_e2e_stub_run.py` failure was investigated rather than assumed: it is the
documented timing-sensitive `_drain_bg_tasks` 10 s timeout — it passes on both a clean
tree and this tree in the same full-suite context, and is unrelated to this story.
- Story statement and acceptance criteria were synthesized because `epics.md` contains a draft rationale rather than a canonical user-story/BDD block.
- Key design ambiguities resolved: durable character-level conditioning profile; explicit closed `pose_guide_key`; one AssetService authority; safe `edit_only` fallback; transaction-safe fingerprinted replacement; one freshness lookup; no anatomy keyword inference; live proof required for non-humanoid conditioning and 16 GB ROCm fit.

### File List

**New — source**
- `src/yt_flow/domain/pose.py`

**New — scripts**
- `scripts/render_pose_guides.py`
- `scripts/backfill_pose_conditioning.py`

**New — tests**
- `tests/domain/test_pose.py`
- `tests/test_render_pose_guides.py`
- `tests/test_backfill_pose_conditioning.py`

**New — workflow + evidence (Task 1 spike; workflow is a rejected-route artifact)**
- `data/workflows/comfyui_qwen_pose_edit_api.json`
- `data/workflows/README-qwen-pose-edit.md`
- `_bmad-output/implementation-artifacts/8-20-live-validation/DECISION-RECORD.md`
- `_bmad-output/implementation-artifacts/8-20-live-validation/measurements.jsonl`
- `_bmad-output/implementation-artifacts/8-20-live-validation/049_editonly.png`
- `_bmad-output/implementation-artifacts/8-20-live-validation/049_openpose_kneel.png`
- `_bmad-output/implementation-artifacts/8-20-live-validation/682_scribble_lunge.png`
- `_bmad-output/implementation-artifacts/8-20-live-validation/pose-guides-contact.png`

**Modified**
- `src/yt_flow/db/models.py` — `Character.pose_conditioning`
- `src/yt_flow/db/__init__.py` — `_ensure_character_columns()` additive migration
- `src/yt_flow/domain/state.py` — `CastMember.pose_guide_key`
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `_parse_pose_guide_key()` + wiring
- `src/yt_flow/services/asset_service.py` — pose-guide registry/resolution + `pose_guides` subdir
- `prompts/scenario/cast_decision.md` — closed `pose_guide_key` catalog rule
- `tests/domain/test_state_imports.py` — declared `CastMember` keys
- `tests/services/test_asset_service.py` — pose-guide coverage
- `tests/pipeline/nodes/test_scenario_chain.py` — `pose_guide_key` parser coverage
- `_bmad-output/implementation-artifacts/8-20-openpose-conditioned-action-poses.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

**Generated, gitignored (repo policy: `assets/*` binaries out, manifest is the audit trail)**
- `assets/pose_guides/{humanoid_reaching_forward,humanoid_lying_supine,humanoid_kneeling,humanoid_collapsed,creature_prone_lunge,creature_rearing}.png`
  — reproduce byte-identically with `uv run python scripts/render_pose_guides.py`
- `assets/manifest.json` — 6 approved `pose_guide/*` entries (also gitignored)

## Change Log

- 2026-08-03: Created implementation-ready Story 8.20 with conditioned-pose adoption gate, deterministic routing and guide contracts, Story 8.4 preservation requirements, cache freshness, live GPU evidence, and disaster-prevention guardrails.
- 2026-08-04: Task 1 adoption spike completed with live measurement on the RX 9060 XT — **route REJECTED** (guide injects content instead of conditioning geometry; 2/5 runs CUDA OOM at 15.20-16.18 GB against 15.92 GB usable). VNCCS rejection re-verified first-hand; its poseset rejected as standing-only. Task 2 delivered: `Character.pose_conditioning` + idempotent migration + applied curated backfill, closed `pose_guide_key` cast field through state/parser/prompt, 6 authored pose guides registered and approved via the existing AssetService manifest, and the complete AC9 fingerprint contract. Corrected `README-qwen-pose-edit.md`'s pre-measurement claims in place. Tasks 3-7 deliberately not started (13.3 blocker + Jay's scope decision + the route rejection). 110 new tests; suite 1936 passed / 1 skipped; Ruff clean.
