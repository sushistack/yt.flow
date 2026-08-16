""""Where did the writer get this?" — answered by a script instead of by hand.

Story 12.8, Task 0 and AC8. `ablation.md:283-288` is a two-column table a human built
by reading three outlines beside three scripts. Until that is mechanical there is no
way to record outline-originated violation counts per run, which is what AC8 asks for.

Given one or more scene dumps (`{scenes, structure, scenario_quality}` — the shape
every live driver in this repo writes), this prints for each flagged narration
sentence the outline field it traces to. "Flagged" is every claim either judge raised:

  1. the `narration_quote` of each `scenario_quality.grounded_contradictions` entry
     (the review's channel — the one the spec named);
  2. the `issue` text of each fact-typed `scenario_quality.critic_scene_notes` entry
     (the critic's channel — the one that actually fires: both live runs of this story
     reported `grounded_contradictions: []` and carried every finding here instead);
  3. any sentence given on the command line with `--sentence`, which is how the three
     ablation dumps are re-derived (they predate the pass-2 grounding gate).

1 and 2 are exactly what `scenario._stamp_origin` reads at the gate, so running this
over a dump reproduces the `origin` labels that dump's run would carry today.

Attribution imports `_overlap` and `_ATTRIBUTION_MIN` from `scenario_chain`, so this
script and the runtime gate can never disagree about what "outline-originated" means.
`calibrate.py` is where that threshold's labelled set and separation live.

    uv run python .../attribute.py <dump.json> [<dump.json> ...]
    uv run python .../attribute.py --baseline      # the three committed 12.6 dumps,
                                                   # hand-flagged sentences ONLY
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from yt_flow.pipeline.nodes.scenario_chain import _ATTRIBUTION_MIN, _overlap  # noqa: E402

ABLATION = ROOT / "_bmad-output/implementation-artifacts/12-6-live-validation"
# The critic issue types whose text is a fact claim — `scenario._FACT_CRITIC_ISSUE_TYPES`.
FACT_ISSUE_TYPES = ("ungrounded_claim",)
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")

# The four rows of `ablation.md:283-288`, as the sentences a human flagged. Passed to
# the three pre-gate dumps so the committed baseline table is reproduced by the same
# code path a live dump takes.
BASELINE = {
    "control": (
        "after_scenes.json",
        ["도자기 가면이 살에 그대로 융합되어 있었죠."],
    ),
    "A": (
        "armA_scenes.json",
        [
            "더욱 기괴한 것은, 피부와 완전히 융합되어 이음새조차 없는 도자기 가면입니다.",
            "도자기가 뼈와 함께 자라난 듯, 두개골에 융합되어 있었죠.",
        ],
    ),
    "B": (
        "armB_scenes.json",
        [
            "보고서에 기록된 등급은 유클리드, 언제 돌발 행동을 일으킬지 모르는, 인간형 개체.",
            "고정하는 끈이나 이음매는커녕, 개체의 피부 및 두개골과 완벽하게 융합되어 있었던 겁니다.",
            "하지만 통제가 이어질수록, 개체가 집요하게 요구한 것은 더 많은 수술 도구였습니다.",
            "파일 속엔 수많은 실패와 불완전한 재활성화 기록뿐.",
            "문서 끝에는, 더 많은 환자를 요구하는 메모만 끊임없이 남아 있습니다.",
        ],
    ),
}


def _fields(scene: object) -> list[tuple[str, str]]:
    """Every outline field a fabrication can be minted in, as (label, text) pairs.

    Handles both `fact_references` shapes: bare strings before Story 12.8,
    `{statement, quote}` mappings after. Only the STATEMENT is a candidate source —
    the quote is source text, and a narration sentence matching it would mean the
    writer quoted the article it never saw.
    """
    if not isinstance(scene, dict):
        return []
    out: list[tuple[str, str]] = []
    for i, fact in enumerate(scene.get("fact_references") or [], start=1):
        text = fact if isinstance(fact, str) else str((fact or {}).get("statement", ""))
        out.append((f"fact_references[{i}]", text))
    event = scene.get("event")
    if isinstance(event, dict):
        for field in ("what", "consequence"):
            out.append((f"event.{field}", str(event.get(field) or "")))
    return out


def _locate(sentence: str, scenes: list) -> int | None:
    """The 1-based position of the scene whose narration contains this sentence."""
    for pos, scene in enumerate(scenes, start=1):
        if isinstance(scene, dict) and sentence.strip() in str(scene.get("narration") or ""):
            return pos
    return None


def _flagged(dump: dict, extra: list[str], channels: bool = True) -> list[tuple[int | None, str, str]]:
    """Every flagged claim in this dump, as (scene, text, which channel it came on).

    BOTH judge channels, because the review's is the one the spec named and the
    critic's is the one that actually fires: across the two live runs of this story,
    `grounded_contradictions` was empty in each while every grounding finding arrived
    as a fact-typed critic scene note. `_build_quality` stamps `origin` on both for the
    same reason, and matches the critic note on its `issue` text alone — the
    `suggestion` is the critic's proposed REWRITE and is grounded by construction.

    `channels=False` drops both and keeps only `extra`; `--baseline` uses it so its
    column stays a re-derivation of `ablation.md`'s hand table and nothing else.
    """
    quality = dump.get("scenario_quality") or {} if channels else {}
    rows = [
        (item.get("scene_num") if type(item.get("scene_num")) is int else None,
         str(item.get("narration_quote") or ""), "review.grounded_contradiction")
        for item in (quality.get("grounded_contradictions") or [])
        if isinstance(item, dict)
    ]
    rows += [
        (note.get("scene_num") if type(note.get("scene_num")) is int else None,
         str(note.get("issue") or ""), f"critic.{note.get('issue_type')}")
        for note in (quality.get("critic_scene_notes") or [])
        if isinstance(note, dict) and note.get("issue_type") in FACT_ISSUE_TYPES
    ]
    scenes = dump.get("scenes") or []
    rows += [(_locate(sentence, scenes), sentence, "--sentence") for sentence in extra]
    return [row for row in rows if row[1].strip()]


def _report(label: str, dump: dict, extra: list[str], channels: bool = True) -> int:
    structure = dump.get("structure") or []
    rows = _flagged(dump, extra, channels)
    print(f"\n{'=' * 78}\n{label}  —  {len(structure)} scenes, {len(rows)} flagged sentence(s)\n{'=' * 78}")
    if not rows:
        print("  nothing flagged in this dump (no grounded_contradictions, no fact-typed "
              "critic scene note, and no --sentence given)")
        return 0

    outline_originated = 0
    unlocated = 0
    for pos, sentence, channel in rows:
        if not (pos and 1 <= pos <= len(structure)):
            # A `--sentence` that is in no scene's narration (a typo, a sentence from
            # another run, a split that did not match). Scoring it against an empty
            # outline scores 0.000 and files it under "writing", which quietly
            # UNDER-reports the outline-originated count AC8 is counting.
            unlocated += 1
            print(f"\n  씬 ?  [unlocated]  이 덤프의 어떤 narration에서도 찾지 못함  via {channel}")
            print(f"    flagged   : {sentence}")
            continue
        scene = structure[pos - 1]
        candidates = sorted(
            ((_overlap(sentence, text), name, text) for name, text in _fields(scene) if text),
            reverse=True,
        )
        best = candidates[0] if candidates else (0.0, "—", "")
        # The gate's own decision, taken over the CONCATENATION of the scene's fields
        # exactly as `scenario._stamp_origin` does — the per-field table below is the
        # human-readable half, not a second rule.
        joined = " ".join(text for _, text in _fields(scene))
        origin = "outline" if _overlap(sentence, joined) >= _ATTRIBUTION_MIN else "writing"
        outline_originated += origin == "outline"
        print(f"\n  씬 {pos or '?'}  [{origin}]  overlap {_overlap(sentence, joined):.3f} "
              f"(threshold {_ATTRIBUTION_MIN})  via {channel}")
        print(f"    flagged   : {sentence}")
        print(f"    최고 일치  : {best[1]}  ({best[0]:.3f})")
        print(f"                {best[2]}")
        for score, name, text in candidates[1:3]:
            print(f"    그 다음    : {name}  ({score:.3f})  {text[:60]}")
    print(f"\n  outline-originated: {outline_originated} / {len(rows)}"
          + (f"   (unlocated, not attributed: {unlocated})" if unlocated else ""))
    return outline_originated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dumps", nargs="*", type=Path, help="scene dump JSON files")
    parser.add_argument("--sentence", action="append", default=[],
                        help="an extra narration sentence to attribute (repeatable)")
    parser.add_argument("--baseline", action="store_true",
                        help="run over the three committed 12.6 ablation dumps with "
                             "ablation.md's hand-flagged sentences")
    args = parser.parse_args(argv)

    totals: dict[str, int] = {}
    if args.baseline:
        for arm, (name, sentences) in BASELINE.items():
            dump = json.loads((ABLATION / name).read_text(encoding="utf-8"))
            # Hand-flagged sentences ONLY (`channels=False`). Those three dumps also
            # carry their own critic notes, and two of them (A 씬6, B 씬3) are the SAME
            # violations the hand table already lists — counting both channels would
            # double-count them and the column would no longer be comparable to
            # `ablation.md:283-288`, which is the only thing this baseline is for.
            totals[f"{arm} (ablation baseline)"] = _report(
                f"{arm}  {name}", dump, sentences, channels=False
            )
    for path in args.dumps:
        dump = json.loads(path.read_text(encoding="utf-8"))
        totals[path.name] = _report(str(path.name), dump, args.sentence)

    if not totals:
        parser.error("give at least one dump, or --baseline")
    print(f"\n{'=' * 78}\nOUTLINE-ORIGINATED VIOLATIONS PER RUN\n{'=' * 78}")
    for label, count in totals.items():
        print(f"  {label:<40} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
