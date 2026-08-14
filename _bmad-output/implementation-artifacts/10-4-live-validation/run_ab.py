#!/usr/bin/env python
"""Story 10.4 PASS B — old prompt vs new prompt on a fixed slate, prompt as the only variable.

Real end to end: the narration and cast come from run ``8a9a288b``'s LangGraph
checkpoint, both legs' ``image_prompt``s are written by the shipped
``scenario_chain.visual_breakdown_step`` on live DeepSeek, both legs are rendered
by the live ComfyUI through the shipped ``image._inject_prompts`` +
``comfyui_client.submit_and_fetch``, and both are scored by the shipped
``scripts/score_shot_narration.py``. Nothing is stubbed.

    uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_ab.py

Slate: scene 1 (7 shots — carries the hook) + scene 5 (8 shots, ``escalation``) =
15 slots, 30 renders.

What is held identical between the two legs, so the runtime prompt text is the
only thing that differs:

* the same narration, the same sentences, the same ``cast_by_sentence``, the same
  scene role/entity context (built once, before either leg runs);
* the same KSampler seed per slot — ``image._shot_seed(run_id, scene_num,
  shot_id)``, i.e. the seed the shot was originally rendered on;
* the same workflow JSON (``settings.comfyui_workflow_path``), so resolution,
  steps, cfg, sampler and LoRA chain all come from production's own file;
* the same ``negative_prompt`` — the one recorded in the checkpoint for that slot,
  NOT each leg's own emitted negative. A leg that also rewrites the negative would
  make the pair differ in two ways at once, and the AC asks for one.

Reconstruction caveats, stated because they are not free (see README §caveats):
``location`` / ``color_palette`` / ``atmosphere`` are ``writing_step`` fields and
were never persisted, so ``visual_breakdown_step`` falls back to its own module
defaults for both legs; ``scene_role`` is rebuilt from the checkpoint's own
``mood``/``title``/``kicker`` (which ARE this run's structure output); and
``frozen_descriptor``/``entity_sheet``/``story_logline`` are produced by one live
``research_step`` call made once and shared by both legs.

Outputs, all in this directory:
  prompt_old.md / prompt_new.md   the two runtime prompt texts actually compiled
  ab_context.json                 the shared context both legs were given
  ab_old_shots.json / ab_new_shots.json   each leg's raw visual_breakdown output
  old/<base>.png, new/<base>.png  the renders
  pairs/<base>_pair.jpg           old | new, labelled
  ab_old.json / ab_new.json       the axis's full report per leg
  ab_result.json                  the pre-registered win rule and its verdict
"""

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
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
BASELINE_REV = "3869f95"  # the prompt text the baseline frames were written by
PROMPT_FILE = "prompts/scenario/visual_breakdown.md"
PROMPT_NAME = "scenario/visual_breakdown"
SLATE_SCENES = (1, 5)  # 1 = the hook scene, 5 = escalation

# The pre-registered win rule, quoted verbatim in the README ABOVE its result.
WIN_RULE = ("mean `match` over the slate does not decrease, the count of shots below "
            "MIN_MATCH does not increase, and the hook shot reaches match >= 4 and legible >= 4")


