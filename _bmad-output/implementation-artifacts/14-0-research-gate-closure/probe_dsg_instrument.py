#!/usr/bin/env python3
"""Story 14.0 §4-5: why `dsg_score` does not correlate with `readable`, and why
unreadable frames score HIGHER.

13.2 recorded the anomaly (rank correlation 0.0263; mean DSG 0.5694 unreadable vs
0.4892 readable) and forbade using any visual axis as a gate until it was
understood. This decomposes it from 13.2's own committed output. No render, no
VLM call, no GPU — it only re-reads `13-2-live-validation/baseline_v3.json`.

The question it answers is not "is the number bad" but "which way does the bias
run", because a dead axis and an inverted axis need different verdicts: a dead
axis is useless, an inverted axis actively rewards the defect.

Exit codes: 0 = printed, 2 = usage, 3 = input missing/unusable.
"""

import json
import sys
from collections import Counter
from pathlib import Path

DEFAULT = (Path(__file__).resolve().parents[1]
           / "13-2-live-validation" / "baseline_v3.json")


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Tie-corrected rank correlation. Hand-rolled: scipy is not a dependency
    here and this is 12 lines. ponytail: exact ties get the average rank, which
    matters because `readable` is binary and half the dsg values repeat."""
    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    a, b = ranks(xs), ranks(ys)
    n = len(xs)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return round(num / den, 4) if den else None


def surviving(row: dict, kinds: set[str] | None = None) -> list[dict]:
    """Propositions that actually entered the score: person-excluded and
    dependency-invalidated ones are removed by 13.2's own scoring rule."""
    return [p for p in row["proposition_answers"]
            if not p.get("excluded") and not p.get("invalidated")
            and (kinds is None or p["kind"] in kinds)]


def yes_rate(row: dict, kinds: set[str]) -> tuple[float | None, int]:
    ps = surviving(row, kinds)
    if not ps:
        return None, 0
    return sum(1 for p in ps if p.get("answer") is True) / len(ps), len(ps)


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print(f"usage: {Path(argv[0]).name} [baseline_v3.json]", file=sys.stderr)
        return 2
    path = Path(argv[1]) if len(argv) == 2 else DEFAULT
    if not path.exists():
        print(f"no scoring output at {path}", file=sys.stderr)
        return 3
    rows = json.loads(path.read_text()).get("rows") or []
    if not rows or "proposition_answers" not in rows[0]:
        print(f"{path} has no per-proposition answers to decompose", file=sys.stderr)
        return 3

    print(f"source: {path}")
    print(f"rows: {len(rows)}  readable: {sum(1 for r in rows if r.get('readable'))}"
          f"  unreadable: {sum(1 for r in rows if not r.get('readable'))}\n")

    # 1. the aggregate, then each sub-axis. The sign is the whole point.
    print("axis decomposition — rho vs `readable`, and the readable/unreadable gap")
    print(f"{'axis':30}{'n':>4}{'rho':>9}{'readable':>10}{'unread':>9}{'gap':>9}")
    axes: list[tuple[str, set[str] | None]] = [
        ("dsg_score (all surviving)", None),
        ("place only", {"place"}),
        ("state only", {"state"}),
        ("state+object (event axis)", {"state", "object"}),
    ]
    for label, kinds in axes:
        xs, ys, r_vals, u_vals = [], [], [], []
        for row in rows:
            val = row["dsg_score"] if kinds is None else yes_rate(row, kinds)[0]
            if val is None:
                continue
            xs.append(val)
            ys.append(1 if row.get("readable") else 0)
            (r_vals if row.get("readable") else u_vals).append(val)
        mr, mu = sum(r_vals) / len(r_vals), sum(u_vals) / len(u_vals)
        print(f"{label:30}{len(xs):>4}{spearman(xs, ys):>9}"
              f"{mr:>10.4f}{mu:>9.4f}{mr - mu:>+9.4f}")

    # 2. the denominator. A 2-3 question denominator cannot carry a continuous score.
    print("\ndenominator (`dsg_scored_n`)")
    counts = Counter(r["dsg_scored_n"] for r in rows)
    for k in sorted(counts):
        print(f"  {k} questions: {counts[k]} rows")
    for name, group in (("readable", [r for r in rows if r.get("readable")]),
                        ("unreadable", [r for r in rows if not r.get("readable")])):
        print(f"  mean scored_n {name:11}: {sum(r['dsg_scored_n'] for r in group)/len(group):.4f}"
              f"   mean person-excluded: "
              f"{sum(r['dsg_excluded_person_n'] for r in group)/len(group):.4f}")
    grid = Counter(round(r["dsg_score"], 4) for r in rows)
    pinned = sum(v for k, v in grid.items() if k in (0.0, 1.0))
    print(f"  distinct dsg values: {len(grid)}   pinned at 0.0/1.0: {pinned}/{len(rows)}")

    # 3. the event axis vanishes entirely on some rows, leaving only the flat one.
    gone = [r["shot_id"] for r in rows if yes_rate(r, {"state", "object"})[1] == 0]
    print(f"\nrows with ZERO surviving state/object question: {len(gone)}/{len(rows)}")
    print("  " + " ".join(gone))

    # 4. the blind axes, as the control: is anything there actually varying?
    def named(v: object) -> bool:
        s = str(v).strip().lower() if v else ""
        return bool(s) and s not in {"none", "unknown", "n/a", "-"}

    print("\nblind-pass axes (control — these are NOT prompt-derived)")
    print(f"  place named : {sum(1 for r in rows if named(r.get('place')))}/{len(rows)}")
    print(f"  event named : {sum(1 for r in rows if named(r.get('event')))}/{len(rows)}")
    print(f"  readable    : {sum(1 for r in rows if r.get('readable'))}/{len(rows)}")
    ms = Counter(r.get("match_score") for r in rows)
    print(f"  match_score : {dict(sorted(ms.items(), key=lambda kv: (kv[0] is None, kv[0])))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
