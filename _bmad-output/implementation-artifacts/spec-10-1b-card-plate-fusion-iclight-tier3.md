---
title: 'Story 10.1b — Card/plate fusion: harmonization tier 3 (IC-Light) live activation'
type: 'feature'
created: '2026-08-08'
status: 'rejected'
baseline_revision: '5ce57ae'
review_loop_iteration: 1
superseded_by: '10-1c'
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/10-1-grounding-composite-live-verification.md'
  - '{project-root}/_bmad-output/implementation-artifacts/10-1-live-validation/README.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** Story 10.1's verdict was STILL FLOATING with the broken link named as `harmonization` — finding 11 (floating) is fixed by 8.16, but finding 3 ("torn out and pasted onto the background") survives because card and plate do not share light. Harmonization tier 3 (IC-Light relight) exists in code and has never rendered a frame into a video.

**Approach:** Fix the two measured wiring defects in the existing IC-Light v1 `fbc` graph, widen relight eligibility so the run's dominant cards are actually covered, re-render run `8a9a288b`'s video stage at tier 3, and adjudicate tier 1 vs tier 3 on Story 10.1's own six-shot slate using its own `make_pairs.sh` / `measure.py`.

**Three premises in the invocation are stale — corrected here, with evidence:**

1. **"Nodes 3~9 are a plain SDXL shell."** False. `data/workflows/comfyui_iclight_relight_api.json` already holds a complete IC-Light v1 `fbc` graph (`LoadAndApplyICLightUnet` + `ICLightConditioning` with `opt_background` + `DetailTransfer` + `JoinImageWithAlpha`). Its own `_ytflow_note` records that it **executes correctly and satisfies the sprite contract**, and was parked on 2026-08-02 because the *output* was bad (denoise 0.45/0.60/0.85 → washed grey / near-black / blue-monochrome). `README-iclight-relight.md` is the stale document, not the JSON. The real work is not "replace a shell" but "fix two wiring defects that explain the bad output".
2. **"Only the marker is missing."** The marker is one of four blockers. The other three are the two graph defects below and the eligibility gate in §Design Notes.
3. **"Re-run the video stage via `POST /stages/video/retry`."** That returns **409** today: `8a9a288b`'s video gate is `pending`, and `retry_stage` requires `approved|rejected|failed` (`run_service.py:46,858-863`). The working call is `POST /runs/{id}/stages/video/gate {"action":"reject"}`, which nullifies and re-enters the video node in one step.

## Boundaries & Constraints

**Always:**
- Preserve the tier-1 control **before** anything re-renders. `video.py:1885` unlinks every `shots/scene_NNN_*.mp4` per scene, and `make_pairs.sh` writes `on/` with `-y`. Copy `10-1-live-validation/on/` → `tier1/` and the six slate clips out of `workspace/8a9a288b-*/shots/` first. `off/` is irreplaceable and is never regenerated.
- IC-Light **v1 `fbc` only** (`iclight_sd15_fbc.safetensors`, kijai `ComfyUI-IC-Light` @ `22811d9`), on the SD1.5 checkpoint `cyberrealistic_v90.safetensors`. `LoadAndApplyICLightUnet` hard-rejects non-SD1.5 models.
- Grant `"ytflow_verified_iclight": true` **only after** a single card+plate pair has been submitted live and returned a visually better sprite than the unlit card. Never as part of the same edit that changes the graph.
- Alpha is the contract: a relit sprite must keep the source silhouette. `precompute_relights` already rejects non-alpha output; verify the silhouette correlation is **positive** (an `InvertMask` here previously produced correlation −1.0).
- The IC-Light failure path stays non-fatal (`composite_harmonization.py:361`).

**Block If:**
- GPU DPM is not `high` (`cat /sys/class/drm/card*/device/power_dpm_force_performance_level`) — needs root; escalate to Jay, do not fix.
- ComfyUI is wedged. Cold start is ~8m30s; do not judge on a shorter threshold. Distinguish by completion history: `journalctl --user -u ytflow-comfy | grep "Prompt executed"`.
- Stage 1 (tier 3 alone) leaves finding 3 open **and** the stage-2 masked low-denoise fusion pass would require changing anything outside `video.py`'s composition path or the workflow JSON.
- The tier-1 vs tier-3 frames cannot be adjudicated visually (renders fail, or the pairs are unreadable) — HALT and escalate to Jay. Do not close on green tests.

