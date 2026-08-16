# ComfyUI environment pin (Story 13.3 AC6)

`env-snapshot.json` is a ComfyUI-Manager **full snapshot** of the GPU host that
produces this project's renders: the ComfyUI core commit, every custom node's
commit/version, and a pip freeze of ComfyUI's own venv.

It exists because Story 8.7 concluded the IC-Light nodes were absent, then that
conclusion was reversed — a cost paid entirely because nothing in the repo
recorded which ComfyUI produced which render. Its sha256 is written into every
render's sidecar as `provenance.env_snapshot_sha256`, so a bad batch can be tied
to an environment instead of re-litigated from memory.

## How ComfyUI must be started

Two graphs in this pipeline are not satisfied by a stock `python main.py`. The
requirement is **declared once in code** —
`src/yt_flow/services/recompose_service.py`'s `REQUIRED_FLAGS` — and **that table
is authoritative**: this section restates it for operators and must be updated in
the same commit that changes it, or it becomes a stale second copy. Story 10.1d's
preflight reads the running server's own `system.argv` from `/system_stats` and
refuses the recompose path when any of it is missing (or, for `--cache-lru`,
present with a non-positive value — ComfyUI's `main.py` enables the LRU cache only
when it is `> 0`, so `--cache-lru 0` is the default behaviour wearing a flag).

**Append these to the launcher you already use — do not replace it.** On this
machine ComfyUI starts from `~/workspaces/ComfyUI/run.sh`, and a bare
`python main.py …` pasted over it loses the venv, the ROCm override and
`--preview-method auto`:

```bash
source venv/bin/activate                       # already in run.sh — keep it
export HSA_OVERRIDE_GFX_VERSION=12.0.0         # RDNA 4 detection — keep it
export PYTORCH_HIP_ALLOC_CONF=garbage_collection_threshold:0.8,max_split_size_mb:512
python main.py --preview-method auto --cache-lru 10 \
  --lowvram --disable-smart-memory             # <- what run.sh is still missing
```

| Flag | Why | Measured |
|---|---|---|
| `--lowvram` | weights stream instead of staying resident on the GPU | required by the Qwen recompose graph |
| `--disable-smart-memory` | without it the Qwen recompose graph swap-deadlocks | Story 10.1c. It pays for that with **system** RAM, which is the scarce resource here — do **not** generalise it to the background path, where it was proposed on 2026-08-15 and was the wrong lever |
| `--cache-lru 10` | the default `cache-classic` evicts the checkpoint on every graph alternation | run `e5ed4b3a`: **490 s vs 14.8 s** per shot. Recompose adds a third graph to the alternation. The value must be **> 0**: `--cache-lru 0` is ComfyUI's own default and the preflight rejects it |
| free system RAM ≥ 12 GiB | not a flag — `Settings.recompose_preflight_min_free_ram_gb` | 2026-08-15: 0 free / 4 GB swap on a 31 GB box was already thrashing a lighter path. Calibrated against that failure only — no healthy-run reading exists yet, so a false-bail rate is unmeasured |

`--cache-lru` is **pipeline-wide** operational advice: every path that alternates
graphs pays the eviction cost, and the ordinary background path in `image_node`
has **no** gate for it. Only the recompose preflight enforces any of this. The
fp8 text encoder the recompose graph needs is not startup state at all — it is
pinned in the workflow JSON's `clip` node and fails fast there with ComfyUI's own
error, so the preflight deliberately does not check it.

### Verifying a restart actually took

HTTP 200 is not readiness. Twice in this repo a `curl /system_stats` answered 200
from an **old process that had not died**, so a restart looked successful while
the new instance had exited on a port conflict. Verify the *process*, not the port:

```bash
ss -ltnp 'sport = :8188'        # -> the PID actually holding the socket
cat /proc/<pid>/cmdline | tr '\0' ' '
```

Take the PID from the listening socket. `pkill -f` / `pgrep -f` match the
operator's own shell and have killed the wrong PID here more than once.

## Refresh command

