"""Approve a draft location plate for pipeline consumption (Story 8.5).

Thin CLI — argparse + LocationService call only. Only status="approved"
plates are visible to image_node's STOCK fast path (LocationService.get_approved_plate).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.state import LOCATION_KEYS  # noqa: E402
from yt_flow.services.location_service import LocationService  # noqa: E402


def run(key: str, variant: str) -> int:
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    with Session(db._engine) as session:
        service = LocationService(session, settings=settings)
        matches = [p for p in service.list_plates(location_key=key) if p.variant == variant]
        if not matches:
            print(f"no plate found for {key} variant {variant}")
            return 1
        plate = matches[0]
        print(f"before: {key} {variant} status={plate.status}")
        approved = service.approve_plate(plate.id)
        print(f"after: {key} {variant} status={approved.status}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Approve a draft location plate.")
    parser.add_argument("--key", required=True, choices=LOCATION_KEYS)
    parser.add_argument("--variant", required=True, choices=("a", "b", "c"))
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return run(args.key, args.variant)


if __name__ == "__main__":
    raise SystemExit(main())
