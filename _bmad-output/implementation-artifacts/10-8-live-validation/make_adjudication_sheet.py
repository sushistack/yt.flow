"""Story 10.8 AC9 — the before/after contact sheet a human adjudicates.

Jay's complaint was visual — *"대부분의 캐릭터들이 그냥 정면 서있는 샷 밖에 없음."* — so the
evidence has to be visual too. This builds it from the **cards the real resolver
actually picks**, for both legs, over the stored scenes of run `e5ed4b3a`:

1. load the run's `scenes` out of the LangGraph checkpoint
   (``measure_fallbacks.load_scenes`` — same loader, same thread, same
   "newest checkpoint with a non-empty ``scenes``" rule);
2. resolve the **fixed** leg with the shipped code and shipped settings, then the
   **baseline** leg through ``measure_fallbacks.install_prefix_behaviour`` plus the
   pinned ``max_tokens=1024`` / ``reasoning="default"`` settings — the same emulation
   the ledger's baseline rows were taken with, validated there against the original
   bytes at `c7c3789`;
3. paste each placement's **own** ``card["path"]`` into a contact sheet, before block
   above after block, in scene/shot order.

Never a hand-written ``(scp_id, pose, angle)`` lookup — the resolver's angle and asset
fallbacks make a direct query lie (Story 10.8 Boundaries).

Order matters inside the process: the fixed leg runs FIRST, because
``install_prefix_behaviour`` monkeypatches ``CharacterService._select_entity_angles``
for the rest of the interpreter's life.

**Both legs read a frozen snapshot of ``yt_flow.db``, not the live file.** Observed
2026-08-16: a card-generation job was writing ``STOCK-d-class`` ``sitting`` rows while
this script ran, and their ``status`` flipped ``approved`` → ``retired`` *between* the
two legs — so the first run of this script produced a before/after in which the library
differed as well as the code, which is not a controlled comparison. The snapshot is
taken with sqlite's own backup API (safe against a concurrent writer), both legs resolve
against it, and the rows that decide the asset fallbacks are recorded in
``adjudication_placements.json`` so a reader can see which library the sheet is of.

Outputs, all in this directory:

    before_after.jpg          all 40 placements, both legs, one sheet
    grid_<card_key>.jpg       one sheet per card_key, larger cells
    angle_histogram.txt/.json per leg per card_key, so the sheet can be recounted
    adjudication_placements.json  the exact sample the JPEGs were drawn from

Usage:
    uv run python _bmad-output/implementation-artifacts/10-8-live-validation/make_adjudication_sheet.py

Spends the same real DeepSeek calls the measurement driver does (1 truncating call for
baseline, one per distinct card_key for fixed). Touches no GPU, generates no card,
writes nothing to the DB.
"""

import asyncio
import json
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import measure_fallbacks as mf  # noqa: E402  (also puts src/ on the path and chdirs to REPO)
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from sqlmodel import Session  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.services import character_service as cs  # noqa: E402

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BG = (16, 16, 18)
PANEL = (30, 30, 34)
INK = (232, 232, 232)
DIM = (150, 150, 156)
RED = (226, 84, 84)
LEGS = ("baseline", "fixed")
LEG_TITLE = {
    "baseline": "BEFORE  (pre-fix: truncated angle call + hardcoded front for extras)",
    "fixed": "AFTER   (10.8 fix: per-card_key angle selection, real budget + reasoning)",
}


# ── resolution ──────────────────────────────────────────────────────────────

def placement_order(scenes: list[dict]) -> list[tuple[str, int]]:
    """(shot_key, index-within-shot) for every cast member, in scene/shot order.

    Built from the scenes, not from a leg's result, so both legs are indexed by the
    same list and cell *i* of the before block is the same placement as cell *i* of
    the after block. A leg that drops a placement shows up as a hole, not as a shift.
    """
    order = []
    for scene in sorted(scenes, key=lambda s: s["scene_num"]):
        for shot in scene.get("shots", []):
            for i, member in enumerate(shot.get("cast") or []):
                if isinstance(member, dict) and member.get("card_key"):
                    order.append((f"{scene['scene_num']}:{shot['shot_id']}", i))
    return order


