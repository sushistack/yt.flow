#!/usr/bin/env python
"""Story 14.1 (axis replaced by 14.8): replay `image._select_plate` over a run's shots,
offline. GPU 0, VLM 0.

    uv run python .../replay_coverage.py 4b35c0ed

Every number in report.md §2/§3 comes out of here. It reads the run's shots from the
LangGraph checkpoint (loader shape copied from
`14-0-angle-conflict/measure_angle_agreement.py` — thread-prefix match, refuse an
ambiguous prefix) and the plate metadata from `plate_meta.json` + `assets/manifest.json`'s
`source.label` + the approved `location_plates` rows, assembles exactly the dicts
`LocationService.resolve_stock_plates` would hand `image_node` — folding both person
verdicts through the SHIPPED `_fold_verdict` — and calls the SHIPPED selector. Nothing is
re-implemented: if the selector changes, this number changes with it. That guarantee was
briefly FALSE (14.8 review): the matching axis had escaped `_select_plate` into this
file's `plates[key]` lookup, so a change to the axis would not have moved this number.
It is back inside the function; the lookup here is now the runtime's SHAPE, not the rule.

It does not render, does not call ComfyUI, does not touch the DB except read-only, and
does not care whether `stock_plate_substitution_enabled` is on — it answers "what WOULD
this run get", which is the flag's entry condition, not its current behaviour.

Exit codes:
    0  replayed at least one location-keyed shot
    2  usage error
    3  nothing to measure (no such run, empty `scenes`, ambiguous thread prefix)
    4  the retired-axis CONTROL no longer reproduces 14.1's committed verdict ON THE RUN
       AND INPUTS IT WAS TAKEN FROM — the before/after delta below it would be
       meaningless, so it is not printed as measured. Replaying any OTHER run, or this
       run with changed inputs (plates approved/re-labelled, the affordance knob raised),
       prints the control as SKIPPED and still exits 0: those are changed inputs, not a
       broken control, and conflating the two is a 14.8 review finding.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # noqa: E402

from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.state import LOCATION_KEYS  # noqa: E402
from yt_flow.pipeline.nodes.image import _ANGLE_VIEWPOINT, _select_plate  # noqa: E402
from yt_flow.services.location_service import _PERSON_VERDICTS, _fold_verdict  # noqa: E402

_EXIT_OK, _EXIT_USAGE, _EXIT_NOTHING, _EXIT_CONTROL = 0, 2, 3, 4


def _repo_path(path: str) -> Path:
    """Absolutise a `Settings` path against the REPO, not the cwd.

    `Settings.db_path` / `assets_path` are repo-relative strings. `db_path` was already
    joined to `REPO` while `assets_path` was not, so this script only worked from the repo
    root — a 14.8 review finding, and the kind of thing that makes a committed number
    unreproducible for the next reader.
    """
    p = Path(path)
    return p if p.is_absolute() else REPO / p

# Pre-registered bars. Copied here so the script prints its own verdict rather than
# leaving the reader to re-apply them by hand — NOT re-decided here.
#
# Story 14.8 replaced the MATCHING AXIS (`camera_angle` -> plate `viewpoint` is retired;
# the axis is `location_key` alone) and therefore re-cut C1/C2 into C1'/C2' over
# `location_key` cells, added C4' as a disclosure with no threshold, and left C3 and this
# constant untouched — `14-8-plate-reuse-shipping/PREREGISTRATION.md` §3. The servable
# denominator (24) and 0.90 are the ONLY fixed points that prove no bar was lowered, so
# they are byte-identical to 14.1's.
#
# ⚠️ ALL THREE of C1'/C2'/C3' are VACUOUS on today's corpus — they cannot fail — and the
# population sweep that establishes that is `PREREGISTRATION.md` §7, appended before this
# script was re-derived. A PASS printed below is therefore NOT evidence; it is the
# absence of a counter-example that could not have existed. Read C4' instead: it is the
# only line here that carries information about the axis change.
C3_MIN_SHARE = 0.90

# 14.1's committed verdict on ONE run over ONE snapshot of the corpus
# (`14-1-approved-plate-sets/report.md:227-244`), used to CHECK the retired-axis control
# below rather than trust it. A control that does not reproduce these is a broken control,
# and a broken control would hand the report a "17 -> 24" it did not earn.
#
# BOTH the run and its preconditions are pinned, because the expectation is coupled to
# inputs the expectation itself does not mention (14.8 review): approving the 5 draft
# plates, re-running `scripts/label_location_plates.py`, or raising
# `plate_affordance_gate_enabled` all move these numbers legitimately. Without the pins
# the script answers "control broken" to a question that was "inputs changed".
CONTROL_RUN = "4b35c0ed"
CONTROL_EXPECTED = {"c1_ok_cells": 5, "c1_cells": 10, "c2_pass": True,
                    "c3_hits": 17, "c3_servable": 24}
CONTROL_PRECONDITIONS = {"approved_plates": 42, "affordance_gate": False}


def load_scenes(db: Path, thread_prefix: str) -> tuple[str, list]:
    """The last checkpoint of the matching thread that carries a non-empty ``scenes``.

    Returns the FULL ``thread_id`` beside the scenes, not just the scenes. The selector's
    tie-break hashes ``run_id``, and ``run_id`` is that whole string — passing the CLI's
    convenience prefix (`4b35c0ed`) produces the right aggregate counts but a per-shot
    plate assignment that does not reproduce in the run being replayed, which is exactly
    the number a report names plates in.
    """
    if not db.exists():
        print(f"no checkpoint DB at {db}", file=sys.stderr)
        return "", []
    serde = JsonPlusSerializer()
    scenes: list = []
    threads: set[str] = set()
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        for thread_id, _cid, typ, blob in conn.execute(
            "SELECT thread_id, checkpoint_id, type, checkpoint FROM checkpoints "
            "WHERE thread_id LIKE ? ORDER BY checkpoint_id", (thread_prefix + "%",),
        ):
            threads.add(thread_id)
            try:
                found = (serde.loads_typed((typ, blob)).get("channel_values") or {}).get("scenes")
            except Exception:  # a partial/foreign blob is not this measurement's problem
                continue
            if found:
                scenes = found
    if len(threads) > 1:
        print(f"prefix {thread_prefix!r} matches {len(threads)} thread_ids — refusing to mix runs",
              file=sys.stderr)
        return "", []
    return (threads.pop() if threads else ""), scenes


def load_plates(settings: Settings) -> dict[str, list[dict]]:
    """``location_key -> [plate dicts]``, byte-shaped like ``resolve_stock_plates`` output.

    THE ASSEMBLY MUST MATCH THE RUNTIME'S, and until Story 14.8 it did not. This loader
    read `plate_meta.json` alone, where ``has_person`` is ABSENT in 42/42 rows, while
    `LocationService.resolve_stock_plates` folds ``has_person`` as
    ``label OR plate_meta`` (`location_service.py:105-112`). `entrance-checkpoint/b` —
    ``label.has_person=true``, ``status='approved'`` — was therefore people-free to this
    replay and person-bearing to the shipped selector. Today's demanded keys do not
    include it, so the two agreed BY LUCK on the numbers a report quoted; the C1' verdict
    is load-bearing, so luck is not good enough.

    The `source.label` half is read from the live manifest (the same file the runtime
    reads); the measurement half stays on the committed `plate_meta.json` snapshot, which
    is byte-equal to the manifest's `source.plate_meta` for all 42 rows and is the sample
    band this directory's reports cite.

    The fold itself is `location_service._fold_verdict`, IMPORTED, not re-expressed: it
    carries two rules a copy here would lose (an explicit `null` or a non-bool stays
    undecidable rather than reading as "no person") and it folds BOTH verdicts, which is
    the 14.8 review fix that lets a labelled-but-unmeasured plate be assignable at all.
    """
    meta = json.loads((HERE / "plate_meta.json").read_text(encoding="utf-8"))
    assets = _repo_path(settings.assets_path)
    try:
        manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))["assets"]
    except Exception as exc:  # noqa: BLE001
        # Fail open, exactly as `LocationService._manifest_assets` does — but LOUDLY,
        # because here the missing half is the labeler's verdicts and a silent `{}` would
        # quietly reproduce the pre-14.8 bug this loader's docstring is about.
        print(f"⚠️ manifest unreadable ({type(exc).__name__}: {exc}) — `source.label` half "
              f"of every plate is MISSING; person verdicts below are plate_meta only",
              file=sys.stderr)
        manifest = {}
    plates: dict[str, list[dict]] = defaultdict(list)
    with sqlite3.connect(f"file:{_repo_path(settings.db_path)}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT location_key, variant, image_path FROM location_plates "
            "WHERE status='approved' ORDER BY location_key, variant")
        for key, variant, image_path in rows:
            entry = f"{key}/{variant}"
            plate = dict(meta.get(entry, {}))
            label = ((manifest.get(entry) or {}).get("source") or {}).get("label")
            label = label if isinstance(label, dict) else {}
            for field in _PERSON_VERDICTS:
                verdict = _fold_verdict(label.get(field), plate.get(field))
                if verdict is None:
                    plate.pop(field, None)
                else:
                    plate[field] = verdict
            # `location_key` rides the plate because since 14.8's review it IS the axis and
            # `_select_plate` re-checks it on the pool it is handed. Keying this dict as
            # well is the runtime's shape (`resolve_stock_plates(key)`), not a second
            # expression of the rule.
            plates[key].append({**plate, "location_key": key, "variant": variant,
                                "path": str(assets / image_path)})
    return plates


def _people_free(plate: dict) -> bool:
    """The D1 predicate, in ONE place, in the SHIPPED convention.

    C1'/C2' below, the retired-axis control and `image._select_plate` have to exclude the
    same plates or the pre-registered coverage bars and the shipped runtime describe
    different sets. This duplication is the known synchronisation risk of this file
    (spec 14.8 §Boundaries), which is why the axis and these rules moved in ONE commit.

    ``is False`` on BOTH curators, not truthiness: Story 14.8 made D1's convention match
    D2's, so an ABSENT or null verdict is undecidable and undecidable is not people-free.
    A plate nobody judged is not a candidate at all — it is `no_metadata`.
    """
    return plate.get("has_person") is False and plate.get("depicts_person") is False


def main(run: str) -> int:
    # `_env_file` explicitly: `Settings.model_config` names a RELATIVE `.env`, so run from
    # anywhere but the repo root this script read a different (usually absent) env file
    # and died on the required keys. Same 14.8 review finding as `_repo_path` — a number
    # nobody else can re-derive is not a committed number.
    settings = Settings(_env_file=REPO / ".env")
    thread_id, scenes = load_scenes(_repo_path(settings.db_path), run)
    if not scenes:
        return _EXIT_NOTHING
    plates = load_plates(settings)
    # The shipped knob, printed, because it is an input to the replay: with the affordance
    # gate down `_select_plate` serves a measured-roomless plate to a cast shot on purpose
    # (D2 — 14.2's recovery path), so a reader has to know which side of that the numbers
    # were taken on.
    affordance_gate = settings.plate_affordance_gate_enabled
    print(f"thread_id {thread_id}  (plate_affordance_gate_enabled={affordance_gate})")

    shots = [(sc["scene_num"], s) for sc in scenes for s in sc["shots"]]
    keyed = [(n, s) for n, s in shots if s.get("location_key")]
    print(f"run {run}: {len(shots)} shots, {len(keyed)} carry a location_key, "
          f"{len(shots) - len(keyed)} do not")

    reasons: Counter[str] = Counter()
    picked: list[tuple[int, str, str, str, object, bool, object]] = []
    for scene_num, shot in keyed:
        key = shot["location_key"]
        pool = plates.get(key, [])
        plate, reason = _select_plate(shot, pool, thread_id, scene_num,
                                      affordance_gate=affordance_gate)
        # A key with no approved plate at all is `stock_plate_missing` at runtime, not a
        # selector reason — image_node never calls the selector in that case. Counting it
        # under whatever the selector happens to say about an empty list (`no_metadata`)
        # would make this table disagree with the warnings the run actually files.
        reasons["stock_plate_missing" if not pool else reason] += 1
        if plate is not None:
            # The viewpoint is kept RAW (`None` when the plate was never measured), not
            # `str()`-ed: C4' has to tell "unmeasured" from "measured and different", and
            # stringifying made every unmeasured plate read as a mismatch (14.8 review —
            # the sentinel moved off `viewpoint`, so an unmeasured plate is now legal in
            # the pool and this distinction became reachable).
            picked.append((scene_num, shot["shot_id"], f"{key}/{plate['variant']}",
                           plate.get("viewpoint"), plate.get("standing_room"),
                           bool(shot.get("cast")), shot.get("camera_angle")))

    print("\n-- selector outcome over the location-keyed shots --")
    for reason, n in reasons.most_common():
        print(f"  {reason:22s} {n}")

    servable = [(n, s) for n, s in keyed if _ANGLE_VIEWPOINT.get(s.get("camera_angle") or "")]
    hits = reasons["match"]
    share = hits / len(servable) if servable else 0.0
    print(f"\nservable shots (camera_angle maps to a viewpoint): {len(servable)}"
          f"  ->  match {hits} ({share:.1%})")
    roomless = sum(1 for *_h, room, cast, _a in picked if cast and room is not True)
    print(f"cast-bearing hits whose plate lacks standing_room=True: {roomless}"
          f"  (0 => the affordance knob does not change this replay)")

    # -- C1'/C2': demanded `location_key` cells (Story 14.8) -------------------------
    # The cell lost its `viewpoint` component with the axis. That is the ONLY change to
    # C1/C2; the predicates (`_people_free`, `standing_room is True`) are byte-identical
    # and shared with `_select_plate` through `_people_free` above.
    demand: dict[str, list] = defaultdict(list)
    for _scene_num, shot in servable:
        demand[shot["location_key"]].append(shot)

    print("\n-- demanded cells (C1'/C2': `location_key`, no viewpoint component) --")
    short_c1, short_c2 = [], []
    for key in sorted(demand):
        cast_shots = sum(1 for s in demand[key] if s.get("cast"))
        pool = [p for p in plates.get(key, []) if _people_free(p)]
        room = [p for p in pool if p.get("standing_room") is True]
        c1 = "OK " if pool else "MISS"
        c2 = "-   " if not cast_shots else ("OK " if room else "MISS")
        if not pool:
            short_c1.append(key)
        elif cast_shots and not room:
            short_c2.append(key)
        print(f"  {key:22s} shots={len(demand[key]):2d} cast={cast_shots:2d} "
              f"C1'={c1} ({len(pool)} plate(s))  C2'={c2} ({len(room)} with room)")

    print("\n-- pre-registered bars (14-8-plate-reuse-shipping/PREREGISTRATION.md §3) --")
    print("  ⚠️ ALL THREE ARE VACUOUS on today's corpus (population sweep, §7 of that file):")
    print("     no demanded key can lose its pool (1 person-flagged plate in 42, in a key")
    print("     nothing demands), so C1' cannot MISS, C3' follows from C1' algebraically,")
    print("     and C2' cannot change assignment while the affordance knob ships OFF.")
    print("     A PASS below is the absence of an impossible counter-example, not evidence.")
    print(f"  C1' key coverage       : {'PASS' if not short_c1 else 'FAIL'} "
          f"({len(demand) - len(short_c1)}/{len(demand)} keys)   [VACUOUS]")
    print(f"  C2' affordance coverage: {'PASS' if not short_c2 else 'FAIL'}   [VACUOUS]")
    print(f"  C3' servable share >= {C3_MIN_SHARE:.0%}: "
          f"{'PASS' if share >= C3_MIN_SHARE else 'FAIL'} ({hits}/{len(servable)} = {share:.1%})"
          "   [VACUOUS]")
    if short_c1 or short_c2:
        print("\n-- shortfall: what an expansion batch must render --")
        for key in short_c1:
            n = len(demand[key])
            cast = sum(1 for s in demand[key] if s.get("cast"))
            print(f"  {key}: 0 usable plates, {n} shot(s) demand it"
                  f"{', standing room required' if cast else ''} -> render >=1")
        for key in short_c2:
            print(f"  {key}: plates exist but none has standing room -> render >=1")

    # -- C4': the price of the new axis, disclosed with no threshold ------------------
    # PREREGISTRATION §3 makes printing this MANDATORY and deliberately sets no bar: the
    # question "is a high-angle card on an eye-level plate acceptable" is Jay's viewing
    # verdict, and C4's failure mode is the number being absent from the report. With
    # C1'/C2'/C3' all vacuous this is the only informative line in the block.
    print("\n-- C4' viewpoint mismatches among the hits (no threshold, disclosure only) --")
    # TWO LINES, not one (14.8 review). "Never measured" and "measured, and it is the
    # wrong one" are different findings with different actions — measure the plate vs.
    # accept the mismatch — and C4' is the only informative number this script prints, so
    # folding them together would corrupt the one line that carries information.
    unmeasured = [(sid, pk, ang) for _n, sid, pk, vp, _r, _c, ang in picked if vp is None]
    mismatched = [(sid, pk, vp, ang) for _n, sid, pk, vp, _r, _c, ang in picked
                  if vp is not None and vp != _ANGLE_VIEWPOINT.get(ang or "")]
    print(f"  {len(mismatched)}/{len(picked)} assigned plates sit at a MEASURED viewpoint "
          f"the shot's camera_angle did not ask for")
    for sid, plate_key, viewpoint, angle in mismatched:
        print(f"    {sid} camera_angle={angle} (wants {_ANGLE_VIEWPOINT.get(angle or '')}) "
              f"-> {plate_key} measured {viewpoint}")
    print(f"  {len(unmeasured)}/{len(picked)} assigned plates have NO viewpoint measurement "
          f"(legal in the pool since 14.8; not a mismatch, not a match)")
    for sid, plate_key, angle in unmeasured:
        print(f"    {sid} camera_angle={angle} -> {plate_key} unmeasured")

    # -- CONTROL: the retired 14.1 axis, same run, same plates ------------------------
    # NOT the shipped selector — `_select_plate` no longer has a viewpoint step, so the
    # only way to show before/after on one screen is to re-express the retired step here.
    # It is CHECKED, not trusted: on run 4b35c0ed it must reproduce `CONTROL_EXPECTED`,
    # the numbers 14.1 committed. A control that silently drifts would hand the report a
    # "17 -> 24" improvement it did not earn.
    old_hits = 0
    for _scene_num, shot in servable:
        viewpoint = _ANGLE_VIEWPOINT[shot["camera_angle"]]
        pool = [p for p in plates.get(shot["location_key"], [])
                if p.get("viewpoint") == viewpoint and _people_free(p)]
        if affordance_gate and shot.get("cast"):
            pool = [p for p in pool if p.get("standing_room") is True]
        old_hits += bool(pool)
    old_demand: dict[tuple[str, str], list] = defaultdict(list)
    for _scene_num, shot in servable:
        old_demand[(shot["location_key"], _ANGLE_VIEWPOINT[shot["camera_angle"]])].append(shot)
    old_c1 = [c for c in old_demand
              if not [p for p in plates.get(c[0], [])
                      if p.get("viewpoint") == c[1] and _people_free(p)]]
    old_c2 = [c for c in old_demand
              if c not in old_c1 and any(s.get("cast") for s in old_demand[c])
              and not [p for p in plates.get(c[0], [])
                       if p.get("viewpoint") == c[1] and _people_free(p)
                       and p.get("standing_room") is True]]
    old_share = old_hits / len(servable) if servable else 0.0
    print("\n-- CONTROL: retired 14.1 axis (camera_angle -> plate viewpoint), same inputs --")
    print(f"  C1  cell coverage      : {'PASS' if not old_c1 else 'FAIL'} "
          f"({len(old_demand) - len(old_c1)}/{len(old_demand)} cells)")
    print(f"  C2  affordance coverage: {'PASS' if not old_c2 else 'FAIL'}")
    print(f"  C3  servable share >= {C3_MIN_SHARE:.0%}: "
          f"{'PASS' if old_share >= C3_MIN_SHARE else 'FAIL'} "
          f"({old_hits}/{len(servable)} = {old_share:.1%})")
    got = {"c1_ok_cells": len(old_demand) - len(old_c1), "c1_cells": len(old_demand),
           "c2_pass": not old_c2, "c3_hits": old_hits, "c3_servable": len(servable)}
    # THREE outcomes, not two (14.8 review). `CONTROL_EXPECTED` is one run's verdict over
    # one corpus snapshot, and comparing it unconditionally made any other thread — or
    # this thread with legitimately changed inputs — exit 4 reporting a control that is
    # not broken. Say which of the two happened.
    inputs = {"approved_plates": sum(len(ps) for ps in plates.values()),
              "affordance_gate": affordance_gate}
    if not thread_id.startswith(CONTROL_RUN):
        checked = (f"SKIPPED — the expectation was taken on run {CONTROL_RUN}, this is "
                   f"{thread_id[:8]}. Not a broken control; nothing was checked.")
    elif inputs != CONTROL_PRECONDITIONS:
        checked = (f"SKIPPED — INPUTS CHANGED, not a broken control: expected "
                   f"{CONTROL_PRECONDITIONS}, got {inputs}. Approving or re-labelling "
                   f"plates, or raising the affordance knob, moves these numbers "
                   f"legitimately; re-take the expectation, do not debug the control.")
    elif got != CONTROL_EXPECTED:
        # Loud and non-zero: a broken control must not be quoted as a baseline. Reached
        # only when the run AND its preconditions are the ones the expectation was taken
        # on, so "the control drifted" is the only remaining explanation.
        print(f"  ⚠️ CONTROL BROKEN — same run, same inputs {inputs}; "
              f"expected {CONTROL_EXPECTED}, got {got}", file=sys.stderr)
        print("     Refusing to present the axis-change delta below as measured.",
              file=sys.stderr)
        return _EXIT_CONTROL
    else:
        checked = f"VALID — reproduces {CONTROL_EXPECTED} with preconditions {inputs}"
    print(f"  control check: {checked}")
    # The shots the retired axis REFUSED, listed rather than counted: they are the whole
    # of the difference between the two axes on this run, and C4' above is their image.
    old_rejected = [(s["shot_id"], s["location_key"], s["camera_angle"], len(s.get("cast") or []))
                    for _n, s in servable
                    if not [p for p in plates.get(s["location_key"], [])
                            if p.get("viewpoint") == _ANGLE_VIEWPOINT[s["camera_angle"]]
                            and _people_free(p)]]
    print(f"  shots the retired axis rejected as `no_viewpoint_match`: {len(old_rejected)}")
    for shot_id, key, angle, cast_n in old_rejected:
        print(f"    {shot_id} {key} camera_angle={angle} cast={cast_n}")
    print(f"  axis change: servable match {old_hits} -> {hits} "
          f"({old_share:.1%} -> {share:.1%}), C4' cost {len(mismatched)} mismatched + "
          f"{len(unmeasured)} unmeasured hit(s)"
          f"{'' if checked.startswith('VALID') else '  [CONTROL UNCHECKED]'}")

    # -- the shots a plate can never reach -------------------------------------------
    # Is `location_key = None` a VOCABULARY gap (the room is not in LOCATION_KEYS) or an
    # EMISSION gap (the writer described a room that IS in the vocabulary and left the
    # field empty)? The two need different fixes and only one of them is 14.1-adjacent.
    unkeyed = [(n, s) for n, s in shots if not s.get("location_key")]
    # Per SHOT: a prompt naming two rooms ("from the corridor into the control room") used
    # to contribute two rows to a numerator whose denominator counts shots, so the ratio
    # could exceed 1. The shot is the unit here, and the keys it names are its detail.
    named = {s["shot_id"]: [k for k in LOCATION_KEYS if k.replace("-", " ") in s["image_prompt"].lower()]
             for _n, s in unkeyed}
    named = {sid: keys for sid, keys in named.items() if keys}
    print(f"\n-- the {len(unkeyed)} shots with no location_key --")
    print(f"  {len(named)}/{len(unkeyed)} name a LOCATION_KEYS room in image_prompt anyway "
          f"-> emission gap, not vocabulary gap")
    for shot_id, keys in named.items():
        print(f"    {shot_id} -> {', '.join(keys)}")

    # -- declared VARIANT_CAMERAS vs measured viewpoint -------------------------------
    # Evidence about whether the plates' ControlNet geometry control actually delivered the
    # camera the prompt asked for. NEVER a correction to the labels: the labels were fixed
    # in viewpoint_verdicts.csv before this table was computed (PREREGISTRATION.md §2).
    meta = json.loads((HERE / "plate_meta.json").read_text(encoding="utf-8"))
    declared = {"a": "EYE", "b": "LOW", "c": None}  # c declares framing, not a viewpoint
    print("\n-- declared variant camera vs measured viewpoint --")
    for variant, want in declared.items():
        got = Counter(m["viewpoint"] for k, m in meta.items() if k.endswith(f"/{variant}"))
        agree = f"{got[want]}/{sum(got.values())}" if want else "n/a (no viewpoint declared)"
        print(f"  {variant}: declared {want or 'off-axis framing':16s} measured {dict(got)}"
              f"  agreement {agree}")

    print("\n-- matched shots --")
    for scene_num, shot_id, plate_key, viewpoint, room, cast, angle in picked:
        print(f"  scene {scene_num} {shot_id} -> {plate_key} ({viewpoint}, "
              f"standing_room={room}, cast={cast}, camera_angle={angle})")
    return _EXIT_OK


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(_EXIT_USAGE)
    raise SystemExit(main(sys.argv[1]))
