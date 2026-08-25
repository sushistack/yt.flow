#!/usr/bin/env python
"""plate ↔ recomposed pair sheets for the Story 14.2 affordance label set. GPU 0.

    uv run python .../build_pair_sheets.py <run_id>

One row per cast-bearing shot: the background `images/` plate beside the
`recomposed/` output the shot actually shipped. This is the adjudication the
affordance gate needs and had never been built — every earlier affordance number
in this project comes from FIVE plates with ONE known failure
(`scripts/assess_plate_affordance.py` docstring), and its own docstring says one
failure case cannot support a threshold.

Why plate-vs-recomposed and not the plate alone: the defect the gate exists to
prevent is a *recompose* failure — asked to stand a figure where there is no
plausible spot, the model re-frames the whole room and the plate is lost. That is
only visible as a pair. Reading the plate alone is how "17/33 shots are
non-eye-level" gets mistaken for "17/33 shots are broken".

~512px tiles per CLAUDE.md: the judging criterion here (did the room survive, are
the feet on the floor) survives the downscale.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

TILE_W, PER_SHEET = 460, 6
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _tile(path: Path, label: str) -> Image.Image:
    im = Image.open(path).convert("RGB")
    im = im.resize((TILE_W, round(TILE_W * im.height / im.width)), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 8 + 7 * len(label), 18], fill=(0, 0, 0))
    d.text((4, 4), label, fill=(255, 255, 0))
    return im


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    base = REPO / "workspace" / argv[1]
    if not (base / "recomposed").is_dir():
        print(f"no recomposed/ under {base}", file=sys.stderr)
        return 2
    # recomposed/ is written only for cast-bearing shots, so its listing IS the
    # population: no need to re-read the checkpoint to learn who had cast.
    shots = sorted(p.name.split("_")[0] for p in (base / "recomposed").glob("S*.png"))
    rows = []
    for sid in shots:
        plate = next(base.joinpath("images").glob(f"scene_*_{sid}.png"), None)
        rec = next(base.joinpath("recomposed").glob(f"{sid}_*.png"), None)
        if plate is None or rec is None:
            print(f"  ! {sid}: missing {'plate' if plate is None else 'recomposed'}", file=sys.stderr)
            continue
        tiles = [_tile(plate, f"{sid} plate"), _tile(rec, f"{sid} recomposed")]
        row = Image.new("RGB", (sum(t.width for t in tiles), max(t.height for t in tiles)), (20, 20, 20))
        x = 0
        for t in tiles:
            row.paste(t, (x, 0))
            x += t.width
        rows.append(row)

    written = 0
    for i in range(0, len(rows), PER_SHEET):
        chunk = rows[i:i + PER_SHEET]
        sheet = Image.new("RGB", (max(r.width for r in chunk), sum(r.height for r in chunk)), (20, 20, 20))
        y = 0
        for r in chunk:
            sheet.paste(r, (0, y))
            y += r.height
        out = HERE / f"pairs_{i // PER_SHEET + 1}.jpg"
        sheet.save(out, quality=85)
        print(f"{out.name}  {sheet.size}  {len(chunk)} shot(s)")
        written += 1
    print(f"\n{len(rows)} cast-bearing shot(s) over {written} sheet(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
