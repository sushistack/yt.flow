# Epic 8 Context: Image Composition Architecture — Background + Character Card Compositing

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Replace the old "generate a frame containing the entity → segment a cutout → inpaint the background" image approach with a layered one: backgrounds come from background-only descriptions (or a reusable stock plate library), and characters are composited as reusable transparent RGBA cards driven by per-shot cast metadata, with character-free shots rendering background only. This structurally eliminates the defect family seen in the baseline E2E run — angle-label mismatch, inpaint scars, environment shots wrongly cut, alpha-less full-frame cards covering every shot — and turns characters and locations into a persistent, human-curated asset library that gives cross-episode visual consistency (channel identity) at sharply lower per-run generation cost. Later stories harden the composite itself (grounding, relighting, pose and placement variety) so the frame reads as one image rather than a collage of stickers.

## Stories

- Story 8.1: Per-shot cast metadata + background-only prompts
- Story 8.2: Character card sprite pipeline + stock cast seeding
- Story 8.3: Background-only generation + multi-card compositing
- Story 8.4 / 8.4a: On-demand special-pose cards (+ prompt-gate decomposition)
- Story 8.5: Stock location plates — pre-built reusable background sets
- Story 8.6: Asset library management — registry, provenance, versioning
- Story 8.7: Composite harmonization ladder (collage-look mitigation)
- Story 8.8: Character micro-motion technique enums
- Story 8.9: Character locomotion / blocking enums
- Story 8.10: cast_decision split into its own LLM call
- Story 8.11: Per-shot cut assembly in video assembly
- Story 8.12: cast placement/scale calibration (prompt-only)
- Story 8.13: Derived-entity card on-demand generation
- Story 8.15: STOCK character face-mask bias fix (remaining)
- Story 8.16: Depth-aware placement + IC-Light relighting (remaining)
- Story 8.17: Location plate real-data generation + AI auto-labeling (remaining)
- Story 8.18: Deterministic cast placement-diversity validator
- Story 8.19: Asset-reuse matching — stdlib/LLM first, embeddings last resort (remaining)
- Story 8.20: Skeleton/reference-conditioned action pose generation (remaining)

## Requirements & Constraints

- **Quality over speed, within envelope**: a full run must still finish inside the 2-hour automated budget (human approval excluded). Image generation dominates it, so anything adding per-shot generation must justify itself or be cached.
- **Local-only, single operator**: no auth, SQLite flat file, ComfyUI over local HTTP, model identifiers in config rather than code.
- **No new pipeline stages**: the graph stays scenario → image → tts → subtitle → video. Work here extends existing nodes/services or adds offline scripts.
- **Monetized channel → licensing matters**: commercially usable weights only. Illumination-harmonization tooling must stay on the permissive v1 (SD1.5) line; the Flux-based v2 is non-commercial and must not be adopted.
- **Runtime generation stays on local ComfyUI** regardless of look-dev outcomes (cost, content-filter tolerance, seed reproducibility). Frontier models are for one-off manual look-dev or style anchors only, with the decision recorded.
- **Human curation gate on library assets**: assets move draft → approved → retired and only approved assets are consumable. Automated scoring may auto-approve clear passes, but ambiguous items go to a human queue instead of shipping silently.
- **Explicit regression protection**: compositing changes must demonstrably not reintroduce the baseline defects (angle mismatch, inpaint scars, environment mis-cut, alpha-less full-frame cards).
- **Prompt changes follow the prompt policy** (repo file authoritative; candidate → gate → promote). The A/B promotion gate is currently frozen and AI sessions are hard-blocked from running the evaluator, so promotion needs the operator.
- **Verify artifacts exist, not just code paths**: shipping schema + service + seed script that produces zero rows/files is not done — prove the fast path fires.

## Technical Decisions

