#!/usr/bin/env python
"""Story 10.6 — render the four isolation legs for 지적 14·15 into this directory.

    uv run python _bmad-output/implementation-artifacts/10-6-live-validation/render_legs.py

Writes 8 PNGs **only under this directory** and touches nothing else:

- ① derived-card rule (지적 15), 1 render each at the *same* pinned seed:
    ``leg1-old`` = the pre-10.6 rule (base entity's verbatim descriptor + qualifier
                   line, base's own front card as an IPAdapter identity anchor)
    ``leg1-new`` = the authored ``DERIVED_DESCRIPTORS`` look, no anchor, STOCK_NEGATIVE

  **This pair compares the whole rule, not one variable.** It changes the descriptor,
  the IPAdapter anchor, the negative suffix *and* the graph topology at once — with
  ``ref=None`` the provider takes its t2i path instead of i2i, so the shared seed is not
  a paired sample either. Dropping the anchor alone could account for the whole
  difference. It answers "does the new rule stop producing a second SCP-049", which is
  the story's requirement; it does **not** attribute the change to the descriptor. Do
  not cite it as isolating one argument.
- ② special-pose negative-suffix isolation (지적 14), 3 renders each at a shared
  seed triple:
    ``leg2-A`` = today's chain, no negative suffix (current production behaviour)
    ``leg2-B`` = today's chain, STOCK_NEGATIVE verbatim

**Why it hand-rolls the calls.** ``generate_cards_from_descriptor`` and
``generate_special_pose_card`` write asset files, ``assets/manifest.json`` entries,
``character_cards`` rows and ``characters.angle_*_path``. ``_resolve_card_path`` reads
those columns with **no status or epoch filter**, so calling either of them *is*
publishing to production (gotcha_standing-cards-have-no-approval-gate). This script
therefore calls ``CharacterService._compile_generation_prompt`` (a staticmethod — no
session) plus ``provider.generate()`` directly and writes the bytes itself, and it opens
the database **read-only** (``mode=ro``) so a mutation is impossible by construction.

Seeds: ``ComfyUICharacterProvider._inject_seed`` randomizes the KSampler seed on every
call via ``random.randint``, so ``random.seed(n)`` is pinned immediately before each
``generate()`` — that is what makes leg A render *i* and leg B render *i* share a seed.
"""

import argparse
import asyncio
import os
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("YTFLOW_PROJECT_ROOT", str(ROOT))

from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.png import has_alpha  # noqa: E402
from yt_flow.domain.state import DERIVED_DESCRIPTORS, STOCK_NEGATIVE  # noqa: E402
from yt_flow.services.character_image_provider import create_provider  # noqa: E402
from yt_flow.services.character_service import (  # noqa: E402
    _ANGLE_DESCRIPTIONS,
    _ANGLE_IPADAPTER_WEIGHTS,
    _POSE_DESCRIPTIONS,
    CharacterService,
    pose_hint_key,
)

# The historical defect under investigation, and the exact hint text that produced it.
POSE_HINT = "lying supine on table"
LEG1_SEED = 1051
LEG2_SEEDS = (1061, 1062, 1063)


