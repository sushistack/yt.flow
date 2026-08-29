#!/usr/bin/env python
"""Story 14.1: measure the 42 approved location plates. GPU 0, no new renders.

Three stages, in this order, because the ORDER is what keeps the viewpoint judgement
blind (`PREREGISTRATION.md` §2 — the declared `VARIANT_CAMERAS` mapping is the hypothesis
under test, so a judge who has read it is not measuring anything):

    uv run python .../measure_plates.py --dry-run   # enumerate the 42, ZERO VLM calls
    uv run python .../measure_plates.py --sheets    # bake sheet_*.jpg, ZERO VLM calls
    # ... a human/agent reads sheet_*.jpg and fills viewpoint_verdicts.csv ...
    uv run python .../measure_plates.py --commit    # CSV + 2 VLM calls per plate -> manifest

``--commit`` writes ``plate_meta.json`` next to this file (the committed, re-derivable
record) and attaches the same dict to each plate's manifest entry through
``AssetService.record_source(key, "plate_meta", …)`` — load/mutate/save, never
``add_asset``, which would reset ``status`` to draft and drop ``approved_at``.

It never changes a plate's ``status``. A plate that measures ``depicts_person=true``
stays approved and goes on report.md's human-review list: un-approving is a human act.

Sample band: `location_plates` rows with ``status='approved'`` (42 as of 2026-08-25 =
14 location_key x 3 variants, style_epoch 2, all 1920x1080). One VLM call per plate per
question, ``temperature=0``, model ``Settings().character_vision_model``. No repeats —
Story 14.2 measured zero within-condition flips on this endpoint over 33 plates x 2-3
passes, so repetition was not bought. That choice is part of the band.
"""

import argparse
import asyncio
import csv
import importlib.util
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))

from PIL import Image, ImageDraw  # noqa: E402
from sqlmodel import Session  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.services import vision_check  # noqa: E402
from yt_flow.services.asset_service import AssetService  # noqa: E402
from yt_flow.services.location_service import LocationService  # noqa: E402

CSV_PATH = HERE / "viewpoint_verdicts.csv"
META_PATH = HERE / "plate_meta.json"
VERDICTS = ("HIGH", "EYE", "LOW", "UNREADABLE")
# PREREGISTRATION.md §2: the HIGH/EYE and EYE/LOW decision boundaries, and the band around
# them inside which `y_h` is `marginal` (the sheet is read by eye to about this precision).
# Checked, not just documented: the first pass of this story hand-typed the column and
# effectively used +/-0.03, which cost 9 of the 20 marginal rows and made the report's
# sensitivity paragraph — the paragraph that decides how many new plates to render —
# come out of a band nobody had pre-registered.
BOUNDARIES = (0.40, 0.60)
MARGINAL_BAND = 0.05

# The three pre-registered decision lines y=0.40 (red) / 0.50 (grey) / 0.60 (blue), from
# 14-0-angle-conflict/build_viewpoint_sheets.py — the rule being read off them is the same
# rule, so the aid has to be the same aid. The GEOMETRY differs: 1024px tiles 2x3 instead
# of 512px 3x3, because a vanishing point read to +/-0.05 of a 0.40 boundary needs the
# pixels. Same images, same lines, same order; only the magnification changed.
TILE_W, COLS, ROWS = 1024, 2, 3


def _plates(settings: Settings) -> list:
    """The approved plates, in the ONLY order the judgement is allowed to see them."""
    db.init(f"sqlite:///{settings.db_path}")
    with Session(db._engine) as session:
        # list_plates already orders by (location_key, variant). Source is the DB row,
        # not a file glob: `assets/locations/control-room/a.depth.png` is a Story 8.16
        # depth companion sitting in the same tree and is not a plate.
        return [(f"{p.location_key}/{p.variant}", Path(settings.assets_path) / p.image_path)
                for p in LocationService(session, settings=settings).list_plates(status="approved")]


def dry_run(settings: Settings) -> int:
    plates = _plates(settings)
    for key, path in plates:
        size = Image.open(path).size if path.exists() else None
        print(f"{key}\t{path}\t{size}")
    print(f"{len(plates)} approved plates, 0 VLM calls")
    return 0


