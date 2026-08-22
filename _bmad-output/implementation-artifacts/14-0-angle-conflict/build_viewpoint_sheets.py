#!/usr/bin/env python
"""Contact sheets for the §4-4 (a)/(b) viewpoint adjudication. GPU 0.

    uv run python .../build_viewpoint_sheets.py <run_id>          # sheet_1..N.jpg, 3x3
    uv run python .../build_viewpoint_sheets.py <run_id> --pairs   # sheet_same_prompt_reseed.jpg

Writes ~512px tiles next to this file. ``--pairs`` puts every plate the
Story 10.2 people-guard re-rendered beside its rung-0 draw: the guard bumps the
KSampler seed and leaves ``image_prompt`` untouched (``image.py`` seed ladder),
so each pair is a SAME-PROMPT control for "does the text determine the viewpoint". Each tile carries the
shot_id and the three decision lines the pre-registration reads off:
y=0.40 red, y=0.50 grey, y=0.60 blue. Nothing here reads the prompt text — the
adjudication has to stay blind to it (PREREGISTRATION.md).
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

TILE_W, COLS, ROWS = 512, 3, 3
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _tile(path: Path, label: str) -> Image.Image:
    im = Image.open(path).convert("RGB")
    h = round(TILE_W * im.height / im.width)
    im = im.resize((TILE_W, h), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    for frac, color in ((0.40, (255, 40, 40)), (0.50, (170, 170, 170)), (0.60, (60, 120, 255))):
        y = round(h * frac)
        d.line([(0, y), (TILE_W, y)], fill=color, width=1)
    d.rectangle([0, 0, 8 + 6 * len(label), 18], fill=(0, 0, 0))
    d.text((4, 4), label, fill=(255, 255, 0))
    return im


def pairs(run: str) -> int:
    """Plates whose pixels differ from images_pre_guard = the guard's re-draws."""
    base = REPO / "workspace" / run
    from PIL import ImageChops
    tiles = []
    for p in sorted((base / "images").glob("scene_*_S*.png")):
        pre = base / "images_pre_guard" / p.name
        if not pre.exists():
            continue
        a, b = Image.open(p).convert("RGB"), Image.open(pre).convert("RGB")
        if a.size != b.size or ImageChops.difference(a, b).getbbox() is None:
            continue  # byte-differs only (PNG re-encode) — not a re-render
        shot = p.stem.split("_")[-1]
        tiles += [_tile(pre, f"{shot} seed rung 0"), _tile(p, f"{shot} seed rung 1 (shipped)")]
    if not tiles:
        print(f"no re-rendered plates under workspace/{run}", file=sys.stderr)
        return 3
    th = tiles[0].height
    sheet = Image.new("RGB", (TILE_W * 2, th * (len(tiles) // 2)), (20, 20, 20))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 2) * TILE_W, (i // 2) * th))
    out = HERE / "sheet_same_prompt_reseed.jpg"
    sheet.save(out, quality=88)
    print(out.name, sheet.size, len(tiles) // 2, "pairs")
    return 0


def main(run: str) -> int:
    src = sorted((REPO / "workspace" / run / "images").glob("scene_*_S*.png"))
    if not src:
        print(f"no plates under workspace/{run}/images", file=sys.stderr)
        return 3
    tiles = []
    for p in src:
        im = Image.open(p).convert("RGB")
        h = round(TILE_W * im.height / im.width)
        im = im.resize((TILE_W, h), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        for frac, color in ((0.40, (255, 40, 40)), (0.50, (170, 170, 170)), (0.60, (60, 120, 255))):
            y = round(h * frac)
            d.line([(0, y), (TILE_W, y)], fill=color, width=1)
        shot = p.stem.split("_")[-1]
        d.rectangle([0, 0, 78, 18], fill=(0, 0, 0))
        d.text((4, 4), shot, fill=(255, 255, 0))
        tiles.append(im)
    th = tiles[0].height
    per = COLS * ROWS
    for n in range(0, len(tiles), per):
        chunk = tiles[n:n + per]
        rows = -(-len(chunk) // COLS)
        sheet = Image.new("RGB", (TILE_W * COLS, th * rows), (20, 20, 20))
        for i, t in enumerate(chunk):
            sheet.paste(t, ((i % COLS) * TILE_W, (i // COLS) * th))
        out = HERE / f"sheet_{n // per + 1}.jpg"
        sheet.save(out, quality=88)
        print(out.name, sheet.size, len(chunk), "tiles")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[2] == "--pairs":
        sys.exit(pairs(sys.argv[1]))
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else (print(__doc__) or 2))