- **Layer discipline and state authority**: imports flow `api → services → (pipeline | db) → domain`; pipeline nodes are pure functions of state with no DB or queue side effects, and only the services layer drives the graph and DB/event fan-out. In-flight data lives in LangGraph state (runs table is a read projection; artifact paths live in state, no artifacts table). Library assets are the exception — catalogued in DB keyed by asset identity, never by run, and no run cleanup may delete them.
- **Shot is the image unit**; shots map to one or more narration sentences, so per-shot cut timing is derivable from existing state (sentence mapping + word timings). Camera fields must be populated by the scenario chain and consumed defensively downstream.
- **Three-layer asset architecture**: a *canonical* layer created once and human-gated (per character: hero image + structured angle/expression sheet; per location: hero plate + depth map + prompt metadata), a *trained/derived* layer, and an *on-demand cached* layer. Angle and pose diversity is a **library-time** concern — derive, curate, reuse — not per-shot ephemeral generation.
- **Identity mechanism**: instruction-edit derivation from an approved reference card (Qwen-Image-Edit-2511 class, GGUF quant for 16GB ROCm), optionally plus a per-character LoRA for high-volume shots. Face-embedding adapters (PuLID/InstantID/IPAdapter FaceID) are **excluded on principle** — they assume real humanoid faces and fail outright on masked, illustrated, or non-humanoid entities. IPAdapter is a style anchor only; it drifts across many shots.
- **Pose control**: skeleton conditioning for humanoids, depth/lineart/scribble conditioning for non-humanoid creatures.
- **Compositing order** (cheapest first, stop when good enough): cutout → depth-informed place/scale with occlusion → background-conditioned relight → masked low-denoise fuse pass (two light passes beat one heavy) → comp finish (edge feather, light wrap, black/white-point match) → grade and grain **last, over the unified frame**. Contact/generated shadow is the strongest grounding cue. Generative insertion that re-renders the subject is rejected as primary (identity drift).
- **Finite combinations get precomputed**: stock card × stock plate relights are a bounded set — compute once into the library for zero runtime cost. Location mood/time variants are cache entries keyed by (plate, mood), not extra plates.
- **Style unity via shared anchors**: the same curated anchors drive card and plate generation; a style-epoch integer versions anchor sets and old epochs are preserved so past episodes are never retroactively changed.
- **LLM output is constrained, then repaired deterministically**: taxonomy fields are closed enums, and distribution/consistency violations are fixed by pure repair functions rather than re-prompting. Repair logic stays inline in the scenario chain — no service extraction for a single implementation.
- **New complexity is isolated behind a narrow service** (compositing: cards + background + metadata → corrected composite; pose: conditioned generation) rather than interleaved into video assembly's ffmpeg construction.
- **Degradation must be visible**: existing failure paths silently produce a lesser video (cast resolution failure → background only, plate miss → regenerate). Surface these as warnings; a card without valid alpha is an explicit error, never a silent full-frame overlay.
- **Automated visual QA over eyeballing**: prefer measurable composite-quality scoring as a gate, calibrated first on a small known-good/known-bad set, since such scorers are trained on photoreal material and may not transfer to stylized cards.
- **Cost guardrails on on-demand generation**: per-run caps, deterministic cache keys for cross-run reuse, skip in mock mode. Failure falls back to a base asset and never fails the run, and must not leave a permanently-unretriable stub record.

## UX & Interaction Patterns

- Curation and approval of library assets happen **outside** the per-run gate flow, via offline scripts/CLI, with only flagged items reaching the operator ("I only do final inspection"). Run gates remain per-stage, not per-image.
- Existing asset-browsing UI and the run artifact panel are consumers of the library path; migrating storage locations must keep those consumers on a single unified path.

## Cross-Story Dependencies

- Foundation order was 8.1 → 8.2 → 8.3 → 8.4, with the asset-library management story a hard prerequisite for the location-plate story.
- Per-shot cut assembly is a prerequisite for perceiving locomotion and placement calibration (with one cut per scene, movement is invisible).
- Card alpha-edge softening is owned by the motion/param-hardening epic and must land **before** the depth-aware placement + relight story, so the fuse-pass effect can be measured cleanly.
- The location-plate data-generation story unblocks the background fast path that later parallax/motion work depends on, and its depth maps are shared with that work.
- The derived-entity and special-pose card stories share one on-demand provisioning trigger point (post-scenario-approval, capped) and reuse the character service's card generation; the pose-conditioning story replaces only the generation call, keeping that trigger infrastructure.
- Prompt-only stories in this epic depend on the frozen A/B promotion gate being resolved by the operator, or on an explicit instruction to skip the gate.
