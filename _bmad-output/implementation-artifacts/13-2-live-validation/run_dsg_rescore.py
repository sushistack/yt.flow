#!/usr/bin/env python
"""Story 13.2 — re-score the PRESERVED 66 baseline frames with the DSG instrument.

Everything here is real: the frames are the exact 66 PNGs ``baseline_v2.json``
scored (51 ``recomposed/`` + 15 ``images/``, all verified present on disk), the
propositions come from live ``qwen-plus`` calls and every answer from a live
``qwen-vl-plus`` call. Nothing is re-rendered, nothing is stubbed, and no GPU is
touched. The script does not reimplement the axis — it imports and drives
``scripts/score_shot_narration.py``, so the numbers are produced by shipped code.

    uv run python _bmad-output/implementation-artifacts/13-2-live-validation/run_dsg_rescore.py

Cloned from ``10-4-live-validation/run_baseline.py --rescore`` and narrowed in one
important way: **the frame paths come from ``baseline_v2.json``'s ``frame`` field,
not from re-resolving the checkpoint.** ``score_run`` would resolve
``shot["image_path"]`` again, and that field has already been repointed once
(``recompose_service``, see 10-4 README §0) — re-resolving would silently score a
different frame set and destroy the v2↔v3 comparison. So each v2 row is carried
forward with its ``readable``/``match_score`` intact (same judge, same frame, same
``temperature: 0``) and only the DSG pass is run fresh on top of it.

Two artifacts, in this directory and never in ``10-4-live-validation/``:

  ``baseline_v3.json``          — v2's rows + the v3 proposition fields, one report.
                                  Also the shape ``evaluate_ab`` reads for
                                  ``unreadable_rate``/``mean_dsg_score``.
  ``instrument_v2_vs_v3.json``  — joined on ``shot_id``: v2 ``match``/``readable``
                                  against v3 ``dsg_score``/excluded counts, both
                                  distributions, the rank correlation, and the
                                  confound numbers.

Cost: ~66 text QG calls + one image QA call per non-invalidated proposition
(~300-400). ``baseline_v2.json`` is never rewritten.
"""

import argparse
import asyncio
import importlib.util
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)  # every `frame` path in baseline_v2.json is repo-relative

from yt_flow.config import Settings  # noqa: E402

HERE = Path(__file__).parent
V2 = ROOT / "_bmad-output" / "implementation-artifacts" / "10-4-live-validation" / "baseline_v2.json"
SOURCE_RUN = "8a9a288b-800f-4c73-88a2-25ae6b5a4d7d"  # 9 scenes, 66 shots, SCP-049

# The re-derivation of 10.4's unreproducible "11/66 card-absence" figure. That number
# was a hand count of `missing` free text with no script and no rule ever recorded
# (confirmed by grep + `git log -S`), so it cannot be a baseline. THIS rule is written
# down, case-sensitive, applied to `missing`, and reported with its own count.
PERSON_NOUN_RE = re.compile(
    r"\b(person|people|figure|figures|human|humans|body|bodies|man|men|woman|women|hand|hands)\b")
# The companion figure IS reproducible: person-nouns in the BLIND `event` caption count
# frames whose plate already contains a body the prompt never asked for (10-4 §2.3).
BLIND_BODY_RE = re.compile(r"\b(figure|figures|person|people)\b")


def load_axis():
    spec = importlib.util.spec_from_file_location(
        "score_shot_narration", ROOT / "scripts" / "score_shot_narration.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _distribution(values) -> dict:
    out: dict = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: float(kv[0])))


