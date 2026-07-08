"""One-shot migration: move 8.2-generated character cards from workspace/ to assets/ (Story 8.6).

Idempotent — safe to re-run; already-migrated assets are skipped.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.db import _ensure_card_columns  # noqa: E402, F401 (re-exported for tests; db.init() already runs it)
from yt_flow.db.models import Character, CharacterCard  # noqa: E402
from yt_flow.services.asset_service import AssetService  # noqa: E402

_STANDING_RE = re.compile(r"^(front|back|side|three_quarter)_candidate_1\.png$")
_HINT_RE = re.compile(r"^hint_([0-9a-f]+)_front\.png$")
_POSE_RE = re.compile(r"^(.+)_(front|back|side|three_quarter)\.png$")

_ANGLE_FIELD = {
    "front": "angle_front_path",
    "back": "angle_back_path",
    "side": "angle_side_path",
    "three_quarter": "angle_three_quarter_path",
}


def migrate(workspace_path: Path, assets_path: Path, session: Session) -> tuple[int, int, int]:
    """Copy 8.2 card PNGs from ``workspace/*/characters/`` into the asset library.

    Returns ``(migrated, skipped, errors)``.
    """
    asset_service = AssetService(assets_path, session)
    epoch = asset_service.style_epoch
    migrated = skipped = errors = 0

    for chars_dir in sorted(workspace_path.glob("*/characters")):
        card_key = chars_dir.parent.name
        dest_dir = assets_path / "characters" / card_key / f"epoch_{epoch}"

        for png in sorted(chars_dir.glob("*.png")):
            m_standing = _STANDING_RE.match(png.name)
            m_hint = _HINT_RE.match(png.name)
            m_pose = _POSE_RE.match(png.name)
            if m_standing:
                pose, angle = "standing", m_standing.group(1)
            elif m_hint:
                # pose_hint_key() produces "hint:<sha256[:10]>"; the on-disk filename
                # replaces the colon with "_" (character_service.generate_special_pose_card).
                pose, angle = f"hint:{m_hint.group(1)}", "front"
            elif m_pose:
                pose, angle = m_pose.groups()
            else:
                continue

            key = f"{card_key}/{pose}_{angle}"
            dest = dest_dir / png.name
            rel_path = str(dest.relative_to(assets_path))

            if asset_service.get_asset(key, include_drafts=True) is not None and dest.exists():
                skipped += 1
                continue

            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(png.read_bytes())
                asset_service.add_asset(
                    key, rel_path, source={"type": "comfyui_generation"},
                    card_key=card_key, pose=pose, angle=angle,
                )
                # Already through 8-2's human QA to be live in workspace/ — approve on sight.
                asset_service.approve_asset(key)

                if pose == "standing":
                    character = session.exec(select(Character).where(Character.scp_id == card_key)).first()
                    if character is not None:
                        setattr(character, _ANGLE_FIELD[angle], rel_path)
                        if angle == "front":
                            character.selected_image_path = rel_path
                        session.add(character)
                        session.commit()
                else:
                    card = session.exec(
                        select(CharacterCard).where(
                            CharacterCard.scp_id == card_key,
                            CharacterCard.pose == pose,
                            CharacterCard.angle == angle,
                        )
                    ).first()
                    if card is not None:
                        card.image_path = rel_path
                        card.status = "approved"
                        card.style_epoch = epoch
                        session.add(card)
                        session.commit()
                migrated += 1
            except OSError:
                errors += 1

    return migrated, skipped, errors


def main() -> int:
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    _ensure_card_columns(db._engine)
    with Session(db._engine) as session:
        migrated, skipped, errors = migrate(
            Path(settings.workspace_path), Path(settings.assets_path), session,
        )
    print(f"migrate_assets: migrated={migrated} skipped={skipped} errors={errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
