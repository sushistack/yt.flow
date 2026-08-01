"""Promote staged STOCK character cards to live, or reject them (Story 8.15).

``seed_stock_cast.py --stage`` writes a replacement card set into the *next* style
epoch and nothing else — no manifest entry, no approval, no ``angle_*_path``
repoint. This script is the only thing that makes those files live.

Promote every staged key in one invocation: the closing ``bump_style_epoch()``
retires the staged epoch as a staging target, so a sibling key left staged would
have to be re-staged afterwards. ``--key`` is refused while a sibling is staged.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from seed_stock_cast import PRESTAGE_DESCRIPTOR_FILE, staged_dir  # noqa: E402
from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.db.models import CharacterCard  # noqa: E402
from yt_flow.domain.png import has_alpha  # noqa: E402
from yt_flow.domain.state import STOCK_CAST_KEYS  # noqa: E402
from yt_flow.services.character_service import CANONICAL_ANGLES, CharacterService, _sanitize_scp_id  # noqa: E402


def _staged_paths(assets_root: Path, key: str, epoch: int) -> dict[str, str]:
    """Return ``{angle: path relative to assets_root}`` for a key's staged set.

    Cards are addressed by exact filename, never globbed — that is what keeps
    ``PRESTAGE_DESCRIPTOR_FILE`` in the same directory from being taken for one.
    """
    rel_dir = staged_dir(assets_root, key, epoch).relative_to(assets_root)
    return {angle: str(rel_dir / f"{angle}_candidate_1.png") for angle in CANONICAL_ANGLES}


def _reject(assets_root: Path, key: str, epoch: int, service: CharacterService) -> bool:
    """Delete a staged set and undo the one live write staging makes. False if nothing staged."""
    directory = staged_dir(assets_root, key, epoch)
    if not directory.exists():
        print(f"nothing staged: {key}")
        return False
    sidecar = directory / PRESTAGE_DESCRIPTOR_FILE
    character = service.check_existing_character(key)
    if character is not None:
        previous = sidecar.read_text(encoding="utf-8") if sidecar.is_file() else None
        if character.visual_descriptor != previous:
            service.update_character(character.id, visual_descriptor=previous)
            print(f"restored pre-stage descriptor: {key}")
    shutil.rmtree(directory)
    print(f"rejected: {key} ({directory})")
    return True


def _retire_special_pose_cards(session, service: CharacterService, key: str) -> None:
    """Retire ``hint:*`` cards derived from the superseded front card.

    ``get_card`` only returns approved rows, so retiring them makes 8.4's
    on-demand path regenerate them from the promoted front on the next run.
    """
    safe_key = _sanitize_scp_id(key)
    cards = session.exec(select(CharacterCard).where(CharacterCard.scp_id == key)).all()
    for card in cards:
        if not card.pose.startswith("hint:"):
            continue
        card.status = "retired"
        session.add(card)
        try:
            service._asset_service.retire_asset(f"{safe_key}/{card.pose}_{card.angle}")
        except (ValueError, OSError) as exc:  # noqa: PERF203 - retire is best-effort
            print(f"warning: could not retire manifest entry for {card.pose}: {exc}")
        print(f"retired: {key} {card.pose}")
    session.commit()


def run(keys: list[str], reject: bool) -> int:
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    assets_root = Path(settings.assets_path)
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        asset_service = service._asset_service
        epoch = asset_service.style_epoch + 1

        if reject:
            rejected = [key for key in keys if _reject(assets_root, key, epoch, service)]
            # Nothing to undo is a failure, not a silent success: after a promotion
            # `epoch` is one past the retired staging epoch, so every key reads as
            # "nothing staged" and a mistaken --reject would look like it worked.
            return 0 if rejected else 1

        # Verify every precondition up front. Promotion mutates per key, so a check
        # inside the loop would leave earlier keys live *and* return before
        # bump_style_epoch() — the next --stage would then compute the same epoch and
        # regenerate straight over the just-promoted files.
        staged = {key: _staged_paths(assets_root, key, epoch) for key in keys}
        characters = {}
        for key, angle_paths in staged.items():
            character = service.check_existing_character(key)
            if character is None:
                print(f"no character row: {key}")
                return 1
            characters[key] = character
            for angle, rel_path in angle_paths.items():
                abs_path = assets_root / rel_path
                if not abs_path.is_file():
                    print(f"no staged card: {key} {angle} ({abs_path})")
                    return 1
                if not has_alpha(abs_path.read_bytes()):
                    print(f"staged card has no alpha channel: {key} {angle} ({abs_path})")
                    return 1

        # The closing bump retires epoch_{epoch} as a staging target, so a sibling left
        # staged would be orphaned in what is now a live epoch directory.
        orphans = [
            key for key in STOCK_CAST_KEYS
            if key not in staged and staged_dir(assets_root, key, epoch).exists()
        ]
        if orphans:
            print(f"refusing partial promotion: still staged in epoch_{epoch}: {', '.join(orphans)}")
            return 1

        for key, angle_paths in staged.items():
            safe_key = _sanitize_scp_id(key)
            for angle, rel_path in angle_paths.items():
                asset_service.add_asset(
                    f"{safe_key}/standing_{angle}", rel_path,
                    source={"type": "comfyui_generation", "story": "8.15"},
                    card_key=safe_key, pose="standing", angle=angle,
                )
                asset_service.approve_asset(f"{safe_key}/standing_{angle}")
            service.update_character(
                characters[key].id,
                selected_image_path=angle_paths["front"],
                **{f"angle_{angle}_path": path for angle, path in angle_paths.items()},
            )
            (staged_dir(assets_root, key, epoch) / PRESTAGE_DESCRIPTOR_FILE).unlink(missing_ok=True)
            print(f"promoted: {key} → epoch_{epoch}")
            _retire_special_pose_cards(session, service, key)

        print(f"style_epoch → {asset_service.bump_style_epoch()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Promote or reject staged STOCK character cards.")
    parser.add_argument("--key", choices=STOCK_CAST_KEYS, help="One stock key instead of all three.")
    parser.add_argument("--reject", action="store_true", help="Delete the staged cards; touch nothing live.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return run([args.key] if args.key else list(STOCK_CAST_KEYS), args.reject)


if __name__ == "__main__":
    raise SystemExit(main())
