# 2.5D Parallax Runtime, Models and Licensing (Story 11.5)

Operational reference for the depth-aware background motion renderer. Covers the
licensing decisions, the external DepthFlow runtime, the depth model, and the
live-gate commands.

---

## 1. The renderer ladder

`services/parallax_service.render_motion_clip` tries three rungs in order and
logs plus traces every degradation. A shot that renders flat is always visible
afterwards in `parallax_25d.renderer_counts` on the video span.

| Rung | Name | Runtime needed | Depth cue | Default |
|---|---|---|---|---|
| 1 | `depthflow` | External AGPL venv + headless OpenGL | Ray-marched, inpainted | **off** |
| 2 | `depth_warp` | none (numpy + PIL + ffmpeg) | Depth-proportional displacement | **on** |
| 3 | `legacy` | none | none (flat Ken Burns) | fallback only |

Rung 2 is the production renderer today. Rung 1 stays off until the target-host
spike in §3 is run and Jay accepts the output.

Kill switch: `YTFLOW_PARALLAX_25D_ENABLED=false` disables depth resolution and
the renderer entirely, restoring Story 7.3/11.3 zoompan behaviour — the same
filtergraph, but **not byte-identical output**. Three constants moved for both
paths and are not switch-gated: `video._MACRO_PAN_RESERVE_PX` widened the
motion-safe box (`CHAR_MAX_W/H`, `_GROUND_Y_MAX`), which moved
`compositing_service._CARD_HEIGHT_FRAC`, and `_DEFAULT_GROUND` was re-measured
against the Apache-2.0 Small checkpoint §2 mandates. Cards are ~6.7% shorter and
the ground clamp is tighter either way. The switch rolls back the *renderer*,
not the render.

---

## 2. Depth model — licensing decision

Depth maps come from ComfyUI's `DepthAnythingV2Preprocessor`
(`comfyui_controlnet_aux`), driven by
`services/compositing_service.depth_map_file`.

**Weight licensing (upstream-verified 2026-08-03):**

| Checkpoint | Params | License | Usable here |
|---|---|---|---|
| `depth_anything_v2_vits.pth` | 24.8M | **Apache-2.0** | **yes — the default** |
| `depth_anything_v2_vitb.pth` | 97.5M | CC-BY-NC-4.0 | no |
| `depth_anything_v2_vitl.pth` | 335.3M | CC-BY-NC-4.0 | no |
| `depth_anything_v2_vitg.pth` | — | CC-BY-NC-4.0 | no |

**Decision:** the pipeline produces potentially monetized YouTube video, which is
commercial use, so only the Apache-2.0 Small checkpoint may run. This is
*enforced*, not documented: `depth_contract()` raises
`NonCommercialDepthModel` for anything else — including an unrecognised
checkpoint name, because guessing a license is the failure mode.

Research-only override (never for a published render):

```
YTFLOW_DEPTH_ALLOW_NONCOMMERCIAL_MODEL=true
YTFLOW_DEPTH_MODEL_CKPT=depth_anything_v2_vitl.pth
```

**Correction this story applied:** Story 8.16 shipped with
`depth_anything_v2_vitl.pth` hardcoded in
`data/workflows/comfyui_depth_anything_v2_api.json` and a depth cache keyed on
the plate's bytes *alone*. Both are fixed: the checkpoint and resolution now come
from config and are injected per call, and the cache key covers the estimator
contract — so changing the model invalidates exactly the dependent maps instead
of serving Large-model maps forever. The 42 Large-model maps from 8.16 remain in
`workspace/cache/depth/` as unreachable legacy artifacts (no provenance sidecar →
permanent cache miss); they are regenerable and safe to delete.

Weights are **not** committed. ComfyUI downloads them on first use into its own
`models/` tree.

### Provenance sidecar

Every depth map is published atomically (temp → rename) with a
`<sha>.json` sidecar written **last**, so a crash between the two is a cache miss
rather than a lie:

```json
{
  "source_sha256": "...", "depth_sha256": "...",
  "source_size": [1920, 1080], "depth_size": [1820, 1024],
  "estimator": "DepthAnythingV2Preprocessor",
  "model_ckpt": "depth_anything_v2_vits.pth",
  "model_license": "Apache-2.0",
  "resolution": 1024, "preproc_version": "1",
  "convention": "relative-brighter-nearer"
}
```

`convention` matters: DepthAnything V2 "Relative" emits **brighter = nearer**. A
consumer that assumes the opposite inverts every parallax layer.

---

## 3. DepthFlow — AGPL compliance decision

Upstream: <https://github.com/BrokenSource/DepthFlow>, version 1.0.0, Python
`>=3.10`, **AGPL-3.0**. Direct dependencies include numpy, Pillow, scipy, torch,
torchvision, transformers and ShaderFlow.

**Decision: DepthFlow is an external tool, never a yt.flow dependency.**

Rationale, and what it turns on:

1. **No distribution.** yt.flow is a private single-operator pipeline. It is not
   conveyed to anyone, so AGPL §5/§6 source-distribution obligations are not
   triggered.
2. **No network interaction with DepthFlow.** AGPL §13's remote-network clause
   applies to users interacting with the *AGPL program* over a network. DepthFlow
   is invoked as a local subprocess that writes a file; nobody interacts with it
   remotely. The yt.flow API never exposes it.
3. **Program output is not a derivative work.** The rendered clips carry no
   AGPL obligation.
4. **No linking, no vendoring.** It lives in its own virtualenv and is driven
   through `scripts/depthflow_render.py` over a JSON spec file. `pyproject.toml`
   must never list `depthflow` or `shaderflow` — there is a test asserting this
   (`test_depthflow_is_not_a_project_dependency`).