def snapshot_db(live_path: str) -> str:
    """Freeze the live DB so both legs resolve against ONE library state.

    sqlite's backup API, not a file copy: the live DB has a concurrent writer.
    """
    dst = Path(tempfile.gettempdir()) / "10-8-adjudication-snapshot.db"
    dst.unlink(missing_ok=True)
    src, out = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True), sqlite3.connect(dst)
    with out:
        src.backup(out)
    src.close()
    out.close()
    return str(dst)


def library_state(db_path: str) -> dict:
    """The rows that decide pose/asset fallbacks, as the snapshot froze them."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cards = [
        dict(zip(("card_key", "pose", "angle", "status", "style_epoch"), r, strict=True))
        for r in con.execute(
            "SELECT scp_id, pose, angle, status, style_epoch FROM character_cards ORDER BY scp_id, pose, angle"
        )
    ]
    tier_a = {
        r[0]: [a for a, p in zip(("front", "back", "side", "three_quarter"), r[1:], strict=True) if p]
        for r in con.execute(
            "SELECT scp_id, angle_front_path, angle_back_path, angle_side_path,"
            " angle_three_quarter_path FROM characters ORDER BY scp_id"
        )
    }
    con.close()
    return {"character_cards": cards, "characters_angle_paths": tier_a}


async def resolve_both(db_path: str) -> tuple[str, list[dict], dict[str, list[dict]]]:
    db.init(f"sqlite:///{db_path}")
    scp_id, scenes = mf.load_scenes(db_path)

    legs: dict[str, list[dict]] = {}
    # FIXED FIRST — install_prefix_behaviour patches the class irreversibly.
    fixed_settings = Settings()
    fixed_settings.db_path = db_path
    with Session(db._engine) as session:
        resolved = await cs.CharacterService(session, settings=fixed_settings).resolve_cast_cards(scp_id, scenes)
    legs["fixed"] = resolved

    baseline_settings = Settings()
    baseline_settings.db_path = db_path
    baseline_settings.deepseek_max_tokens = 1024
    baseline_settings.deepseek_reasoning = "default"
    mf.install_prefix_behaviour(scp_id)
    with Session(db._engine) as session:
        resolved = await cs.CharacterService(session, settings=baseline_settings).resolve_cast_cards(scp_id, scenes)
    legs["baseline"] = resolved
    return scp_id, scenes, legs


def flatten(resolved: dict[str, list[dict]], order: list[tuple[str, int]]) -> list[dict | None]:
    """One entry per placement slot; ``None`` where the leg resolved no card."""
    out: list[dict | None] = []
    for shot_key, idx in order:
        cards = resolved.get(shot_key) or []
        out.append({**cards[idx], "shot_key": shot_key} if idx < len(cards) else None)
    return out


# ── drawing ─────────────────────────────────────────────────────────────────

_thumbs: dict[tuple[str, int, int], Image.Image] = {}


def thumb(path: str, w: int, h: int) -> Image.Image:
    """Card PNG cropped to its alpha bbox and fitted into (w, h) on a flat panel.

    The crop is deliberate: these sprites are mostly transparent margin, and at cell
    size the untrimmed figure is a few dozen pixels tall. Trimming is what makes
    "which way is this figure facing" readable — and it is also why this sheet says
    nothing about on-screen scale (see the README's limits section).
    """
    key = (path, w, h)
    if key in _thumbs:
        return _thumbs[key]
    cell = Image.new("RGB", (w, h), PANEL)
    try:
        src = Image.open(path).convert("RGBA")
        bbox = src.getchannel("A").getbbox() or src.getbbox()
        src = src.crop(bbox)
        scale = min(w / src.width, h / src.height)
        src = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))), Image.LANCZOS)
        cell.paste(src, ((w - src.width) // 2, (h - src.height) // 2), src)
    except Exception as exc:  # a missing card must show as a labelled hole, not abort the sheet
        ImageDraw.Draw(cell).text((4, 4), f"!! {type(exc).__name__}", fill=RED, font=ImageFont.load_default())
    _thumbs[key] = cell
    return cell


def sheet(
    blocks: list[tuple[str, list[dict | None]]],
    title: str,
    cols: int,
    tw: int,
    th: int,
) -> Image.Image:
    """Contact sheet: one labelled block per leg, ``cols`` cells wide."""
    font = ImageFont.truetype(FONT, 12)
    head = ImageFont.truetype(FONT, 15)
    pad, band = 6, 4 * 15 + 6  # 4 label lines: shot_key, card_key, pose/angle, fallback
    cw, ch = tw + 2 * pad, th + band + 2 * pad
    rows = [((len(cells) + cols - 1) // cols) for _, cells in blocks]
    height = 34 + sum(26 + r * ch + 10 for r in rows)
    img = Image.new("RGB", (cols * cw, height), BG)
    d = ImageDraw.Draw(img)
    d.text((pad, 9), title, fill=INK, font=head)

    y = 34
    for (label, cells), nrows in zip(blocks, rows, strict=True):
        d.text((pad, y + 5), label, fill=INK, font=head)
        y += 26
        for i, card in enumerate(cells):
            x0, y0 = (i % cols) * cw, y + (i // cols) * ch
            if card is None:
                d.rectangle([x0 + pad, y0 + pad, x0 + pad + tw, y0 + pad + th], outline=RED)
                d.text((x0 + pad + 4, y0 + pad + 4), "no card", fill=RED, font=font)
                continue
            img.paste(thumb(card["path"], tw, th), (x0 + pad, y0 + pad))
            fb = card.get("fallback_reason")
            if fb:
                d.rectangle([x0 + pad, y0 + pad, x0 + pad + tw - 1, y0 + pad + th - 1], outline=RED, width=2)
            ty = y0 + pad + th + 3
            for text, colour in (
                (card["shot_key"], DIM),
                (card["card_key"], INK),
                (f"{card['pose']}/{card['angle']}", INK),
                (f"FALLBACK {fb}" if fb else "", RED),
            ):
                d.text((x0 + pad, ty), text, fill=colour, font=font)
                ty += 15
        y += nrows * ch + 10
    return img


# ── histograms ──────────────────────────────────────────────────────────────

def histogram(cells: list[dict | None]) -> dict:
    per: dict[str, dict] = {}
    for card in cells:
        if card is None:
            continue
        e = per.setdefault(card["card_key"], {"placements": 0, "angles": Counter(), "poses": Counter(), "fallback": Counter()})
        e["placements"] += 1
        e["angles"][card["angle"]] += 1
        e["poses"][card["pose"]] += 1
        if card.get("fallback_reason"):
            e["fallback"][card["fallback_reason"]] += 1
    return {
        k: {
            "placements": v["placements"],
            "distinct_angles": len(v["angles"]),
            "angles": dict(sorted(v["angles"].items())),
            "poses": dict(sorted(v["poses"].items())),
            "fallback": dict(sorted(v["fallback"].items())),
        }
        for k, v in sorted(per.items())
    }


def histogram_text(hists: dict[str, dict], meta: dict) -> str:
    out = [
        "Story 10.8 AC9 — angles drawn per card_key, both legs",
        f"run        {mf.THREAD}",
        f"generated  {meta['ts']}   git {meta['git_rev']}{' +dirty(src/)' if meta['git_dirty'] else ''}",
        f"regenerate {meta['command']}",
        "",
        "Counted off the SAME resolver results the JPEG cells were drawn from",
        "(adjudication_placements.json), so every cell in the sheet is in exactly one",
        "bucket below and the sheet can be recounted by hand against it.",
        "Both legs resolved against ONE frozen snapshot of yt_flow.db, so the only",
        "difference between them is the code (library_state in the JSON is the proof).",
    ]
    for leg in LEGS:
        n = sum(h["placements"] for h in hists[leg].values())
        fb: Counter[str] = Counter()
        for h in hists[leg].values():
            for reason, count in h["fallback"].items():
                for part in reason.split("+"):
                    fb[part] += count
        split = ", ".join(f"{r} {c}" for r, c in sorted(fb.items())) or "none"
        out += [
            "",
            f"=== {leg} ===  {n} placements, "
            f"{sum(sum(h['fallback'].values()) for h in hists[leg].values())} fallback ({split})",
            f"{'card_key':<18}{'n':>4}{'distinct':>10}  angles",
        ]
        for key, h in hists[leg].items():
            angles = "  ".join(f"{a} {n}" for a, n in sorted(h["angles"].items(), key=lambda kv: -kv[1]))
            out.append(f"{key:<18}{h['placements']:>4}{h['distinct_angles']:>10}  {angles}")
        for key, h in hists[leg].items():
            if h["poses"] != {"standing": h["placements"]} or h["fallback"]:
                poses = ", ".join(f"{p} {n}" for p, n in h["poses"].items())
                fb = ", ".join(f"{r} {n}" for r, n in h["fallback"].items()) or "none"
                out.append(f"  {key}: poses {poses}; fallback {fb}")
    return "\n".join(out) + "\n"


# ── main ────────────────────────────────────────────────────────────────────

async def main() -> None:
    snapshot = snapshot_db(Settings().db_path)
    scp_id, scenes, legs = await resolve_both(snapshot)
    order = placement_order(scenes)
    cells = {leg: flatten(legs[leg], order) for leg in LEGS}

    meta = {
        "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "run": mf.THREAD,
        "scp_id": scp_id,
        "git_rev": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "git_dirty": bool(subprocess.run(["git", "status", "--porcelain", "src/"], capture_output=True, text=True).stdout.strip()),
        "command": (
            "uv run python _bmad-output/implementation-artifacts/10-8-live-validation/make_adjudication_sheet.py"
        ),
        "placement_slots": len(order),
        "db_snapshot": snapshot,
    }
    hists = {leg: histogram(cells[leg]) for leg in LEGS}

    (HERE / "adjudication_placements.json").write_text(
        json.dumps(
            {
                **meta,
                # The fixed leg is a temperature-0.3 LLM call: this file IS the sample the
                # JPEGs show, not a claim about every sample.
                "legs": {
                    leg: [
                        None if c is None else {
                            k: (str(Path(c[k]).relative_to(Path.cwd())) if k == "path" and str(c[k]).startswith(str(Path.cwd())) else c[k])
                            for k in ("shot_key", "card_key", "pose", "angle", "path", "fallback", "fallback_reason")
                        }
                        for c in cells[leg]
                    ]
                    for leg in LEGS
                },
                "histogram": hists,
                # The library both legs saw. Only the CODE differs between the legs;
                # this is the proof, and it is here because the live DB was being
                # written while the sheet was built.
                "library_state": library_state(snapshot),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (HERE / "angle_histogram.json").write_text(
        json.dumps({**meta, "histogram": hists}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (HERE / "angle_histogram.txt").write_text(histogram_text(hists, meta), encoding="utf-8")

    written = []
    overview = sheet(
        [(LEG_TITLE[leg], cells[leg]) for leg in LEGS],
        f"Story 10.8 AC9 — cast cards the resolver draws, run {mf.THREAD[:8]} ({scp_id}), "
        f"{len(order)} placements in scene:shot order   [{meta['ts']}]",
        cols=8, tw=168, th=224,
    )
    overview.save(HERE / "before_after.jpg", quality=84, optimize=True)
    written.append(HERE / "before_after.jpg")

    for key in sorted({c["card_key"] for c in cells["fixed"] if c}):
        per_leg = [(LEG_TITLE[leg], [c for c in cells[leg] if c and c["card_key"] == key]) for leg in LEGS]
        img = sheet(per_leg, f"Story 10.8 AC9 — {key}, run {mf.THREAD[:8]}   [{meta['ts']}]", cols=6, tw=232, th=310)
        img.save(HERE / f"grid_{key}.jpg", quality=86, optimize=True)
        written.append(HERE / f"grid_{key}.jpg")

    print((HERE / "angle_histogram.txt").read_text(encoding="utf-8"))
    for p in written:
        print(f"{p.relative_to(mf.REPO)}  {Image.open(p).size}  {p.stat().st_size / 1024:.0f} KiB")


if __name__ == "__main__":
    asyncio.run(main())