def compare_instruments(v2_rows: list[dict], v3_rows: list[dict]) -> dict:
    """v2's 1-5 Likert against v3's proposition fraction, on the same frames.

    Joined on ``shot_id`` — ``run_baseline.compare_instruments``'s precedent, and the
    only join available once a row's identity is the shot rather than the frame file.

    "Moved off the 3-pile" is defined here rather than argued: of the rows v2 scored
    exactly 3, count the distinct v3 values, and call the rows outside the *largest*
    v3 bucket the ones that moved. A pile that merely relocated to one new value is
    therefore not counted as resolution.
    """
    v2 = {r["shot_id"]: r for r in v2_rows if r["status"] == "scored"}
    v3 = {r["shot_id"]: r for r in v3_rows if r["status"] == "scored"}
    both = sorted(set(v2) & set(v3))
    scorable = [s for s in both if v3[s].get("dsg_score") is not None]

    match_dist = _distribution(v2[s]["match_score"] for s in both)
    dsg_dist = _distribution(v3[s]["dsg_score"] for s in scorable)

    pile = [s for s in scorable if v2[s]["match_score"] == 3]
    pile_dist = _distribution(v3[s]["dsg_score"] for s in pile)
    largest_pile_bucket = max(pile_dist.values()) if pile_dist else 0

    # Spearman: stdlib since 3.12 (`method="ranked"`), so no scipy. Needs >= 2 points
    # and non-constant input on both sides, or it raises — guarded, not assumed.
    xs = [float(v2[s]["match_score"]) for s in scorable]
    ys = [float(v3[s]["dsg_score"]) for s in scorable]
    try:
        rank_corr = round(statistics.correlation(xs, ys, method="ranked"), 4)
    except statistics.StatisticsError as exc:
        rank_corr = f"undefined: {exc}"

    person_missing = [s for s in both if PERSON_NOUN_RE.search(v2[s].get("missing") or "")]
    blind_body = [s for s in both if BLIND_BODY_RE.search(v2[s].get("event") or "")]
    with_person_prop = [s for s in scorable if v3[s].get("dsg_excluded_person_n", 0) > 0]

    return {
        "frames_joined": len(both),
        "v3_scorable": len(scorable),
        "v3_unscorable": len(both) - len(scorable) - sum("dsg_error" in v3[s] for s in both),
        "v3_errored": sum("dsg_error" in v3[s] for s in both),

        # ── resolution ────────────────────────────────────────────────────────
        "v2_match_distribution": match_dist,
        "v2_distinct_values": len(match_dist),
        "v3_dsg_distribution": dsg_dist,
        "v3_distinct_values": len(dsg_dist),
        "v2_match_3_rows": len(pile),
        "v3_distinct_values_among_v2_match_3": len(pile_dist),
        "v3_largest_bucket_among_v2_match_3": largest_pile_bucket,
        "rows_moved_off_the_3_pile": len(pile) - largest_pile_bucket,
        "v2_v3_rank_correlation": rank_corr,

        # ── the card-absence confound, as a counted quantity ──────────────────
        "person_propositions_excluded_total":
            sum(v3[s].get("dsg_excluded_person_n", 0) for s in scorable),
        "rows_with_at_least_one_person_proposition": len(with_person_prop),
        "rows_with_person_proposition_ids": with_person_prop,
        "propositions_total":
            sum(v3[s].get("dsg_scored_n", 0) + v3[s].get("dsg_excluded_person_n", 0) for s in scorable),
        "dependency_invalidated_total": sum(v3[s].get("dsg_invalidated_n", 0) for s in scorable),
        # Compliance of the one QG rule the exclusion rests on. `_is_person` takes the
        # union of `kind`/`about_body`, so a disagreement cannot pollute the score — but
        # a high number here means the decomposition is fragile and the next session
        # should read it before trusting the exclusion counts above.
        "qg_label_disagreements_total": sum(v3[s].get("dsg_label_disagreements", 0) for s in scorable),
        # v2's own proxy for the same confound, re-derived with a written-down rule
        # because the "11/66" hand count is not reproducible.
        "person_noun_rule": PERSON_NOUN_RE.pattern,
        "v2_rows_whose_missing_names_a_person": len(person_missing),
        "v2_rows_whose_missing_names_a_person_ids": person_missing,
        "blind_body_rule": BLIND_BODY_RE.pattern,
        "v2_rows_whose_blind_event_reads_a_body": len(blind_body),

        # ── does v3 agree with the orthogonal readability axis? ───────────────
        "mean_dsg_readable": _mean(v3[s]["dsg_score"] for s in scorable if v2[s]["readable"]),
        "mean_dsg_unreadable": _mean(v3[s]["dsg_score"] for s in scorable if not v2[s]["readable"]),

        "note": ("same 66 preserved frames, same judge, same temperature 0; v2's readable/"
                 "match_score are carried forward unchanged and only the DSG pass is new. "
                 "baseline_v2.json untouched."),
    }


def _mean(values) -> float | None:
    values = list(values)
    return round(statistics.fmean(values), 4) if values else None


