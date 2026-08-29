"""AssetService — manifest-backed asset library: provenance, integrity, lifecycle, style_epoch.

Architecture: services/ imports domain/ and db/. Must NOT import api/ or pipeline/. [AD-1]
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from yt_flow.db.models import LocationPlate
from yt_flow.domain.pose import POSE_GUIDE_KEYS, canonical_guide_key, guide_compatible

logger = logging.getLogger(__name__)

_MANIFEST_NAME = "manifest.json"
_SUBDIRS = ("characters", "locations", "anchors", "pose_guides")

# Story 8.20: pose-guide manifest keys are namespaced so a guide can never
# collide with a character card key ("SCP-049/standing_front") or a location
# plate key ("control_room/variant_1") in the one shared manifest.
_GUIDE_PREFIX = "pose_guide/"


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
        """Insert (or overwrite) a manifest entry and recompute sha256 from the file at ``assets_path / path``.

        # ponytail: a re-`add_asset` under a bumped style_epoch overwrites the same
        # key in place rather than archiving the superseded entry (manifest schema
        # rule 4 wants "new entries, not in-place replacement"). Unaddressed because
        # nothing calls bump_style_epoch() yet — revisit once a caller does.
        """
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

    def record_source(self, key: str, field: str, value: dict) -> None:
        """Merge one advisory dict into an existing asset's ``source``, in place.

        Story 14.1. load/mutate/save around the one key, NEVER ``add_asset``: re-adding
        rewrites ``status`` to draft, drops ``approved_at`` and re-stamps ``created_at``
        — exactly the wrong thing to do to a plate that is already approved. That pattern
        was hand-written inside ``scripts/label_location_plates._record_verdict``; the
        second writer (``14-1-approved-plate-sets/measure_plates.py``) is what promotes it
        here, so both curators share one implementation instead of two copies drifting.

        ``LookupError`` on an unregistered key rather than a silent no-op: a curator that
        thinks it attached a measurement and did not is the failure mode this exists to
        prevent (`gotcha_a-decision-that-only-reaches-env-never-ships`, same shape).
        """
        manifest = self.load_manifest()
        entry = manifest["assets"].get(key)
        if entry is None:
            raise LookupError(f"unknown asset key: {key}")
        # A hand-edited or pre-8.6 entry can carry `source: null` (or a bare string), and
        # `setdefault` would hand that back untouched and raise TypeError on the assignment
        # — mid-sweep, with the manifest already half-written from the keys before it. The
        # advisory dict has nowhere to merge into, so it replaces: the LookupError contract
        # above promises a curator that this call either records or raises, never no-ops.
        if not isinstance(entry.get("source"), dict):
            entry["source"] = {}
        entry["source"][field] = value
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
        entry = manifest["assets"].get(key)
        if entry is None:
            raise ValueError(f"unknown asset key: {key}")
        if entry["status"] == "retired":
            raise ValueError(f"cannot approve a retired asset: {key}")
        if entry["status"] == "approved":
            return
        entry["status"] = "approved"
        entry["approved_at"] = datetime.now(tz=timezone.utc).isoformat()
        self.save_manifest(manifest)

    def retire_asset(self, key: str) -> None:
        manifest = self.load_manifest()
        entry = manifest["assets"].get(key)
        if entry is None:
            raise ValueError(f"unknown asset key: {key}")
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

    # ── Pose guides (Story 8.20) ─────────────────────────────────────────
    # Guides reuse this manifest's provenance/integrity/lifecycle authority
    # rather than getting a registry of their own (AC5: one manifest). They are
    # library assets exactly like cards and plates — curated once, reused
    # across runs, and never written by a run.

    def add_pose_guide(
        self, guide_key: str, path: str, *,
        schema: str, anatomy: str, control_type: str,
        source: dict, aliases: tuple[str, ...] | list[str] = (),
    ) -> None:
        """Register a structural pose guide. Lands as ``draft`` like every asset.

        ``schema``/``anatomy``/``control_type`` are what make a guide safely
        routable: ``resolve_pose_guide`` refuses to hand a ``coco18`` human
        skeleton to a creature profile, so these three fields are recorded at
        registration time instead of being re-derived from the filename later.
        """
        if guide_key not in POSE_GUIDE_KEYS:
            raise ValueError(f"pose guide key outside the closed catalog: {guide_key}")
        self.add_asset(
            _GUIDE_PREFIX + guide_key, path, source=source,
            guide_key=guide_key, schema=schema, anatomy=anatomy,
            control_type=control_type, aliases=list(aliases),
        )

    def approve_pose_guide(self, guide_key: str) -> None:
        self.approve_asset(_GUIDE_PREFIX + guide_key)

    def resolve_pose_guide(self, raw_key: object, profile: str) -> dict | None:
        """Return the usable guide entry for ``raw_key`` under ``profile``, else ``None``.

        Fails closed to ``None`` (the caller's edit_only fallback, AC5) on every
        rejection path, each logged with its reason: unspellable key, absent
        entry, unapproved/retired status, integrity mismatch, or a
        schema/anatomy incompatible with the character's profile.

        Returns a copy with ``abs_path`` resolved so callers never re-join the
        asset root and never mutate the manifest entry in place.
        """
        key = canonical_guide_key(raw_key)
        if key is None:
            logger.warning("resolve_pose_guide: key outside the approved catalog: %r", raw_key)
            return None
        manifest_key = _GUIDE_PREFIX + key
        entry = self.get_asset(manifest_key)
        if entry is None:
            logger.warning(
                "resolve_pose_guide: %s is missing or not approved -> edit_only fallback", manifest_key,
            )
            return None
        if not self.verify_asset(manifest_key):
            logger.warning(
                "resolve_pose_guide: %s failed integrity verification -> edit_only fallback", manifest_key,
            )
            return None
        if not guide_compatible(profile, entry.get("schema", ""), entry.get("anatomy", "")):
            logger.warning(
                "resolve_pose_guide: guide %s (schema=%r anatomy=%r) is incompatible with "
                "conditioning profile %r -> edit_only fallback",
                key, entry.get("schema"), entry.get("anatomy"), profile,
            )
            return None
        return {**entry, "abs_path": str(self._root / entry["path"])}

    # ── LocationPlate (8-5 consumes; defined here) ──────────────────────

    def add_location_plate(
        self, location_key: str, variant: str, image_path: str, source: dict | None = None,
    ) -> LocationPlate:
        """Create the DB row + manifest entry for a location plate in one call.

        ``source`` merges extra provenance into the manifest entry (Story 8.17 puts
        the render seed/reroll salt there, and the auto-labeler's verdict later) —
        ``LocationPlate`` has no such columns and one advisory dict is not a migration.
        """
        plate = LocationPlate(
            location_key=location_key, variant=variant, image_path=image_path, style_epoch=self.style_epoch,
        )
        self._session.add(plate)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            raise
        self._session.refresh(plate)
        self.add_asset(
            f"{location_key}/{variant}", image_path,
            source={"type": "comfyui_generation", **(source or {})},
            location_key=location_key, variant=variant,
        )
        return plate
