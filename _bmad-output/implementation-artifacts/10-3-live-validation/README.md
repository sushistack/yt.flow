# 10.3 Live Validation — LoRA/checkpoint alignment and the art-style verdict

Evidence for Story 10.3 (Jay findings 10·12: "이상한 화풍의 이미지가 나오는 경우가 있음",
"갑자기 애니메이션 캐릭터가 나옴"). Measured 2026-08-09 against the live ComfyUI at
`http://127.0.0.1:8188` (v0.12.3, ROCm), checkpoint `AnimagineXL_v31.safetensors`.

**Verdict: `horror.safetensors` is the SD1.5-layout file and is the sole source of both error
classes. `darkness_xl_v2.safetensors` is genuine SDXL and loads clean. `horror` removed from all
five workflows; `darkness_xl_v2` kept and re-chained directly onto the checkpoint. After-frames are
better-or-equal on all six slate shots — nothing worse — so the change ships.**

> The root cause recorded in `epics.md:1548` was **inverted**: it convicted `darkness_xl_v2` and
> claimed the checkpoint "expects 1280" at `output_blocks_3_1...attn1_to_k`. Both halves are wrong —
> that checkpoint tensor is `[640, 640]` and `darkness_xl_v2` supplies exactly `[640, 640]`.
> `epics.md` has been corrected to the measured attribution.

---

## 1. Per-file shape verdict

Recompute all of the below with:

```
uv run python _bmad-output/implementation-artifacts/10-3-live-validation/probe_lora.py --shapes
```

Raw output is saved at `shapes.txt`. `delta` = the rank-collapsed product `up @ down`, i.e. the
tensor ComfyUI tries to add to the checkpoint weight.

### `horror.safetensors` — **MISMATCH (SD1.5)**

1050 tensors, `__metadata__` empty, **diffusers** key naming, **one** text encoder (`lora_te_*`;
SDXL has two, `lora_te1_*`/`lora_te2_*`), and **72 tensors under `down_blocks_0_attentions_*`** —
SDXL's first down block has no attention at all, SD1.5's does.

| LoRA key | down | up | delta | checkpoint counterpart |
|---|---|---|---|---|
| `lora_unet_up_blocks_0_resnets_0_conv1` | `[16, 2560, 3, 3]` | `[1280, 16, 1, 1]` | `[1280, 2560, 3, 3]` = **29,491,200** | `output_blocks.2.0.in_layers.2.weight` = `[1280, 1920, 3, 3]` = 22,118,400 |
| `lora_unet_down_blocks_0_attentions_0_proj_in` | `[16, 320, 1, 1]` | `[320, 16, 1, 1]` | `[320, 320, 1, 1]` | **no counterpart** — SDXL `input_blocks.1/2` are ResBlocks only |
| `lora_unet_mid_block_attentions_0_transformer_blocks_0_attn1_to_k` | `[16, 1280]` | `[1280, 16]` | `[1280, 1280]` | matches by luck (mid block is 1280 in both topologies) |

The first row is the whole story, and it is confirmed verbatim in the log:

```
ERROR lora diffusion_model.output_blocks.2.0.in_layers.2.weight shape '[1280, 1920, 3, 3]' is invalid for input of size 29491200
```

29,491,200 is `1280 × 2560 × 3 × 3` — the SD1.5 output-block width. The second row is the whole
story for the *other* error class: keys with no target at all become `lora key not loaded`.

### `darkness_xl_v2.safetensors` — **MATCH (SDXL)**

2364 tensors, sd-scripts metadata present (`ss_network_args: {"conv_dim": 4, "conv_alpha": 4}`),
sd-scripts UNet naming, **zero** `lora_te_*` keys (UNet-only LoRA), **zero** `down_blocks_0`
attention keys.

| LoRA key | down | up | delta | checkpoint counterpart | |
|---|---|---|---|---|---|
| `lora_unet_output_blocks_2_0_in_layers_2` | `[4, 1920, 3, 3]` | `[1280, 4, 1, 1]` | `[1280, 1920, 3, 3]` | `output_blocks.2.0.in_layers.2.weight` = `[1280, 1920, 3, 3]` | ✅ |
| `lora_unet_output_blocks_3_0_in_layers_2` | `[4, 1920, 3, 3]` | `[640, 4, 1, 1]` | `[640, 1920, 3, 3]` | `output_blocks.3.0.in_layers.2.weight` = `[640, 1920, 3, 3]` | ✅ |
| `lora_unet_output_blocks_3_1_transformer_blocks_0_attn1_to_k` | `[8, 640]` | `[640, 8]` | `[640, 640]` | `output_blocks.3.1...attn1.to_k.weight` = `[640, 640]` | ✅ |
| `lora_unet_input_blocks_4_1_transformer_blocks_0_attn1_to_q` | `[8, 640]` | `[640, 8]` | `[640, 640]` | `input_blocks.4.1...attn1.to_q.weight` = `[640, 640]` | ✅ |