async def main(args) -> int:
    axis = load_axis()
    settings = Settings()  # type: ignore[call-arg]
    if not settings.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — this is a live measurement")

    v2 = json.loads(V2.read_text(encoding="utf-8"))
    v2_rows = v2["rows"]
    print(f"{V2.name}: {len(v2_rows)} rows, "
          f"{sum(r['status'] == 'scored' for r in v2_rows)} scored; "
          f"QG={axis.QG_MODEL} QA={settings.character_vision_model}", flush=True)

    missing = [r["frame"] for r in v2_rows if r.get("frame") and not Path(r["frame"]).is_file()]
    if missing:
        sys.exit(f"{len(missing)} preserved frame(s) are gone — the comparison is void: {missing[:3]}")

    t0 = time.perf_counter()
    rows: list[dict] = []
    for row in v2_rows[: args.limit] if args.limit else v2_rows:
        new = dict(row)          # v2's verdict carried forward, not recomputed
        rows.append(new)
        # `frame` is checked too, not just status: the existence sweep above only tests
        # truthy paths, so a scored row with a null frame would reach read_bytes() and
        # kill the run mid-way — after the paid calls already spent, with nothing written.
        if row["status"] != "scored" or not row.get("sentences") or not row.get("frame"):
            print(f"  - {row['shot_id']}: {row['status']} in v2"
                  f"{'' if row.get('frame') else ', no frame path'}, no DSG pass", flush=True)
            continue
        await axis._score_dsg(settings, new, row["sentences"], Path(row["frame"]).read_bytes())
        if "dsg_error" in new:
            print(f"  ! {new['shot_id']}: DSG ERROR — {new['dsg_error']}", flush=True)
        else:
            print(f"  ✓ {new['shot_id']}: dsg={new['dsg_score']} "
                  f"({new['dsg_scored_n']} scored, -{new['dsg_excluded_person_n']} person, "
                  f"{new['dsg_invalidated_n']} invalidated)  v2 match={row['match_score']} "
                  f"readable={row['readable']}", flush=True)

    namespace = argparse.Namespace(frames=v2.get("frame_source", "images"), reps=args.reps,
                                   pair_by="shot", dsg=True)
    report = axis.report(rows, settings, SOURCE_RUN, namespace)

    # The intent contract's HALT thresholds, checked BEFORE anything is written. Writing
    # first and warning afterwards leaves a halted distribution on disk looking exactly
    # like a good one, and the next session reads the file, not the console.
    errored = report["summary"].get("dsg_errored", 0)
    scorable = report["summary"].get("dsg_scorable", 0)
    if errored > 5 or (not args.limit and scorable < 60):
        print(f"\nHALT: {errored} of {len(rows)} rows errored, {scorable} scorable — a partial "
              "distribution is not the comparison. Nothing written; fix the instrument first.",
              flush=True)
        return 1
    report["frames_from"] = str(V2.relative_to(ROOT))
    report["provenance"] = (
        "readable/match_score/place/event/evidence/missing are baseline_v2.json's verdicts on "
        "these same frames, unchanged; propositions/dsg_* are this run's. See 10-4 README §0 — "
        "51 of the 66 frames are Story 10.1c recompositions, not the frames Jay watched.")
    (HERE / "baseline_v3.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> baseline_v3.json: {json.dumps(report['summary'], ensure_ascii=False, indent=2)}",
          flush=True)

    # Also publish it where the CONSUMER looks, which is what makes the eval_service
    # wiring live rather than notional: `evaluate_ab` reads unreadable_rate /
    # mean_dsg_score from <workspace>/<run>/visual_score.json. The CLI path
    # (`score_shot_narration.py --dsg`) writes this too; this harness drives
    # `_score_dsg` directly and would otherwise skip it. Skipped, with a message, when
    # the run's workspace directory does not exist — never created here, because
    # inventing a workspace for a run would be a different kind of artifact.
    from yt_flow.services.eval_service import VISUAL_SCORE_FILENAME  # noqa: PLC0415
    run_dir = Path(settings.workspace_path) / SOURCE_RUN
    if args.limit:
        print(f"-> --limit {args.limit}: visual_score.json not published (a subset cannot be "
              "told apart from a full sweep downstream)", flush=True)
    elif run_dir.is_dir():
        (run_dir / VISUAL_SCORE_FILENAME).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"-> {run_dir / VISUAL_SCORE_FILENAME} (consumed by evaluate_ab)", flush=True)
    else:
        print(f"-> {run_dir} absent; visual_score.json not published", flush=True)

    comparison = compare_instruments(v2_rows, rows)
    (HERE / "instrument_v2_vs_v3.json").write_text(
        json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **comparison},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n== DSG fraction vs the piled-at-3 Likert, on the same frames ==", flush=True)
    print(json.dumps({k: v for k, v in comparison.items()
                      if not k.endswith("_ids")}, indent=2, ensure_ascii=False), flush=True)
    print(f"\nelapsed {time.perf_counter() - t0:.0f}s", flush=True)

    # The HALT thresholds already ran (and returned 1) before anything was written. A low
    # score is a result, not a failure, so a completed measurement exits 0 even when the
    # verdict is unflattering — and an errored row count inside the accepted band must not
    # contradict the printed verdict by exiting non-zero.
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reps", type=int, default=1, help="recorded in the report; DSG asks each question once")
    p.add_argument("--limit", type=int, help="score only the first N v2 rows (smoke test)")
    raise SystemExit(asyncio.run(main(p.parse_args())))
