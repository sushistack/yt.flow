#!/usr/bin/env python
"""Story 14.6: align manifest entries that are `approved` while their DB row is `retired`.

Spec: `_bmad-output/implementation-artifacts/spec-14-6-dclass-object-asset-sets.md`

`approve_stock_cast._retire_special_pose_cards` retires the `character_cards` row and
then retires the manifest entry inside a best-effort `try`, so a failure there leaves
the manifest claiming `approved` for a card the DB has withdrawn. `AssetService` has
no inverse of `approve_asset`, so this only ever moves entries in the SAFE direction:
`retire`, never `approve`.

    uv run python .../reconcile_manifest.py --dry-run     # list, change nothing
    uv run python .../reconcile_manifest.py --commit      # retire the listed entries

`--dry-run` and `--commit` are MUTUALLY EXCLUSIVE and argparse refuses both together.
An earlier iteration accepted both and silently wrote — with `retire_asset` having no
inverse, "I passed --dry-run and it wrote anyway" is unrecoverable.

Exit codes (only the ones this script actually returns):
    0  read succeeded — entries listed, and written if `--commit`
    1  HALT: at least one entry is `retired` in the manifest while its row is
       `approved`. That is drift in the APPROVAL direction and this script is not
       entitled to decide it; the opposite direction was already adjudicated by Story
       10.8. `draft` is not this: it is the normal gap between `add_asset` and
       `approve_asset` and would strand every legitimate row forever.
    2  argparse usage error (including `--dry-run --commit`)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# cwd independence, and it is load-bearing rather than tidy: `Settings.db_path` and
# `assets_path` are RELATIVE ("yt_flow.db", "./assets"), and `AssetService.__init__`
# mkdirs its subdirectories. Run from anywhere else and this script CREATES an empty
# assets tree and reads an empty DB, then prints "nothing to align" and exits 0 — a
# green lie. Story 14.5's harness took the same `os.chdir` for the same reason.
_REPO_ROOT = Path(__file__).resolve().parents[3]
os.chdir(_REPO_ROOT)
sys.path.insert(0, str(_REPO_ROOT / "src"))

from sqlmodel import Session, select  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.db.models import CharacterCard  # noqa: E402
from yt_flow.services.asset_service import AssetService  # noqa: E402
from yt_flow.services.character_service import _sanitize_scp_id  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="list the divergences; write nothing (default)")
    mode.add_argument("--commit", action="store_true", help="retire the listed manifest entries")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    with Session(db._engine) as session:
        assets = AssetService(settings.assets_path, session)
        manifest = assets.load_manifest()
        entries = {k: v for k, v in manifest["assets"].items() if "card_key" in v}
        rows = list(session.exec(select(CharacterCard)))

        forward: list[str] = []
        reverse: list[str] = []
        for card in sorted(rows, key=lambda c: (c.scp_id, c.pose, c.angle)):
            # `_sanitize_scp_id`, not the raw `scp_id`: manifest keys are written from the
            # sanitized form (`character_service`, `approve_stock_cast`) while the row
            # keeps the raw one. They are identical for every key live today, so the raw
            # form "worked" — but a key that ever needed sanitizing would print as "no
            # manifest entry" and, being `continue`d, would skip the reverse-direction
            # HALT check entirely. A mismatch that turns a HALT into a printed line is
            # not a cosmetic mismatch.
            key = f"{_sanitize_scp_id(card.scp_id)}/{card.pose}_{card.angle}"
            entry = entries.get(key)
            if entry is None:
                # Printed, never skipped silently: a card row with no manifest entry has
                # no provenance and no sha256, so `verify_asset` can never speak for it.
                print(f"no manifest entry: {key} (row status {card.status})")
                continue
            if entry["status"] == "approved" and card.status == "retired":
                forward.append(key)
            elif entry["status"] == "retired" and card.status == "approved":
                reverse.append(key)

        if reverse:
            print(f"HALT: {len(reverse)} entry(ies) retired in the manifest but approved in the DB —")
            print("      approval-direction drift is not this script's call.")
            for key in reverse:
                print(f"  {key}")
            return 1

        print(f"manifest `approved` / db `retired`: {len(forward)}")
        for key in forward:
            print(f"  {key}  ({entries[key]['path']})")
        if not args.commit:
            print("dry run — manifest not written. Re-run with --commit to retire these entries.")
            return 0
        for key in forward:
            assets.retire_asset(key)
            print(f"retired: {key}")
        print(f"wrote {assets._manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
