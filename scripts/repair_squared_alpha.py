"""Undo the alpha-squaring damage in already-approved character cards (Story 8.15).

`_normalize_subject_scale` briefly pasted the sprite with itself as the mask, which
double-applies alpha: a (200,200,200,140) edge pixel was written as (110,110,110,77).
Every card generated in that window has its anti-aliased silhouette at ~45% of its
intended opacity with RGB dragged toward black — a thin dark halo once composited.

Regenerating is the obvious fix and the wrong one here: the seed is random, so a re-render
returns a *different* character, and the approved d-class came back obese instead of gaunt.
The damage is a deterministic transform, so invert it instead and keep the approved art:

    alpha_out = alpha_in^2 / 255      ->  alpha_in = sqrt(alpha_out * 255)
    rgb_out   = rgb_in * alpha_in/255 ->  rgb_in   = rgb_out * 255 / alpha_in

Measured against a synthetic ramp, recovery is exact where it matters: for alpha >= 32 the
alpha error is <= 1 and the RGB error <= 3. Below alpha 16 the RGB error reaches ~19
because the premultiplied value was quantised to 8 bits, but those pixels contribute
alpha/255 of themselves to the composite, so the alpha-weighted error stays under 1.5.

# ponytail: idempotence is not free — running this twice would over-brighten the edges, so
# it writes a marker file per epoch directory and refuses a second pass.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

MARKER = ".alpha_repaired"


def repair(png: Path) -> tuple[int, float]:
    """Invert the squaring in place. Returns (edge pixel count, mean alpha gain)."""
    arr = np.array(Image.open(png).convert("RGBA")).astype(np.float64)
    a_out = np.clip(arr[:, :, 3], 0, 255)
    a_in = np.sqrt(a_out * 255.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        rgb_in = np.where(a_in[..., None] > 0, arr[:, :, :3] * 255.0 / a_in[..., None], 0)
    out = np.concatenate([np.clip(rgb_in, 0, 255), np.clip(a_in, 0, 255)[..., None]], axis=2)
    out = out.round().astype(np.uint8)
    edge = (a_out > 0) & (a_out < 255)
    gain = float((out[:, :, 3][edge].astype(float) - a_out[edge]).mean()) if edge.any() else 0.0
    Image.fromarray(out, "RGBA").save(png)
    return int(edge.sum()), gain


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Undo squared alpha in card PNGs.")
    parser.add_argument("dirs", nargs="+", help="Epoch directories holding the damaged cards.")
    parser.add_argument("--force", action="store_true", help="Repair even if already marked.")
    args = parser.parse_args(argv)

    total = 0
    for d in (Path(x) for x in args.dirs):
        if not d.is_dir():
            print(f"skipped (not a directory): {d}")
            continue
        if (d / MARKER).exists() and not args.force:
            print(f"skipped (already repaired): {d}")
            continue
        for png in sorted(d.glob("*.png")):
            edge, gain = repair(png)
            print(f"repaired: {png} ({edge} edge px, mean alpha +{gain:.1f})")
            total += 1
        (d / MARKER).write_text("alpha squaring inverted (Story 8.15)\n", encoding="utf-8")
    print(f"done: {total} cards repaired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
