# `comfyui_qwen_pose_edit_api.json` — conditioned action-pose generation (Story 8.20)

> ⛔ **NOT ADOPTED — measured and rejected 2026-08-04.** This workflow runs, and its
> identity preservation is excellent, but it fails two hard gates on the target host.
> It is kept as the reproducible evidence artifact behind
> `_bmad-output/implementation-artifacts/8-20-live-validation/DECISION-RECORD.md`, not
> as a production path. Do not wire a service to it. Two blockers:
>
> 1. **The guide does not condition geometry.** `image2` of
>    `TextEncodeQwenImageEditPlus` is a *reference* image, so the guide raster is drawn
>    as **content** — a COCO-18 skeleton became a literal skeleton in frame, a creature
>    silhouette became a literal white animal. The pose effect is confounded: the
>    no-guide baseline already hit the requested action from text alone.
> 2. **It does not fit 16 GB.** 2 of 5 runs died of CUDA OOM at the `InspyrenetRembg`
>    node (peak 15.20–16.18 GB against 15.92 GB usable) because the 13.24 GB GGUF stays
>    resident while the cutout asks for another 4.50 GiB.
>
> Everything below describes the workflow as measured. The "why this shape" reasoning
> in the next section was the pre-measurement hypothesis and is **disproven** — it is
> retained only so the rejected reasoning is auditable.

Minimal API-format workflow that re-poses an **already-approved character card**
into a requested action, then cuts it out to a transparent sprite.

It takes exactly three inputs and nothing else:

| Input | Node title | Meaning |
|-------|-----------|---------|
| reference card | `ytflow:reference_image` | the approved standing-front card — the identity source |
| action instruction | `ytflow:positive_prompt` (`prompt`) | free text, e.g. *"the character in image 1 is reaching forward with the right arm"* |
| structural guide (optional) | `ytflow:guide_image` | one raster that constrains geometry — see **Guides** |

## Why this shape

Qwen-Image-Edit-2511 is a *reference-editing* model: identity comes from the
reference image, not from a face embedding. That is the whole reason Story 8.20
picked it — IPAdapter FaceID / InstantID / PuLID / InsightFace all need a
detectable **real human** face and fail outright on a stylised plague-doctor
mask (SCP-049) or a non-human anomaly (SCP-682). None of those are used here,
and none may be added.

`TextEncodeQwenImageEditPlus` accepts `image1`/`image2`/`image3` natively. That
is what makes the structural guide cheap: **the guide is just a second reference
image**, so the same route serves humanoid and non-humanoid anatomy — only the
guide raster differs. No ControlNet is loaded, which also sidesteps the
unresolved question of whether Qwen-Image ControlNet Union is compatible with
Edit-2511 at all.

> ❌ **Disproven by measurement.** "A second reference image" is exactly the problem:
> a reference is composited as subject matter, not applied as a structural
> constraint, so the guide is *drawn* rather than obeyed. The ControlNet
> compatibility question is therefore **not** sidestepped — a real control adapter
> is the only remaining structural candidate, and Q4_K_M already peaks at the
> 15.92 GB ceiling with no ControlNet loaded. See the decision record.

For the `edit_only` route, delete the `ytflow:guide_image` node and drop
`image2`. Do not wire a blank image — an empty guide is still a guide as far as
the encoder is concerned.

## Guides

A guide is a curated raster showing *the requested action*, never a skeleton
extracted from the reference card (that would just restate the pose the card
already has).

- **Humanoid** — an OpenPose COCO-18 skeleton on black, canonical limb colours.
- **Non-humanoid** — a crude white-on-black scribble of the target silhouette.
  A human DWPose/OpenPose skeleton must never be applied to a non-humanoid;
  its 18 keypoints encode a human ontology that does not exist on a reptile.

## Node graph

```
UnetLoaderGGUF ──► ModelSamplingAuraFlow(3.1) ──► CFGNorm(1.0) ──┐
                                                                 ▼
CLIPLoader(qwen_image) ──► TextEncodeQwenImageEditPlus ──► FluxKontextMultiReferenceLatentMethod
                            ▲    ▲        ▲                      (index_timestep_zero)
                    reference    guide   VAE                            │
                            │                                           ▼
VAELoader ──────────────────┴──► VAEEncode(reference) ──────────► KSampler ──► VAEDecode
                                                                             │
                                                          InspyrenetRembg ◄──┘
                                                                 │
                                                                 ▼
                                                             SaveImage (RGBA)
```

Two details are load-bearing:

- **The latent comes from `VAEEncode` of the reference**, so the output
  resolution equals the reference resolution. The approved humanoid cards are
  already `832x1216` (both divisible by 16), which is exactly the configured
  `character_image_width x character_image_height`, so AC10's geometry holds
  with no rescale node. The official ComfyUI template puts a
  `FluxKontextImageScale` here; it is deliberately omitted because it snaps to
  its own preferred resolution set and would silently change the card size.
