"""Approve draft location plates for pipeline consumption (Story 8.5, bulk in 8.17).

Only status="approved" plates are visible to image_node's STOCK fast path
(LocationService.get_approved_plate), so approving *is* publishing.

With no arguments this prints the operator queue — every plate the auto-labeler
(scripts/label_location_plates.py) left as draft — and approves nothing. Bulk
approval is explicit: ``--key`` without ``--variant`` for one location, ``--all``
for the whole queue.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.state import LOCATION_KEYS  # noqa: E402
from yt_flow.services.location_service import LocationService  # noqa: E402

VARIANTS = ("a", "b", "c")


def _print_queue(service: LocationService) -> int:
    """List what is still draft. Non-zero when there are no plates at all."""
    plates = service.list_plates()
    if not plates:
        print("no location plates — run scripts/seed_location_plates.py first")
        return 1
    counts = Counter(plate.status for plate in plates)
    print("plates: " + ", ".join(f"{status}={count}" for status, count in sorted(counts.items())))
    drafts = [plate for plate in plates if plate.status == "draft"]
    for plate in drafts:
        print(f"draft: {plate.location_key} {plate.variant} ({plate.image_path})")
    if not drafts:
        print("operator queue is empty")
    return 0


def run(key: str | None, variant: str | None, approve_all: bool) -> int:
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    with Session(db._engine) as session:
        service = LocationService(session, settings=settings)
        if not (key or approve_all):
            return _print_queue(service)

        targets = [p for p in service.list_plates(location_key=key) if variant in (None, p.variant)]
        if not targets:
            print(f"no plate found for {key or 'any key'}" + (f" variant {variant}" if variant else ""))
            return 1
        pending = [p for p in targets if p.status != "approved"]
        if not pending:
            print(f"already approved: {len(targets)} plate(s), nothing to do")
            return 0

        failed = 0
        for plate in pending:
            before = plate.status
            try:
                approved = service.approve_plate(plate.id)
            except (LookupError, ValueError) as exc:  # missing row, or unknown/retired manifest entry
                print(f"failed ({exc}): {plate.location_key} {plate.variant}")
                failed += 1
                continue
            print(f"approved: {plate.location_key} {plate.variant} ({before} -> {approved.status})")
        print(f"done: {len(pending) - failed} approved, {failed} failed")
    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Approve draft location plates, or list the operator queue when given no arguments.",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--key", choices=LOCATION_KEYS, help="Approve this location key's plates.")
    target.add_argument("--all", action="store_true", dest="approve_all", help="Approve every draft plate.")
    parser.add_argument("--variant", choices=VARIANTS, help="With --key, approve only this variant.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.variant and not args.key:
        sys.exit("--variant needs --key (a variant letter alone matches all 14 locations)")
    return run(args.key, args.variant, args.approve_all)


if __name__ == "__main__":
    raise SystemExit(main())