Run it from ComfyUI's own directory, with ComfyUI's own interpreter (the CLI
imports `typer` from that venv, not from yt.flow's):

```bash
YTFLOW_REPO=$(git -C /path/to/yt.flow rev-parse --show-toplevel)   # or just cd into it first
cd "$HOME/workspaces/ComfyUI"
./venv/bin/python custom_nodes/ComfyUI-Manager/cm-cli.py save-snapshot \
  --output "$YTFLOW_REPO/data/comfyui/env-snapshot.json" \
  --full-snapshot
```

`--output` redirects the file into this repo; without it the snapshot lands in
`<user_dir>/default/ComfyUI-Manager/snapshots/`. The `WARN: The COMFYUI_PATH
environment variable is not set` line it prints is expected — it then assumes
`custom_nodes/ComfyUI-Manager/../../`, which is correct.

Captured 2026-08-14 against ComfyUI `0.12.3` / torch `2.11.0.dev20260206+rocm7.1`
(`comfyui` commit `f350a842611f4d75da7104c2d2965f45989089b9`, 7 git custom nodes,
2 registry custom nodes, 179 pinned pips).

## When to refresh

- Any custom-node install, update or removal.
- Any ComfyUI core update.
- Any change to ComfyUI's venv (a torch/rocm bump above all).

Refreshing changes `provenance.env_snapshot_sha256` for renders made afterwards.
That is the intent, and it is deliberately **not** part of the image stage's
resume comparison — `_existing_complete_shot` compares only `image_prompt`,
`negative_prompt` and `seed`, so a refreshed snapshot never re-renders a cached
background (Story 13.3 AC8).

## Restore

Not automated, on purpose. `cm-cli.py restore-snapshot` works against this file
if a rebuild is ever needed, but it is deferred-on-restart (it writes
`startup-scripts/restore-snapshot.json` and applies on the next ComfyUI boot),
and no pipeline code path wants that. `ponytail:` a committed artifact plus a
documented refresh command is the whole requirement; there is no loader, no
config field and no restore automation.

## Why this directory and not `data/workflows/`

`data/workflows/` is *input the pipeline submits* — six `Settings` fields point
into it and the graphs there are edited as part of feature work. This file is
*a record of the machine*, is regenerated by an external tool rather than
hand-edited, and belongs to no single workflow. Keeping it out of
`data/workflows/` also keeps `tests/test_workflow_definitions.py`'s
`WORKFLOW_DIR.glob("*.json")` — which asserts graph structure on every JSON it
finds — from trying to parse a snapshot as a node graph.

## The other half of the pin

Environment is only half of "what produced this render". The other half is the
graph, and that lives in the same sidecar: `provenance.workflow_path`,
`provenance.workflow_sha256` (the canonical hash of the loaded template *before*
per-shot injection) and `provenance.nodes` (the resolved manifest-title → node-id
map). That pair only covers the **background** graph, though — the one
`image_node` loads. Twelve graphs live in `data/workflows/`, and this is what is
actually pinned:

| Graph | Manifest-resolved by code? | Covered by `test_workflow_definitions.CONSUMER_KEYS`? |
|---|---|---|
| `comfyui_sdxl_anime_lora_workflow_api2.json` | yes — `image._load_workflow` | yes |
| `comfyui_location_plate_api.json` | yes — `scripts/seed_location_plates.py` | yes |
| `comfyui_iclight_relight_api.json` | yes — `composite_harmonization._load_iclight_workflow` | yes |
| `comfyui_character_multi_angle_api.json` | yes — `character_image_provider` | yes |
| `comfyui_character_pose_guide_api.json` | yes — `character_image_provider` (`ytflow:guide_image` is an exact match with **no** fallback) | yes |
| `comfyui_qwen_pose_edit_api.json` | **no** — carries sixteen `ytflow:` titles that no code resolves | **no** (deferred) |
| `comfyui_depth_anything_v2_api.json` | **no** — `compositing_service` still addresses nodes `"1"`/`"2"` by hardcoded id | no (deferred) |
| `comfyui_fusion_img2img_api.json`, `comfyui_shot_recompose_api.json`, `comfyui_shot_recompose_qwen_api.json` | no — `class_type`-scanned by design | n/a |
| `comfyui_sdxl_anime_lora_layered{,_inspyrenet}_api.json` | dead since Story 8.3; the inspyrenet file is the resolver's substring-trap fixture | n/a |

The two "deferred" rows are filed as deferred work, not oversights: the depth
graph's `DEPTH_IMAGE_NODE = "1"` / `DEPTH_MODEL_NODE = "2"` are blind-written on
every generated background (`depth_placement_enabled` ships `True`), and the Qwen
pose-edit graph's `ytflow:` titles are aspirational — nothing reads them, so
renaming one breaks nothing today and would break silently the day it does.

The manifest-bearing graphs document their own keys in
`data/workflows/README-location-plate.md`,
`data/workflows/README-iclight-relight.md` and
`data/workflows/README-character-multi-angle.md` (which covers the pose-guide
variant too); `comfyui_sdxl_anime_lora_workflow_api2.json` has no README of its
own and its two keys are `ytflow:positive_prompt` / `ytflow:negative_prompt`.
