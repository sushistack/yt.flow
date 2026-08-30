"""LocationService — Story 8.5 stock location plate resolution + curation gate.

Consumes the `LocationPlate` table (created by Story 8.6) plus `AssetService`
for manifest-backed provenance/lifecycle. Service-layer pattern: session
injection, no cross-layer imports beyond domain/db. [AD-1]
"""

import logging
from pathlib import Path

from sqlmodel import Session, select

from yt_flow.config import Settings
from yt_flow.db.models import LocationPlate
from yt_flow.services.asset_service import AssetService

logger = logging.getLogger(__name__)

# The two person verdicts D1 filters on (`image._select_plate`). Both are asked twice —
# once by the 2026-08-02 seeding labeler (`scripts/label_location_plates.py`, which writes
# both into `source.label`) and once by the 2026-08-25 measurement (`measure_plates.py`,
# `source.plate_meta`) — and BOTH have to arrive or the selector calls the plate unjudged.
_PERSON_VERDICTS = ("has_person", "depicts_person")


def _fold_verdict(*values: object) -> bool | None:
    """Either curator saying "true" wins; anything that is not a ``bool`` is undecidable.

    Two rules in one line, and both were review findings against the Story 14.8 selector:

    * **OR, not "the newer one wins".** The two writers ask the same question of the same
      pixels months apart. Letting a re-judgement quietly clear an earlier flag is how a
      plate with a person in it comes back; reconciling a disagreement is the human queue's
      job, not this merge's.
    * **``None`` (undecidable) is not ``False``.** The manifest holds whatever JSON the
      labeler emitted, unvalidated — an explicit ``null``, a ``0``/``1``, ``"no"``. Under
      the old ``bool(...)`` fold every one of those read as "no person here" and sailed
      through D1's ``is False``; a truthy non-bool read as "person here" and would reject a
      whole key's pool, silently disabling substitution for that room. Non-bool means
      nobody answered, and the honest reason for that is ``no_metadata``.
    """
    answered = [v for v in values if isinstance(v, bool)]
    return (True in answered) if answered else None


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

    def _manifest_assets(self) -> dict:
        """``manifest["assets"]``, or ``{}`` when the manifest cannot be read or is malformed.

        Story 14.1, and fail-open on purpose: the plate metadata is an *enrichment* of a
        lookup that worked fine without it for three stories. A caller that gets plates
        with no metadata falls back to generation with ``stock_plate_unfit(no_metadata)``,
        which is a normal path; a caller that gets an exception files
        ``stock_plate_resolution_failed`` for every key in the run, which reads as "the
        plate database is down" and is a lie. ``Exception`` rather than
        ``(OSError, ValueError)``: a manifest whose ``assets`` is a list, or whose entry is
        ``None``, raises ``AttributeError``/``TypeError`` on the merge below and would leak
        straight past a narrower clause.
        """
        try:
            assets = self._asset_service.load_manifest()["assets"]
        except Exception as exc:  # noqa: BLE001 — see the docstring: fail open, never raise
            logger.warning("plate metadata unavailable (%s: %s); resolving plates unmeasured",
                           type(exc).__name__, exc)
            return {}
        return assets if isinstance(assets, dict) else {}

    def resolve_stock_plates(self, location_key: str) -> list[dict]:
        """image_node's STOCK fast-path contract: approved plates as
        ``{**measured metadata, variant, path}``.

        Story 14.1 widened this seam from ``{variant, path}``. The manifest is read ONCE
        per call (image_node memoises the call itself, one per location_key per run), and
        two different places in the entry are merged:

        * ``source.plate_meta`` — the 2026-08-25 measurement (``viewpoint``, ``y_h``,
          ``standing_room``, ``depicts_person``, …), written by
          ``14-1-approved-plate-sets/measure_plates.py``.
        * ``source.label`` — the *seeding-time* labeler's verdicts
          (`scripts/label_location_plates.py`), which include **both** ``has_person`` (a
          real body in the room) and ``depicts_person`` (a person inside a picture). They
          are two different questions and ``image._select_plate`` needs both: the plate
          path skips the Story 10.2/14.4 people-free guard entirely (it ``continue``s
          before the render), so a plate a curator already flagged is only kept off the
          screen by this seam carrying the flag through.

        BOTH verdicts are folded, and 14.8's review is why: until then only ``has_person``
        was merged, so a plate that had been labelled but never measured arrived carrying
        half a verdict — and 14.8's selector requires both to be present, which made such a
        plate permanently unassignable (``no_metadata``). The only other writer of
        ``plate_meta.depicts_person`` is `14-1-approved-plate-sets/measure_plates.py`, the
        very instrument this story retired, so "just re-measure it" is not a path. In the
        other direction the labeler's ``depicts_person=true`` was being dropped on the
        floor whenever the measurement said ``false``.

        A plate with no measurement carries **no ``viewpoint`` key at all** — not ``{}``,
        not ``None`` — and the same convention holds for an undecidable person verdict
        (see ``_fold_verdict``). The selector has to tell "never judged" (fail open, fall
        back to generation) from "judged and unfit", and a null would collapse the two.

        ``location_key``, ``variant`` and ``path`` are written LAST so no metadata key can
        shadow the three the selector and the copy depend on. ``location_key`` is there
        because it is the MATCHING AXIS itself (Story 14.8): ``_select_plate`` re-checks
        the equality on the pool it is handed rather than trusting the caller's lookup.
        """
        assets = self._manifest_assets()
        plates = []
        for p in self.get_approved_plates(location_key):
            entry = assets.get(f"{p.location_key}/{p.variant}")
            source = entry.get("source") if isinstance(entry, dict) else None
            source = source if isinstance(source, dict) else {}
            meta = source.get("plate_meta")
            label = source.get("label")
            plate = dict(meta) if isinstance(meta, dict) else {}
            label = label if isinstance(label, dict) else {}
            for field in _PERSON_VERDICTS:
                verdict = _fold_verdict(label.get(field), plate.get(field))
                # Absent, never `None`: "nobody judged this" is expressed the same way the
                # unmeasured `viewpoint` is, so the selector's `is not None` sentinel and
                # this seam cannot drift apart.
                if verdict is None:
                    plate.pop(field, None)
                else:
                    plate[field] = verdict
            plate["location_key"] = p.location_key
            plate["variant"] = p.variant
            plate["path"] = self._abs_asset_path(p.image_path)
            plates.append(plate)
        return plates

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
