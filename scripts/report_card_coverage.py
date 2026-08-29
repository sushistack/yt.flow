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

Story 14.6 EXTENDED this reporter rather than adding a second one. Two reporters over
one population diverge — `Settings.style_epoch` and the manifest's `style_epoch` are
spelled the same and disagree live, and that is exactly what misled a second script
before (deferred-work.md:725-727). Three axes were added, and both of the
population-wide ones sweep the WHOLE library, not a convenient subset:

  * sprite contract — every tier-A path AND every card entry in the manifest;
  * prompt provenance — `character-generation` v5 went live 2026-08-16, so entries
    are bucketed pre-v5 / same-day / post-v5 against `created_at`. Seeding carries no
    timestamp, so `same-day` is NOT attributable and is never counted as regenerated;
  * registry reconciliation — over all 52 card manifest entries, not the 20
    `character_cards` rows. A `character_cards`-only sweep sees no `standing` row at
    all, which is 32 of the 52 entries, and the most dangerous shape of all (manifest
    `retired` while `angle_*_path` still publishes the file) would not even print.

`--demand <run-id>` reads a run's checkpoint and reports the demand that run actually
placed, kept separate from the full-vocabulary denominator above. `served` is judged
against the sprite contract and file existence, never against a non-empty column: an
RGB card is a run-killer at `video.py:2537`, and calling it "served" is the inversion
this axis exists to correct.

Usage:
    uv run python scripts/report_card_coverage.py
    uv run python scripts/report_card_coverage.py --probe
    uv run python scripts/report_card_coverage.py --demand 4b35c0ed
