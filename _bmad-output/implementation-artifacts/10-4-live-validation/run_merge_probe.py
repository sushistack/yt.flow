#!/usr/bin/env python
"""Story 10.4 — the decisive probe: does merging help WHEN IT ACTUALLY HAPPENS?

PASS B (§10) could not answer the mapping question, because the model merged 11
adjacent pairs positionally and left all four AC3 sentences alone. So this probe stops
asking the model to choose and hands it a **hand-authored cover** over scenes 3 and 7 —
the two scenes carrying ``S00303`` and ``S00708``.

The merge list comes from a rule written down BEFORE any score was read (README §12.1):
*a sentence merges iff, read on its own, it names no place, no physical object/body
part/surface, and no physical change or motion.* ``HAND_COVER`` below is that rule's
output, frozen.

    uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_merge_probe.py

Two arms, cheapest first:

* **M1 — zero renders.** Re-score the control's EXISTING frame for a span's first
  sentence against the **joined** text of the whole span. Asks exactly: is the
  neighbour's frame, now carrying both sentences, better than the fabricated frame the
  merged sentence got on its own? Nothing is re-rendered; ``ab2_old/`` is read only.
* **M2 — 12 renders.** Re-run the shipped ``visual_breakdown_step`` with the cover
  **dictated** in the prompt, so the model authors an ``image_prompt`` *for the merged
  span* rather than deciding whether to merge. Same seeds and same checkpoint negatives
  as every other leg.

Control for both arms is the already-scored ``ab2_old`` leg (the bijection), restricted
to these two scenes. It is never re-rendered and never re-scored.

Outputs: ``probe_m2_shots.json``, ``probe_m1.json``, ``probe_m2.json``,
``probe_result.json``, renders in ``probe_m2/``. Every stage is resumable.
"""

import argparse
import asyncio
import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from langfuse.api import Prompt_Text  # noqa: E402
from langfuse.model import TextPromptClient  # noqa: E402

import yt_flow.pipeline.nodes.image as image  # noqa: E402
import yt_flow.pipeline.nodes.scenario_chain as chain  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.pipeline.nodes.scenario import _call_deepseek  # noqa: E402
from yt_flow.services import comfyui_client  # noqa: E402
from yt_flow.services.eval_service import _load_state  # noqa: E402
from yt_flow.services.prompt_service import get_prompt  # noqa: E402

HERE = Path(__file__).parent
SOURCE_RUN = "8a9a288b-800f-4c73-88a2-25ae6b5a4d7d"
PROMPT_NAME = "scenario/visual_breakdown"
SCENES = (3, 7)

# The hand-authored cover, 0-based inclusive sentence ranges, frozen before any score
# was read. README §12.2 shows the rule applied sentence by sentence.
#   scene 3: "보입니까, 그 병이?"(3) folds into 2; "그는 진심으로 보고 있습니다."(5) and
#            "당신만 못 볼 뿐…"(6) fold into 4.
#   scene 7: "만족스러운 듯이요."(7) and "이게 에스씨피 공사구-이입니다."(8) fold into 6.
HAND_COVER = {
    3: [(0, 0), (1, 1), (2, 3), (4, 6)],
    7: [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 8)],
}
MERGED_SENTENCES = {(3, 3), (3, 5), (3, 6), (7, 7), (7, 8)}


