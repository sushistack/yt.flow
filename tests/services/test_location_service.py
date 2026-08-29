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


# ── Story 14.1: resolve_stock_plates carries the measurement ─────────────────


def _write_manifest(settings, session, key, source):
    service = AssetService(settings.assets_path, session)
    manifest = service.load_manifest()
    manifest["assets"][key]["source"] = source
    service.save_manifest(manifest)


def test_resolve_merges_the_measurement_and_the_labeler_person_flag(svc, session, settings):
    _seed_plate(session, settings, variant="a", status="approved")
    _write_manifest(session=session, settings=settings, key="corridor/a", source={
        "plate_meta": {"viewpoint": "HIGH", "y_h": 0.19, "standing_room": True,
                       "depicts_person": False},
        "label": {"has_person": True, "decision": "draft"},
    })
    (plate,) = svc.resolve_stock_plates("corridor")
    assert plate["viewpoint"] == "HIGH"
    assert plate["standing_room"] is True
    # Two different questions living in two different places in the entry, and
    # `image._select_plate` filters on both — the plate path skips the runtime
    # people-free guard entirely, so this seam is the only carrier.
    assert plate["has_person"] is True
    assert plate["depicts_person"] is False
    assert plate["variant"] == "a"


def test_an_unmeasured_plate_has_no_viewpoint_key_at_all(svc, session, settings):
    """Not `{}`, not `None`. The selector has to tell "never measured" (fail open) from
    "measured and unfit", and a null collapses the two into one silent wrong pick."""
    _seed_plate(session, settings, variant="a", status="approved")
    (plate,) = svc.resolve_stock_plates("corridor")
    assert "viewpoint" not in plate
    assert set(plate) == {"variant", "path"}


def test_metadata_can_never_shadow_variant_or_path(svc, session, settings):
    """A hand-edited `plate_meta` carrying either key would otherwise redirect the copy —
    which is why they are written last, not merged."""
    _seed_plate(session, settings, variant="a", status="approved")
    _write_manifest(session=session, settings=settings, key="corridor/a", source={
        "plate_meta": {"viewpoint": "EYE", "variant": "z", "path": "/etc/passwd"}})
    (plate,) = svc.resolve_stock_plates("corridor")
    assert plate["variant"] == "a"
    assert plate["path"].endswith("locations/corridor/a.png")


def test_either_curator_saying_person_keeps_the_flag_true(svc, session, settings):
    """The 2026-08-02 labeler and the 2026-08-25 measurement ask the same question of the
    same pixels. A re-judgement must not quietly clear the earlier flag — reconciling a
    disagreement is the human queue's job, not this merge's."""
    _seed_plate(session, settings, variant="a", status="approved")
    _write_manifest(session=session, settings=settings, key="corridor/a", source={
        "plate_meta": {"viewpoint": "EYE", "has_person": False},
        "label": {"has_person": True}})
    assert svc.resolve_stock_plates("corridor")[0]["has_person"] is True


@pytest.mark.parametrize("source", [None, "a string", [], {"plate_meta": None},
                                    {"plate_meta": "wat", "label": 7}])
def test_a_malformed_source_block_degrades_to_unmeasured(svc, session, settings, source):
    _seed_plate(session, settings, variant="a", status="approved")
    _write_manifest(session=session, settings=settings, key="corridor/a", source=source)
    (plate,) = svc.resolve_stock_plates("corridor")
    assert set(plate) == {"variant", "path"}


@pytest.mark.parametrize("manifest", [
    {"style_epoch": 1, "assets": []},                       # assets is not a dict
    {"style_epoch": 1, "assets": {"corridor/a": None}},     # the entry is null
    {"style_epoch": 1, "assets": {"corridor/a": "gone"}},   # …or a bare string
    {"style_epoch": 1},                                     # no `assets` key at all
    {"broken": True},
])
def test_a_corrupt_manifest_falls_open_to_no_metadata_not_an_exception(
        svc, session, settings, manifest):
    """The declared fallback is `stock_plate_unfit(no_metadata)` — one warning per shot,
    generation, done. An exception here instead files `stock_plate_resolution_failed` for
    every key in the run, which reads as "the plate database is down" and is a lie.
    `AttributeError`/`TypeError` are the shapes a narrower `except` would have leaked."""
    _seed_plate(session, settings, variant="a", status="approved")
    AssetService(settings.assets_path, session).save_manifest(manifest)
    plates = svc.resolve_stock_plates("corridor")
    assert [set(p) for p in plates] == [{"variant", "path"}]


def test_a_missing_manifest_file_is_not_an_error(svc, session, settings):
    """`load_manifest` already answers `{"assets": {}}` for an absent file, so this is the
    no-plates-registered case rather than a failure — asserted so the merge above cannot
    start depending on the file existing."""
    _seed_plate(session, settings, variant="a", status="approved")
    (settings_path(settings) / "manifest.json").unlink()
    assert [set(p) for p in svc.resolve_stock_plates("corridor")] == [{"variant", "path"}]
