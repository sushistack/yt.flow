"""Unit tests for LocationService — plate resolution + curation gate (Story 8.5)."""

import pytest
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import LocationPlate
from yt_flow.services.asset_service import AssetService
from yt_flow.services.location_service import LocationService

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@pytest.fixture(autouse=True)
def _init_db():
    db.init("sqlite://")


@pytest.fixture
def session():
    from yt_flow.db import _engine
    with Session(_engine) as s:
        yield s


@pytest.fixture
def settings(tmp_path):
    return Settings(
        langfuse_host="x", langfuse_public_key="x", langfuse_secret_key="x",
        assets_path=str(tmp_path),
    )


@pytest.fixture
def svc(session, settings):
    return LocationService(session, settings=settings)


def _seed_plate(session, settings, location_key="corridor", variant="a", status="draft") -> LocationPlate:
    rel = f"locations/{location_key}/{variant}.png"
    (tmp := settings_path(settings) / rel).parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(PNG_BYTES)
    asset_service = AssetService(settings.assets_path, session)
    plate = asset_service.add_location_plate(location_key, variant, rel)
    if status == "approved":
        asset_service.approve_asset(f"{location_key}/{variant}")
        plate.status = "approved"
        session.add(plate)
        session.commit()
        session.refresh(plate)
    return plate


def settings_path(settings):
    from pathlib import Path
    return Path(settings.assets_path)


def test_get_approved_plate_returns_none_when_no_plates(svc):
    assert svc.get_approved_plate("corridor") is None


def test_get_approved_plate_ignores_draft(svc, session, settings):
    _seed_plate(session, settings, variant="a", status="draft")
    assert svc.get_approved_plate("corridor") is None


def test_get_approved_plate_returns_approved_ordered_by_variant(svc, session, settings):
    _seed_plate(session, settings, variant="b", status="approved")
    _seed_plate(session, settings, variant="a", status="approved")
    plate = svc.get_approved_plate("corridor")
    assert plate is not None
    assert plate.variant == "a"


def test_get_approved_plates_returns_all_approved_variants(svc, session, settings):
    _seed_plate(session, settings, variant="a", status="approved")
    _seed_plate(session, settings, variant="b", status="approved")
    _seed_plate(session, settings, variant="c", status="draft")
    plates = svc.get_approved_plates("corridor")
    assert [p.variant for p in plates] == ["a", "b"]


def test_approve_plate_sets_status_and_manifest(svc, session, settings):
    plate = _seed_plate(session, settings, variant="a", status="draft")
    approved = svc.approve_plate(plate.id)
    assert approved.status == "approved"
    asset_service = AssetService(settings.assets_path, session)
    entry = asset_service.get_asset("corridor/a")
    assert entry is not None
    assert entry["status"] == "approved"


def test_approve_plate_unknown_id_raises(svc):
    with pytest.raises(LookupError):
        svc.approve_plate("does-not-exist")


def test_reject_plate_resets_to_draft(svc, session, settings):
    plate = _seed_plate(session, settings, variant="a", status="approved")
    rejected = svc.reject_plate(plate.id)
    assert rejected.status == "draft"
    assert svc.get_approved_plate("corridor") is None


def test_reject_plate_unknown_id_raises(svc):
    with pytest.raises(LookupError):
        svc.reject_plate("does-not-exist")


def test_list_plates_filters_by_location_key_and_status(svc, session, settings):
    _seed_plate(session, settings, location_key="corridor", variant="a", status="approved")
    _seed_plate(session, settings, location_key="corridor", variant="b", status="draft")
    _seed_plate(session, settings, location_key="office", variant="a", status="approved")

    assert len(svc.list_plates()) == 3
    assert len(svc.list_plates(location_key="corridor")) == 2
    assert len(svc.list_plates(status="approved")) == 2
    assert len(svc.list_plates(location_key="corridor", status="approved")) == 1


def test_abs_asset_path_resolves_against_assets_root(svc, settings):
    assert svc._abs_asset_path("locations/corridor/a.png") == str(
        settings_path(settings) / "locations/corridor/a.png"
    )
