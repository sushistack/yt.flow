---
title: 'Story 8.16: Depth-aware card placement + IC-Light v1 relighting'
type: 'feature'
created: '2026-08-02'
baseline_revision: 'f69f37e'
status: 'draft'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: [oversized]
---

<intent-contract>

## Intent

**Problem:** Cards read as pasted-on rather than standing in the room. The direct cause is arithmetic, not aesthetics: the overlay's vertical anchor is `y = (main_h-overlay_h)/2` (`video.py:435`) — dead frame-centre, identical for `near`, `mid` and `far` — while the contact shadow is drawn at a fixed `Y/H = 0.85` (`composite_harmonization.py:102`). Feet and shadow therefore disagree by construction, and no ground plane exists anywhere in the pipeline. Separately, the whole relight ladder above Tier 2 is inert: Story 8.7 built the resolver, cache, precompute and tracing, but `data/workflows/comfyui_iclight_relight_api.json` is a placeholder with no IC-Light node and two dangling `LoadImage` inputs, so `_load_iclight_workflow`'s `ytflow_verified_iclight` guard fails every call and Tier 3 has never once fired.

**Approach:** Give the frame a ground plane and anchor feet to it, estimated per background from a monocular depth map, with the shadow derived from the same plane so the two can no longer disagree. Then make Tier 3 real: author the IC-Light v1 graph the installed nodes now support, and light the card from its own plate. Both live behind a new `services/compositing_service.py` so `video_node`'s ffmpeg assembly does not grow depth or relight logic.

## Boundaries & Constraints

**Always:**
- Feet and contact shadow derive from **one** ground-plane value per (shot, card). They are currently independent constants and that is the defect.
- IC-Light stays on **v1 `iclight_sd15_fbc`** (installed, 1.72GB, commercially usable). v2/Flux is non-commercial and must never be introduced.
- Tier 1/2 remain the fallback when relight is off, unavailable or fails. Every relight failure degrades to the existing chain and never fails a run (AD-10).
- Respect the injection seams: `pipeline/nodes/` may not import `db`, `api` or `services`; only `run_service.py` may import `pipeline/`; crossings go through the allow-listed `inject_*` functions. Two tests enforce this.
- Depth estimation runs **once per background plate**, cached beside the plate — never per shot, never per card. Sharing the location-plate depth map with Story 11.5 is the intended reuse.
- `has_alpha` remains a hard failure for any card entering the overlay path (a D13 guard).

**Block If:**
- IC-Light produces a relit sprite whose alpha differs from the source silhouette, or whose resolution differs from the card — that would break the sprite contract that D13 exists to protect. HALT rather than loosen the check.
- The measured on-screen character height after the placement change exceeds the pre-8.15 D13 margin. `deferred-work.md` already records that 8.15's subject-scale normalisation shrank that margin with no test; this story must not compound it silently.

**Never:**
- No `libcom`. Verified uninstallable here: `libcom 0.1.7` → `mmpose 1.2.0` → `xtcocotools`, whose sdist ships no Cython-generated C and fails to compile on Python 3.12 (three attempts, including `--no-build-isolation` and a pinned Cython). Its two roles are covered instead by the depth-derived shadow below and by the Qwen-VL scorer already proven twice in this epic — which also sidesteps the draft's own concern that libcom's photoreal-trained score may not transfer to stylised cards.
- Do not touch `src/yt_flow/pipeline/nodes/{subtitle,tts,scenario_chain}.py` or anything under `_bmad-output/story-automator/`.
- Do not change the `position` / `depth` enums or the scenario prompts that emit them. This story reinterprets those values against a real plane; it does not extend the vocabulary.
- No new pipeline stage.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Plate with a depth map | shot has `location_key`, depth cached | Feet land on the estimated ground line; shadow uses the same value | — |
| Background with no depth map yet | first use of a plate | Depth computed once and cached beside the plate | Estimation failure → fall back to the per-depth default ground line, warn once |
| Freely generated background | no `location_key` | Depth computed for that shot's render, cached by content hash | Same fallback |
| `far` vs `near` card | same shot | Different ground y **and** different scale; `far` sits higher in frame | — |
| Foreground occluder | depth map says something is nearer than the card | Card is masked where the occluder is in front | No occluder → unchanged overlay |
| Relight available | tier 3, STOCK card + plate, both verified | Card relit from the plate, alpha and resolution identical to source | Any mismatch → discard, keep original card, warn |
| Relight unavailable | node/model absent, or workflow unverified | Silent fall through to Tier 1/2 | Never fails the run |
| Relight cache hit | same (card, plate, style_epoch) | No ComfyUI call | Stale epoch → recompute |
| Background-only shot | `cast == []` | Zero placement and zero relight work | — |