**If yt.flow is ever distributed or offered as a network service, revisit this.**
At that point either drop to rung 2 (no AGPL code involved at all) or comply with
AGPL-3.0 in full.

Out-of-process isolation buys three things at once and is not optional:
AGPL isolation, OpenGL/context-cleanup isolation, and keeping torch/ShaderFlow
out of the pipeline's dependency graph.

### Installing the external runtime

```bash
# A venv that is NOT yt.flow's. Pin the exact tested release, never floating main.
uv venv --python 3.12 ~/.venvs/depthflow
uv pip install --python ~/.venvs/depthflow/bin/python 'depthflow==1.0.0'
```

Then enable it:

```
YTFLOW_DEPTHFLOW_ENABLED=true
YTFLOW_DEPTHFLOW_PYTHON=/home/<user>/.venvs/depthflow/bin/python
YTFLOW_DEPTHFLOW_TIMEOUT_SEC=180
```

> **Status: not yet spiked.** `scripts/depthflow_render.py` drives upstream's
> documented `DepthScene` surface (`state.offset_x/offset_y/zoom/rotate`,
> `main(output=…, fps=…, time=…, ssaa=…)`) but has **not** been executed on the
> target host — that needs a GPU/headless-OpenGL session. Until it is, leave
> `depthflow_enabled=false`. An API mismatch exits with code 3, which the adapter
> classifies as `unavailable` and degrades to rung 2 with a warning, so a wrong
> guess costs a log line, not a broken pipeline.
>
> Do not substitute the ComfyUI Depthflow node pack. It is also AGPL-3.0 and adds
> custom-node/Flex version coupling on top.

### Runner exit codes → failure taxonomy

| Code | Adapter classification | Operator action |
|---|---|---|
| 0 | success | — |
| 3 | `unavailable` | install/upgrade the DepthFlow venv |
| 4 | `headless_gl_failure` | fix the GPU driver / EGL setup |
| 1 | `render_failed` | read the traceback in the log |
| (timeout) | `timeout` | raise `depthflow_timeout_sec` |

---

## 4. Tunable settings

| Setting | Default | Notes |
|---|---|---|
| `parallax_25d_enabled` | `true` | AC9 kill switch — off restores the pre-11.5 *renderer* (see §1 for what it does **not** roll back) |
| `parallax_displacement_frac` | `0.02` | Peak visible displacement, fraction of frame **width**. Validated to the 1–3% band |
| `depth_model_ckpt` | `depth_anything_v2_vits.pth` | Apache-2.0 only unless overridden |
| `depth_model_resolution` | `1024` | Estimator input resolution |
| `depth_allow_noncommercial_model` | `false` | Research renders only |
| `depthflow_enabled` | `false` | Rung 1 |
| `depthflow_python` | `""` | External venv interpreter |
| `depthflow_timeout_sec` | `180` | Per-shot bound |

Why 1–3%: wider and the disoccluded band behind a foreground object becomes a
rubber smear (rung 2 stretches disocclusions, it cannot inpaint them); narrower
and there is no readable depth cue. `camera_path.clamp_displacement` forces the
configured value into the band.

Card layers move at a closed, server-owned fraction of the plate's excursion,
keyed on the existing `near | mid | far` enum — never a number an LLM emits:

```
far 0.60   mid 0.70   near 0.80
```

`video._MACRO_PAN_RESERVE_PX` reserves the analytic ceiling of that
(3% × 1920 × 0.80 = 46.08px per side) inside the motion-safe card box, which is
why `CHAR_MAX_H` moved 796.34 → 743.28 and `compositing_service._CARD_HEIGHT_FRAC`
moved with it.

---

## 5. Operations

### Backfill depth maps for the approved plate library

Non-destructive by construction: never opens an approved plate for writing, never
touches a `LocationPlate` row or the asset manifest, isolates per-plate failures,
and is free to re-run (a valid pair is a verified cache hit).

```bash
uv run python scripts/backfill_location_depth_maps.py            # approved only
uv run python scripts/backfill_location_depth_maps.py --all      # include drafts
uv run python scripts/backfill_location_depth_maps.py --dry-run  # report only
```

Requires ComfyUI reachable at `comfyui_url`. Exit code 1 means at least one plate
failed or its file is missing.

### Reading the trace

The video span carries:

```json
"parallax_25d": {
  "enabled": true,
  "displacement_frac": 0.02,
  "layer_ratios": {"far": 0.6, "mid": 0.7, "near": 0.8},
  "renderer_counts": {
    "depth_warp": 52, "legacy": 2,
    "fallback_no_depth_map": 2, "cache_hit": 11, "latency_ms": 812340
  }
}
```

`legacy > 0` with a `fallback_*` key beside it is a degraded run. The image span
carries `depth_hit` / `depth_miss` / `depth_unavailable` for the estimator side.

### Performance

Measured on the target host (RX 9060 XT box, 16 cores), 1920×1080 rung 2:

| Implementation | ms/frame |
|---|---|
| whole-frame pass, 2D fancy indexing | 250 |
| `np.take` + in-place lerp | 159 |
| + 32 row blocks (working set fits L3) | 101 |
| + 4 worker threads over those blocks | 53 |

End to end including the ffmpeg encode: **~71 ms/frame**, i.e. ~7.1s for a
4-second clip. A full ~8-minute video (~12,250 frames) costs roughly 14 minutes
of warping, which is what keeps the run inside the PRD's two-hour ceiling. The
knobs are `WARP_ROW_BLOCKS` and `WARP_WORKERS` in `parallax_service`.
