"""Re-write one fixed outline with the shipped 12.7 prompts — writing is the only variable.

Story 12.7 Task "재측정". The 12.6 ablation ran the whole scenario chain per arm, so
each arm got a *different* outline (control 8 scenes, arm A 9) and its 어절/WPM numbers
carried that confound — only the device counts were free of it (`ablation.md`, Trap 4).
This driver removes the confound the cheap way: it pins the control run's own outline
(`12-6-live-validation/after_scenes.json` → `structure`, the same one the control
narration was written against) and re-runs *only* the writing half against it.

The seam is `scenario.structure_step`, replaced by a coroutine that returns a deep copy
of the pinned outline and then runs the SHIPPING annotation — `_allocate_devices` imported
from `scenario_chain`, applied exactly as `structure_step` applies it. So the outline is
frozen but the allocation under test is production code, not a copy of it. Everything
downstream (writing, review, critic, scene repair) is the real chain, fetching the real
`production` prompts from Langfuse.

**What is still NOT pinned:** the research stage runs live, so `frozen_descriptor`,
`entity_sheet`, `story_logline` and `story_archetype` are regenerated per invocation —
and all four are writing-stage inputs. Pinning the outline removes the confound the
ablation had; it does not make the run hermetic. The research payload is therefore
dumped under `research` so a later reader can check how far it moved rather than guess.

    uv run python _bmad-output/implementation-artifacts/12-7-live-validation/run_writing_only.py \
        --out _bmad-output/implementation-artifacts/12-7-live-validation/after_scenes.json

Output shape matches `run_ablation.py`'s so `count_devices.py` and `measure_script.py`
read it unchanged.
"""

import argparse
import asyncio
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from yt_flow.pipeline.nodes import scenario as sc  # noqa: E402
from yt_flow.pipeline.nodes.scenario_chain import _allocate_devices  # noqa: E402

CONTROL = HERE.parent / "12-6-live-validation" / "after_scenes.json"


def _display(path: Path) -> str:
    """Repo-relative when it can be — never raise AFTER a paid live run."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outline", type=Path, default=CONTROL, help="dump whose `structure` to pin")
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-id", default="12-7-after", help="same id the TTS/measure steps use")
    args = parser.parse_args()

    control = json.loads(args.outline.read_text(encoding="utf-8"))
    pinned = control["structure"]
    scp_id = control["scp_id"]
    scp_text = control["scp_text"]
    for scene in pinned:  # a re-run of this script must not inherit its own annotation
        scene.pop("assigned_devices", None)

    outline: list[dict] = []

    async def pinned_structure(*_a, **_k):
        scenes = copy.deepcopy(pinned)
        for scene, devices in zip(scenes, _allocate_devices(scenes), strict=True):
            scene["assigned_devices"] = devices
        outline[:] = scenes  # assign, not append: a second call must not double the dump
        return scenes

    sc.structure_step = pinned_structure

    research: dict = {}
    real_research = sc.research_step

    async def capturing_research(*a, **k):
        packet = await real_research(*a, **k)
        research.update(packet)
        return packet

    sc.research_step = capturing_research

    stages: list[dict] = []
    state = {
        "run_id": args.run_id,
        "scp_id": scp_id,
        "scp_text": scp_text,
        "scenes": [],
        "video_path": None,
        "current_stage": "scenario",
        "gate_states": {},
        "prompt_variant": "A",  # Langfuse label variant, i.e. the production prompt
        "error": None,
    }
    out = await sc.scenario_node(state, trace_sink=stages)
    if out.get("error"):
        raise SystemExit(f"scenario failed: {out['error']}")

    scenes = [dict(scene) for scene in out["scenes"]]
    for idx, scene in enumerate(scenes):  # positional pairing, as run_ablation.py does
        if idx < len(outline):
            scene["word_budget"] = outline[idx].get("word_budget")
            scene["assigned_devices"] = outline[idx].get("assigned_devices")

    Path(args.out).write_text(
        json.dumps(
            {
                "run_id": state["run_id"],
                "scp_id": scp_id,
                "scp_text": scp_text,
                "outline_source": _display(args.outline),
                "scenes": scenes,
                "structure": outline,
                # The unpinned writing inputs, recorded so the residual confound is
                # inspectable instead of merely acknowledged.
                "research": {k: research.get(k) for k in
                             ("frozen_descriptor", "entity_sheet", "story_logline", "story_archetype")},
                "allocation": {
                    str(idx + 1): scene.get("assigned_devices") for idx, scene in enumerate(outline)
                },
                "scenario_quality": out.get("scenario_quality"),
                "story_archetype": out.get("story_archetype"),
                "stages": stages,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {args.out}: {len(scenes)} scenes", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
