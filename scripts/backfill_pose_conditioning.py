#!/usr/bin/env python
"""Backfill Character.pose_conditioning for the curated cast (Story 8.20, AC4).

``db.init()``'s additive migration sets every existing row to the safe
``edit_only`` default. That is correct but useless: it opts the whole library out
of structural conditioning. This script applies the *curated* mapping, which is
a human judgement about each character's anatomy and cannot be derived from the
card key or the descriptor (AC4 forbids that inference — "SCP-1471" and
"SCP-096" are indistinguishable as strings but need opposite routes).

Idempotent: re-running reports "unchanged" for rows already at their target.

Run: uv run python scripts/backfill_pose_conditioning.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.db.models import Character  # noqa: E402
from yt_flow.domain.pose import DEFAULT_POSE_CONDITIONING, POSE_CONDITIONING_PROFILES  # noqa: E402

# The curated mapping. Every entry is a deliberate anatomy call:
#
#   openpose   — human-shaped body a COCO-18 skeleton describes correctly.
#                SCP-049's plague-doctor mask and SCP-096's proportions are
#                stylised but still bipedal-humanoid, so the skeleton holds.
#   scribble   — non-human body. A human skeleton's 18 keypoints name eyes,
#                ears, and a two-arm topology a reptile does not have, so the
#                guide carries silhouette only.
#   edit_only  — anatomy is ambiguous or contested; no structural guide until a
#                human curates it. Reference-only editing still works.
#
# SCP-1471 is deliberately edit_only: it presents as a canine-headed humanoid in
# some depictions and a full quadruped in others, so neither route is safely
# correct without an explicit approval decision.
CURATED: dict[str, str] = {
    "STOCK-d-class": "openpose",
    "STOCK-researcher": "openpose",
    "STOCK-security": "openpose",
    "SCP-049": "openpose",
    "SCP-049-2": "openpose",
    "SCP-096": "openpose",
    "SCP-682": "scribble",
    "SCP-1471": "edit_only",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report the plan without writing")
    args = ap.parse_args()

    # Guard the table itself: a typo here would write a value the routing layer
    # cannot honour, and the failure would surface as a silent edit_only later.
    bad = {k: v for k, v in CURATED.items() if v not in POSE_CONDITIONING_PROFILES}
    if bad:
        print(f"ERROR: curated mapping has values outside the closed vocabulary: {bad}")
        return 1

    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    changed = unchanged = uncurated = 0
    with Session(db.get_engine()) as session:
        for ch in session.exec(select(Character)).all():
            target = CURATED.get(ch.scp_id)
            if target is None:
                # Not an error: a future character legitimately has no curated
                # entry yet and stays on the safe default.
                uncurated += 1
                print(f"  {ch.scp_id:20s} uncurated -> stays {ch.pose_conditioning!r}")
                continue
            if ch.pose_conditioning == target:
                unchanged += 1
                print(f"  {ch.scp_id:20s} unchanged  {target}")
                continue
            print(f"  {ch.scp_id:20s} {ch.pose_conditioning!r} -> {target!r}")
            if not args.dry_run:
                ch.pose_conditioning = target
                session.add(ch)
            changed += 1
        if not args.dry_run:
            session.commit()

    print(
        f"\n{'DRY RUN — ' if args.dry_run else ''}changed={changed} unchanged={unchanged} "
        f"uncurated={uncurated} (uncurated rows keep the safe {DEFAULT_POSE_CONDITIONING!r} default)",
    )
    print(f"curated catalog covers {len(CURATED)} characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
