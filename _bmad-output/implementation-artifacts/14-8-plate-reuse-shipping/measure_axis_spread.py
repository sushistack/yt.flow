#!/usr/bin/env python
"""Story 14.8 T1: does a CONTINUOUS `y_h` ranking survive the judge error? GPU 0, VLM 0.

    uv run python .../14-8-plate-reuse-shipping/measure_axis_spread.py

Candidate (4) of `AXIS-CANDIDATES.md` drops the HIGH/EYE/LOW category boundaries and
ranks a location_key's plates by |y_h - target| instead. That trade only pays if the
*gap between the candidates it is ranking* is bigger than the error with which `y_h` is
read. So this script prints, from the 42 committed rows of
`14-1-approved-plate-sets/viewpoint_verdicts.csv` and nothing else:

  (c) per `location_key`: the y_h spread (max-min) and the SMALLEST adjacent gap the
      ranking has to resolve. A ranking cannot be more reliable than its tightest pair.
  (b) the judge error, quoted from the two independent controls that measured it.
  and, for candidate (1)'s (c), each plate's distance to the nearest category boundary.

It reads ONE committed CSV, holds no state and calls nothing. Two runs are byte-identical
(`diff <(cmd) <(cmd)`), which is the AC's determinism check.

The REREAD second pass is printed BESIDE the first, never over it
(`REREAD-2026-08-30.md:39` — "두 판정을 병기하라"): overwriting is what erases the
disagreement this whole story rests on.
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE.parent / "14-1-approved-plate-sets" / "viewpoint_verdicts.csv"

# (b) — the reproduction error of `y_h`, from the ONE control that measured it by having
# two independent blind judges read the SAME five images:
# `14-1-approved-plate-sets/AUGMENTATION-BATCH-2026-08-30.md:45`
#   "범주 뒤집힘 2/5 · |Δy_h| 최대 0.12 · 평균 0.072."
JUDGE_ERR_MEAN, JUDGE_ERR_MAX = 0.072, 0.12

# PREREGISTRATION.md (14.1) §2 — the two category boundaries the retired axis used.
BOUNDARIES = (0.40, 0.60)

# The location_keys run `4b35c0ed` actually demands inside the servable-24 denominator.
# Not re-derived here (that needs the checkpoint); copied from the committed replay:
#   uv run python .../14-1-approved-plate-sets/replay_coverage.py 4b35c0ed
# whose "-- demanded cells --" block lists 10 (key, viewpoint) cells over these 6 keys.
DEMANDED = ("autopsy-room", "containment-chamber", "control-room", "corridor",
            "medical-bay", "observation-room")

# Second-pass `y_h`, read by a repo-blind judge at higher magnification:
# `REREAD-2026-08-30.md:20-31`. Recorded ALONGSIDE the CSV, never merged into it.
REREAD = {"corridor/a": 0.55, "corridor/b": 0.51, "corridor/c": 0.52,
          "medical-bay/b": 0.47, "observation-room/a": 0.40, "observation-room/b": 0.42}


def rows() -> list[dict]:
    with CSV_PATH.open(encoding="utf-8") as fh:
        return list(csv.DictReader(line for line in fh if not line.startswith("#")))


def gaps(values: list[float]) -> list[float]:
    s = sorted(values)
    return [round(b - a, 3) for a, b in zip(s, s[1:])]


def main() -> int:
    data = rows()
    y = {r["plate"]: float(r["y_h"]) for r in data}
    by_key: dict[str, list[str]] = defaultdict(list)
    for plate in y:
        by_key[plate.split("/")[0]].append(plate)

    print(f"source : {CSV_PATH.relative_to(HERE.parents[2])}  ({len(data)} rows)")
    print(f"(b)    : judge error mean {JUDGE_ERR_MEAN:.3f} / max {JUDGE_ERR_MAX:.3f}"
          "  [AUGMENTATION-BATCH-2026-08-30.md:45]")
    vals = sorted(y.values())
    print(f"\n-- whole corpus --\nn={len(vals)}  min {vals[0]:.3f}  max {vals[-1]:.3f}  "
          f"mean {statistics.fmean(vals):.3f}  median {statistics.median(vals):.3f}  "
          f"stdev {statistics.stdev(vals):.3f}")
    verdicts: dict[str, int] = defaultdict(int)
    for r in data:
        verdicts[r["verdict"]] += 1
    print("verdicts: " + "  ".join(f"{k} {verdicts[k]}" for k in sorted(verdicts)))

    print("\n-- (c) for candidate (4): the gap a within-key ranking must resolve --")
    print(f"{'location_key':22s} {'n':>2s}  {'y_h values':26s} {'spread':>6s} "
          f"{'min_gap':>7s}  gap>{JUDGE_ERR_MEAN:.3f}?  demanded")
    min_gaps, spreads, resolvable, resolvable_demanded = {}, {}, [], []
    for key in sorted(by_key):
        vs = sorted(y[p] for p in by_key[key])
        spread = round(vs[-1] - vs[0], 3)
        g = gaps(vs)
        mg = min(g) if g else 0.0
        min_gaps[key], spreads[key] = mg, spread
        ok = mg > JUDGE_ERR_MEAN
        if ok:
            resolvable.append(key)
            if key in DEMANDED:
                resolvable_demanded.append(key)
        print(f"{key:22s} {len(vs):2d}  {' '.join(f'{v:.2f}' for v in vs):26s} "
              f"{spread:6.3f} {mg:7.3f}  {'YES' if ok else 'no ':13s} "
              f"{'yes' if key in DEMANDED else '.'}")
    print(f"\nkeys whose tightest pair EXCEEDS the mean judge error: "
          f"{len(resolvable)}/{len(by_key)}  {sorted(resolvable)}")
    print(f"  ... among the {len(DEMANDED)} keys run 4b35c0ed demands: "
          f"{len(resolvable_demanded)}/{len(DEMANDED)}  {sorted(resolvable_demanded)}")
    print(f"median min_gap {statistics.median(min_gaps.values()):.3f}   "
          f"median spread {statistics.median(spreads.values()):.3f}")

    print(f"\n-- (c) for candidate (1): distance to the nearest boundary {BOUNDARIES} --")
    dist = {p: round(min(abs(v - b) for b in BOUNDARIES), 3) for p, v in y.items()}
    near_mean = sorted(p for p, d in dist.items() if d < JUDGE_ERR_MEAN)
    near_max = sorted(p for p, d in dist.items() if d < JUDGE_ERR_MAX)
    print(f"within the MEAN judge error {JUDGE_ERR_MEAN:.3f}: {len(near_mean)}/{len(y)} "
          f"({len(near_mean) / len(y):.1%})  -> category assignment is a coin flip")
    print(f"within the MAX  judge error {JUDGE_ERR_MAX:.3f}: {len(near_max)}/{len(y)} "
          f"({len(near_max) / len(y):.1%})")
    for p in sorted(dist, key=lambda k: (dist[k], k)):
        flag = "**" if dist[p] < JUDGE_ERR_MEAN else ("* " if dist[p] < JUDGE_ERR_MAX else "  ")
        print(f"  {flag} {p:24s} y_h {y[p]:.2f}  d(boundary) {dist[p]:.3f}")

    print("\n-- second reading recorded ALONGSIDE the first (REREAD-2026-08-30.md:20-31) --")
    print(f"{'location_key':22s} {'spread(1st)':>11s} {'spread(2nd where read)':>23s} "
          f"{'level shift':>11s}   reread rows")
    for key in sorted({p.split("/")[0] for p in REREAD}):
        mixed = [REREAD.get(p, y[p]) for p in by_key[key]]
        only = [(REREAD[p] - y[p]) for p in by_key[key] if p in REREAD]
        print(f"{key:22s} {spreads[key]:11.3f} {round(max(mixed) - min(mixed), 3):23.3f} "
              f"{statistics.fmean(only):+11.3f}   "
              f"{', '.join(sorted(p for p in by_key[key] if p in REREAD))}")
    print("the LEVEL moves by more than the SPREAD: a within-key ranking is re-judged"
          " wholesale while the order it ranks stays inside the error.")

    worst = statistics.median(min_gaps.values())
    print(f"\nVERDICT candidate (4): (b)={JUDGE_ERR_MEAN:.3f} vs (c)=median min_gap "
          f"{worst:.3f}  ->  {'ADMISSIBLE' if JUDGE_ERR_MEAN < worst else 'REJECT — (b) > (c)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
