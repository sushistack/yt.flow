# IC-Light Re-lighting Workflow (Story 8.7, Tier 3)

## Status: unverified graph — but the nodes and weights ARE installed now

> **2026-08-08 correction.** The paragraph below used to say this host had no
> IC-Light nodes. That is **no longer true** and was the basis of a wrong
> "blocked on hardware" conclusion during Story 10.1. Measured on this host:
> [kijai's ComfyUI-IC-Light](https://github.com/kijai/ComfyUI-IC-Light) is
> installed at rev `22811d9` (2026-08-02), `models/unet/iclight_sd15_fbc.safetensors`
> (1.7 GB) is present, and the SD1.5 base that `fbc` needs
> (`models/checkpoints/cyberrealistic_v90.safetensors`, 2.1 GB) is present.
> That is a **~4 GB VRAM class** route. The 16 GB OOM figures in
> `8-20-live-validation/DECISION-RECORD.md` belong to a *different* route
> (Qwen-Image-Edit-2511 GGUF, 13.24 GB, card+pose-guide → new card) and do not
> apply here. So step 1 of "Before enabling" below is **already done**; what
> remains is steps 2–5. Owned by Story 10.1b.

`data/workflows/comfyui_iclight_relight_api.json` is a **structural
placeholder**, not a verified graph. Unlike
`comfyui_character_multi_angle_api.json`/`comfyui_location_plate_api.json`,
this workflow's node graph has **not** been live-verified against a real
ComfyUI submission.

This is by design, not an oversight: Story 8.7's Tier 3 is the last rung of a
cost-ordered ladder (Tier 1 ffmpeg tint+shadow → Tier 2 ffmpeg light wrap →
Tier 3 IC-Light), gated on Tiers 1/2 proving insufficient in A/B review.
`composite_harmonization.relight_sprite()` treats every failure mode —
missing custom nodes included — as non-fatal (AC:11). Code review added a
second guard: a workflow must be explicitly marked with
`"ytflow_verified_iclight": true` before the runtime will submit it. This
placeholder intentionally lacks that marker, so Tier 3 degrades to cache miss
without ever caching a bogus text-to-image output. No run ever fails because of
this file.

## What's real vs placeholder

- **Nodes `"1"`/`"2"` (LoadImage) — real, load-bearing.** These are the only
  nodes `composite_harmonization.py` reads/writes
  (`CARD_IMAGE_NODE`/`BACKGROUND_IMAGE_NODE`): the card sprite and the
  location plate are uploaded via `comfyui_client.upload_image` and injected
  here before submission.
- **Nodes `"3"`–`"9"` — structural placeholder.** A plain SDXL
  checkpoint→CLIPTextEncode→KSampler→VAEDecode→SaveImage chain, reusing this
  project's existing checkpoint. The real IC-Light pipeline patches the UNet
  with a foreground/background-conditioned latent (typically over an SD1.5
  checkpoint) — this placeholder does **not** do that; it will produce a
  generic text-to-image render unrelated to the two input images once IC-Light
  nodes are actually available, or fail validation entirely if the checkpoint
  key doesn't resolve locally.

## Before enabling `composite_harmonization_tier=3` for real

1. ~~Install an IC-Light custom-node pack into `$HOME/workspaces/ComfyUI/custom_nodes/`.~~
   **Done 2026-08-02** — kijai `ComfyUI-IC-Light` @ `22811d9`, plus
   `iclight_sd15_fbc.safetensors`. Use **v1 `fbc` only**: v2/Flux variants are
   non-commercial and this pipeline is monetized.
2. Replace nodes `"3"`–`"9"` with the real IC-Light node graph (unet patch,
   foreground/background conditioning, matching checkpoint).
3. Re-run `composite_harmonization.relight_sprite()` against a live ComfyUI
   instance with a real card+plate pair and confirm a plausible relit PNG
   comes back — this is the "live validation" step the story's own Tasks
   list defers pending Tiers 1/2's A/B outcome.
4. Add `"ytflow_verified_iclight": true` to the workflow JSON only after that
   live validation passes.
5. Update this README once verified, mirroring
   [`README-character-multi-angle.md`](README-character-multi-angle.md)'s
   documented/live-checked node list.