def load_axis():
    spec = importlib.util.spec_from_file_location(
        "score_shot_narration", ROOT / "scripts" / "score_shot_narration.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def pin_prompt(text: str, version: int) -> None:
    client = TextPromptClient(Prompt_Text(
        name=PROMPT_NAME, version=version, prompt=text, labels=["production"], tags=[], config={}))

    def fake_get_prompt(name: str, *, label: str | None = None):
        return client if name == PROMPT_NAME else get_prompt(name, label=label)

    chain.prompt_service.get_prompt = fake_get_prompt


def dictated_prompt(base_text: str, ranges: list[tuple[int, int]]) -> str:
    """The cover prompt plus a block that FIXES the ranges.

    This is the whole point of M2: the model no longer decides whether to merge, so what
    is being measured is the quality of a prompt written for a merged span — not the
    model's willingness to merge. Appended as a section rather than edited in, so the
    rest of the cover prompt is byte-identical to the text PASS B used.
    """
    lines = "\n".join(
        f"  shot {i + 1}: sentence_start: {a + 1}, sentence_end: {b + 1}"
        for i, (a, b) in enumerate(ranges))
    return base_text + f"""

---

## MANDATORY COVER FOR THIS SCENE — overrides every range rule above

Do NOT choose the ranges yourself. This scene's cover has already been decided. Emit
EXACTLY these shots, in this order, with EXACTLY these values:

{lines}

Total shots: {len(ranges)}.

For any shot whose range spans more than one sentence, the `image_prompt` must carry the
WHOLE span — one frame that honestly covers every sentence in the range, not a frame for
its first sentence with the rest ignored. Choose the moment and the framing that lets one
image hold all of them.
"""


def scene_role_of(scene: dict) -> dict:
    return {"act": str(scene.get("mood") or ""), "emotional_beat": str(scene.get("kicker") or ""),
            "synopsis": str(scene.get("title") or "")}


def cast_by_sentence_of(scene: dict) -> dict[int, list]:
    out: dict[int, list] = {}
    for shot in scene["shots"]:
        for index in shot.get("sentence_indices") or []:
            out[index + 1] = shot.get("cast") or []
    return out


def slot_of(scene: dict) -> dict[int, dict]:
    return {i: shot for shot in scene["shots"] for i in (shot.get("sentence_indices") or [])}


def control_frame(scene_num: int, first: int) -> Path:
    """The ab2_old (bijection) render for the sentence a span opens on.

    ``ab2_old`` is a preserved record: read, never written.
    """
    old = json.loads((HERE / "ab2_old_scenes.json").read_text(encoding="utf-8"))
    scene = next(s for s in old if s["scene_num"] == scene_num)
    shot = next(s for s in scene["shots"] if s["sentence_indices"] == [first])
    return HERE / "ab2_old" / f"{shot['base']}.png"


def m1_state(state: dict) -> dict:
    """A PipelineState view: the hand cover's spans, each pointing at the CONTROL frame
    for its first sentence. Scoring this joins the span's sentences and asks the one
    question M1 exists to ask."""
    scenes = []
    for scene in state["scenes"]:
        n = scene["scene_num"]
        if n not in HAND_COVER:
            continue
        shots = [{
            "shot_id": f"M1_{n:03d}_{a}_{b}",
            "sentence_indices": list(range(a, b + 1)),
            "image_prompt": "(control frame, re-scored against the joined span)",
            "cast": [],
            "image_path": str(control_frame(n, a)),
        } for a, b in HAND_COVER[n]]
        scenes.append({"scene_num": n, "narration": scene["narration"], "shots": shots})
    return {"scenes": scenes}


async def write_m2(state, settings, version) -> dict:
    """Both scenes' visual_breakdown output under the DICTATED cover."""
    path = HERE / "probe_m2_shots.json"
    out: dict[str, list] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    base_text = (HERE / "prompt_cover.md").read_text(encoding="utf-8")
    for scene in state["scenes"]:
        n = scene["scene_num"]
        if n not in HAND_COVER or str(n) in out:
            continue
        sentences = chain.split_sentences(scene["narration"])
        pin_prompt(dictated_prompt(base_text, HAND_COVER[n]), version)
        t0 = time.perf_counter()
        shots = await chain.visual_breakdown_step(
            state["scp_id"], {"scene_num": n, "narration": scene["narration"]},
            sentences, cast_by_sentence_of(scene), *(await _context(state, settings)),
            scene_role_of(scene), settings, _call_deepseek,
        )
        got = [(s["sentence_start"] - 1, s["sentence_end"] - 1) for s in shots]
        # The parser accepts ANY valid cover, so "it parsed" does not mean "it obeyed".
        # A deviation is recorded, never silently accepted as the dictated cover.
        if got != HAND_COVER[n]:
            print(f"  ! scene {n}: model deviated from the dictated cover: {got} "
                  f"!= {HAND_COVER[n]}", flush=True)
        out[str(n)] = shots
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  m2 scene {n}: {len(shots)} shots, ranges {got} ({time.perf_counter() - t0:.0f}s)",
              flush=True)
    return out


