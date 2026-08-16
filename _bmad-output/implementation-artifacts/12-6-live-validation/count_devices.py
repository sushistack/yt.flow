"""Count the four immersion devices per scene, for any number of scene dumps.

The ablation's hypothesis is about *device density per scene*, and no instrument in
the repo measures that — ``measure_script.py`` counts 어절, not 기법. This is that
instrument, and it is deliberately dumb: four transparent lexical rules, applied
identically to control and to both arms, so a difference between arms is a
difference in the scripts rather than in how they were read.

    uv run python _bmad-output/implementation-artifacts/12-6-live-validation/count_devices.py \
        control=after_scenes.json A=armA_scenes.json B=armB_scenes.json

Rules (all case-sensitive Korean, all counted on ``narration``):

* **2인칭** — occurrences of 당신/여러분. Occurrence count, not scene count: a scene
  that says 당신 three times is three times as 2인칭 as one that says it once.
* **질문** — number of ``?``. Every question in these scripts ends in one.
* **리액션** — occurrences of the narrator-reaction / lurid-intensifier lexicon
  below. It is a closed list, and it does not distinguish the narrator reacting
  ("소름 돋았습니다") from the narration describing something as lurid ("기괴한
  치료"); both are the register the device produces, and separating them needs a
  judge rather than a regex. A reaction phrased outside the list is missed.
* **가정** — number of SENTENCES carrying a hypothetical marker (만약 / ~라면 /
  ~다면 / 상상해 / 생각해보세요 / 해봅시다). Sentence-level, because one hypothetical
  usually spends two markers on one thought ("만약 그가 옳다면") and counting
  occurrences would score it twice.

Checked against the hand count that motivated the ablation (control, 8 scenes). The
two axes Jay actually heard reproduce cell for cell — 2인칭 1·1·2·1·1·0·0·1 and 질문
1·1·1·1·1·1·1·2, 16/16. The two softer axes differ in 4 cells and this counter is
the stricter reading of its own rule in every one of them: 리액션 scene 3 (끔찍하게
썩어가고), scene 6 (기괴한 '치료') and scene 8 (a "-죠" aside the hand count took and
the lexicon has no entry for), 가정 scene 6 (the hypothetical spans two sentences,
"만약 그가 옳다면" and "…보고 있다면요", and both are counted). Nothing is tuned to
match the hand count; the same rule runs on all three arms.

Also reports prose shape — sentence count and mean sentence length in characters —
because arm B claims to have changed the sentences, and an instruction that changed
no sentence is not a change.
"""

import json
import re
import sys
from pathlib import Path

SECOND_PERSON = re.compile(r"당신|여러분")
REACTION = re.compile(
    r"소름|진짜|기괴|놀랍게|솔직히|미쳐|섬뜩|오싹|끔찍|충격적|개인적으로|저도|무섭|소름끼"
)
HYPOTHETICAL = re.compile(r"만약|라면|다면|상상해|생각해보세요|해봅시다")
# Sentence terminator. `…`/`...` mid-sentence is an ellipsis, not a break, so only
# ./?/! split — and a trailing run of them counts once.
SENTENCE_SPLIT = re.compile(r"[.?!]+\s*")


def sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]


def count(narration: str) -> dict:
    parts = sentences(narration)
    return {
        "2인칭": len(SECOND_PERSON.findall(narration)),
        "질문": narration.count("?"),
        "리액션": len(REACTION.findall(narration)),
        "가정": sum(1 for part in parts if HYPOTHETICAL.search(part)),
        # The words that fired, so a 리액션 count can be read back as narrator stance
        # ("솔직히", "소름") or as a lurid adjective about the object ("기괴한 집착").
        "리액션_hits": REACTION.findall(narration),
        "sentences": len(parts),
        "chars": len(narration),
        "words": len(narration.split()),
    }


# `assigned_devices` name → the axis it is supposed to license.
ASSIGNED_AXIS = {"second_person": "2인칭", "dramatic_question": "질문", "narrator_reaction": "리액션"}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    arms = []
    for spec in sys.argv[1:]:
        label, _, path = spec.partition("=")
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = [count(scene.get("narration") or "") for scene in doc["scenes"]]
        for row, scene in zip(rows, doc["scenes"]):
            row["scene_num"] = scene.get("scene_num")
            row["assigned_devices"] = scene.get("assigned_devices")  # None for the control
        arms.append({"arm": label, "source": Path(path).name, "scenes": rows})

    for axis in ("2인칭", "질문", "리액션", "가정"):
        print(f"\n{axis}")
        for arm in arms:
            per = [row[axis] for row in arm["scenes"]]
            print(f"  {arm['arm']:8s} " + " ".join(f"{v:2d}" for v in per) + f"   합계 {sum(per):3d}"
                  f"  씬당 {sum(per) / len(per):.2f}  사용 씬 {sum(1 for v in per if v)}/{len(per)}")

    print("\n문장")
    for arm in arms:
        rows = arm["scenes"]
        total_sentences = sum(row["sentences"] for row in rows)
        total_chars = sum(row["chars"] for row in rows)
        print(
            f"  {arm['arm']:8s} 문장 {total_sentences:3d}  평균 문장 길이 "
            f"{total_chars / total_sentences:.1f}자  평균 어절/문장 "
            f"{sum(row['words'] for row in rows) / total_sentences:.2f}  "
            "씬별 문장수 " + " ".join(str(row["sentences"]) for row in rows)
        )

    # Did the allocation land where it was aimed? Only arms carrying `assigned_devices`
    # have an aim; the control is skipped rather than scored against a plan it never had.
    for arm in arms:
        if not any(row["assigned_devices"] is not None for row in arm["scenes"]):
            continue
        print(f"\n배정 대비 실제 ({arm['arm']})")
        for device, axis in ASSIGNED_AXIS.items():
            planned = [row["scene_num"] for row in arm["scenes"] if device in (row["assigned_devices"] or [])]
            actual = [row["scene_num"] for row in arm["scenes"] if row[axis]]
            print(f"  {axis:4s} 배정 {planned}  실제 {actual}"
                  + ("  일치" if planned == actual else "  불일치"))

    print()
    print(json.dumps({"arms": arms}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
