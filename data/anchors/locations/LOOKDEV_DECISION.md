# Location plate look-dev decision

**Date:** 2026-08-02
**Decided by:** Jay (visual selection from 4 generated candidates)
**Chosen anchor:** `style_anchor.png` — candidate 4 of 4

## Frontier vs local

Local ComfyUI (Story 8.5 AC10). The candidates were rendered on the project's own
stack — AnimagineXL v3.1 + horror/darkness LoRAs, the same models the plate batch
uses — so the anchor is drawn from the distribution it will condition, and no
frontier-model licensing or content-filter question arises. Runtime generation
stays local regardless of look-dev outcome (epic constraint).

## What was chosen and why

Candidate 4 reads as a facility corridor with the vanishing point opening into
light: mid-tone concrete, exposed ceiling pipework, yellow floor hazard lines,
no people, no legible signage. It sits between the darkest candidate (1, heavy
pipe density and almost no ambient light) and the brightest, highest-contrast one
(3). That middle position matters because a single anchor conditions all 14
location keys: an anchor that is too dark fights the rooms that must read as
clean and lit (medical bay, cafeteria, office), and one that is too bright drains
the pressure from the containment-side rooms.

## How it is applied

IPAdapter, weight 0.4, `ip-adapter-plus_sdxl_vit-h`, on every plate in the batch
(`data/workflows/comfyui_location_plate_api.json`, node 23). Replacing this file
changes the look of every plate generated afterwards but not plates already on
disk — bump the style epoch rather than swapping it silently.