Shapes agree exactly, and the live probe confirms **zero unloaded keys** — which is the stronger
statement, because ComfyUI reports every key it could not place and reported none.

---

## 2. Live attribution probe — four configs

512×512, 4 steps, one submission per config against the same checkpoint; the log byte offset is
captured immediately before `POST /prompt` and only the newly appended region is counted.

```
uv run python _bmad-output/implementation-artifacts/10-3-live-validation/probe_lora.py
```

| config | `lora key not loaded` | `ERROR lora ... invalid for input of size` |
|---|---:|---:|
| `both` (horror@0.6 → darkness@0.5) | **342** | **73** |
| `horror_only` (@0.6) | **342** | **73** |
| `darkness_only` (@0.5) | **0** | **0** |
| `none` | **0** | **0** |

`horror_only` reproduces `both` exactly; `darkness_only` contributes nothing. Attribution is total,
not partial.

**Cache control (why `darkness_only = 0` is a real zero, not a cached no-op).** ComfyUI's default
execution cache retains the previous prompt's node outputs, so a `LoraLoader` with identical inputs
run twice in a row logs nothing. The probe therefore runs
`both → none → horror_only → none → darkness_only → none` — each `none` graph contains no
`LoraLoader`, which evicts the loader nodes — and uses a fresh seed every submission. The
`darkness_only` window in `probe_counts.txt` shows `got prompt`, `Requested to load SDXLClipModel`
and a full `Requested to load SDXL` / `loaded completely; ... 4897.05 MB loaded`, i.e. a freshly
patched model object was built and moved to the GPU. The neighbouring `none` windows do **not**
contain the `SDXLClipModel` line. The patch happened; it just had nothing to complain about.

Raw per-config log windows: `probe_counts.txt`.

---

## 3. Remedy chosen

**Delete node `10` (`horror.safetensors`) from all five workflows and re-chain node `11`
(`darkness_xl_v2.safetensors`, unchanged strength) directly onto node `4`.** Node ids of everything
else are untouched, so `image.py`'s hardcoded `"6"`/`"7"` injection and its `class_type ==
"KSampler"` seed sweep keep working, and `scripts/seed_location_plates.py:57`'s `MODEL_NODE = "11"`
still resolves (node 11 survives — **no change was needed there**).

Why removal and not `strength = 0`: ComfyUI still loads the file and runs the patch loop at strength
0, so both the error storm and its cost remain. Why keep `darkness_xl_v2`: it is proven clean, and
the Epic-10 rule is to remove what is broken, not to reach for a bigger change than the evidence
supports.

Files rewired:

- `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json` (the production shot workflow)
- `data/workflows/comfyui_character_multi_angle_api.json`
- `data/workflows/comfyui_location_plate_api.json`
- `data/workflows/comfyui_sdxl_anime_lora_layered_api.json`
- `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json`

Regression guard: `tests/test_workflow_definitions.py` fails if any `comfyui_*_api*.json` names a
LoRA outside `{darkness_xl_v2.safetensors}`, or if any node input references a node id that does not
exist, or if `api2` loses `6`/`7` as `CLIPTextEncode` or its `KSampler`.

---

## 4. Frame evidence — the 6-shot slate

Story 10.1's slate replayed at production settings from run `8a9a288b`'s sidecars
(`image_prompt` / `negative_prompt` / `seed` verbatim; 1344×768, 30 steps, cfg 7.5,
`dpmpp_2m`/`karras` from the workflow file). **The LoRA chain is the only variable.**

```
EVID=_bmad-output/implementation-artifacts/10-3-live-validation
uv run python $EVID/render_slate.py $EVID/before/workflow_before.json $EVID/before
uv run python $EVID/render_slate.py data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json $EVID/after
```

**The before-leg must point at `before/workflow_before.json`** — the pre-fix graph preserved beside
the frames. The live workflow file no longer chains `horror.safetensors`, so aiming both legs at it
silently overwrites `before/` with post-fix frames and turns the A/B into an after/after comparison
that still looks like evidence.

| render | log window | `lora key not loaded` | `ERROR lora ... invalid size` |
|---|---|---:|---:|
| `before/` (horror + darkness) | 838 lines from offset 424009 | **342** | **438** (= 73 × 6 shots) |
| `after/` (darkness only) | 56 lines from offset 538761 | **0** | **0** |

(`key_not_loaded` is emitted once per `LoraLoader` execution — cached across the 6 shots — while the
shape errors are emitted per model patch, hence 73 per shot.) Windows saved as
`before/_log_window.txt` and `after/_log_window.txt`. All six after-shots returned an image, which
is also the live proof that the rewired graph is valid.

Pairs: `pairs/<shot>_pair.jpg` (before | after, labelled) and `pairs/_contact_grid.jpg`.

```
for s in scene_001_S00101 scene_001_S00102 scene_001_S00104 scene_002_S00202 scene_002_S00203 scene_004_S00403; do
  ffmpeg -y -i before/$s.png -i after/$s.png -filter_complex \
    "[0:v]drawtext=text='BEFORE horror+darkness':x=20:y=20:fontsize=36:fontcolor=yellow:box=1:boxcolor=black@0.6[a];\
     [1:v]drawtext=text='AFTER darkness only':x=20:y=20:fontsize=36:fontcolor=yellow:box=1:boxcolor=black@0.6[b];\
     [a][b]hstack=inputs=2" -q:v 3 pairs/${s}_pair.jpg
