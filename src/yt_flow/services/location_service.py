"""LocationService — Story 8.5 stock location plate resolution + curation gate.

Consumes the `LocationPlate` table (created by Story 8.6) plus `AssetService`
for manifest-backed provenance/lifecycle. Service-layer pattern: session
injection, no cross-layer imports beyond domain/db. [AD-1]
"""

from pathlib import Path

from sqlmodel import Session, select

from yt_flow.config import Settings
from yt_flow.db.models import LocationPlate
from yt_flow.services.asset_service import AssetService


class LocationService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or Settings()

    @property
    def _asset_service(self) -> AssetService:
        return AssetService(self._settings.assets_path, self._session)

    def _abs_asset_path(self, path: str) -> str:
        """Resolve a stored assets/-relative path to a real filesystem path (Story 8.6)."""
        return str(Path(self._settings.assets_path) / path)

    def list_plates(self, location_key: str | None = None, status: str | None = None) -> list[LocationPlate]:
        stmt = select(LocationPlate)
        if location_key is not None:
            stmt = stmt.where(LocationPlate.location_key == location_key)
        if status is not None:
            stmt = stmt.where(LocationPlate.status == status)
        stmt = stmt.order_by(LocationPlate.location_key, LocationPlate.variant)
        return list(self._session.exec(stmt).all())

    def get_approved_plates(self, location_key: str) -> list[LocationPlate]:
        return self.list_plates(location_key=location_key, status="approved")

    def get_approved_plate(self, location_key: str) -> LocationPlate | None:
        plates = self.get_approved_plates(location_key)
        return plates[0] if plates else None

    def resolve_stock_plates(self, location_key: str) -> list[dict]:
        """image_node's STOCK fast-path contract: approved plates as {variant, path}."""
        return [
            {"variant": p.variant, "path": self._abs_asset_path(p.image_path)}
            for p in self.get_approved_plates(location_key)
        ]

    def approve_plate(self, plate_id: str) -> LocationPlate:
        plate = self._session.get(LocationPlate, plate_id)
        if plate is None:
            raise LookupError(f"LocationPlate not found: {plate_id}")
        # Manifest first: if this raises (unknown/retired asset), the DB row stays
        # untouched instead of drifting out of sync with manifest.json.
        self._asset_service.approve_asset(f"{plate.location_key}/{plate.variant}")
        plate.status = "approved"
        self._session.add(plate)
        self._session.commit()
        self._session.refresh(plate)
        return plate

    def reject_plate(self, plate_id: str) -> LocationPlate:
        """Reset an approved/draft plate back to draft (AC9: seed script re-run overwrites it)."""
        plate = self._session.get(LocationPlate, plate_id)
        if plate is None:
            raise LookupError(f"LocationPlate not found: {plate_id}")
        plate.status = "draft"
        self._session.add(plate)
        self._session.commit()
        self._session.refresh(plate)
        return plate
