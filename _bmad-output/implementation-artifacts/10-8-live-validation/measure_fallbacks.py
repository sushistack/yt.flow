"""Story 10.8 — cast fallback + angle-variety measurement over run `e5ed4b3a`.

Loads the run's stored ``scenes`` out of the LangGraph checkpoint and calls the
**real** ``CharacterService.resolve_cast_cards`` against the live DB. Never a
hand-written ``(scp_id, pose, angle)`` query: the resolver's angle and asset
fallbacks make a direct lookup report cards missing that in fact resolve
(Story 10.8 Boundaries, and the mistake the story records being made on
2026-08-15).

Two legs:

``--leg fixed``
    The shipped code and the shipped settings, untouched.

``--leg baseline``
    The PRE-fix behaviour, re-expressed on top of the fixed code. Two
    mechanisms, because the defect was two defects:

    1. *defect 1 (truncation)* — the settings the request is built from are
       pinned to ``max_tokens=1024`` / ``reasoning="default"``. That produces a
       request body byte-identical to the pre-fix hardcoded one (model,
       messages, ``max_tokens: 1024``, ``temperature: 0.3``, no reasoning
       field), so the truncation is REAL and live, not stubbed: the reasoner
       spends the whole budget in ``reasoning_content`` and returns
       ``content=""``.
    2. *defect 2 (hardcoded front)* — ``_select_entity_angles`` is wrapped so
       that any ``card_key != scp_id`` short-circuits to the exact expression
       the deleted ``else`` branch used (``"front"`` if the character has a
       front path else the first available angle, ``angle_fallback=False``).

    This is an emulation, not the original bytes. Stated plainly because a
    baseline produced by a different mechanism than the original defect is not
    the same measurement. Leg 1 is exact — same request body, same live API,
    same failure. Leg 2 is exact *for this run's data*: all four card keys
    placed by `e5ed4b3a` have ``angle_front_path`` set, so the deleted branch
    and this wrapper cannot diverge here. To reproduce from the original bytes
    instead, check out `c7c3789` and run with `--leg fixed`.

Usage:
    uv run python _bmad-output/implementation-artifacts/10-8-live-validation/measure_fallbacks.py --leg baseline
    uv run python _bmad-output/implementation-artifacts/10-8-live-validation/measure_fallbacks.py --leg fixed

Both legs spend real DeepSeek calls (1 for baseline, one per distinct card_key
for fixed). Neither touches ComfyUI, generates a card, or writes to the DB.
"""

import argparse
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
os.chdir(REPO)

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # noqa: E402
from sqlmodel import Session  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.services import character_service as cs  # noqa: E402

THREAD = "e5ed4b3a-fabb-46e6-8adb-5c1c0fc68889"
OUT = Path(__file__).with_name("measurements.jsonl")


def load_scenes(db_path: str) -> tuple[str, list[dict]]:
    """Newest checkpoint of THREAD whose channel_values carry a non-empty `scenes`."""
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT type, checkpoint FROM checkpoints WHERE thread_id=? ORDER BY checkpoint_id DESC",
        (THREAD,),
    ).fetchall()
    ser = JsonPlusSerializer()
    for typ, blob in rows:
        values = ser.loads_typed((typ, blob)).get("channel_values", {})
        if values.get("scenes"):
            return values["scp_id"], values["scenes"]
    raise SystemExit(f"no checkpoint with scenes for thread {THREAD}")


def install_prefix_behaviour(scp_id: str) -> None:
    """Re-express the pre-fix resolver on top of the fixed one (see module docstring)."""
    original = cs.CharacterService._select_entity_angles

    async def _prefix(self, key: str, catalogue: list[dict]) -> dict[str, dict]:
        if key == scp_id:
            return await original(self, key, catalogue)
        character = self.check_existing_character(key)
        angle = "front" if getattr(character, "angle_front_path", None) else (
            cs._first_available_angle(character) or "front"
        )
        return {f"{s['scene_num']}:{s['shot_id']}": {"angle": angle, "fallback": False}
                for s in catalogue}

    cs.CharacterService._select_entity_angles = _prefix


def summarise(resolved: dict[str, list[dict]]) -> dict:
    placements = [card for cards in resolved.values() for card in cards]
    reasons: Counter[str] = Counter()
    # `.get`, not `[...]`: a measurement instrument that raises KeyError on an
    # unexpected card shape reports nothing at all, where a partial report still
    # carries the placement count and the angle histogram.
    for card in placements:
        for reason in (card.get("fallback_reason") or "").split("+"):
            if reason:
                reasons[reason] += 1
    angles: dict[str, Counter[str]] = defaultdict(Counter)
    poses: dict[str, Counter[str]] = defaultdict(Counter)
    for card in placements:
        angles[card["card_key"]][card["angle"]] += 1
        poses[card["card_key"]][card["pose"]] += 1
    return {
        "shots_with_cards": len(resolved),
        "placements": len(placements),
        "fallback": sum(1 for c in placements if c.get("fallback")),
        "reason_split": dict(sorted(reasons.items())),
        # The metric the fallback count is blind to (Story 10.8 Boundaries): a leg
        # that lowers fallbacks without raising these has not fixed what Jay watched.
        "angles_per_key": {k: dict(sorted(v.items())) for k, v in sorted(angles.items())},
        "distinct_angles_per_key": {k: len(v) for k, v in sorted(angles.items())},
        "poses_per_key": {k: dict(sorted(v.items())) for k, v in sorted(poses.items())},
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--leg", choices=("baseline", "fixed"), required=True)
    ap.add_argument("--no-record", action="store_true", help="print only, do not append to measurements.jsonl")
    args = ap.parse_args()

    settings = Settings()
    if args.leg == "baseline":
        settings.deepseek_max_tokens = 1024
        settings.deepseek_reasoning = "default"

    db.init(f"sqlite:///{settings.db_path}")
    scp_id, scenes = load_scenes(settings.db_path)
    if args.leg == "baseline":
        install_prefix_behaviour(scp_id)

    with Session(db._engine) as session:
        service = cs.CharacterService(session, settings=settings)
        resolved = await service.resolve_cast_cards(scp_id, scenes)

    record = {
        "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "leg": args.leg,
        "run": THREAD,
        "scp_id": scp_id,
        "git_rev": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
        ).stdout.strip(),
        # The fix is deliberately left uncommitted for review, so `git_rev` alone cannot
        # tell a pre-fix run from a post-fix one — both report the same HEAD.
        "git_dirty": bool(subprocess.run(
            ["git", "status", "--porcelain", "src/"], capture_output=True, text=True,
        ).stdout.strip()),
        "request": {
            "model": settings.deepseek_model,
            "max_tokens": settings.deepseek_max_tokens,
            "reasoning": settings.deepseek_reasoning,
        },
        "command": (
            "uv run python _bmad-output/implementation-artifacts/10-8-live-validation/"
            f"measure_fallbacks.py --leg {args.leg}"
        ),
        **summarise(resolved),
    }
    print(json.dumps(record, indent=2, ensure_ascii=False))
    if not args.no_record:
        with OUT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"\nappended -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
