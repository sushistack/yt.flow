#!/usr/bin/env python
"""Story 10.4 PASS A — the measured baseline over the 66 frames Jay actually watched.

Everything here is real: the scenes come from run ``8a9a288b``'s LangGraph
checkpoint, the frames are the PNGs that run wrote and that were composited into
the video Jay reviewed, and every verdict is a live DashScope ``qwen-vl-plus``
call. Nothing is faked, stubbed or replayed. The script does not reimplement the
axis — it imports and drives ``scripts/score_shot_narration.py``, so the numbers
below are produced by the shipped code.

    uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_baseline.py

Three arms, in order:

  A1  all 66 shots, ``--frames images`` (the generated plate), ``--reps 1``
      → ``baseline.json``   — the failure rate before any change.
  A2  the N worst shots of A1, ``--frames images``, ``--reps 3``
      → ``worst_images.json`` — a REPEAT of the same frames, same source. This is
      the control for A3: without it, a verdict that moves in A3 cannot be told
      apart from the judge sampling differently on a second look.
  A3  the same N shots, ``--frames shots`` (the composited clip's mid-frame),
      ``--reps 3``
      → ``worst_shots.json``  — answers "the plate is not what he watched" with
      data rather than an argument.

A2 and A3 are run at the same ``--reps`` on the same shot set so the only
difference between them is the frame source.

Read-only with respect to ``workspace/8a9a288b-.../``: frames are read, ffmpeg
writes its extracted mid-frames into a temp dir, nothing in the run is touched.
"""

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)  # the checkpoint's image_path values are repo-relative

from yt_flow.config import Settings  # noqa: E402
from yt_flow.services.eval_service import _load_state  # noqa: E402

HERE = Path(__file__).parent
SOURCE_RUN = "8a9a288b-800f-4c73-88a2-25ae6b5a4d7d"  # the run Jay watched — 9 scenes, 66 shots, SCP-049


def load_axis():
    spec = importlib.util.spec_from_file_location(
        "score_shot_narration", ROOT / "scripts" / "score_shot_narration.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write(axis, rows, settings, name: str, frames: str, reps: int, state=None, pair_by="shot") -> dict:
    report = axis.report(rows, settings, SOURCE_RUN,
                         argparse.Namespace(frames=frames, reps=reps, pair_by=pair_by), state)
    (HERE / name).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {name}: {json.dumps(report['summary'], ensure_ascii=False, indent=2)}", flush=True)
    return report


def _unclear(row: dict) -> bool:
    """Iteration 1's buried signal: the blind reply wrote ``event: "unclear"`` while
    scoring the same frame ``legible: 4``."""
    return "unclear" in str(row.get("event") or "").strip().lower()


def compare_instruments(v2_rows: list[dict]) -> dict:
    """What the boolean recovered that the dead Likert buried.

    ``baseline.json`` is iteration 1's record and is never rewritten — this reads it,
    joins on ``shot_id``, and cross-tabs the old 1--5 ``legible`` against the new
    ``readable`` on **the same 66 frames**, so the difference is the question asked
    and nothing else.
    """
    old_rows = json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))["rows"]
    old = {r["shot_id"]: r for r in old_rows if r["status"] == "scored"}
    new = {r["shot_id"]: r for r in v2_rows if r["status"] == "scored"}
    both = sorted(set(old) & set(new))
    legible_dist: dict[int, int] = {}
    for shot_id in both:
        legible_dist[old[shot_id]["legible"]] = legible_dist.get(old[shot_id]["legible"], 0) + 1
    unreadable = [s for s in both if not new[s]["readable"]]
    return {
        "frames_joined": len(both),
        "likert_legible_distribution": dict(sorted(legible_dist.items())),
        "likert_below_3": sum(old[s]["legible"] < 3 for s in both),
        "likert_event_unclear": sum(_unclear(old[s]) for s in both),
        "boolean_unreadable": len(unreadable),
        "boolean_unreadable_shots": unreadable,
        "boolean_unreadable_that_the_likert_scored_4_or_5":
            sum(old[s]["legible"] >= 4 for s in unreadable),
        "new_event_unclear": sum(_unclear(new[s]) for s in both),
        "unreadable_and_event_unclear": sum(_unclear(new[s]) for s in unreadable),
        "note": ("same 66 preserved frames, same judge, same blind prompt body except the "
                 "readability question; baseline.json untouched"),
    }


