"""AssetService — manifest-backed asset library: provenance, integrity, lifecycle, style_epoch.

Architecture: services/ imports domain/ and db/. Must NOT import api/ or pipeline/. [AD-1]
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session

from yt_flow.db.models import LocationPlate

_MANIFEST_NAME = "manifest.json"
_SUBDIRS = ("characters", "locations", "anchors")


class AssetService:
    """Single-responsibility owner of assets/manifest.json — provenance, integrity, lifecycle, style_epoch."""

    def __init__(self, assets_path: Path | str, session: Session) -> None:
        self._root = Path(assets_path)
        self._session = session
        for sub in _SUBDIRS:
            (self._root / sub).mkdir(parents=True, exist_ok=True)

    @property
    def _manifest_path(self) -> Path:
        return self._root / _MANIFEST_NAME

    # ── Manifest ─────────────────────────────────────────────────────────

    def load_manifest(self) -> dict:
        if not self._manifest_path.exists():
            return {"style_epoch": 1, "assets": {}}
        return json.loads(self._manifest_path.read_text())

    def save_manifest(self, manifest: dict) -> None:
        tmp = self._manifest_path.with_name(_MANIFEST_NAME + ".tmp")
        tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
        os.replace(tmp, self._manifest_path)

    def add_asset(self, key: str, path: str, source: dict, **meta) -> None:
        """Insert (or overwrite) a manifest entry and recompute sha256 from the file at ``assets_path / path``."""
        manifest = self.load_manifest()
        sha256 = hashlib.sha256((self._root / path).read_bytes()).hexdigest()
        manifest["assets"][key] = {
            "path": path,
            "sha256": sha256,
            "source": source,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "approved_at": None,
            "status": "draft",
            **meta,
        }
        self.save_manifest(manifest)

    def get_asset(self, key: str, *, include_drafts: bool = False) -> dict | None:
        """Return the manifest entry, or ``None`` if absent — or not approved, unless ``include_drafts``."""
        entry = self.load_manifest()["assets"].get(key)
        if entry is None:
            return None
        if not include_drafts and entry["status"] != "approved":
            return None
        return entry

    # ── Integrity ────────────────────────────────────────────────────────

    def verify_asset(self, key: str) -> bool:
        entry = self.load_manifest()["assets"].get(key)
        if entry is None:
            return False
        file_path = self._root / entry["path"]
        if not file_path.exists():
            return False
        return hashlib.sha256(file_path.read_bytes()).hexdigest() == entry["sha256"]

    def verify_all(self) -> list[str]:
        manifest = self.load_manifest()
        return [key for key in manifest["assets"] if not self.verify_asset(key)]

    # ── Lifecycle ────────────────────────────────────────────────────────

    def approve_asset(self, key: str) -> None:
        manifest = self.load_manifest()
        entry = manifest["assets"][key]
        if entry["status"] == "retired":
            raise ValueError(f"cannot approve a retired asset: {key}")
        if entry["status"] == "approved":
            return
        entry["status"] = "approved"
        entry["approved_at"] = datetime.now(tz=timezone.utc).isoformat()
        self.save_manifest(manifest)

    def retire_asset(self, key: str) -> None:
        manifest = self.load_manifest()
        entry = manifest["assets"][key]
        if entry["status"] == "retired":
            return
        entry["status"] = "retired"
        self.save_manifest(manifest)

    # ── Versioning ───────────────────────────────────────────────────────

    @property
    def style_epoch(self) -> int:
        return self.load_manifest()["style_epoch"]

    def bump_style_epoch(self) -> int:
        manifest = self.load_manifest()
        manifest["style_epoch"] += 1
        self.save_manifest(manifest)
        return manifest["style_epoch"]

    # ── LocationPlate (8-5 consumes; defined here) ──────────────────────

    def add_location_plate(self, location_key: str, variant: str, image_path: str) -> LocationPlate:
        """Create the DB row + manifest entry for a location plate in one call."""
        plate = LocationPlate(
            location_key=location_key, variant=variant, image_path=image_path, style_epoch=self.style_epoch,
        )
        self._session.add(plate)
        self._session.commit()
        self._session.refresh(plate)
        self.add_asset(
            f"{location_key}/{variant}", image_path,
            source={"type": "comfyui_generation"}, location_key=location_key, variant=variant,
        )
        return plate
