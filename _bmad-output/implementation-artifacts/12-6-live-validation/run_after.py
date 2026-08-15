"""Drive ONE live scenario chain on SCP-049 and dump it for `measure_script.py` (AC8).

Story 12.6 Task 5. The graph is not involved: ``scenario_node`` runs standalone
against the real DeepSeek/Gemini seams (precedent: ``eval_prompts._run_scenario``,
and ``5-22-verification-evidence/verify_5_22.py`` before it), so this exercises the
newly seeded prompts and the new outline validator without spending a GPU-hour on
images or a TTS quota on audio. The cost of that: no ``audio_duration``, so WPM
comes out ``null`` — see ``after.md`` for how the density claim is settled instead.

The one thing this driver adds over the eval runner is capturing the STRUCTURE
outline. `scenario_node` returns built scenes only, and the declared ``word_budget``
is precisely the number Story 12.6 changed — the baseline could not report it
(`SceneState` has no such field and no checkpoint carries the outline), so the after
run has to.

    uv run python _bmad-output/implementation-artifacts/12-6-live-validation/run_after.py \
        --out _bmad-output/implementation-artifacts/12-6-live-validation/after_scenes.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from yt_flow.pipeline.nodes import scenario as sc  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scp-id", default="SCP-049")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scps = json.loads((ROOT / "data" / "scps.json").read_text(encoding="utf-8"))
    entry = next(s for s in scps if s["id"] == args.scp_id)
    scp_text = entry["scp_text"]

    outline: list[dict] = []
    real_structure = sc.structure_step

    async def capturing_structure(*a, **k):
        scenes = await real_structure(*a, **k)
        outline.extend(scenes)
        return scenes

    sc.structure_step = capturing_structure

    stages: list[dict] = []
    state = {
        "run_id": f"12-6-after-{args.scp_id}",
        "scp_id": args.scp_id,
        "scp_text": scp_text,
        "scenes": [],
        "video_path": None,
        "current_stage": "scenario",
        "gate_states": {},
        "prompt_variant": "A",
        "error": None,
    }
    out = await sc.scenario_node(state, trace_sink=stages)
    if out.get("error"):
        raise SystemExit(f"scenario failed: {out['error']}")

    # Merge the declared budget onto its scene positionally — the same pairing rule
    # `build_scenes`/`_repair_and_review` use, because the model's own `scene_num`
    # is known to duplicate and reorder (6.5/6.6).
    scenes = [dict(scene) for scene in out["scenes"]]
    for idx, scene in enumerate(scenes):
        if idx < len(outline):
            scene["word_budget"] = outline[idx].get("word_budget")

    Path(args.out).write_text(
        json.dumps(
            {
                "run_id": state["run_id"],
                "scp_id": args.scp_id,
                "scp_text": scp_text,
                "scenes": scenes,
                "structure": outline,
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