async def rescore(axis, settings, state, args) -> int:
    """Re-score the PRESERVED baseline frames with the boolean instrument.

    No frame is re-rendered: this is the identical ``workspace/8a9a288b-.../images``
    PNG set ``baseline.json`` scored, asked a different question.
    """
    rows = await axis.score_run(settings, state, SOURCE_RUN, frames="images", reps=args.reps)
    report = write(axis, rows, settings, "baseline_v2.json", "images", args.reps,
                   state=state, pair_by="sentence")
    comparison = compare_instruments(rows)
    (HERE / "instrument_v1_vs_v2.json").write_text(
        json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **comparison},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n== boolean vs the dead Likert, on the same frames ==", flush=True)
    print(json.dumps(comparison, indent=2, ensure_ascii=False), flush=True)
    return 1 if report["summary"]["skipped"] or report["summary"]["errored"] else 0


async def main(args) -> int:
    axis = load_axis()
    settings = Settings()  # type: ignore[call-arg]
    if not settings.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — pass A is a live measurement")
    state = await _load_state(SOURCE_RUN, settings.db_path)
    print(f"{SOURCE_RUN}: {len(state['scenes'])} scenes, "
          f"{sum(len(sc['shots']) for sc in state['scenes'])} shots, model="
          f"{settings.character_vision_model}", flush=True)

    if args.rescore:
        return await rescore(axis, settings, state, args)

    t0 = time.perf_counter()
    print("\n== A1: all shots, frames=images, reps=%d ==" % args.reps, flush=True)
    rows = await axis.score_run(settings, state, SOURCE_RUN, frames="images", reps=args.reps)
    a1 = write(axis, rows, settings, "baseline.json", "images", args.reps)

    scored = [r for r in rows if r["status"] == "scored"]
    worst = sorted(scored, key=lambda r: (r["match_score"], r["legible"]))[:args.worst]
    only = {r["shot_id"] for r in worst}
    print(f"\nworst {len(only)}: {sorted(only)}", flush=True)

    print(f"\n== A2: worst {len(only)}, frames=images, reps={args.recheck_reps} (repeat control) ==",
          flush=True)
    rows_a2 = await axis.score_run(settings, state, SOURCE_RUN, frames="images",
                                   reps=args.recheck_reps, only=only)
    a2 = write(axis, rows_a2, settings, "worst_images.json", "images", args.recheck_reps)

    print(f"\n== A3: worst {len(only)}, frames=shots, reps={args.recheck_reps} (cross-check) ==",
          flush=True)
    rows_a3 = await axis.score_run(settings, state, SOURCE_RUN, frames="shots",
                                   reps=args.recheck_reps, only=only)
    a3 = write(axis, rows_a3, settings, "worst_shots.json", "shots", args.recheck_reps)

    by_id = {r["shot_id"]: r for r in rows}
    delta = []
    for shot_id in sorted(only):
        a2_row = next((r for r in rows_a2 if r["shot_id"] == shot_id), {})
        a3_row = next((r for r in rows_a3 if r["shot_id"] == shot_id), {})
        delta.append({
            "shot_id": shot_id,
            "a1_images_reps1": [by_id[shot_id]["legible"], by_id[shot_id]["match_score"]],
            "a2_images_reps3": [a2_row.get("legible"), a2_row.get("match_score")],
            "a3_shots_reps3": [a3_row.get("legible"), a3_row.get("match_score")],
            "a3_status": a3_row.get("status"), "a3_reason": a3_row.get("reason"),
            "a1_place": by_id[shot_id].get("place"), "a3_place": a3_row.get("place"),
        })
    (HERE / "worst_delta.json").write_text(
        json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "note": "[legible, match] per arm; A2 is the repeat control for A3",
                    "rows": delta}, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + json.dumps(delta, indent=2, ensure_ascii=False), flush=True)
    print(f"\nelapsed {time.perf_counter() - t0:.0f}s", flush=True)

    # Non-zero if any arm failed to MEASURE something (skip/error). A low score is a
    # result, not a run failure — this is the baseline, it is supposed to be bad.
    # A3's skips are expected and excluded: a shot with no composited clip is a fact
    # about the run, recorded in worst_shots.json, not a failure of pass A.
    return 1 if any(s["summary"]["skipped"] or s["summary"]["errored"] for s in (a1, a2)) \
        or a3["summary"]["errored"] else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reps", type=int, default=1, help="samples per question for the full sweep")
    p.add_argument("--recheck-reps", type=int, default=3, help="samples per question for A2/A3")
    p.add_argument("--worst", type=int, default=8, help="how many worst shots go into A2/A3")
    p.add_argument("--rescore", action="store_true",
                   help="iteration 2: re-score the SAME preserved frames with the boolean "
                        "instrument into baseline_v2.json (baseline.json is never rewritten)")
    raise SystemExit(asyncio.run(main(p.parse_args())))
