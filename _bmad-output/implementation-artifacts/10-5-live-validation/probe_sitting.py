#!/usr/bin/env python
"""Story 10.5 (A) — probe one ``STOCK-d-class`` sitting front before seeding live.

    uv run python _bmad-output/implementation-artifacts/10-5-live-validation/probe_sitting.py

14 of the 23 bad cast slots are missing assets, not a missing technique: the key owns no
``sitting`` card, so ``_resolve_card_path`` fell back to standing. ``seed_stock_cast.py
--pose sitting`` already closes that — but seeding writes an *approved* card row and
``_resolve_card_path`` reads those with no status or epoch filter, so the seeding run is
unreviewable once started. This renders the same recipe into **this directory only**,
for eye judgement against the README's pre-registered rule, first.

It reproduces the seeding run's **front angle** exactly:
``generate_cards_from_descriptor`` overwrites ``characters.visual_descriptor`` with the
authored ``STOCK_DESCRIPTORS`` text before generating, so the front prompt is built from
that text (not from the live enriched read-back) — hence the import from
``scripts/seed_stock_cast.py`` rather than a hand copy that could drift. Reference image
is the same ``--anchor`` the command passes, ``ipadapter_weight`` and ``negative_suffix``
are the values that path uses.

**What it cannot predict.** The seeding run does not pin a seed, so this frame is one
sample of the recipe, not a preview of the bytes that will land. It answers "does this
recipe produce an acceptable seated D-class", not "will that exact card appear".

Writes nothing outside this directory and opens no database.
"""

import argparse
import asyncio
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("YTFLOW_PROJECT_ROOT", str(ROOT))

from seed_stock_cast import STOCK_DESCRIPTORS  # noqa: E402  (the seeding script's own text)
from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.png import has_alpha  # noqa: E402
from yt_flow.domain.state import STOCK_NEGATIVE  # noqa: E402
from yt_flow.services.character_image_provider import create_provider  # noqa: E402
from yt_flow.services.character_service import (  # noqa: E402
    _ANGLE_DESCRIPTIONS,
    _ANGLE_IPADAPTER_WEIGHTS,
    _POSE_DESCRIPTIONS,
    CharacterService,
)

CARD_KEY = "STOCK-d-class"
ANCHOR = "assets/characters/STOCK-d-class/epoch_2/front_candidate_1.png"
SEED = 1071


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-render if the PNG already exists")
    args = ap.parse_args()

    settings = Settings()
    provider = create_provider(settings)
    if provider.__class__.__name__ != "ComfyUICharacterProvider" or settings.comfyui_mock:
        raise SystemExit("this probe needs a live ComfyUICharacterProvider (comfyui_mock off)")

    out = OUT / f"probeA_sitting_front_seed{SEED}.png"
    if out.exists() and not args.force:
        print(f"exists  {out.name}  alpha={has_alpha(out.read_bytes())}  (--force to re-render)")
        return 0

    prompt = CharacterService._compile_generation_prompt(
        visual_descriptor=STOCK_DESCRIPTORS[CARD_KEY],
        angle="front",
        angle_description=f"{_ANGLE_DESCRIPTIONS['front']}, {_POSE_DESCRIPTIONS['sitting']}",
        scp_id=CARD_KEY,
    )
    random.seed(SEED)
    ksampler_seed = random.randint(0, 2**32 - 1)
    random.seed(SEED)
    img = await provider.generate(
        prompt=prompt,
        ref_image_path=str(ROOT / ANCHOR),
        width=settings.character_image_width,
        height=settings.character_image_height,
        ipadapter_weight=_ANGLE_IPADAPTER_WEIGHTS["front"],
        negative_suffix=STOCK_NEGATIVE,
    )
    alpha = has_alpha(img)
    out.write_bytes(img)
    print(f"wrote   {out.name}  rng={SEED} ksampler_seed={ksampler_seed} alpha={alpha} bytes={len(img)}")
    return 0 if alpha else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