**Never:**
- IC-Light v2 or Flux (non-commercial licence). Qwen-Image-Edit (rejected in 8.20).
- Enlarging any negative prompt (`gotcha_negative-prompt-overstuffing` — wrecked renders twice).
- `POST /stages/image/retry` on `8a9a288b` — deletes all 66 plates (`run_service.py:870-871`).
- Setting `stock_plate_substitution_enabled` to anything but `false`.
- Starting the conditional stage 2 before stage 1 has a recorded verdict.
- Any other Epic 10 story (10.2–10.7), and the follow-ups 10.1 routed elsewhere (occlusion head-erasure, near-band clamp, contact-shadow strength).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Eligible pair, marker true | verified card + verified `location_key`, tier 3 | IC-Light returns an alpha PNG; cached at `assets/relit/{card_key}/{location_key}/epoch_2.png`; `stats.computed` +1 | No error expected |
| Marker still false | tier 3, `ytflow_verified_iclight` absent/`false` | `{}` map, `stats.failed` +1, run continues at tier 1/2 | `ValueError` swallowed at `:361`, logged as a warning |
| Relit output has no alpha | ComfyUI returns opaque RGB | Pair discarded; original card path used | `RelightCache.store` raises `ValueError`; counted as failed |
| Shot has no `location_key` | free-text background (8 of 66 shots) | Shot skipped; card composited unrelit | Not an error — a skip |
| Entity card over verified location | `SCP-049` × `containment-chamber`, tier 3 | **After the eligibility widening:** pair is computed. Before it: silently skipped | Not an error — a skip |
| ComfyUI unreachable / times out | tier 3, no server | `{}` map, `stats.failed` = pair count, video renders at tier 1/2 | Warning per pair; run never fails |

</intent-contract>

## Code Map

- `data/workflows/comfyui_iclight_relight_api.json` -- the fbc graph. Real, executes, parked on quality. Nodes to change: `12` (fg latent), `3` (init latent + denoise); node to add: grey matte + `LightSource`. The marker lives at the top level and must be `true` (identity check, `is not True`).
- `data/workflows/README-iclight-relight.md` -- stale: still describes nodes 3–9 as an SDXL placeholder. Correct it.
- `src/yt_flow/pipeline/nodes/composite_harmonization.py` -- `_load_iclight_workflow:306-329` (marker check), `_inject_relight_inputs:332-337` (writes only nodes `"1"`/`"2"`), `relight_sprite:340-363`, `precompute_relights:366-460`. **`:421` `card_key not in STOCK_CAST_KEYS` is the eligibility gate.** `RelightCache:185-256`.
- `src/yt_flow/pipeline/nodes/video.py:2262-2270` -- tier ≥ 3 resolver call; `:2298-2320` -- per-shot relit-path substitution; `:2201` -- `Settings()` read per invocation (so `.env` edits need no API restart); `:1885` -- the destructive shot-clip unlink.
- `src/yt_flow/services/comfyui_client.py:146-155,194-211` -- `upload_image` → `POST /upload/image`; `:214-241` -- `_bust_save_cache` rewrites `filename_prefix` so resubmits are not cache-served; `:397-406` -- output retrieval is node-id-agnostic (first output node).
- `src/yt_flow/config.py:254-255` -- `composite_harmonization_tier` (default `1`), `iclight_comfyui_workflow_path`.
- `_bmad-output/implementation-artifacts/10-1-live-validation/` -- `make_pairs.sh` (hardcodes `on/` and the label), `measure.py` (hardcodes `off/` vs `on/`), `off/` (third reference point, never regenerate).
- `tests/pipeline/nodes/test_composite_harmonization.py`, `tests/pipeline/nodes/test_video_harmonization.py` -- existing tier-3 unit coverage; **no test loads the shipped workflow JSON**.

## Tasks & Acceptance

**Execution:**

