#!/usr/bin/env python
"""Story 10.4b — baseline prompt vs absence-free prompt, paired over all 66 sentences.

The lever is the **prompt text and nothing else**. Both legs run the working tree's
parser, assembler and repairers; only ``prompts/scenario/visual_breakdown.md`` differs
(``old`` read from git at ``BASELINE_REV``, ``new`` from the working tree). That is
narrower than Story 10.4's iteration 2, which varied the parser too — here the parser is
unchanged apart from ``_fallback_prompt``'s text, and that only fires on a leading empty
prompt, so holding it constant keeps the prompt the single variable.

    uv run python _bmad-output/implementation-artifacts/10-4b-live-validation/run_absence_ab.py

Real end to end, nothing stubbed: narration, cast and negative prompts come from run
``8a9a288b``'s LangGraph checkpoint; both legs' ``image_prompt``s are written by the
shipped ``visual_breakdown_step`` on live DeepSeek; both are rendered by the live ComfyUI
through the shipped ``image._inject_prompts``; both are scored by the shipped
``scripts/score_shot_narration.py`` (Story 13.2's instrument, used as-is).

Held identical between the legs so the prompt is the only difference:

* the same narration, ``cast_by_sentence``, and scene role/entity context, built ONCE
  before either leg runs;
* the same **seed per starting sentence** — ``image._shot_seed(run, scene, "S{scene}{k}")``
  — so sampler noise stays paired wherever the two covers align;
* the same ``negative_prompt`` (the checkpoint's, for the shot's first sentence). A leg
  that also rewrote its negative would differ in two ways at once, and 10.4b explicitly
  does not touch negatives.

**The analysis is pre-registered in PRE-REGISTRATION.md, committed before this script ever
ran.** It is not restated here in a form that could drift from it: this file computes the
numbers that file asks for. Summary of what that means mechanically —

* primary axis is the boolean ``readable``, paired **by sentence** (once a cover may fold
  sentences the legs share no shot slots, so a per-shot pairing is undefined);
* the verdict comes from the **discordant pairs only** — ``b`` = unreadable→readable,
  ``c`` = readable→unreadable — with an exact two-sided binomial over ``b + c``. Comparing
  two independent rates at n≈66 has a ±6-frame interval and could only see half the
  defect; that is the trap 10.4's 15-slot round fell into;
* rates are always reported with ``n_shots``, because folding sentences removes frames and
  an unreadable *count* can fall while the *rate* rises (10.4 measured 16→15 count against
  24.2 %→27.3 % rate);
* ``b``/``c`` are also reported per **stratum** — the 5 rows whose baseline prompt made an
  absence the subject, the 1 borderline, and the 6 whose subject was already concrete.
  Pooling them would hide that scope ①'s ceiling is ~6 of 12, not 12 of 12.

``dsg_score`` is carried for per-proposition attribution only and is never part of the
verdict (rank-uncorrelated with ``match`` at 0.0263, and higher on unreadable frames).

Every stage is resumable: an existing output file is reused rather than recomputed, so a
killed run costs only the work in flight.

Outputs, all in this directory:
  ab_context.json                      the shared context both legs were given
  ab_old_shots.json / ab_new_shots.json    each leg's raw visual_breakdown output
  ab_old_scenes.json / ab_new_scenes.json  each leg's build_scenes result
  ab_old/<base>.png, ab_new/<base>.png     the renders
  ab_old.json / ab_new.json            the axis's full report per leg (+ sentence rows)
  ab_result.json                       the paired verdict against the pre-registered rule
"""

import argparse
import asyncio
import importlib.util
import json
import math
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
# The prompt as it stood before 10.4b. 10.4 reverted its two experiments to 3869f95, and
# 10.2 seeded that text as Langfuse production v14, so this revision IS the live prompt.
BASELINE_REV = "9b460d5"
PROMPT_FILE = "prompts/scenario/visual_breakdown.md"
PROMPT_NAME = "scenario/visual_breakdown"

# The pre-registered rule, quoted from PRE-REGISTRATION.md §4 so the JSON carries it.
WIN_RULE = (
    "b > c (strictly more sentences became readable than became unreadable), AND the exact "
    "two-sided binomial p over b+c is <= 0.05, AND the unreadable RATE does not increase "
    "above the 0.182 baseline"
)
BASELINE_UNREADABLE_RATE = 12 / 66  # 0.1818… — run 8a9a288b, Story 10.4 iteration 2

