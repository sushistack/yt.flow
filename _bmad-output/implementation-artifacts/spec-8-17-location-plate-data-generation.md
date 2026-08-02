---
title: 'Story 8.17: Stock location plate data generation + AI auto-labeling'
type: 'feature'
created: '2026-08-02'
baseline_revision: '213a087'
status: 'in-progress'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: [oversized]
---

<intent-contract>

## Intent

**Problem:** Story 8.5 shipped the location-plate schema, service, seed script, workflow and consumer fast-path, then was marked done without ever producing a plate: `location_plates` has 0 rows and `assets/locations/` is empty, so every run regenerates every background and the STOCK fast path has never once fired in production. The script cannot even start in real mode — it `sys.exit`s on two preflight gates (`data/anchors/locations/LOOKDEV_DECISION.md` and at least one anchor image), and neither exists.

**Approach:** Make the generator actually runnable and its output reviewable, then run it: curate a style anchor, generate 14 LocationKeys × 3 variants = 42 plates at SDXL-native resolution, score each one with the already-wired Qwen-VL vision call, auto-approve clear passes and leave everything ambiguous as `draft` for the operator queue. No pipeline code or wiring changes — this is an offline batch plus the fixes it needs to survive one.

## Boundaries & Constraints

**Always:**
- Auto-approval is only for unambiguous passes. Anything the scorer is unsure about stays `draft`, which is already the human queue (`get_approved_plates` filters on `status == "approved"`, so a draft plate can never reach a render).
- A rejected plate must be re-rollable to a *different* image. Today the seed is `int.from_bytes(f"{key}:{variant}")`, so regenerating reproduces the identical plate byte-for-byte and the human gate cannot converge.
- The 42-plate batch must survive a ComfyUI abort. `hipErrorIllegalAddress` core dumps are an established fact of this host (Story 5.23, and three more today) and 5.23's recovery loop lives only in `image.py`.
- Plates stay RGB full-frame 1920×1080 on disk — `_valid_plate` requires exactly those dimensions and the consumer copies the file verbatim.
- Prompt content is out of scope. In particular do **not** strip "SCP Foundation" from `LOCATION_PROMPTS`: the token's proven failure mode is collapsing *faces* into masks, there is no evidence it harms room architecture, and `PLATE_NEGATIVE_PROMPT` already suppresses `person, people, human, character, creature, figure, silhouette`.

**Block If:**
- The operator has not chosen a style anchor. Generate 4 candidate anchors, write them somewhere reviewable, and HALT `blocked` with `awaiting Jay anchor selection` — 42 plates inherit that anchor via IPAdapter, so guessing it wastes the whole batch.
- After the batch: HALT `blocked` with `awaiting Jay visual approval` listing every plate that auto-labeling left as `draft`. Auto-approved plates still get reported, never silently shipped.

**Never:**
- No new pipeline stage, no change to `image.py`'s fast path, no change to `visual_breakdown`'s `location_key` vocabulary.
- No schema migration. `LocationPlate` has no label/score column; put the scorer's verdict in the manifest entry's free-form `source` dict.
- Do not touch `src/yt_flow/pipeline/nodes/{subtitle,tts,scenario_chain}.py` or anything under `_bmad-output/story-automator/` — a concurrent session owns them.
- Do not weaken `_valid_plate`'s dimension check to accommodate a smaller render; upscale to meet it instead.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Anchor missing | no image in `data/anchors/locations/` | Generate 4 candidates, HALT for selection | Existing `sys.exit` message stays accurate |
| Normal plate | key+variant, anchor chosen | 1920×1080 RGB PNG, DB row `draft`, manifest entry | Per-plate failure logs and continues; exit 1 if any failed |
| Re-roll a rejected plate | `--reroll` on an existing draft | A *different* image for the same key+variant | No error expected |
| Already approved | approved row, no `--force` | Skipped, GPU not spent | No error expected |
| ComfyUI dies mid-batch | abort after plate N | Wait-and-recheck, then continue from plate N+1 | Exhausted recovery window → fail with the remaining keys named |
| Auto-label clear pass | scorer returns high confidence + no defects | `status="approved"`, verdict recorded in manifest `source` | — |
| Auto-label ambiguous/fail | low confidence, or names a defect | stays `draft`, verdict recorded, surfaced in the operator queue | Scorer HTTP failure → stays `draft`, never auto-approves on a failed call |
| Scorer sees a person | plate contains a figure (D11 class) | Never auto-approved | — |

