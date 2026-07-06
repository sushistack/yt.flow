---
created: 2026-07-06
baseline_commit: 0267f0b
story_key: 8-2-character-card-sprite-pipeline
story_id: "8.2"
epic: 8
previous_story: 8-1-shot-cast-metadata-bg-prompts
depends_on:
  - 5-10-entity-reference-pipeline-repair   # the IPAdapter multi-angle workflow this story hardens
blocks:
  - 8-3-bg-only-generation-multicard-compositing   # consumes the RGBA card artifact contract
  - 8-4-on-demand-special-pose-cards               # reuses the pose-keyed card table + descriptor generation path
related:
  - 8-1-shot-cast-metadata-bg-prompts       # parallel-safe; shares only the card_key + pose vocabulary
  - 5-6-character-cutout-quality            # InSPyReNet precedent (now applied on clean studio bg)
---

# Story 8.2: Character Card Sprite Pipeline + Stock Cast Seeding

Status: ready-for-dev

## Story

As Jay,
I want character angle cards produced as standardized transparent RGBA sprites (generated on a plain studio background, then cut out), with real per-angle view adherence and a pose axis (base library: standing for every card_key, plus sitting for the run entity), plus the fixed SCP-universe stock cast (D-class, researcher, security) and derived entities (e.g. SCP-049-2) pre-generated and cached under reserved `STOCK-*` / `<scp_id>-<n>` keys,
so that video-time compositing (8.3) has clean, correctly-framed, genuinely-multi-angle card assets — fixing the two contract mismatches behind D13 (no alpha, full-scene framing) and the angle-label mismatch D5, with cross-episode visual consistency as a channel-identity side effect.

## Context

**Context: E2E baseline 2026-07-06 (run 272b05a4, SCP-049)** — report: `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md`. This story is the card-production third of Epic 8. It owns the **card artifact contract** consumed by 8.3 and fixes the defects that live inside card generation itself:

- **D13 (critical) — root cause, both halves owned here**: 5-10's angle cards are **RGB no-alpha 1664×928 full-frame illustrations**, while video_node's compositing path assumes a transparent RGBA sprite (`video.py:304` comment on `scale`/alpha, `_character_scale_filter` docstring `video.py:339-351`). When 1.13's angle selection overrode `character_path` on every shot, the opaque full-frame card covered the whole screen for the entire video ("4분 내내 같은 그림"). The contract mismatches are (1) no alpha channel, (2) full-scene framing instead of a subject sprite. This story fixes the *asset*; 8.3 fixes the *gating* and adds explicit alpha validation.
- **D5 (moderate)**: "side" and "back" cards came out near-frontal — the IPAdapter front-view reference (weight 0.65, workflow node 23) dominates the angle prompt text. Angle diversity is therefore fake, and 1.13's label-based selection picks between four almost-identical images.
- **Jay 추가 결정**: fixed SCP-universe cast (D-class personnel, researchers/doctors, security guards) pre-generated and cached as reusable cards under reserved keys — `CharacterModel` already keys by `scp_id` with 4 angle-path fields, so `STOCK-*` rows need **zero schema change for the standing pose**. Derived entities (SCP-049-2) get cards through the same mechanism.
- **Jay 결정 2026-07-06 (pose dimension)**: the epic's "포즈 배리에이션 검토" is now confirmed as the industry-standard tiered model — a pre-generated sprite library of base poses (angles × {standing, sitting}) plus on-demand special poses as per-scene key art (Story 8.4). This story owns the pose-extensible **card storage design** (Interfaces #4) and the base-pose library; 8.1 owns the `pose` field on `CastMember`; 8.3 resolves `(pose, angle)`; 8.4 owns the on-demand tier.

Key insight from the epic: cutting a character out of a **plain studio background** is the easy case for InSPyReNet — the 5-6/5-7 segmentation pain came from cutting out of *busy generated scenes*. Segmentation isn't abandoned; it moves to where it's reliable.

## Interfaces (Epic 8 contract)

`CastMember` / `card_key` vocabulary is defined normatively in `8-1-shot-cast-metadata-bg-prompts.md#Interfaces` — this story uses it identically and does not redefine it:

