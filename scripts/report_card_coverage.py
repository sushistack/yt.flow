"""Card-library coverage per (card_key, pose, angle) — Story 10.8 AC4.

Sizes the generation job without running a three-hour E2E and counting warnings.

READS BOTH STORAGE TIERS, and never merges them into one "truth":

  tier A  `characters.angle_{front,back,side,three_quarter}_path`
          — this IS the `standing` card set. No pose column, no status, no epoch.
          A report that looks for `standing` in `character_cards` finds nothing and
          concludes the library is empty; that reading is wrong and is the story's
          recorded diagnosis being falsified.
  tier B  `character_cards` rows — every non-standing pose, with `status` and
          `style_epoch`.

The `--probe` cross-check is OPT-IN because it spends one DeepSeek call per key per
probed pose: a script named "report" must not bill an account to print a report. It
calls the REAL `resolve_cast_cards` over a synthetic one-shot-per-(key, pose) scene
and reports AGREE/DISAGREE against this report's own reading. `sitting` is probed
alongside `standing` precisely because it is the pose where the two CAN disagree —
the resolver demotes a missing/retired sitting row to standing, which a tier-B read
of the row does not show.

Usage:
    uv run python scripts/report_card_coverage.py
    uv run python scripts/report_card_coverage.py --probe
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.db.models import Character, CharacterCard  # noqa: E402
from yt_flow.services.character_service import (  # noqa: E402
    CANONICAL_ANGLES,
    _ANGLE_FIELD_NAMES,
    CharacterService,
)

# The base poses a run can request (`_normalize_pose` maps everything else onto
# `standing`). `hint:*` cards are excluded on purpose: they are per-scene, generated
# on demand, and there is no fixed set of them to be "missing".
BASE_POSES = ("standing", "sitting")


def probe_scenes(keys: list[str], poses: tuple[str, ...]) -> list[dict]:
    """One shot per (key, pose), so the resolver is asked about each independently."""
    return [{
        "scene_num": 1,
        "narration": "coverage probe",
        "shots": [
            {
                "shot_id": f"P{i:03d}",
                "sentence_indices": [0],
                "image_prompt": "", "negative_prompt": "",
                "camera_angle": None, "camera_movement": None,
                "cast": [{"card_key": key, "position": "center", "depth": "mid", "pose": pose}],
            }
            for i, (key, pose) in enumerate((k, p) for k in keys for p in poses)
        ],
    }]


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true",
                    help="run the resolver cross-check (spends one LLM call per card_key)")
    args = ap.parse_args()

    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")

    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        characters = list(session.exec(select(Character).order_by(Character.scp_id)))
        cards = list(session.exec(select(CharacterCard)))
        if not characters:
            # A fresh install, and the first state anyone would reach for this report
            # from. `keys[0]` below is an IndexError here, which is a worse answer than
            # the true one.
            print("No `characters` rows — the card library is empty. Nothing to size.")
            return
        by_key: dict[tuple[str, str, str], CharacterCard] = {
            (c.scp_id, c.pose, c.angle): c for c in cards
        }

        missing: list[tuple[str, str, str]] = []
        # A row that points at a deleted PNG is not coverage: the question this report
        # answers is "is there a card to draw", and a dangling path answers it "no".
        dangling: list[tuple[str, str, str]] = []
        # Present, approved, but stamped with a different `style_epoch` than the
        # current one. Deliberately NOT folded into `present`: that would silently move
        # the headline number. The fill is blocked on epoch matching (AC7), so its real
        # size is only visible when this count is printed next to MISSING.
        off_epoch: list[tuple[str, str, str, int]] = []
        print(f"{'card_key':<18} {'pose':<9} {'angle':<14} {'tier':<6} {'present':<8} {'status':<9} epoch")
        print("-" * 78)
        for character in characters:
            for pose in BASE_POSES:
                for angle in CANONICAL_ANGLES:
                    if pose == "standing":
                        tier, path = "A", getattr(character, _ANGLE_FIELD_NAMES[angle])
                        # Tier A has no status/epoch columns at all — printing "-" rather
                        # than inventing "approved" keeps the two tiers distinguishable.
                        status, epoch = "-", "-"
                        # `_abs_asset_path` joins against assets_path and is a no-op for
                        # an already-absolute stored path (Path("/a") / "/b" == "/b"),
                        # so this is the same resolution `_resolve_card_path` performs.
                        present = bool(path) and Path(service._abs_asset_path(path)).exists()
                        if path and not present:
                            dangling.append((character.scp_id, pose, angle))
                    else:
                        tier = "B"
                        card = by_key.get((character.scp_id, pose, angle))
                        status = card.status if card else "-"
                        epoch = str(card.style_epoch) if card else "-"
                        present = card is not None and card.status == "approved"
                        if present and not Path(service._abs_asset_path(card.image_path)).exists():
                            present = False
                            dangling.append((character.scp_id, pose, angle))
                        elif present and card.style_epoch != settings.style_epoch:
                            off_epoch.append((character.scp_id, pose, angle, card.style_epoch))
                    if not present:
                        missing.append((character.scp_id, pose, angle))
                    mark = "yes" if present else (
                        "DANGLING" if (character.scp_id, pose, angle) in dangling else "MISSING")
                    print(f"{character.scp_id:<18} {pose:<9} {angle:<14} {tier:<6} "
                          f"{mark:<8} {status:<9} {epoch}")

        # Every row, not one per pose key: the same hint key legitimately exists for
        # two card_keys with DIFFERENT statuses (`hint:475c8a9231` is retired for
        # SCP-049-2 and approved for STOCK-d-class), and printing one row per key hides
        # the approved one — which is the row that decides whether a shot short-circuits
        # before angle selection.
        hint_rows = sorted((c for c in cards if c.pose.startswith("hint:")),
                           key=lambda c: (c.pose, c.scp_id))
        print(f"\nhint:* card rows (not counted as coverage): {len(hint_rows)}")
        for card in hint_rows:
            print(f"  {card.pose:<18} {card.scp_id:<18} {card.status:<9} epoch {card.style_epoch}")
        # Approved hint rows go into the epoch tally even though they are not coverage:
        # an approved hint card SHORT-CIRCUITS angle selection and is drawn as-is, so an
        # off-epoch one is a card actually on screen beside cards of another epoch. That
        # is where the live mismatch lives (STOCK-d-class `hint:475c8a9231` at epoch 2
        # against SCP-049's approved hints at epoch 1) — the base-pose grid alone
        # reports 0 and reads as "no epoch problem", which is not what the fill faces.
        off_epoch.extend(
            (c.scp_id, c.pose, c.angle, c.style_epoch) for c in hint_rows
            if c.status == "approved" and c.style_epoch != settings.style_epoch
        )

        total = len(characters) * len(BASE_POSES) * len(CANONICAL_ANGLES)
        print(f"\nMISSING {len(missing)} of {total} (card_key x pose x angle). Sized as a generation job:")
        # Stated because the denominator flatters nobody: it is the FULL vocabulary
        # cross-product, which demands four sitting angles for keys that were never
        # observed sitting. Run e5ed4b3a's observed demand was 3 sitting placements for
        # one key. The number is kept as the vocabulary target, not read as backlog.
        print(f"  (denominator = {len(characters)} keys x {len(BASE_POSES)} poses x "
              f"{len(CANONICAL_ANGLES)} angles — a full-vocabulary target, NOT observed demand)")
        per_key: dict[str, list[str]] = {}
        for key, pose, angle in missing:
            per_key.setdefault(key, []).append(f"{pose}/{angle}")
        for key, slots in sorted(per_key.items()):
            print(f"  {key:<18} {len(slots):>2}  {', '.join(slots)}")

        print(f"\nDANGLING {len(dangling)} (a row/path exists, the file does not — counted as MISSING):")
        for key, pose, angle in dangling:
            print(f"  {key:<18} {pose}/{angle}")

        print(f"\nOFF-EPOCH {len(off_epoch)} (approved and present, but not style_epoch "
              f"{settings.style_epoch} — the fill has to match, AC7):")
        for key, pose, angle, epoch in off_epoch:
            print(f"  {key:<18} {pose}/{angle} at epoch {epoch}")

        if not args.probe:
            print("\n(resolver cross-check skipped — pass --probe to spend the LLM calls)")
            return

        print("\n-- resolver cross-check (this report's reading vs what resolve_cast_cards resolves) --")
        keys = [c.scp_id for c in characters]
        poses = BASE_POSES
        missing_set = set(missing)
        resolved = await service.resolve_cast_cards(keys[0], probe_scenes(keys, poses))
        present_standing = {
            c.scp_id: {a for a in CANONICAL_ANGLES if getattr(c, _ANGLE_FIELD_NAMES[a])}
            for c in characters
        }
        for i, (key, pose) in enumerate((k, p) for k in keys for p in poses):
            cards_for_shot = resolved.get(f"1:P{i:03d}", [])
            claimed_angles = present_standing[key]
            if not cards_for_shot:
                verdict = ("AGREE (report says no standing angle, resolver skipped it)"
                           if not claimed_angles
                           else f"DISAGREE: report claims {sorted(claimed_angles)}, resolver resolved nothing")
            else:
                got = cards_for_shot[0]
                # The prediction, made from this report's own per-(key, pose, angle)
                # reading of the row the resolver actually landed on: if the report
                # calls that slot missing, the resolver must have demoted to standing;
                # if the report calls it present, the resolver must have kept the pose.
                # This is why `sitting` is probed — on `standing` alone the check was a
                # tautology (the resolver picks its angle from exactly the tier-A set
                # the report reads, so `angle in claimed` could not be False), and a
                # `retired` or absent sitting row is precisely where a naive tier-B read
                # ("the row is there") and the resolver ("demoted") come apart.
                expect = "standing" if (key, pose, got["angle"]) in missing_set else pose
                agree = got["pose"] == expect and got["angle"] in claimed_angles
                verdict = (f"AGREE (resolved {got['pose']}/{got['angle']}, report predicted {expect})"
                           if agree else
                           f"DISAGREE: resolved {got['pose']}/{got['angle']}, "
                           f"report predicted {expect} at one of {sorted(claimed_angles)}")
            print(f"  {key:<18} {pose:<9} {verdict}")


if __name__ == "__main__":
    asyncio.run(main())
