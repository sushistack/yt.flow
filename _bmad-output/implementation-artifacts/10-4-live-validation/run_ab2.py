#!/usr/bin/env python
"""Story 10.4 PASS B (iteration 2) — bijection vs ordered cover, over the WHOLE run.

Iteration 1's A/B was a 15-shot slate against a prompt-wording change, and it landed
inside its own noise floor (effect −0.333, same-prompt control sd 1.87). Two things
change here, both because iteration 1's own data said so:

* **The lever.** ``old`` is the 1:1 sentence↔shot bijection — the baseline prompt from
  git AND the baseline parser from git. ``new`` is the ordered cover — the working
  tree's prompt and the working tree's parser. The mapping is the variable, not the
  adjectives.
* **The power and the pairing.** All 9 scenes / 66 sentences, and the pairing is **by
  sentence**, because once one shot may cover three sentences the two legs share no
  shot slots at all. 66 paired deltas, bootstrap 95% CI, ``--reps 1``.

    uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_ab2.py

Real end to end: narration, cast and negative prompts come from run ``8a9a288b``'s
LangGraph checkpoint; both legs' ``image_prompt``s are written by the shipped
``visual_breakdown_step`` on live DeepSeek and assembled by the shipped
``build_scenes``; both legs are rendered by the live ComfyUI through the shipped
``image._inject_prompts``; both are scored by the shipped
``scripts/score_shot_narration.py``. Nothing is stubbed.

Held identical between the legs so the mapping is the only difference:

* the same narration, the same ``cast_by_sentence``, the same scene role/entity
  context (built once, before either leg runs);
* the same **seed per starting sentence** — ``image._shot_seed(run_id, scene_num,
  "S{scene:03d}{sentence_index:02d}")``. Under the bijection that IS the baseline
  shot's own seed; under the cover a shot opening on sentence *k* inherits the same
  one, so sampler noise stays paired wherever the two covers align;
* the same ``negative_prompt`` — the checkpoint's, for the shot's first sentence, NOT
  each leg's own emitted negative. A leg that also rewrote the negative would make the
  pair differ in two ways at once.

Reconstruction caveats (unchanged from iteration 1, see README §caveats):
``location``/``color_palette``/``atmosphere`` are ``writing_step`` fields and were
never persisted, so both legs fall back to the same module defaults; ``scene_role`` is
rebuilt from the checkpoint's own ``mood``/``title``/``kicker``; and
``frozen_descriptor``/``entity_sheet``/``story_logline`` come from one live
``research_step`` call shared by both legs.

Outputs, all in this directory:
  ab2_context.json                the shared context both legs were given
  ab2_old_shots.json / ab2_new_shots.json   each leg's raw visual_breakdown output
  ab2_old_scenes.json / ab2_new_scenes.json each leg's build_scenes result (the cover)
  ab2_old/<base>.png, ab2_new/<base>.png    the renders
  ab2_old.json / ab2_new.json     the axis's full report per leg (+ sentence rows)
  ab2_result.json                 the pre-registered win rule and its verdict

Every stage is resumable: an existing output file is reused rather than recomputed, so
a killed run costs only the work in flight.
"""

import argparse
import asyncio
import importlib.util
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
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
BASELINE_REV = "3869f95"
PROMPT_FILE = "prompts/scenario/visual_breakdown.md"
CHAIN_FILE = "src/yt_flow/pipeline/nodes/scenario_chain.py"
PROMPT_NAME = "scenario/visual_breakdown"

# The pre-registered win rule, quoted verbatim in the README ABOVE its result.
WIN_RULE = (
    "the paired mean Δ `match` over the 66 sentences is positive and its bootstrap 95% CI "
    "excludes 0; the count of unreadable frames does not increase; and the hook shot is "
    "`readable` with `match >= 4`"
)

# The four sentences that scored `match <= 2` at baseline. AC3 is the falsifiable
# prediction the root-cause claim makes: under a cover these fold into a neighbour.
# (baseline shot_id -> scene, 0-based sentence index, since the baseline was a bijection)
AC3_SHOTS = {"S00105": (1, 5), "S00303": (3, 3), "S00708": (7, 8), "S00503": (5, 3)}

BOOTSTRAP_RESAMPLES = 10000
BOOTSTRAP_SEED = 10_04  # fixed so the CI in the README is re-derivable to the digit


