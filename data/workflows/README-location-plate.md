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

| Node | Manifest title | What the seed script does with it |
|---|---|---|
| `"6"` | `ytflow:positive_prompt` | writes the per-plate prompt |
| `"7"` | `ytflow:negative_prompt` | writes `PLATE_NEGATIVE_PROMPT` |
| `"3"` | `ytflow:sampler` | writes the seed; `--anchor-candidates` rewires its `model`/`positive`/`negative` links |
| `"5"` | `ytflow:latent` | writes the 1344×768 render bucket |
| `"11"` | `ytflow:model` | t2i-fallback target — the second `LoraLoader`, the sampler's model source once IPAdapter is stripped |
| `"20"` | `ytflow:style_anchor` | first anchor image; extra anchors are batched as derived ids |
| `"23"` | `ytflow:ipadapter` | writes the IPAdapter weight and the batched anchor link |
| `"31"` | `ytflow:structure_hint` | writes the uploaded reference/blockout filename |
| `"33"` | `ytflow:scribble` | dropped entirely on the blockout path |
| `"32"` | `ytflow:controlnet_apply` | writes `strength`, and its `image` link is repointed at `ytflow:structure_hint` on the blockout path |
| `"30"` | `ytflow:controlnet_loader` | dropped on the t2i-fallback path |

## What those titles used to say

Six of the eleven carried explanatory prose in `_meta.title` before Story 13.3
replaced it with the manifest key. The prose is the measured rationale for the
values in this graph, so it is preserved here verbatim:

- `"20"`: *Style Anchor Reference (uploaded per-run; seed script batches additional anchors as 20_extra_N / 20_batch_N)*
  — the derived ids are now built from the *resolved* anchor node id, i.e.
  `<anchor_id>_extra_N` / `<anchor_id>_batch_N`, which is `20_extra_N` /
  `20_batch_N` for as long as the anchor node keeps id `"20"`.
- `"23"`: *IPAdapter (style transfer only — anchor must not impose its corridor layout)*
- `"30"`: *Scribble ControlNet (SDXL)*
- `"31"`: *Structure hint — a curated reference photo (default) or the procedural room blockout (fallback); the seed script uploads one per plate*
- `"33"`: *scribble_hed — the only thing the reference photo is allowed to contribute: line structure, never pixels*
- `"32"`: *Apply structure hint — strength 0.9/end 0.7: at 0.55/0.55 the library was still 69% corridors, i.e. a hint the sampler ignored*

Nodes `"6"`/`"7"` read `Positive Prompt` / `Negative Prompt`; `"3"`, `"5"` and
`"11"` had no title at all — `"11"` in particular was addressed purely as the
string `"11"` by the t2i-fallback rewiring.

## Copyright note (unchanged by 13.3)

The curated reference photo is uploaded to `ytflow:structure_hint` and nowhere
else, and that node feeds only the scribble preprocessor. It never reaches the
IPAdapter (`ytflow:ipadapter`, whose image input is the style-anchor batch) and
never reaches the latent (`ytflow:latent` is an `EmptyLatentImage`). What the
sampler sees of somebody's photograph is a line drawing.