# Strata fixed in PRE-REGISTRATION.md §5 by reading each baseline `image_prompt`. The
# recorded premise ("all 12 make an absence the subject") is wrong; only 5 do.
STRATA = {
    "A_absence_was_subject": ["S00204", "S00300", "S00304", "S00305", "S00805"],
    "A_borderline": ["S00303"],
    "B_subject_already_concrete": ["S00201", "S00202", "S00400", "S00707", "S00804", "S00900"],
}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_axis():
    return _load_module("score_shot_narration", ROOT / "scripts" / "score_shot_narration.py")


def leg_texts() -> dict[str, str]:
    """``old`` from git at the baseline revision, ``new`` from the working tree.

    If the two are identical there is nothing to measure — that happens after a losing
    A/B is reverted per the pre-registered rule, and the preserved copy below is what
    keeps the run re-derivable afterwards (the role ``prompt_cover.md`` plays for 10.4).
    """
    old = subprocess.run(["git", "show", f"{BASELINE_REV}:{PROMPT_FILE}"],
                         capture_output=True, text=True, check=True).stdout
    new = (ROOT / PROMPT_FILE).read_text(encoding="utf-8")
    if old.strip() == new.strip():
        preserved = HERE / "prompt_absence_free.md"
        if not preserved.is_file():
            sys.exit(f"{PROMPT_FILE} is identical to {BASELINE_REV} and {preserved} is gone "
                     f"— there is no A/B to run")
        print(f"{PROMPT_FILE} is at baseline (reverted); reading the new leg from "
              f"{preserved.name}", flush=True)
        new = preserved.read_text(encoding="utf-8")
    return {"old": old, "new": new}


def pin_prompt(text: str, version: int) -> None:
    """Point the prompt fetch at this text, for ``visual_breakdown`` only.

    Uses the real ``TextPromptClient`` the runtime gets back from Langfuse, so ``{{var}}``
    compilation is Langfuse's own rather than a local imitation of it.
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


def cast_by_sentence_of(scene: dict) -> dict[str, list]:
    """The checkpoint's cast, keyed by 1-based sentence number as the prompt expects."""
    out: dict[str, list] = {}
    for shot in scene["shots"]:
        for index in shot.get("sentence_indices") or []:
            out.setdefault(str(index + 1), []).extend(
                {k: c.get(k) for k in ("card_key", "position", "depth", "pose")}
                for c in (shot.get("cast") or []) if isinstance(c, dict))
    return out


def slot_of(scene: dict) -> dict[int, dict]:
    """0-based sentence index -> the checkpoint shot that covered it (for its negative)."""
    return {i: shot for shot in scene["shots"] for i in (shot.get("sentence_indices") or [])}


async def build_context(state, settings) -> dict:
    path = HERE / "ab_context.json"
    if path.is_file():
        print("reusing ab_context.json", flush=True)
        return json.loads(path.read_text(encoding="utf-8"))
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
    path.write_text(json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    return context


async def write_leg(leg: str, text: str, state, context, settings, version) -> dict:
    """One leg's raw ``visual_breakdown_step`` output, keyed scene_num -> shots.

    Written to disk after every scene: 9 live DeepSeek calls per leg is too much work to
    lose to one timeout.
    """
    path = HERE / f"ab_{leg}_shots.json"
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
        shots = await chain.visual_breakdown_step(
            state["scp_id"], {"scene_num": scene["scene_num"], "narration": scene["narration"]},
            sentences, cast, context["frozen_descriptor"], context["entity_sheet"],
            context["story_logline"], context["scene_roles"][key], settings, _call_deepseek,
        )
        out[key] = shots
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {leg} scene {key}: {len(shots)} shots for {len(sentences)} sentences "
              f"({time.perf_counter() - t0:.0f}s)", flush=True)
    return out


