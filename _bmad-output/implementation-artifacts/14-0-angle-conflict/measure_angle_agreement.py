#!/usr/bin/env python
"""Story 14.0 §4-4: does the ``image_prompt`` body contradict the ``camera_angle`` field?

Spec: ``_bmad-output/implementation-artifacts/spec-14-0-angle-conflict.md``

Recomputes the measurement the story reports, straight from a run's LangGraph
checkpoint, so the numbers in ``report.md`` survive without the render
(`gotcha_a-measurement-without-its-sample-band`: a pixel/count measurement with
no re-derivation script and no control is not a measurement).

    uv run python .../measure_angle_agreement.py 4b35c0ed

Verdicts are deliberately asymmetric — reporting a shot UNDECIDABLE is always
preferred over calling it a CONFLICT, because a false conflict is what sent
§4-4 down the wrong branch in the first place.

Exit codes (the falsification gate — report.md §7 cites these):
    0  at least one DECIDED shot (AGREE or CONFLICT) and zero CONFLICTs
    1  at least one CONFLICT — the report's claim is falsified
    2  usage error
    3  nothing to measure: no such run, no non-empty ``scenes``, an ambiguous
       thread prefix, or every shot UNDECIDABLE. NOT a pass — a zero-conflict
       tally over zero decided shots proves nothing.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

_EXIT_OK, _EXIT_CONFLICT, _EXIT_USAGE, _EXIT_NOTHING = 0, 1, 2, 3

# Byte-identical to prompts/scenario/visual_breakdown.md:215 (POV is uppercase).
_ANGLES = ("wide", "medium", "close-up", "low-angle", "high-angle", "over-the-shoulder", "POV")

# Slot-1 detectors, in no priority order: the winner is whichever matches
# EARLIEST in the text (ties broken toward the LONGEST match, so a pattern
# nested in another can't win on alphabetical order), which is how "low-angle
# medium shot" (S00501) resolves to low-angle.
#
# Each pattern matches the angle WORD, never "<angle> shot". A naive
# r"\b(wide|medium|...) shot\b" regex scores only 22 of the 43 shots of run
# 4b35c0ed as AGREE — see the always-printed `naive` tally below and report.md
# §4 for the breakdown of the 21 it gets wrong.
_SLOT1_PATTERNS = {
    "wide": r"\bwide\b",
    "medium": r"\bmedium\b",
    "close-up": r"\bclose[- ]ups?\b",
    "low-angle": r"\blow[- ]angle\b",
    "high-angle": r"\bhigh[- ]angle\b",
    "over-the-shoulder": r"\bover[- ]the[- ]shoulder\b",
    "POV": r"\b(?:POV|point of view)\b",
}

# The counterfactual matcher §4 quotes: requires the noun `shot` right after the
# angle word, which is what a first-pass reader reaches for.
_NAIVE_PATTERN = (
    r"\b(wide|medium|close[- ]ups?|low[- ]angle|high[- ]angle|over[- ]the[- ]shoulder"
    r"|POV|point of view) shot\b"
)

# Lighting / fixture vocabulary, matched against the FULL prompt to print an
# audit list. Nothing here filters anything: `detect()` never sees this table.
# The reason these words cannot swing a verdict is structural — `detect()` reads
# slot 1 only, and no pattern in `_SLOT1_PATTERNS` matches any of them. The list
# exists so "we did not count the lamps as camera angles" is auditable instead
# of asserted. `overhead surgical lamp` and `twin rows of ceiling-mounted
# fluorescent tubes` describe where the light hangs, not where the camera
# stands — but position matters: in slot 1, `overhead`/`down` CAN be genuine
# framing (S00504 `high-angle overhead view of containment cell floor`,
# S00404/S00702 `view down`), so this is a whole-prompt audit and never a rule.
#
# The story's first pass flagged 15 shots as "carries a second angle phrase".
# That is not this tally: this vocabulary is wider (`overhead` alone hits 17
# shots), and it counts hits across the whole prompt, not just slot 1.
_LIGHTING_DECOYS = {
    "overhead": r"\boverhead\b",
    "from above": r"\bfrom above\b",  # covers `lit harshly from above` — no separate row
    "ceiling-mounted": r"\bceiling[- ]mounted\b",
}


def load_scenes(db: Path, thread_prefix: str) -> tuple[list, str, str]:
    """``(scenes, thread_id, checkpoint_id)`` of the last checkpoint of the
    matching thread that carries a non-empty ``scenes``.

    Returns empty values when there is nothing to measure — including an
    ambiguous prefix, which would silently mix two runs' shots.
    """
    if not db.exists():
        print(f"no checkpoint DB at {db} — run this from a checkout that has the run's yt_flow.db",
              file=sys.stderr)
        return [], "", ""
    serde = JsonPlusSerializer()
    scenes: list = []
    thread = checkpoint = ""
    threads: set[str] = set()
    skipped = 0
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT thread_id, checkpoint_id, type, checkpoint FROM checkpoints "
            "WHERE thread_id LIKE ? ORDER BY checkpoint_id",
            (thread_prefix + "%",),
        )
        for thread_id, checkpoint_id, typ, blob in rows:
            threads.add(thread_id)
            try:
                found = (serde.loads_typed((typ, blob)).get("channel_values") or {}).get("scenes")
            except Exception as exc:  # a partial/foreign blob is not this measurement's problem
                skipped += 1
                print(f"skipped checkpoint {thread_id}/{checkpoint_id}: {type(exc).__name__}: {exc}",
                      file=sys.stderr)
                continue
            if found:
                scenes, thread, checkpoint = found, thread_id, checkpoint_id
    if skipped:
        print(f"{skipped} checkpoint(s) skipped (undeserializable)", file=sys.stderr)
    if len(threads) > 1:
        print(f"prefix '{thread_prefix}' matches {len(threads)} thread_ids "
              f"({', '.join(sorted(threads)[:3])}, …) — refusing to mix runs", file=sys.stderr)
        return [], "", ""
    return scenes, thread, checkpoint


def slot1(image_prompt: str) -> str:
    """Slot 1 per visual_breakdown.md:72 — the shot-type clause that every
    non-empty image_prompt must open with. Bounded by the first comma, or by
    the first 14 words when the model wrote a comma-free opening clause.

    ponytail: a heuristic, not a parser for the 8-slot structure. All 43 shots of
    the measured run open slot 1 with the angle in the first few words, and
    widening the window can only ADD a later angle word, which the earliest-match
    rule already ignores. Parse the slots properly only if a run ever shows an
    angle arriving after word 14."""
    head = image_prompt.split(",", 1)[0]
    return " ".join(head.split()[:14])


def detect(text: str) -> tuple[str | None, str]:
    """(canonical angle, matched substring) for the earliest angle word in ``text``.

    Ties at the same offset go to the LONGEST match, never to the alphabetically
    first angle name.
    """
    hits = [
        (m.start(), -len(m.group(0)), angle, m.group(0))
        for angle, pattern in _SLOT1_PATTERNS.items()
        if (m := re.search(pattern, text, re.IGNORECASE))
    ]
    if not hits:
        return None, ""
    _, _, angle, matched = min(hits)
    return angle, matched


def canonical(raw: object) -> str | None:
    """Field value folded to the documented spelling, or None when off-vocabulary."""
    if not isinstance(raw, str):
        return None
    return {a.lower(): a for a in _ANGLES}.get(raw.strip().lower())


def _verdict(field: str | None, body_angle: str | None) -> str:
    if field is None:
        return "UNDECIDABLE(field)"
    if body_angle is None:
        return "UNDECIDABLE(slot-1)"
    return "AGREE" if body_angle == field else "CONFLICT"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return _EXIT_USAGE
    repo = Path(__file__).resolve().parents[3]
    scenes, thread_id, checkpoint_id = load_scenes(repo / "yt_flow.db", argv[1])
    if not scenes:
        print(f"nothing to measure: no checkpoint with a non-empty `scenes` for "
              f"thread_id LIKE '{argv[1]}%'")
        return _EXIT_NOTHING

    rows, decoys, naive = [], [], Counter()
    for scene in scenes:
        for shot in scene.get("shots") or []:
            prompt = shot.get("image_prompt") or ""
            head = slot1(prompt)
            field_raw = shot.get("camera_angle")
            field = canonical(field_raw)
            body_angle, matched = detect(head)
            verdict = _verdict(field, body_angle)
            rows.append((shot.get("shot_id"), field_raw, matched, verdict, head))
            naive_hit = re.search(_NAIVE_PATTERN, head, re.IGNORECASE)
            naive[_verdict(field, detect(naive_hit.group(0))[0] if naive_hit else None)] += 1
            for name, pattern in _LIGHTING_DECOYS.items():
                if re.search(pattern, prompt, re.IGNORECASE):
                    decoys.append((shot.get("shot_id"), name))

    print(f"run {argv[1]}: {len(rows)} shots")
    print(f"thread_id {thread_id} @ checkpoint_id {checkpoint_id}\n")
    print(f"{'shot':8} {'field':19} {'slot-1 match':20} verdict")
    for shot_id, field_raw, matched, verdict, _ in rows:
        print(f"{shot_id:8} {str(field_raw):19} {matched:20} {verdict}")

    tally = Counter(v for _, _, _, v, _ in rows)
    print("\nverdicts:", json.dumps(tally, ensure_ascii=False))
    print("naive   :", json.dumps(naive, ensure_ascii=False),
          '<- counterfactual matcher r"<angle> shot" (report.md §4)')
    print("census  :", json.dumps(Counter(str(f) for _, f, _, _, _ in rows).most_common(), ensure_ascii=False))
    print(f"\nlighting-vocabulary hits (audit print only — `detect()` never reads this table): "
          f"{len(decoys)} in {len({s for s, _ in decoys})} shots")
    for shot_id, name in decoys:
        print(f"  {shot_id} {name}")
    for shot_id, _, _, verdict, head in rows:
        if verdict != "AGREE":
            print(f"\n{verdict} {shot_id}: {head!r}")

    decided = tally.get("AGREE", 0) + tally.get("CONFLICT", 0)
    if tally.get("CONFLICT", 0):
        return _EXIT_CONFLICT
    if not decided:
        print("\nnothing to measure: 0 decided verdicts — zero conflicts here proves nothing")
        return _EXIT_NOTHING
    return _EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
