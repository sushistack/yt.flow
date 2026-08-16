"""Judge sheet for the 2026-08-16 regeneration probe: did the newly-shipped fixes reach the pixels?

Three fixes landed after every current card was made, and all three are non-retroactive:

  1. `character-generation` v5 — the 2026-07-08 prompt that had never been seeded, adding
     "no scenery ... or extra characters" and "identical regardless of angle".
  2. `character-vision-enrichment` v3 — stops the descriptor describing the reference PHOTO.
  3. `humanoid_lying_supine` arm spread 47deg -> 18deg.

This renders OLD vs NEW side by side per angle so each one can be judged by eye. It reads
whatever is on disk; it does not generate, approve, retire or write to the DB.

    uv run python _bmad-output/implementation-artifacts/10-8-live-validation/make_regen_sheet.py

The judging questions, in the order the fixes predict:
  - Is it the SAME PERSON across the four angles?  (fix 1 — the current set is not:
    jumpsuit 2135 / 250 / 225 with different hair)
  - Are the angles actually different FACINGS, or four front views with different faces?
  - Any scenery, props, extra figures, or a baked-in background?
  - On the lying card: are the arms near the body rather than splayed?
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

ASSETS = REPO / "assets" / "characters"
OUT = Path(__file__).parent / "regen_STOCK-d-class.jpg"

KEY = "STOCK-d-class"
ANGLES = ["front", "back", "side", "three_quarter"]
CELL_H = 380
LABEL_H = 22


def _find(key: str, epoch: int, stem: str) -> Path | None:
    """Cards are named `{angle}_candidate_1.png` for standing and `{pose}_{angle}.png` otherwise."""
    p = ASSETS / key / f"epoch_{epoch}" / f"{stem}.png"
    return p if p.exists() else None


def _cell(path: Path | None, height: int) -> Image.Image:
    box = Image.new("RGBA", (int(height * 0.72), height), (32, 32, 32, 255))
    if path is None:
        d = ImageDraw.Draw(box)
        d.text((6, height // 2), "(absent)", fill=(150, 150, 150, 255))
        return box
    im = Image.open(path).convert("RGBA")
    # Crop to the alpha bbox first: without it a supine sprite occupying the bottom
    # third of a portrait canvas shrinks to nothing beside a full-height standing one,
    # and the thing being judged is the FIGURE, not its placement on the canvas.
    bb = im.split()[3].getbbox()
    if bb:
        im = im.crop(bb)
    im.thumbnail((box.width - 8, height - 8))
    box.paste(im, ((box.width - im.width) // 2, (height - im.height) // 2), im)
    return box


def sheet(rows: list[tuple[str, list[tuple[str, Path | None]]]]) -> Image.Image:
    cols = max(len(cells) for _, cells in rows)
    cw = int(CELL_H * 0.72)
    img = Image.new("RGB", (cw * cols + 8, (CELL_H + LABEL_H * 2) * len(rows) + 26), (18, 18, 18))
    d = ImageDraw.Draw(img)
    d.text((6, 6), f"Story 10.8 follow-up — {KEY} regeneration probe (old vs new)", fill=(255, 255, 255))
    y = 26
    for title, cells in rows:
        d.text((6, y + 2), title, fill=(255, 220, 120))
        for i, (label, path) in enumerate(cells):
            img.paste(_cell(path, CELL_H).convert("RGB"), (i * cw + 4, y + LABEL_H))
            d.text((i * cw + 8, y + LABEL_H + CELL_H + 2), label, fill=(200, 200, 200))
        y += CELL_H + LABEL_H * 2
    return img


def main() -> int:
    rows: list[tuple[str, list[tuple[str, Path | None]]]] = []

    # Live standing set (epoch 2) — the one whose four angles are four front views.
    rows.append((
        "OLD standing (live, epoch 2) — four angles, but is it one person?",
        [(a, _find(KEY, 2, f"{a}_candidate_1")) for a in ANGLES],
    ))
    # Staged standing set (epoch 3) — generated under character-generation v5.
    rows.append((
        "NEW standing (staged, epoch 3) — character-generation v5",
        [(a, _find(KEY, 3, f"{a}_candidate_1")) for a in ANGLES],
    ))
    # Sitting: the set retired on viewing (3 of 4 were standing figures).
    rows.append((
        "sitting — retired 2026-08-16 (3 of 4 drew a STANDING figure)",
        [(a, _find(KEY, 2, f"sitting_{a}")) for a in ANGLES],
    ))
    # The lying hint card Jay called out, plus the guide raster driving it.
    guide = REPO / "assets" / "pose_guides" / "humanoid_lying_supine.png"
    rows.append((
        "lying hint card + its pose guide (guide retuned 47deg -> 18deg, card NOT yet regenerated)",
        [("hint:475c8a9231 (card)", _find(KEY, 2, "hint_475c8a9231_front")),
         ("humanoid_lying_supine (guide, current)", guide if guide.exists() else None)],
    ))

    img = sheet(rows)
    img.save(OUT, quality=90)
    print(f"wrote {OUT}  {img.size}")
    for title, cells in rows:
        present = sum(1 for _, p in cells if p is not None)
        print(f"  {present}/{len(cells)}  {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