def assemble(leg: str, state, raw_shots: dict) -> list[dict]:
    """Run the shipped ``build_scenes`` over this leg's visual output.

    Using the shipped assembler rather than a local reimplementation is what makes the
    cover's ``sentence_indices``, the empty-prompt merge and the three deterministic
    repairers part of what is measured. ``negative_prompt`` is then overwritten with the
    checkpoint's, so the legs differ in one thing only.
    """
    writing = {"scenes": [{"scene_num": sc["scene_num"], "narration": sc["narration"],
                           "display_narration": sc.get("display_narration") or sc["narration"]}
                          for sc in state["scenes"]]}
    structure = [{"mood": sc.get("mood"), "title": sc.get("title"), "kicker": sc.get("kicker")}
                 for sc in state["scenes"]]
    visual_by_scene = {i: raw_shots[str(sc["scene_num"])] for i, sc in enumerate(state["scenes"])}
    built = chain.build_scenes(writing, visual_by_scene, structure)

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
                # Same seed for the same STARTING sentence in both legs.
                "seed": image._shot_seed(SOURCE_RUN, scene["scene_num"],
                                         f"S{scene['scene_num']:03d}{first:02d}"),
                "negative_prompt": (slots.get(first) or {}).get("negative_prompt") or "",
                "base": f"scene_{scene['scene_num']:03d}_{shot['shot_id']}",
            })
        out.append({"scene_num": scene["scene_num"], "narration": scene["narration"], "shots": shots})
    (HERE / f"ab_{leg}_scenes.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def leg_state(leg: str, scenes: list[dict]) -> dict:
    """A PipelineState-shaped view whose ``image_path`` points at this leg's renders."""
    return {"scenes": [{
        "scene_num": sc["scene_num"], "narration": sc["narration"],
        "shots": [{**shot, "image_path": str(HERE / f"ab_{leg}" / f"{shot['base']}.png")}
                  for shot in sc["shots"]],
    } for sc in scenes]}


async def render(leg: str, scenes: list[dict], settings) -> dict:
    """Render every shot of one leg. Returns attempted/succeeded so a thin slate is visible."""
    template = image._load_workflow(settings.comfyui_workflow_path)
    await comfyui_client.check_health(settings.comfyui_url)
    (HERE / f"ab_{leg}").mkdir(exist_ok=True)
    attempted = succeeded = reused = 0
    for scene in scenes:
        for shot in scene["shots"]:
            out = HERE / f"ab_{leg}" / f"{shot['base']}.png"
            if out.is_file() and out.stat().st_size > image.MIN_VALID_IMAGE_BYTES:
                reused += 1
                continue
            attempted += 1
            t0 = time.perf_counter()
            workflow = image._inject_prompts(
                template, shot["image_prompt"], shot["negative_prompt"], shot["seed"])
            try:
                out.write_bytes(await comfyui_client.submit_and_fetch(
                    settings.comfyui_url, workflow, poll_interval=3.0, max_polls=600))
            except Exception as exc:  # noqa: BLE001 — a dead render is data, not a crash
                print(f"  ! {leg} {shot['base']}: {type(exc).__name__}: {exc}", flush=True)
                continue
            succeeded += 1
            print(f"  {leg} {shot['base']} seed={shot['seed']} "
                  f"({time.perf_counter() - t0:.1f}s)", flush=True)
    return {"attempted": attempted, "succeeded": succeeded, "reused": reused,
            "total": reused + succeeded}


async def score_leg(axis, leg: str, scenes, settings, reps: int) -> dict:
    path = HERE / f"ab_{leg}.json"
    if path.is_file():
        print(f"reusing {path.name}", flush=True)
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"\n== scoring leg {leg} (reps={reps}) ==", flush=True)
    view = leg_state(leg, scenes)
    rows = await axis.score_run(settings, view, SOURCE_RUN, frames="images", reps=reps, dsg=True)
    report = axis.report(rows, settings, SOURCE_RUN,
                         argparse.Namespace(frames="images", reps=reps, pair_by="sentence",
                                            dsg=True), view)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False), flush=True)
    return report


def _binom_two_sided(b: int, c: int) -> float:
    """Exact two-sided binomial p for ``b`` successes in ``b+c`` trials at p=0.5.

    stdlib only (``math.comb``). At these counts an exact test is the honest one — the
    normal approximation McNemar usually quotes needs b+c >= 25 and we expect the teens.
    """
    n = b + c
    if n == 0:
        return 1.0
    tail = min(b, c)
    cumulative = sum(math.comb(n, k) for k in range(tail + 1)) / (2 ** n)
    return min(1.0, 2 * cumulative)