- **`InspyrenetRembg` is inside the workflow**, not a post-step. It is the same
  cutout stage Story 5.6 proved (rembg → InSPyReNet) and the same node the
  multi-angle workflow uses. Flat RGB output is a failure, not a fallback.
  ❌ **This is blocker B**: it needs 4.50 GiB while the 13.24 GB GGUF is still
  resident, so it OOMs intermittently (2/5 runs). The node exposes only
  `torchscript_jit` — no device or resolution knob — so the cutout has to leave
  this workflow whatever route replaces it.

Measured note for any future alpha validator: InSPyReNet saturates subject pixels
at **254, not 255** (only ~2% of the frame is exactly 255). Requiring `alpha == 255`
would reject every card this produces.

## Parameter map (from the official ComfyUI 2511 template)

| Node | Setting | Value |
|------|---------|-------|
| `ModelSamplingAuraFlow` | shift | `3.1` |
| `CFGNorm` | strength | `1.0` |
| `FluxKontextMultiReferenceLatentMethod` | method | `index_timestep_zero` |
| `KSampler` | steps / cfg | `40` / `4.0` (base) |
| `KSampler` | sampler / scheduler / denoise | `euler` / `simple` / `1.0` |
| `KSampler` | seed | injected per call (deterministic) |

The 4-step Lightning variant replaces steps/cfg with `4` / `1.0` and adds
`LoraLoaderModelOnly` on the Lightning LoRA. See the decision record for which
one was adopted and why.

## Required ComfyUI-side artifacts

None of these are Python dependencies — they are operational artifacts on the
GPU host, and none are committed to this repo.

| Kind | File | Size | License |
|------|------|------|---------|
| custom node | `ComfyUI-GGUF` @ `6ea2651e7df66d7585f6ffee804b20e92fb38b8a` | — | Apache-2.0 |
| custom node | `ComfyUI-Inspyrenet-Rembg` @ `87ac452ef1182e8f35f59b04010158d74dcefd06` | — | MIT |
| pip (ComfyUI venv) | `gguf>=0.13.0` (installed: `0.19.0`) | — | Apache-2.0 |
| diffusion model | `models/unet/qwen-image-edit-2511-Q4_K_M.gguf` | 13.24 GB | Apache-2.0 |
| text encoder | `models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors` | 9.38 GB | Apache-2.0 |
| VAE | `models/vae/qwen_image_vae.safetensors` | 0.25 GB | Apache-2.0 |
| LoRA (optional) | `models/loras/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` | 0.85 GB | Apache-2.0 |

Content hashes (sha256):

```
a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f  qwen_image_vae.safetensors
cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4  qwen_2.5_vl_7b_fp8_scaled.safetensors
22226e8d05d354bb356627d428809f5afd7819399b077238a2b70a82883a904f  Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors
```

Sources: `unsloth/Qwen-Image-Edit-2511-GGUF` (quantised from
`Qwen/Qwen-Image-Edit-2511`), `Comfy-Org/Qwen-Image_ComfyUI`,
`lightx2v/Qwen-Image-Edit-2511-Lightning`. Every artifact above is Apache-2.0,
which is commercial-use compatible for this monetized channel. Verify the hash
of what you actually downloaded rather than trusting the label.

### Install

```bash
cd ~/workspaces/ComfyUI/custom_nodes
git clone https://github.com/city96/ComfyUI-GGUF.git && cd ComfyUI-GGUF && git checkout 6ea2651e
~/workspaces/ComfyUI/venv/bin/pip install "gguf>=0.13.0"
# then restart ComfyUI (./run.sh) — GGUF loader nodes only register at startup
```

ComfyUI must be launched via `./run.sh`, which sets the RDNA-4 ROCm overrides
(`HSA_OVERRIDE_GFX_VERSION=12.0.0`, `PYTORCH_HIP_ALLOC_CONF=...`). Verified
against ComfyUI core `f350a842611f4d75da7104c2d2965f45989089b9` (v0.12.3),
torch `2.11.0.dev20260206+rocm7.1`, AMD Radeon RX 9060 XT 16 GB.

## Node titles are a contract

Every node this pipeline injects into is titled `ytflow:<key>` and is resolved
by **exact** title match, never by JSON node ID. Renaming one of these titles in
the ComfyUI UI breaks injection loudly rather than silently writing a prompt
into the wrong node. Non-injected nodes may be retitled freely.

The canonical resolver for these keys is Story 13.3's
`comfyui_client.resolve_nodes`. **Story 13.3 is not yet implemented**, so this
workflow currently has no production consumer — see the Story 8.20 decision
record. Do not add a second resolver here.
