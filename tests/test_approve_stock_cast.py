"""Tests for scripts/approve_stock_cast.py (Story 8.15).

This script is the only thing in the repo that can destroy live card assets: it
repoints ``Character.angle_*_path`` — a bare column read at runtime — and bumps the
global ``style_epoch``, which is what decides where the *next* ``--stage`` run writes.
So every refusal path is asserted to leave live state untouched, not merely to exit
non-zero. Uses a tmp DB + tmp assets root via env overrides; never the repo's own.
"""

import importlib.util
import struct
import zlib

from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.domain.state import STOCK_CAST_KEYS
from yt_flow.services.character_service import CANONICAL_ANGLES, CharacterService
from tests.stubs.fakes import TINY_PNG


def _load_script():
    spec = importlib.util.spec_from_file_location("approve_stock_cast", "scripts/approve_stock_cast.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _rgb_png() -> bytes:
    """A valid 1x1 PNG with color_type=2 — no alpha channel, so it must be refused."""
    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00"))
        + chunk(b"IEND", b"")
    )


def _live_path(key: str, angle: str) -> str:
    return f"characters/{key}/epoch_1/{angle}_candidate_1.png"


def _staged_rel(key: str, angle: str) -> str:
    return f"characters/{key}/epoch_2/{angle}_candidate_1.png"