_CTX: tuple | None = None


async def _context(state, settings) -> tuple:
    """``(frozen_descriptor, entity_sheet, story_logline)`` — reused from PASS B's
    ``ab2_context.json`` so this probe and PASS B share one research call."""
    global _CTX
    if _CTX is None:
        ctx = json.loads((HERE / "ab2_context.json").read_text(encoding="utf-8"))
        _CTX = (ctx["frozen_descriptor"], ctx.get("entity_sheet", ""), ctx.get("story_logline", ""))
    return _CTX


def m2_assemble(state, raw: dict) -> list[dict]:
    """The shipped ``build_scenes`` over the dictated-cover output, then the same seed
    and checkpoint-negative rule every other leg used."""
    scenes = [s for s in state["scenes"] if s["scene_num"] in HAND_COVER]
    writing = {"scenes": [{"scene_num": s["scene_num"], "narration": s["narration"],
                           "display_narration": s.get("display_narration") or s["narration"]}
                          for s in scenes]}
    structure = [{"mood": s.get("mood"), "title": s.get("title"), "kicker": s.get("kicker")}
                 for s in scenes]
    built = chain.build_scenes(
        writing, {i: raw[str(s["scene_num"])] for i, s in enumerate(scenes)}, structure)

    out = []
    for scene, source in zip(built, scenes):
        n = source["scene_num"]
        slots = slot_of(source)
        shots = []
        for shot in scene["shots"]:
            first = min(shot["sentence_indices"])
            shots.append({
                "shot_id": shot["shot_id"],
                "sentence_indices": list(shot["sentence_indices"]),
                "image_prompt": shot["image_prompt"],
                "cast": shot["cast"],
                "seed": image._shot_seed(SOURCE_RUN, n, f"S{n:03d}{first:02d}"),
                "negative_prompt": (slots.get(first) or {}).get("negative_prompt") or "",
                "base": f"scene_{n:03d}_{shot['shot_id']}",
            })
        out.append({"scene_num": n, "narration": source["narration"], "shots": shots})
    return out


async def render(scenes: list[dict], settings) -> None:
    template = image._load_workflow(settings.comfyui_workflow_path)
    await comfyui_client.check_health(settings.comfyui_url)
    (HERE / "probe_m2").mkdir(exist_ok=True)
    for scene in scenes:
        for shot in scene["shots"]:
            out = HERE / "probe_m2" / f"{shot['base']}.png"
            if out.is_file() and out.stat().st_size > image.MIN_VALID_IMAGE_BYTES:
                continue
            workflow = image._inject_prompts(
                template, shot["image_prompt"], shot["negative_prompt"], shot["seed"])
            t0 = time.perf_counter()
            out.write_bytes(await comfyui_client.submit_and_fetch(
                settings.comfyui_url, workflow, poll_interval=3.0, max_polls=600))
            print(f"  m2 {shot['base']} seed={shot['seed']} ({time.perf_counter() - t0:.1f}s)",
                  flush=True)


def m2_state(scenes: list[dict]) -> dict:
    return {"scenes": [{
        "scene_num": s["scene_num"], "narration": s["narration"],
        "shots": [{**sh, "image_path": str(HERE / "probe_m2" / f"{sh['base']}.png")}
                  for sh in s["shots"]],
    } for s in scenes]}


def control_rows() -> dict[tuple[int, int], dict]:
    """``ab2_old``'s per-sentence rows for these two scenes — the control, as scored."""
    old = json.loads((HERE / "ab2_old.json").read_text(encoding="utf-8"))
    return {(r["scene_num"], r["sentence_index"]): r
            for r in old["sentence_rows"] if r["scene_num"] in HAND_COVER}