def load_axis():
    spec = importlib.util.spec_from_file_location(
        "score_shot_narration", ROOT / "scripts" / "score_shot_narration.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def leg_texts() -> dict[str, str]:
    """``old`` from git at the baseline revision, ``new`` from the working tree.

    The old leg must come from git, not from a copy: pointing both legs at the
    working tree is an after/after comparison that still looks like evidence
    (10-3's lesson, written down there in the same words).
    """
    old = subprocess.run(["git", "show", f"{BASELINE_REV}:{PROMPT_FILE}"],
                         capture_output=True, text=True, check=True).stdout
    new = (ROOT / PROMPT_FILE).read_text(encoding="utf-8")
    if old.strip() == new.strip():
        sys.exit(f"{PROMPT_FILE} is identical to {BASELINE_REV} — there is no A/B to run")
    return {"old": old, "new": new}


def pin_prompt(text: str, version: int) -> None:
    """Point ``scenario_chain``'s prompt fetch at this text for visual_breakdown only.

    Uses the real ``TextPromptClient`` the runtime gets back from Langfuse, so
    ``{{var}}`` compilation is Langfuse's own and not a reimplementation of it.
    """
    client = TextPromptClient(Prompt_Text(
        name=PROMPT_NAME, version=version, prompt=text, labels=["production"], tags=[], config={}))

    def fake_get_prompt(name: str, *, label: str | None = None):
        return client if name == PROMPT_NAME else get_prompt(name, label=label)

    chain.prompt_service.get_prompt = fake_get_prompt


def scene_role_of(scene: dict) -> dict:
    """``structure_step``'s per-scene role, rebuilt from what the checkpoint kept.

    ``build_scenes`` copies structure's ``mood``/``title``/``kicker`` onto the
    scene, so these three ARE this run's own structure output — the act/beat/
    synopsis wording is not, and that is why it is recorded here rather than
    presented as recovered.
    """
    return {"act": str(scene.get("mood") or ""), "emotional_beat": str(scene.get("kicker") or ""),
            "synopsis": str(scene.get("title") or "")}


def cast_by_sentence_of(scene: dict) -> dict[int, list]:
    """``{1-based sentence number: cast list}`` from the shots the run recorded."""
    out: dict[int, list] = {}
    for shot in scene["shots"]:
        for index in shot.get("sentence_indices") or []:
            out[index + 1] = shot.get("cast") or []
    return out


def slot_of(scene: dict) -> dict[int, dict]:
    """``{1-based sentence number: recorded shot}`` — the seed/negative source."""
    return {index + 1: shot for shot in scene["shots"] for index in (shot.get("sentence_indices") or [])}


async def write_legs(state, texts, settings, version) -> dict[str, dict]:
    """Both legs' ``visual_breakdown_step`` output, keyed leg → scene_num → shots."""
    scenes = {sc["scene_num"]: sc for sc in state["scenes"] if sc["scene_num"] in SLATE_SCENES}
    format_guide = get_prompt("scenario/format_guide").compile()
    research = await chain.research_step(state["scp_id"], state["scp_text"], format_guide,
                                         settings, _call_deepseek)
    context = {
        "frozen_descriptor": research["frozen_descriptor"],
        "entity_sheet": research.get("entity_sheet", ""),
        "story_logline": research.get("story_logline", ""),
        "scene_roles": {n: scene_role_of(sc) for n, sc in scenes.items()},
        "cast_by_sentence": {n: cast_by_sentence_of(sc) for n, sc in scenes.items()},
        "note": "built ONCE, before either leg ran, and passed unchanged to both",
    }
    (HERE / "ab_context.json").write_text(
        json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")

    out: dict[str, dict] = {}
    for leg, text in texts.items():
        pin_prompt(text, version)
        out[leg] = {}
        for scene_num, scene in scenes.items():
            sentences = chain.split_sentences(scene["narration"])
            shots = await chain.visual_breakdown_step(
                state["scp_id"], {"scene_num": scene_num, "narration": scene["narration"]},
                sentences, context["cast_by_sentence"][scene_num],
                context["frozen_descriptor"], context["entity_sheet"], context["story_logline"],
                context["scene_roles"][scene_num], settings, _call_deepseek,
            )
            out[leg][scene_num] = shots
            print(f"  {leg} scene {scene_num}: {len(shots)} shots written", flush=True)
        (HERE / f"ab_{leg}_shots.json").write_text(
            json.dumps(out[leg], indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def build_slate(state, legs) -> list[dict]:
    """One entry per renderable slot, both legs' prompts and the shared seed."""
    scenes = {sc["scene_num"]: sc for sc in state["scenes"] if sc["scene_num"] in SLATE_SCENES}
    slate = []
    for scene_num, scene in scenes.items():
        slots = slot_of(scene)
        for sentence_start in sorted(slots):
            shot = slots[sentence_start]
            prompts = {}
            for leg in legs:
                match = next((sh for sh in legs[leg][scene_num]
                              if sh.get("sentence_start") == sentence_start), None)
                prompts[leg] = str((match or {}).get("image_prompt") or "").strip()
            if not all(prompts.values()):
                # An empty prompt on either side would leave the pair unmatched;
                # dropping it keeps every rendered pair a true like-for-like.
                print(f"  ! slot {shot['shot_id']} dropped: empty image_prompt "
                      f"({ {k: bool(v) for k, v in prompts.items()} })", flush=True)
                continue
            slate.append({
                "scene_num": scene_num, "shot_id": shot["shot_id"],
                "sentence_start": sentence_start,
                "base": image._shot_base(scene_num, shot),
                "seed": image._shot_seed(SOURCE_RUN, scene_num, shot["shot_id"]),
                "negative_prompt": shot.get("negative_prompt") or "",
                "sentence_indices": shot.get("sentence_indices") or [],
                "cast": shot.get("cast") or [],
                "prompts": prompts,
                "leg_negatives": {leg: next((sh.get("negative_prompt") for sh in legs[leg][scene_num]
                                             if sh.get("sentence_start") == sentence_start), None)
                                  for leg in legs},
            })
    return slate


async def render(slate, settings, legs) -> None:
    # Story 13.3: (workflow, resolved node map); prompts inject by declared title.
    template, nodes = image._load_workflow(settings.comfyui_workflow_path)
    await comfyui_client.check_health(settings.comfyui_url)
    for leg in legs:
        (HERE / leg).mkdir(exist_ok=True)
        for entry in slate:
            out = HERE / leg / f"{entry['base']}.png"
            if out.is_file() and out.stat().st_size > image.MIN_VALID_IMAGE_BYTES:
                print(f"  {leg} {entry['base']}: already rendered", flush=True)
                continue
            workflow = image._inject_prompts(
                template, nodes, entry["prompts"][leg], entry["negative_prompt"], entry["seed"])
            t0 = time.perf_counter()
            out.write_bytes(await comfyui_client.submit_and_fetch(
                settings.comfyui_url, workflow, poll_interval=3.0, max_polls=600))
            print(f"  {leg} {entry['base']} seed={entry['seed']} "
                  f"({time.perf_counter() - t0:.1f}s)", flush=True)


def leg_state(state, slate, leg) -> dict:
    """A PipelineState-shaped view whose ``image_path`` points at this leg's renders."""
    scenes = {sc["scene_num"]: sc for sc in state["scenes"]}
    out = []
    for scene_num in SLATE_SCENES:
        shots = [{
            "shot_id": e["shot_id"], "sentence_indices": e["sentence_indices"],
            "image_prompt": e["prompts"][leg], "cast": e["cast"],
            "image_path": str(HERE / leg / f"{e['base']}.png"),
        } for e in slate if e["scene_num"] == scene_num]
        if shots:
            out.append({"scene_num": scene_num, "narration": scenes[scene_num]["narration"], "shots": shots})
    return {"scenes": out}


def make_pairs(slate) -> None:
    (HERE / "pairs").mkdir(exist_ok=True)
    for entry in slate:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(HERE / "old" / f"{entry['base']}.png"),
            "-i", str(HERE / "new" / f"{entry['base']}.png"), "-filter_complex",
            "[0:v]drawtext=text='OLD prompt':x=20:y=20:fontsize=36:fontcolor=yellow:box=1:boxcolor=black@0.6[a];"
            "[1:v]drawtext=text='NEW prompt':x=20:y=20:fontsize=36:fontcolor=yellow:box=1:boxcolor=black@0.6[b];"
            "[a][b]hstack=inputs=2", "-q:v", "3",
            str(HERE / "pairs" / f"{entry['base']}_pair.jpg"),
        ], capture_output=True, check=False)


def decide(axis, old: dict, new: dict) -> dict:
    """The pre-registered rule, evaluated. Three independent clauses, all required."""
    o, n = old["summary"], new["summary"]
    hook = n["hook"] or {}
    clauses = {
        "mean_match_does_not_decrease": {
            "old": o["mean_match"], "new": n["mean_match"],
            "held": n["mean_match"] is not None and o["mean_match"] is not None
            and n["mean_match"] >= o["mean_match"]},
        "below_min_match_does_not_increase": {
            "old": o["below_min_match"], "new": n["below_min_match"],
            "held": n["below_min_match"] <= o["below_min_match"]},
        "hook_reaches_4_and_4": {
            "old": (old["summary"]["hook"] or {}).get("match"), "new": hook.get("match"),
            "new_legible": hook.get("legible"),
            "held": (hook.get("match") or 0) >= axis.MIN_MATCH_HOOK
            and (hook.get("legible") or 0) >= axis.MIN_LEGIBLE_HOOK},
    }
    return {"rule": WIN_RULE, "clauses": clauses,
            "won": all(c["held"] for c in clauses.values())}


async def main(args) -> int:
    axis = load_axis()
    settings = Settings()  # type: ignore[call-arg]
    for key, why in ((settings.character_vision_api_key, "YTFLOW_CHARACTER_VISION_API_KEY"),
                     (settings.deepseek_api_key, "YTFLOW_DEEPSEEK_API_KEY")):
        if not key:
            sys.exit(f"{why} is not set — pass B is a live A/B")
    state = await _load_state(SOURCE_RUN, settings.db_path)
    texts = leg_texts()
    for leg, text in texts.items():
        (HERE / f"prompt_{leg}.md").write_text(text, encoding="utf-8")

    if args.reuse_shots and all((HERE / f"ab_{leg}_shots.json").is_file() for leg in texts):
        legs = {leg: {int(k): v for k, v in
                      json.loads((HERE / f"ab_{leg}_shots.json").read_text(encoding="utf-8")).items()}
                for leg in texts}
        print("reusing the previously written image_prompts", flush=True)
    else:
        print("== writing both legs' image_prompts (live DeepSeek) ==", flush=True)
        legs = await write_legs(state, texts, settings, get_prompt(PROMPT_NAME).version)

    slate = build_slate(state, legs)
    (HERE / "ab_slate.json").write_text(json.dumps(slate, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"slate: {len(slate)} slots x 2 legs = {len(slate) * 2} renders", flush=True)

    print("\n== rendering ==", flush=True)
    await render(slate, settings, legs)
    make_pairs(slate)

    reports = {}
    for leg in legs:
        print(f"\n== scoring leg {leg} (reps={args.reps}) ==", flush=True)
        rows = await axis.score_run(settings, leg_state(state, slate, leg), SOURCE_RUN,
                                    frames="images", reps=args.reps)
        reports[leg] = axis.report(rows, settings, SOURCE_RUN,
                                   argparse.Namespace(frames="images", reps=args.reps))
        (HERE / f"ab_{leg}.json").write_text(
            json.dumps(reports[leg], indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(reports[leg]["summary"], indent=2, ensure_ascii=False), flush=True)

    result = decide(axis, reports["old"], reports["new"])
    result["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    result["slate"] = [e["shot_id"] for e in slate]
    result["per_shot"] = [{
        "shot_id": e["shot_id"],
        **{f"{leg}_{k}": next((r.get(k) for r in reports[leg]["rows"] if r["shot_id"] == e["shot_id"]), None)
           for leg in legs for k in ("legible", "match_score", "place", "missing")},
    } for e in slate]
    (HERE / "ab_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + json.dumps({k: result[k] for k in ("rule", "clauses", "won")},
                            indent=2, ensure_ascii=False), flush=True)
    # Exit code carries the verdict: 0 = the new prompt may be seeded, 1 = it may not.
    return 0 if result["won"] else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reps", type=int, default=3, help="samples per judge question")
    p.add_argument("--reuse-shots", action="store_true",
                   help="reuse ab_*_shots.json instead of re-calling DeepSeek")
    raise SystemExit(asyncio.run(main(p.parse_args())))
