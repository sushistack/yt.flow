#!/usr/bin/env python
"""Story 10.3 — attribute the ComfyUI LoRA load errors to a specific file.

Submits a tiny render (512x512, 4 steps) against AnimagineXL v3.1 in four LoRA
configs and counts the two error classes emitted into ~/workspaces/ComfyUI/user/
comfyui.log *inside that submission's window only* (byte offset captured just
before POST /prompt).

ComfyUI's default execution cache keeps the previous prompt's node outputs, so a
LoraLoader with byte-identical inputs run twice in a row is served from cache and
logs nothing. To force a fresh patch every time, the configs are interleaved with
`none` runs (which contain no LoraLoader at all and therefore evict the loader
nodes), and every submission uses a fresh seed so the sampler never caches either.

A clean `0 + 0` is only meaningful if the base model was actually (re)loaded and
patched in that window, so the window is required to contain a `Requested to load`
line; otherwise it is reported CACHED. A fresh seed alone is NOT proof — it
relogs the sampler while the LoraLoader above it is still served from cache.

Caveat: comfyui.log is shared. A concurrent client submitting during a window
folds its lines into these counts. Errors can therefore only be over-counted,
never under-counted, so a measured zero stays trustworthy while a non-zero should
be read together with the raw window archived in probe_counts.txt.

Run:  uv run python _bmad-output/implementation-artifacts/10-3-live-validation/probe_lora.py
"""

import asyncio
import json
import re
import struct
import sys
import time
from pathlib import Path

from yt_flow.services.comfyui_client import submit_and_fetch

BASE_URL = "http://127.0.0.1:8188"
LOG = Path.home() / "workspaces/ComfyUI/user/comfyui.log"
MODELS = Path.home() / "workspaces/ComfyUI/models"
OUT = Path(__file__).parent
CKPT = "AnimagineXL_v31.safetensors"

# (lora_name, strength) chain, in production order.
CONFIGS = {
    "both": [("horror.safetensors", 0.6), ("darkness_xl_v2.safetensors", 0.5)],
    "horror_only": [("horror.safetensors", 0.6)],
    "darkness_only": [("darkness_xl_v2.safetensors", 0.5)],
    "none": [],
}
# `none` between each measured config evicts the previous LoraLoader from the cache.
ORDER = ["both", "none", "horror_only", "none", "darkness_only", "none"]

# The key/shape pairs quoted in README.md — sd-scripts (SDXL) naming first, then
# the diffusers (SD1.5) naming horror.safetensors uses. Absent bases are skipped.
QUOTED_BASES = (
    "lora_unet_output_blocks_2_0_in_layers_2",
    "lora_unet_output_blocks_3_0_in_layers_2",
    "lora_unet_output_blocks_3_1_transformer_blocks_0_attn1_to_k",
    "lora_unet_input_blocks_4_1_transformer_blocks_0_attn1_to_q",
    "lora_unet_down_blocks_0_attentions_0_proj_in",
    "lora_unet_up_blocks_0_resnets_0_conv1",
    "lora_unet_mid_block_attentions_0_transformer_blocks_0_attn1_to_k",
)

KEY_NOT_LOADED = re.compile(r"lora key not loaded")
INVALID_SIZE = re.compile(r"ERROR lora .* is invalid for input of size")


def build_graph(chain: list[tuple[str, float]], seed: int) -> dict:
    """Minimal txt2img graph; LoRA nodes chained 10, 11, ... off node 4."""
    graph = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    }
    model, clip = ["4", 0], ["4", 1]
    for i, (name, strength) in enumerate(chain):
        nid = str(10 + i)
        graph[nid] = {"class_type": "LoraLoader", "inputs": {
            "lora_name": name, "strength_model": strength, "strength_clip": strength,
            "model": model, "clip": clip,
        }}
        model, clip = [nid, 0], [nid, 1]
    graph["6"] = {"class_type": "CLIPTextEncode",
                  "inputs": {"text": "masterpiece, best quality", "clip": clip}}
    graph["7"] = {"class_type": "CLIPTextEncode",
                  "inputs": {"text": "lowres, bad anatomy, worst quality", "clip": clip}}
    graph["3"] = {"class_type": "KSampler", "inputs": {
        "seed": seed, "steps": 4, "cfg": 7.5, "sampler_name": "dpmpp_2m",
        "scheduler": "karras", "denoise": 1.0, "model": model,
        "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
    }}
    graph["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    graph["9"] = {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": "ytflow_probe103", "images": ["8", 0]}}
    return graph


