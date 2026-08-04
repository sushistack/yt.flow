"""Unit tests for AssetService — manifest I/O, integrity, lifecycle, style_epoch (Story 8.6)."""

import hashlib
from pathlib import Path

import pytest
from sqlmodel import Session

from yt_flow import db
from yt_flow.services.asset_service import AssetService

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
def svc(tmp_path, session):
    return AssetService(tmp_path, session)


def _write(root: Path, rel: str, data: bytes = PNG_BYTES) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


# ── Manifest I/O (AC2) ──────────────────────────────────────────────────────


def test_bootstraps_subdirs_on_init(tmp_path, session):
    AssetService(tmp_path, session)
    assert (tmp_path / "characters").is_dir()
    assert (tmp_path / "locations").is_dir()
    assert (tmp_path / "anchors").is_dir()


def test_load_manifest_empty_skeleton_when_missing(svc):
    assert svc.load_manifest() == {"style_epoch": 1, "assets": {}}


def test_add_asset_get_asset_round_trip(svc, tmp_path):
    _write(tmp_path, "characters/SCP-049/front.png")
    svc.add_asset("SCP-049/standing_front", "characters/SCP-049/front.png", source={"type": "comfyui_generation"})

    entry = svc.get_asset("SCP-049/standing_front", include_drafts=True)
    assert entry is not None
    assert entry["path"] == "characters/SCP-049/front.png"
    assert entry["status"] == "draft"
    assert entry["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()


def test_get_asset_missing_key_returns_none(svc):
    assert svc.get_asset("nope") is None


def test_get_asset_hides_drafts_by_default(svc, tmp_path):
    _write(tmp_path, "characters/SCP-049/front.png")
    svc.add_asset("SCP-049/standing_front", "characters/SCP-049/front.png", source={"type": "comfyui_generation"})

    assert svc.get_asset("SCP-049/standing_front") is None
    assert svc.get_asset("SCP-049/standing_front", include_drafts=True) is not None

    svc.approve_asset("SCP-049/standing_front")
    assert svc.get_asset("SCP-049/standing_front") is not None


# ── Integrity (AC3) ──────────────────────────────────────────────────────────


def test_verify_asset_valid(svc, tmp_path):
    _write(tmp_path, "characters/SCP-049/front.png")
    svc.add_asset("k", "characters/SCP-049/front.png", source={})
    assert svc.verify_asset("k") is True


def test_verify_asset_tampered(svc, tmp_path):
    _write(tmp_path, "characters/SCP-049/front.png")
    svc.add_asset("k", "characters/SCP-049/front.png", source={})
    (tmp_path / "characters/SCP-049/front.png").write_bytes(b"corrupted")
    assert svc.verify_asset("k") is False


def test_verify_asset_missing_file(svc, tmp_path):
    _write(tmp_path, "characters/SCP-049/front.png")
    svc.add_asset("k", "characters/SCP-049/front.png", source={})
    (tmp_path / "characters/SCP-049/front.png").unlink()
    assert svc.verify_asset("k") is False


def test_verify_asset_missing_key(svc):
    assert svc.verify_asset("nope") is False


def test_verify_all_returns_only_failed_keys(svc, tmp_path):
    _write(tmp_path, "characters/SCP-049/front.png")
    _write(tmp_path, "characters/SCP-049/back.png")
    svc.add_asset("front", "characters/SCP-049/front.png", source={})
    svc.add_asset("back", "characters/SCP-049/back.png", source={})
    (tmp_path / "characters/SCP-049/back.png").unlink()

    assert svc.verify_all() == ["back"]


# ── Lifecycle (AC4) ──────────────────────────────────────────────────────────


def test_approve_asset_sets_status_and_timestamp(svc, tmp_path):
    _write(tmp_path, "a.png")
    svc.add_asset("k", "a.png", source={})
    svc.approve_asset("k")
    entry = svc.get_asset("k")
    assert entry["status"] == "approved"
    assert entry["approved_at"] is not None


def test_approve_asset_noop_if_already_approved(svc, tmp_path):
    _write(tmp_path, "a.png")
    svc.add_asset("k", "a.png", source={})
    svc.approve_asset("k")
    first_ts = svc.get_asset("k")["approved_at"]
    svc.approve_asset("k")
    assert svc.get_asset("k")["approved_at"] == first_ts


def test_approve_retired_asset_raises(svc, tmp_path):
    _write(tmp_path, "a.png")
    svc.add_asset("k", "a.png", source={})
    svc.approve_asset("k")
    svc.retire_asset("k")
    with pytest.raises(ValueError, match="retired"):
        svc.approve_asset("k")


def test_retire_asset_noop_if_already_retired(svc, tmp_path):
    _write(tmp_path, "a.png")
    svc.add_asset("k", "a.png", source={})
    svc.retire_asset("k")
    svc.retire_asset("k")  # no raise
    assert svc.get_asset("k", include_drafts=True)["status"] == "retired"


def test_approve_unknown_key_raises_value_error(svc):
    with pytest.raises(ValueError, match="unknown asset key"):
        svc.approve_asset("nope")


def test_retire_unknown_key_raises_value_error(svc):
    with pytest.raises(ValueError, match="unknown asset key"):
        svc.retire_asset("nope")


# ── Versioning (AC5) ──────────────────────────────────────────────────────────


def test_style_epoch_defaults_to_one(svc):
    assert svc.style_epoch == 1


def test_bump_style_epoch_increments_and_persists(svc, tmp_path, session):
    assert svc.bump_style_epoch() == 2
    assert svc.style_epoch == 2
    # New AssetService instance re-reads the persisted manifest.
    assert AssetService(tmp_path, session).style_epoch == 2


def test_bump_style_epoch_touches_no_asset_entries(svc, tmp_path):
    _write(tmp_path, "a.png")
    svc.add_asset("k", "a.png", source={})
    before = svc.get_asset("k", include_drafts=True)
    svc.bump_style_epoch()
    assert svc.get_asset("k", include_drafts=True) == before


# ── Atomic save ────────────────────────────────────────────────────────────


def test_save_manifest_leaves_no_tmp_file(svc, tmp_path):
    svc.save_manifest({"style_epoch": 1, "assets": {}})
    assert not (tmp_path / "manifest.json.tmp").exists()
    assert (tmp_path / "manifest.json").exists()


def test_save_manifest_crash_mid_write_preserves_original(svc, tmp_path, monkeypatch):
    svc.save_manifest({"style_epoch": 1, "assets": {"a": {"status": "draft"}}})
    original = (tmp_path / "manifest.json").read_text()

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", boom)
    with pytest.raises(OSError):
        svc.save_manifest({"style_epoch": 2, "assets": {}})

    assert (tmp_path / "manifest.json").read_text() == original


# ── LocationPlate (AC6) ──────────────────────────────────────────────────────


def test_add_location_plate_creates_row_and_manifest_entry(svc, tmp_path):
    _write(tmp_path, "locations/isolation-cell/wide.png")
    plate = svc.add_location_plate("isolation-cell", "wide", "locations/isolation-cell/wide.png")

    assert plate.id
    assert plate.style_epoch == 1
    entry = svc.get_asset("isolation-cell/wide", include_drafts=True)
    assert entry is not None
    assert entry["location_key"] == "isolation-cell"
    assert entry["variant"] == "wide"


def test_location_plate_unique_constraint(svc, tmp_path, session):
    from sqlalchemy.exc import IntegrityError

    _write(tmp_path, "locations/isolation-cell/wide.png")
    svc.add_location_plate("isolation-cell", "wide", "locations/isolation-cell/wide.png")
    session.commit()
    with pytest.raises(IntegrityError):
        svc.add_location_plate("isolation-cell", "wide", "locations/isolation-cell/wide.png")


def test_location_plate_unique_constraint_rolls_back_failed_transaction(svc, tmp_path, session):
    """A duplicate-plate IntegrityError must not poison the session for later calls."""
    from sqlalchemy.exc import IntegrityError

    _write(tmp_path, "locations/isolation-cell/wide.png")
    _write(tmp_path, "locations/isolation-cell/close.png")
    svc.add_location_plate("isolation-cell", "wide", "locations/isolation-cell/wide.png")
    session.commit()
    with pytest.raises(IntegrityError):
        svc.add_location_plate("isolation-cell", "wide", "locations/isolation-cell/wide.png")

    # Session must still be usable — a bare `raise` without rollback would leave it
    # in a failed-transaction state and this next call would raise PendingRollbackError.
    plate = svc.add_location_plate("isolation-cell", "close", "locations/isolation-cell/close.png")
    assert plate.id


# ── Pose guides (Story 8.20, AC5) ───────────────────────────────────────────


def _add_guide(svc, root, key="humanoid_kneeling", *, schema="coco18", anatomy="humanoid",
               control_type="openpose", data=PNG_BYTES):
    _write(root, f"pose_guides/{key}.png", data)
    svc.add_pose_guide(
        key, f"pose_guides/{key}.png",
        schema=schema, anatomy=anatomy, control_type=control_type,
        source={"type": "authored_diagram", "license": "CC0-1.0"},
        aliases=("kneeling",),
    )
    return key


def test_add_pose_guide_records_routing_metadata_and_lands_as_draft(svc, tmp_path):
    key = _add_guide(svc, tmp_path)
    entry = svc.load_manifest()["assets"][f"pose_guide/{key}"]
    assert entry["status"] == "draft"
    assert (entry["schema"], entry["anatomy"], entry["control_type"]) == ("coco18", "humanoid", "openpose")
    assert entry["aliases"] == ["kneeling"]
    assert entry["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    assert entry["source"]["license"] == "CC0-1.0"


def test_add_pose_guide_rejects_a_key_outside_the_closed_catalog(svc, tmp_path):
    _write(tmp_path, "pose_guides/humanoid_backflip.png")
    with pytest.raises(ValueError, match="closed catalog"):
        svc.add_pose_guide(
            "humanoid_backflip", "pose_guides/humanoid_backflip.png",
            schema="coco18", anatomy="humanoid", control_type="openpose", source={},
        )


def test_pose_guide_keys_are_namespaced_away_from_card_and_plate_keys(svc, tmp_path):
    """One shared manifest: a guide key must not be able to collide with
    "SCP-049/standing_front" or a location plate key."""
    key = _add_guide(svc, tmp_path)
    assert f"pose_guide/{key}" in svc.load_manifest()["assets"]
    assert key not in svc.load_manifest()["assets"]


def test_resolve_pose_guide_returns_an_approved_compatible_guide_with_abs_path(svc, tmp_path):
    key = _add_guide(svc, tmp_path)
    svc.approve_pose_guide(key)
    entry = svc.resolve_pose_guide(key, "openpose")
    assert entry is not None
    assert entry["abs_path"] == str(tmp_path / "pose_guides" / f"{key}.png")
    assert Path(entry["abs_path"]).read_bytes() == PNG_BYTES


def test_resolve_pose_guide_accepts_an_alias(svc, tmp_path):
    key = _add_guide(svc, tmp_path)
    svc.approve_pose_guide(key)
    assert svc.resolve_pose_guide("kneeling", "openpose") is not None


def test_resolve_pose_guide_rejects_an_unapproved_draft(svc, tmp_path):
    """AC5: unapproved -> edit_only fallback, never a silent draft render."""
    key = _add_guide(svc, tmp_path)
    assert svc.resolve_pose_guide(key, "openpose") is None


def test_resolve_pose_guide_rejects_a_retired_guide(svc, tmp_path):
    key = _add_guide(svc, tmp_path)
    svc.approve_pose_guide(key)
    svc.retire_asset(f"pose_guide/{key}")
    assert svc.resolve_pose_guide(key, "openpose") is None


def test_resolve_pose_guide_rejects_an_integrity_mismatch(svc, tmp_path):
    key = _add_guide(svc, tmp_path)
    svc.approve_pose_guide(key)
    (tmp_path / "pose_guides" / f"{key}.png").write_bytes(PNG_BYTES + b"tampered")
    assert svc.resolve_pose_guide(key, "openpose") is None


def test_resolve_pose_guide_rejects_a_missing_file(svc, tmp_path):
    key = _add_guide(svc, tmp_path)
    svc.approve_pose_guide(key)
    (tmp_path / "pose_guides" / f"{key}.png").unlink()
    assert svc.resolve_pose_guide(key, "openpose") is None


def test_resolve_pose_guide_refuses_a_human_skeleton_on_a_creature_profile(svc, tmp_path):
    """AC6's core safety rule, enforced at the resolver so no caller can bypass it."""
    key = _add_guide(svc, tmp_path)
    svc.approve_pose_guide(key)
    assert svc.resolve_pose_guide(key, "scribble") is None


def test_resolve_pose_guide_refuses_a_creature_silhouette_on_openpose(svc, tmp_path):
    key = _add_guide(
        svc, tmp_path, key="creature_prone_lunge",
        schema="silhouette", anatomy="non_humanoid", control_type="scribble",
    )
    svc.approve_pose_guide(key)
    assert svc.resolve_pose_guide(key, "openpose") is None
    assert svc.resolve_pose_guide(key, "scribble") is not None


def test_resolve_pose_guide_refuses_any_guide_under_edit_only(svc, tmp_path):
    key = _add_guide(svc, tmp_path)
    svc.approve_pose_guide(key)
    assert svc.resolve_pose_guide(key, "edit_only") is None


def test_resolve_pose_guide_rejects_an_unspellable_key(svc):
    assert svc.resolve_pose_guide("humanoid_backflip", "openpose") is None
    assert svc.resolve_pose_guide(None, "openpose") is None


def test_resolve_pose_guide_does_not_mutate_the_manifest_entry(svc, tmp_path):
    """abs_path is a caller convenience; leaking it back into the manifest would
    write a machine-specific absolute path into the committed audit trail (AC12)."""
    key = _add_guide(svc, tmp_path)
    svc.approve_pose_guide(key)
    svc.resolve_pose_guide(key, "openpose")
    assert "abs_path" not in svc.load_manifest()["assets"][f"pose_guide/{key}"]


def test_pose_guide_lifecycle_does_not_disturb_other_assets(svc, tmp_path):
    _write(tmp_path, "characters/SCP-049/front.png")
    svc.add_asset("SCP-049/standing_front", "characters/SCP-049/front.png", source={})
    svc.approve_asset("SCP-049/standing_front")
    key = _add_guide(svc, tmp_path)
    svc.approve_pose_guide(key)
    assert svc.get_asset("SCP-049/standing_front") is not None
    assert svc.verify_all() == []