"""

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.db.models import Character, CharacterCard  # noqa: E402
from yt_flow.domain.png import (  # noqa: E402
    _MIN_TRANSPARENT_FRACTION,
    alpha_profile,
    sprite_contract,
)
from yt_flow.services.character_service import (  # noqa: E402
    CANONICAL_ANGLES,
    _ANGLE_FIELD_NAMES,
    _normalize_pose,
    CharacterService,
    pose_hint_key,
)

# `character-generation` v5 was seeded to Langfuse on this date (Story 10.8). Anything
# generated before it carries the weak prompt; anything after carries v5. Entries
# stamped ON that date are unattributable — prompt seeding writes no timestamp, so the
# card may have been rendered either side of the seed — and this report refuses to
# count them as regenerated.
_V5_LIVE_DATE = "2026-08-16"

# The lower edge of the front-only 6-card band an early draft of Story 14.6 mistook for
# the population band. Kept only so the sweep below can PRINT what fitting the contract
# floor to it would have cost — it is not a threshold anything enforces.
_FRONT_ONLY_BAND_FLOOR = 0.7055

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


def _card_entries(manifest: dict) -> dict[str, dict]:
    """The manifest's CARD entries. Kinds are inferred, not declared.

    ``AssetService`` has no ``kind`` field — a card is an entry carrying ``card_key``,
    a plate one carrying ``location_key``, a guide one under the ``pose_guide/``
    prefix. That absence is also why Story 14.6 refused to build an object library:
    there is no fourth kind to declare.
    """
    return {key: entry for key, entry in manifest["assets"].items() if "card_key" in entry}


def _contract_row(abs_path: Path) -> tuple[bool, str, dict]:
    """``(passes, reason, profile)`` for one card file. A missing file is its own reason."""
    if not abs_path.is_file():
        return False, "file_missing", {}
    data = abs_path.read_bytes()
    passes, reason = sprite_contract(data)
    return passes, reason, alpha_profile(data) or {}


def _report_contract(service: CharacterService, characters, manifest: dict) -> dict[str, tuple[bool, str]]:
    """Sweep the sprite contract over the WHOLE card population and print the failures.

    Population = every tier-A ``angle_*_path`` + every card entry in the manifest. Both
    halves are needed: tier A is the only place a `standing` card is addressable from
    the DB, and the manifest is the only place a card the DB no longer points at is
    still recorded. Keyed by RESOLVED path so a file reached both ways is one row, and
    returned so the demand axis consults these verdicts instead of re-deriving them.
    """
    root = Path(service._settings.assets_path)
    targets: dict[str, str] = {}  # resolved abs path -> label
    for character in characters:
        for angle in CANONICAL_ANGLES:
            path = getattr(character, _ANGLE_FIELD_NAMES[angle])
            if path:
                key = str(Path(service._abs_asset_path(path)).resolve())
                targets.setdefault(key, f"{character.scp_id} standing/{angle} [tier A]")
    entries = _card_entries(manifest)
    for key, entry in sorted(entries.items()):
        targets.setdefault(str((root / entry["path"]).resolve()), f"{key} [{entry['status']}]")

    verdicts: dict[str, tuple[bool, str]] = {}
    failures: list[str] = []
    fractions: list[float] = []
    below_front_band: list[tuple[str, float]] = []
    for abs_path, label in sorted(targets.items(), key=lambda kv: kv[1]):
        passes, reason, profile = _contract_row(Path(abs_path))
        verdicts[abs_path] = (passes, reason)
        if passes:
            fractions.append(profile["transparent_fraction"])
            if profile["transparent_fraction"] < _FRONT_ONLY_BAND_FLOOR:
                below_front_band.append((label, profile["transparent_fraction"]))
            continue
        failures.append(
            f"  {label:<44} {reason:<18} "
            f"canvas={profile.get('canvas_w')}x{profile.get('canvas_h')} "
            f"aspect={_fmt(profile.get('canvas_aspect'))} "
            f"transparent_fraction={_fmt(profile.get('transparent_fraction'))} "
            f"bbox={profile.get('alpha_bbox')}"
        )
    print(f"\n-- SPRITE CONTRACT over {len(targets)} distinct card file(s) "
          f"(tier A paths + {len(entries)} manifest card entries) --")
    print(f"  PASS {len(targets) - len(failures)}  FAIL {len(failures)}")
    for line in failures:
        print(line)
    if fractions:
        # The band the `_MIN_TRANSPARENT_FRACTION` comment cites, re-derived here so the
        # constant is auditable from a command instead of from a claim
        # (`gotcha_a-measurement-without-its-sample-band`).
        print(f"  observed transparent_fraction band over the passing population: "
              f"{min(fractions):.4f} … {max(fractions):.4f} "
              f"(floor in force: {_MIN_TRANSPARENT_FRACTION})")
        # The counterfactual the story argues from, printed rather than asserted. An
        # earlier draft of Story 14.6 quoted the front-only 6-card band and put the
        # number of casualties at 14 by hand; it is 18, and four of them are `standing`
        # cards, so "sitting and hint cards first" understated the class as well as the
        # count. Anything the prose claims here has to be re-derivable from this command.
        casualties = sorted(f for f in fractions if f < _FRONT_ONLY_BAND_FLOOR)
        print(f"  counterfactual: a floor fitted to the front-only band "
              f"({_FRONT_ONLY_BAND_FLOOR}) would reject {len(casualties)} of "
              f"{len(fractions)} passing card(s), spanning "
              + (f"{casualties[0]:.4f} … {casualties[-1]:.4f}" if casualties else "nothing"))
        for label, fraction in sorted(below_front_band, key=lambda kv: kv[1]):
            print(f"    {fraction:.4f}  {label}")
    return verdicts


def _fmt(value) -> str:
    return "None" if value is None else f"{value:.4f}"


def _report_provenance(manifest: dict) -> None:
    """Which prompt generation each card came from, by `created_at` against v5's date."""
    buckets: dict[str, list[str]] = {"pre-v5": [], "same-day": [], "post-v5": [], "unknown": []}
    for key, entry in sorted(_card_entries(manifest).items()):
        day = (entry.get("created_at") or "")[:10]
        # An entry with no `created_at` has no provenance evidence at all. Bucketed
        # separately because `"" < "2026-08-16"` is True: without this it landed in
        # `pre-v5`, which is never listed, so it inflated the headline "45 pre-v5" and
        # was invisible in the same breath.
        if not day:
            bucket = "unknown"
        elif day < _V5_LIVE_DATE:
            bucket = "pre-v5"
        elif day == _V5_LIVE_DATE:
            bucket = "same-day"
        else:
            bucket = "post-v5"
        buckets[bucket].append(f"{key} ({day or 'no created_at'})")
    print(f"\n-- PROMPT PROVENANCE (character-generation v5 live {_V5_LIVE_DATE}) --")
    for bucket in ("pre-v5", "same-day", "post-v5", "unknown"):
        print(f"  {bucket:<10} {len(buckets[bucket]):>3}")
    print("  `same-day` is NOT counted as regenerated: prompt seeding writes no timestamp,")
    print("  so a card stamped that day may have been rendered on either side of the seed.")
    print("  `unknown` = no `created_at` at all: not evidence of anything, and NOT pre-v5.")
    for bucket in ("same-day", "post-v5", "unknown"):
        for line in buckets[bucket]:
            print(f"    {bucket}: {line}")


