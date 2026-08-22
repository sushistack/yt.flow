#!/usr/bin/env python
"""Story 14.4: how many seconds does the guard's vision call add per shot?

Spec: ``_bmad-output/implementation-artifacts/spec-14-4-people-free-background-default.md``

The flip of ``background_person_guard_attempts`` 0 -> 2 is a cost/benefit claim, and
the per-shot cost has two halves: ONE vision call on every generated shot (paid
always) and ONE extra ~17s render per HIT (paid 5 times in 43 shots — see
``derive_guard_rungs.py``). Only the first half was never measured. This measures it.

It calls the REAL ``vision_check.background_has_person`` — the shipped function, not a
reimplementation — against PNGs already on disk from run 4b35c0ed. No render, no GPU,
no ComfyUI; the only network traffic is the DashScope call itself, capped at
``--limit`` (default 4) frames.

WHAT IT REFUSES TO DO: invent a number. No vision key, no frames, or a call that
comes back undecidable are all reported as such and produce no timing claim — a
fabricated latency would be worse than a missing one, because it would look like
evidence for a default that ships on every run.

    uv run python .../probe_vision_latency.py
    uv run python .../probe_vision_latency.py --limit 2 --run <run_id>

Exit 0 on at least one timed decided call, 3 when nothing could be timed.
"""

import argparse
import asyncio
import logging
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from yt_flow.config import Settings  # noqa: E402
from yt_flow.services import vision_check  # noqa: E402

DEFAULT_RUN = "4b35c0ed-8a1e-4448-8594-11bd9997376d"

# ponytail: the Block-If line from the spec's Boundaries, stated here so the number and
# the rule it is judged against live in one place. > 30 s/shot means the flip would add
# more than ~20 min to a 43-shot run and must not ship unattended.
BLOCK_IF_OVER_SEC = 30.0


async def probe(paths: list[Path], settings: Settings) -> list[tuple[str, float, object]]:
    timings = []
    for path in paths:
        started = time.monotonic()
        verdict = await vision_check.background_has_person(path.read_bytes(), settings)
        timings.append((path.name, time.monotonic() - started, verdict))
    return timings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", default=DEFAULT_RUN)
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--limit", type=int, default=4, help="vision calls, 1..4 (spec cap: 4)")
    args = parser.parse_args()
    # Refused, not clamped: `--limit 0` used to print "no PNGs under <dir>", a false claim
    # about the workspace, and `--limit 10` used to silently do 4.
    if not 1 <= args.limit <= 4:
        parser.error("--limit must be between 1 and 4 (the spec caps this probe at 4 calls)")
    # INFO so the detector's own `notes=` line (Story 14.4, vision_check.py) is visible:
    # that string is the only description of what is actually in the frame, and 14.1's
    # plate gate wants a corpus of them. The 2026-08-22 pass recorded in README.md ran
    # before this line existed, so its notes went nowhere — the latency figures are
    # unaffected, a logging handler cannot change a network round trip.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    images = args.workspace / args.run / "images"
    frames = sorted(images.glob("*.png"))[: args.limit]
    try:
        settings = Settings()
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError on a fresh checkout
        # The three Langfuse keys are required fields, so `Settings()` raises anywhere
        # `.env` is not resolvable — which is precisely the fresh-checkout case this
        # story is about. A traceback here would read as a probe failure, not as "the
        # config could not be loaded".
        print(f"\nDID NOT RUN: settings could not be loaded ({type(exc).__name__}); run "
              "this from the repo root with a readable .env. No latency figure produced.",
              file=sys.stderr)
        return 3
    print(f"sample band: run {args.run}")
    print(f"             frames    {images.resolve()}")
    print(f"             model     {settings.character_vision_model}")
    print(f"             calls     {len(frames)} (cap 4, spec Boundaries)")
    if not frames:
        print(f"\nDID NOT RUN: no PNGs under {images}. No latency figure produced.",
              file=sys.stderr)
        return 3
    if not settings.character_vision_api_key:
        print("\nDID NOT RUN: YTFLOW_CHARACTER_VISION_API_KEY is unset, so the detector "
              "would return None without a network call. No latency figure produced.",
              file=sys.stderr)
        return 3

    timings = asyncio.run(probe(frames, settings))
    for name, seconds, verdict in timings:
        print(f"  {name:<28} {seconds:6.2f}s  has_person={verdict!r}")
    decided = [s for _, s, v in timings if v is not None]
    if not decided:
        print("\nDID NOT MEASURE: every call came back undecidable (no key, HTTP error or "
              "unparseable reply). Those timings are failure latency, not detector "
              "latency, so no per-shot cost is claimed.", file=sys.stderr)
        return 3
    mean = statistics.fmean(decided)
    print(f"\ndecided calls: {len(decided)}/{len(timings)}   "
          f"per-call seconds min {min(decided):.2f} / mean {mean:.2f} / max {max(decided):.2f}")
    print(f"per-shot detector overhead vs the {BLOCK_IF_OVER_SEC:.0f}s Block-If line: "
          f"{'WITHIN' if max(decided) <= BLOCK_IF_OVER_SEC else 'OVER — DO NOT FLIP'}")
    shots = len(sorted(images.glob("*_done.json")))
    print(f"projected on this run's {shots} generated shot(s): {shots * mean / 60:.1f} min "
          "of vision calls, plus one ~17s render per hit — run `derive_guard_rungs.py "
          f"{args.run}` for this run's hit count (5 of 43 on {DEFAULT_RUN[:8]} = ~1.4 min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
