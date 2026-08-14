"""Story 13.3 AC9 live gate: title-resolved injection still lands, provenance is populated.

Runs the SHIPPED code path — ``image._load_workflow`` (which resolves
``ytflow:positive_prompt`` / ``ytflow:negative_prompt`` by title, with no id
fallback), ``image._inject_prompts``, ``comfyui_client.submit_and_fetch`` — plus
``image._build_provenance`` against the live server, so nothing here re-implements
what it is validating.

Two submissions, one prompt each, deliberately unlike each other: if injection
resolved to the wrong node (or to nothing) the two frames would be identical or
both empty. Also submits a renumbered copy of the same graph — the exact failure
mode this story removes — to prove resolution is by title and not by position.

    cd <repo> && PYTHONPATH=$PWD/src uv run python \
        _bmad-output/implementation-artifacts/13-3-live-validation/run_probe.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from yt_flow.config import Settings  # noqa: E402
from yt_flow.pipeline.nodes import image as img  # noqa: E402
from yt_flow.services import comfyui_client  # noqa: E402

OUT = Path(__file__).parent
PROMPTS = {
    "corridor": "A dim utilitarian facility corridor, exposed pipes along the ceiling, hazard stripes on the floor",
    "autopsy": "A stainless steel autopsy suite, drain channels in the tiled floor, overhead surgical lamp",
}


def _renumber(workflow: dict, offset: int = 700) -> dict:
    """What the ComfyUI UI does on re-export: every id moves, every link follows."""
    remap = {nid: str(int(nid) + offset) for nid in workflow}

    def relink(v):
        return [remap[str(v[0])], v[1]] if isinstance(v, list) and len(v) == 2 and str(v[0]) in remap else v

    return {remap[nid]: {**n, "inputs": {k: relink(v) for k, v in n["inputs"].items()}}
            for nid, n in workflow.items()}


async def main() -> int:
    s = Settings()
    template, nodes = img._load_workflow(s.comfyui_workflow_path)
    stats = await comfyui_client.get_system_stats(s.comfyui_url)
    provenance = img._build_provenance(s.comfyui_workflow_path, template, nodes, stats)
    print("resolved nodes:", nodes)
    print("provenance:", json.dumps(provenance, indent=2))

    for name, prompt in PROMPTS.items():
        wf = img._inject_prompts(template, nodes, prompt, "lowres, watermark", 13300001)
        data = await comfyui_client.submit_and_fetch(s.comfyui_url, wf)
        (OUT / f"raw_{name}.png").write_bytes(data)
        print(f"{name}: {len(data)} bytes")

    # The regression this story exists for: the same graph, every node renumbered.
    renumbered = _renumber(template)
    r_nodes = comfyui_client.resolve_nodes(renumbered, (img.POSITIVE_KEY, img.NEGATIVE_KEY))
    print("renumbered nodes:", r_nodes)
    wf = img._inject_prompts(renumbered, r_nodes, PROMPTS["corridor"], "lowres, watermark", 13300001)
    data = await comfyui_client.submit_and_fetch(s.comfyui_url, wf)
    (OUT / "raw_renumbered.png").write_bytes(data)
    print(f"renumbered: {len(data)} bytes")

    (OUT / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
