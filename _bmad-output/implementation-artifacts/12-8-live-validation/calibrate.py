"""Choose `_EVENT_SUPPORT_MIN` and `_ATTRIBUTION_MIN` from a labelled set, not from taste.

Story 12.8. Both constants are tuning knobs on `scenario_chain._overlap`, and a
threshold recorded without the distribution that chose it is unreproducible
(`gotcha_a-measurement-without-its-sample-band`). This script IS that band.

The labelled set is the three committed outlines of the 12.6 ablation
(`12-6-live-validation/{after,armA,armB}_scenes.json`) and the attribution table a
human wrote by hand at `ablation.md:283-288`:

  * 3 fabricated `event` fields  — B 씬3 `consequence`, B 씬8 `what`, B 씬8 `consequence`
  * 8 narration sentences        — the same three rows plus the "등급은 유클리드" row
                                   and the four "가면이 융합되어 있다" assertions

Everything else in those three dumps is the unlabelled remainder. It is NOT a
negative class: nearly every narration sentence in this pipeline *is* outline-derived,
which is the whole finding of the ablation, so "background ≥ t" below is the base rate
of the property being measured, not a false-positive rate. For the event side it is
closer to one: those 50 fields were written under a prompt that never asked for
support, so a fire there is "this outline would have been asked to fix it".

Selection rules, stated before the numbers so they cannot be fitted to them:

  _EVENT_SUPPORT_MIN  = the largest tested threshold whose fire rate over the 50
                        pre-change event fields stays at or under 20% (a note costs a
                        corrective retry; the spec says prefer the conservative side).
  _ATTRIBUTION_MIN    = a round value strictly between the lowest and second-lowest
                        labelled sentence score, i.e. the largest recall the
                        instrument can reach without sitting on a data point.

Run:  uv run python _bmad-output/implementation-artifacts/12-8-live-validation/calibrate.py
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from yt_flow.pipeline.nodes.scenario_chain import (  # noqa: E402
    _ATTRIBUTION_MIN,
    _EVENT_SUPPORT_MIN,
    _overlap,
)

ABLATION = ROOT / "_bmad-output/implementation-artifacts/12-6-live-validation"
DUMPS = {"control": "after_scenes.json", "A": "armA_scenes.json", "B": "armB_scenes.json"}

# ablation.md:283-288, rows 2 and 3 — the event fields the writer copied verbatim.
LABELLED_EVENTS = {("B", 3, "consequence"), ("B", 8, "what"), ("B", 8, "consequence")}

# ablation.md:283-288, every row — the narration sentences a human traced to an
# outline field. Quoted from the committed dumps, so a dump edit breaks the match
# loudly rather than silently dropping a positive (asserted below).
LABELLED_SENTENCES = {
    ("B", 4): [
        "보고서에 기록된 등급은 유클리드, 언제 돌발 행동을 일으킬지 모르는, 인간형 개체.",
        "고정하는 끈이나 이음매는커녕, 개체의 피부 및 두개골과 완벽하게 융합되어 있었던 겁니다.",
    ],
    ("B", 3): ["하지만 통제가 이어질수록, 개체가 집요하게 요구한 것은 더 많은 수술 도구였습니다."],
    ("B", 8): [
        "파일 속엔 수많은 실패와 불완전한 재활성화 기록뿐.",
        "문서 끝에는, 더 많은 환자를 요구하는 메모만 끊임없이 남아 있습니다.",
    ],
    ("A", 1): ["더욱 기괴한 것은, 피부와 완전히 융합되어 이음새조차 없는 도자기 가면입니다."],
    ("A", 6): ["도자기가 뼈와 함께 자라난 듯, 두개골에 융합되어 있었죠."],
    ("control", 7): ["도자기 가면이 살에 그대로 융합되어 있었죠."],
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")


def _facts(scene: dict) -> str:
    """The scene's fact statements, joined. Handles both shapes: the calibration
    dumps predate this story and hold bare strings; a post-12.8 outline holds
    ``{statement, quote}`` mappings and only the STATEMENT is the reference — the
    quote is source text and would make every event field look supported."""
    out = []
    for item in scene.get("fact_references") or []:
        out.append(item if isinstance(item, str) else str((item or {}).get("statement", "")))
    return " ".join(out)


def _outline_fields(scene: dict) -> str:
    event = scene.get("event") or {}
    return " ".join([_facts(scene), str(event.get("what", "")), str(event.get("consequence", ""))])


def _quantiles(values: list[float]) -> str:
    ordered = sorted(values)
    q = statistics.quantiles(ordered, n=4)
    return (
        f"n={len(ordered)}  min {ordered[0]:.3f}  q1 {q[0]:.3f}  med {statistics.median(ordered):.3f}"
        f"  q3 {q[2]:.3f}  max {ordered[-1]:.3f}"
    )


def main() -> int:
    dumps = {arm: json.loads((ABLATION / name).read_text(encoding="utf-8")) for arm, name in DUMPS.items()}

    # ── event support ────────────────────────────────────────────────────────
    events: list[tuple[bool, float, str, int, str, str]] = []
    for arm, dump in dumps.items():
        for pos, scene in enumerate(dump["structure"], start=1):
            reference = _facts(scene)
            for field in ("what", "consequence"):
                value = str((scene.get("event") or {}).get(field, ""))
                events.append(
                    (
                        (arm, pos, field) in LABELLED_EVENTS,
                        _overlap(value, reference),
                        arm, pos, field, value,
                    )
                )
    labelled_events = sorted(row[1] for row in events if row[0])
    assert len(labelled_events) == len(LABELLED_EVENTS), "a labelled event field did not match the dump"

    print("=" * 78)
    print("EVENT SUPPORT — _overlap(event.what|consequence, that scene's fact statements)")
    print("=" * 78)
    print("  all 50 pre-change fields:", _quantiles([row[1] for row in events]))
    print("  hand-attributed fabrications (ablation.md:285-287):",
          " ".join(f"{v:.3f}" for v in labelled_events))
    print("\n  threshold sweep — a field FIRES when its overlap is below the threshold:")
    print(f"    {'t':>6} {'fires':>10} {'rate':>7} {'catches':>9}")
    chosen_event = None
    for t in (0.01, 0.02, 0.03, 0.04, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25):
        fired = [row for row in events if row[1] < t]
        rate = len(fired) / len(events)
        caught = sum(1 for row in fired if row[0])
        flag = ""
        if rate <= 0.20:
            chosen_event = t
            flag = "  <- within the 20% fire budget"
        print(f"    {t:>6.2f} {len(fired):>7}/{len(events)} {rate:>6.0%} {caught:>6}/{len(labelled_events)}{flag}")
    print(f"\n  RULE: largest t with fire rate <= 20%  ->  _EVENT_SUPPORT_MIN = {chosen_event}")
    print(f"  SHIPPED: {_EVENT_SUPPORT_MIN}")
    # Printing the derived rule and the shipped constant as two independent statements
    # lets someone edit the constant and still read a clean report — the constant would
    # then no longer be "shipping with the numbers that chose it".
    assert chosen_event == _EVENT_SUPPORT_MIN, (
        f"the rule above derives {chosen_event} but _EVENT_SUPPORT_MIN ships {_EVENT_SUPPORT_MIN}"
    )

    print("\n  the fields that fire at the shipped threshold:")
    for row in sorted((r for r in events if r[1] < _EVENT_SUPPORT_MIN), key=lambda r: r[1]):
        mark = "**" if row[0] else "  "
        print(f"    {mark} {row[1]:.3f}  {row[2]:<8} s{row[3]:<2} {row[4]:<12} {row[5][:52]}")
    print("    (** = hand-attributed fabrication)")

    # ── attribution ──────────────────────────────────────────────────────────
    labelled: list[tuple[float, str, int, str]] = []
    background: list[float] = []
    for arm, dump in dumps.items():
        for pos, (written, outline) in enumerate(zip(dump["scenes"], dump["structure"]), start=1):
            reference = _outline_fields(outline)
            for sentence in _SENTENCE_SPLIT.split(written.get("narration", "")):
                sentence = sentence.strip()
                if not sentence:
                    continue
                score = _overlap(sentence, reference)
                if sentence in LABELLED_SENTENCES.get((arm, pos), []):
                    labelled.append((score, arm, pos, sentence))
                else:
                    background.append(score)
    expected = sum(len(v) for v in LABELLED_SENTENCES.values())
    assert len(labelled) == expected, f"matched {len(labelled)} of {expected} labelled sentences"

    print()
    print("=" * 78)
    print("ATTRIBUTION — _overlap(narration sentence, that scene's fact statements + event)")
    print("=" * 78)
    print("  unlabelled remainder:", _quantiles(background))
    print("  (NOT a negative class — most narration here IS outline-derived; that is the finding)")
    print("\n  the 8 hand-attributed sentences:")
    for score, arm, pos, sentence in sorted(labelled):
        print(f"    {score:.3f}  {arm:<8} s{pos:<2} {sentence[:56]}")
    print("\n  threshold sweep — a sentence is OUTLINE-originated at or above the threshold:")
    print(f"    {'t':>6} {'labelled':>10} {'remainder':>14}")
    for t in (0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.40):
        kept = sum(1 for row in labelled if row[0] >= t)
        bg = sum(1 for score in background if score >= t)
        print(f"    {t:>6.2f} {kept:>7}/{len(labelled)} {bg:>9}/{len(background)} ({bg / len(background):>3.0%})")
    ordered = sorted(row[0] for row in labelled)
    print(f"\n  RULE: strictly between the lowest ({ordered[0]:.3f}) and second-lowest "
          f"({ordered[1]:.3f}) labelled score")
    print(f"  SHIPPED: _ATTRIBUTION_MIN = {_ATTRIBUTION_MIN}  "
          f"-> {sum(1 for row in labelled if row[0] >= _ATTRIBUTION_MIN)}/{len(labelled)} labelled recovered")
    assert ordered[0] < _ATTRIBUTION_MIN < ordered[1], (
        f"the rule above wants a value strictly between {ordered[0]:.3f} and {ordered[1]:.3f}, "
        f"but _ATTRIBUTION_MIN ships {_ATTRIBUTION_MIN}"
    )

    print("\n" + "=" * 78)
    print("HONESTY")
    print("=" * 78)
    print(
        "  Neither axis separates cleanly. Character trigrams do not survive Korean\n"
        "  conjugation: control 씬7's '융합되어' shares exactly ONE trigram with its outline's\n"
        "  '융합된', which is why that labelled sentence scores 0.045 and is the one the\n"
        "  attribution threshold cannot recover. On the event axis, catching all three\n"
        "  fabrications needs t=0.20, which fires on 60% of the pre-change fields; the\n"
        "  shipped threshold catches one of three and fires on 18%. Both constants are\n"
        "  therefore floors on lexical disjointness, not detectors — the prompt rules\n"
        "  added by this story are what is expected to do the actual work, and the live\n"
        "  runs in after.md are where that is measured."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
