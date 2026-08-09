---
title: 'Story 10.3 — Art-style consistency + LoRA/checkpoint alignment (findings 10·12)'
type: 'bugfix'
created: '2026-08-09'
status: 'done'
baseline_revision: 'f84df9a'
final_revision: '42175d3'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/10-1-grounding-composite-live-verification.md'
warnings: ['oversized', 'dirty-worktree-unrelated-10-1b']
---

<intent-contract>

## Intent

**Problem:** Every SDXL image workflow chains two LoRAs onto AnimagineXL v3.1 (`4 → 10 horror@0.6 → 11 darkness_xl_v2@0.5`), and each fresh model patch emits ~342 `lora key not loaded` plus ~292 `ERROR lora ... is invalid for input of size` — so the intended style control is mostly not applied, and shots drift in art style (Jay: "이상한 화풍", "갑자기 애니메이션 캐릭터"). **The recorded root cause in `epics.md:1548` is inverted and must be corrected**: `darkness_xl_v2` is genuine SDXL whose shapes match the checkpoint exactly (`output_blocks.2.0.in_layers.2` = `[1280,1920,3,3]` in both; `output_blocks.3.1...attn1.to_k` = `[640,640]` in both, not the claimed 1280), while `horror.safetensors` is the SD1.5-layout file (attention in `down_blocks_0`, single `lora_te_*` text encoder — SDXL has none of the first and two of the second).

**Approach:** Empirically attribute the two error classes by loading each LoRA alone against the checkpoint, remove only the LoRA(s) proven to misapply, and prove the art-style change with same-prompt/same-seed before/after frames on Story 10.1's existing 6-shot slate.

## Boundaries & Constraints

**Always:**
- Verdicts come from **actual tensor shapes and live ComfyUI load logs**, never from filenames or from the prior write-up. Where evidence contradicts `epics.md`, correct `epics.md`.
- Before/after frames use the **identical prompt, negative prompt, seed, resolution, sampler, scheduler, steps and cfg**; only the LoRA chain differs.
- Each measurement ships with its command and raw counts in the evidence dir, so it can be recomputed.
- Fix all workflow JSONs that chain the same broken loader — leaving 4 of 5 broken while calling the story done is not a fix.
- Changes to workflow JSON only rewire node graphs; `image.py` injects into nodes `"6"`/`"7"` and every `KSampler` by class, so those must keep working unchanged.

**Block If:**
- The after-frames are judged **worse** than the before-frames. Ship nothing, HALT with the frame pairs as evidence — a metric win the viewer would reject loses (Epic 10 rule).
- The only viable remedy requires **downloading a new model/LoRA** from the network.
- The remedy would require **regenerating already-approved character cards** or editing `assets/manifest.json`.
- ComfyUI is unreachable or cannot complete the render slate, so no frame evidence can exist.

**Never:**
- Do not touch negative prompts (negative-prompt inflation has wrecked renders twice).
- Do not swap the checkpoint, change steps/cfg/sampler/resolution, or tune LoRA strengths as a substitute for fixing the load.
- Do not chase the render-slowness question — `epics.md` already records that removing the LoRA did not resolve it; it is a separate problem.
- Do not regenerate, re-approve or delete any existing card/plate asset.
- Do not start any other Epic 10 story. Do not commit the unrelated 10.1b work in the working tree.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Corrected workflow loaded | `comfyui_sdxl_anime_lora_workflow_api2.json` after edit | `_load_workflow` accepts it; nodes `6`/`7` are `CLIPTextEncode`; every `KSampler` receives the seed | `ValueError` if `6`/`7` missing — must not happen |
| Prompt injection unchanged | template + prompt/negative/seed | `6.inputs.text`, `7.inputs.text`, `3.inputs.seed` set; graph submits and returns an image | Submission error surfaces as stage `error` (existing path) |
| LoRA node removed | KSampler/CLIPTextEncode reference a deleted node id | No node reference points at a removed id anywhere in the graph | Dangling reference = ComfyUI 400 on `/prompt`; must be caught by the structural test, not at runtime |
| Clean model patch | corrected workflow submitted to live ComfyUI | Zero `lora key not loaded` and zero `ERROR lora ...` lines during that patch | Any remaining line is a finding, recorded not suppressed |

