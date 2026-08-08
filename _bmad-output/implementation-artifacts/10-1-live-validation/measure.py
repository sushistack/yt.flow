#!/usr/bin/env python3
"""Story 10.1 — re-derive every number the verdict rests on, from committed evidence.

The dev session reported its measurements without recording the sample bands, so the
figures could be read but not re-checked. This script fixes that: each number below
prints with the exact rectangle or query that produced it.

    PYTHONPATH=src python3 _bmad-output/implementation-artifacts/10-1-live-validation/measure.py

Reads: the committed off/on PNGs, the run's checkpoint, and the plate-side masks.
Writes nothing. `resolve_placements` hits the depth cache, not the GPU.
"""
import asyncio
import statistics
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
RUN = "8a9a288b-800f-4c73-88a2-25ae6b5a4d7d"
IMAGES = Path("workspace") / RUN / "images"


def contact_shadow() -> None:
    """AC6 contributor 2 — is there a shadow under the feet, and is it the shadow?

    Two h264 encodes carry a ~0.9 mean-|luminance| noise floor, so an absolute
    diff proves nothing. The control bands are the instrument: same frame pair,
    same rows, card-free columns.
    """
    off = np.asarray(Image.open(HERE / "off/scene_002_S00202_t3.1.png").convert("L"), float)
    on = np.asarray(Image.open(HERE / "on/scene_002_S00202_t3.1.png").convert("L"), float)
    d = off - on  # positive = the on-state is darker here

    print("Contact shadow — scene_002_S00202 @ t=3.1s")
    print(f"  noise floor, card-free strip x=0..250 : {np.abs(d[:, :250]).mean():.2f} mean |diff|")
    # x from the card's own diff footprint; y starts one row below the feet (y=1018,
    # the rendered anchor) and ends where the diff dies out, so the band is shadow, not boot.
    bands = {
        "shadow  x=1172..1392": (1172, 1392),
        "control x= 772.. 992": (772, 992),
        "control x=1572..1792": (1572, 1792),
    }
    for label, (x0, x1) in bands.items():
        b = d[1019:1051, x0:x1]
        print(f"  {label} y=1019..1051 : {b.mean():+6.2f} mean, {(b > 8).mean() * 100:3.0f}% of pixels >8 levels")


def occlusion_head_cut() -> None:
    """The regression the on-state introduces. Black in a mask = plate occludes the card."""
    print("\nOcclusion masks — black share of each mask (black = card pixels erased)")
    rows = []
    for p in sorted(IMAGES.glob("*.occ_*.png")):
        a = np.asarray(Image.open(p).convert("L"), float)
        rows.append((p.name, (a[: a.shape[0] // 4] < 128).mean() * 100, (a < 128).mean() * 100))
    rows.sort(key=lambda r: -r[1])
    print(f"  {'mask':<52}{'top quarter':>12}{'whole card':>12}")
    for name, top, whole in rows:
        print(f"  {name:<52}{top:11.1f}%{whole:11.1f}%")
    cut = sum(1 for _, top, _ in rows if top > 30)
    print(f"  masks removing >30% of the top quarter (head/shoulders): {cut} / {len(rows)}")


async def ground_placement() -> None:
    """AC3 — replay video_node's own resolver chain against the same checkpoint."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlmodel import Session

    from yt_flow import db
    from yt_flow.config import Settings
    from yt_flow.pipeline.nodes.video import _GROUND_Y_MAX
    from yt_flow.services import compositing_service
    from yt_flow.services.character_service import CharacterService

    settings = Settings()
    db.init("sqlite:///yt_flow.db")
    async with AsyncSqliteSaver.from_conn_string("yt_flow.db") as cp:
        state = (await cp.aget_tuple({"configurable": {"thread_id": RUN}})).checkpoint["channel_values"]
    scenes, scp_id = state["scenes"], state.get("scp_id") or "SCP-049"

    shots = [s for sc in scenes for s in (sc.get("shots") or [])]
    print(f"\nAC4 — shots carrying depth_map_path: {sum(1 for s in shots if s.get('depth_map_path'))} / {len(shots)}")

    # placements are keyed "<scene number>:<shot id>"; depth lives on the shot's cast entries
    depth_by_key = {
        f"{i}:{sh['shot_id']}": [c.get("depth") for c in (sh.get("cast") or [])]
        for i, sc in enumerate(scenes, 1)
        for sh in (sc.get("shots") or [])
    }
    with Session(db._engine) as session:
        cards = await CharacterService(session, settings=settings).resolve_cast_cards(scp_id, scenes)
    placements = await compositing_service.resolve_placements(scenes, cards, settings)

    bands: dict[str, list[float]] = {}
    excess: dict[str, list[float]] = {}
    nulls = masks = total = 0
    for key, entries in placements.items():
        depths = depth_by_key.get(key, [])
        for i, e in enumerate(entries):
            total += 1
            masks += bool(e.get("occlusion_mask"))
            gy = e.get("ground_y")
            if gy is None:
                nulls += 1
                continue
            band = (depths[i] if i < len(depths) else None) or "?"
            bands.setdefault(band, []).append(gy)
            if gy > _GROUND_Y_MAX:
                excess.setdefault(band, []).append((gy - _GROUND_Y_MAX) * 1080)

    print(f"AC3 — cards {total}, null ground_y {nulls}, occlusion masks {masks}")
    print(f"  _GROUND_Y_MAX = {_GROUND_Y_MAX:.4f}")
    clamped = sum(len(v) for v in excess.values())
    for band in ("far", "mid", "near"):
        vals, over = bands.get(band, []), excess.get(band, [])
        if not vals:
            continue
        mean_excess = statistics.mean(over) if over else 0.0
        print(
            f"  {band:<5} n={len(vals):3}  mean ground_y={statistics.mean(vals):.4f}  "
            f"clamped {len(over):2} ({len(over) / len(vals) * 100:3.0f}%)  mean excess {mean_excess:4.1f}px"
        )
    print(f"  clamped overall: {clamped}/{total} = {clamped / total * 100:.1f}%")


if __name__ == "__main__":
    if not IMAGES.exists():
        sys.exit(f"run from the repo root — {IMAGES} not found")
    contact_shadow()
    occlusion_head_cut()
    asyncio.run(ground_placement())
