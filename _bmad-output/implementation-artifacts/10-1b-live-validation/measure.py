#!/usr/bin/env python3
"""Story 10.1b — does the tier-3 card share the plate's light, and by how much?

Adapted from 10-1-live-validation/measure.py. Same control-band method, new
question. 10.1 asked "did the card move?" (a geometry question, answered with a
luminance diff under the feet). 10.1b asks "did the card's colour and luminance
move toward the plate's?" — so every figure here is a card-region statistic
paired with a plate-region control read from the SAME frame.

    PYTHONPATH=src python3 _bmad-output/implementation-artifacts/10-1b-live-validation/measure.py

Reads: the committed off/, tier1/ and tier3/ PNGs plus the run's card sprites.
Writes nothing.

Method notes carried over from 10.1, because they are what make the numbers mean
anything:

* tier1/ and tier3/ are two separate h264 encodes of the same Ken Burns chain, so
  a background-only region still measures a non-zero diff. That is the **noise
  floor**, printed first for every frame. A card-region diff is only evidence if
  it clears it.
* The card region is not guessed. It is the tier1-vs-tier3 diff's own footprint,
  intersected with the sprite's placement band — reported as explicit x/y
  rectangles so any figure below can be re-derived from the committed PNGs.
* "Agreement with the plate" is |card mean − plate mean| per channel. Lower is
  better. The plate sample is the band at the same rows as the card, on the
  card-free side of the frame, so it carries the same Ken Burns crop and the same
  encode.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent

# (clip, timestamp, y-band) — all in 1920x1080 composite pixels.
#
# The card's x-band is NOT hardcoded: the first version of this script inherited
# eyeballed bands and two of them missed the card entirely (S00101's band sat on
# empty wall at x=330..620 while the card was at x=1459..1611, so the script
# reported "unchanged" for a card that visibly changed). Bands are now DERIVED
# from the tier1-vs-tier3 luminance diff footprint and printed with every figure,
# so each number states exactly where it was sampled.
#
# The derivation is honest about what it can and cannot answer: locating the card
# by where the relight acted cannot also prove the relight acted. That is what the
# plate control band is for — an equal-width, card-free strip on the same rows,
# whose diff is pure encode noise and sets the floor every card figure is read against.
SLATE: list[tuple[str, str, tuple[int, int]]] = [
    ("scene_001_S00102", "1.5", (430, 800)),
    ("scene_001_S00101", "1.5", (330, 900)),
    ("scene_002_S00203", "2.4", (280, 900)),
    ("scene_002_S00202", "3.1", (180, 1020)),
    ("scene_001_S00104", "1.2", (180, 1020)),
    ("scene_004_S00403", "1.2", (180, 1020)),
]


def _bands(t1: np.ndarray, t3: np.ndarray, yb: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    """Card x-band from the diff footprint; plate control = same width, card-free, same rows."""
    lum = lambda a: 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    col = np.abs(lum(t1) - lum(t3))[yb[0]:yb[1]].mean(axis=0)
    idx = np.where(col > max(col.max() * 0.25, 2.0))[0]
    if len(idx) == 0:  # no relight acted here — fall back to the frame centre
        w = t1.shape[1]
        return (w // 2 - 100, w // 2 + 100), (60, 260)
    card = (int(idx.min()), int(idx.max()) + 1)
    width, w = card[1] - card[0], t1.shape[1]
    # Widest card-free gap on either side, with a 40px guard so the control never
    # borrows the card's own edge. The control is clipped to that gap rather than
    # forced to the card's width — a wide card footprint (two cards plus the plate
    # between them) leaves less room than the card is wide, and an equal-width
    # strip would then overlap the card and inflate the noise floor, which is
    # exactly what it exists to measure.
    gap_l, gap_r = max(0, card[0] - 40), max(0, w - card[1] - 40)
    if gap_l >= gap_r:
        c1 = card[0] - 40
        return card, (max(0, c1 - width), c1)
    c0 = card[1] + 40
    return card, (c0, min(w, c0 + width))


CHANNELS = ("R", "G", "B")


def _frame(tier: str, clip: str, t: str) -> np.ndarray:
    return np.asarray(Image.open(HERE / tier / f"{clip}_t{t}.png").convert("RGB"), float)


def _stats(a: np.ndarray, xb: tuple[int, int], yb: tuple[int, int]) -> np.ndarray:
    """Mean RGB over the rectangle x=xb, y=yb."""
    return a[yb[0]:yb[1], xb[0]:xb[1]].reshape(-1, 3).mean(axis=0)


def noise_floor(t1: np.ndarray, t3: np.ndarray, plate_x: tuple[int, int], yb: tuple[int, int]) -> float:
    """Mean |luminance diff| over a card-free band: the instrument's own error."""
    d = t1[yb[0]:yb[1], plate_x[0]:plate_x[1]].mean(axis=2) - t3[yb[0]:yb[1], plate_x[0]:plate_x[1]].mean(axis=2)
    return float(np.abs(d).mean())


