"""Seed stock and derived character card sprites (Story 8.2)."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.png import has_alpha  # noqa: E402
from yt_flow.domain.state import STOCK_CAST_KEYS  # noqa: E402
from yt_flow.services.character_service import CharacterService, _sanitize_scp_id  # noqa: E402
from yt_flow.services.image_search import DuckDuckGoImageSearch  # noqa: E402


STOCK_DESCRIPTORS = {
    "STOCK-d-class": (
        "SCP Foundation D-class personnel, gaunt build, orange prison jumpsuit "
        "with a stenciled number, worn work boots, anxious posture"
    ),
    "STOCK-researcher": (
        "SCP Foundation researcher or doctor, white lab coat over shirt and tie, "
        "ID badge, practical shoes, clinical professional posture"
    ),
    "STOCK-security": (
        "SCP Foundation security guard, black tactical gear, vest with Foundation "
        "insignia, helmet or cap, alert disciplined posture"
    ),
}
VALID_POSES = ("standing", "sitting")


def _is_alpha_png_file(path: str | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).is_file() and has_alpha(Path(path).read_bytes())
    except OSError:
        return False


def _all_standing_paths_ready(character) -> bool:
    return all(
        _is_alpha_png_file(getattr(character, f"angle_{angle}_path"))
        for angle in ("front", "back", "side", "three_quarter")
    )


def _pose_complete(service: CharacterService, key: str, pose: str) -> bool:
    if pose == "standing":
        character = service.check_existing_character(key)
        return character is not None and _all_standing_paths_ready(character)
    return all(
        (card := service.get_card(key, pose, angle)) is not None and _is_alpha_png_file(card.image_path)
        for angle in ("front", "back", "side", "three_quarter")
    )


async def _anchor_search(service: CharacterService, key: str, descriptor: str, settings: Settings) -> int:
    query = descriptor.split(",")[0]
    results = await DuckDuckGoImageSearch().search(query=query, max_results=5)
    review_dir = Path(settings.workspace_path) / "anchor-search" / _sanitize_scp_id(key)
    review_dir.mkdir(parents=True, exist_ok=True)
    for idx, result in enumerate(results, start=1):
        try:
            ext = await service._download_reference_image(result["url"], review_dir, idx)
            print(f"downloaded: {review_dir / f'ref_{idx}.{ext}'}")
        except Exception as exc:  # noqa: BLE001 - best-effort curation aid
            print(f"skipped: {result['url']} ({exc})")
    print(f"Review {review_dir}, then rerun with --anchor <path>.")
    return 0


async def seed_key(
    service: CharacterService,
    key: str,
    descriptor: str,
    *,
    pose: str = "standing",
    force: bool = False,
    anchor: str | None = None,
) -> list[str]:
    if pose not in VALID_POSES:
        raise ValueError(f"pose must be one of {VALID_POSES}")
    if not force and _pose_complete(service, key, pose):
        print(f"skipped: {key} ({pose})")
        return []
    paths = await service.generate_cards_from_descriptor(
        key,
        descriptor=descriptor,
        pose=pose,
        anchor_path=anchor,
    )
    print(f"generated: {key} ({pose}) {len(paths)} cards")
    return paths


async def run(args) -> int:
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        if args.key:
            if not args.descriptor:
                raise SystemExit("--descriptor is required with --key")
            targets = {args.key: args.descriptor}
        else:
            targets = {key: STOCK_DESCRIPTORS[key] for key in STOCK_CAST_KEYS}
            if args.anchor:
                raise SystemExit("--anchor requires --key so one curated image is not reused for every stock cast member")

        if args.anchor_search:
            for key, descriptor in targets.items():
                await _anchor_search(service, key, descriptor, settings)
            return 0

        for key, descriptor in targets.items():
            await seed_key(
                service,
                key,
                descriptor,
                pose=args.pose,
                force=args.force,
                anchor=args.anchor,
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed stock/derived character card sprites.")
    parser.add_argument("--key", help="Seed one derived or stock key instead of all stock keys.")
    parser.add_argument("--descriptor", help="Descriptor for --key derived card generation.")
    parser.add_argument("--pose", default="standing", choices=VALID_POSES, help="Pose key to generate (default: standing).")
    parser.add_argument("--force", action="store_true", help="Regenerate even if cards already exist.")
    parser.add_argument("--anchor", help="Optional curated front-angle anchor image path.")
    parser.add_argument("--anchor-search", action="store_true", help="Download candidate anchors and stop.")
    return parser


def main(argv=None) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
