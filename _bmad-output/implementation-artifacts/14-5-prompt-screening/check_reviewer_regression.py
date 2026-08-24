#!/usr/bin/env python
"""Story 14.5: did "put the event in the frame" pull BODIES back into `image_prompt`? GPU 0.

Spec: ``_bmad-output/implementation-artifacts/spec-14-5-narration-plate-pose-match.md``

This is the regression side of the edit, and it is not optional. Slot 3 now says *"put
this sentence's event in the frame"*, and the events in this narration are mostly things
a person or the entity does. One paraphrase away from that instruction is *"put the
person in the frame"* — which is precisely the defect
``prompts/scenario/review.md`` (Story 14.7, live ``scenario/review`` v11) reports as
``descriptor_violation``. So the candidate prompts are fed to the SHIPPED reviewer and
the reverse-direction finding is counted.

    uv run python .../check_reviewer_regression.py 4b35c0ed --reps 2

Reads the candidate ``image_prompt`` strings from ``visible_event.json`` (leg ``new``,
written by ``screen_visible_event.py``) and, for the control, leg ``old`` — a count with
no control cannot tell "the edit added violations" from "the reviewer always says this".

Everything except the shot substitution is 14.7's harness, imported: its reviewer
variable reconstruction, its Langfuse-free renderer, its call site and its mutually
exclusive ``bucket()`` classifier. Re-deriving any of that here would be a second
hand-copied vocabulary of exactly the kind Story 14.0 pinned a test against.

Exit codes:
    0  screened; the candidate leg added no ``entity-in-prompt`` finding over the control
    1  regression — the candidate leg drew more of them than the control
    2  usage error
    3  nothing to measure (no cached legs, unreadable prompt, every rep errored)
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))
# `Settings(env_file=".env")` is CWD-relative (`config.py:31`). Without this the reviewer
# silently runs on code-default model/budget instead of the configured one whenever the
# script is invoked from anywhere but the repo root — `gotcha_env-file-beats-code-default`
# inverted, and it would mean measuring a different reviewer than Story 14.7 did.
os.chdir(REPO)

_EXIT_OK, _EXIT_REGRESSION, _EXIT_USAGE, _EXIT_NOTHING = 0, 1, 2, 3


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ARTIFACTS = REPO / "_bmad-output" / "implementation-artifacts"
S147 = _load(ARTIFACTS / "14-7-prompt-screening" / "screen_review_prompt.py", "screen_14_7")

from yt_flow.config import Settings  # noqa: E402


def scenes_with(scenes: list[dict], rows: list[dict], rep: int) -> list[dict]:
    """The run's scenes with each scene's ``image_prompt`` list replaced by one
    generation rep's output.

    Shot metadata (``shot_id``, ``sentence_indices``, ``cast``, ``negative_prompt``) is
    kept from the shipped shot at the same position: the reviewer reads those fields and
    regenerating them is not what is under test. A scene whose rep produced a different
    shot count is SKIPPED and reported — silently zipping mismatched lists would put one
    shot's prompt under another's sentence indices and make every finding unreadable.
    """
    by_scene: dict = {}
    for row in rows:
        if row.get("rep") == rep:
            by_scene.setdefault(row["scene_num"], []).append(row)
    out = []
    for scene in scenes:
        produced = by_scene.get(scene.get("scene_num")) or []
        shots = scene.get("shots") or []
        if len(produced) != len(shots):
            print(f"  skip scene {scene.get('scene_num')}: rep{rep} produced "
                  f"{len(produced)} shots for {len(shots)} shipped", file=sys.stderr)
            continue
        clone = json.loads(json.dumps(scene))
        for shot, row in zip(clone["shots"], produced):
            shot["image_prompt"] = row["image_prompt"]
        out.append(clone)
    return out


async def run(args) -> int:
    store_path = HERE / "visible_event.json"
    if not store_path.is_file():
        print(f"no {store_path.name} — run screen_visible_event.py --legs old,new first",
              file=sys.stderr)
        return _EXIT_NOTHING
    store = json.loads(store_path.read_text(encoding="utf-8"))
    legs = store.get("legs") or {}
    missing = [leg for leg in ("old", "new") if leg not in legs]
    if missing:
        print(f"missing leg(s) {missing} in {store_path.name}", file=sys.stderr)
        return _EXIT_NOTHING

    db = REPO / "yt_flow.db"
    found = S147.load_checkpoint(db, args.run)
    scenes = found.get("scenes") or []
    if not scenes:
        print(f"nothing to measure for thread_id LIKE '{args.run}%'", file=sys.stderr)
        return _EXIT_NOTHING
    scp_id = found.get("scp_id") or ""
    frozen, sheet = S147.grounding(db, scp_id)
    try:
        guide = (REPO / "prompts" / "scenario" / "format_guide.md").read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read format_guide.md: {exc}", file=sys.stderr)
        return _EXIT_NOTHING
    review_text = S147.prompt_text("new", "")  # the working tree's reviewer
    if not review_text.strip():
        return _EXIT_USAGE
    # "working tree == the shipped v11" was asserted in a comment and never checked. If
    # `review.md` carries any local edit the number below is measured against a reviewer
    # nobody ships, while `sample_band` records the opposite.
    dirty = subprocess.run(["git", "-C", str(REPO), "diff", "--stat", "--", S147.PROMPT],
                           capture_output=True, text=True)
    if dirty.stdout.strip():
        print(f"{S147.PROMPT} has uncommitted changes — this would measure a reviewer that "
              f"is not the shipped one:\n{dirty.stdout.strip()}", file=sys.stderr)
        return _EXIT_NOTHING
    compiled = S147.client("v11", review_text)
    s = Settings()  # type: ignore[call-arg]

    limit = asyncio.Semaphore(args.concurrency)
    results: dict = {}
    t0 = time.perf_counter()

    async def one(leg: str, rep: int, scene: dict) -> dict:
        variables = S147.variables(scene, scp_id, found.get("scp_text") or "", frozen, sheet,
                                   guide, len(scenes), True)
        async with limit:
            out = await S147.one_call(compiled, variables, s)
        # 14.7's `one_call` yields `(kind, entry)` pairs, not bare entries.
        entries = [entry for _kind, entry in out.get("entries") or []]
        buckets = Counter(S147.bucket(entry) for entry in entries)
        # The SPEC's acceptance criterion names `descriptor_violation`, which is a typed
        # field of the reviewer's own schema (`REVIEW_ISSUE_TYPES`). 14.7's `bucket()` is a
        # free-text classifier that never reads `entry["type"]`, so counting only its
        # `entity_in_prompt` bucket measured a proxy and called it the AC. Both are kept:
        # the typed count IS the AC, the bucket is the interpretable cross-check.
        typed = Counter(str(entry.get("type") or "") for entry in entries)
        return {"leg": leg, "rep": rep, "scene_num": scene.get("scene_num"),
                "error": out.get("error"), "buckets": dict(buckets), "typed": dict(typed),
                "descriptor_violation": [S147.entry_text(entry)[:300] for entry in entries
                                         if str(entry.get("type")) == "descriptor_violation"],
                # EVERY finding's text, not just one bucket's. `other`/`narration` were
                # unauditable sinks: a real body leak phrased so `bucket()` routes it
                # elsewhere would have been invisible in the evidence file.
                "entries": [{"bucket": S147.bucket(e), "type": str(e.get("type") or ""),
                             "text": S147.entry_text(e)[:400]} for e in entries]}

    for leg in ("old", "new"):
        rows = legs[leg].get("rows") or []
        jobs = []
        for rep in range(1, args.reps + 1):
            for scene in scenes_with(scenes, rows, rep):
                jobs.append(one(leg, rep, scene))
        if not jobs:
            print(f"leg {leg}: no usable rep — nothing to compare", file=sys.stderr)
            return _EXIT_NOTHING
        cells = await asyncio.gather(*jobs, return_exceptions=True)
        crashed = [c for c in cells if isinstance(c, BaseException)]
        for exc in crashed:
            print(f"  ! {leg}: {type(exc).__name__}: {exc}", file=sys.stderr)
        cells = [c for c in cells if not isinstance(c, BaseException)]
        errored = [c for c in cells if c["error"]]
        for cell in errored:
            print(f"  ! {leg} rep{cell['rep']} scene {cell['scene_num']}: {cell['error']}",
                  file=sys.stderr)
        # Only an ALL-errored leg used to halt, so 17 of 18 failures printed `new=0` and
        # exited "no regression" — the gate reads a silence as a clean bill.
        bad = len(errored) + len(crashed)
        if bad > max(1, int(0.1 * (len(cells) + len(crashed)))):
            print(f"leg {leg}: {bad}/{len(cells) + len(crashed)} reviewer calls failed — "
                  "refusing a verdict on the survivors", file=sys.stderr)
            return _EXIT_NOTHING
        totals: Counter = Counter()
        typed_totals: Counter = Counter()
        for cell in cells:
            totals.update(cell["buckets"])
            typed_totals.update(cell["typed"])
        results[leg] = {"cells": len(cells), "errored": len(errored), "crashed": len(crashed),
                        "buckets": dict(totals), "typed": dict(typed_totals),
                        "covered": sorted({(c["rep"], c["scene_num"]) for c in cells}),
                        "rows": cells}
        print(f"[{leg}] cells={len(cells)} errored={len(errored)} buckets={dict(totals)} "
              f"typed={dict(typed_totals)} ({time.perf_counter() - t0:.0f}s)", flush=True)

    # Legs judged over different (rep, scene) slates are not a control/candidate pair:
    # 5 findings over 18 cells vs 0 over 11 would print as a clean win.
    if results["old"]["covered"] != results["new"]["covered"]:
        only_old = set(results["old"]["covered"]) - set(results["new"]["covered"])
        only_new = set(results["new"]["covered"]) - set(results["old"]["covered"])
        print(f"legs cover different (rep, scene) slates — old-only {sorted(only_old)[:5]}, "
              f"new-only {sorted(only_new)[:5]}; refusing a verdict", file=sys.stderr)
        return _EXIT_NOTHING
    entity = {leg: results[leg]["buckets"].get(S147.ENTITY_IN_PROMPT, 0) for leg in results}
    frozen_fp = {leg: results[leg]["buckets"].get(S147.FROZEN_FP, 0) for leg in results}
    typed_dv = {leg: results[leg]["typed"].get("descriptor_violation", 0) for leg in results}
    report = {
        "sample_band": {
            "run": args.run, "thread_id": found.get("thread_id"),
            "checkpoint_id": found.get("checkpoint_id"), "reviewer": "prompts/scenario/review.md",
            "reviewer_live_version": "scenario/review v11 (Story 14.7)",
            "scenes": len(scenes), "reps": args.reps,
            "candidate_source": "visible_event.json legs old/new",
        },
        "entity_in_prompt": entity, "frozen_descriptor_false_positive": frozen_fp,
        "descriptor_violation_typed": typed_dv,
        "buckets": {leg: results[leg]["buckets"] for leg in results},
        "typed": {leg: results[leg]["typed"] for leg in results},
        "total_findings": {leg: sum(results[leg]["buckets"].values()) for leg in results},
        # ABSOLUTE, as the spec's AC is written ("descriptor_violation이 0건"). The relative
        # rule (`new > old`) passed a candidate emitting 4 violations against a control
        # emitting 5. The control is kept for interpretation, never as the bar.
        "verdict": {"ac_met": typed_dv.get("new", 0) == 0 and entity.get("new", 0) == 0,
                    "worse_than_control": (typed_dv.get("new", 0) > typed_dv.get("old", 0)
                                           or entity.get("new", 0) > entity.get("old", 0))},
        "legs": results,
    }
    out_path = HERE / "reviewer_regression.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\ntyped descriptor_violation: old={typed_dv.get('old')} new={typed_dv.get('new')} "
          f"| entity_in_prompt bucket: old={entity.get('old')} new={entity.get('new')} "
          f"| total findings: {report['total_findings']}", flush=True)
    print(f"AC (new == 0): {'MET' if report['verdict']['ac_met'] else 'NOT MET'}", flush=True)
    print(f"elapsed {time.perf_counter() - t0:.0f}s -> {out_path.name}", flush=True)
    return _EXIT_OK if report["verdict"]["ac_met"] else _EXIT_REGRESSION


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("run", help="thread_id prefix, e.g. 4b35c0ed")
    p.add_argument("--reps", type=int, default=5, help="generation reps to review per leg")
    p.add_argument("--concurrency", type=int, default=4)
    args = p.parse_args(argv)
    if args.reps < 1:
        p.error("--reps must be >= 1")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