def read_character(db_path: Path, scp_id: str) -> tuple[str | None, str | None]:
    """(visual_descriptor, angle_front_path) — read-only, by construction."""
    uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        row = conn.execute(
            "select visual_descriptor, angle_front_path from characters where scp_id = ?",
            (scp_id,),
        ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def standing_prompt(descriptor: str, card_key: str) -> str:
    """``generate_candidates_from_reference``'s front/standing composition, verbatim."""
    return CharacterService._compile_generation_prompt(
        visual_descriptor=descriptor,
        angle="front",
        angle_description=f"{_ANGLE_DESCRIPTIONS['front']}, {_POSE_DESCRIPTIONS['standing']}",
        scp_id=card_key,
    )


def special_pose_prompt(descriptor: str, card_key: str, pose_hint: str) -> str:
    """``generate_special_pose_card``'s composition, verbatim.

    Hand-copied, and nothing ties it to the original — if that method's composition
    changes, this drifts silently and the legs stop describing production. Compare the two
    by name, not by line number (line citations here went stale within one session).
    """
    return CharacterService._compile_generation_prompt(
        visual_descriptor=f"{descriptor}\nSpecial pose: {pose_hint.strip()}",
        angle="front",
        angle_description=(
            f"{_ANGLE_DESCRIPTIONS['front']}, {pose_hint.strip()}, "
            "studio background, full body, single subject"
        ),
        scp_id=card_key,
    )


async def render(provider, settings, *, name, prompt, ref, seed, negative_suffix, force):
    out = OUT / f"{name}.png"
    if out.exists() and not force:
        # Still assert the alpha channel, so re-running as a verification step checks the
        # artefacts instead of only reporting that they are present.
        alpha = has_alpha(out.read_bytes())
        print(f"exists  {out.name}  alpha={alpha}  (skipped; --force to re-render)")
        return alpha
    # Record the KSampler seed that will actually be injected, not just the RNG input:
    # draw it, then re-pin so _inject_seed draws the same value. The A/B claim is "both
    # legs shared a seed", and that claim is only checkable if the drawn value is logged.
    random.seed(seed)
    ksampler_seed = random.randint(0, 2**32 - 1)
    random.seed(seed)  # pins _inject_seed's draw for THIS call only
    img = await provider.generate(
        prompt=prompt,
        ref_image_path=ref,
        width=settings.character_image_width,
        height=settings.character_image_height,
        ipadapter_weight=_ANGLE_IPADAPTER_WEIGHTS["front"],
        negative_suffix=negative_suffix,
    )
    alpha = has_alpha(img)
    out.write_bytes(img)
    print(f"wrote   {out.name}  rng={seed}  ksampler_seed={ksampler_seed}  alpha={alpha}  "
          f"bytes={len(img)}  ref={'yes (i2i)' if ref else 'no (t2i)'}  "
          f"neg_suffix={'STOCK_NEGATIVE' if negative_suffix else 'None'}")
    return alpha


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-render legs whose PNG already exists")
    ap.add_argument("--only", choices=("1", "2"), help="render only leg group ① or ②")
    args = ap.parse_args()

    settings = Settings()
    # settings.db_path/assets_path are relative by default, so resolve against the repo
    # root rather than the caller's cwd — otherwise this dies on an sqlite3 traceback
    # instead of the diagnostic exits below.
    db_path = Path(settings.db_path)
    db_path = db_path if db_path.is_absolute() else ROOT / db_path
    assets = Path(settings.assets_path)
    assets = assets if assets.is_absolute() else ROOT / assets
    if not db_path.is_file():
        raise SystemExit(f"no database at {db_path}; run from the repo root")
    provider = create_provider(settings)
    # Both legs' validity depends on this provider. QwenCharacterProvider accepts
    # negative_suffix for signature parity and *discards* it with only a warning, and it
    # does not go through _inject_seed at all — under it leg A and leg B would be the
    # same call and random.seed() a no-op, so the isolation would read as "no effect"
    # for a reason that has nothing to do with the hypothesis. Fail loudly instead.
    if provider.__class__.__name__ != "ComfyUICharacterProvider":
        raise SystemExit(
            f"provider is {provider.__class__.__name__}; these legs require "
            "ComfyUICharacterProvider (it is the only one that honours negative_suffix "
            "and _inject_seed). Set YTFLOW_CHARACTER_IMAGE_PROVIDER=comfyui."
        )
    if settings.comfyui_mock:
        raise SystemExit("comfyui_mock is on; these legs need real renders")
    print(f"provider={provider.__class__.__name__} db={db_path} (read-only) out={OUT}")

    base_desc, base_front = read_character(db_path, "SCP-049")
    dclass_desc, dclass_front = read_character(db_path, "STOCK-d-class")
    hint_key = pose_hint_key(POSE_HINT)
    print(f"pose_hint_key({POSE_HINT!r}) = {hint_key}")

    alphas: list[bool] = []

    if args.only != "2":
        if not base_desc or not base_front:
            raise SystemExit("SCP-049 has no descriptor/front card — leg ① cannot be isolated")
        old_desc = f"{base_desc}\nA reclassified/duplicate instance of SCP-049."
        alphas.append(await render(
            provider, settings, name="leg1-old_inherited-descriptor_seed1051",
            prompt=standing_prompt(old_desc, "SCP-049-2"),
            ref=str(assets / base_front), seed=LEG1_SEED, negative_suffix=None, force=args.force,
        ))
        alphas.append(await render(
            provider, settings, name="leg1-new_authored-descriptor_seed1051",
            prompt=standing_prompt(DERIVED_DESCRIPTORS["SCP-049-2"], "SCP-049-2"),
            ref=None, seed=LEG1_SEED, negative_suffix=STOCK_NEGATIVE, force=args.force,
        ))

    if args.only != "1":
        if not dclass_desc or not dclass_front:
            raise SystemExit("STOCK-d-class has no descriptor/front card — leg ② cannot be run")
        prompt = special_pose_prompt(dclass_desc, "STOCK-d-class", POSE_HINT)
        ref = str(assets / dclass_front)
        for leg, suffix in (("A", None), ("B", STOCK_NEGATIVE)):
            for i, seed in enumerate(LEG2_SEEDS, start=1):
                alphas.append(await render(
                    provider, settings, name=f"leg2-{leg}_{'nosuffix' if suffix is None else 'stocknegative'}_r{i}_seed{seed}",
                    prompt=prompt, ref=ref, seed=seed, negative_suffix=suffix, force=args.force,
                ))

    pngs = sorted(p.name for p in OUT.glob("*.png"))
    print(f"\n{len(pngs)} PNG(s) in {OUT.name}: {', '.join(pngs)}")
    if not all(alphas):
        print("FAIL: at least one render has no alpha channel", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