</intent-contract>

## Code Map

- `scripts/seed_location_plates.py` — the generator. `LOCATION_PROMPTS` (:49-64), `VARIANTS` (:36), preflight gates `_load_anchor_paths` (:79-86) / `_check_lookdev_decision` (:89-96), deterministic seed (:184), `_valid_plate` (:126-143), destructive re-run path (:173-179, deletes any non-approved row), `add_location_plate` call (:204), CLI (:246-251). Zero tests today.
- `src/yt_flow/services/location_service.py` — real schema and lifecycle. `approve_plate` (:53) is manifest-first then `status="approved"`; `reject_plate` (:66) resets to `draft`, there is no distinct rejected state.
- `src/yt_flow/db/models.py:57-67` — `LocationPlate`: `location_key`, `variant`, `image_path`, `status`, `style_epoch`, `created_at`. No label/score column.
- `src/yt_flow/services/asset_service.py:130-146` — `add_location_plate` writes the row plus a manifest entry whose `source` dict is free-form (where the verdict goes).
- `data/workflows/comfyui_location_plate_api.json` — AnimagineXL + horror/darkness LoRAs + IPAdapter (`ip-adapter-plus_sdxl_vit-h`, weight 0.4); `EmptyLatentImage` **1920×1080**; RGB out, no rembg. Injection nodes 6/7/3/20/23.
- `src/yt_flow/services/character_service.py:577-651` — `enrich_descriptor_from_references`, the only Qwen-VL call in the repo: DashScope endpoint constant (:41), `character_vision_model` / `character_vision_api_key` / `character_vision_max_tokens`, caps input at 3 images, returns free text or `None`. There is no structured/JSON vision scorer to reuse.
- `src/yt_flow/pipeline/nodes/image.py:319-344` — consumer fast path; requires `_location_service` injected (only `api/main.py:42-47` does that) plus ≥1 approved plate, else one warning per key and fall through to generation.
- `scripts/approve_location_plate.py` — one plate per invocation, `--key` + `--variant`, no bulk.
- `src/yt_flow/pipeline/nodes/image.py` (5.23 recovery) — the crash wait-and-recheck pattern to mirror: `comfyui_crash_recovery_poll_sec` / `comfyui_crash_recovery_timeout_sec` in `config.py:46-47`.

## Tasks & Acceptance

