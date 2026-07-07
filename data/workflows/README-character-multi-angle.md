# Character Multi-Angle Reference Generation (Story 5.10)

Fixes Story 1.12's multi-angle character generation, which had never been
exercised successfully against a real ComfyUI server: `Settings.character_comfyui_workflow_path`
pointed at a file that didn't exist, so every run silently fell through to
`ComfyUICharacterProvider._default_workflow()` (a bare t2i SDXL graph) and the
real local ComfyUI instance rejected it with `prompt_outputs_failed_validation`.

## Workflow file

`data/workflows/comfyui_character_multi_angle_api.json` — reuses the same
checkpoint/LoRA generation branch as the layered background/character
workflows (see [`README-layered-assets.md`](README-layered-assets.md)):
`AnimagineXL_v31.safetensors` (node `"4"`) → `horror.safetensors` LoRA (node
`"10"`) → `darkness_xl_v2.safetensors` LoRA (node `"11"`) →
`CLIPTextEncode` positive/negative (nodes `"6"`/`"7"`) → `KSampler` (node
`"3"`) → `VAEDecode` (node `"8"`) → `InspyrenetRembg` (node `"12"`) →
`SaveImage` (node `"9"`). Single output — one transparent RGBA character sprite
per angle. The prompt path asks for a full-body subject on a plain light-gray
studio background so the background-removal node gets a clean cutout problem.

The reference image conditions generation via **IPAdapter**, not a
VAEEncode-based img2img denoise:

- `LoadImage` (node `"20"`) — the reference image, uploaded per-generation
  (see "Reference image injection" below).
- `CLIPVisionLoader` (node `"21"`) — `clip_vision_vit_h.safetensors`.
- `IPAdapterModelLoader` (node `"22"`) — `ip-adapter-plus_sdxl_vit-h.safetensors`.
- `IPAdapterAdvanced` (node `"23"`) — applies the reference to the
  checkpoint+LoRA model (`weight: 0.65`, `weight_type: "linear"`) before
  `KSampler`.

**Why explicit loaders instead of `IPAdapterUnifiedLoader`:** the convenience
loader resolves clip-vision/ipadapter files by regex pattern against a preset
name (e.g. `"PLUS (high strength)"` expects a clip-vision filename matching
`ViT-H-14-*-s32B-b79K` or similar upstream-standard names). This environment's
installed files are named `clip_vision_vit_h.safetensors` and
`ip-adapter-plus_sdxl_vit-h.safetensors`, which don't match those patterns —
`IPAdapterUnifiedLoader` raises `"ClipVision model not found."` against them.
`CLIPVisionLoader` + `IPAdapterModelLoader` select files by exact filename
from ComfyUI's model dropdown instead, so they work regardless of naming
convention. `IPAdapterAdvanced` (not the simpler `IPAdapter`/`IPAdapterSimple`
node) is required to pair with these explicit loaders — `IPAdapterSimple`
only accepts the unified loader's combined pipeline dict, while
`IPAdapterAdvanced` has direct optional `ipadapter`/`clip_vision` inputs (see
the node pack's `NODES.md`).

## Reference image injection — upload, not base64

`ComfyUICharacterProvider._inject_reference_image` (Story 1.12) used to set
`LoadImage.inputs.image` to a base64-encoded data URI. Stock ComfyUI's
`LoadImage` node resolves `inputs.image` as a **filename** in its input
directory (`folder_paths.get_annotated_filepath`) — it never accepted base64,
so every real i2i attempt was silently failing over to the t2i fallback path
before this story. Fixed in `comfyui_client.upload_image()`: the reference
image bytes are POSTed to `/upload/image` first, and the returned filename is
what gets injected into `LoadImage.inputs.image`.

## t2i fallback (AC9)

`ComfyUICharacterProvider._remove_i2i_input` bypasses the `IPAdapter`/
`IPAdapterAdvanced` node by reconnecting `KSampler.model` directly to
whatever fed the IPAdapter node (the LoRA chain), rather than touching the
latent — IPAdapter conditions the model/cross-attention, not the sampler's
starting latent, so the old approach (reconnecting `KSampler.latent_image` to
`EmptyLatentImage`) was already a no-op for this workflow shape even before
this story (the legacy VAEEncode-i2i reconnection logic is preserved as a
fallback for any workflow that still uses that older shape).

## Required ComfyUI models

| File | Expected location |
|------|-------------------|
| `AnimagineXL_v31.safetensors` | `<ComfyUI>/models/checkpoints/` |
| `horror.safetensors` | `<ComfyUI>/models/loras/` |
| `darkness_xl_v2.safetensors` | `<ComfyUI>/models/loras/` |
| `clip_vision_vit_h.safetensors` | `<ComfyUI>/models/clip_vision/` |
| `ip-adapter-plus_sdxl_vit-h.safetensors` | `<ComfyUI>/models/ipadapter/` |

`ComfyUI_IPAdapter_plus` (repo:
[`cubiq/ComfyUI_IPAdapter_plus`](https://github.com/cubiq/ComfyUI_IPAdapter_plus))
must be installed under `<ComfyUI>/custom_nodes/` — already present in this
environment along with both model files, no install step needed.

## `.env` variables

`Settings.character_comfyui_workflow_path` already defaults to
`data/workflows/comfyui_character_multi_angle_api.json`. Character card
generation now defaults to a portrait SDXL bucket:

```bash
YTFLOW_CHARACTER_IMAGE_WIDTH=832
YTFLOW_CHARACTER_IMAGE_HEIGHT=1216
```

## Direct ComfyUI validation procedure

Same procedure as the layered-assets README, but a real reference image must
be uploaded first (the workflow's `LoadImage` node has a placeholder filename
that fails validation on its own). Validate all four canonical angles and check
that each returned PNG has an alpha channel with `yt_flow.domain.png.has_alpha`:

```bash
python3 - <<'EOF'
import json, urllib.request

wf = json.load(open("data/workflows/comfyui_character_multi_angle_api.json"))
# Upload a real reference image first, then set wf["20"]["inputs"]["image"]
# to the filename returned by POST /upload/image before submitting — see
# yt_flow.services.comfyui_client.upload_image for the exact multipart shape.
req = urllib.request.Request(
    "http://127.0.0.1:8188/prompt",
    data=json.dumps({"prompt": wf}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(req, timeout=30).read().decode())
EOF
```

Validated live on 2026-07-05 against the local ComfyUI instance for all 4
canonical angles (`front`, `back`, `side`, `three_quarter`) through the real
`ComfyUICharacterProvider.generate()` code path — no `node_errors`, no
fallback to t2i, and a real SCP Wiki reference photo (SCP-1471) produced a
visually identity-consistent stylized illustration (masked figure, dark
robe, matching composition). A flat solid-color test image (no real visual
features) produced a near-solid-color output — expected given IPAdapter has
no character detail to transfer from a textureless swatch, not a workflow
defect.

## Known limitation — LoRA shape-mismatch warnings

Both `horror.safetensors` and `darkness_xl_v2.safetensors` log a large batch
of `ERROR lora <key> shape ... is invalid for input of size ...` lines on
every load in this ComfyUI/LoRA-version combination. This is **pre-existing**
or the already-validated layered background/character workflow ([Story
5.2/5.6/5.7](README-layered-assets.md)) — confirmed by re-submitting that
workflow directly and observing the identical warning set. ComfyUI skips the
mismatched tensors and continues; generation still succeeds
(`node_errors: {}`, `Prompt executed`). Not addressed here — same
pre-existing behavior as the already-shipped layered workflow.