def _report_reconciliation(service: CharacterService, characters, cards, manifest: dict) -> None:
    """Manifest status vs what the DB actually publishes — over all 52 card entries.

    Directions are printed separately because they are not equally serious.
    `manifest approved / db retired` is a bookkeeping lag Story 10.8 already adjudicated;
    `db approved / manifest retired` is an approval-direction drift this story is not
    entitled to decide and HALTs the reconciler. `manifest retired / still published in
    angle_*_path` is the tier-A shape that a `character_cards`-only sweep cannot see at
    all — 32 of the 52 entries are standing and have no row to compare against.
    """
    root = Path(service._settings.assets_path)
    by_row = {(c.scp_id, c.pose, c.angle): c for c in cards}
    published = {
        str((root / getattr(character, _ANGLE_FIELD_NAMES[angle])).resolve())
        for character in characters for angle in CANONICAL_ANGLES
        if getattr(character, _ANGLE_FIELD_NAMES[angle])
    }
    forward: list[str] = []     # manifest approved / db retired
    reverse: list[str] = []     # db approved / manifest retired  -> HALT for the reconciler
    published_retired: list[str] = []
    no_counterpart: list[str] = []
    other_mismatch: list[str] = []   # every remaining disagreement, `draft` included
    entries = _card_entries(manifest)
    for key, entry in sorted(entries.items()):
        pose, angle = entry.get("pose"), entry.get("angle")
        # The manifest key is `{_sanitize_scp_id(scp_id)}/{pose}_{angle}` while the row is
        # keyed on the raw `scp_id`. Identical for every live key (none contains a path
        # separator), and `entry["card_key"]` is the sanitized half either way — so a key
        # that ever needed sanitizing would show up as a "no counterpart" row rather than
        # being silently matched to the wrong character.
        row = by_row.get((key.split("/", 1)[0], pose, angle))
        is_published = str((root / entry["path"]).resolve()) in published
        if pose == "standing":
            if entry["status"] == "retired" and is_published:
                published_retired.append(f"{key} — manifest retired, still in angle_{angle}_path")
            continue
        if row is None:
            no_counterpart.append(f"{key} — manifest {entry['status']}, no `character_cards` row")
        elif entry["status"] == "approved" and row.status == "retired":
            forward.append(f"{key} — manifest approved / db retired")
        elif entry["status"] == "retired" and row.status == "approved":
            reverse.append(f"{key} — db approved / manifest retired")
        elif entry["status"] != row.status:
            # The catch-all, because two named directions are not a class sweep. The
            # concrete gap it closes: manifest `draft` against an `approved` row — a card
            # the runtime publishes whose manifest entry was never approved, which
            # matched neither named bucket and so printed nowhere at all.
            other_mismatch.append(f"{key} — manifest {entry['status']} / db {row.status}")
    orphan_rows = [
        f"{c.scp_id} {c.pose}/{c.angle} ({c.status}) — no manifest entry"
        for c in sorted(cards, key=lambda c: (c.scp_id, c.pose, c.angle))
        if f"{c.scp_id}/{c.pose}_{c.angle}" not in entries
    ]
    print(f"\n-- REGISTRY RECONCILIATION over {len(entries)} manifest card entries "
          f"({sum(1 for e in entries.values() if e.get('pose') == 'standing')} standing / "
          f"{len(cards)} `character_cards` rows) --")
    for label, rows in (
        ("manifest approved / db retired", forward),
        ("db approved / manifest retired (HALTs reconcile_manifest.py)", reverse),
        ("manifest retired / still published in angle_*_path", published_retired),
        ("manifest entry with no `character_cards` row", no_counterpart),
        ("`character_cards` row with no manifest entry", orphan_rows),
        ("other manifest/db status mismatch (e.g. manifest draft / db approved)", other_mismatch),
    ):
        print(f"  {label}: {len(rows)}")
        for row in rows:
            print(f"    {row}")