def sheets(settings: Settings) -> int:
    tiles = []
    for key, path in _plates(settings):
        im = Image.open(path).convert("RGB")
        h = round(TILE_W * im.height / im.width)
        im = im.resize((TILE_W, h), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        for frac, color in ((0.40, (255, 40, 40)), (0.50, (170, 170, 170)), (0.60, (60, 120, 255))):
            y = round(h * frac)
            d.line([(0, y), (TILE_W, y)], fill=color, width=2)
        d.rectangle([0, 0, 14 + 12 * len(key), 30], fill=(0, 0, 0))
        d.text((6, 8), key, fill=(255, 255, 0))
        tiles.append(im)
    per = COLS * ROWS
    for n in range(0, len(tiles), per):
        chunk = tiles[n:n + per]
        # Row height is the tallest tile in THIS sheet, and each row starts below the one
        # above it. The 42 shipped plates are all 1920x1080 so a single height would have
        # worked, but the set is meant to grow (`report.md` §3 specifies five more) and a
        # plate with another aspect ratio would have silently overlapped the row below —
        # i.e. corrupted the very image the viewpoint verdict is read off.
        row_h = max(t.height for t in chunk)
        rows = -(-len(chunk) // COLS)
        sheet = Image.new("RGB", (TILE_W * COLS, row_h * rows), (20, 20, 20))
        for i, t in enumerate(chunk):
            sheet.paste(t, ((i % COLS) * TILE_W, (i // COLS) * row_h))
        out = HERE / f"sheet_{n // per + 1}.jpg"
        sheet.save(out, quality=72)
        print(out.name, sheet.size, len(chunk), "tiles")
    print(f"{len(tiles)} tiles, 0 VLM calls — now fill {CSV_PATH.name} WITHOUT reading any prompt")
    return 0


def _is_marginal(y_h: float) -> bool:
    return min(abs(y_h - b) for b in BOUNDARIES) <= MARGINAL_BAND


def _read_verdicts() -> dict[str, dict]:
    rows = {}
    with CSV_PATH.open(encoding="utf-8") as fh:
        for row in csv.DictReader(line for line in fh if not line.startswith("#")):
            if row["verdict"] not in VERDICTS:
                raise ValueError(f"{row['plate']}: verdict {row['verdict']!r} outside {VERDICTS}")
            if (row["marginal"] == "1") != _is_marginal(float(row["y_h"])):
                # Refuse rather than silently recompute: `verdict` is a human's blind
                # judgement and `marginal` is a pure function of `y_h`, so a disagreement
                # means the CSV and the pre-registration have drifted apart and a person
                # has to look. Rewriting the column here would let the band be edited by
                # accident, which is the failure this check exists to catch.
                raise ValueError(
                    f"{row['plate']}: marginal={row['marginal']} contradicts "
                    f"PREREGISTRATION.md's +/-{MARGINAL_BAND} band around {BOUNDARIES} "
                    f"for y_h={row['y_h']}")
            rows[row["plate"]] = row
    return rows


class _ReasonSink(logging.Handler):
    """Keep the model's own one-sentence ``reason`` from the affordance call.

    ``plate_has_standing_room`` returns ``bool | None`` and logs the free text; re-asking
    for it would be a second envelope for the same question, which is exactly what Story
    14.2 forbade (3/7 vs 5/7 on part order alone). So the text is read off the log record
    the shipped function already emits.

    # ponytail: correct only because `--commit` awaits one plate at a time. Concurrent
    # calls would interleave records with no plate key to sort them by. Add a key to the
    # log record (a src change) before making this loop concurrent.
    """

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.last: str | None = None

    def emit(self, record: logging.LogRecord) -> None:
        if record.args and len(record.args) == 5 and record.args[0] == "plate affordance check":
            self.last = str(record.args[4])


async def commit(settings: Settings) -> int:
    if not settings.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — --commit needs the Qwen-VL key")
    plates = _plates(settings)
    verdicts = _read_verdicts()
    missing = [key for key, _ in plates if key not in verdicts]
    if missing:
        sys.exit(f"{CSV_PATH.name} is missing {len(missing)} plate(s): {', '.join(missing[:5])} …")

    # Imported, not re-implemented: `depicts_person` is a field of the labeler's ONE
    # prompt, and a hand-copied second wording would make the two curators ask different
    # questions (`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`). `scripts/` is not a
    # package, hence the path load.
    spec = importlib.util.spec_from_file_location(
        "label_location_plates", REPO / "scripts" / "label_location_plates.py")
    labeler = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(labeler)

    sink = _ReasonSink()
    logging.getLogger("yt_flow.services.vision_check").addHandler(sink)
    logging.getLogger("yt_flow.services.vision_check").setLevel(logging.INFO)

    now = datetime.now(tz=timezone.utc).isoformat()
    out: dict[str, dict] = {}
    failed: list[str] = []
    db.init(f"sqlite:///{settings.db_path}")
    try:
        with Session(db._engine) as session:
            asset_service = AssetService(settings.assets_path, session)
            for key, path in plates:
                # One plate's failure costs one plate. Without this the 43rd call timing
                # out would abort the loop with the manifest already updated for 42 keys
                # and `plate_meta.json` never written at all — and the re-run buys the
                # whole 84 calls again to recover a file we had the data for.
                try:
                    out[key] = await _measure(settings, asset_service, labeler, sink, key, path,
                                              verdicts[key], now)
                except Exception as exc:  # noqa: BLE001 — see above: isolate, report, continue
                    failed.append(key)
                    print(f"{key}: FAILED ({type(exc).__name__}: {exc})")
    finally:
        # In `finally` for the same reason: whatever was measured before the interruption
        # is real, cost real calls, and is already on the manifest.
        META_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True),
                             encoding="utf-8")
        print(f"\n{len(out)} plates measured, wrote {META_PATH.name}")
    if failed:
        print(f"{len(failed)} plate(s) NOT measured: {', '.join(failed)} — re-run to fill them in")
    print("status untouched — a depicts_person=true plate stays approved and goes to report.md")
    return 0 if not failed else 1


async def _measure(settings, asset_service, labeler, sink, key: str, path: Path,
                   row: dict, now: str) -> dict:
    """Two VLM calls for one plate -> its `plate_meta` dict, attached to the manifest."""
    meta = {
        "viewpoint": row["verdict"],
        "y_h": float(row["y_h"]),
        "marginal": row["marginal"] == "1",
        "measured_at": now,
        "measured_by": "story-14.1/measure_plates.py",
        "vision_model": settings.character_vision_model,
    }
    sink.last = None
    room = await vision_check.plate_has_standing_room(path.read_bytes(), settings)
    # Absent key, never `null`: Story 14.2's undecidable policy is that a refused
    # verdict is NOT "no standing room" (corpse/medical plates are refused
    # deterministically by this endpoint), and the selector must be able to tell
    # "unjudged" from "judged false".
    if room is not None:
        meta["standing_room"] = room
        if sink.last:
            meta["affordance_reason"] = sink.last
    try:
        label = await labeler.score_plate(
            settings, path, labeler.LOCATION_PROMPTS[key.split("/")[0]])
    except Exception as exc:  # noqa: BLE001 — an unanswered question stays unanswered
        print(f"{key}: depicts_person UNDECIDABLE ({type(exc).__name__}: {exc})")
    else:
        # BOTH person axes, not just the new one. The first pass of this story kept
        # `depicts_person` and threw `has_person` away — on the one plate where it
        # mattered most (`entrance-checkpoint/b`, two people in the guard booth, labelled
        # `has_person: true` in 2026-08-02 and approved anyway). They are different
        # questions (a body in the room vs a person inside a picture) and
        # `image._select_plate` filters on both, so a 2026-08-25 re-judgement of the older
        # one is worth exactly as much as the new one and costs the same zero extra calls.
        for field in ("depicts_person", "has_person"):
            if isinstance(label.get(field), bool):
                meta[field] = label[field]
            else:
                print(f"{key}: {field}={label.get(field)!r} not boolean")
        meta["label_notes"] = str(label.get("notes", ""))[:200]
    asset_service.record_source(key, "plate_meta", meta)
    print(f"{key}\t{meta['viewpoint']}\tstanding_room={meta.get('standing_room', 'UNDECIDABLE')}"
          f"\tdepicts_person={meta.get('depicts_person', 'UNDECIDABLE')}"
          f"\thas_person={meta.get('has_person', 'UNDECIDABLE')}")
    return meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="enumerate the approved plates, 0 VLM calls")
    group.add_argument("--sheets", action="store_true", help="bake the y_h contact sheets, 0 VLM calls")
    group.add_argument("--commit", action="store_true", help="CSV + VLM -> plate_meta.json + manifest")
    args = parser.parse_args(argv)
    settings = Settings()
    if args.dry_run:
        return dry_run(settings)
    if args.sheets:
        return sheets(settings)
    return asyncio.run(commit(settings))


if __name__ == "__main__":
    raise SystemExit(main())
