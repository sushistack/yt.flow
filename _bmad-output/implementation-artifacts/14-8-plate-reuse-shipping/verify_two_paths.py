#!/usr/bin/env python
"""Story 14.8 T2: the adopted axis (2) over the approved 42, by two paths each. GPU 0, VLM 0.

    uv run python .../14-8-plate-reuse-shipping/verify_two_paths.py

`AXIS-CANDIDATES.md` adopted axis (2): `shot.location_key == plate.location_key`, with the
shipped filters inherited unchanged. This script does NOT call a new judge. Both paths for
every predicate already exist in `assets/manifest.json`, written months apart by different
callers with different prompts:

    source.label      2026-08-02  scripts/label_location_plates.py  (8.17 auto-labeler)
    source.plate_meta 2026-08-25  14-1-approved-plate-sets/measure_plates.py

plus the human blind `floor_share` column of `viewpoint_verdicts.csv` for the affordance
predicate. Reading is the whole job: a new measurement would re-introduce exactly the
error this story diagnosed.

Everything it decides — which predicates, which two paths, what counts as a comparable
row, the P4 contradiction rule, rule U, and the band — is fixed in `PREREGISTRATION.md`
(committed BEFORE this file existed) and only quoted here. Read-only throughout: it opens
the manifest and the DB for reading and writes nothing. Two runs are byte-identical.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))

from yt_flow.config import Settings  # noqa: E402

CSV_PATH = HERE.parent / "14-1-approved-plate-sets" / "viewpoint_verdicts.csv"

# PREREGISTRATION.md §2 — pinned before this file existed. `git log --diff-filter=A` on the
# two paths proves the order. B1 gates P1 only; §1 says why the inherited filters are
# reported and not gated, and rule U says an empty comparison is never a PASS.
BAND_B1 = 0.050
# PREREGISTRATION.md §1 "P4의 비교 규칙": the two paths ask different questions, so only a
# contradiction counts. 0.20 = 6x the +/-0.03 read error of `floor_share`
# (REREAD-2026-08-30.md:50). Same test report.md:147-158 already applied to server-room/b.
P4_FLOOR_CONTRADICTION = 0.20


def fmt(v: object) -> str:
    return "-" if v is None else {True: "T", False: "F"}.get(v, str(v))  # type: ignore[arg-type]


def main() -> int:
    settings = Settings()
    manifest_path = REPO / settings.assets_path / "manifest.json"
    raw = manifest_path.read_bytes()
    assets = json.loads(raw)["assets"]
    plates = {k: v for k, v in sorted(assets.items())
              if str(v.get("path", "")).startswith("locations/") and v.get("status") == "approved"}
    floor = {}
    with CSV_PATH.open(encoding="utf-8") as fh:
        for row in csv.DictReader(line for line in fh if not line.startswith("#")):
            floor[row["plate"]] = float(row["floor_share"])
    with sqlite3.connect(f"file:{REPO / settings.db_path}?mode=ro", uri=True) as conn:
        db_keys = {f"{k}/{v}": k for k, v in conn.execute(
            "SELECT location_key, variant FROM location_plates WHERE status='approved'")}

    print("verify_two_paths.py — Story 14.8 T2, adopted axis (2) = location_key")
    print(f"sample band: {manifest_path.relative_to(REPO)} sha256 {hashlib.sha256(raw).hexdigest()[:16]}"
          f"  ·  {len(plates)} approved location plates  ·  VLM calls 0, GPU 0")
    print(f"band       : B1 = {BAND_B1:.1%} of {len(plates)} -> PASS <=2 rows / FAIL >=3"
          "   [PREREGISTRATION.md §2, committed before this file]")

    # ---- the 42-row two-path table ------------------------------------------------
    print("\n-- every approved plate, both paths, all four predicates --")
    print("            P1 = location_key      P2 = has_person   P3 = depicts_person   "
          "P4 = standing_room / floor_share")
    print(f"{'plate':24s} {'P1.A struct':20s} {'P1.B match':10s} {'P2.A':5s}{'P2.B':5s}"
          f"{'P3.A':5s}{'P3.B':5s}{'P4.A':6s}{'P4.B':6s}")
    rows = []
    for key, entry in plates.items():
        src = entry.get("source") or {}
        label = src.get("label") or {}
        meta = src.get("plate_meta") or {}
        struct = key.split("/")[0]
        r = {
            "plate": key,
            # P1.A is only "structural" if the manifest key, the `location_key` field, the
            # `path` and the DB row all say the same thing — four copies, so a drift
            # between any two of them is a P1 disagreement, not a silent pick of one.
            "p1a": struct if (entry.get("location_key") == struct
                              and str(entry.get("path", "")).split("/")[1] == struct
                              and db_keys.get(key) == struct) else "STRUCT-DRIFT",
            "p1b": label.get("matches_location"),
            "p2a": label.get("has_person"), "p2b": meta.get("has_person"),
            "p3a": meta.get("depicts_person"), "p3b": label.get("depicts_person"),
            "p4a": meta.get("standing_room"), "p4b": floor.get(key),
        }
        rows.append(r)
        share = "-" if r["p4b"] is None else f"{r['p4b']:.2f}"
        print(f"{r['plate']:24s} {r['p1a']:20s} {fmt(r['p1b']):10s} "
              f"{fmt(r['p2a']):5s}{fmt(r['p2b']):5s}{fmt(r['p3a']):5s}{fmt(r['p3b']):5s}"
              f"{fmt(r['p4a']):6s}{share:6s}")

    # ---- per-predicate verdicts -----------------------------------------------------
    def report(name: str, comparable, disagree, gated: bool) -> str:
        n, d = len(comparable), len(disagree)
        if n == 0:
            # PREREGISTRATION.md §1 rule U. An empty comparison is never a PASS.
            verdict = "UNDEFINED (0 comparable rows)"
        elif not gated:
            verdict = f"{d}/{n} = {d / n:.1%}  (reported, not gated — PREREGISTRATION §1)"
        else:
            verdict = (f"{d}/{n} = {d / n:.1%}  vs band {BAND_B1:.1%}  ->  "
                       f"{'PASS' if d <= int(BAND_B1 * n) else 'FAIL'}")
        print(f"\n-- {name} --\n  comparable {n}/{len(rows)}   disagree {d}\n  VERDICT: {verdict}")
        for line in disagree:
            print(f"    {line}")
        return verdict

    p1c = [r for r in rows if isinstance(r["p1b"], bool)]
    p1d = [f"{r['plate']:24s} pathA={r['p1a']}  matches_location={r['p1b']}"
           for r in p1c if r["p1a"] == "STRUCT-DRIFT" or r["p1b"] is not True]
    v1 = report("P1  location_key : structural(4 copies) vs label.matches_location  [GATED]",
                p1c, p1d, gated=True)

    p2c = [r for r in rows if isinstance(r["p2a"], bool) and isinstance(r["p2b"], bool)]
    v2 = report("P2  has_person : label(2026-08-02) vs plate_meta(2026-08-25)",
                p2c, [f"{r['plate']:24s} label={r['p2a']}  plate_meta={r['p2b']}"
                      for r in p2c if r["p2a"] != r["p2b"]], gated=False)

    p3c = [r for r in rows if isinstance(r["p3a"], bool) and isinstance(r["p3b"], bool)]
    v3 = report("P3  depicts_person : plate_meta(2026-08-25) vs label(8.17 labeler)",
                p3c, [f"{r['plate']:24s} plate_meta={r['p3a']}  label={r['p3b']}"
                      for r in p3c if r["p3a"] != r["p3b"]], gated=False)

    p4c = [r for r in rows if isinstance(r["p4a"], bool) and r["p4b"] is not None]
    p4d = [f"{r['plate']:24s} standing_room={r['p4a']}  floor_share={r['p4b']:.2f}  "
           f"({'room claimed with no floor seen' if r['p4a'] else 'no room claimed over a floor'})"
           for r in p4c
           if (r["p4a"] and r["p4b"] == 0.0) or (not r["p4a"] and r["p4b"] >= P4_FLOOR_CONTRADICTION)]
    v4 = report("P4  standing_room(VLM) vs floor_share(human, blind) — contradiction only",
                p4c, p4d, gated=False)

    print("\n-- T2 summary --")
    for name, v in (("P1 [GATED]", v1), ("P2", v2), ("P3", v3), ("P4", v4)):
        print(f"  {name:11s} {v}")
    print("\nP1 is the axis itself and is the only pass/fail. P2-P4 are filters this story")
    print("inherits unchanged; UNDEFINED rows are open findings, never a PASS (rule U).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
