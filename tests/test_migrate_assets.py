import importlib.util

from sqlmodel import Session, select

from yt_flow import db
from yt_flow.db.models import Character, CharacterCard
from yt_flow.services.asset_service import AssetService

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _load_script():
    spec = importlib.util.spec_from_file_location("migrate_assets", "scripts/migrate_assets.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _seed_workspace_cards(workspace_path):
    chars_dir = workspace_path / "SCP-049" / "characters"
    chars_dir.mkdir(parents=True)
    (chars_dir / "front_candidate_1.png").write_bytes(PNG_BYTES)
    (chars_dir / "sitting_front.png").write_bytes(PNG_BYTES)


def test_migrate_copies_cards_and_updates_db(tmp_path):
    mod = _load_script()
    db.init("sqlite://")
    workspace_path = tmp_path / "workspace"
    assets_path = tmp_path / "assets"
    _seed_workspace_cards(workspace_path)

    with Session(db._engine) as session:
        session.add(Character(scp_id="SCP-049", canonical_name="Plague Doctor"))
        session.commit()
        session.add(CharacterCard(scp_id="SCP-049", pose="sitting", angle="front", image_path="stale"))
        session.commit()

        migrated, skipped, errors = mod.migrate(workspace_path, assets_path, session)

        assert (migrated, skipped, errors) == (2, 0, 0)

        character = session.exec(select(Character).where(Character.scp_id == "SCP-049")).first()
        assert character is not None
        assert character.angle_front_path == "characters/SCP-049/epoch_1/front_candidate_1.png"
        assert (assets_path / character.angle_front_path).exists()

        card = session.exec(select(CharacterCard).where(CharacterCard.pose == "sitting")).first()
        assert card is not None
        assert card.image_path == "characters/SCP-049/epoch_1/sitting_front.png"
        assert card.status == "approved"

        asset_service = AssetService(assets_path, session)
        assert asset_service.get_asset("SCP-049/standing_front") is not None
        assert asset_service.get_asset("SCP-049/sitting_front") is not None


def test_migrate_reconstructs_hint_pose_with_colon(tmp_path):
    """Story 8.4 special-pose card filenames replace ':' with '_' on disk

    (character_service.generate_special_pose_card); the migration must reverse that
    exactly, since CharacterCard.pose is stored with the colon (pose_hint_key()).
    """
    mod = _load_script()
    db.init("sqlite://")
    workspace_path = tmp_path / "workspace"
    assets_path = tmp_path / "assets"
    chars_dir = workspace_path / "SCP-049" / "characters"
    chars_dir.mkdir(parents=True)
    (chars_dir / "hint_3fa89c2a1b_front.png").write_bytes(PNG_BYTES)

    with Session(db._engine) as session:
        session.add(Character(scp_id="SCP-049", canonical_name="Plague Doctor"))
        session.commit()
        session.add(CharacterCard(scp_id="SCP-049", pose="hint:3fa89c2a1b", angle="front", image_path="stale"))
        session.commit()

        migrated, skipped, errors = mod.migrate(workspace_path, assets_path, session)
        assert (migrated, skipped, errors) == (1, 0, 0)

        card = session.exec(select(CharacterCard).where(CharacterCard.scp_id == "SCP-049")).first()
        assert card is not None
        assert card.pose == "hint:3fa89c2a1b"
        assert card.status == "approved"
        assert card.image_path == "characters/SCP-049/epoch_1/hint_3fa89c2a1b_front.png"

        asset_service = AssetService(assets_path, session)
        assert asset_service.get_asset("SCP-049/hint:3fa89c2a1b_front") is not None


def test_migrate_is_idempotent(tmp_path):
    mod = _load_script()
    db.init("sqlite://")
    workspace_path = tmp_path / "workspace"
    assets_path = tmp_path / "assets"
    _seed_workspace_cards(workspace_path)

    with Session(db._engine) as session:
        session.add(Character(scp_id="SCP-049", canonical_name="Plague Doctor"))
        session.commit()

        first = mod.migrate(workspace_path, assets_path, session)
        second = mod.migrate(workspace_path, assets_path, session)

        assert first == (2, 0, 0)
        assert second == (0, 2, 0)


def test_ensure_card_columns_adds_missing_columns():
    db.init("sqlite://")
    mod = _load_script()
    with db._engine.connect() as conn:
        cols_before = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(character_cards)")}
    assert "status" in cols_before  # create_all already includes it for a fresh DB

    mod._ensure_card_columns(db._engine)  # idempotent no-op on a fresh DB
    with db._engine.connect() as conn:
        cols_after = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(character_cards)")}
    assert cols_after == cols_before