</intent-contract>

## Code Map

- `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` -- main shot workflow; `settings.comfyui_workflow_path` default and pinned in `.env:52`. Nodes 10/11 are the LoRA chain.
- `data/workflows/comfyui_character_multi_angle_api.json` -- card generation; same pair, `darkness_xl_v2@0.3`.
- `data/workflows/comfyui_location_plate_api.json` -- background plates; same pair.
- `data/workflows/comfyui_sdxl_anime_lora_layered_api.json`, `..._layered_inspyrenet_api.json` -- retired layered variants; same pair. Fix for consistency, not exercised at runtime.
- `src/yt_flow/pipeline/nodes/image.py:46-47,108,143-156` -- hardcodes only node ids `"6"`/`"7"`; seeds every node with `class_type == "KSampler"`. **No code references node `10` or `11`** of these workflows.
- `scripts/seed_location_plates.py:57` -- `MODEL_NODE = "11"` but targets `comfyui_location_plate_api.json`; if that file's node 11 is removed, this constant must move to the new model source.
- `tests/pipeline/nodes/test_image.py` -- uses a synthetic 2-node workflow; no test guards the real workflow JSONs.
- `~/workspaces/ComfyUI/models/loras/{horror,darkness_xl_v2}.safetensors` -- the two LoRAs. `~/workspaces/ComfyUI/user/comfyui.log` -- load-error source.
- `workspace/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d/images/*_done.json` -- 66 sidecars with `image_prompt` / `negative_prompt` / `seed`; the replay source.
- `_bmad-output/implementation-artifacts/10-1-live-validation/` -- Story 10.1's 6-shot slate to reuse.

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/implementation-artifacts/10-3-live-validation/probe_lora.py` -- new throwaway probe: submit a minimal render (512×512, 4 steps) against AnimagineXL v3.1 in four LoRA configs (both / horror-only / darkness-only / none), capturing `~/workspaces/ComfyUI/user/comfyui.log` line counts per config -- attributes each error class to a specific file empirically, replacing the inverted claim in `epics.md`.
- [x] `_bmad-output/implementation-artifacts/10-3-live-validation/render_slate.py` -- new throwaway renderer: replay the 6 Story-10.1 slate shots at production settings (1344×768, 30 steps, cfg 7.5, dpmpp_2m/karras) from their sidecar `image_prompt`/`negative_prompt`/`seed`, once with the current chain and once with the corrected chain -- produces the only evidence that closes this story.
- [x] `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` -- remove the LoRA node(s) the probe convicts and rewire the consumers (`3.model`, `6.clip`, `7.clip`) to the surviving model/clip source -- restores the checkpoint's own style as the actual, non-silently-degraded style.
- [x] `data/workflows/comfyui_character_multi_angle_api.json`, `comfyui_location_plate_api.json`, `comfyui_sdxl_anime_lora_layered_api.json`, `comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` -- apply the identical rewire -- the same broken loader in the card and plate generators is the cross-layer half of "화풍 일관성".
- [x] `scripts/seed_location_plates.py` -- update `MODEL_NODE` if the plate workflow's node 11 is removed -- otherwise its IPAdapter strip targets a dead id. **Checked: node 11 is the *surviving* loader (`darkness_xl_v2`), node 10 (`horror`) was the one removed, so `MODEL_NODE = "11"` still resolves and the file is unchanged.**
- [x] `tests/test_workflow_definitions.py` -- new test asserting, for every `data/workflows/comfyui_*_api.json`: no `LoraLoader` names a LoRA outside an allowlist, every node input reference points at an existing node id, and `api2` keeps `6`/`7` as `CLIPTextEncode` plus at least one `KSampler` -- api2 is currently the only major workflow with no structural guard, and a dangling reference is otherwise only discoverable as a live 400.
- [x] `_bmad-output/planning-artifacts/epics.md` -- correct the Story 10.3 root-cause sentence to the measured attribution -- the current text sends the next reader after the wrong file.
- [x] `_bmad-output/implementation-artifacts/10-3-live-validation/README.md` -- record shapes, per-config error counts, the frame verdict, the recompute commands, and the ③ judgment on whether a shot-to-shot style-drift axis belongs in 13.2 -- Epic 10 closes on recorded evidence, not on a green suite.

**Acceptance Criteria:**
- Given the two LoRA files, when their tensor shapes are compared against `AnimagineXL_v31.safetensors`, then the report states for each whether its layout matches, citing at least three concrete key/shape pairs per file.
- Given a fresh ComfyUI model patch with the corrected workflow, when the log window for that patch is counted, then `lora key not loaded` and `ERROR lora ... invalid for input of size` are both zero, versus the non-zero baseline counts recorded for the same probe with the current workflow.
- Given the 6 slate shots replayed at identical prompt/negative/seed/sampler settings, when before and after images are placed side by side, then paired comparison images exist on disk for all 6 and the README states a per-shot art-style verdict.
- Given the corrected workflow JSONs, when the structural test runs, then no node input references a missing node id in any workflow file and `api2` still satisfies `_load_workflow`'s contract.
- Given a live submission of the corrected `api2` workflow with an injected prompt and seed, when it completes, then an image is returned (proving the rewire did not break the graph).
- Given the after-frames are judged worse than the before-frames, when the verdict is reached, then no workflow change is committed and the run halts as `blocked` with the pairs as evidence.

## Spec Change Log

## Review Triage Log

### 2026-08-09 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 15: (high 0, medium 5, low 10)
- defer: 4: (high 0, medium 3, low 1)
- reject: 8: (high 0, medium 0, low 8)
- addressed_findings:
  - `[medium]` `[patch]` The LoRA allowlist matched only `class_type == "LoraLoader"`, so `LoraLoaderModelOnly` (already live in `comfyui_shot_recompose_qwen_api.json`) bypassed it entirely — re-adding `horror.safetensors` through that class would have shipped green. Now matches any `LoraLoader*` class.
  - `[medium]` `[patch]` The allowlist was a global filename set while its own contract is per-base-model; an SDXL-verified LoRA in a Qwen graph (or vice versa) passed. Re-keyed to `{base model: {loras}}`, resolving the base from `ckpt_name`/`unet_name`.
  - `[medium]` `[patch]` `used <= ALLOWED_LORAS` passes vacuously on the empty set, so deleting node 11 or re-pointing `KSampler.model` to node 4 left the style LoRA silently gone with a green suite. Added a model-chain walk asserting the sampler still passes through a LoraLoader in `api2` and the plate workflow, plus a guard on the node id `scripts/seed_location_plates.py` hardcodes.
  - `[medium]` `[patch]` The documented before-leg command pointed at the live workflow file, which no longer chains `horror` — re-running it would overwrite `before/` with post-fix frames and silently turn the A/B into after/after. Preserved the pre-fix graph as `before/workflow_before.json` and repointed the command and docstring at it.
  - `[medium]` `[patch]` Stale re-add vectors outside the story's own files: `epics.md:332` and `prd.md:176` still declared the horror+darkness stack as the workflow baseline, and `README-character-multi-angle.md` documented node 10 as part of the chain, listed `horror.safetensors` as a required model, and carried a "Known limitation" section blaming both LoRAs and calling the errors pre-existing. All four corrected; `README-layered-assets.md` model table too.
  - `[low]` `[patch]` `probe_lora.py`'s cache heuristic keyed on raw new-log-line count, which a fresh seed always makes non-zero — a cache-served LoRA patch could read as a genuine `0 + 0`. Re-keyed to requiring a `Requested to load` line in the window.
  - `[low]` `[patch]` The probe summary table showed only the first run per config and dropped both the cached flag and the error string, so a cached or failed run printed as a clean `0 0` in the table that was copied into `epics.md`. Now prints every run with an explicit `ok`/`CACHED`/`ERROR` status.
  - `[low]` `[patch]` `probe_lora.py` returned 0 unconditionally and swallowed submission exceptions, so ComfyUI being offline produced an all-zero table and a success exit. Now exits non-zero if any run errored or was cache-served.
  - `[low]` `[patch]` Neither script guarded log rotation; a truncated `comfyui.log` would make `read_bytes()[offset:]` empty and report a false zero. Both now abort if the log shrank below the captured offset.
  - `[low]` `[patch]` `render_slate.py` iterated all top-level keys and called `.get()` on them, crashing with `AttributeError` on the five workflows carrying `ytflow_verified_*`/`_ytflow_note` scalars. Now filters to dicts carrying `class_type`, and rejects a workflow whose node `6` is not the positive `CLIPTextEncode`.
  - `[low]` `[patch]` `render_slate.py`'s sidecar path was cwd-relative, so the documented replay only worked from the repo root. Anchored to `__file__`.
  - `[low]` `[patch]` `render_slate.py` indexed `sys.argv[1:3]` unguarded; now prints its usage docstring instead of an `IndexError`.
  - `[low]` `[patch]` The dangling-reference check required `isinstance(value[0], str)`, silently skipping links whose node id serialises as an int. Now compares `str(value[0])`.
  - `[low]` `[patch]` `nodes()` accepted any dict-valued top-level key as a node, making a future dict-shaped metadata key both scannable and a valid link target. Now requires `class_type`; the glob widened from `comfyui_*_api*.json` to `*.json` so a renamed workflow cannot escape the guards.
  - `[low]` `[patch]` The test docstring claimed the runtime strips provenance markers before submitting, which is true of the harmonization/fusion/recompose nodes but not of `image.py` — acting on it would have got every shot render rejected. Reworded, and the README now records the measured `73`-per-patch figure against the Intent block's pre-measurement `~292` estimate.

## Design Notes

**Why node removal rather than strength=0:** ComfyUI still loads and patches at strength 0, so the error storm and its load cost remain. Deleting the node and rewiring is the only change that actually stops the failed patching.

The rewire is mechanical — with both loaders removed, node 4's outputs feed the consumers directly:

```json
"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "...", "clip": ["4", 1]}},
"7": {"class_type": "CLIPTextEncode", "inputs": {"text": "...", "clip": ["4", 1]}},
"3": {"class_type": "KSampler",       "inputs": {"model": ["4", 0], ...}}
```

If only one loader is convicted, keep the survivor and re-chain it directly off node 4 instead.

**Why the slate and not fresh prompts:** the 66 sidecars carry the exact `image_prompt`/`negative_prompt`/`seed` of the run Jay watched, so replay isolates the LoRA chain as the single variable. A fresh scenario run would need LLM keys and would confound the comparison.

**Sequencing note:** ComfyUI is a shared single-queue resource and another session's 10-1b probe is currently queued on it. Submit serially and do not restart the `ytflow-comfy` unit.

## Verification

**Commands:**
- `uv run pytest tests/test_workflow_definitions.py tests/pipeline/nodes/test_image.py -q` -- expected: all pass
- `uv run ruff check src tests scripts` -- expected: clean
- `python3 -c "import json,glob;[json.load(open(f)) for f in glob.glob('data/workflows/comfyui_*_api.json')]"` -- expected: every workflow still parses
- `grep -c "lora key not loaded\|ERROR lora" ~/workspaces/ComfyUI/user/comfyui.log` before/after the corrected probe -- expected: the corrected-config window contributes 0

**Manual checks:**
- `_bmad-output/implementation-artifacts/10-3-live-validation/pairs/` contains one before/after pair per slate shot, at production resolution, visibly rendered from the same seed (composition recognisably the same shot).
- `README.md` states the per-file shape verdict, the four per-config error counts, and an explicit art-style verdict per shot.

## Dev Agent Record

**Outcome: SHIPPED.** `horror.safetensors` convicted by live probe and removed from all five
workflows; `darkness_xl_v2.safetensors` proven clean and kept. After-frames better-or-equal on all
six slate shots — the `Block If` "after-frames judged worse" condition did **not** trigger.

### Probe result (512×512, 4 steps, per-submission log window)

| config | `lora key not loaded` | `ERROR lora ... invalid for input of size` |
|---|---:|---:|
| `both` (horror@0.6 → darkness@0.5) | 342 | 73 |
| `horror_only` | 342 | 73 |
| `darkness_only` | 0 | 0 |
| `none` | 0 | 0 |

`horror_only` reproduces `both` exactly. The `darkness_only` zero is a real zero, not a cached
no-op: configs were interleaved with `none` runs to evict the loader from ComfyUI's execution cache,
and that window contains `Requested to load SDXLClipModel` + a full `Requested to load SDXL`
(4897.05 MB) that the neighbouring `none` windows do not.

Shape evidence agrees: `horror` is diffusers-named with one `lora_te_*` encoder and 72
`down_blocks_0_attentions_*` tensors (SDXL has neither), and its
`up_blocks_0_resnets_0_conv1` delta is `[1280, 2560, 3, 3]` = 29,491,200 — the exact size in the log
error against the checkpoint's `[1280, 1920, 3, 3]`. `darkness_xl_v2` matches the checkpoint on all
four sampled keys, including `output_blocks_3_1...attn1_to_k` = `[640, 640]` (the spec's own note
was right and `epics.md`'s "expects 1280" was wrong).

### Slate verdict (same prompt / negative / seed / 1344×768 / 30 steps / cfg 7.5 / dpmpp_2m+karras)

before-render log window: 342 + 438 errors. after-render: **0 + 0**, all six images returned.

| shot | verdict |
|---|---|
| `scene_001_S00101` | better (small) — crisper panel geometry, legible door frame, warmer floor spill |
| `scene_001_S00102` | **better** — formless starburst glare becomes an actual drawn pendant lamp |
| `scene_001_S00104` | better (small) — coherent tray, cleaner edges |
| `scene_002_S00202` | equal/better — firmer mortar and an added ledge instead of soft blur |
| `scene_002_S00203` | **better** — the stray anime face in the grate (finding 12 itself) is gone |
| `scene_004_S00403` | equal/better — nonsense dome replaced by coherent glass column |

Overall: 4 better, 2 equal-or-better, 0 worse. The after-set is also more internally consistent —
the two before-frames that fell outside the set's own look have no after-side counterpart.

### Files changed

- `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json`
- `data/workflows/comfyui_character_multi_angle_api.json`
- `data/workflows/comfyui_location_plate_api.json`
- `data/workflows/comfyui_sdxl_anime_lora_layered_api.json`
- `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json`
  (all five: node `10` deleted, node `11` re-chained to `["4", 0]` / `["4", 1]`; every other node id
  unchanged, so `image.py`'s `"6"`/`"7"` + `KSampler` injection is untouched)
- `tests/test_workflow_definitions.py` (new — dangling-reference sweep, LoRA allowlist, api2 contract)
- `_bmad-output/planning-artifacts/epics.md` (Story 10.3 paragraph only)
- `_bmad-output/implementation-artifacts/10-3-live-validation/` (new — probe, renderer, before/after
  frames, pairs, log windows, README)

Nothing was committed; the unrelated Story 10.1b work in the tree was left alone.

### Verification

- `uv run pytest tests/test_workflow_definitions.py tests/pipeline/nodes/test_image.py -q` → **73 passed**
- `uv run ruff check src tests scripts` → **All checks passed** (also clean over the evidence dir)
- JSON parse sweep of `data/workflows/comfyui_*_api.json` → all 10 parse
- Live: 6/6 corrected-workflow submissions returned an image, 0 LoRA errors in their log window

### Deliberately not done

- **Render slowness** — out of scope by the Never tier; measured incidentally as unchanged
  (15–18 s/shot before and after) and recorded as still unresolved.
- **Style-drift axis for 13.2** — judged and written up (recommendation: **no, not now**, with a
  named re-open condition), not implemented, per spec item ③.
- **`scripts/seed_location_plates.py`** — inspected, no change needed (`MODEL_NODE = "11"` survives).
- **`data/workflows/comfyui_fusion_img2img_api.json`** — its `_ytflow_note` repeats the inverted
  claim about `darkness_xl_v2`, but it is another session's in-flight 10.1b file and was left
  untouched; flagged in the evidence README for its owner.
- No LoRA strength tuning, no checkpoint/sampler/resolution change, no negative-prompt edit, no asset
  regeneration, no downloads, no ComfyUI unit restart.

## Auto Run Result

Status: **done**

### Implemented change

`horror.safetensors` was removed from all five SDXL ComfyUI workflows and `darkness_xl_v2.safetensors`
re-chained directly onto the checkpoint. The attribution recorded in `epics.md` was **inverted** and is
now corrected from live measurement: loading each LoRA alone against AnimagineXL v3.1 gives
`horror_only` = 342 `lora key not loaded` + 73 `ERROR lora ... invalid for input of size`,
`darkness_only` = 0 + 0. Shape evidence agrees — `horror` is SD1.5-layout (diffusers naming, a single
`lora_te_text_model_*` encoder, attention in `down_blocks_0`), while `darkness_xl_v2` matches the
checkpoint on every sampled key.

Story 10.1's 6-shot slate was replayed at production settings from run `8a9a288b`'s sidecars
(identical prompt / negative / seed / 1344×768 / 30 steps / cfg 7.5 / dpmpp_2m+karras; the LoRA chain
was the only variable). Before: 342 + 438 errors. After: **0 + 0**, with 7 `Requested to load SDXL`
lines proving a real patch rather than a cached no-op. Six before/after pairs and a contact grid are on
disk.

### Files changed

- `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` — node 10 (`horror`) deleted, node 11 rechained to node 4
- `data/workflows/comfyui_character_multi_angle_api.json` — same rewire (cards)
- `data/workflows/comfyui_location_plate_api.json` — same rewire (plates)
- `data/workflows/comfyui_sdxl_anime_lora_layered_api.json`, `..._layered_inspyrenet_api.json` — same rewire (retired variants)
- `data/workflows/README-character-multi-angle.md` — chain diagram, required-models table, and the "Known limitation" section that blamed both LoRAs, replaced with the measured attribution
- `data/workflows/README-layered-assets.md` — required-models table
- `tests/test_workflow_definitions.py` — **new**: per-base-model LoRA allowlist, dangling-reference check, `api2` node-id contract, style-LoRA-reaches-sampler guard
- `_bmad-output/planning-artifacts/epics.md` — Story 10.3 root cause corrected; the stale workflow-baseline line at 332 corrected
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md` — OQ-2's stale stack marked superseded
- `_bmad-output/implementation-artifacts/deferred-work.md` — 4 entries
- `_bmad-output/implementation-artifacts/epic-10-context.md` — regenerated (was stale against `epics.md`)
- `_bmad-output/implementation-artifacts/10-3-live-validation/` — **new**: probe, slate renderer, preserved pre-fix graph, raw log windows, before/after frames, pairs, README