</intent-contract>

## Code Map

- `src/yt_flow/pipeline/nodes/video.py` — `_overlay_filter` (:396-451), the vertical anchor to replace at **:435**; `_character_scale_filter` (:531-549) downscale-only inside the motion-safe box; `_build_card_chain` (:842-947) the single chain builder both render paths share; `CARD_EDGE_FEATHER` (:94); `_DEPTH_SCALE` / `_DEPTH_PARALLAX` / `_POSITION_X_FRAC` (:174-193); tier gate (:865-876); Tier-3 substitution site (:1673, :1706-1727); `inject_relight_resolver` (:67-76); the `has_alpha` hard fail (:1663-1668).
- `src/yt_flow/pipeline/nodes/composite_harmonization.py` — `build_contact_shadow` (:76-104) with the fixed `Y/H=0.85` and `_SHADOW_DEPTH_SCALES`/`_SHADOW_BLUR_RADII`/`_SHADOW_POSITION_OFFSETS` (:59-63); `build_light_wrap` (:107-162); `RelightCache` (:173-244, key `relit/{card_key}/{location_key}`, file `epoch_{style_epoch}.png`, stale-epoch = miss); `_load_iclight_workflow` (:312-316) and its `ytflow_verified_iclight` guard; eligibility (:363-379); `_RELIGHT_CONCURRENCY` (:170); the AD-1 note (:8-15).
- `data/workflows/comfyui_iclight_relight_api.json` — the placeholder to replace: plain txt2img, no IC-Light node, both `LoadImage` outputs unreferenced, and its own `_meta.title` says so. `data/workflows/README-iclight-relight.md` records why.
- Newly installed and verified registered: `LoadAndApplyICLightUnet`, `ICLightConditioning`, `LightSource`, `BackgroundScaler`, `DetailTransfer`; model `models/unet/iclight_sd15_fbc.safetensors`; SD1.5 base `cyberrealistic_v90.safetensors`; depth via `comfyui_controlnet_aux`'s `depth_anything_v2`.
- `src/yt_flow/domain/state.py` — `CastMember` (:62-73), `ShotData` (:89-99, `camera_angle`, `location_key`, `cast`), `SceneState.mood` (:110). No depth/ground field exists yet.
- `src/yt_flow/services/run_service.py:865-882` — `precompute_relights_for_run`, the only sanctioned services→pipeline crossing.
- `src/yt_flow/services/location_service.py` — where a plate's depth map should live alongside `image_path`.
- Tests: `tests/pipeline/nodes/test_composite_harmonization.py`, `tests/pipeline/nodes/test_video_harmonization.py` (16, incl. two real-ffmpeg renders), `tests/pipeline/nodes/test_video.py`. **Every assertion is on the filter string or that a graph renders; none inspects pixels** — a placement change is invisible to all of them.

## Tasks & Acceptance