async def run_one(name: str, seed: int) -> dict:
    offset = LOG.stat().st_size
    t0 = time.time()
    graph = build_graph(CONFIGS[name], seed)
    err = ""
    try:
        img = await submit_and_fetch(BASE_URL, graph, poll_interval=2.0, max_polls=900)
        nbytes = len(img)
    except Exception as exc:  # noqa: BLE001 — a failed config is a datum, keep going
        nbytes, err = 0, f"{type(exc).__name__}: {exc}"
    await asyncio.sleep(3.0)  # let the log flush
    if LOG.stat().st_size < offset:
        sys.exit("comfyui.log rotated mid-probe; the attribution would be meaningless")
    window = LOG.read_bytes()[offset:].decode("utf-8", "replace")
    lines = window.splitlines()
    return {
        "config": name, "seed": seed, "elapsed": time.time() - t0, "bytes": nbytes,
        "offset": offset, "new_lines": len(lines),
        "key_not_loaded": sum(bool(KEY_NOT_LOADED.search(ln)) for ln in lines),
        "invalid_size": sum(bool(INVALID_SIZE.search(ln)) for ln in lines),
        "got_prompt": sum("got prompt" in ln for ln in lines),
        "model_loads": sum("Requested to load" in ln for ln in lines),
        "error": err,
        "window": window,
    }


async def main() -> int:
    results = []
    report = []
    for i, name in enumerate(ORDER):
        r = await run_one(name, seed=770300 + i)
        results.append(r)
        # No model (re)load in the window means nothing was patched, so a zero here
        # says nothing about the LoRA. Do not let it read as a clean load.
        r["cached"] = r["got_prompt"] == 0 or r["model_loads"] == 0
        flag = "  <-- NO MODEL LOAD IN WINDOW (cached patch, not a real zero)" if r["cached"] else ""
        line = (f"[{i}] {name:14s} seed={r['seed']} {r['elapsed']:6.1f}s "
                f"img={r['bytes']}B new_log_lines={r['new_lines']:4d} "
                f"model_loads={r['model_loads']:2d} "
                f"key_not_loaded={r['key_not_loaded']:4d} invalid_size={r['invalid_size']:4d}"
                f"{' ERR=' + r['error'] if r['error'] else ''}{flag}")
        print(line, flush=True)
        report.append(line)

    header = (f"{'config':16s}{'lora key not loaded':>22s}{'ERROR lora invalid size':>26s}"
              f"{'  status':<10s}")
    print("\n" + header)
    report.append("\n" + header)
    # Every run, not just the first per config — a config that ran three times and
    # disagreed with itself is exactly what a single-row table would hide.
    for r in results:
        status = "CACHED" if r["cached"] else ("ERROR" if r["error"] else "ok")
        row = (f"{r['config']:16s}{r['key_not_loaded']:>22d}{r['invalid_size']:>26d}"
               f"  {status}")
        print(row)
        report.append(row)

    (OUT / "probe_counts.txt").write_text(
        "\n".join(report) + "\n\n" + "=" * 70 + "\n"
        + "\n\n".join(f"--- window [{i}] {r['config']} (offset {r['offset']}) ---\n{r['window']}"
                      for i, r in enumerate(results))
    )
    # A table of zeros produced by failed or cache-served submissions must not exit
    # success — it would read as "every config is clean".
    return 1 if any(r["error"] or r["cached"] for r in results) else 0


def safetensors_header(path: Path) -> dict:
    """Read a .safetensors header without loading any tensor. ponytail: stdlib."""
    with open(path, "rb") as f:
        return json.loads(f.read(struct.unpack("<Q", f.read(8))[0]))


def shapes() -> int:
    """Print the LoRA/checkpoint key-shape evidence quoted in the README."""
    ckpt = safetensors_header(MODELS / "checkpoints" / CKPT)
    for lora in ("horror.safetensors", "darkness_xl_v2.safetensors"):
        h = safetensors_header(MODELS / "loras" / lora)
        keys = [k for k in h if k != "__metadata__"]
        print(f"\n== {lora}: {len(keys)} tensors, metadata={h.get('__metadata__')!r:.90}")
        print(f"   text-encoder prefixes: {sorted({k.split('_text_model')[0] for k in keys if k.startswith('lora_te')})}")
        print(f"   down_blocks_0 attention keys (SD1.5 has these, SDXL does not): "
              f"{len([k for k in keys if 'down_blocks_0_attentions' in k])}")
        for base in QUOTED_BASES:
            dn = h.get(base + ".lora_down.weight", {}).get("shape")
            up = h.get(base + ".lora_up.weight", {}).get("shape")
            if not dn or not up:
                continue
            delta = [up[0], *dn[1:]]  # up @ down collapses the rank dim
            print(f"   {base}\n     down={dn} up={up} -> delta={delta}")
    print(f"\n== {CKPT}: {len([k for k in ckpt if k != '__metadata__'])} tensors")
    for k in ("model.diffusion_model.output_blocks.2.0.in_layers.2.weight",
              "model.diffusion_model.output_blocks.3.0.in_layers.2.weight",
              "model.diffusion_model.output_blocks.3.1.transformer_blocks.0.attn1.to_k.weight",
              "model.diffusion_model.input_blocks.4.1.transformer_blocks.0.attn1.to_q.weight"):
        print(f"   {k} = {ckpt.get(k, {}).get('shape')}")
    return 0


if __name__ == "__main__":
    sys.exit(shapes() if "--shapes" in sys.argv else asyncio.run(main()))