def load_axis():
    return _load_module("score_shot_narration", ROOT / "scripts" / "score_shot_narration.py")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_baseline_chain():
    """``scenario_chain`` exactly as it stood at the baseline revision.

    The old leg needs the old **parser**, not just the old prompt: the bijection was
    enforced in ``visual_breakdown_step.parse``, and a leg that ran the old prompt
    through the new permissive parser would be measuring only half the change. Loaded
    from git rather than copied, for the same reason ``leg_texts`` does.
    """
    source = subprocess.run(["git", "show", f"{BASELINE_REV}:{CHAIN_FILE}"],
                            capture_output=True, text=True, check=True).stdout
    tmp = Path(tempfile.mkdtemp()) / "scenario_chain_baseline.py"
    tmp.write_text(source, encoding="utf-8")
    return _load_module("scenario_chain_baseline", tmp)


def leg_texts() -> dict[str, str]:
    """``old`` from git at the baseline revision, ``new`` from the working tree.

    The cover leg LOST its pre-registered rule, so the working-tree prompt was reverted
    to the baseline per the spec's Block If. ``prompt_cover.md`` preserves the text this
    run actually used, and the fall-back below is what keeps the run re-derivable after
    that revert — exactly the role ``prompt_new.md`` plays for iteration 1.
    """
    old = subprocess.run(["git", "show", f"{BASELINE_REV}:{PROMPT_FILE}"],
                         capture_output=True, text=True, check=True).stdout
    new = (ROOT / PROMPT_FILE).read_text(encoding="utf-8")
    if old.strip() == new.strip():
        preserved = HERE / "prompt_cover.md"
        if not preserved.is_file():
            sys.exit(f"{PROMPT_FILE} is identical to {BASELINE_REV} and {preserved} is gone "
                     f"— there is no A/B to run")
        print(f"{PROMPT_FILE} is at baseline (the cover prompt was reverted); "
              f"reading the new leg from {preserved.name}", flush=True)
        new = preserved.read_text(encoding="utf-8")
    return {"old": old, "new": new}


def pin_prompt(text: str, version: int) -> None:
    """Point the prompt fetch at this text for visual_breakdown only.

    ``prompt_service`` is one module object shared by both chain modules, so this pins
    whichever leg is running. Uses the real ``TextPromptClient`` the runtime gets back
    from Langfuse, so ``{{var}}`` compilation is Langfuse's own.
    """
    client = TextPromptClient(Prompt_Text(
        name=PROMPT_NAME, version=version, prompt=text, labels=["production"], tags=[], config={}))

    def fake_get_prompt(name: str, *, label: str | None = None):
        return client if name == PROMPT_NAME else get_prompt(name, label=label)

    chain.prompt_service.get_prompt = fake_get_prompt


def scene_role_of(scene: dict) -> dict:
    """``structure_step``'s per-scene role, rebuilt from what the checkpoint kept."""
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
    """``{0-based sentence index: recorded shot}`` — the negative-prompt source."""
    return {index: shot for shot in scene["shots"] for index in (shot.get("sentence_indices") or [])}


async def build_context(state, settings) -> dict:
    if (HERE / "ab2_context.json").is_file():
        print("reusing ab2_context.json", flush=True)
        return json.loads((HERE / "ab2_context.json").read_text(encoding="utf-8"))
    format_guide = get_prompt("scenario/format_guide").compile()
    research = await chain.research_step(state["scp_id"], state["scp_text"], format_guide,
                                         settings, _call_deepseek)
    context = {
        "frozen_descriptor": research["frozen_descriptor"],
        "entity_sheet": research.get("entity_sheet", ""),
        "story_logline": research.get("story_logline", ""),
        "scene_roles": {str(sc["scene_num"]): scene_role_of(sc) for sc in state["scenes"]},
        "cast_by_sentence": {str(sc["scene_num"]): cast_by_sentence_of(sc) for sc in state["scenes"]},
        "note": "built ONCE, before either leg ran, and passed unchanged to both",
    }
    (HERE / "ab2_context.json").write_text(
        json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    return context


async def write_leg(leg: str, module, text: str, state, context, settings, version) -> dict:
    """One leg's raw ``visual_breakdown_step`` output, keyed scene_num -> shots.

    Written to disk after every scene: 9 live DeepSeek calls per leg is too much work
    to lose to one timeout.
    """
    path = HERE / f"ab2_{leg}_shots.json"
    out: dict[str, list] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    pin_prompt(text, version)
    for scene in state["scenes"]:
        key = str(scene["scene_num"])
        if key in out:
            print(f"  {leg} scene {key}: reusing {len(out[key])} shots", flush=True)
            continue
        sentences = chain.split_sentences(scene["narration"])
        cast = {int(k): v for k, v in context["cast_by_sentence"][key].items()}
        t0 = time.perf_counter()
        shots = await module.visual_breakdown_step(
            state["scp_id"], {"scene_num": scene["scene_num"], "narration": scene["narration"]},
            sentences, cast, context["frozen_descriptor"], context["entity_sheet"],
            context["story_logline"], context["scene_roles"][key], settings, _call_deepseek,
        )
        out[key] = shots
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {leg} scene {key}: {len(shots)} shots for {len(sentences)} sentences "
              f"({time.perf_counter() - t0:.0f}s)", flush=True)
    return out


