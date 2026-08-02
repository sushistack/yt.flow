"""Tests for scripts/approve_location_plate.py (Story 8.5 single, Story 8.17 bulk).

Approving a plate *is* publishing it — image_node's fast path consumes approved plates
verbatim — so the no-argument default is asserted to approve nothing.
"""

import io
import json

import pytest
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.services.asset_service import AssetService
from yt_flow.services.location_service import LocationService

import importlib.util


def _load_script():
    spec = importlib.util.spec_from_file_location("approve_location_plate", "scripts/approve_location_plate.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), (32, 34, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _env(tmp_path, monkeypatch, plates=(("corridor", "a"), ("corridor", "b"), ("office", "a"))):
    assets = tmp_path / "assets"
    monkeypatch.setenv("YTFLOW_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(assets))
    db.init(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(db._engine) as session:
        asset_service = AssetService(assets, session)
        for location_key, variant in plates:
            rel = f"locations/{location_key}/{variant}.png"
            (assets / rel).parent.mkdir(parents=True, exist_ok=True)
            (assets / rel).write_bytes(_png())
            asset_service.add_location_plate(location_key, variant, rel)
    return assets


def _statuses(assets) -> dict[str, str]:
    settings = Settings(assets_path=str(assets))
    with Session(db._engine) as session:
        return {
            f"{p.location_key}/{p.variant}": p.status
            for p in LocationService(session, settings=settings).list_plates()
        }


def test_no_arguments_lists_the_queue_and_approves_nothing(tmp_path, monkeypatch, capsys):
    approve = _load_script()
    assets = _env(tmp_path, monkeypatch)

    assert approve.main([]) == 0

    out = capsys.readouterr().out
    assert "plates: draft=3" in out
    assert "draft: corridor a" in out and "draft: office a" in out
    assert set(_statuses(assets).values()) == {"draft"}


def test_key_without_variant_approves_that_location_only(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _env(tmp_path, monkeypatch)

    assert approve.main(["--key", "corridor"]) == 0

    assert _statuses(assets) == {"corridor/a": "approved", "corridor/b": "approved", "office/a": "draft"}


def test_key_with_variant_approves_one_plate(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _env(tmp_path, monkeypatch)

    assert approve.main(["--key", "corridor", "--variant", "b"]) == 0

    assert _statuses(assets) == {"corridor/a": "draft", "corridor/b": "approved", "office/a": "draft"}


def test_all_approves_the_whole_queue_and_the_manifest_follows(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _env(tmp_path, monkeypatch)

    assert approve.main(["--all"]) == 0

    assert set(_statuses(assets).values()) == {"approved"}
    manifest = json.loads((assets / "manifest.json").read_text())["assets"]
    assert {entry["status"] for entry in manifest.values()} == {"approved"}


def test_a_second_all_is_a_no_op(tmp_path, monkeypatch, capsys):
    approve = _load_script()
    assets = _env(tmp_path, monkeypatch)
    assert approve.main(["--all"]) == 0
    capsys.readouterr()

    assert approve.main(["--all"]) == 0

    assert "nothing to do" in capsys.readouterr().out
    assert set(_statuses(assets).values()) == {"approved"}


def test_an_unknown_target_exits_non_zero(tmp_path, monkeypatch):
    approve = _load_script()
    _env(tmp_path, monkeypatch, plates=(("corridor", "a"),))

    assert approve.main(["--key", "cafeteria"]) == 1


def test_no_plates_at_all_exits_non_zero(tmp_path, monkeypatch, capsys):
    approve = _load_script()
    _env(tmp_path, monkeypatch, plates=())

    assert approve.main([]) == 1

    assert "seed_location_plates.py" in capsys.readouterr().out


def test_variant_without_key_is_refused(tmp_path, monkeypatch):
    """A bare variant letter matches all 14 locations — mass publication by typo."""
    approve = _load_script()
    _env(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        approve.main(["--variant", "a"])

    assert "--variant needs --key" in str(exc.value)


def test_key_and_all_are_mutually_exclusive(tmp_path, monkeypatch):
    approve = _load_script()

    with pytest.raises(SystemExit):
        approve.build_parser().parse_args(["--key", "corridor", "--all"])
