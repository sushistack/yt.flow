"""Run the real scenario chain on SCP-049 and keep the outline's grounding evidence.

Story 12.8 AC8. Unlike 12.7's driver, **nothing is pinned here**: the outline is what
this story changed, so pinning it would pin the thing under test. Every stage runs live
against the seeded `production` prompts, exactly as `scenario_node` does in a real run.

What the driver adds over calling the node directly is a capture of the two things the
gate payload bounds and clips: the raw `grounding_sink` notes (`_bounded` caps the
payload at 20 and clips each field to 600 chars) and the full outline including each
`fact_references` item's `quote` / `quote_verified`. `after.md` quotes those, and
`attribute.py` reads the dump's `scenes` + `structure` + `scenario_quality`.

    uv run python _bmad-output/implementation-artifacts/12-8-live-validation/run_outline.py \
        --out _bmad-output/implementation-artifacts/12-8-live-validation/run1_scenes.json

Output shape is `run_writing_only.py`'s plus `outline_grounding_raw`, so
`count_devices.py`, `measure_script.py` and `attribute.py` all read it unchanged.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from yt_flow.pipeline.nodes import scenario as sc  # noqa: E402

SCPS = ROOT / "data" / "scps.json"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scp", default="SCP-049")
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-id", default="12-8-run1")
    args = parser.parse_args()

    catalog = json.loads(SCPS.read_text(encoding="utf-8"))
    record = next((item for item in catalog if item["id"] == args.scp), None)
    if record is None:  # a bare StopIteration names neither the id nor the alternatives
        raise SystemExit(
            f"unknown --scp {args.scp!r}; {SCPS} has: {', '.join(item['id'] for item in catalog)}"
        )
    scp_text = record["scp_text"]

    outline: list[dict] = []
    notes: list[dict] = []
    real_structure = sc.structure_step

    async def capturing_structure(*a, grounding_sink=None, **k):
        # The production stage, called with the production arguments — the only thing
        # added is a sink of our own, merged into the caller's if it passed one. A copy
        # of `structure_step`'s body here would be a copy that can drift.
        sink: list[dict] = []
        scenes = await real_structure(*a, grounding_sink=sink, **k)
        if grounding_sink is not None:
            grounding_sink.extend(sink)
        notes[:] = sink        # assign, not append: a second call must not double the dump
        outline[:] = scenes
        return scenes

    sc.structure_step = capturing_structure

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
        "scp_id": args.scp,
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

    Path(args.out).write_text(
        json.dumps(
            {
                "run_id": state["run_id"],
                "scp_id": args.scp,
                "scp_text": scp_text,
                "scenes": [dict(scene) for scene in out["scenes"]],
                "structure": outline,
                # RAW, before `_bounded` caps at 20 and clips each field to 600 chars —
                # a summary computed from a capped list is the 12.6 review's own finding.
                "outline_grounding_raw": notes,
                "research": {k: research.get(k) for k in
                             ("frozen_descriptor", "entity_sheet", "story_logline", "story_archetype")},
                "scenario_quality": out.get("scenario_quality"),
                "story_archetype": out.get("story_archetype"),
                "stages": stages,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"wrote {args.out}: {len(out['scenes'])} scenes, {len(notes)} grounding note(s)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