`scripts/seed_location_plates.py` needed no change — its `MODEL_NODE = "11"` is the surviving loader.

### Review findings

15 patches applied (5 medium, 10 low), 4 deferred, 8 rejected, 0 intent gaps, 0 spec defects. The
medium patches all concerned the regression guard and evidence integrity rather than production
behaviour: `LoraLoaderModelOnly` bypassed the allowlist, the allowlist was global where its contract is
per-base-model, it passed vacuously once the LoRA was deleted, the documented before-leg command would
have silently overwritten the before-frames with post-fix renders, and four documents outside this
story still advertised the removed LoRA as the baseline. Details in the Review Triage Log.

### Verification performed

- `uv run pytest tests/test_workflow_definitions.py tests/pipeline/nodes/test_image.py tests/test_seed_location_plates.py -q` → **100 passed**
- `uv run ruff check src tests scripts _bmad-output/implementation-artifacts/10-3-live-validation` → **All checks passed**
- JSON parse sweep over `data/workflows/*.json` → all parse; independent dangling-reference scan → none
- Live: 6/6 corrected-workflow submissions returned an image with 0 LoRA errors
- Frames adjudicated by direct inspection of `pairs/_contact_grid.jpg`: 0 of 6 shots worse, so the
  Block If did not trigger

### Residual risks

- The art-style improvement is **real but modest**. The clearest wins are S00102 (a formless glare
  becomes a drawn pendant lamp) and S00203 (a stray artifact in the grate disappears); the rest are
  marginal. The louder defect in the slate — whole anime figures painted into the background plates of
  S00104 and S00403 — is untouched by this story and belongs to **10.2**.
- Only `api2` has frame evidence; the card, plate and layered rewires are unmeasured aesthetically.
- Approved cards and plates were rendered with the old chain, so a newly generated angle for an
  existing character will not style-match its siblings.
- This reverses Story 8.15's explicit "do not remove the `horror` LoRA" constraint; 8.15's
  `STOCK_NEGATIVE` suppression may now be compensating for a bias that no longer exists.
- Render slowness is untouched and unresolved (15–18 s/shot before and after).