def _load_checkpoint(db_path: Path, run_prefix: str) -> tuple[list, list, str]:
    """``(scenes, run_warnings, thread_id)`` from the last checkpoint carrying scenes.

    Same shape as ``14-0-angle-conflict/measure_angle_agreement.load_scenes``, with two
    deliberate differences this story's spec asks for:

    * a deserialization failure is **re-raised**, not skipped. That precedent measures a
      distribution and can afford to drop a blob; this one sizes a regeneration batch,
      and a silently skipped checkpoint understates demand — which is the direction that
      lets a defect through.
    * an ambiguous prefix is refused rather than mixed, and a missing DB or table is
      reported as a reason instead of a traceback.
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    if not db_path.exists():
        raise SystemExit(f"no checkpoint DB at {db_path} — run this from a checkout that has the run's DB")
    serde = JsonPlusSerializer()
    scenes: list = []
    warnings: list = []
    thread = ""
    threads: set[str] = set()
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        try:
            rows = list(conn.execute(
                "SELECT thread_id, checkpoint_id, type, checkpoint FROM checkpoints "
                "WHERE thread_id LIKE ? ORDER BY checkpoint_id",
                (run_prefix + "%",),
            ))
        except sqlite3.OperationalError as exc:
            raise SystemExit(f"cannot read checkpoints from {db_path}: {exc}") from exc
    for thread_id, checkpoint_id, typ, blob in rows:
        threads.add(thread_id)
        try:
            values = serde.loads_typed((typ, blob)).get("channel_values") or {}
        except Exception as exc:
            raise SystemExit(
                f"checkpoint {thread_id}/{checkpoint_id} did not deserialize ({type(exc).__name__}: {exc}); "
                "refusing to size a batch from a partial read"
            ) from exc
        if values.get("scenes"):
            scenes, thread = values["scenes"], thread_id
        if values.get("run_warnings"):
            warnings = values["run_warnings"]
    if len(threads) > 1:
        raise SystemExit(
            f"prefix {run_prefix!r} matches {len(threads)} thread_ids "
            f"({', '.join(sorted(threads)[:3])}, …) — refusing to mix runs"
        )
    if not scenes:
        raise SystemExit(f"no checkpoint under prefix {run_prefix!r} carries a non-empty `scenes`")
    return scenes, warnings, thread


def _verdict(verdicts: dict[str, tuple[bool, str]], abs_path: str) -> tuple[bool, str]:
    """The contract verdict the sweep above already computed, or compute it now.

    The miss is real rather than theoretical: a card row can point outside the swept
    population (a retired row whose manifest entry was removed). Not a `dict.get`
    default — that would re-read the file on every hit.
    """
    if abs_path in verdicts:
        return verdicts[abs_path]
    passes, reason, _ = _contract_row(Path(abs_path))
    return passes, reason


def _served(
    service: CharacterService, verdicts: dict[str, tuple[bool, str]],
    character, cards_by_slot: dict, card_key: str, pose: str,
) -> tuple[bool, str]:
    """Can the library serve this (key, pose) for EVERY angle? ``(served, reason)``.

    Every angle, not any: the angle is picked by an LLM at video time from the key's own
    catalogue, so a pose that is complete for two angles out of four is a coin flip that
    surfaces later as `cast_card_fallback`. And "there is a row / the column is not
    empty" is NOT the question — the file has to exist and pass the sprite contract,
    because an RGB card raises at `video.py:2537` and kills the run. Counting SCP-682 as
    "served" is precisely the inversion this axis exists to correct.
    """
    if pose.startswith("hint:"):
        card = cards_by_slot.get((card_key, pose, "front"))
        if card is None:
            return False, "no approved hint card"
        abs_path = str(Path(service._abs_asset_path(card.image_path)).resolve())
        passes, reason = _verdict(verdicts, abs_path)
        return (True, "ok") if passes else (False, f"hint card {reason}")
    # `resolve_cast_cards` runs every non-hint pose through `_normalize_pose` before it
    # looks anything up, so an off-vocabulary or missing `pose` is served by the STANDING
    # set at runtime. Reading the raw value here reported UNMET for a placement the
    # library actually covers, which is the same class of inversion as calling an RGB
    # card "served" — in the other direction.
    pose = _normalize_pose(pose)
    misses: list[str] = []
    for angle in CANONICAL_ANGLES:
        if pose == "standing":
            path = getattr(character, _ANGLE_FIELD_NAMES[angle]) if character else None
            if not path:
                misses.append(f"{angle}: no angle_{angle}_path")
                continue
            abs_path = str(Path(service._abs_asset_path(path)).resolve())
        else:
            card = cards_by_slot.get((card_key, pose, angle))
            if card is None:
                misses.append(f"{angle}: no approved row")
                continue
            abs_path = str(Path(service._abs_asset_path(card.image_path)).resolve())
        passes, reason = _verdict(verdicts, abs_path)
        if not passes:
            misses.append(f"{angle}: {reason}")
    return (not misses), "; ".join(misses) or "ok"


def _report_demand(
    service: CharacterService, verdicts: dict[str, tuple[bool, str]], characters, cards, run_prefix: str,
) -> None:
    """The demand one run actually placed, kept apart from the vocabulary denominator."""
    settings = service._settings
    scenes, run_warnings, thread = _load_checkpoint(Path(settings.db_path), run_prefix)
    by_scp = {c.scp_id: c for c in characters}
    approved = {(c.scp_id, c.pose, c.angle): c for c in cards if c.status == "approved"}

    placements: list[tuple[int, str, str, str, str | None, str | None]] = []
    for scene in sorted(scenes, key=lambda s: s["scene_num"]):
        for shot in scene.get("shots", []):
            for member in (shot.get("cast") or []):
                if not isinstance(member, dict) or not member.get("card_key"):
                    continue
                hint = member.get("pose_hint")
                hint = hint.strip() if isinstance(hint, str) and hint.strip() else None
                placements.append((
                    scene["scene_num"], shot["shot_id"], member["card_key"],
                    member.get("pose") or "standing", hint, member.get("pose_guide_key"),
                ))

    # Keyed on (shot_id, card_key), never shot_id alone: 8 shots of run 4b35c0ed place
    # more than one cast member, so a shot-keyed map would let one row's warning stand in
    # for the other's and silently drop the second.
    warned = {
        (str((w.get("context") or {}).get("shot_id")), str((w.get("context") or {}).get("card_key"))): w
        for w in run_warnings if w.get("code") == "cast_card_fallback"
    }
    print(f"\n-- OBSERVED DEMAND, run {run_prefix} (thread {thread}) --")
    print(f"  {len(placements)} placement(s) across {len(scenes)} scene(s). This is what the run ASKED FOR;")
    print("  it is NOT the full-vocabulary denominator printed above and must not be read against it.")
    print(f"\n  {'scene':<6} {'shot':<8} {'card_key':<18} {'pose':<9} {'hint':<18} {'guide':<26} served")
    unmet: list[tuple[str, str, str]] = []
    for scene_num, shot_id, card_key, pose, hint, guide in placements:
        slot = pose_hint_key(hint) if hint else pose
        served, reason = _served(service, verdicts, by_scp.get(card_key), approved, card_key, slot)
        if not served:
            unmet.append((shot_id, card_key, reason))
        print(f"  {scene_num:<6} {shot_id:<8} {card_key:<18} {pose:<9} "
              f"{(pose_hint_key(hint) if hint else '-'):<18} {str(guide or '-'):<26} "
              f"{'yes' if served else 'NO — ' + reason}")

    print(f"\n  UNMET {len(unmet)} of {len(placements)} placement(s), "
          f"against {len(warned)} `cast_card_fallback` warning(s) in the same checkpoint:")
    for shot_id, card_key, reason in unmet:
        warning = warned.get((shot_id, card_key))
        matched = (f"cast_card_fallback reason={(warning.get('context') or {}).get('fallback_reason')}"
                   if warning else "NO matching warning")
        print(f"    {shot_id:<8} {card_key:<18} {reason:<40} {matched}")
    unexplained = sorted(set(warned) - {(s, k) for s, k, _ in unmet})
    print(f"  warnings with no unmet placement: {len(unexplained)}"
          + ("".join(f"\n    {s} {k}" for s, k in unexplained) if unexplained else ""))


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true",
                    help="run the resolver cross-check (spends one LLM call per card_key)")
    ap.add_argument("--demand", metavar="RUN_ID",
                    help="also report the demand one run actually placed (checkpoint read, no LLM call)")
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
            if args.demand:
                # `--demand` reads a CHECKPOINT, not the library, and an empty library is
                # exactly when someone asks what a run wanted. Returning here printed
                # nothing and exited 0, which reads as "no unmet demand" — the opposite
                # of the truth, where every placement is unmet.
                _report_demand(service, {}, characters, cards, args.demand)
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
        #
        # The current epoch is the MANIFEST's, read through AssetService — not
        # `Settings.style_epoch`. There are two fields spelled the same and they
        # disagree live (config default 1, manifest 2); `save_card` stamps the manifest
        # one, so comparing against the config field flagged every correctly-stamped
        # card as off-epoch and cleared the genuinely stale ones. `Settings.style_epoch`
        # has no other reader in the repo — see deferred-work.md.
        off_epoch: list[tuple[str, str, str, int]] = []
        current_epoch = service._asset_service.style_epoch
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
                        elif present and card.style_epoch != current_epoch:
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
            if c.status == "approved" and c.style_epoch != current_epoch
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
              f"{current_epoch} — the fill has to match, AC7):")
        for key, pose, angle, epoch in off_epoch:
            print(f"  {key:<18} {pose}/{angle} at epoch {epoch}")

        manifest = service._asset_service.load_manifest()
        verdicts = _report_contract(service, characters, manifest)
        _report_provenance(manifest)
        _report_reconciliation(service, characters, cards, manifest)
        if args.demand:
            _report_demand(service, verdicts, characters, cards, args.demand)

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