- [x] `_bmad-output/implementation-artifacts/10-1b-live-validation/` -- create it, `cp -a ../10-1-live-validation/off .` and `cp -a ../10-1-live-validation/on ./tier1`, and copy the six slate clips from `workspace/8a9a288b-*/shots/` -- the tier-1 state is the control and the video retry destroys it. Do this **first**; nothing else may run before it.
- [x] `data/workflows/comfyui_iclight_relight_api.json` -- fix the foreground latent: the card's transparent region is 71.7% pure black RGB after `LoadImage`'s `convert("RGB")`, so fbc is told the subject sits in a void. Composite the card onto neutral grey `#7F7F7F` (`EmptyImage` 832×1216 `color=8355711` + `ImageCompositeMasked` using `LoadImage`'s MASK as-is — it is already `1 - alpha`, no `InvertMask`) and encode **that** into node `12`. Matches the official fbc example, which mattes onto grey.
- [x] `data/workflows/comfyui_iclight_relight_api.json` -- fix the init latent: node `3` currently samples from `ICLightConditioning.empty_latent`, a zero tensor, at `denoise 0.85`. The official example encodes a **light-shape image** and runs `denoise 1.0`. Use `LightSource` (IC-Light's own node, installed) → `VAEEncode` → `KSampler.latent_image`, `denoise 1.0`. Keep `cfg 2.0`, `dpmpp_2m`, `karras`, `multiplier 0.18215`. Do not touch node `17` (`JoinImageWithAlpha` is correct as-is) and do not enlarge node `7`.
- [x] `src/yt_flow/pipeline/nodes/composite_harmonization.py` -- widen `precompute_relights` eligibility at `:421` from `card_key in STOCK_CAST_KEYS` to any card that passes `_verified_card_asset`, keeping the verified-`location_key` requirement unchanged -- without this the story cannot close: run `8a9a288b` yields **1** eligible pair (`STOCK-d-class`/`containment-chamber`) and every `SCP-049` card — the subject of finding 3's worst frames — is excluded. 8.7 deferred this explicitly as "YAGNI until proven needed"; 10.1's verdict is the proof. See §Design Notes.
- [x] `tests/pipeline/nodes/test_composite_harmonization.py` -- cover the I/O matrix rows that changed: an entity card (`SCP-049`) over a verified location is now computed; an unverified card is still skipped; a shot without `location_key` is still skipped; and add one test that loads the **shipped** `data/workflows/comfyui_iclight_relight_api.json` and asserts it parses, has `LoadImage` at `"1"`/`"2"`, and that its marker matches its verification state -- nothing currently guards the real file.
- [x] LIVE — single-pair probe -- submit one card+plate pair (`SCP-049` × `containment-chamber`) to ComfyUI through `relight_sprite` with the marker temporarily forced in a scratch copy, and compare the returned sprite against the unlit card -- ② of the epic scope. Record the output PNG under `10-1b-live-validation/probe/`. If the sprite is worse than the unlit card, iterate on `denoise`/`multiplier` **inside the JSON only** before proceeding; do not add negative-prompt clauses.
- [x] `data/workflows/comfyui_iclight_relight_api.json` -- set `"ytflow_verified_iclight": true` and rewrite `_ytflow_note` to record what changed and what the probe showed -- only after the probe passes.
- [x] `data/workflows/README-iclight-relight.md` -- replace the stale "nodes 3–9 are a placeholder SDXL chain" section with what the graph actually is, why it was parked, and what fixed it -- ④ of the epic scope.
- [x] LIVE — tier-3 render -- add `YTFLOW_COMPOSITE_HARMONIZATION_TIER=3` to `.env` (no API restart needed: `video.py:2201` instantiates `Settings()` per invocation, and the var is absent from the unit's process env), then `POST /runs/8a9a288b-.../stages/video/gate {"action":"reject"}` -- **not** `/stages/video/retry`, which 409s on a `pending` gate. Confirm from the API log that `relit_pairs_computed` > 0 before extracting frames.
- [x] `_bmad-output/implementation-artifacts/10-1b-live-validation/make_pairs.sh` -- adapt 10.1's script (copy it; do not rewrite from scratch) to parameterize the output dir and the right-hand burn-in label, and produce **two** pair sets on the same six-shot slate: `tier1|tier3` (the primary judgment) and `off|tier3` (against 10.1's third reference point) -- ⑤ of the epic scope.
- [x] `_bmad-output/implementation-artifacts/10-1b-live-validation/measure.py` -- adapt 10.1's script to compare `tier1/` vs `tier3/` instead of `off/` vs `on/`, keeping its control-band method intact, and report card-region colour/luminance agreement with the plate -- every figure must carry its sample band, control band, and noise floor (`gotcha_a-measurement-without-its-sample-band`).
- [x] `_bmad-output/implementation-artifacts/spec-10-1b-card-plate-fusion-iclight-tier3.md` -- record the verdict on finding 3 with the frame pairs cited by path, the measurements with their bands, and either the stage-2 trigger or the reason it is not needed.
- [ ] CONDITIONAL — stage 2 -- only if stage 1's recorded verdict leaves finding 3 open: add a masked low-denoise (0.2–0.3) img2img fusion pass over the composited frame to unify edges and grain. Do not begin before the stage-1 verdict is written.

**Acceptance Criteria:**

- Given run `8a9a288b`'s six-shot slate, when the video stage is re-rendered at tier 3, then `tier1|tier3` frame pairs for all six shots exist on disk under `10-1b-live-validation/pairs/` and are cited in this spec — **the story does not close on tests or wiring** (Epic 10 common AC).
- Given the tier-3 render, when the API log is inspected, then `relit_pairs_computed` is greater than zero and `relit_pairs_failed` is zero or explained per pair.
- Given a relit sprite, when its alpha is compared to the source card's, then the silhouette correlation is positive and the sprite is the same 832×1216 canvas.
- Given the workflow file, when `ytflow_verified_iclight` is `true`, then a live single-pair probe has already returned a sprite judged better than the unlit card, and that probe output is on disk under `10-1b-live-validation/probe/`.
- Given the tier-1 control, when the tier-3 render completes, then `tier1/` and `off/` still hold their original frames — neither was overwritten.
- Given the frame pairs cannot be adjudicated visually, when the verdict is written, then the status is `blocked` and escalated to Jay, never `done`.
- Given `uv run pytest tests/pipeline/nodes/test_composite_harmonization.py tests/pipeline/nodes/test_video_harmonization.py` and `uv run ruff check`, when run after the code change, then both pass.

## Spec Change Log

### 2026-08-08 — pose-blind relight cache key (found during live validation, fixed here)

**Trigger:** verifying the relit sprites against their source cards before adjudicating. The alpha IoU of `assets/relit/SCP-049/containment-chamber/epoch_2.png` against the pose the run actually uses (`hint:7031f483b8`) was **0.66**, not 1.0 — so the sprite contract looked broken. It was not: the sprite is a perfect (IoU 1.0000) relight of a *different pose*, `standing/front`.

**The defect.** Story 8.7 keyed the relight cache on `(card_key, location_key)` and `video.py` substituted on the same 2-tuple. A relight is a function of the **sprite**, not of the character, so a card_key with two poses gets whichever pose was precomputed first — silently swapping the pose in every shot using the other one. Measured on run `8a9a288b`:

| card | relit sprite computed from | substituted onto | silhouette IoU |
|---|---|---|---|
| `STOCK-d-class` | `hint:a40ec9c170` | its 12 `standing` shots | **0.63** |
| `SCP-049-2` | `hint:475c8a9231` | its 12 `standing` shots | **0.78** |
| `SCP-049` | `standing` | its 1 `hint:7031f483b8` shot | 0.66 |

**Three of the six slate shots** (`S00101`, `S00104`, `S00403`) carry `STOCK-d-class/standing`, so the adjudication frames were contaminated — a pose swap would have been read as an IC-Light artifact.

**Why it surfaced now.** Latent under 8.7: the STOCK-only gate made single-pose STOCK cards the only eligible pairs. This story's eligibility widening (a prerequisite for the story closing at all — see Design Notes) made it live.

**Amendment.** Cache key and substitution key are now `(card_variant, location_key)` where `card_variant = card_key__pose__angle` (`:` in `hint:<digest>` folds to `_`). The `assets/relit/` tree and its 4 manifest entries from the contaminated render were purged, and the render was re-run from a cold relight cache.

**KEEP:** the eligibility widening, the two graph fixes (grey matte + `LightSource` init latent), and the `_inject_relight_inputs` fix that strips non-node top-level keys before submission — all three are load-bearing and independently live-verified.

## Review Triage Log

## Design Notes

**Why the parked graph produced washed grey / near-black / blue-monochrome.** Two divergences from kijai's own fbc example (extracted from `example_workflows/ic_light_fbc_example_02.png`), both fixable with nodes already installed:

1. *The foreground latent is 72% black.* ComfyUI's `LoadImage` does `image.convert("RGB")` (`ComfyUI/nodes.py:1727`), discarding alpha. Measured on the actual card: **71.65% of pixels have alpha < 8, and their RGB is exactly `[0,0,0]`**. IC-Light is therefore conditioned on a subject in a black void, and a background-conditioned relight of a void is exactly "near-black". The official example mattes the subject onto `#7F7F7F` first. `LoadImage`'s MASK output is already `1 - alpha`, and `ImageCompositeMasked` pastes `source` where mask == 1 — so grey lands precisely in the transparent region with **no `InvertMask`**.
2. *The init latent is a zero tensor.* `ICLightConditioning`'s third output is `torch.zeros_like(...)`; sampling it at `denoise 0.85` is neither a relight nor a generation. The official example encodes a **light-shape gradient** and runs `denoise 1.0` — the gradient *is* the light direction. `LightSource` (IC-Light's own node) replaces the `CreateShapeMask` + `GrowMaskWithBlur` pair the example uses, which are KJNodes and **not installed** here.

The 2026-08-02 hypothesis in `_ytflow_note` — "IC-Light v1 is photoreal-trained, the cards are flat anime" — may still contribute, but it was never tested against a correctly-wired graph. It is a hypothesis; the two defects above are measurements.

**Why eligibility must widen, and why it is in scope.** `precompute_relights:421` restricts relighting to `STOCK_CAST_KEYS`. Replayed against run `8a9a288b`'s checkpoint, that yields exactly **1** eligible pair:

```
shots=66, with location_key=58, distinct locations=2 (containment-chamber, observation-room) — both verified
card keys in run: SCP-049 (41 shots), STOCK-d-class (19), SCP-049-2 (13)
_verified_card_asset: SCP-049 ✓  SCP-049-2 ✓  STOCK-d-class ✓
>>> ELIGIBLE RELIGHT PAIRS: 1   ('STOCK-d-class', 'containment-chamber')
```

Of the six slate shots, only three carry a `STOCK-d-class` card; the frames 10.1 named as the clearest evidence of finding 3 — `S00403`'s mirror floor, `S00202` — carry **only `SCP-049`**. Shipping tier 3 unwidened would relight one card key and leave the adjudication frames essentially unchanged, which fails the story's own acceptance. 8.7 excluded entity cards as an explicit YAGNI deferral ("their relighting is deferred to runtime, YAGNI until proven needed"), not as an identity-safety rule — all three card keys already pass `_verified_card_asset`, and the "IC-Light needs a reference plate, not a prompt" constraint is satisfied because both locations are keyed and verified. 10.1's verdict is the "proven needed" trigger. The cache key is `(card_key, location_key)`, so widening takes this run from 1 to at most 6 IC-Light jobs, not 66.

**Order matters.** Preserve → fix graph → probe one pair → mark verified → widen → render → adjudicate. The marker must never be flipped in the same change that edits the graph; that is the safety property it exists for.

## Verification

**Commands:**
- `uv run pytest tests/pipeline/nodes/test_composite_harmonization.py tests/pipeline/nodes/test_video_harmonization.py -q` -- expected: all pass, including the new eligibility and shipped-workflow tests.
- `uv run ruff check src/ tests/` -- expected: clean.
- `python3 -c "import json;w=json.load(open('data/workflows/comfyui_iclight_relight_api.json'));print(w['ytflow_verified_iclight'], sorted(w.keys()))"` -- expected: `True` only after the live probe passed.
- `cat /sys/class/drm/card*/device/power_dpm_force_performance_level` -- expected: `high`. Anything else: escalate, do not fix.
- `curl -s localhost:8000/runs/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d | python3 -m json.tool` -- expected before the render: `video` gate `pending`; after: the run re-enters `video`.
- `journalctl --user -u ytflow-api --since "-30min" | grep -E "relit_pairs|IC-Light"` -- expected: `relit_pairs_computed` > 0, no `IC-Light relight failed` lines.
- `10-1b-live-validation/make_pairs.sh` then `PYTHONPATH=src python3 10-1b-live-validation/measure.py` -- expected: six `tier1|tier3` pairs and six `off|tier3` pairs written; measurements print with their bands.

**Manual checks:**
- The six `tier1|tier3` pair JPEGs: does the card in the tier-3 half share the plate's colour cast and light direction? Are the alpha edges still hard? Is the silhouette unchanged? This is the judgment that closes or blocks the story — no metric substitutes for it.
- `10-1b-live-validation/tier1/` and `off/` file mtimes must predate the tier-3 render.

## Dev Agent Record

### Agent Model Used

claude-opus-5[1m] (bmad-dev-auto, 2026-08-08; resumed after a mid-render host reboot)

### VERDICT — finding 3 ("torn out and pasted onto the background")

- [ ] CLOSED
- [x] **MATERIALLY REDUCED where the relight fires; NOT closed run-wide**

Tier 3 fires, produces sprites, and visibly changes the frames. On the four slate shots where an
IC-Light sprite is substituted, the card stops reading as a pasted cutout. It is not closed because
one card key in this run never reaches the relight at all (a manifest integrity drift, below) and
because relight changes *light*, not *edges*.

**Frame pairs** (all six shots, `tier1 | tier3`, same shot ids and timestamps as 10.1):
[`10-1b-live-validation/pairs/`](10-1b-live-validation/pairs/) — and against 10.1's third reference
point, [`10-1b-live-validation/pairs_off/`](10-1b-live-validation/pairs_off/) (`off | tier3`).

| shot | card(s) | relit? | what the pair shows |
|---|---|---|---|
| `scene_001_S00102` | SCP-049 far/right | ✅ | **the clearest case.** Tier 1: a bright blue-white figure glowing against a near-black room — unmistakably pasted. Tier 3: dark, sits *in* the darkness, reads as a figure in an unlit space. |
| `scene_002_S00202` | SCP-049 near/right | ✅ | card stands in the plate's shadow band. Tier 1 keeps a flat mid-blue coat and a bright white mask against shadowed brick; tier 3 drops both to the shadow's level. The one shot where the metric agrees with the eye (closer by ~10.4/channel). |
| `scene_002_S00203` | SCP-049 mid/center | ✅ | coat darkens into the corridor. Better integrated, at some cost to readability. |
| `scene_004_S00403` | SCP-049 near/right **+** STOCK-d-class near/left | ✅ / ❌ | **the in-frame control.** SCP-049 is relit and settles into the dark chamber; STOCK-d-class is not, and stays a saturated orange cutout beside it. The same frame shows both states. |
| `scene_001_S00104` | SCP-049 near/right **+** STOCK-d-class mid/left | ✅ / ❌ | subtle — the plate is bright, so there is little to match. Also the plate 10.1 routed to 10.2 (a painted human fills it). |
| `scene_001_S00101` | STOCK-d-class mid/left | ❌ | **null control.** Card band changed 0.94, i.e. **0.8× the noise floor, 0% of pixels shifted >8 levels** — pixel-identical within encode noise. Confirms the substitution is selective and that nothing global changed between the two renders. |

### The relight fires, measured (AC: `relit_pairs_computed` > 0)

Six pairs computed, zero failed, all cached under `assets/relit/`. ComfyUI execution times:
**346.71 s** for the first prompt (one-time `LoadAndApplyICLightUnet` patch — 1.6 GB of tensors moved
to device/dtype; py-spy confirmed an *active* thread at `ComfyUI-IC-Light/nodes.py:67`, not a
deadlock) then **12.68–13.56 s** each. Cost scales with card-variant × location, not with the 66 shots.

Every sprite is 832×1216 RGBA and preserves **its own** source silhouette at **alpha IoU 1.0000** —
the sprite contract holds for all six.

### Card/plate colour agreement — and why the metric must not be trusted here

`10-1b-live-validation/measure.py`, re-runnable from the repo root. Every figure carries its sample
band, its plate control band, and the card-free noise floor between the two encodes.

| shot | card band | plate control | noise floor | card band changed | vs floor |
|---|---|---|---|---|---|
| `S00102` | x=1330..1520 y=430..800 | x=300..490 | 0.63 | 1.17 | 1.9× |
| `S00101` | x=330..620 y=330..900 | x=1150..1440 | 1.14 | 0.94 | **0.8× (not relit)** |
| `S00203` | x=810..1110 y=280..900 | x=150..450 | 0.84 | 7.00 | 8.3× |
| `S00202` | x=1172..1520 y=180..1020 | x=300..648 | 0.93 | 11.20 | 12.0× |
| `S00104` | x=1250..1600 y=180..1020 | x=700..1050 | 1.21 | 9.90 | 8.1× |
| `S00403` | x=1230..1620 y=180..1020 | x=620..1010 | 4.17 | 9.67 | 2.3× |

**Mean |card − plate| RGB distance across the slate: tier 1 = 20.33 → tier 3 = 21.50.** By that
number tier 3 is *slightly worse*, and by the frames it is clearly better. Both statements are true,
and the disagreement is the interesting result: IC-Light **darkens** a card to match a dim plate, and
a figure standing in shadow *should* be darker than the lit wall behind it — so "mean distance to the
plate band" punishes exactly the correction that makes the frame read. `S00102` is the reduction to
absurdity: the metric moves 0.6 while the frame goes from a glowing cutout to a figure in a dark room.

**This is 10.1 AC7 repeating with a different metric, and it is routed the same way — to 13.2.** The
usable lesson: card/plate agreement must be measured as *consistency of light direction and relative
level*, not as distance between two band means. The paired-frame method with an in-frame control band
remains sound; the statistic on top of it was the wrong one.

### Why one card key was never relit — manifest integrity drift (needs Jay)

`STOCK-d-class/standing_front` is `approved` in `assets/manifest.json` and its file exists, but its
**sha256 does not match**: manifest `41e71b552025c61f…`, on disk `bdc98174ed06f276…`. `verify_asset`
therefore fails and `_verified_card_asset` skips it — correct conservative behaviour, not a bug
introduced here. Consequence: the card in **12 shots**, including three of the six slate cards, is
never relit and stays the bright orange cutout visible in `S00403` and `S00104`.

Re-registering it would let tier 3 cover those shots, but writing approved-asset state is Jay's call
(`gotcha_standing-cards-have-no-approval-gate`), so it is **not** done here.

### What tier 3 does not fix

- **Alpha edges stay hard** in all six pairs. IC-Light re-lights pixels inside the silhouette; it
  cannot soften a cut edge. This is what the conditional stage-2 masked low-denoise fusion pass exists for.
- **No reflections.** `S00403`'s mirror-polished floor reflects every plate object and neither card,
  exactly as 10.1 recorded. Relight cannot add a reflection.
- Both remain open contributors to finding 3.

### Files changed

- `data/workflows/comfyui_iclight_relight_api.json` — grey-matte foreground (nodes `20` `EmptyImage`,
  `21` `ImageCompositeMasked`) and light-shape init latent (`22` `LightSource`, `23` `VAEEncode`),
  `denoise` 0.85 → 1.0; marker set `true` after the live probe.
- `data/workflows/README-iclight-relight.md` — the "nodes 3–9 are an SDXL placeholder" section was stale; replaced.
- `src/yt_flow/pipeline/nodes/composite_harmonization.py` — eligibility widened past `STOCK_CAST_KEYS`;
  new `card_variant()`; cache/lookup key is now `(card_variant, location_key)`;
  `_inject_relight_inputs` strips non-node top-level keys (ComfyUI's `validate_prompt` 500s on the bool marker).
- `src/yt_flow/pipeline/nodes/video.py` — substitution keyed on the card variant.
- `tests/pipeline/nodes/test_composite_harmonization.py` — variant keys, shipped-workflow guard, two pose-swap regressions.
- `tests/pipeline/nodes/test_video_harmonization.py` — variant key in the tier-3 substitution test.

`uv run pytest … -q` → **59 passed**. `uv run ruff check src/ tests/` → clean.

### State left behind — needs Jay's decision

1. **`ytflow-api` runs with `YTFLOW_COMPOSITE_HARMONIZATION_TIER=3` and `YTFLOW_DEPTH_PLACEMENT_ENABLED=true`,
   pinned in a transient unit** (both drop back to code defaults on reboot — as they did during this session).
   Whether tier 3 becomes the production default is Jay's call; 10.1's occlusion head-erasure regression is still open and unrelated to this story.
2. **Run `8a9a288b`'s video gate is `pending`** and `workspace/8a9a288b-…/video.mp4` is now the **tier-3** render (21:51).
   The tier-1 render survives only as `10-1b-live-validation/tier1/video_on.mp4`; the original off-state only as `10-1-live-validation/off/video_off.mp4`.
   The gate was **not** approved — approving asserts the render is good, which overstates a "materially reduced, not closed" verdict.
3. **GPU DPM was reset to `auto` by the reboot and restored to `high` with `sudo`, on Jay's explicit instruction in this session.** It will reset again on the next reboot.

---

### FINAL VERDICT (supersedes the interim verdict above)

The interim verdict was recorded against a **partial** tier-3 render and **mis-sampled** measurement
bands. Both were corrected on Jay's instruction (option A: re-register the drifted asset, then
re-adjudicate). Both corrections are recorded here rather than edited away, because each one changed
the answer.

**Correction 1 — coverage.** `STOCK-d-class/standing_front`'s manifest `sha256` was re-registered to
the file actually on disk (`41e71b55…` → `bdc98174…`, path and `approved` status untouched). Relight
pairs went **6 → 8**, and the card in 12 shots — including three of the six slate cards — became
eligible. That card is the bright orange jumpsuit that dominates `S00101`, `S00104` and `S00403`.

**Correction 2 — the bands were wrong.** `measure.py` had inherited eyeballed x-bands, and two of
them missed the card. `S00101`'s "card band" sat on empty wall at `x=330..620` while the card was at
`x=1459..1612`, so the script reported the card as *unchanged* (0.8× noise floor) for a frame whose
card visibly changed. A second flaw: on the two-card frames the "card-free" control overlapped the
card and inflated the noise floor to 5.3–5.5. `measure.py` now **derives** the card band from the
tier1↔tier3 diff footprint and clips the control to the genuine card-free gap; every band is printed
with its figure. Noise floors dropped to **0.70–2.29**.

**Verdict: finding 3 is substantially reduced, and now measurable.**

| shot | card band (derived) | plate control | noise floor | card changed | vs floor | card→plate distance |
|---|---|---|---|---|---|---|
| `S00102` | x=1264..1320 y=430..800 | x=1168..1224 | 0.70 | 28.94 | **41.5×** | **closer by 29.0 / 29.6 / 26.6** |
| `S00101` | x=1459..1612 y=330..900 | x=1266..1419 | 0.75 | 44.28 | **58.8×** | **closer by 61.7 / 41.1 / 27.7** |
| `S00203` | x=894..1042 y=280..900 | x=706..854 | 0.87 | 12.89 | 14.9× | further by 12.5 / 12.7 / 10.2 |
| `S00202` | x=1238..1371 y=180..1020 | x=1065..1198 | 2.29 | 23.55 | 10.3× | further by 22.0 / 21.9 / 21.8 |
| `S00104` | x=541..1376 y=180..1020 | x=1416..1920 | 0.79 | 11.28 | 14.3× | further by 8.2 / 5.5 / 3.6 |
| `S00403` | x=515..1369 y=180..1020 | x=1409..1920 | 1.17 | 15.73 | 13.4× | **closer by 15.8 / 10.0 / 5.3** |

**Mean |card − plate| RGB distance across the slate: tier 1 = 34.52 → tier 3 = 27.66 — a 20% reduction.**
Every shot's card region moved 10.3–58.8× the encode noise floor, so the relight demonstrably acted
on all six.

The three "further" rows are not counter-evidence, and the reason is worth keeping: on those frames
the derived control band lands on a **lit** part of the plate while the card stands in **shadow**. A
figure in shadow *should* be darker than a lit wall, so "distance between two band means" penalises
the correct answer. `S00202` is the clearest instance — the card sits in the plate's shadow wedge and
the control sits in its light shaft. **Mean-distance-to-a-plate-band is therefore a usable aggregate
but a misleading per-shot verdict**, and that is the refined form of the axis handed to 13.2: measure
*agreement of light direction and relative level*, not distance between band means.

**What the frames show** (`10-1b-live-validation/pairs/`):
- `S00102` — tier 1 a blue-white figure glowing in a near-black room; tier 3 a figure standing in the dark. Decisive.
- `S00101` — the orange jumpsuit drops from saturated primary to a muted, dimmer figure that belongs in the cell block. `pairs/_zoom_S00101_head.jpg` confirms **line art and facial features survive**: the change is a shadow across the upper face consistent with the plate's door light, not a loss of detail.
- `S00403` — both cards now share the chamber's light level; in the previous partial render the orange card was untouched beside a relit SCP-049.
- `S00202`, `S00203` — card settles into the shadowed plate.
- `S00104` — mildest; a bright plate leaves little to match, and it is the plate 10.1 routed to 10.2.

**Still not fixed by tier 3, and still contributing to finding 3:**
- **Hard alpha edges** in all six pairs. IC-Light re-lights pixels inside the silhouette; it cannot soften a cut edge.
- **No reflections** — `S00403`'s mirror floor reflects every plate object and neither card.

Both are precisely what the conditional stage-2 masked low-denoise fusion pass targets. Stage 1 is
recorded; **stage 2 was not started** — Jay's decision after seeing these frames.

## Senior Developer Review (AI)

Adversarial review of the diff against `5ce57ae`. The key change itself came back clean — all six
call sites converted, no unbound `card_key`, no path escape, non-fatality intact, the JSON acyclic
with node 21's mask polarity and node 17's original-alpha wiring both verified against the installed
ComfyUI source. The serious findings were elsewhere, and they share a cause: **this diff is the first
change that ever lets tier 3 execute, so every latent defect on that path went live at once.**

### Fixed in this pass

**HIGH — ComfyUI input-namespace collision could relight one character from another's sprite.**
`upload_image` POSTs with `overwrite=true` and ComfyUI keys its input dir on the **basename**, while
`LoadImage` reads the file at node-execution time, not submit time. Card basenames are not unique —
measured: `front_candidate_1.png`, `back_candidate_1.png`, `side_candidate_1.png` and
`three_quarter_candidate_1.png` are each the basename of **8 different characters' cards**. With
`_RELIGHT_CONCURRENCY = 3` the last upload wins for every job still queued, so a pair could be relit
from the wrong character and then cached and **auto-approved** under the right one's key — the same
identity-swap class this story exists to fix, one layer down. It did not fire in this run (verified:
every cached sprite matches its own source at alpha IoU 1.0000) purely because of dict ordering.
Fixed: `_upload_name()` qualifies the upload with a digest of the resolved source path.

**HIGH — a non-832×1216 card would have been silently corrupted.** The graph's grey matte (node 20)
and light-source gradient (node 22) shipped hardcoded at 832×1216, but `LoadImage` loads a card at
its native size, and **8 approved cards are 1664×928** (`SCP-1471/*`, `SCP-682/*`). Before this story
the init latent was `zeros_like(foreground)`, so the canvas always followed the card; introducing a
generated init latent removed that property. The failure is silent: `ICLightConditioning`
center-crops the concat latent to the noise shape while `JoinImageWithAlpha` re-attaches the *full*
original mask, so the result still passes `has_alpha()` and gets cached and auto-approved. Fixed:
`_inject_relight_inputs` now injects the card's real dimensions (read stdlib-only via a new
`domain/png.dimensions()`) into both generated canvases.