def assemble(leg: str, module, state, raw_shots: dict) -> list[dict]:
    """Run the leg's own ``build_scenes`` over its own visual output.

    Using the shipped assembler rather than a local reimplementation is what makes the
    cover's ``sentence_indices``, the empty-prompt merge and the three deterministic
    repairers part of what is being measured. The ``negative_prompt`` is then
    overwritten with the checkpoint's, so the legs differ in one thing only.
    """
    writing = {"scenes": [{"scene_num": sc["scene_num"], "narration": sc["narration"],
                           "display_narration": sc.get("display_narration") or sc["narration"]}
                          for sc in state["scenes"]]}
    structure = [{"mood": sc.get("mood"), "title": sc.get("title"), "kicker": sc.get("kicker")}
                 for sc in state["scenes"]]
    visual_by_scene = {i: raw_shots[str(sc["scene_num"])] for i, sc in enumerate(state["scenes"])}
    built = module.build_scenes(writing, visual_by_scene, structure)

    out = []
    for scene, source in zip(built, state["scenes"]):
        slots = slot_of(source)
        shots = []
        for shot in scene["shots"]:
            first = min(shot["sentence_indices"])
            shots.append({
                "shot_id": shot["shot_id"],
                "sentence_indices": list(shot["sentence_indices"]),
                "image_prompt": shot["image_prompt"],
                "cast": shot["cast"],
                # Same seed for the same STARTING sentence in both legs; under the
                # bijection this is byte-identically the baseline shot's own seed.
                "seed": image._shot_seed(SOURCE_RUN, scene["scene_num"], f"S{scene['scene_num']:03d}{first:02d}"),
                "negative_prompt": (slots.get(first) or {}).get("negative_prompt") or "",
                "base": f"scene_{scene['scene_num']:03d}_{shot['shot_id']}",
            })
        out.append({"scene_num": scene["scene_num"], "narration": scene["narration"], "shots": shots})
    (HERE / f"ab2_{leg}_scenes.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def leg_state(leg: str, scenes: list[dict]) -> dict:
    """A PipelineState-shaped view whose ``image_path`` points at this leg's renders."""
    return {"scenes": [{
        "scene_num": sc["scene_num"], "narration": sc["narration"],
        "shots": [{**shot, "image_path": str(HERE / f"ab2_{leg}" / f"{shot['base']}.png")}
                  for shot in sc["shots"]],
    } for sc in scenes]}


async def render(leg: str, scenes: list[dict], settings) -> None:
    template = image._load_workflow(settings.comfyui_workflow_path)
    await comfyui_client.check_health(settings.comfyui_url)
    (HERE / f"ab2_{leg}").mkdir(exist_ok=True)
    for scene in scenes:
        for shot in scene["shots"]:
            out = HERE / f"ab2_{leg}" / f"{shot['base']}.png"
            if out.is_file() and out.stat().st_size > image.MIN_VALID_IMAGE_BYTES:
                continue
            workflow = image._inject_prompts(
                template, shot["image_prompt"], shot["negative_prompt"], shot["seed"])
            t0 = time.perf_counter()
            out.write_bytes(await comfyui_client.submit_and_fetch(
                settings.comfyui_url, workflow, poll_interval=3.0, max_polls=600))
            print(f"  {leg} {shot['base']} seed={shot['seed']} "
                  f"({time.perf_counter() - t0:.1f}s)", flush=True)


def bootstrap_ci(deltas: list[float], resamples: int = BOOTSTRAP_RESAMPLES) -> dict:
    """Percentile bootstrap 95% CI of the paired mean.

    Paired deltas, so the resampling unit is the sentence — the pairing is what
    removes the between-sentence variance that swamped iteration 1 at n=15.
    """
    rng = random.Random(BOOTSTRAP_SEED)
    means = sorted(statistics.fmean(rng.choices(deltas, k=len(deltas))) for _ in range(resamples))
    lo = means[int(0.025 * resamples)]
    hi = means[int(0.975 * resamples) - 1]
    return {"mean": round(statistics.fmean(deltas), 4), "n": len(deltas),
            "ci95_low": round(lo, 4), "ci95_high": round(hi, 4),
            "excludes_zero": lo > 0 or hi < 0, "resamples": resamples, "seed": BOOTSTRAP_SEED}


def pair(old_rows: list[dict], new_rows: list[dict]) -> tuple[list[dict], list[float]]:
    """Join the two legs' sentence rows on (scene, sentence index)."""
    new_by_key = {(r["scene_num"], r["sentence_index"]): r for r in new_rows}
    pairs, deltas = [], []
    for old in old_rows:
        key = (old["scene_num"], old["sentence_index"])
        new = new_by_key.get(key)
        entry = {
            "scene_num": key[0], "sentence_index": key[1], "sentence": old["sentence"],
            "old_status": old["status"], "new_status": (new or {}).get("status"),
            "old_shots": old["shot_ids"], "new_shots": (new or {}).get("shot_ids"),
            "old_match": old.get("match"), "new_match": (new or {}).get("match"),
            "old_readable": old.get("readable"), "new_readable": (new or {}).get("readable"),
        }
        if old["status"] == "scored" and (new or {}).get("status") == "scored":
            entry["delta"] = round(new["match"] - old["match"], 3)
            deltas.append(entry["delta"])
        pairs.append(entry)
    return pairs, deltas


def decide(old: dict, new: dict, ci: dict) -> dict:
    """The pre-registered rule, evaluated. Three independent clauses, all required."""
    o, n = old["summary"], new["summary"]
    hook = n["hook"] or {}
    clauses = {
        "paired_mean_delta_positive_and_ci_excludes_zero": {
            "mean": ci["mean"], "ci95": [ci["ci95_low"], ci["ci95_high"]], "n": ci["n"],
            "held": ci["mean"] > 0 and ci["ci95_low"] > 0},
        "unreadable_frames_do_not_increase": {
            "old": o["unreadable"], "new": n["unreadable"],
            "old_of": o["scored"], "new_of": n["scored"],
            "held": n["unreadable"] <= o["unreadable"]},
        "hook_is_readable_and_match_at_least_4": {
            "old": [(old["summary"]["hook"] or {}).get("readable"),
                    (old["summary"]["hook"] or {}).get("match")],
            "new": [hook.get("readable"), hook.get("match")],
            "held": hook.get("readable") is True and (hook.get("match") or 0) >= 4},
    }
    return {"rule": WIN_RULE, "clauses": clauses, "won": all(c["held"] for c in clauses.values())}


def cover_shape(scenes: list[dict], state) -> list[dict]:
    """Per-scene shot count and the cover's own validity, read off the emitted data.

    AC2 is verified here rather than asserted: every sentence covered, no inverted or
    backwards range — measured from what the leg actually produced.
    """
    out = []
    for scene, source in zip(scenes, state["scenes"]):
        n = len(chain.split_sentences(source["narration"]))
        covered = {i for shot in scene["shots"] for i in shot["sentence_indices"]}
        firsts = [min(shot["sentence_indices"]) for shot in scene["shots"]]
        lasts = [max(shot["sentence_indices"]) for shot in scene["shots"]]
        out.append({
            "scene_num": scene["scene_num"], "sentences": n, "shots": len(scene["shots"]),
            "merged_shots": sum(len(s["sentence_indices"]) > 1 for s in scene["shots"]),
            "split_sentences": sum(firsts.count(f) > 1 for f in set(firsts)),
            "uncovered": sorted(set(range(n)) - covered),
            "monotonic": all(a <= b for a, b in zip(firsts, firsts[1:]))
            and all(a <= b for a, b in zip(lasts, lasts[1:])),
            "inverted": [s["shot_id"] for s in scene["shots"]
                         if min(s["sentence_indices"]) > max(s["sentence_indices"])],
        })
    return out


def ac3_outcome(pairs: list[dict], new_scenes: list[dict]) -> list[dict]:
    """The falsifiable prediction, checked: were the four worst rows merged or split?"""
    by_scene = {sc["scene_num"]: sc for sc in new_scenes}
    out = []
    for shot_id, (scene_num, index) in AC3_SHOTS.items():
        entry = next((p for p in pairs if p["scene_num"] == scene_num
                      and p["sentence_index"] == index), None)
        covering = [s for s in by_scene[scene_num]["shots"] if index in s["sentence_indices"]]
        if not covering:
            verdict = "UNCOVERED (cover bug)"
        elif len(covering) > 1:
            verdict = f"SPLIT across {len(covering)} shots"
        elif len(covering[0]["sentence_indices"]) > 1:
            verdict = f"MERGED into a shot covering sentences {covering[0]['sentence_indices']}"
        else:
            verdict = "LEFT ALONE (still its own shot)"
        out.append({
            "baseline_shot": shot_id, "scene_num": scene_num, "sentence_index": index,
            "sentence": (entry or {}).get("sentence"), "prediction": "merged or split",
            "outcome": verdict,
            "old_match": (entry or {}).get("old_match"), "new_match": (entry or {}).get("new_match"),
            "held": verdict.startswith(("MERGED", "SPLIT")),
        })
    return out


async def score_leg(axis, leg: str, scenes, settings, reps: int) -> dict:
    path = HERE / f"ab2_{leg}.json"
    if path.is_file():
        print(f"reusing {path.name}", flush=True)
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"\n== scoring leg {leg} (reps={reps}) ==", flush=True)
    view = leg_state(leg, scenes)
    rows = await axis.score_run(settings, view, SOURCE_RUN, frames="images", reps=reps)
    report = axis.report(rows, settings, SOURCE_RUN,
                         argparse.Namespace(frames="images", reps=reps, pair_by="sentence"), view)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False), flush=True)
    return report


