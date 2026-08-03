"""Depth-only backfill for the approved stock location plates (Story 11.5 AC1).

Story 8.17 produced and Jay approved 42 RGB plates. Story 8.16 then computed
depth maps for them, but keyed the cache on the plate's bytes ALONE and ran
``depth_anything_v2_vitl.pth`` — Large, CC-BY-NC-4.0. Story 11.5 AC3 moves the
default to the Apache-2.0 Small checkpoint and folds the estimator contract into
the cache key, which correctly invalidates every Large-model map. This script
recomputes them.

Non-destructive by construction, not by care:

* it only ever calls :func:`compositing_service.depth_map_file`, which writes to
  the content-addressed depth cache under ``workspace/cache/depth/``;
* it never opens an approved plate for writing, never touches a ``LocationPlate``
  row, its ``status``, or the asset manifest;
* a failure on one plate is logged and the next plate is attempted (8.17's
  per-item isolation precedent);
* re-running it is free: a valid image/depth pair is a verified cache hit and
  costs zero inference, so an interrupted run resumes where it stopped.

Usage::

    uv run python scripts/backfill_location_depth_maps.py            # approved plates
    uv run python scripts/backfill_location_depth_maps.py --all      # incl. drafts
    uv run python scripts/backfill_location_depth_maps.py --dry-run
"""

import argparse
import asyncio
import hashlib
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlmodel import Session  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.services import compositing_service  # noqa: E402
from yt_flow.services.location_service import LocationService  # noqa: E402

logger = logging.getLogger("backfill_depth")


async def backfill(settings: Settings, *, status: str | None, dry_run: bool) -> int:
    contract = compositing_service.depth_contract(settings)  # raises on a refused ckpt
    logger.info(
        "depth contract: %s @ res %s (%s)",
        contract["model_ckpt"], contract["resolution"], contract["model_license"],
    )
    db.init(f"sqlite:///{settings.db_path}")
    with Session(db._engine) as session:
        plates = LocationService(session, settings=settings).list_plates(status=status)
        # Read every field we need while the session is open — a detached row
        # raises DetachedInstanceError on later attribute access (Story 1.13).
        items = [(p.location_key, p.variant, p.image_path) for p in plates]

    assets = Path(settings.assets_path)
    hits = made = failed = missing = 0
    for key, variant, rel in items:
        plate = assets / rel
        if not plate.is_file():
            logger.warning("%s/%s: plate file missing at %s", key, variant, plate)
            missing += 1
            continue
        source_sha = hashlib.sha256(plate.read_bytes()).hexdigest()
        cache = compositing_service.depth_map_cache_path(plate, settings)
        if compositing_service.verify_depth_pair(cache, source_sha, contract):
            hits += 1
            continue
        if dry_run:
            logger.info("%s/%s: WOULD estimate -> %s", key, variant, cache.name)
            made += 1
            continue
        try:
            result = await compositing_service.depth_map_file(plate, settings)
        except Exception as exc:  # noqa: BLE001 — per-item isolation (8.17 precedent)
            logger.warning("%s/%s: depth estimation raised: %s", key, variant, exc)
            result = None
        if result is None or not compositing_service.verify_depth_pair(
            cache, source_sha, contract
        ):
            logger.warning("%s/%s: depth estimation FAILED", key, variant)
            failed += 1
            continue
        logger.info("%s/%s: depth map written -> %s", key, variant, result.name)
        made += 1

    logger.info(
        "backfill done: %d plate(s) — %d cache hit, %d %s, %d failed, %d missing file",
        len(items), hits, made, "would estimate" if dry_run else "estimated", failed, missing,
    )
    # Non-zero only when work was attempted and lost, so a fully cached re-run
    # and a dry run both exit clean.
    return 1 if failed or missing else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="include draft/rejected plates")
    ap.add_argument("--dry-run", action="store_true", help="report work, estimate nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return asyncio.run(
        backfill(Settings(), status=None if args.all else "approved", dry_run=args.dry_run)
    )


if __name__ == "__main__":
    raise SystemExit(main())
