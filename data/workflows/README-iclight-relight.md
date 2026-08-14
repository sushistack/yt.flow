# IC-Light Re-lighting Workflow (Story 8.7 Tier 3, live-verified in Story 10.1b)

## Status: verified — live-submitted, and rendering into video

`data/workflows/comfyui_iclight_relight_api.json` carries
`"ytflow_verified_iclight": true` as of **2026-08-08 (Story 10.1b)**. It is a
complete IC-Light **v1 `fbc`** graph, submitted live against this host's
ComfyUI, and its output is cached under `assets/relit/{card_variant}/{location_key}/`
and composited by `video.py` at `composite_harmonization_tier=3`.

Installed here (measured, not assumed): kijai
[`ComfyUI-IC-Light`](https://github.com/kijai/ComfyUI-IC-Light) @ `22811d9`,
`models/unet/iclight_sd15_fbc.safetensors` (1.6 GiB), and the SD1.5 base `fbc`
requires, `models/checkpoints/cyberrealistic_v90.safetensors` (1.99 GiB).
`LoadAndApplyICLightUnet` hard-rejects anything that is not SD1.5, so this
project's SDXL checkpoint cannot carry it. **v1 `fbc` only** — v2/Flux variants
are non-commercial and this pipeline is monetized.

> **Two earlier versions of this file were wrong, in opposite directions.** It
> first said the host had no IC-Light nodes (false since 2026-08-02). It then
> said nodes `"3"`–`"9"` were a placeholder SDXL text-to-image chain (false —
> that chain was replaced by the real `fbc` graph on 2026-08-02, and the JSON's
> own `_ytflow_note` said so). Both claims outlived the code and each cost a
> session. The JSON is the source of truth; this file describes it.

## The graph

| Node | Class | Role |
|---|---|---|
| `"1"` | `LoadImage` | **Injection point.** The card sprite, uploaded per pair by `composite_harmonization.relight_sprite`. Slot 0 = RGB, slot 1 = MASK. |
| `"2"` | `LoadImage` | **Injection point.** The location plate. |
| `"4"` | `CheckpointLoaderSimple` | SD1.5 base. |
| `"10"` | `LoadAndApplyICLightUnet` | Patches the SD1.5 unet with the `fbc` weights. |
| `"20"` | `EmptyImage` | 832×1216 of `#7F7F7F` (`color: 8355711`). |
| `"21"` | `ImageCompositeMasked` | Card matted onto that grey. See *Mask polarity* below. |
| `"12"` | `VAEEncode` | Foreground latent — **node `"21"`, not node `"1"`.** |
| `"11"` → `"13"` | `ImageScale` → `VAEEncode` | Plate resized to the card canvas, then encoded: the `bc` in `fbc`. |
| `"6"` / `"7"` | `CLIPTextEncode` | Positive / negative. Do **not** enlarge the negative — `gotcha_negative-prompt-overstuffing`. |
| `"14"` | `ICLightConditioning` | `multiplier` 0.18215. `opt_background` is what makes this background-conditioned; the `fbc` weights require it. |
| `"22"` → `"23"` | `LightSource` → `VAEEncode` | Init latent, a light-shape gradient. |
| `"3"` | `KSampler` | `denoise 1.0`, `cfg 2.0`, `dpmpp_2m`, `karras`, 25 steps. |
| `"8"` → `"15"` | `VAEDecode` → `DetailTransfer` | Relit RGB, then the card's own line detail added back. |
| `"17"` | `JoinImageWithAlpha` | Re-attaches the source alpha. **The sprite contract.** |
| `"9"` | `SaveImage` | Output. Retrieval is node-id-agnostic (first output node). |

Four nodes are read or written by `composite_harmonization.py`, and it addresses
all four **by declared title, never by node id** (Story 13.3) — see *Manifest
titles* below. Everything else is opaque to the runtime — but
`tests/pipeline/nodes/test_composite_harmonization.py` now loads this actual
file and asserts the injection points, the marker, the grey matte, the
light-shape init latent and the alpha re-attachment, so a renumbering or an
undone fix fails a test instead of failing silently in a live render.

## Manifest titles (Story 13.3)

`_meta.title` on an injection target is a **contract string**, not a label:
`comfyui_client.resolve_nodes` matches it exactly and raises if it is missing or
duplicated. Renaming one of these in the ComfyUI UI breaks the relight loudly at
load, which is the point — before 13.3 the grey-matte / light-source pair was
looked up by id through `workflow.get()` and a renumber dropped card-size
conditioning **silently**.

| Node | Manifest title | Written by |
|---|---|---|
| `"1"` | `ytflow:card_image` | `_inject_relight_inputs` — uploaded card filename |
| `"2"` | `ytflow:background_image` | `_inject_relight_inputs` — uploaded plate filename |
| `"20"` | `ytflow:grey_matte` | `_inject_relight_inputs` — `width`/`height` = card size |
| `"22"` | `ytflow:light_source` | `_inject_relight_inputs` — `width`/`height` = card size |

The descriptive titles those four carried before 13.3 are preserved here
verbatim, because they explain *why* each node is what it is:

- `"1"`: *Foreground — the character card (RGBA sprite), uploaded per pair*
- `"2"`: *Background — the location plate whose light the card should take, uploaded per pair*
- `"20"`: *Neutral grey #7F7F7F matte — the card canvas, filled*
- `"22"`: *Light-shape gradient — IC-Light's own node. This IS the light direction; the fbc example seeds the sampler with it instead of a zero latent. (The example uses CreateShapeMask + GrowMaskWithBlur, which are KJNodes and not installed here.)*

## Why it was parked, and what actually fixed it

Parked 2026-08-02 on output quality: denoise 0.45 / 0.60 / 0.85 gave washed
grey, near-black and blue-monochrome. The recorded explanation — "IC-Light v1 is
photoreal-trained and these cards are flat anime" — was a hypothesis. Story
10.1b found two measurable wiring defects instead:

1. **The foreground latent was 72% black.** ComfyUI's `LoadImage` does
   `image.convert("RGB")` (`ComfyUI/nodes.py:1727`), discarding alpha. Measured
   on the actual SCP-049 card: **71.65% of pixels have alpha < 8, and their RGB
   is exactly `[0,0,0]`**. `fbc` was told the subject stands in a void, and a
   background-conditioned relight of a void is exactly "near-black". Fixed by
   nodes `"20"`/`"21"` — the official example mattes onto `#7F7F7F` too.
2. **The init latent was a zero tensor.** `ICLightConditioning`'s third output
   is `torch.zeros_like(...)`; sampling it at denoise 0.85 is neither a relight
   nor a generation. Fixed by nodes `"22"`/`"23"` at denoise 1.0, matching the
   example. Identity and pose survive because they come from
   `ICLightConditioning.foreground`, not from the init latent.

A third defect lived outside this directory: `_inject_relight_inputs` used to
deep-copy the whole file, so `ytflow_verified_iclight` and `_ytflow_note` were
submitted as if they were nodes. ComfyUI's `validate_prompt` runs
`'class_type' not in prompt[x]` over every top-level key, and a bool there
raises `TypeError` — **every** submission returned 500. It now copies only
entries carrying a `class_type`. Any future top-level metadata key is therefore
safe to add.

## Mask polarity — the thing that keeps getting "fixed" and breaking

- `LoadImage` slot 1 is a MASK equal to **`1 - alpha`** (1 where *transparent*),
  `ComfyUI/nodes.py:1739`.
- `ImageCompositeMasked` pastes `source` where the mask is 1. So
  `destination=["1",0]`, `source=grey`, `mask=["1",1]` puts grey precisely in
  the transparent region — **no `InvertMask`**.
- `JoinImageWithAlpha` internally applies `alpha = 1.0 - mask`, which cancels
  `LoadImage`'s inversion. Node `"17"` therefore takes `["1", 1]` directly.

An `InvertMask` was added here once and produced a perfectly inverted
silhouette (alpha correlation **−1.0**). The verified graph measures **+1.0000**
with a max alpha difference of 0/255.

## Known limits (measured, not guessed)

- **The relit card is darker than the unlit one.** Node `"11"` centre-crops the
  whole plate to the card canvas, so `fbc` sees the plate's average light, not
  the band the card is actually composited into. On `S00202` the crop reads
  L=71.8 while the region the card lands in reads L=113.4. The cache key is
  `(card_variant, location_key)` — card_key+pose+angle — not the shot, so the local band is not knowable at
  relight time — closing this means changing the cache granularity.
- **`light_position` is effectively inert.** At `denoise 1.0` ComfyUI ignores
  the init latent's *content*; only its shape survives. "Top Light" vs
  "Top Left Light" measured ΔL = 0.6 and ≤0.8 per channel — sampler variance.
  The node stays because the official example keeps it and it sets the latent
  shape. In `fbc`, the background latent *is* the light source.
- **~11.5 min for the first pair, ~13 s after.** `LoadAndApplyICLightUnet`
  spends most of a cold pair adding patches; subsequent pairs reuse the patched
  model.

## Changing this file

1. Edit the graph. **Never** flip `ytflow_verified_iclight` in the same change —
   that marker exists so an unproven graph cannot reach a render.
2. Probe one card+plate pair live and look at the sprite next to the unlit card.
3. Only then set the marker back to `true`, as its own edit, and rewrite
   `_ytflow_note` with what the probe showed.
4. Renumbering nodes is now safe; **renaming** them is not. The four injection
   points are resolved by the `ytflow:` titles in *Manifest titles* above — keep
   those strings byte-identical, or the relight fails at load (Story 13.3).
