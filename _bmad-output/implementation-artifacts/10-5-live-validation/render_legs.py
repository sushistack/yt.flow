#!/usr/bin/env python
"""Story 10.5 (B) — render the two new isolation legs for 지적 6 into this directory.

    uv run python _bmad-output/implementation-artifacts/10-5-live-validation/render_legs.py

Question: **which pipeline can draw the requested action state at all?** 10.6 measured
7/7 renders of ``pose_hint="lying supine on table"`` coming back standing or seated, so
the hint reaches the prompt and the model ignores it. Two candidate mechanisms, one
variable each, everything else pinned to 10.6's ② values:

- ``L1`` anchor isolation — same graph, ``ipadapter_weight=0.0``. Tests whether the
  standing frontal reference is what locks the structure. The reference image stays
  *loaded*: passing ``ref_image_path=None`` would take the provider's t2i path and change
  the graph topology too, which is exactly the confound 10.6's ① pair fell into.
- ``L2`` structural conditioning — the ControlNet Union promax graph
  (``comfyui_character_pose_guide_api.json``) with ``humanoid_lying_supine.png`` as an
  openpose control at strength 0.9.

``L0``, the control, is **not rendered here**: it is 10.6's three ②-B frames, same key,
same prompt, same reference, same seeds, same chain, judged 0/3 supine. Re-rendering it
would cost ~15 GPU-minutes to reproduce a number that is already on record.

Seeds: ``ComfyUICharacterProvider._inject_seed`` randomizes the KSampler seed on every
call, so ``random.seed(n)`` is pinned immediately before each ``generate()`` — that is
what makes L0/L1/L2 render *i* share a KSampler seed. Triple: 1061/1062/1063.

**Why it hand-rolls the calls.** ``generate_special_pose_card`` writes the asset file, a
manifest entry, an *approved* ``character_cards`` row — and ``_resolve_card_path`` reads
those with no status or epoch filter, so calling it *is* publishing to production. This
script calls ``CharacterService._compile_generation_prompt`` (a staticmethod — no session)
plus ``provider.generate()`` directly, writes the bytes itself, and opens the database
**read-only** (``mode=ro``) so a mutation is impossible by construction.

VRAM: ComfyUI's ``/system_stats`` reports an instant, not a peak, so it is polled every
2 s for the duration of each render and ``max(vram_total - vram_free)`` is recorded. The
ceiling this host must stay under is 15.92 GiB (``vram_total`` = 17095983104 B).
"""

import argparse
import asyncio
import contextlib
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("YTFLOW_PROJECT_ROOT", str(ROOT))

from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.png import has_alpha  # noqa: E402
from yt_flow.domain.state import STOCK_NEGATIVE  # noqa: E402
from yt_flow.services.character_image_provider import create_provider  # noqa: E402
from yt_flow.services.character_service import (  # noqa: E402
    _ANGLE_DESCRIPTIONS,
    _ANGLE_IPADAPTER_WEIGHTS,
    CharacterService,
    pose_hint_key,
)

CARD_KEY = "STOCK-d-class"
POSE_HINT = "lying supine on table"
SEEDS = (1061, 1062, 1063)
GUIDE = "assets/pose_guides/humanoid_lying_supine.png"
VRAM_CEILING_BYTES = 15.92 * 1024**3
MEASUREMENTS = OUT / "measurements.jsonl"