Both fixes were **live-verified after the adjudication**, and neither changes this run's evidence —
every card in run `8a9a288b` is 832×1216, so the injected size equals the value that was hardcoded,
and the relit cache was already warm:

```
SCP-049/standing_front   (832,1216) -> relit (832,1216)  alpha=True
SCP-1471/standing_front  (1664,928) -> relit (1664,928)  alpha=True, alpha IoU 1.0000, dL -4.8
```

Also fixed: the shipped-workflow marker test was tautological (it branched on the file's current
value and passed either way, giving zero protection for the one bit this story flipped) — split into
a positive assertion plus a real rejection test; a `logger.warning` that always printed `None` for
the variant because `card_variant()` raises before the assignment binds; and a README line still
naming the old `{card_key}` cache path.

New regression tests: upload-name disambiguation, canvas-size injection (both directions), and — the
gap the review named — **two poses of one `card_key` in a single shot each receiving their own sprite
at the `video.py` substitution site**, not just in `precompute_relights`. Full targeted suite:
**1357 passed, 1 skipped**; `ruff` clean.

### Accepted, not fixed — deliberately out of this story's blast radius

- **Node 15 `DetailTransfer` still reads node `"1"`, the black-void card.** The same defect the node-12
  fix addressed: mode `add` computes `(source − blur(source)) + blur(target)`, so the void drags
  `blur(source)` toward black at the silhouette boundary and the high-frequency detail is transferred
  from the wrong reference. Rewiring it to node `"21"` is a one-line change — **but it changes every
  relit sprite**, which would invalidate the frame pairs adjudicated above. Deferred so the fix gets
  its own before/after gate rather than silently re-deciding a closed comparison.