- `card_key` == `CharacterModel.scp_id`, exactly: SCP entity `"SCP-049"`, stock cast `"STOCK-d-class" | "STOCK-researcher" | "STOCK-security"` (canonical list: `STOCK_CAST_KEYS` in `src/yt_flow/domain/state.py`, added by 8.1), derived `"<scp_id>-<n>"` e.g. `"SCP-049-2"`.
- `position`/`depth` placement metadata is produced by 8.1 and consumed by 8.3 — this story never touches it.
- `pose` vocabulary (`CastPose = "standing" | "sitting"`) is defined normatively in 8.1's Interfaces; this story produces the card library entries those values resolve to.

**Card artifact contract (this story Produces; 8.3 Consumes):**

1. **Format**: RGBA PNG sprite — PNG `color_type` 6 (RGBA) or 4 (gray+alpha); subject fully cut out on a fully transparent background (no matte, no studio backdrop remnants).
2. **Framing**: full body, centered, feet included, subject occupying ~60–90% of canvas height; framing consistent across all 4 angles of a card and across cards (bust-only is NOT acceptable for v1 — 8.3's depth-scale math assumes comparable subject extents). Sitting cards frame the full *seated* body under the same height rule (a plain minimal chair/stool may appear inside the sprite; no other props).
3. **Canvas**: portrait `832×1216` (SDXL-native bucket; replaces the landscape `1664×928` default that encouraged full-scene illustration framing — part of the D13 fix). Same canvas for all poses.
4. **Storage (pose-aware — normative; 8.3 and 8.4 reference this, they do not redefine it)**: the card library is keyed `(card_key, pose, angle)`.
   - **Standing** cards live exactly where they do today: `CharacterModel.angle_{front,back,side,three_quarter}_path` (`db/models.py:34-37`), files under `workspace/{card_key}/characters/{angle}_candidate_1.png` — the fixed columns ARE the standing-pose fast path, not legacy; **no column migration**, reserved keys ride the existing unique `scp_id` index (`db/models.py:27`), and every existing consumer (5-8 provisioning, 1.12/3.7 candidate UI, angle selection) keeps working untouched.
   - **Every non-standing card** lives in a new table `CharacterCard` (`__tablename__ = "character_cards"`, `db/models.py`): `id (uuid pk), scp_id (indexed), pose (str), angle (str), image_path (str), created_at` with a `UniqueConstraint(scp_id, pose, angle)`; files under `workspace/{card_key}/characters/{pose}_{angle}.png`. `pose` holds `"sitting"` for this story's base library and Story 8.4's deterministic `"hint:<sha256[:10]>"` keys for on-demand special poses — the keying never changes again when new poses appear. The table is created by the existing `SQLModel.metadata.create_all` bootstrap (this project has no migration infra; a new table is additive and safe, unlike altering `characters`).
   - **Decision record — rejected alternatives**: (a) a `pose` column on `character_candidates` — that table is the Story 1.12/3.7 candidate-*selection* lifecycle (status machine, `candidate_num`, UI listing); every existing query would need a pose filter and sitting/special cards would leak into the candidates UI; (b) pose-suffixed path columns on `characters` (`angle_front_sitting_path`, …) — 4 new columns per pose and structurally incapable of holding 8.4's open-ended hint keys, forcing a re-keying later. A 6-field row table is the least-invasive design that never needs re-keying.
5. **Angle truthfulness (D5)**: the image stored under `angle_side_path` must actually be a profile view, `angle_back_path` a from-behind view — verified live per AC5. Applies equally to sitting cards (a sitting "side" card is a seated profile).
6. **Validation seam**: `has_alpha(png_bytes)` moves from `image.py:109-117` to a new stdlib-pure `src/yt_flow/domain/png.py` (this story owns the move); 8.2 uses it to reject opaque generation output at save time, 8.3 reuses it at composition time. Rationale: after 8.3 deletes the layered image path, `image.py` no longer needs it, and both `services/` (8.2) and `pipeline/nodes/video.py` (8.3) need a home importable without layer noise (AD-1: everyone → domain).

## Acceptance Criteria

1. **Sprite workflow.** Given `data/workflows/comfyui_character_multi_angle_api.json`, then it is extended (following 5-10's authoring precedent: derive from the validated baseline, don't reinvent) so the generation output passes through an `InspyrenetRembg` node before its single `SaveImage` — i.e. insert `InspyrenetRembg` between `VAEDecode` (node 8) and `SaveImage` (node 9), mirroring the layered workflow's proven node-12 usage in `comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` — and the workflow's positive-prompt path directs generation onto a **plain/studio background** so the cutout is trivial and clean.
2. **Prompt = sprite intent.** Given `prompts/character/generation.md` (and the same-named Langfuse prompt, seeded via `scripts/seed_character_prompts.py`) plus the built-in fallback in `CharacterService._compile_generation_prompt` (`character_service.py:624-664`), then all three prompt sources demand: full body, feet visible, centered, single subject, **plain flat light-gray studio background**, no scenery/props/environment; and `_ANGLE_DESCRIPTIONS` (`character_service.py:51-57`) is strengthened with model-native view tags the AnimagineXL checkpoint respects (e.g. side → "side profile view, from side, facing left, full body"; back → "from behind, back view, facing away, full body"). Character-prompt changes follow `docs/PROMPT_POLICY.md` rule 4's substitute check (character prompts aren't covered by the scenario golden set — do a direct candidate-vs-production compile comparison on identical inputs).
3. **D5 — per-angle IPAdapter weight.** Given `ComfyUICharacterProvider` (`character_image_provider.py`), then `generate()` accepts and injects a per-call IPAdapter weight (new `_inject_ipadapter_weight`, same pattern as `_inject_seed` at lines 160-168, targeting the `IPAdapterAdvanced`/`IPAdapter` node's `inputs.weight` — currently hard-coded 0.65 in workflow node 23), and `generate_candidates_from_reference` (`character_service.py:542-610`) passes an angle-keyed weight from a module-level table (starting values, tune live: front 0.65, three_quarter 0.55, side 0.4, back 0.3 — the reference is a frontal photo, so identity conditioning must yield to the pose prompt as the pose diverges from frontal).
4. **RGBA enforced at save.** Given a generated candidate, when `generate_candidates_from_reference` writes bytes, then it validates them with `domain.png.has_alpha` and treats an opaque result as that angle's generation failure (existing per-angle failure handling at `character_service.py:600-606` — log + continue, don't crash the batch). The `has_alpha` move itself (Interfaces #6) keeps `image.py` working untouched (it imports the relocated function until 8.3 deletes its call sites).
5. **D5 verified live.** Given a real reference (SCP-049 wiki image already at `workspace/SCP-049/references/ref_1.png`), when the 4 angles are generated against real ComfyUI, then a human-inspectable evidence note records that side is an actual profile and back an actual from-behind view (the baseline's D5 failure mode), all 4 outputs are RGBA sprites meeting the framing contract, and no `prompt_outputs_failed_validation` occurs (5-10 AC8 procedure).
6. **Stock cast seeding.** Given a new script `scripts/seed_stock_cast.py` (house style: `scripts/seed_character_prompts.py`), when run, then for each key in `STOCK_CAST_KEYS` it: creates the `CharacterModel` row if absent (reusing `CharacterService.create_character` — reserved keys pass `_validate_create`); sets a curated built-in `visual_descriptor` (D-class: gaunt build, orange jumpsuit with stenciled number; researcher: white lab coat over shirt and tie, ID badge; security: black tactical gear, Foundation insignia — anchored in the visual vocabulary already in `prompts/scenario/visual_breakdown.md:180-201`); generates 4 RGBA angle cards (**standing pose only — v1 seeding scope, AC13**); persists paths via `update_character` (allowlisted fields, `character_service.py:61-65`). Idempotent: a row with all 4 angle paths already set is skipped unless `--force`. A `--pose sitting` flag exists to widen a key's library later without new code (writes `character_cards` rows per Interfaces #4).
7. **Stock/derived reference sourcing.** Given that wiki-fetch is SCP-page-specific (`ScpWikiImageFetch` derives URLs from scp numbers — useless for `STOCK-*`) and DDG search is an unreliable 403-prone fallback, then stock and derived cards are generated **without an external reference image**: front angle first via the provider's t2i path (descriptor-driven; the existing `_remove_i2i_input` IPAdapter bypass, `character_image_provider.py:183-232`, invoked deliberately rather than only as error fallback), then the remaining 3 angles i2i **using the just-generated front card as the IPAdapter reference** (self-referencing for cross-angle identity consistency). Expose this as a service method (e.g. `CharacterService.generate_cards_from_descriptor(card_key, pose="standing")`) so the seed script, the sitting library (AC12), Story 8.4's on-demand provisioning, and future derived-entity provisioning all share one code path.
8. **Derived entities.** Given a derived key (e.g. `SCP-049-2`) and a descriptor, when `scripts/seed_stock_cast.py --key SCP-049-2 --descriptor "..."` (or the AC7 service method) runs, then a card set is produced under that key exactly like stock cast — same storage contract, no schema change. (Auto-provisioning derived cards mid-run is explicitly out of scope — see Saved Questions.)
9. **Existing SCP-049 cards regenerated.** Given the baseline's non-compliant SCP-049 cards (RGB full-frame), when this story completes, then SCP-049's 4 standing angle paths point at new contract-compliant RGBA sprites (regenerate via the 5-8/5-10 path with the new workflow/weights — the dev-DB row exists, so clear angle paths or regenerate in place) **and** its 4 sitting cards exist as `character_cards` rows (AC13's entity scope), because 8.3's DoD (SCP-049 re-render A/B) needs both.
10. **5-8 auto-provisioning still works.** Given `run_service._ensure_character_reference` (`run_service.py:367-443`), then its control flow, rollback, and dedup logic are untouched (5-10's standing guardrail) — it transparently produces sprite-contract cards now because its callees changed underneath it. `select_character_angles`' tri-state contract (`None`/`{}`/dict) is untouched.
11. **Tests.** Given automated verification: `domain/png.py` unit tests (RGBA/gray+alpha/RGB/short/garbage bytes — port the existing `_has_alpha` coverage from `tests/pipeline/nodes/test_image.py`); provider tests for `_inject_ipadapter_weight` (weight lands on the IPAdapter node, negative node untouched) and the deliberate-t2i entry point; service tests for the angle→weight table, opaque-save rejection, and `generate_cards_from_descriptor` (mock provider returning fixture bytes — reuse `tests/fixtures/images/mock_character.png` as valid RGBA); pose-axis tests per AC12 (pose param default keeps today's outputs byte-identical; `pose="sitting"` writes `{pose}_{angle}.png` + upserts a `character_cards` row; upsert idempotency under the unique constraint); seed-script idempotency test with an in-memory session. `uv run pytest tests/services tests/pipeline/nodes/test_image.py tests/domain -q` and the full suite green. **Do not copy the known trap**: always pass `workspace_path=str(tmp_path)` into `Settings` in tests (memory: `test_character_service_generation.py` pollutes the repo `./workspace/`).
12. **Pose axis plumbing (2026-07-06 amendment).** Given the storage design in Interfaces #4, then: the `CharacterCard` SQLModel exists in `db/models.py` with the `(scp_id, pose, angle)` unique constraint; a module-level `_POSE_DESCRIPTIONS` table in `character_service.py` (`{"standing": "standing upright", "sitting": "sitting on a plain simple chair, seated pose"}` — starting values, tune live like `_ANGLE_DESCRIPTIONS`) is composed with `_ANGLE_DESCRIPTIONS` when compiling the generation prompt; `generate_candidates_from_reference` and `generate_cards_from_descriptor` accept `pose: str = "standing"` — with the default, output paths, persistence, and behavior are byte-identical to pre-amendment (angle_*_path columns, `{angle}_candidate_1.png`); with a non-standing pose, files save as `{pose}_{angle}.png` and rows upsert into `character_cards` (insert-or-replace on the unique key). RGBA save validation (AC4) applies to every pose identically.
13. **v1 seeding scope (decision).** Given generation cost is real (each card is a ComfyUI render plus eyes-on QA), then the seeded library is: **run entity (SCP-049 here): {standing, sitting} × 4 angles = 8 cards; stock cast: standing × 4 angles only = 12 cards; derived entities: standing only unless explicitly seeded otherwise.** Rationale: stock extras composite mostly at mid/far depth where a sitting side/back sprite is visually near-indistinguishable from standing at 55–75% scale, and 8.3's standing fallback makes a `pose: "sitting"` request for an unseeded stock card benign (warn + standing) — so sitting stock cards are 12 more renders with no evidenced payoff. The entity gets both poses because it is the near-plane subject of interview/containment-chair beats (8.1 AC3(g) actively steers those to sitting). Widen by evidence via `seed_stock_cast.py --pose sitting`, not by default. Entity sitting cards are generated i2i with the entity's **standing front card** as the IPAdapter reference (AC7's self-referencing mechanism — one identity anchor for the whole library).

## Tasks / Subtasks

- [ ] Task 1 — `domain/png.py` + move (AC: 4, 11)
  - [ ] Create `src/yt_flow/domain/png.py` with `has_alpha(png_bytes: bytes) -> bool` moved verbatim from `image.py:109-117` (stdlib-only, keep the color_type-byte docstring). Update `image.py` to import it (its layered path still calls it until 8.3). Port/extend tests.
- [ ] Task 2 — Sprite workflow authoring + validation (AC: 1, 5)
  - [ ] Extend `data/workflows/comfyui_character_multi_angle_api.json`: `VAEDecode(8) → InspyrenetRembg(new node, torchscript_jit "default" like layered node 12) → SaveImage(9)`. Single SaveImage stays (5-10: `submit_and_fetch` returns first output's bytes — no node-ID-keyed variant needed).
  - [ ] Change `Settings.character_image_width/height` defaults to `832/1216` (`config.py:79-80`) and document in `.env.example`.
  - [ ] Validate directly against local ComfyUI (memory: `$HOME/workspaces/ComfyUI`, `./run.sh`, :8188; InSPyReNet node installed since 5-6): `POST /prompt`, poll `/history/{prompt_id}`, all 4 angle prompts, no `node_errors`, outputs pass `has_alpha` (5-10 Task 2 procedure; update `data/workflows/README-character-multi-angle.md`).
- [ ] Task 3 — Sprite prompts (AC: 2)
  - [ ] Update `_ANGLE_DESCRIPTIONS` (`character_service.py:51-57`) with the strengthened view tags; it is the single source of truth (5-10 guardrail) — no second list.
  - [ ] Update `prompts/character/generation.md` + the built-in fallback in `_compile_generation_prompt` (`character_service.py:657-664`) with the studio-background/full-body sprite requirements; re-seed via `scripts/seed_character_prompts.py`; run the PROMPT_POLICY rule-4 substitute check (compile comparison) and record it.
  - [ ] Also add background-exclusion negatives to the workflow's negative node 7 text (scenery, room, background detail) — belt and suspenders for the cutout.
- [ ] Task 4 — Per-angle IPAdapter weight (AC: 3, 5)
  - [ ] `_inject_ipadapter_weight(workflow, weight)` in `character_image_provider.py` (pattern: `_inject_seed`, lines 160-168; target `class_type in ("IPAdapter", "IPAdapterAdvanced")`, set `inputs["weight"]`). Thread `weight: float | None` through `generate()`.
  - [ ] `_ANGLE_IPADAPTER_WEIGHTS` module table in `character_service.py`; pass per angle from `generate_candidates_from_reference` (`character_service.py:577-599` loop). `# ponytail:` the values as live-tuned starting points.
  - [ ] Live D5 check: generate SCP-049's 4 angles, eyeball side/back truthfulness, iterate weights/prompt tags until side=profile and back=from-behind; record final values + evidence paths in Dev Agent Record.
- [ ] Task 5 — RGBA save validation (AC: 4)
  - [ ] In `generate_candidates_from_reference`, after `provider.generate(...)` returns bytes: `if not has_alpha(img_bytes): raise ValueError(...)` inside the existing per-angle try (`character_service.py:586-606`) so it logs + continues per angle, naming the card_key/angle in the message.
- [ ] Task 6 — Descriptor-driven card generation + stock seeding (AC: 6, 7, 8)
  - [ ] Provider: expose deliberate t2i (e.g. `generate(prompt, ref_image_path=None, ...)` → skip upload/injection and apply `_remove_i2i_input` up front; today `ref_image_path` is required and t2i only fires on exception, `character_image_provider.py:99-113`).
  - [ ] Service: `generate_cards_from_descriptor(card_key)` — front via t2i, then side/back/three_quarter i2i with the front card as IPAdapter reference; reuse the AC3 weight table; persist via existing `update_character`.
  - [ ] `scripts/seed_stock_cast.py`: built-in descriptor table for `STOCK_CAST_KEYS` (import from `yt_flow.domain.state` — 8.1; if 8.1 hasn't merged yet, define the tuple locally in the script with a `# ponytail:` note and swap to the domain import on rebase), `--key/--descriptor` for derived entities, `--pose` (default `standing`) per AC6/AC13, `--force` re-generation, idempotent skip. Follow `scripts/seed_character_prompts.py` structure (settings/session bootstrapping).
  - [ ] Live-run the script for the 3 stock keys against real ComfyUI (standing only — AC13); verify all 12 cards meet the artifact contract; record evidence.
- [ ] Task 6b — Pose axis (AC: 12, 13)
  - [ ] Add the `CharacterCard` model to `db/models.py` per Interfaces #4 (unique `(scp_id, pose, angle)` via `UniqueConstraint` in `__table_args__`); confirm `create_all` bootstrap picks it up; add a thin upsert helper on `CharacterService` (e.g. `save_card(scp_id, pose, angle, image_path)`) plus a lookup (`get_card(scp_id, pose, angle)`) — 8.3/8.4 consume the lookup.
  - [ ] `_POSE_DESCRIPTIONS` module table; thread `pose: str = "standing"` through `generate_candidates_from_reference` / `generate_cards_from_descriptor` (prompt compose + `{pose}_{angle}.png` naming + `character_cards` persistence for non-standing). `# ponytail:` the sitting descriptor as a live-tuned starting point.
  - [ ] Generate SCP-049's sitting × 4 library (i2i, standing front card as reference); eyeball seated truthfulness like the D5 check; record evidence.
- [ ] Task 7 — SCP-049 regeneration + regression (AC: 9, 10, 11)
  - [ ] Regenerate SCP-049's 4 standing cards under the new pipeline (evidence for 8.3's A/B DoD); sitting × 4 covered by Task 6b.
  - [ ] Regression gate (5-8/5-10 suite): `uv run pytest tests/services/test_run_service_character_provisioning.py tests/services/test_character_service.py tests/services/test_character_service_generation.py tests/services/test_character_angle_selector.py tests/pipeline/nodes/test_image.py -q` plus new tests; full suite green.

## Dev Notes

### D13/D5 mechanics — why studio-background + cutout, and why weights

- The 5-10 workflow renders the character *inside a scene* at 1664×928 because its prompt/framing were inherited from scene-generation defaults; nothing ever cut the subject out. `video.py`'s overlay chain (`_character_scale_filter` → `scale` → `overlay`, lines 301-351) mathematically works on any input but *visually* requires transparency — an opaque input is just a picture-in-picture covering the frame. Segmenting on a flat studio backdrop gives InSPyReNet a near-binary problem (the 5-6 quality issues were busy-scene artifacts, and D11's absurd cutouts were entity-less scenes — neither can occur on a studio plate with a guaranteed single subject).
- D5's mechanism: IPAdapter conditions cross-attention with the *frontal* reference embedding at weight 0.65 for every angle; the text tokens "side profile" lose. Lowering weight per angle trades identity fidelity for pose adherence — that trade is angle-dependent, hence the table, and needs eyes-on tuning (Task 4), not a unit test. The alternative knobs if weight alone is insufficient: `weight_type` (e.g. "ease out" — strong early composition guidance, weaker late detail) and prompt emphasis syntax; try weight first, escalate only if needed, record what worked.
- Self-referencing (AC7) reuses the D5 fix: the front card becomes the identity anchor for the other angles, exactly like a wiki reference does for real SCPs — one mechanism, two sources.

### Current Code State — files to read before editing

- `src/yt_flow/services/character_service.py` — `_ANGLE_DESCRIPTIONS` 51-57 (single source of truth), `_UPDATE_ALLOWLIST` 61-65, `create_character`/`_validate_create` 74-161, `generate_candidates_from_reference` 542-610 (per-angle try/except 586-606 is where opaque-rejection slots in), `_compile_generation_prompt` 624-664 (Langfuse → local file → built-in fallback triple, all three must carry the sprite requirements), `select_character_angles` 828-954 (do not touch — 8.3 reworks it).
- `src/yt_flow/services/character_image_provider.py` — `generate` 83-113 (i2i try / t2i-on-exception; AC7 makes t2i a first-class entry), `_load_workflow` 115-130, `_inject_prompt` 132-149 (skips negative nodes — the weight injector must be similarly targeted), `_inject_seed` 160-168 (the injection pattern), `_remove_i2i_input` 183-232 (IPAdapter bypass — already validated by 5-10's review to work for this workflow shape).
- `data/workflows/comfyui_character_multi_angle_api.json` — nodes: 3 KSampler, 4 checkpoint, 5 EmptyLatentImage, 6/7 CLIPTextEncode pos/neg, 8 VAEDecode, 9 SaveImage, 10/11 LoRAs, 20 LoadImage (reference), 21/22 CLIPVision/IPAdapter loaders, 23 IPAdapterAdvanced (weight 0.65). `comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` node 12 (`InspyrenetRembg`, `torchscript_jit: "default"`) → node 13 SaveImage is the RGBA pattern to graft.
- `src/yt_flow/db/models.py:23-39` — `Character` (scp_id unique index 27, angle paths 34-37). **`characters` is not altered**; the pose amendment adds the *new additive* `character_cards` table only (Interfaces #4). `CharacterCandidate` (54-73) stays the candidate-selection lifecycle — do not add pose to it (decision record in Interfaces #4).
- `src/yt_flow/services/run_service.py:367-443` — `_ensure_character_reference` (read, don't touch: 5-8/5-10 hardened rollback/dedup; it calls this story's changed callees).
- `src/yt_flow/config.py:73-88` — character settings block (width/height defaults change here).
- `src/yt_flow/pipeline/nodes/image.py:109-117` — `_has_alpha` (moving out).
- `_bmad-output/implementation-artifacts/5-10-entity-reference-pipeline-repair.md` — the workflow-authoring + live-validation precedent this story extends; its Review Findings (seed injection, t2i bypass warnings) are all still in force.

### Preserved behavior (do not break)

- **5-8 auto-provisioning contract** (`_ensure_character_reference`): non-fatal, rollback-on-total-failure, IntegrityError dedup — untouched (AC10). Its wiki→DDG reference path stays the source for *real SCP* cards; only stock/derived use descriptor-driven t2i.
- **`select_character_angles` tri-state** (`None`/`{}`/dict, `character_service.py:828-954`) — untouched here; 8.3 owns its rework. A `STOCK-*` row full of angle paths must not confuse it (it's keyed by the scp_id you pass, so it won't).
- **1.13 video-side behavior**: this story deployed alone changes what the override card *looks like* (RGBA sprite instead of opaque full-frame — a strict improvement on D13's worst symptom) but still overrides every shot until 8.3 gates it. Acceptable interim; note it in the Dev Agent Record when live-validating.
- **Mock/stub profiles**: `YTFLOW_COMFYUI_MOCK` never reaches character generation (provider is only invoked via CharacterService, mocked in tests via provider fakes); `tests/fixtures/images/mock_character.png` remains the RGBA fixture for provider-level fakes. Character-provisioning test seams (`tests/stubs/fakes.py::patch_character_reference_seams`) keep working — extend, don't replace.
- **Candidate-tracking flow** (`create_candidate_batch`/`select_candidate`, Story 1.12/3.7 UI): unchanged; card regeneration for SCP-049 (AC9) goes through existing update paths.
- **PROMPT_POLICY rule 4**: character prompts use the substitute pre-promotion check (direct compile comparison), documented in-policy — follow it for the generation.md change.

### Architecture compliance

- AD-1: `domain/png.py` is stdlib-pure (everyone → domain is always legal); `services/` importing it is clean. No pipeline/api imports added to services.
- AD-2: no state/checkpoint changes at all in this story.
- AD-10: card generation stays non-fatal within 5-8's envelope; per-angle failures log and continue.
- Layer note: `image.py` importing `domain.png` keeps `pipeline → domain` — strictly better than today.

### Testing standards

Provider/service tests mock HTTP + provider (existing `tests/services/test_character_service_generation.py` patterns); no real ComfyUI in the unit suite. Real-ComfyUI validation is a mandatory live task (5-10 precedent) — D5 truthfulness and cutout quality are eyes-on judgments; record evidence (file paths, weights used) in the Dev Agent Record. Always `workspace_path=str(tmp_path)` (memory: workspace-pollution trap).

### Ponytail note

No new provider class, and pose is ONE approved axis, not a matrix (2026-07-06, per Jay — the epic's "포즈 배리에이션 검토" resolved to the industry-standard tiered model): exactly two base pose values, the entity alone gets both, stock cast stays standing-only until evidence says otherwise (AC13), and anything freer is Story 8.4's on-demand single card — no expression/costume/outfit dimensions, no speculative pose values. One new domain module (5 lines), one 6-field table, one pose-descriptor table, one workflow node grafted from an already-validated workflow, one weight table, one script. `STOCK_CAST_KEYS` stays a 3-tuple until a real episode needs a fourth archetype.

## Project Structure Notes

- New: `src/yt_flow/domain/png.py`, `scripts/seed_stock_cast.py`, `CharacterCard` model in `src/yt_flow/db/models.py`, `data/workflows/README-character-multi-angle.md` updates, tests (`tests/domain/test_png.py` or fold into `test_state_imports`-adjacent module; `tests/services/` additions).
- Modified: `data/workflows/comfyui_character_multi_angle_api.json`, `src/yt_flow/services/character_service.py`, `src/yt_flow/services/character_image_provider.py`, `src/yt_flow/db/models.py` (additive table), `src/yt_flow/config.py` (width/height defaults), `.env.example`, `prompts/character/generation.md`, `src/yt_flow/pipeline/nodes/image.py` (import swap only).
- Parallel-work hazard: 8.1 also edits `domain/state.py` and 8.3 edits `image.py`/`config.py` — this story touches `image.py` (one import line) and `config.py` (two defaults); coordinate merges.

## References

- `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md` — D5, D13, "캐릭터 프로비저닝" section, "추가 결정 (Jay)" stock-cast block.
- `_bmad-output/planning-artifacts/epics.md#Story 8.2` — epic draft.
- `8-1-shot-cast-metadata-bg-prompts.md#Interfaces` — normative `card_key` vocabulary + `STOCK_CAST_KEYS`.
- `8-3-bg-only-generation-multicard-compositing.md` — the consumer of this story's card artifact contract (resolves `(pose, angle)` per cast member).
- `8-4-on-demand-special-pose-cards.md` — reuses this story's `character_cards` table (with `hint:*` pose keys) and `generate_cards_from_descriptor` path for on-demand special-pose cards.
- `_bmad-output/implementation-artifacts/5-10-entity-reference-pipeline-repair.md` — workflow authoring/validation precedent + IPAdapter environment facts (models/custom nodes confirmed installed).
- `docs/PROMPT_POLICY.md` rule 4 — character-prompt substitute check.
- Memory: `reference_comfyui_local` (ComfyUI at `$HOME/workspaces/ComfyUI`, ROCm quirks), `project_test-isolation-workspace-pollution` (tmp_path rule), `project_5-6-review-done` (InSPyReNet install + LoraLoader node-13 history — note that config's `comfyui_character_node="13"` refers to the *layered* workflow and dies with it in 8.3; unrelated to this story's workflow).

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Change Log

- 2026-07-06: Story created from Epic 8 architecture decision (E2E baseline run 272b05a4). Owns the Epic 8 card artifact contract (RGBA sprite) and stock-cast seeding.
- 2026-07-06: pose dimension added per Jay — industry-standard sprite-library tiering. This story now owns the pose-aware storage design (Interfaces #4: standing stays in `angle_*_path`, non-standing in the new `character_cards` table keyed `(scp_id, pose, angle)`), the `pose` generation parameter, and the v1 seeding scope decision (entity: standing+sitting ×4; stock: standing-only ×4 — AC13). Supersedes this story's earlier "pose variations deferred" Ponytail stance; Saved Question #4 re-scoped accordingly.

## Saved Questions / Clarifications

1. **Mid-run derived-entity provisioning.** This story delivers the mechanism (`generate_cards_from_descriptor` + script) but nothing auto-generates `SCP-049-2` cards when a scenario first emits that card_key — 8.3 skips missing cards with a warning. Story 8.4 now builds exactly the post-scenario-gate provisioning hook this question anticipated, but scoped to *special-pose cards for already-carded keys* — auto-generating a whole card set for a never-seen derived entity remains open: needs Jay's call on whether an LLM-authored descriptor for a derived entity is trustworthy enough to generate unattended (if yes, 8.4's hook is the natural extension point).
2. **Identity drift on self-referenced angles.** Stock cards use the generated front card as the IPAdapter reference for the other angles — identity consistency depends on that single t2i roll. If live results drift, the fallback is a curated local reference image per stock archetype (checked into `data/`), which the same service method can consume. Decide by evidence in Task 6.
3. **Existing non-049 character rows.** Any other dev-DB characters generated pre-8.2 hold non-compliant RGB cards. 8.3's alpha validation will reject them loudly at render time (by design). Bulk regeneration is a one-liner with the seed script pattern but is not in this story's DoD — flag to Jay.
4. **Sprite canvas 832×1216** assumes full-body cards. If a future close-up shot wants a bust card, that's a per-angle framing *variant*, not a new canvas — still deferred (pose itself is no longer deferred — 2026-07-06 amendment — but framing is a different axis and stays out until a real shot needs it; if it ever lands, the `character_cards` pose key can absorb it without re-keying).