**Execution:**
- [ ] `scripts/seed_location_plates.py` -- generate at an SDXL-native bucket (1344×768, matching Story 11.1's shot-background fix) and Lanczos-upscale to 1920×1080 before validation/save -- a 1920×1080 latent is ~2× SDXL's training area and produces duplicated architecture; the on-disk contract stays 1920×1080.
- [ ] `scripts/seed_location_plates.py` -- add `--reroll`: mixes a salt into the per-plate seed so a regenerated plate is genuinely different, and record the salt used in the manifest `source` so a good plate can be reproduced -- a human gate that always re-renders the same image cannot converge.
- [ ] `scripts/seed_location_plates.py` -- wrap the per-plate submit in a ComfyUI wait-and-recheck recovery loop reusing `comfyui_crash_recovery_poll_sec`/`comfyui_crash_recovery_timeout_sec`, and make the batch resumable so recovery continues at the next unfinished plate -- a 42-plate batch on this host will hit an abort.
- [ ] `scripts/seed_location_plates.py` -- add `--anchor-candidates N`: generate N anchor candidates with no IPAdapter conditioning into a review directory and exit, so the anchor gate can be satisfied without hand-made art.
- [ ] `scripts/label_location_plates.py` -- new: for each `draft` plate, one Qwen-VL call returning a structured verdict (matches the `location_key` description / contains no person or legible text / quality). Clear pass → `approve_plate`; anything else stays `draft`. Always write the verdict into the manifest `source`. A scorer HTTP failure leaves the plate `draft` -- reuses 5.13's wiring, adds no dependency, and the closed decision rule keeps auto-approval conservative.
- [ ] `scripts/approve_location_plate.py` -- add a bulk mode (all flagged, or `--key` without `--variant`) and a listing of what is still `draft` -- the operator reviews a queue, not 42 individual invocations.
- [ ] `tests/test_seed_location_plates.py` -- new: preflight gates, `_valid_plate` (dimensions/size/magic), the approved-skip vs non-approved-delete branch, reroll produces a different seed, upscale path yields exactly 1920×1080, crash-recovery loop continues after a simulated abort.
- [ ] `tests/test_label_location_plates.py` -- new: clear pass approves, ambiguous stays draft, person-detected never approves, scorer failure stays draft, verdict lands in the manifest `source`.
- [ ] Generate the anchor candidates, HALT for selection, then on selection write `data/anchors/locations/LOOKDEV_DECISION.md` recording which candidate was chosen and why.
- [ ] Run the 42-plate batch, run the labeler, then verify the fast path actually fires end-to-end and HALT for the operator queue.

**Acceptance Criteria:**
- Given the anchor gate is unsatisfied, when the seed script runs in real mode, then it explains what is missing and spends no GPU.
- Given a chosen anchor, when the batch completes, then `location_plates` holds 42 rows, `assets/locations/` holds 42 PNGs, and every file is exactly 1920×1080 RGB.
- Given the labeler has run, when a plate was auto-approved, then its manifest `source` records the verdict that justified it; when a plate was not, then it is still `draft` and appears in the operator queue.
- Given approved plates exist, when a run resolves a shot carrying that `location_key`, then the plate file is copied instead of generated and `stock_plate_count` is non-zero in the trace — the fast path is proven to fire, not merely wired.
- Given ComfyUI aborts mid-batch, when it comes back inside the recovery window, then the batch continues and no already-generated plate is regenerated.
- Given `--reroll` on a plate, when it runs twice, then the two images differ.

## Spec Change Log

## Review Triage Log

## Design Notes

Why the fast path must be *proven*, not assumed: `image.py` only resolves plates when `inject_location_service` has been called, and the sole caller is the API app factory. A CLI-driven verification would silently fall through to generation and look like a pass. Verification has to go through the API path (or explicitly inject the resolver) and assert `stock_plate_count > 0`.

Why the verdict goes in the manifest rather than a new column: `LocationPlate` has no label/score/notes field, `add_asset`'s `source` is already a free-form dict carrying provenance, and a migration for one advisory string is not worth it. If per-plate scores later need querying, that is the moment for a column.

## Verification

**Commands:**
- `PYTHONPATH=$PWD/src python -m pytest tests/test_seed_location_plates.py tests/test_label_location_plates.py -q` -- expected: all pass
- `PYTHONPATH=$PWD/src python -m pytest -q` -- expected: green against the 1494-test baseline
- `sqlite3 yt_flow.db "select status, count(*) from location_plates group by status"` -- expected: 42 rows total after the batch
- `python3 -c "from PIL import Image; import glob; print({Image.open(p).size for p in glob.glob('assets/locations/*/*.png')})"` -- expected: `{(1920, 1080)}`

**Manual checks (if no CLI):**
- Each anchor candidate: does it read as one coherent facility look worth applying to all 42 plates?
- Each `draft` plate left by the labeler: room matches its `location_key`, no people, no legible signage, no duplicated architecture from over-resolution.