- **The re-registered `sha256` did not bump `style_epoch`.** `RelightCache`'s only invalidation signal
  is the epoch, so a relight computed from either version of that sprite is now indistinguishable and
  will be served indefinitely. Re-approval arguably ought to bump the epoch; that is asset-lifecycle
  policy and Jay's call. Worth recording: this stale hash — not the `STOCK_CAST_KEYS` gate alone — is
  the second reason run `8a9a288b` had only one eligible pair before this story.
- The `shipped_workflow` fixture resolves a relative path through `Settings()`, so it follows a
  `YTFLOW_ICLIGHT_COMFYUI_WORKFLOW_PATH` override and needs repo-root cwd.


---

## FINAL DISPOSITION — ⛔ REJECTED (Jay, 2026-08-09)

**This story did what it set out to do, and the answer was no.** Harmonization tier 3
(IC-Light) was activated for the first time since Story 8.7, six relit sprites were computed
and cached, the video stage was re-rendered, and the six-shot slate was adjudicated. Jay
watched the result and判定ed **"나빠졌다"** — worse than tier 1.

Closing this `done` would be false: the story's own exit condition was that finding 3 be shown
gone in frames, and the frames show it is not. Closing it `rejected` is the accurate record,
and under Epic 10's charter — *"어느 스토리가 어떤 시각 결함을 실제로 없앴는지 추적 가능하게 만드는 것"* —
a measured negative IS this story's deliverable.

