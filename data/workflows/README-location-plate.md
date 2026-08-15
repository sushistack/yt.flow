# Location Plate Workflow (Story 8.5 / 8.17)

`data/workflows/comfyui_location_plate_api.json` — the graph
`scripts/seed_location_plates.py` drives to render the stock location library
(14 keys × 3 variants) that `image_node` substitutes for generated backgrounds.

It is the most heavily injected workflow in the repo: the seed script writes
eleven of its nodes, and three of those writes are **link rewrites** (`["31", 0]`
style edges), not just widget values. A node renumber therefore used to produce a
structurally valid but wrong graph — which is why every one of the eleven is now
addressed by declared title (Story 13.3) and none by node id.

## Manifest titles (Story 13.3)

`_meta.title` on an injection target is a **contract string**, not a label:
`comfyui_client.resolve_nodes` matches it exactly, and a missing or duplicated
title raises at workflow load, before any GPU is spent. Renaming one of these in
the ComfyUI UI is a breaking change.

Node ids are deliberately **not** listed here: they are what this story stopped
being the contract, and a table of them is the first thing to go stale after the
exact renumber it was written about. `scripts/seed_location_plates.py`'s
`PLATE_NODE_CLASSES` is the authority on what each title must be, and
`_load_workflow` enforces it at load — so a title moved onto the wrong node fails
before any GPU is spent, not just a title that went missing.

| Manifest title | Must be a | What the seed script does with it |
|---|---|---|
| `ytflow:positive_prompt` | `CLIPTextEncode` | writes the per-plate prompt |
| `ytflow:negative_prompt` | `CLIPTextEncode` | writes `PLATE_NEGATIVE_PROMPT` |
| `ytflow:sampler` | `KSampler` | writes the seed; `--anchor-candidates` rewires its `model`/`positive`/`negative` links |
| `ytflow:latent` | `EmptyLatentImage` | writes the 1344×768 render bucket |
| `ytflow:model` | `LoraLoader` | t2i-fallback target — the second LoRA loader, the sampler's model source once IPAdapter is stripped |
| `ytflow:style_anchor` | `LoadImage` | first anchor image; extra anchors are batched as derived ids |
| `ytflow:ipadapter` | `IPAdapterAdvanced` | writes the IPAdapter weight and the batched anchor link |
| `ytflow:structure_hint` | `LoadImage` | writes the uploaded reference/blockout filename |
| `ytflow:scribble` | `FakeScribblePreprocessor` | dropped entirely on the blockout path |
| `ytflow:controlnet_apply` | `ControlNetApplyAdvanced` | writes `strength`, and its `image` link is repointed at `ytflow:structure_hint` on the blockout path |
| `ytflow:controlnet_loader` | `ControlNetLoader` | dropped on the t2i-fallback path |

## What those titles used to say

Six of the eleven carried explanatory prose in `_meta.title` before Story 13.3
replaced it with the manifest key. The prose is the measured rationale for the
values in this graph, so it is preserved here verbatim (keyed by the manifest
title that replaced it):

- `ytflow:style_anchor`: *Style Anchor Reference (uploaded per-run; seed script batches additional anchors as 20_extra_N / 20_batch_N)*
  — that parenthetical is now wrong in its specifics and right in its shape:
  `_inject_anchors` builds the derived ids from the *resolved* anchor node id, as
  `<anchor_id>_extra_N` / `<anchor_id>_batch_N`. Whatever the anchor node is
  numbered, the batch nodes follow it.
- `ytflow:ipadapter`: *IPAdapter (style transfer only — anchor must not impose its corridor layout)*
- `ytflow:controlnet_loader`: *Scribble ControlNet (SDXL)*
- `ytflow:structure_hint`: *Structure hint — a curated reference photo (default) or the procedural room blockout (fallback); the seed script uploads one per plate*
- `ytflow:scribble`: *scribble_hed — the only thing the reference photo is allowed to contribute: line structure, never pixels*
- `ytflow:controlnet_apply`: *Apply structure hint — strength 0.9/end 0.7: at 0.55/0.55 the library was still 69% corridors, i.e. a hint the sampler ignored*

The prompt encoders read `Positive Prompt` / `Negative Prompt`; the sampler, the
latent and the LoRA loader had no title at all — the LoRA loader in particular
was addressed purely as the string `"11"` by the t2i-fallback rewiring.

## Copyright note (unchanged by 13.3)

The curated reference photo is uploaded to `ytflow:structure_hint` and nowhere
else, and that node feeds only the scribble preprocessor. It never reaches the
IPAdapter (`ytflow:ipadapter`, whose image input is the style-anchor batch) and
never reaches the latent (`ytflow:latent` is an `EmptyLatentImage`). What the
sampler sees of somebody's photograph is a line drawing.