def _setup(tmp_path, monkeypatch, keys=STOCK_CAST_KEYS, descriptor="live descriptor"):
    """Point Settings at a tmp DB + tmp assets root and seed a complete live epoch_1."""
    assets = tmp_path / "assets"
    monkeypatch.setenv("YTFLOW_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(assets))
    db.init(f"sqlite:///{tmp_path / 'test.db'}")
    settings = Settings(workspace_path=str(tmp_path / "workspace"), assets_path=str(assets))
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        for key in keys:
            character = service.create_character(key, key)
            live = {f"angle_{angle}_path": _live_path(key, angle) for angle in CANONICAL_ANGLES}
            for rel in live.values():
                (assets / rel).parent.mkdir(parents=True, exist_ok=True)
                (assets / rel).write_bytes(TINY_PNG)
            service.update_character(
                character.id,
                visual_descriptor=descriptor,
                selected_image_path=_live_path(key, "front"),
                **live,
            )
    return assets


def _stage(assets, key, *, angles=CANONICAL_ANGLES, payload=TINY_PNG, prestage=None):
    directory = assets / "characters" / key / "epoch_2"
    directory.mkdir(parents=True, exist_ok=True)
    for angle in angles:
        (directory / f"{angle}_candidate_1.png").write_bytes(payload)
    if prestage is not None:
        (directory / "_prestage_descriptor.txt").write_text(prestage, encoding="utf-8")
    return directory


def _characters(assets, tmp_path):
    settings = Settings(workspace_path=str(tmp_path / "workspace"), assets_path=str(assets))
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        return {key: service.check_existing_character(key) for key in STOCK_CAST_KEYS}


def _asset_service(assets, tmp_path):
    settings = Settings(workspace_path=str(tmp_path / "workspace"), assets_path=str(assets))
    with Session(db._engine) as session:
        return CharacterService(session, settings=settings)._asset_service


def _assert_live_untouched(assets, tmp_path):
    for key, character in _characters(assets, tmp_path).items():
        for angle in CANONICAL_ANGLES:
            assert getattr(character, f"angle_{angle}_path") == _live_path(key, angle)
        assert character.selected_image_path == _live_path(key, "front")
    asset_service = _asset_service(assets, tmp_path)
    assert asset_service.style_epoch == 1
    assert asset_service.load_manifest()["assets"] == {}


def test_promote_repoints_every_angle_and_approves_the_manifest(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    for key in STOCK_CAST_KEYS:
        _stage(assets, key, prestage="live descriptor")

    assert approve.run(list(STOCK_CAST_KEYS), reject=False) == 0

    for key, character in _characters(assets, tmp_path).items():
        for angle in CANONICAL_ANGLES:
            assert getattr(character, f"angle_{angle}_path") == _staged_rel(key, angle)
        assert character.selected_image_path == _staged_rel(key, "front")
    asset_service = _asset_service(assets, tmp_path)
    manifest = asset_service.load_manifest()["assets"]
    for key in STOCK_CAST_KEYS:
        for angle in CANONICAL_ANGLES:
            entry = manifest[f"{key}/standing_{angle}"]
            assert entry["status"] == "approved"
            assert entry["path"] == _staged_rel(key, angle)
    # The bump retires epoch_2 as a staging target so the next --stage cannot
    # regenerate over the files just promoted.
    assert asset_service.style_epoch == 2
    # The sidecar exists only to undo a rejection; promotion consumes it.
    assert not (assets / "characters" / STOCK_CAST_KEYS[0] / "epoch_2" / "_prestage_descriptor.txt").exists()


def test_missing_staged_card_refuses_and_leaves_live_state_untouched(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    for key in STOCK_CAST_KEYS:
        _stage(assets, key)
    (assets / "characters" / STOCK_CAST_KEYS[-1] / "epoch_2" / "back_candidate_1.png").unlink()

    assert approve.run(list(STOCK_CAST_KEYS), reject=False) == 1
    _assert_live_untouched(assets, tmp_path)


def test_alpha_less_staged_card_refuses(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    for key in STOCK_CAST_KEYS:
        _stage(assets, key)
    _stage(assets, STOCK_CAST_KEYS[-1], angles=["side"], payload=_rgb_png())

    assert approve.run(list(STOCK_CAST_KEYS), reject=False) == 1
    _assert_live_untouched(assets, tmp_path)


def test_reject_deletes_the_staged_dir_and_restores_the_descriptor(tmp_path, monkeypatch):
    """Staging overwrites visual_descriptor, which runtime reads — leaving the STOCK
    text behind would describe cards that no longer exist."""
    assets = _setup(tmp_path, monkeypatch, descriptor="staged STOCK descriptor")
    approve = _load_script()
    for key in STOCK_CAST_KEYS:
        _stage(assets, key, prestage="original poisoned descriptor")

    assert approve.run(list(STOCK_CAST_KEYS), reject=True) == 0

    for key, character in _characters(assets, tmp_path).items():
        assert not (assets / "characters" / key / "epoch_2").exists()
        assert character.visual_descriptor == "original poisoned descriptor"
    _assert_live_untouched(assets, tmp_path)


def test_reject_without_a_sidecar_clears_the_descriptor(tmp_path, monkeypatch):
    """Absent sidecar means there was no descriptor before staging."""
    assets = _setup(tmp_path, monkeypatch, descriptor="staged STOCK descriptor")
    approve = _load_script()
    _stage(assets, STOCK_CAST_KEYS[0])

    assert approve.run([STOCK_CAST_KEYS[0]], reject=True) == 0
    assert _characters(assets, tmp_path)[STOCK_CAST_KEYS[0]].visual_descriptor is None


def test_reject_with_nothing_staged_exits_non_zero(tmp_path, monkeypatch):
    """After a promotion `epoch` points past the retired staging epoch, so a mistaken
    --reject finds nothing — exiting 0 would read as a successful undo."""
    approve = _load_script()
    _setup(tmp_path, monkeypatch)

    assert approve.run(list(STOCK_CAST_KEYS), reject=True) == 1


def test_a_key_without_a_character_row_blocks_the_whole_promotion(tmp_path, monkeypatch):
    """The row check has to run before the first mutation: promoting the earlier keys
    and then returning short of bump_style_epoch() leaves style_epoch at 1, so the next
    --stage regenerates directly over the files just promoted."""
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch, keys=STOCK_CAST_KEYS[:-1])
    for key in STOCK_CAST_KEYS:
        _stage(assets, key)

    assert approve.run(list(STOCK_CAST_KEYS), reject=False) == 1

    asset_service = _asset_service(assets, tmp_path)
    assert asset_service.style_epoch == 1
    assert asset_service.load_manifest()["assets"] == {}
    for key, character in _characters(assets, tmp_path).items():
        if character is None:
            continue
        assert character.angle_front_path == _live_path(key, "front")


def test_single_key_promotion_refused_while_a_sibling_is_staged(tmp_path, monkeypatch):
    """The closing bump retires epoch_2, orphaning any sibling left staged in what is
    now a live epoch directory."""
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    for key in STOCK_CAST_KEYS:
        _stage(assets, key)

    assert approve.run([STOCK_CAST_KEYS[0]], reject=False) == 1
    _assert_live_untouched(assets, tmp_path)


def test_single_key_promotion_allowed_when_no_sibling_is_staged(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    _stage(assets, STOCK_CAST_KEYS[0])

    assert approve.run([STOCK_CAST_KEYS[0]], reject=False) == 0
    assert _characters(assets, tmp_path)[STOCK_CAST_KEYS[0]].angle_front_path == _staged_rel(
        STOCK_CAST_KEYS[0], "front"
    )
