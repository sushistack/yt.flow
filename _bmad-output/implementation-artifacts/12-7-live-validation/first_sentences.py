"""Print every scene's opening sentence so AC6's "앞 씬과 연결하며 시작" is auditable.

AC6 has no automatable判定: whether a sentence establishes the previous scene's state
is a reading, not a regex — an anaphor (`그`, `그렇게`, `그런`) is strong evidence but a
scene can connect without one and carry one without connecting. So this script does the
mechanical half only: it extracts the first sentence of each scene and flags the anaphora
as a hint. The count in `after.md` is a human judgment made against THIS output, which is
what makes it re-derivable — `gotcha_a-measurement-without-its-sample-band`.

    uv run python _bmad-output/implementation-artifacts/12-7-live-validation/first_sentences.py \
        control=…/12-6-live-validation/after_scenes.json after=…/12-7-live-validation/after_scenes.json
"""

import json
import re
import sys
from pathlib import Path

# Korean demonstratives that point back at something already said. A hint for the
# reader, never the verdict: 그/이 also open plenty of sentences that connect to nothing.
ANAPHORA = re.compile(r"^(그|이|저)(?:\s|것|런|렇|때|후|리하|러나|래서|처럼|런데|만큼)")


def first_sentence(narration: str) -> str:
    return re.split(r"(?<=[.!?])\s+", narration.strip())[0]


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for spec in sys.argv[1:]:
        label, _, path = spec.partition("=")
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        print(f"\n=== {label} ({Path(path).name}) ===")
        for scene in doc["scenes"]:
            num = scene.get("scene_num")
            text = first_sentence(scene.get("narration") or "")
            hint = "↩" if (num != 1 and ANAPHORA.match(text)) else " "
            print(f"  {hint} [{num}] {text}")
        print("  (scene 1 is the hook — exempt. ↩ marks a back-pointing opener; judge the rest by reading.)")


if __name__ == "__main__":
    main()