def compare(axis, arm: str, state: dict, rows: list[dict], control: dict) -> dict:
    """Per-sentence deltas against the control, split by whether the rule merged it."""
    paired = axis.pair_by_sentence(state, rows)
    out, merged, kept = [], [], []
    for row in paired:
        key = (row["scene_num"], row["sentence_index"])
        ctl = control.get(key)
        entry = {
            "scene_num": key[0], "sentence_index": key[1], "sentence": row["sentence"],
            "merged_by_rule": key in MERGED_SENTENCES,
            "control_match": (ctl or {}).get("match"), "arm_match": row.get("match"),
            "control_readable": (ctl or {}).get("readable"), "arm_readable": row.get("readable"),
            "shot_ids": row["shot_ids"], "status": row["status"],
        }
        if row["status"] == "scored" and ctl and ctl["status"] == "scored":
            entry["delta"] = round(row["match"] - ctl["match"], 3)
            (merged if entry["merged_by_rule"] else kept).append(entry["delta"])
        out.append(entry)
    return {
        "arm": arm, "rows": out,
        "n": len(merged) + len(kept),
        "merged_n": len(merged),
        "merged_mean_delta": round(statistics.fmean(merged), 3) if merged else None,
        "kept_n": len(kept),
        "kept_mean_delta": round(statistics.fmean(kept), 3) if kept else None,
        "all_mean_delta": round(statistics.fmean(merged + kept), 3) if merged or kept else None,
        "merged_improved": sum(d > 0 for d in merged),
        "merged_worse": sum(d < 0 for d in merged),
        "merged_same": sum(d == 0 for d in merged),
    }


async def main(args) -> int:
    axis = load_axis()
    settings = Settings()  # type: ignore[call-arg]
    if not settings.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — this probe is a live measurement")
    state = await _load_state(SOURCE_RUN, settings.db_path)
    control = control_rows()
    result: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": SOURCE_RUN,
                    "scenes": list(SCENES), "hand_cover": {str(k): v for k, v in HAND_COVER.items()},
                    "merged_sentences": sorted(f"{s}:{i}" for s, i in MERGED_SENTENCES)}

    print("== M1: control frames re-scored against the joined spans (0 renders) ==", flush=True)
    s1 = m1_state(state)
    p1 = HERE / "probe_m1.json"
    if p1.is_file():
        rows1 = json.loads(p1.read_text(encoding="utf-8"))["rows"]
        print("reusing probe_m1.json", flush=True)
    else:
        rows1 = await axis.score_run(settings, s1, SOURCE_RUN, frames="images", reps=args.reps)
        p1.write_text(json.dumps(
            axis.report(rows1, settings, SOURCE_RUN,
                        argparse.Namespace(frames="images", reps=args.reps, pair_by="sentence"), s1),
            indent=2, ensure_ascii=False), encoding="utf-8")
    result["m1"] = compare(axis, "M1", s1, rows1, control)

    if not args.m1_only:
        print("\n== M2: dictated cover, re-authored prompts, rendered ==", flush=True)
        raw = await write_m2(state, settings, get_prompt(PROMPT_NAME).version)
        scenes2 = m2_assemble(state, raw)
        print(f"  m2 shots: {[(s['scene_num'], len(s['shots'])) for s in scenes2]}", flush=True)
        await render(scenes2, settings)
        s2 = m2_state(scenes2)
        p2 = HERE / "probe_m2.json"
        if p2.is_file():
            rows2 = json.loads(p2.read_text(encoding="utf-8"))["rows"]
            print("reusing probe_m2.json", flush=True)
        else:
            rows2 = await axis.score_run(settings, s2, SOURCE_RUN, frames="images", reps=args.reps)
            p2.write_text(json.dumps(
                axis.report(rows2, settings, SOURCE_RUN,
                            argparse.Namespace(frames="images", reps=args.reps, pair_by="sentence"), s2),
                indent=2, ensure_ascii=False), encoding="utf-8")
        result["m2"] = compare(axis, "M2", s2, rows2, control)

    (HERE / "probe_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    for arm in ("m1", "m2"):
        if arm in result:
            r = result[arm]
            print(f"\n{r['arm']}: merged n={r['merged_n']} mean Δ {r['merged_mean_delta']} "
                  f"(+{r['merged_improved']}/-{r['merged_worse']}/={r['merged_same']}) | "
                  f"kept n={r['kept_n']} mean Δ {r['kept_mean_delta']} | "
                  f"all Δ {r['all_mean_delta']}", flush=True)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--m1-only", action="store_true", help="skip the rendered arm")
    raise SystemExit(asyncio.run(main(p.parse_args())))