async def main(args) -> int:
    axis = load_axis()
    settings = Settings()  # type: ignore[call-arg]
    for key, why in ((settings.character_vision_api_key, "YTFLOW_CHARACTER_VISION_API_KEY"),
                     (settings.deepseek_api_key, "YTFLOW_DEEPSEEK_API_KEY")):
        if not key:
            sys.exit(f"{why} is not set — pass B is a live A/B")
    state = await _load_state(SOURCE_RUN, settings.db_path)
    texts = leg_texts()
    modules = {"old": load_baseline_chain(), "new": chain}
    version = get_prompt(PROMPT_NAME).version
    context = await build_context(state, settings)

    print("== writing both legs' image_prompts (live DeepSeek) ==", flush=True)
    scenes = {}
    for leg in ("old", "new"):
        raw = await write_leg(leg, modules[leg], texts[leg], state, context, settings, version)
        scenes[leg] = assemble(leg, modules[leg], state, raw)
        print(f"  {leg}: {sum(len(sc['shots']) for sc in scenes[leg])} shots total", flush=True)

    shape = {leg: cover_shape(scenes[leg], state) for leg in scenes}
    print("\n== cover shape ==\n" + json.dumps(shape, indent=2, ensure_ascii=False), flush=True)

    print("\n== rendering ==", flush=True)
    for leg in ("old", "new"):
        await render(leg, scenes[leg], settings)

    reports = {leg: await score_leg(axis, leg, scenes[leg], settings, args.reps)
               for leg in ("old", "new")}

    pairs, deltas = pair(reports["old"]["sentence_rows"], reports["new"]["sentence_rows"])
    ci = bootstrap_ci(deltas) if deltas else {"mean": None, "ci95_low": None, "ci95_high": None,
                                              "n": 0, "excludes_zero": False}
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "run": SOURCE_RUN, "reps": args.reps,
        **decide(reports["old"], reports["new"], ci),
        "paired": ci,
        "shot_counts": {leg: sum(len(sc["shots"]) for sc in scenes[leg]) for leg in scenes},
        "cover_shape": shape,
        "ac3": ac3_outcome(pairs, scenes["new"]),
        "sentence_summary": {leg: reports[leg]["sentence_summary"] for leg in reports},
        "pairs": pairs,
    }
    (HERE / "ab2_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + json.dumps({k: result[k] for k in
                             ("rule", "clauses", "won", "paired", "shot_counts", "ac3")},
                            indent=2, ensure_ascii=False), flush=True)
    # Exit code carries the verdict: 0 = the prompt may be seeded, 1 = it may not.
    return 0 if result["won"] else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reps", type=int, default=1, help="samples per judge question (n=66 does the work)")
    raise SystemExit(asyncio.run(main(p.parse_args())))
