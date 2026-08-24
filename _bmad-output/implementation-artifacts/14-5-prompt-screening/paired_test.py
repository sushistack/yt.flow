#!/usr/bin/env python
"""Story 14.5: is the old→new difference bigger than the harness's own noise? No calls.

Spec: ``_bmad-output/implementation-artifacts/spec-14-5-narration-plate-pose-match.md``

``screen_visible_event.py``'s exit code is a strict inequality on two pooled rates, and
that is not a verdict: on this data the per-generation-rep spread WITHIN each leg is
14.3 pp while the between-leg gap is 2.9 pp. A gate that passes on a difference five
times smaller than its own scatter is the mirror image of the failure Story 14.7 hit
(`gotcha_a-screening-gate-can-fail-on-its-own-threshold`) — there noise made a live
rule look dead, here it would make a dead edit look live. So the pooled number gets a
paired test beside it, and the report quotes both.

    uv run python .../paired_test.py

Pairs on the SHOT, not the rep: every event-bearing shot was generated 5 times under
each prompt version, so each shot contributes ``old_hits/5`` vs ``new_hits/5`` and the
between-rep scatter that swamps the pooled comparison is inside the pair. Two-sided
exact sign test over the shots that moved (stdlib ``math.comb``, no scipy, no RNG —
a permutation p-value that changes between runs is not re-derivable).

Reports three axes separately because they are three different claims:
  * ``event_bearing``  — the target. Higher is better.
  * ``no_event``       — the guardrail. LOWER is better: a rise means the edit taught
                         the model to invent events for sentences that have none.
  * ``present_subject`` — the 10.2 regression line. Must stay at 1.0.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sign_test(pairs: list[tuple[float, float]]) -> dict:
    """Two-sided exact sign test. Ties are dropped, and their count is REPORTED —
    dropping them silently is how a 4-of-140 difference gets to look decisive."""
    up = sum(1 for old, new in pairs if new > old)
    down = sum(1 for old, new in pairs if new < old)
    ties = len(pairs) - up - down
    n = up + down
    if n == 0:
        return {"pairs": len(pairs), "up": up, "down": down, "ties": ties, "p_two_sided": 1.0}
    k = min(up, down)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return {"pairs": len(pairs), "up": up, "down": down, "ties": ties,
            "moved": n, "p_two_sided": round(min(1.0, 2 * tail), 4)}


def main() -> int:
    store_path = HERE / "visible_event.json"
    if not store_path.is_file():
        print(f"no {store_path.name}", file=sys.stderr)
        return 2
    store = json.loads(store_path.read_text(encoding="utf-8"))
    legs = store.get("legs") or {}
    if not {"old", "new"} <= set(legs):
        print("need both `old` and `new` legs", file=sys.stderr)
        return 2

    # shot_id -> {leg: [bool, ...]} for each axis
    axes = {"visible_event": ("has_event", True), "no_event_visible_event": ("has_event", False),
            "present_subject": (None, None)}
    out: dict = {"note": __doc__.split("\n\n")[1].strip() if __doc__ else ""}
    for axis, (filter_field, want) in axes.items():
        field = "present_subject" if axis == "present_subject" else "visible_event"
        # Keyed on the SENTENCE, not the positional `shot_id`. `shot_id` is minted from a
        # rep's own cover position, so a rep that merged or split differently would pair
        # position N of one leg against a different sentence in the other. The first
        # version of this script keyed on `shot_id` alone; on this data all 5 reps of both
        # legs produced a 1:1 cover, so it happened to be right — by luck, not by guard.
        buckets: dict = defaultdict(lambda: {"old": [], "new": []})
        for leg in ("old", "new"):
            for row in legs[leg]["rows"]:
                if field not in row:
                    continue
                if filter_field is not None and row.get(filter_field) is not want:
                    continue
                buckets[row["sentence"]][leg].append(bool(row[field]))
        pairs, dropped, uneven = [], 0, 0
        for _sentence, cells in sorted(buckets.items()):
            # A sentence a leg never produced (the cover merged it away that rep) is
            # dropped from the PAIRED test and counted — a one-sided cell is not a pair.
            if not cells["old"] or not cells["new"]:
                dropped += 1
                continue
            if len(cells["old"]) != len(cells["new"]):
                # Unequal rep counts make `mean_old` and `mean_new` different estimators.
                uneven += 1
            pairs.append((sum(cells["old"]) / len(cells["old"]),
                          sum(cells["new"]) / len(cells["new"])))
        result = sign_test(pairs)
        result["cells_dropped_unpaired"] = dropped
        result["cells_with_unequal_rep_counts"] = uneven
        if pairs:
            result["mean_old"] = round(sum(p[0] for p in pairs) / len(pairs), 4)
            result["mean_new"] = round(sum(p[1] for p in pairs) / len(pairs), 4)
            result["mean_delta"] = round(result["mean_new"] - result["mean_old"], 4)
        out[axis] = result

    # The scatter the pooled gate ignores, printed next to the pooled gap it passed on.
    for leg in ("old", "new"):
        spread = legs[leg]["tally"].get("per_rep_spread") or {}
        out.setdefault("per_rep_spread", {})[leg] = spread
    out["pooled_event_bearing"] = {
        leg: legs[leg]["tally"]["event_bearing_visible_event"] for leg in ("old", "new")}
    # The POOLED rate the spec's AC actually named, printed beside the split it was
    # replaced by. On this data the two disagree in SIGN, so quoting only one is the
    # `gotcha_summary-from-a-capped-list-drops-the-severest-item` shape.
    out["pooled_all_rows"] = {
        leg: legs[leg]["tally"]["pooled_visible_event"] for leg in ("old", "new")}
    # p is not a verdict of "no effect". With 16 of 28 pairs tied the sign test runs on 12
    # movable cells and has almost no power at ~3 pp — absence of evidence, not evidence
    # of absence. Stated in the artifact so a later reader cannot quote p as a null result.
    out["power_note"] = (
        "Sign test over movable pairs only. A non-significant p here means the design "
        "cannot resolve an effect of this size, NOT that the effect is zero."
    )
    (HERE / "paired_test.json").write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "note"}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
