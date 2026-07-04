# Layered Assets (Story 5.2, cutout quality upgraded in Story 5.6)

Activates the already-built layered-image / character-overlay pipeline
(Story 1.6b `image_node`, Story 1.9c `video_node`) against a real ComfyUI
workflow that emits an opaque background PNG plus a transparent (RGBA)
character PNG.

## Segmentation node — recommended: InSPyReNet (Story 5.6)

Story 5.2's original `rembg`/u2net node satisfied the mechanical contract
(`_has_alpha()`) but Story 5.6's side-by-side comparison against
`john-mnz/ComfyUI-Inspyrenet-Rembg` found rembg regularly leaves translucent
background "ghosts" (a phone-booth silhouette bleeding through a portrait's
shoulder) and solid background islands fused onto the character silhouette
(a knife/ladder shape merged into a hooded figure's outline). InSPyReNet
produced clean edges on every tested case and never regressed relative to
rembg, so it is now the recommended node. See
[Story 5.6's Dev Agent Record](../../_bmad-output/implementation-artifacts/5-6-character-cutout-quality.md)
for the full evidence set and decision rationale.

- Repo: [`john-mnz/ComfyUI-Inspyrenet-Rembg`](https://github.com/john-mnz/ComfyUI-Inspyrenet-Rembg)
- Node name in the workflow JSON: `InspyrenetRembg`
- Workflow file: `data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json`
- Install (git-clone, matches the existing custom-node layout — the
  ComfyUI-Manager `cm-cli.py install <id>` path failed to resolve the node id
  in this environment, so a direct clone was used instead):

  ```bash
  cd <ComfyUI>/custom_nodes
  git clone https://github.com/john-mnz/ComfyUI-Inspyrenet-Rembg.git
  <ComfyUI venv>/bin/pip install -r ComfyUI-Inspyrenet-Rembg/requirements.txt
  ```

  This pulls the `transparent-background` PyPI package (InSPyReNet). The
  first `Remover()` call downloads its checkpoint to the package's cache
  directory (`~/.transparent-background` by default) — warm this once before
  a real pipeline run in offline environments. Restart ComfyUI after
  installing so the new node is picked up.

  The node outputs `(IMAGE, MASK)` where `IMAGE` is already RGBA
  (`type='rgba'` internally), so no extra mask-combine node is needed — the
  same `SaveImage` → RGBA PNG chain as rembg works unchanged.

## Legacy node — `rembg`/u2net (Story 5.2, superseded)

Kept as `data/workflows/comfyui_sdxl_anime_lora_layered_api.json` for
reference/rollback; not the default recommendation as of Story 5.6.

> **Warning (Story 5.7):** this file predates the background inpaint fix and
> still has the double-exposure defect — its background output shows the
> same entity that the character overlay also renders. Do not reactivate it
> for a real run without porting the inpaint pass from
> `comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` first.

- Repo: [`Jcd1230/rembg-comfyui-node`](https://github.com/Jcd1230/rembg-comfyui-node)
- Node name in the workflow JSON: `Image Remove Background (rembg)`
- Install via ComfyUI-Manager's headless CLI (no GUI needed):

  ```bash
  cd <ComfyUI>/custom_nodes/ComfyUI-Manager
  <ComfyUI venv>/bin/python cm-cli.py install rembg-comfyui-node
  ```

  This pulls the `rembg` PyPI package (onnxruntime-based `u2net` model,
  downloaded to `~/.u2net` on first use — no manual model placement
  required).

  For headless or offline runs, warm this cache once before starting a real
  pipeline run. The ComfyUI process must be able to write to its home directory,
  or `U2NET_HOME` must point at a writable directory containing the downloaded
  model.

  The workflow was validated against the local `cm-cli.py install
  rembg-comfyui-node` install on 2026-07-04. If ComfyUI rejects the class name,
  update the node through ComfyUI-Manager and re-export this API workflow from
  the working graph.

## Required ComfyUI models

This workflow preserves the same model filenames as the baseline SDXL+LoRA
workflow. ComfyUI must be able to resolve them before prompt submission:

| File | Expected location |
|------|-------------------|
| `AnimagineXL_v31.safetensors` | `<ComfyUI>/models/checkpoints/` |
| `horror.safetensors` | `<ComfyUI>/models/loras/` |
| `darkness_xl_v2.safetensors` | `<ComfyUI>/models/loras/` |

## Workflow file

`data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json` (recommended)
and the legacy `comfyui_sdxl_anime_lora_layered_api.json` are both a copy of
the baseline `comfyui_sdxl_anime_lora_workflow_api2.json` with one shared
generation branch (checkpoint → LoRAs → `CLIPTextEncode` nodes `"6"`/`"7"`
→ `KSampler` → `VAEDecode`) feeding two independent output branches:

- **Character** (RGBA): `VAEDecode` (node `"8"`) → segmentation node (node
  `"12"`, either `InspyrenetRembg` or `Image Remove Background (rembg)`) →
  `SaveImage` (node `"13"`, prefix `ytflow_char`).
- **Background** (opaque, character-erased, Story 5.7): node `"12"`'s MASK
  output (the same foreground mask used to cut out the character) also feeds
  `VAEEncodeForInpaint` (node `"16"`), which re-encodes node `"8"`'s image
  with that region marked for regeneration (`grow_mask_by: 12` pixels to
  feather the mask edge and reduce visible seams; `denoise: 1.0` to fully
  replace the masked pixels rather than blend with the original figure). A
  second `KSampler` (node `"17"`) fills the masked area using a static
  entity-free positive prompt (node `"14"`, `"empty background, scenery
  only, no people, ..."`) and a dedicated entity-exclusion negative prompt
  (node `"15"`, `"person, people, human, character, creature, ..."` — kept
  separate from node `"7"` because node `"7"` is overwritten per-shot by
  `image_node` and may not always contain person-exclusion terms).
  `VAEDecode` (node `"18"`) → `SaveImage` (node `"9"`, prefix `ytflow_bg`)
  then saves the entity-free result instead of the raw node `"8"` frame.
  Everything outside the mask is *intended* to pass through unchanged, but a
  second full VAE encode/decode round-trip is not bit-exact — expect minor
  global reconstruction differences (not just inside the masked region), not
  an absolute pixel-identity guarantee.

Prompt injection stays on nodes `"6"`/`"7"`, unchanged from the baseline
workflow — no code changes were needed in `image_node`. Both output node IDs
(`"9"` background, `"13"` character) are unchanged, so `Settings.comfyui_background_node`
/ `Settings.comfyui_character_node` don't need to change either. The extra
inpaint pass (nodes `"14"`/`"15"`/`"16"`/`"17"`/`"18"`) roughly doubles
per-shot ComfyUI sampling time (a second 30-step `KSampler` run — confirmed
live, see Story 5.7's Dev Agent Record) — the accepted cost of removing the
double-exposure. The legacy `comfyui_sdxl_anime_lora_layered_api.json`
(rembg) has not been updated with this inpaint pass since it is superseded and
kept only for rollback; it still has the double-exposure defect if
reactivated — its node `"9"` `_meta.title` carries an inline warning to that
effect for anyone opening the file directly.

## Output node ID mapping

| Output      | Node ID | Settings field                    |
|-------------|---------|------------------------------------|
| Background  | `9`     | `Settings.comfyui_background_node` |
| Character   | `13`    | `Settings.comfyui_character_node`  |

Node `13` was chosen (instead of the `Settings` default `"10"`) because
`"10"`/`"11"` are already used by the baseline workflow's two `LoraLoader`
nodes — hence the explicit `YTFLOW_COMFYUI_CHARACTER_NODE=13` below.

## `.env` variables

```
YTFLOW_COMFYUI_LAYERED=true
YTFLOW_COMFYUI_WORKFLOW_PATH=data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json
YTFLOW_COMFYUI_BACKGROUND_NODE=9
YTFLOW_COMFYUI_CHARACTER_NODE=13
```

Keep the baseline (non-layered) workflow path when `YTFLOW_COMFYUI_LAYERED=false`;
each layered workflow file hard-pins its own segmentation node (`InspyrenetRembg`
or `Image Remove Background (rembg)`), so ComfyUI must have that specific custom
node installed to validate the graph even if the pipeline later uses the
flat-image branch.

## Known limitation — no "is this the story's character" concept

Neither rembg/u2net nor InSPyReNet know what a video's protagonist is; both
are generic saliency/foreground segmenters. For shots whose composition has
no person in frame (an establishing shot of laptops on a table, a close-up
of a hand holding an ID card), both models still extract *something* as the
"character" — the most visually distinct foreground blob — which is
format-valid (passes `_has_alpha()`) but semantically wrong, and gets the
same idle-motion overlay treatment as a real character. Story 5.6 confirmed
this is model-agnostic (both nodes fail the same way on the same shots) and
explicitly out of scope to fix here: it needs either a person-presence
pre-check before segmentation or acceptance as a documented limitation. See
Story 5.6's Dev Agent Record for the concrete evidence.

## Direct ComfyUI validation procedure

Before running yt.flow, submit the workflow straight to ComfyUI and confirm
both output nodes appear with an alpha-channel character PNG:

```bash
python3 - <<'EOF'
import json, urllib.request
wf = json.load(open("data/workflows/comfyui_sdxl_anime_lora_layered_inspyrenet_api.json"))
req = urllib.request.Request(
    "http://127.0.0.1:8188/prompt",
    data=json.dumps({"prompt": wf}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(req, timeout=30).read().decode())
EOF
```

Then poll `GET /history/{prompt_id}` until `outputs` contains both node
`"9"` and node `"13"`, and confirm the node `"13"` PNG's IHDR color type
byte (offset 25) is `4` or `6` (RGBA) — this is exactly what
`image_node._has_alpha()` checks. For live validation, also inspect the alpha
channel or extracted frames to confirm there are transparent pixels and useful
foreground separation; the byte check proves format compatibility, not visual
quality.

The character cutout is still derived from the same generated frame as the
background (Story 5.7 only fixed the background leaking the character —
segmentation quality is Story 5.6's scope). If segmentation extracts too much
foreground for a specific prompt, the inpaint pass will also erase that
over-extracted region from the background; keep the run as background-only or
follow up manually rather than treating either file as a semantic
segmentation guarantee.

## Fallback behavior

If the character node alone produces no output for a shot (e.g. the
segmentation node runs but the RGBA check fails), `image_node` sets
`character_path = None` and keeps `background_path` set; `video_node` then
falls back to the background-only Ken Burns path (Story 1.9b) for that shot
instead of failing the run.

**Story 5.7 changed this for one failure mode.** Before 5.7, node `"9"`
(background) sourced directly from node `"8"` and was independent of node
`"12"` (segmentation) — a segmentation failure only cost the character
layer. After 5.7, node `"9"` depends on node `"12"`'s mask via the inpaint
chain (`"16"`→`"17"`→`"18"`), so if segmentation itself errors (not just
produces a bad cutout), **both** background and character outputs are now
missing, `image_node` raises `ComfyUIError` for that shot, and — since the
per-shot loop has no per-shot try/except — the entire run's image stage
fails rather than degrading to background-only. This coupling is a known
limitation of the workflow-JSON-only fix approach and has not been
addressed at the Python level; treat a segmentation-node crash as a
run-failing event, not a soft per-shot fallback, until a follow-up story
revisits it.
