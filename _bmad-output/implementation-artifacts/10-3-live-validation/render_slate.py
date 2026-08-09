#!/usr/bin/env python
"""Story 10.3 — replay Story 10.1's 6-shot slate at production settings.

Reads each slate shot's `image_prompt` / `negative_prompt` / `seed` from the run
`8a9a288b` sidecars and submits them against a given workflow JSON, injecting
exactly the way `pipeline/nodes/image.py` does (node "6" positive, node "7"
negative, `seed` into every `KSampler`). Everything else — 1344x768, 30 steps,
cfg 7.5, dpmpp_2m/karras — comes from the workflow file itself, so before/after
differ only by the LoRA chain.

The "before" leg must be re-run against `before/workflow_before.json` — the
pre-fix graph preserved beside the frames — NOT against the live workflow file,
which no longer chains horror.safetensors. Pointing both legs at the live file
turns the A/B into an after/after comparison that still looks like evidence.

Run:
  EVID=_bmad-output/implementation-artifacts/10-3-live-validation
  uv run python $EVID/render_slate.py $EVID/before/workflow_before.json $EVID/before
  uv run python $EVID/render_slate.py \
      data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json $EVID/after
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from yt_flow.services.comfyui_client import submit_and_fetch

BASE_URL = "http://127.0.0.1:8188"
LOG = Path.home() / "workspaces/ComfyUI/user/comfyui.log"
# Anchored to this file, not to cwd, so the documented replay works from anywhere.
REPO = Path(__file__).resolve().parents[3]
SIDECARS = REPO / "workspace/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d/images"
SLATE = [
    "scene_001_S00101", "scene_001_S00102", "scene_001_S00104",
    "scene_002_S00202", "scene_002_S00203", "scene_004_S00403",
]


async def main(workflow_path: str, out_dir: str) -> int:
    raw = json.loads(Path(workflow_path).read_text(encoding="utf-8"))
    # Some workflows carry ytflow_verified_* / _ytflow_note scalars beside the graph.
    template = {k: v for k, v in raw.items() if isinstance(v, dict) and "class_type" in v}
    if template.get("6", {}).get("class_type") != "CLIPTextEncode":
        sys.exit(f"{workflow_path}: node '6' is not the positive CLIPTextEncode")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    offset = LOG.stat().st_size
    for shot in SLATE:
        sc = json.loads((SIDECARS / f"{shot}_done.json").read_text(encoding="utf-8"))
        graph = json.loads(json.dumps(template))
        graph["6"]["inputs"]["text"] = sc["image_prompt"]
        graph["7"]["inputs"]["text"] = sc["negative_prompt"]
        for node in graph.values():
            if node.get("class_type") == "KSampler":
                node["inputs"]["seed"] = int(sc["seed"])
        t0 = time.time()
        img = await submit_and_fetch(BASE_URL, graph, poll_interval=3.0, max_polls=600)
        (out / f"{shot}.png").write_bytes(img)
        print(f"{shot} seed={sc['seed']} {len(img)}B {time.time() - t0:.1f}s", flush=True)

    if LOG.stat().st_size < offset:
        sys.exit("comfyui.log rotated mid-run; the error counts would be meaningless")
    window = LOG.read_bytes()[offset:].decode("utf-8", "replace").splitlines()
    counts = (sum("lora key not loaded" in ln for ln in window),
              sum("ERROR lora" in ln and "invalid for input of size" in ln for ln in window))
    print(f"log window from offset {offset}: {len(window)} lines, "
          f"lora key not loaded={counts[0]}, ERROR lora invalid size={counts[1]}")
    (out / "_log_window.txt").write_text(
        f"workflow={workflow_path} offset={offset} lines={len(window)} "
        f"key_not_loaded={counts[0]} invalid_size={counts[1]}\n" + "\n".join(window)
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2])))
