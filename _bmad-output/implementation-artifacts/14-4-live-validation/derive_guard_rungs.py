#!/usr/bin/env python
"""Story 14.4: which rung of the guard's seed ladder did each shot of a run land on?

Spec: ``_bmad-output/implementation-artifacts/spec-14-4-people-free-background-default.md``

The flip of ``background_person_guard_attempts`` 0 -> 2 rests on one live number —
how many shots actually needed a bumped rung, and how deep. That number must be
re-derivable without the render (`gotcha_a-measurement-without-its-sample-band`),
so this reads it back out of the run's own resume sidecars:

    accepted rung == index of sidecar["seed"] in image._seed_ladder(run, scene, shot)

which works because ``_seed_ladder`` is a pure function of (run_id, scene_num,
shot_id) and the sidecar records the seed the guard accepted. No GPU, no network,
no ComfyUI, no re-run.

WHAT IT REFUSES TO DO: report numbers when the workspace is absent, or when nothing
in it is a sidecar this derivation can read. A tally over zero shots is not a clean
sweep, and an "0 exhausted" printed from an empty directory is exactly the kind of
vacuous green this repo has been bitten by
(`gotcha_gitignored-file-makes-git-status-vacuous`). Exit 3 says nothing was
measured; exit 1 says a sidecar seed is on no rung of its own ladder, which
would falsify the derivation itself rather than the story.

It also refuses to count what the guard never looked at. Copied stock plates are
written with rung 0's seed and skip the detector entirely, so they are excluded and
reported rather than tallied as "cleared first try" — 0 shots today
(`stock_plate_substitution_enabled` is False) and the reason this exclusion exists
is that 14.1 turning plates on is the epic's stated direction. Unreadable and
pre-11.1 seedless sidecars are excluded and counted the same way.

    uv run python .../derive_guard_rungs.py                   # the story's run
    uv run python .../derive_guard_rungs.py <run_id> [--workspace ./workspace]
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from yt_flow.config import BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS  # noqa: E402
from yt_flow.pipeline.nodes.image import _seed_ladder  # noqa: E402

# The run Jay viewed as E2E iteration 4 (SCP-049, 3:20), rendered with the guard
# pinned at 2 through `.env` — the pin Story 14.4 promotes into the code default.
DEFAULT_RUN = "4b35c0ed-8a1e-4448-8594-11bd9997376d"

_SIDECAR = re.compile(r"^scene_(\d+)_(.+)_done\.json$")

_EXIT_OK, _EXIT_OFF_LADDER, _EXIT_USAGE, _EXIT_NOTHING = 0, 1, 2, 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id", nargs="?", default=DEFAULT_RUN)
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    args = parser.parse_args()

    images = args.workspace / args.run_id / "images"
    sidecars = sorted(images.glob("*_done.json")) if images.is_dir() else []
    if not sidecars:
        print(f"nothing to measure: no sidecars under {images} — this run's workspace is "
              "not on this machine, and a tally over zero shots is not evidence",
              file=sys.stderr)
        return _EXIT_NOTHING

    # SAMPLE BAND, printed before any tally so a pasted number can never travel
    # without the population it was read off.
    print(f"sample band: thread id (run_id) {args.run_id}")
    print(f"             sidecar dir        {images.resolve()}")
    print(f"             sidecars read      {len(sidecars)}")
    print(f"             ladder length      {BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS + 1} "
          f"rungs (MAX_ATTEMPTS + 1, fixed regardless of the run's knob)")

    rungs: Counter[int] = Counter()
    off_ladder: list[str] = []
    exhausted: list[str] = []
    undecidable: list[str] = []
    bumped: list[tuple[str, int]] = []
    unreadable: list[str] = []
    seedless: list[str] = []
    stock_plate: list[str] = []
    for path in sidecars:
        matched = _SIDECAR.match(path.name)
        if matched is None:  # not a shot sidecar; the dir is not ours to police
            continue
        scene_num, shot_id = int(matched.group(1)), matched.group(2)
        try:
            sidecar = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A run killed mid-write leaves a truncated sidecar; `image_node` tolerates
            # those, so a measurement script that dies on one is stricter than the code
            # it is measuring. Counted separately — it is missing data, not a bad rung.
            unreadable.append(path.name)
            continue
        if not isinstance(sidecar, dict):
            unreadable.append(path.name)
            continue
        ladder = _seed_ladder(args.run_id, scene_num, shot_id)
        seed = sidecar.get("seed")
        if seed is None:
            # Pre-11.1 sidecar. `_existing_complete_shot` treats it as stale and
            # regenerates, i.e. a documented cache-invalidation case — NOT the
            # off-ladder condition, which claims the derivation is wrong.
            seedless.append(shot_id)
            continue
        if sidecar.get("provenance", {}).get("stock_plate") is not None:
            # A copied stock plate is written with `seeds[0]` and never put to the
            # detector (`image.py`: the guard is skipped on that path). Counting it as
            # "rung 0" would read as "the guard cleared it first try". With
            # `stock_plate_substitution_enabled` False this is 0 shots today, but 14.1
            # turning plates on is the epic's stated direction.
            stock_plate.append(shot_id)
            continue
        if seed not in ladder:
            off_ladder.append(f"{shot_id} (seed {seed})")
            continue
        rung = ladder.index(seed)
        rungs[rung] += 1
        if rung:
            bumped.append((shot_id, rung))
        if sidecar.get("guard_exhausted"):
            exhausted.append(shot_id)
        if sidecar.get("guard_undecidable"):
            undecidable.append(shot_id)

    total = sum(rungs.values())
    if total == 0:
        print(f"nothing to measure: {len(sidecars)} file(s) under {images} but none is a "
              "generated-shot sidecar this derivation can read "
              f"(unreadable {len(unreadable)}, seedless {len(seedless)}, "
              f"stock plates {len(stock_plate)}, off-ladder {len(off_ladder)})",
              file=sys.stderr)
        return _EXIT_NOTHING

    print(f"\nshots: {total}")
    for rung in range(BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS + 1):
        print(f"  rung {rung}: {rungs[rung]}")
    print(f"  exhausted (guard KNEW it was populated and kept it): {len(exhausted)}"
          + (f" {sorted(exhausted)}" if exhausted else ""))
    print(f"  undecidable (detector could not judge it): {len(undecidable)}"
          + (f" {sorted(undecidable)}" if undecidable else ""))
    print(f"  seeds on no rung of their own ladder: {len(off_ladder)}"
          + (f" {off_ladder}" if off_ladder else ""))
    print(f"  excluded — copied stock plates, never screened: {len(stock_plate)}"
          + (f" {sorted(stock_plate)}" if stock_plate else ""))
    print(f"  excluded — unreadable {len(unreadable)}, pre-11.1 seedless {len(seedless)}")
    print(f"\nshots the guard regenerated: {sorted(bumped)}")
    if exhausted:
        print(f"\nWhat this says about the flip: NO budget covered every hit in this run — "
              f"{len(exhausted)} shot(s) exhausted the ladder and shipped a frame the guard "
              "knew was populated. The bumped-rung tally above is a floor, not the need.")
    else:
        print("\nWhat this says about the flip: a budget of "
              f"{max((r for _, r in bumped), default=0)} would have covered every hit in "
              "THIS run. The shipped 2 is the worst case across BOTH live samples — 10.2's "
              "single hit needed rung 2 (`10-2-live-validation/`). Note these are DETECTOR "
              "hits, not confirmed contaminations: see README.md for which were "
              "eyeballed, and for what the sample does not say.")

    if off_ladder:
        # Not a story failure — a derivation failure. Either the run was rendered by
        # a different `_shot_seed`, or the run_id argument is not the one that wrote
        # these sidecars. Either way the rung tally above is not trustworthy.
        return _EXIT_OFF_LADDER
    return _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