done
```

### Per-shot art-style verdict

Composition is recognisably the same shot in every pair (same seed), so the differences below are
style and rendering, not a different draw.

| shot | did the art style change? | direction | verdict |
|---|---|---|---|
| `scene_001_S00101` | Slightly. Same painterly dark-industrial look; after has crisper panel geometry, a legible door frame, an extra warm floor spill and a small red indicator light. | more architectural detail, marginally warmer | **better (small)** |
| `scene_001_S00102` | Yes, and it is the clearest win. Before renders the ceiling light as a **formless white starburst with ray artifacts**; after renders an actual pendant lamp — cord, shade, hotspot — with the light falling as streaks down the wall. | incoherent glare → drawn object | **better** |
| `scene_001_S00104` | Slightly. Same anime rendering in both; after adds a coherent food tray in the slot and a cleaner door edge; grime/blood spatter reads as texture rather than mush. | more object coherence | **better (small)** |
| `scene_002_S00202` | Slightly. Brick wall in both, same light wedge geometry; after adds a horizontal ledge/beam and firmer mortar lines instead of a soft blur. | sharper, more structured | **equal/better** |
| `scene_002_S00203` | **Yes — this is finding 12 itself.** The before frame has a **stray anime face peering through the grate** in a shot whose prompt is an empty top-down cell. After: no face, clean unpeopled interior, consistent hard-surface rendering. | spurious character removed | **better** |
| `scene_004_S00403` | Slightly. Both draw a face behind the observation window in the same style; after drops a nonsensical dark dome above the window and replaces it with a coherent glass column and console. | less nonsense geometry, same style | **equal/better** |

**Overall: better on 4, equal-or-better on 2, worse on 0. The Block-If condition ("after-frames judged
worse") did not trigger.** The style is also more *internally consistent* after the fix — the
before-set contains two frames that fall outside the set's own look (`S00102`'s glare abstraction,
`S00203`'s intruding character), and the after-set contains none.

Caveat, stated so it is not mistaken for a 10.3 regression: `scene_001_S00104` and
`scene_004_S00403` still render a human figure in what should be an unpeopled plate. That is
finding 5·12 and belongs to **Story 10.2**; it is unchanged by this fix in either direction.

---

## 5. Judgment on spec item ③ — should a shot-to-shot style-drift axis go into Story 13.2?

**Recommendation: no — do not add it now.** Reasoning:

1. **It would not have caught this defect.** The broken patch applied identically to all 66 shots, so
   a pairwise style-distance metric across the run would have measured a *uniform* style and reported
   nothing. What Jay perceived as "drift" was actually two different things — one config fault
   (now fixed, and now guarded statically at zero runtime cost by
   `tests/test_workflow_definitions.py`) and one content fault.
2. **The one genuinely outlying frame is cheaper to catch elsewhere.** `S00203`'s intruding anime
   character is a *person in a background that should be unpeopled* — exactly the detector Story
   10.2 already owns, and a per-frame binary check is far cheaper and far more actionable than a
   run-level distance distribution.
3. **13.2 already has four higher-value handoff candidates** from Story 10.1 (plate provides a ground
   plane / clamp survival / card-plate light sharing / contact legibility), all of which name a
   defect that survived a fix attempt. A style-drift axis names no surviving defect.
4. **Cost is not zero.** With no new dependency allowed, the only in-house embedding path is
   ComfyUI's `CLIPVisionLoader` (already used by the IPAdapter workflows), which means a per-run GPU
   pass on the shared single queue, plus a threshold nobody can calibrate until a genuine drift case
   exists.

**Re-open condition:** if a future run shows style outliers *after* the plate/people fixes land —
i.e. frames that are unpeopled and on-prompt but still read as a different illustration style — then
add it, and build it on ComfyUI `CLIPVision` embeddings of the run's own shot images (no new
dependency), scored as "distance from the run's own median shot", not against an absolute reference.

---

## 6. Explicitly not addressed

- **Render slowness is a separate, unresolved problem and was not touched.** `epics.md` already
  records that removing the LoRA did not resolve it, and the Never tier forbids chasing it here. For
  what it is worth as a datum and nothing more: this slate rendered at **15–18 s/shot before and
  15–18 s/shot after** (1344×768, 30 steps), i.e. the fix changed throughput by nothing measurable.
- **LoRA strengths, checkpoint, steps/cfg/sampler/resolution, and negative prompts are untouched.**
- **No asset was regenerated, re-approved or deleted**; `assets/manifest.json` is not modified.
- **No model or LoRA was downloaded.** The remedy is pure removal.
- **A stale copy of the inverted claim survives outside this story's scope.**
  `data/workflows/comfyui_fusion_img2img_api.json`'s `_ytflow_note` says "the background workflow
  loads darkness_xl_v2.safetensors, which Story 10.3 measured as an SD1.5-layout file". That is the
  pre-measurement claim and it is wrong — but that file is another session's in-flight Story 10.1b
  work, so it was deliberately left alone. Whoever owns 10.1b should correct that sentence
  (the file has no `LoraLoader`, so nothing about its behaviour is affected).

## 7. Caveats and residual risks (added during review)

- **The counts are read from a shared log.** `~/workspaces/ComfyUI/user/comfyui.log` is written by
  every client, and another session was queueing 10.1b probes on the same server during this work.
  Foreign traffic can only *add* error lines to a window, never remove them, so the measured
  **zeros are safe** and the non-zero counts are upper bounds. The raw windows are archived in
  `probe_counts.txt` and `*/_log_window.txt` for anyone who wants to re-attribute line by line.
  `after/_log_window.txt` contains 7 `Requested to load SDXL` lines, so its `0 + 0` is a real clean
  patch, not a cache-served no-op.
- **"패치 대부분이 조용히 실패" overstates it.** 342 of `horror.safetensors`'s ~1050 tensors failed to
  bind; its text-encoder half *was* being applied. Removing it is therefore a real aesthetic change,
  not the restoration of a no-op — which is exactly why this story closes on frames rather than on
  the error count going to zero. (The spec's Intent block quotes a pre-measurement estimate of
  "~292 `ERROR lora`"; the measured figure is **73 per model patch**, 438 across the 6-shot before
  render. The Intent block is read-only by workflow rule, so the correction is recorded here.)
- **Only `api2` has frame evidence.** `comfyui_character_multi_angle_api.json` (cards),
  `comfyui_location_plate_api.json` (plates) and both layered variants were rewired identically but
  rendered nothing. The rewire is mechanically the same and the structural test covers it, but the
  *aesthetic* effect on cards and plates is unmeasured.
- **Approved assets were produced under the old chain.** Every card in `assets/manifest.json` and
  every stock plate was rendered with `horror@0.6` applied. Nothing was regenerated (Never tier), so
  the library is unchanged and valid — but generating *one new angle* for an existing character now
  produces a style that will not match its three siblings. Deferred, not fixed here.
- **This reverses a documented Story 8.15 constraint.** 8.15 said "do not lower/remove the `horror`
  LoRA (shared with entity cards)" and built its `STOCK_NEGATIVE` suppression list specifically
  against that LoRA's skull-mask bias. The reversal is justified — the LoRA's UNet half was never
  loading — but 8.15's negative suffix may now be suppressing a bias that no longer exists.
  Deferred for re-validation.

## Layout

| Path | What it is |
|---|---|
| `probe_lora.py` | Four-config live attribution probe; `--shapes` dumps the tensor evidence |
| `before/workflow_before.json` | The pre-fix graph, preserved so the before-leg stays re-runnable |
| `probe_counts.txt` | Probe table + the raw log window for each of the six submissions |
| `shapes.txt` | `--shapes` output (key/shape pairs quoted in §1) |
| `render_slate.py` | Replays the 6 slate shots from run `8a9a288b`'s sidecars against a given workflow |
| `before/*.png` | Slate rendered with the pre-fix chain (horror + darkness) |
| `after/*.png` | Slate rendered with the post-fix chain (darkness only) |
| `*/_log_window.txt` | The ComfyUI log region belonging to that render, with its counts |
| `pairs/*_pair.jpg` | before \| after, labelled — the adjudication artifacts |
| `pairs/_contact_grid.jpg` | All six pairs stacked |