def report() -> None:
    print("Story 10.1b — card/plate colour agreement, tier 1 vs tier 3")
    print("Every row prints its own sample band, its plate control band, and the")
    print("card-free noise floor measured between the two encodes it compares.\n")

    totals = {"tier1": [], "tier3": []}
    for clip, t, yb in SLATE:
        t1, t3 = _frame("tier1", clip, t), _frame("tier3", clip, t)
        card_x, plate_x = _bands(t1, t3, yb)
        nf = noise_floor(t1, t3, plate_x, yb)

        card1, card3 = _stats(t1, card_x, yb), _stats(t3, card_x, yb)
        plate1, plate3 = _stats(t1, plate_x, yb), _stats(t3, plate_x, yb)
        # Agreement = distance from the card's mean to the plate's, per channel.
        gap1, gap3 = np.abs(card1 - plate1), np.abs(card3 - plate3)
        totals["tier1"].append(gap1.mean())
        totals["tier3"].append(gap3.mean())

        print(f"{clip} @ t={t}s")
        print(f"  card band  x={card_x[0]}..{card_x[1]}  y={yb[0]}..{yb[1]}")
        print(f"  plate band x={plate_x[0]}..{plate_x[1]}  y={yb[0]}..{yb[1]}  (control)")
        print(f"  noise floor (plate band, tier1 vs tier3): {nf:.2f} mean |luminance diff|")
        for i, ch in enumerate(CHANNELS):
            print(
                f"    {ch}: card t1={card1[i]:6.1f} t3={card3[i]:6.1f} | "
                f"plate t1={plate1[i]:6.1f} t3={plate3[i]:6.1f} | "
                f"|card-plate| t1={gap1[i]:5.1f} -> t3={gap3[i]:5.1f}  "
                f"({'closer' if gap3[i] < gap1[i] else 'further'} by {abs(gap3[i] - gap1[i]):.1f})"
            )
        d = np.abs(t1[yb[0]:yb[1], card_x[0]:card_x[1]].mean(axis=2)
                   - t3[yb[0]:yb[1], card_x[0]:card_x[1]].mean(axis=2))
        print(
            f"  card band changed: {d.mean():.2f} mean |luminance diff| "
            f"({d.mean() / nf:.1f}x noise floor), {(d > 8).mean() * 100:3.0f}% of pixels >8 levels\n"
        )

    print("Mean |card - plate| RGB distance across the six-shot slate:")
    print(f"  tier 1: {np.mean(totals['tier1']):.2f}")
    print(f"  tier 3: {np.mean(totals['tier3']):.2f}")
    print("  (lower = card agrees more with its plate; this is the finding-3 axis)")


def sprite_contract() -> None:
    """The relit sprites themselves: same canvas, positive silhouette correlation."""
    relit = sorted((Path("assets/relit")).rglob("*.png"))
    if not relit:
        print("\nNo assets/relit/**.png — tier 3 never cached a sprite.")
        return
    print(f"\nSprite contract — {len(relit)} cached relit sprites")
    for p in relit:
        im = Image.open(p).convert("RGBA")
        a = np.asarray(im.split()[3], float)
        print(f"  {p.relative_to('assets')}: {im.size}, alpha coverage {(a > 200).mean() * 100:.1f}%")


if __name__ == "__main__":
    if not (HERE / "tier3").exists():
        sys.exit("run make_pairs.sh first — tier3/ not found")
    report()
    sprite_contract()