def pair_readable(old_rows: list[dict], new_rows: list[dict]) -> dict:
    """Pair the two legs' per-SENTENCE readability and count the discordant cells.

    The sentence is the pairing key because once a shot may cover several sentences the
    two legs share no shot slots. A sentence covered by several shots is unreadable if any
    covering frame is — that is ``pair_by_sentence``'s own ``all()`` rule, reused.
    """
    def index(rows):
        return {(r["scene_num"], r["sentence_index"]): r
                for r in rows if r.get("status") == "scored"}

    old, new = index(old_rows), index(new_rows)
    keys = sorted(set(old) & set(new))
    cells = {"both_readable": 0, "both_unreadable": 0, "b_gained": 0, "c_lost": 0}
    flips: list[dict] = []
    for key in keys:
        o, n = bool(old[key]["readable"]), bool(new[key]["readable"])
        if o and n:
            cells["both_readable"] += 1
        elif not o and not n:
            cells["both_unreadable"] += 1
        elif n and not o:
            cells["b_gained"] += 1
        else:
            cells["c_lost"] += 1
        if o != n:
            flips.append({
                "scene_num": key[0], "sentence_index": key[1],
                "sentence": new[key].get("sentence"),
                "direction": "unreadable->readable" if n else "readable->unreadable",
                "old_shot_ids": old[key].get("shot_ids"), "new_shot_ids": new[key].get("shot_ids"),
            })
    b, c = cells["b_gained"], cells["c_lost"]
    return {"paired_sentences": len(keys), **cells,
            "discordant": b + c, "exact_binomial_p": round(_binom_two_sided(b, c), 5),
            "flips": flips}


def stratum_outcome(old_report: dict, new_report: dict) -> dict:
    """b/c restricted to the sentences the 12 baseline-unreadable SHOTS covered.

    The strata are shot ids from the baseline run, so they are mapped to sentences through
    the baseline's own bijection: each of those shots covered exactly one sentence. Without
    this split a pooled improvement could come entirely from stratum B and still be read as
    scope ① working.
    """
    baseline = json.loads((ROOT / "_bmad-output" / "implementation-artifacts" /
                           "10-4-live-validation" / "baseline_v2.json").read_text(encoding="utf-8"))
    by_shot = {r["shot_id"]: r for r in baseline["rows"]}
    out = {}
    for name, shot_ids in STRATA.items():
        keys = set()
        for shot_id in shot_ids:
            row = by_shot.get(shot_id)
            if row:
                keys.update((row["scene_num"], i) for i in row.get("sentence_indices") or [])
        subset = pair_readable(
            [r for r in old_report["sentence_rows"] if (r["scene_num"], r["sentence_index"]) in keys],
            [r for r in new_report["sentence_rows"] if (r["scene_num"], r["sentence_index"]) in keys])
        out[name] = {k: subset[k] for k in
                     ("paired_sentences", "both_readable", "both_unreadable", "b_gained",
                      "c_lost", "discordant", "exact_binomial_p")}
        out[name]["shot_ids"] = shot_ids
    return out


def decide(old_report: dict, new_report: dict, paired: dict) -> dict:
    """The pre-registered rule from PRE-REGISTRATION.md §4, evaluated clause by clause."""
    old_s, new_s = old_report["summary"], new_report["summary"]
    new_rate = new_s["unreadable"] / new_s["scored"] if new_s["scored"] else None
    old_rate = old_s["unreadable"] / old_s["scored"] if old_s["scored"] else None
    b, c = paired["b_gained"], paired["c_lost"]
    clauses = {
        "b_exceeds_c": b > c,
        "exact_binomial_p_at_most_0.05": paired["exact_binomial_p"] <= 0.05,
        "unreadable_rate_not_above_baseline": new_rate is not None and new_rate <= BASELINE_UNREADABLE_RATE,
    }
    return {
        "rule": WIN_RULE,
        "clauses": clauses,
        "won": all(clauses.values()),
        # Rates ALWAYS with n_shots: folding sentences removes frames, so a falling count
        # can hide a rising rate (10.4: 16->15 count, 24.2%->27.3% rate).
        "rates": {
            "baseline_reference": {"unreadable": 12, "n_shots": 66,
                                  "rate": round(BASELINE_UNREADABLE_RATE, 4)},
            "old_leg": {"unreadable": old_s["unreadable"], "n_shots": old_s["scored"],
                        "rate": None if old_rate is None else round(old_rate, 4)},
            "new_leg": {"unreadable": new_s["unreadable"], "n_shots": new_s["scored"],
                        "rate": None if new_rate is None else round(new_rate, 4)},
        },
        # Attribution only, never a verdict input (rank-uncorrelated with match, and
        # higher on unreadable frames — see 13-2-live-validation/README.md §5).
        "dsg_attribution_only": {
            leg: {k: report["summary"].get(k) for k in
                  ("mean_dsg", "dsg_distinct_values", "dsg_excluded_person_total",
                   "dsg_rows_with_person_prop", "dsg_qa_errors_total")}
            for leg, report in (("old", old_report), ("new", new_report))
        },
    }


