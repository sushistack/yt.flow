"""Promote staged character cards to live, or reject them (Story 8.15, widened 14.6).

``seed_stock_cast.py --stage`` writes a replacement card set into the *next* style
epoch and nothing else — no manifest entry, no approval, no ``angle_*_path``
repoint. This script is the only thing that makes those files live.

**An epoch is promoted atomically: every key and every pose staged in it, together,
and every promotion closes with ``bump_style_epoch()``.** That is not a preference,
it is the only mechanism that separates staging from live. ``staged_dir`` is
``epoch_{style_epoch + 1}`` — the staging slot and the next live slot are the SAME
directory — so a promotion that does not bump leaves the files it just published as
the target of the next ``--stage``. Review loop 1 of Story 14.6 built the alternative
(per-pose orphan checks, bump only on ``standing``) and reviewers reproduced three
failures from it:

  1. a ``standing`` promotion bumped globally while the orphan check was per pose, so
     a staged ``sitting`` set was left in what had just become the live ``epoch_N`` —
     unreachable by promotion *and* by ``--reject``, both of which then compute
     ``epoch_{N+1}`` and report "nothing staged";
  2. a bump-free promotion left ``epoch`` unchanged, so a later ``--reject`` of that
     pose recomputed the same epoch, deleted the four cards that were now LIVE and
     approved, "restored" a ``None`` descriptor over the live one, and exited 0;
  3. the same arithmetic let a re-``--stage`` of a promoted pose overwrite the pixels
     an approved manifest entry had already hashed, breaking ``verify_asset`` and the
     write-once ``_prestage_descriptor.txt`` rule with it.

``--key`` / ``--pose`` are narrowing filters, and a narrowed PROMOTION is REFUSED while
any other staged set remains in the epoch — they can assert what is staged, never
promote a part of it. ``--reject`` is not bound by that rule and is not gated by the
blockers either: it deletes staged files and publishes nothing, so it stays available
exactly when a half-written stage has made promotion impossible — which is when an
operator needs it. ``--key`` narrows a rejection freely; ``--pose`` cannot, because one
directory holds every pose staged for a key.

Staged files are validated by ``has_alpha`` **and** ``sprite_contract``, both, before
anything mutates. Neither subsumes the other: ``has_alpha`` walks chunks and CRCs and
catches a truncated or corrupt container that Pillow opens without complaint;
``sprite_contract`` decodes pixels and catches a fully opaque RGBA, which is exactly
what ``has_alpha`` cannot see. A card that slips past either one reaches
``video.py:2537``, which raises and kills the run.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from seed_stock_cast import (  # noqa: E402
    POSTSTAGE_DESCRIPTOR_FILE,
    PRESTAGE_DESCRIPTOR_FILE,
    VALID_POSES,
    staged_dir,
)
from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.db.models import Character, CharacterCard  # noqa: E402
from yt_flow.domain.png import alpha_profile, has_alpha, sprite_contract  # noqa: E402
from yt_flow.services.character_service import CANONICAL_ANGLES, CharacterService, _sanitize_scp_id  # noqa: E402


def _card_filename(pose: str, angle: str) -> str:
    """The name ``character_service`` saves a card under (``:877-879``), mirrored.

    Not unified with a single convention on purpose: renaming would migrate every
    existing epoch directory and the 108 path strings in the manifest, with 24
    unregistered files already loose on disk. The approver learns the branch instead.
    """
    return f"{angle}_candidate_1.png" if pose == "standing" else f"{pose}_{angle}.png"


def _staged_paths(assets_root: Path, key: str, pose: str, epoch: int) -> dict[str, str]:
    """``{angle: path relative to assets_root}`` for one key's staged set of one pose.

    Cards are addressed by exact filename, never globbed — that is what keeps
    ``PRESTAGE_DESCRIPTOR_FILE`` in the same directory from being taken for one.
    """
    rel_dir = staged_dir(assets_root, key, epoch).relative_to(assets_root)
    return {angle: str(rel_dir / _card_filename(pose, angle)) for angle in CANONICAL_ANGLES}


def _discover(
    assets_root: Path, epoch: int, session: Session,
) -> tuple[dict[tuple[str, str], dict[str, str]], list[str], dict[str, tuple[str | None, Path]]]:
    """Everything staged in ``epoch_{epoch}``: ``{(card_key, pose): {angle: rel_path}}``.

    Enumerated from DISK, not from a key list, because the whole point is to find sets
    nobody remembered to name. The second return value is the list of blockers — a
    non-empty list means refuse to PROMOTE before mutating anything. The third is every
    ``epoch_{epoch}`` directory on disk, blocked ones included, keyed by card key (or by
    directory name when no ``characters`` row maps to it): ``--reject`` works from that
    list, because a directory a blocker names is precisely the one an operator needs to
    delete and it may hold no promotable set at all.

    A directory that exists but yields no promotable set is a blocker, not a skip: a
    stage that died after writing ``_prestage_descriptor.txt`` leaves exactly that, and
    skipping it would let the closing bump strand it in a live epoch. Checking for card
    files alone misses it, which is how review loop 1 missed it.
    """
    by_safe = {_sanitize_scp_id(c.scp_id): c.scp_id for c in session.exec(select(Character))}
    staged: dict[tuple[str, str], dict[str, str]] = {}
    blockers: list[str] = []
    directories: dict[str, tuple[str | None, Path]] = {}
    root = assets_root / "characters"
    if not root.is_dir():
        return staged, blockers, directories
    for entry in sorted(root.iterdir()):
        directory = entry / f"epoch_{epoch}"
        if not directory.is_dir():
            continue
        key = by_safe.get(entry.name)
        directories[key or entry.name] = (key, directory)
        if key is None:
            blockers.append(f"staged directory has no `characters` row: {directory}")
            continue
        found: dict[str, dict[str, str]] = {}
        for pose in VALID_POSES:
            paths = {angle: directory / _card_filename(pose, angle) for angle in CANONICAL_ANGLES}
            present = [angle for angle, path in paths.items() if path.is_file()]
            if not present:
                continue
            if len(present) < len(CANONICAL_ANGLES):
                blockers.append(
                    f"incomplete staged set: {key} ({pose}) has {len(present)}/{len(CANONICAL_ANGLES)} "
                    f"cards in {directory} (missing {sorted(set(paths) - set(present))})"
                )
            found[pose] = _staged_paths(assets_root, key, pose, epoch)
        if not found:
            blockers.append(
                f"staged directory holds no promotable card set: {directory} "
                f"(contains {sorted(p.name for p in directory.iterdir())})"
            )
            continue
        for pose, angle_paths in found.items():
            staged[(key, pose)] = angle_paths
    return staged, blockers, directories


def _select(
    staged: dict[tuple[str, str], dict[str, str]], keys: list[str], poses: list[str], epoch: int,
) -> tuple[dict[tuple[str, str], dict[str, str]] | None, str]:
    """Apply the ``--key``/``--pose`` filters, or explain why the PROMOTION is refused.

    A filter that leaves anything staged behind is refused rather than honoured: the
    closing bump would orphan the remainder in a directory that has just become live.

    Promotion only. ``--reject`` does not come through here — it deletes directories and
    publishes nothing, so a sibling set staged for another key is no reason to refuse it,
    and forcing "all or nothing" there would mean discarding a good sibling to clear a
    bad one.
    """
    selected = {
        (key, pose): paths for (key, pose), paths in staged.items()
        if (not keys or key in keys) and (not poses or pose in poses)
    }
    if not selected:
        return None, f"nothing staged in epoch_{epoch} matches the given --key/--pose"
    leftover = sorted(set(staged) - set(selected))
    if leftover:
        return None, (
            f"refusing partial promotion: still staged in epoch_{epoch}: "
            + ", ".join(f"{key} ({pose})" for key, pose in leftover)
        )
    return selected, ""


def _reject(directory: Path, key: str | None, service: CharacterService) -> None:
    """Delete a staged directory and undo the one live write staging makes.

    Addressed by DIRECTORY, not by key, because rejection has to reach the directories
    ``_discover`` reports as blockers — including one that maps to no ``characters`` row
    at all, which has no key to be addressed by.

    A missing sidecar means the descriptor was NOT snapshotted, which is not the same
    as "there was no descriptor": the promote path *consumes* the sidecar, so writing
    ``None`` back on its absence is how review loop 1 wiped a live descriptor. Absent
    sidecar therefore leaves ``visual_descriptor`` alone.

    The restore is also refused when the live descriptor is neither the pre-stage text
    nor the text THIS staging left (``_poststage_descriptor.txt``). Restoring on the
    sidecar alone assumes nothing has touched the column since the stage, and the live
    library falsified that assumption cheaply: `STOCK-d-class/epoch_3` carries a sidecar
    that diverges from the live descriptor from character 380 on, and a directory staged
    before Story 14.6 carries no post-stage record to settle which of the two is the
    staging's own product. Warn and keep the live text: an operator can paste the sidecar
    back, but nobody can recover a descriptor this script has overwritten.

    This can no longer fire against an already-promoted set at all, because promotion
    always bumps: ``epoch`` is then one past the directory that was promoted, so the
    lookup below finds nothing. The rule above is the belt to that suspenders — the
    invariant is one line in another function and this is destructive.
    """
    sidecar = directory / PRESTAGE_DESCRIPTOR_FILE
    character = service.check_existing_character(key) if key else None
    if character is not None and sidecar.is_file():
        previous = sidecar.read_text(encoding="utf-8")
        staged_file = directory / POSTSTAGE_DESCRIPTOR_FILE
        staged_text = staged_file.read_text(encoding="utf-8") if staged_file.is_file() else None
        live = character.visual_descriptor
        if live == previous:
            pass  # staging never got as far as replacing it, or it already matches
        elif staged_text is not None and live == staged_text:
            service.update_character(character.id, visual_descriptor=previous)
            print(f"restored pre-stage descriptor: {key}")
        else:
            print(
                f"WARNING: NOT restoring the descriptor for {key} — the live "
                f"`visual_descriptor` ({len(live or '')} chars) is neither the pre-stage "
                f"sidecar ({len(previous)} chars) nor "
                + (f"the text this stage left ({len(staged_text)} chars)"
                   if staged_text is not None
                   else f"any recorded staging text ({POSTSTAGE_DESCRIPTOR_FILE} is absent, "
                        "so this directory was staged before Story 14.6)")
                + f". Something edited the column since the stage; putting {sidecar} back "
                  "would roll that edit away silently. The staged files are still deleted; "
                  "restore the descriptor by hand if that sidecar is the text you want."
            )
    shutil.rmtree(directory)
    print(f"rejected: {key or directory.parent.name} ({directory})")


def _retire_special_pose_cards(session, service: CharacterService, key: str) -> None:
    """Retire ``hint:*`` cards derived from the superseded front card.

    ``get_card`` only returns approved rows, so retiring them makes 8.4's
    on-demand path regenerate them from the promoted front on the next run.

    Standing promotions only: a hint card is generated from ``angle_front_path``, so a
    ``sitting`` promotion supersedes nothing it was derived from.
    """
    safe_key = _sanitize_scp_id(key)
    cards = session.exec(select(CharacterCard).where(CharacterCard.scp_id == key)).all()
    for card in cards:
        if not card.pose.startswith("hint:"):
            continue
        card.status = "retired"
        session.add(card)
        try:
            service._asset_service.retire_asset(f"{safe_key}/{card.pose}_{card.angle}")
        except (ValueError, OSError) as exc:  # noqa: PERF203 - retire is best-effort
            print(f"warning: could not retire manifest entry for {card.pose}: {exc}")
        print(f"retired: {key} {card.pose}")
    session.commit()


def _validate(assets_root: Path, selected: dict[tuple[str, str], dict[str, str]]) -> list[str]:
    """Every precondition, over every target, before the first mutation.

    Collected in full rather than short-circuited: an operator who has to re-render is
    entitled to the whole list, and a per-target check inside the promotion loop would
    leave earlier targets live and return short of ``bump_style_epoch()`` — which is
    failure mode 3 in this module's docstring.
    """
    violations: list[str] = []
    for (key, pose), angle_paths in sorted(selected.items()):
        for angle, rel_path in angle_paths.items():
            abs_path = assets_root / rel_path
            if not abs_path.is_file():
                violations.append(f"no staged card: {key} ({pose}) {angle} ({abs_path})")
                continue
            data = abs_path.read_bytes()
            # BOTH, always. See the module docstring: `has_alpha` is the container/CRC
            # check and `sprite_contract` is the pixel check, and each passes files the
            # other rejects. Story 14.6's spec names replacing one with the other as a
            # Never, because review loop 1 did exactly that.
            if not has_alpha(data):
                violations.append(
                    f"staged card fails has_alpha (format/CRC): {key} ({pose}) {angle} ({abs_path})"
                )
            passes, reason = sprite_contract(data)
            if not passes:
                profile = alpha_profile(data) or {}
                violations.append(
                    f"staged card fails sprite_contract [{reason}]: {key} ({pose}) {angle} "
                    f"({abs_path}) — canvas={profile.get('canvas_w')}x{profile.get('canvas_h')} "
                    f"aspect={profile.get('canvas_aspect')} "
                    f"transparent_fraction={profile.get('transparent_fraction')} "
                    f"alpha_bbox={profile.get('alpha_bbox')}"
                )
    return violations


def run(keys: list[str] | tuple[str, ...] = (), poses: list[str] | tuple[str, ...] = (),
        *, reject: bool = False) -> int:
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    assets_root = Path(settings.assets_path)
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        asset_service = service._asset_service
        epoch = asset_service.style_epoch + 1

        staged, blockers, directories = _discover(assets_root, epoch, session)
        for blocker in blockers:
            print(blocker)

        if reject:
            # Blockers do NOT gate rejection, and this is the whole point: rejection is
            # what an operator reaches for BECAUSE of a blocker. `seed_stock_cast.py`
            # snapshots the descriptor and lets generation replace the live one BEFORE it
            # raises on an incomplete set, so a ComfyUI crash (Story 5.23) lands as
            # exactly an incomplete or sidecar-only directory, with the live
            # `visual_descriptor` already holding staging text and the only restore path
            # behind this gate. Refusing here left `rm -rf` inside `assets/` as the
            # recovery — the thing this gate exists to prevent. Rejection deletes staged
            # files and touches nothing live.
            targets = {
                name: entry for name, entry in directories.items()
                if not keys or name in keys
            }
            if not targets:
                print(f"nothing staged in epoch_{epoch}"
                      + (f" matches --key {', '.join(keys)}" if keys else ""))
                return 1
            if poses:
                # One directory holds every pose staged for a key, so `--pose` cannot
                # narrow a delete. Said out loud instead of honoured or silently dropped.
                print(f"note: --pose is ignored by --reject — the whole epoch_{epoch} "
                      f"directory of {', '.join(sorted(targets))} is deleted")
            for name in sorted(targets):
                key, directory = targets[name]
                _reject(directory, key, service)
            return 0

        if blockers:
            return 1
        if not staged:
            # Nothing to act on is a failure, not a silent success: after a promotion
            # `epoch` is one past the retired staging epoch, so a mistaken run would
            # otherwise look like it worked.
            print(f"nothing staged in epoch_{epoch}")
            return 1

        selected, refusal = _select(staged, list(keys), list(poses), epoch)
        if selected is None:
            print(refusal)
            return 1

        # `_discover` maps every directory through a `characters` row, so a key here
        # always has one.
        characters = {key: service.check_existing_character(key) for key, _ in selected}
        violations = _validate(assets_root, selected)
        if violations:
            print(f"refusing promotion: {len(violations)} staged card(s) failed validation")
            for violation in violations:
                print(f"  {violation}")
            return 1

        promoted: set[tuple[str, str]] = set()
        try:
            for (key, pose), angle_paths in sorted(selected.items()):
                safe_key = _sanitize_scp_id(key)
                for angle, rel_path in angle_paths.items():
                    asset_service.add_asset(
                        f"{safe_key}/{pose}_{angle}", rel_path,
                        source={"type": "comfyui_generation", "story": "8.15"},
                        card_key=safe_key, pose=pose, angle=angle,
                    )
                    asset_service.approve_asset(f"{safe_key}/{pose}_{angle}")
                if pose == "standing":
                    # The only `angle_*_path` write in this script, and the only one in
                    # the repo behind a human gate. Non-standing poses live in
                    # `character_cards` and must not touch these columns — they ARE the
                    # standing card set.
                    service.update_character(
                        characters[key].id,
                        selected_image_path=angle_paths["front"],
                        **{f"angle_{angle}_path": path for angle, path in angle_paths.items()},
                    )
                    _retire_special_pose_cards(session, service, key)
                else:
                    for angle, rel_path in angle_paths.items():
                        card = service.save_card(key, pose, angle, rel_path)
                        # `save_card` stamps the CURRENT manifest epoch, and the bump that
                        # makes `epoch` current is deliberately the last thing this script
                        # does. Left alone the row would claim epoch_{epoch-1} while the
                        # file lives in epoch_{epoch}, and report_card_coverage.py would
                        # print the newest card in the library as off-epoch.
                        card.style_epoch = epoch
                        session.add(card)
                    session.commit()
                promoted.add((key, pose))
                print(f"promoted: {key} ({pose}) → epoch_{epoch}")
        finally:
            # The bump has to happen even when a target raised mid-loop, because the
            # earlier keys are ALREADY live: without it the staging slot is still the
            # directory they now live in, so the next `--stage` overwrites approved
            # pixels and a `--reject` deletes them — failure mode 3 in this module's
            # docstring, reached by the failure path instead of by design. The operator
            # is told exactly how far it got.
            if len(promoted) < len(selected):
                print(f"PARTIAL PROMOTION: {len(promoted)}/{len(selected)} (key, pose) set(s) "
                      f"went live before the failure: {sorted(promoted)}. The epoch is bumped "
                      "anyway so nothing can re-stage over them; the rest must be re-staged.")
            for key in sorted({key for key, _ in promoted}):
                directory = staged_dir(assets_root, key, epoch)
                (directory / PRESTAGE_DESCRIPTOR_FILE).unlink(missing_ok=True)
                (directory / POSTSTAGE_DESCRIPTOR_FILE).unlink(missing_ok=True)
            # Unconditional, and last. This is the boundary itself: it declares
            # epoch_{epoch} live and sends the next --stage somewhere else.
            print(f"style_epoch → {asset_service.bump_style_epoch()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Promote or reject staged character cards.")
    parser.add_argument(
        "--key",
        help="Narrow to one card key. A PROMOTION is refused if anything else is staged "
             "in the same epoch; a --reject is not.",
    )
    parser.add_argument(
        "--pose", choices=VALID_POSES,
        help="Narrow a promotion to one pose. Refused if anything else is staged in the "
             "same epoch. Ignored by --reject (one directory holds every pose).",
    )
    parser.add_argument(
        "--reject", action="store_true",
        help="Delete the staged cards; touch nothing live. Available even when a blocker "
             "refuses promotion — that is the recovery path for a crashed stage.",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return run(
        [args.key] if args.key else [],
        [args.pose] if args.pose else [],
        reject=args.reject,
    )


if __name__ == "__main__":
    raise SystemExit(main())
