# Layered Assets (Story 5.2)

Activates the already-built layered-image / character-overlay pipeline
(Story 1.6b `image_node`, Story 1.9c `video_node`) against a real ComfyUI
workflow that emits an opaque background PNG plus a transparent (RGBA)
character PNG.

## Custom node

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

`data/workflows/comfyui_sdxl_anime_lora_layered_api.json` — a copy of the
baseline `comfyui_sdxl_anime_lora_workflow_api2.json` with one shared
generation branch (checkpoint → LoRAs → `CLIPTextEncode` nodes `"6"`/`"7"`
→ `KSampler` → `VAEDecode`) feeding two independent output branches:

- **Background** (opaque): `VAEDecode` → `SaveImage` (node `"9"`, prefix
  `ytflow_bg`).
- **Character** (RGBA): `VAEDecode` → `Image Remove Background (rembg)`
  (node `"12"`) → `SaveImage` (node `"13"`, prefix `ytflow_char`).

Prompt injection stays on nodes `"6"`/`"7"`, unchanged from the baseline
workflow — no code changes were needed in `image_node`.

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
YTFLOW_COMFYUI_WORKFLOW_PATH=data/workflows/comfyui_sdxl_anime_lora_layered_api.json
YTFLOW_COMFYUI_BACKGROUND_NODE=9
YTFLOW_COMFYUI_CHARACTER_NODE=13
```

Keep the baseline workflow path when `YTFLOW_COMFYUI_LAYERED=false`; the layered
workflow requires the rembg custom node even if the pipeline later uses the
flat-image branch.

## Direct ComfyUI validation procedure

Before running yt.flow, submit the workflow straight to ComfyUI and confirm
both output nodes appear with an alpha-channel character PNG:

```bash
python3 - <<'EOF'
import json, urllib.request
wf = json.load(open("data/workflows/comfyui_sdxl_anime_lora_layered_api.json"))
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

This first layered workflow intentionally derives the character cutout from the
same generated frame as the background. If rembg extracts too much foreground
for a specific prompt, keep the run as background-only or follow up with a
separate character-prompt workflow; do not treat this file as a semantic
segmentation guarantee.

## Fallback behavior

If background removal fails or the character node produces no output for
a shot, `image_node` sets `character_path = None` and keeps
`background_path` set. `video_node` then falls back to the background-only
Ken Burns path (Story 1.9b) for that shot instead of failing the run.