**What tier 3 does and does not do, settled by frames:** it matches the card's light level to
the plate (card/plate colour distance 34.52 → 27.66, every shot moving 10.3–58.8× the encode
noise floor) but **cannot touch the alpha edge**, so the card still reads as pasted. The
remaining causes are edge hardness and the absence of reflections — neither is a lighting
problem, which is why a lighting fix could not close finding 3.

**Superseded by Story 10.1c.** Jay's direction after this rejection: stop refining an overlay
and re-create the frame from background + card + a natural-language placement instruction.
That is a different architecture, a different model, and it deletes the placement layer this
story was built on — a new story, not a continuation.

**What survives and must not be re-litigated:**
- The IC-Light fbc graph works (`data/workflows/comfyui_iclight_relight_api.json`, marker `true`,
  6 pairs at 13 s each after a one-time 346 s unet patch). Kept, not deleted.
- Three real defects fixed here are independent of the rejected direction and stay:
  pose-blind relight cache key, ComfyUI upload-name collision, and canvas size not following
  a non-832×1216 card. All three would corrupt any future ComfyUI path.
- Evidence: `10-1b-live-validation/` — `off/`, `tier1/`, `pairs/`, `pairs_off/`, `fusion-probe/`,
  `fusion-slate-055/`, `recompose-probe/`, `recompose-qwen/`, plus `measure.py` with its bands.
  This is the "why not this way" record for the composite-then-refine family.