def read_character(db_path: Path, scp_id: str) -> tuple[str | None, str | None]:
    """(visual_descriptor, angle_front_path) — read-only, by construction."""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        row = conn.execute(
            "select visual_descriptor, angle_front_path from characters where scp_id = ?", (scp_id,)
        ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def special_pose_prompt(descriptor: str, card_key: str, pose_hint: str) -> str:
    """``generate_special_pose_card``'s composition, verbatim.

    Hand-copied, and nothing ties it to the original — if that method's composition
    changes this drifts silently and the legs stop describing production. Compare the two
    by name, not by line number.
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


async def wait_for_free_gpu(base_url: str) -> None:
    """Block while another session's workflow holds the GPU.

    HTTP 200 is not a free GPU (gotcha_comfyui-health-200-is-not-a-free-gpu): the 10-4b
    session shares this card, so the queue's running/pending ``class_type`` sets are
    printed and waited on rather than assumed empty.
    """
    while True:
        async with httpx.AsyncClient(timeout=30.0) as client:
            queue = (await client.get(f"{base_url}/queue")).json()
        busy = False
        for kind in ("queue_running", "queue_pending"):
            for item in queue.get(kind, []):
                classes = sorted({n.get("class_type") for n in item[2].values() if isinstance(n, dict)})
                print(f"  {kind}: {classes}")
                busy = True
        if not busy:
            print("  queue empty — GPU is ours")
            return
        print("  another workflow holds the GPU; waiting 60 s")
        await asyncio.sleep(60)


async def sample_vram(base_url: str, stop: asyncio.Event, out: dict) -> None:
    """Poll /system_stats every 2 s, recording the peak allocation seen."""
    peak_used, total = 0, 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while not stop.is_set():
            try:
                dev = (await client.get(f"{base_url}/system_stats")).json()["devices"][0]
                total = dev["vram_total"]
                peak_used = max(peak_used, total - dev["vram_free"])
            except Exception as exc:  # noqa: BLE001 — a missed sample must not kill the render
                print(f"  (vram sample failed: {exc})")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=2.0)
    out["peak_vram_bytes"], out["vram_total_bytes"] = peak_used, total


async def render(provider, settings, base_url, *, name, prompt, ref, seed, weight, guide, force):
    out = OUT / f"{name}.png"
    if out.exists() and not force:
        alpha = has_alpha(out.read_bytes())
        print(f"exists  {out.name}  alpha={alpha}  (skipped; --force to re-render)")
        return alpha
    # Record the KSampler seed that will actually be injected, not just the RNG input:
    # draw it, then re-pin so _inject_seed draws the same value. The pairing claim is only
    # checkable if the drawn value is logged.
    random.seed(seed)
    ksampler_seed = random.randint(0, 2**32 - 1)
    random.seed(seed)  # pins _inject_seed's draw for THIS call only

    stop, vram = asyncio.Event(), {}
    sampler = asyncio.create_task(sample_vram(base_url, stop, vram))
    started, failure = time.monotonic(), None
    try:
        img = await provider.generate(
            prompt=prompt,
            ref_image_path=ref,
            width=settings.character_image_width,
            height=settings.character_image_height,
            ipadapter_weight=weight,
            negative_suffix=STOCK_NEGATIVE,
            pose_guide_path=guide,
        )
    except Exception as exc:  # noqa: BLE001 — an OOM is a measurement, not a crash
        img, failure = None, f"{type(exc).__name__}: {exc}"
    wall = time.monotonic() - started
    stop.set()
    await sampler

    alpha = has_alpha(img) if img else False
    if img:
        out.write_bytes(img)
    peak_gb = vram.get("peak_vram_bytes", 0) / 1024**3
    row = {
        "name": name, "seed": seed, "ksampler_seed": ksampler_seed,
        "ipadapter_weight": weight, "guide": guide, "wall_sec": round(wall, 1),
        "peak_vram_bytes": vram.get("peak_vram_bytes"), "peak_vram_gib": round(peak_gb, 2),
        "vram_total_bytes": vram.get("vram_total_bytes"),
        "over_ceiling": vram.get("peak_vram_bytes", 0) > VRAM_CEILING_BYTES,
        "alpha": alpha, "bytes": len(img) if img else 0, "failure": failure,
    }
    with MEASUREMENTS.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(
        f"{'wrote  ' if img else 'FAILED '} {name}  rng={seed} ksampler_seed={ksampler_seed} "
        f"weight={weight} guide={'yes' if guide else 'no'} wall={wall:.1f}s "
        f"peak_vram={peak_gb:.2f}GiB alpha={alpha}" + (f"\n  !! {failure}" if failure else "")
    )
    return alpha


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-render legs whose PNG already exists")
    ap.add_argument("--only", choices=("L1", "L2"), help="render only one leg")
    args = ap.parse_args()

    settings = Settings()
    db_path = Path(settings.db_path)
    db_path = db_path if db_path.is_absolute() else ROOT / db_path
    assets = Path(settings.assets_path)
    assets = assets if assets.is_absolute() else ROOT / assets
    if not db_path.is_file():
        raise SystemExit(f"no database at {db_path}; run from the repo root")
    provider = create_provider(settings)
    # Both legs' validity depends on this provider: it is the only one that honours
    # ipadapter_weight, pose_guide_path and _inject_seed. Under QwenCharacterProvider the
    # two legs would be the same call and the isolation would read as "no effect" for a
    # reason unrelated to the hypothesis. Fail loudly instead.
    if provider.__class__.__name__ != "ComfyUICharacterProvider":
        raise SystemExit(f"provider is {provider.__class__.__name__}; these legs need ComfyUICharacterProvider")
    if settings.comfyui_mock:
        raise SystemExit("comfyui_mock is on; these legs need real renders")
    base_url = settings.comfyui_url.rstrip("/")

    descriptor, front = read_character(db_path, CARD_KEY)
    if not descriptor or not front:
        raise SystemExit(f"{CARD_KEY} has no descriptor/front card — the legs cannot be run")
    prompt = special_pose_prompt(descriptor, CARD_KEY, POSE_HINT)
    ref = str(assets / front)
    guide_path = str(ROOT / GUIDE)
    print(f"provider={provider.__class__.__name__} db={db_path} (read-only) out={OUT}")
    print(f"pose_hint_key({POSE_HINT!r}) = {pose_hint_key(POSE_HINT)}  ref={ref}")

    legs = [
        ("L1_anchor0", 0.0, None),
        ("L2_controlnet", _ANGLE_IPADAPTER_WEIGHTS["front"], guide_path),
    ]
    if args.only:
        legs = [leg for leg in legs if leg[0].startswith(args.only)]

    alphas: list[bool] = []
    for leg, weight, guide in legs:
        print(f"\n--- {leg} (ipadapter_weight={weight}, guide={'yes' if guide else 'no'}) ---")
        for i, seed in enumerate(SEEDS, start=1):
            await wait_for_free_gpu(base_url)
            alphas.append(await render(
                provider, settings, base_url, name=f"{leg}_r{i}_seed{seed}",
                prompt=prompt, ref=ref, seed=seed, weight=weight, guide=guide, force=args.force,
            ))

    pngs = sorted(p.name for p in OUT.glob("*.png"))
    print(f"\n{len(pngs)} PNG(s) in {OUT.name}: {', '.join(pngs)}")
    if not all(alphas):
        print("FAIL: at least one render is missing or has no alpha channel", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