def absence_compliance(scenes: list[dict]) -> dict:
    """How many of this leg's prompts still open on an absence.

    Reported as non-compliance, never scrubbed — a regex over `image_prompt` deletes
    camera, scale and depicted figures too (`gotcha_person-token-regex-is-unusable-on-image-prompt`),
    and 10.2 already built one, measured 27 of 313 shots damaged, and deleted it. This
    counts a fixed marker list for reporting only; nothing branches on it.
    """
    markers = ("open air", "empty concrete floor", "blank wall", "vast empty", "nothing on",
               "empty floor", "no visible subject", "featureless", "devoid of")
    hits = [{"shot_id": shot["shot_id"], "matched": m, "image_prompt": shot["image_prompt"][:160]}
            for sc in scenes for shot in sc["shots"]
            for m in markers if m in shot["image_prompt"].lower()]
    total = sum(len(sc["shots"]) for sc in scenes)
    return {"marker_list": list(markers), "shots": total, "hits": len(hits),
            "rate": round(len(hits) / total, 4) if total else None, "rows": hits}


async def main(args) -> int:
    axis = load_axis()
    settings = Settings()  # type: ignore[call-arg]
    for key, why in ((settings.character_vision_api_key, "YTFLOW_CHARACTER_VISION_API_KEY"),
                     (settings.deepseek_api_key, "YTFLOW_DEEPSEEK_API_KEY")):
        if not key:
            sys.exit(f"{why} is not set — this is a live A/B")
    state = await _load_state(SOURCE_RUN, settings.db_path)
    texts = leg_texts()
    version = get_prompt(PROMPT_NAME).version
    context = await build_context(state, settings)

    print("== writing both legs' image_prompts (live DeepSeek) ==", flush=True)
    scenes: dict[str, list] = {}
    for leg in ("old", "new"):
        raw = await write_leg(leg, texts[leg], state, context, settings, version)
        scenes[leg] = assemble(leg, state, raw)
        print(f"  {leg}: {sum(len(sc['shots']) for sc in scenes[leg])} shots total", flush=True)

    print("\n== rendering ==", flush=True)
    renders = {leg: await render(leg, scenes[leg], settings) for leg in ("old", "new")}
    print(json.dumps(renders, indent=2), flush=True)
    for leg, counts in renders.items():
        expected = sum(len(sc["shots"]) for sc in scenes[leg])
        if counts["total"] < expected * 0.9:
            sys.exit(f"leg {leg}: only {counts['total']}/{expected} frames on disk — a partial "
                     f"slate is not a comparison (intent contract Block If)")

    reports = {leg: await score_leg(axis, leg, scenes[leg], settings, args.reps)
               for leg in ("old", "new")}

    paired = pair_readable(reports["old"]["sentence_rows"], reports["new"]["sentence_rows"])
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "run": SOURCE_RUN, "reps": args.reps,
        "baseline_rev": BASELINE_REV,
        "pre_registration": "PRE-REGISTRATION.md (committed 25bed30, before any candidate render)",
        **decide(reports["old"], reports["new"], paired),
        "paired_readable": paired,
        "strata": stratum_outcome(reports["old"], reports["new"]),
        "shot_counts": {leg: sum(len(sc["shots"]) for sc in scenes[leg]) for leg in scenes},
        "renders": renders,
        "absence_compliance": {leg: absence_compliance(scenes[leg]) for leg in scenes},
        "sentence_summary": {leg: reports[leg]["sentence_summary"] for leg in reports},
    }
    (HERE / "ab_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    printable = {k: result[k] for k in
                 ("rule", "clauses", "won", "rates", "shot_counts", "strata")}
    printable["paired_readable"] = {k: v for k, v in paired.items() if k != "flips"}
    printable["absence_compliance"] = {
        leg: {k: v for k, v in block.items() if k not in ("rows", "marker_list")}
        for leg, block in result["absence_compliance"].items()}
    print("\n" + json.dumps(printable, indent=2, ensure_ascii=False), flush=True)
    # Exit code carries the verdict: 0 = the prompt may be seeded, 1 = it may not.
    return 0 if result["won"] else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reps", type=int, default=1,
                   help="samples per judge question; n=66 paired sentences does the work")
    raise SystemExit(asyncio.run(main(p.parse_args())))
