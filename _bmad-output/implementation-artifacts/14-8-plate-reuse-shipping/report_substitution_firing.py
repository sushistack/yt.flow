#!/usr/bin/env python3
"""AC6: what plate substitution ACTUALLY did in a live run — not what a replay predicts.

`replay_coverage.py` re-plays the selector offline against a finished checkpoint. This
reads the run's own record instead: the per-shot sidecars image_node wrote while it ran,
plus the warnings the graph carried. The two answer different questions and they are
allowed to disagree — a disagreement is the finding, so both are printed side by side.

    uv run python .../report_substitution_firing.py <run-id-prefix>

Exit 0 on a successful read (a run with zero substitutions is a result, not an error),
2 on a usage error, 3 when the run or its workspace cannot be found.
"""
from __future__ import annotations

import collections
import json
import pathlib
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from yt_flow.config import Settings  # noqa: E402

_USAGE, _NOTFOUND = 2, 3
# The five reasons `_select_plate` can return, in the order it decides them (14.8 re-cut
# 14.1's seven). Listed rather than imported so this report still reads an OLD run whose
# warnings carry a retired reason: an unknown reason is printed, never dropped.
_REASONS = ("unknown_framing", "unservable_framing", "no_metadata",
            "plate_shows_person", "no_standing_room")


def _settings() -> Settings:
    return Settings(_env_file=REPO / ".env")  # cwd-independent, like replay_coverage.py


def _resolve(db: sqlite3.Connection, prefix: str) -> str:
    rows = [r[0] for r in db.execute("select id from run where id like ?", (prefix + "%",))]
    if not rows:
        sys.exit(f"no run matches prefix {prefix!r}")
    if len(rows) > 1:
        sys.exit(f"prefix {prefix!r} is ambiguous: {rows}")
    return rows[0]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return _USAGE
    s = _settings()
    db_path = REPO / s.db_path if not pathlib.Path(s.db_path).is_absolute() else pathlib.Path(s.db_path)
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    run_id = _resolve(db, argv[1])
    row = db.execute("select status, current_stage, error from run where id=?", (run_id,)).fetchone()
    print(f"run {run_id}\n  status={row[0]}  stage={row[1]}  error={row[2]}")

    ws = REPO / s.workspace_path / run_id / "images"
    if not ws.is_dir():
        print(f"  workspace absent: {ws}")
        return _NOTFOUND

    # -- what the run recorded per shot -------------------------------------------------
    hits, generated, unreadable = [], [], []
    for f in sorted(ws.glob("*_done.json")):
        try:
            side = json.loads(f.read_text())
        except Exception as e:                     # a corrupt sidecar is data, not a crash
            unreadable.append((f.name, str(e)))
            continue
        sp = (side.get("provenance") or {}).get("stock_plate")
        (hits if sp else generated).append((f.name, sp))

    total = len(hits) + len(generated)
    print(f"\n-- shots with an image sidecar: {total} --")
    print(f"  plate-served : {len(hits)}")
    print(f"  generated    : {len(generated)}")
    if unreadable:
        print(f"  unreadable   : {len(unreadable)}  {unreadable}")

    if hits:
        by_key = collections.Counter(sp["location_key"] for _, sp in hits)
        by_plate = collections.Counter(f'{sp["location_key"]}/{sp["variant"]}' for _, sp in hits)
        axes = collections.Counter(sp.get("axis", "<unmarked>") for _, sp in hits)
        print("\n-- which plates served, by key --")
        for k, n in sorted(by_key.items()):
            print(f"  {k:<22} {n}")
        print("\n-- variant spread (a re-used plate is intent, not a regression) --")
        for k, n in sorted(by_plate.items()):
            print(f"  {k:<24} {n}")
        print(f"\n-- assigning axis recorded in the sidecar: {dict(axes)}")

    # -- why the rest fell back ---------------------------------------------------------
    cur = db.execute(
        "select checkpoint from checkpoints where thread_id=? order by rowid desc limit 1",
        (run_id,)).fetchone()
    if cur is None:
        print("\n-- no checkpoint row: fallback reasons unavailable --")
        return 0
    try:
        import ormsgpack
        chk = ormsgpack.unpackb(cur[0])
    except Exception as e:
        print(f"\n-- checkpoint unreadable ({e}) --")
        return 0
    warns = ((chk.get("channel_values") or {}).get("run_warnings")) or []
    codes = collections.Counter(w.get("code") for w in warns if isinstance(w, dict))
    unfit = collections.Counter(
        (w.get("context") or {}).get("reason", "<no reason>")
        for w in warns if isinstance(w, dict) and w.get("code") == "stock_plate_unfit")
    print("\n-- warnings carried by the run --")
    for c, n in sorted(codes.items(), key=lambda kv: -kv[1]):
        print(f"  {c:<34} {n}")
    print("\n-- stock_plate_unfit, by reason (selector order; unknown reasons kept) --")
    for r in _REASONS:
        if unfit.get(r):
            print(f"  {r:<22} {unfit[r]}")
    for r, n in sorted(unfit.items()):
        if r not in _REASONS:
            print(f"  {r:<22} {n}   <-- not in this build's vocabulary")
    if not unfit:
        print("  (none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