**Execution:**
- [ ] `src/yt_flow/services/compositing_service.py` -- new: `ground_line(depth_map, position, depth) -> float` and `occlusion_mask(depth_map, card_box, card_depth) -> Path | None`, plus depth-map computation and caching keyed on the plate (or the render's content hash for freely generated backgrounds) -- keeps depth logic out of `video_node`'s ffmpeg assembly, per the epic's "isolate new complexity behind a narrow service".
- [ ] `src/yt_flow/pipeline/nodes/video.py` -- replace the frame-centre `y` with the ground line supplied per (shot, card) through a new `inject_ground_resolver` seam, defaulting to today's centre when no resolver is injected -- the anchor is the actual "floating" defect, and the default keeps every existing test byte-identical until it opts in.
- [ ] `src/yt_flow/pipeline/nodes/composite_harmonization.py` -- derive `build_contact_shadow`'s ellipse Y from the same ground value instead of the hardcoded `0.85` -- one value feeding both is what makes feet and shadow agree.
- [ ] `src/yt_flow/pipeline/nodes/video.py` + `composite_harmonization.py` -- apply the occlusion mask to the card chain when the service returns one -- the overlay has no occlusion concept today, so a foreground object never covers a character.
- [ ] `data/workflows/comfyui_iclight_relight_api.json` -- author the real graph: SD1.5 base + `LoadAndApplyICLightUnet` (`iclight_sd15_fbc`) + `ICLightConditioning` fed by the plate as background, card as foreground; set `ytflow_verified_iclight: true` only after a live render is confirmed -- the marker is a promise about live verification, not a formality.
- [ ] `src/yt_flow/pipeline/nodes/composite_harmonization.py` -- assert the relit sprite matches the source in resolution and alpha silhouette before it is cached -- a relit card that changes its own silhouette is the D13 contract break, so it must be rejected rather than trusted.
- [ ] `src/yt_flow/services/compositing_service.py` -- masked low-denoise fuse pass (denoise ~0.2-0.3 over the card plus a dilated border) as an optional stage after relight -- the community-standard finish that kills the sticker edge; two light passes beat one heavy.
- [ ] `src/yt_flow/services/compositing_service.py` -- depth-derived contact shadow: project the card's footprint onto the ground plane using the plate's light direction estimated from the depth map and plate luminance -- replaces libcom's shadow generation with no new dependency.
- [ ] `scripts/score_composites.py` -- new: Qwen-VL composite QA over rendered frames (does the character look placed in the room, are feet grounded, is lighting consistent), reusing the wiring proven by `label_location_plates.py` -- replaces libcom's composite scorer, and unlike it is calibrated on this project's stylised art.
- [ ] `src/yt_flow/config.py` -- raise `composite_harmonization_tier` default to 3 **only after** live verification, and add the depth/fuse knobs -- tier 3 has never fired, so promoting it by default before a live render would ship an untested path.
- [ ] `tests/` -- pixel-level tests, which do not exist today: ground line monotonic in depth (`far` higher than `near`), feet and shadow agree within tolerance, occlusion mask actually masks, relit-sprite contract rejection, and a real-ffmpeg render asserting the composited character's bounding box sits on the expected ground line.
- [ ] Live verification: render one real shot per depth value and per relight state, measure the composited character's feet against the ground line and its height against the D13 margin, and score the frames with the QA script.

**Acceptance Criteria:**
- Given a shot with a depth map, when a card is composited, then its feet and its contact shadow sit on the same ground line, and `far` cards sit measurably higher in frame than `near` ones.
- Given no ground resolver is injected, when a scene renders, then the filtergraph is byte-identical to today's.
- Given the depth map marks a foreground object nearer than the card, when the shot renders, then the card is occluded there.
- Given tier 3 and a verified workflow, when a STOCK card meets its plate, then a relit sprite is produced, cached, and reused on the next run without a ComfyUI call.
- Given a relit sprite whose alpha or resolution differs from the source, when it is evaluated, then it is discarded and the original card is used.
- Given IC-Light is unavailable or fails, when a run renders, then it completes on Tier 1/2 with a warning and no failed stage.
- Given the four baseline defects, when the composited frames are inspected, then D5 (angle mismatch), D10 (inpaint scars), D11 (environment mis-cut) and D13 (alpha-less full-frame card) are each demonstrably absent.

## Spec Change Log

## Review Triage Log

## Design Notes

Why the anchor is the whole story: `y = (main_h-overlay_h)/2` places every card's *centre* at the frame's centre, so a `far` card — scaled to 0.55 — has its feet 22% of frame height above where a `near` card's feet land, in the opposite direction from perspective. The shadow's independent `Y/H = 0.85` then draws contact at a third place entirely. No amount of relighting fixes a figure whose feet are nowhere near its shadow, which is why ① precedes ② despite ② being the more interesting technique.

Why Tier 3 is cheap now: 8.7 shipped the resolver, the atomic cache with epoch invalidation, the concurrency cap and the tracing, all reviewed. The only missing pieces are a workflow graph the installed nodes can execute and the `ytflow_verified_iclight` marker. Treat that marker as the live-verification gate it was designed to be.

## Verification

**Commands:**
- `PYTHONPATH=$PWD/src python -m pytest tests/pipeline/nodes/ tests/services/test_compositing_service.py -q` -- expected: all pass
- `PYTHONPATH=$PWD/src python -m pytest -q` -- expected: green against the 1568-test baseline
- `curl -s localhost:8188/object_info | grep -c ICLightConditioning` -- expected: 1 (nodes registered)

**Manual checks (if no CLI):**
- One rendered frame per depth value: are the feet on the floor, and does the shadow sit under them?
- A frame with a foreground occluder: is the character behind it?
- A relit card over its own plate: does the lighting direction match the room?
