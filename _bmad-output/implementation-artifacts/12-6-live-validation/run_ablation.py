"""Prompt ablation on the writing stage: device allocation (A) and prose relaxation (B).

Sibling of ``run_after.py`` — same SCP, same seams, same dump shape — so the control
arm is ``after_scenes.json`` and nothing has to be re-run to compare against it.

**What is being tested.** Jay's two complaints about the control script:

1. *"모든 씬이 똑같은 기법을 쓴다"* — measured: every one of the 8 scenes carries
   exactly one dramatic question and 6 of 8 address the viewer as 당신.
   ``writing.md``'s "필수 몰입 기법 (전부 사용)" states its quotas **script-wide**
   ("시나리오 전체에서 최소 3회"), but ``writing_step`` is ONE LLM call per scene and
   each call sees only its own scene plus a one-line neighbour summary. A call cannot
   know the quota is already met, so it satisfies the whole quota alone — a script-wide
   quota executed N times is N times the intended density, and reads as a tic.
2. *"맥락 없이 상세한 내용만 주저리주저리"* — suspected: the 문장 길이 15~25자 rule
   strips the subordinate/connective grammar that carries causation and contrast, so
   the narration lands as a list of assertions with no orientation.

**Arm A** fixes (1) only: Python allocates the devices across the outline — exactly the
way ``hook_type`` is already scoped to scene 1 — and each writing call is told only its
own share. **Arm B** is A plus the prose relaxation for (2). So control→A isolates the
device fix and A→B isolates the prose fix.

**Nothing is seeded and nothing under ``prompts/`` or ``src/`` is edited.** The
production prompt is fetched and the substitutions are applied to the *compiled* text
in memory (``_Overridden``). Every substitution asserts its anchor was found, because a
silently-failed replace would make an arm byte-identical to control and the null result
would be a bug rather than a finding. The rendered scene-1 prompt is dumped beside the
scenes JSON as the receipt.

    uv run python _bmad-output/implementation-artifacts/12-6-live-validation/run_ablation.py \
        --arm A --out _bmad-output/implementation-artifacts/12-6-live-validation/armA_scenes.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# repo root = .../yt.flow. NOTE `run_after_tts.py` writes `HERE.parents[3]` for the same
# thing and is off by one — it only works because it uses ROOT solely for a sys.path
# insert, which a wrong path makes a silent no-op (yt_flow resolves via the editable
# install instead). This script reads `data/scps.json` off it, so it has to be right.
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from yt_flow.pipeline.nodes import scenario as sc  # noqa: E402
from yt_flow.services import prompt_service  # noqa: E402

# ---------------------------------------------------------------- allocation

# The device names the injected `assigned_devices` field uses. `sensory` is
# deliberately absent: 감각 묘사 is texture rather than a device that reads as a tic,
# so the overridden prompt leaves it free in every scene (see WRITING_DEVICE_BLOCK).
DEVICES = ("dramatic_question", "second_person", "narrator_reaction")


def allocate(structure: list[dict]) -> list[list[str]]:
    """Which scenes own which immersion device — one deterministic pass over the outline.

    Every rule reads a field the retention validator already constrains to a closed
    vocabulary (``pattern_interrupt``, ``loops_closed``, ``word_budget``), so the
    allocation survives a different archetype choosing different ``act`` names.

    - **극적 질문 → 2 scenes**: the hook scene, and the scene that closes the LAST
      loop. Those are the two places the outline itself puts an open question: one
      that opens the episode and one that lands the final payoff.
    - **2인칭 / 상황 가정 → 2 scenes**: the scenes whose ``pattern_interrupt`` is
      ``direct_address``. The outline already decides where the viewer gets addressed;
      the control run's prompt simply overrode that plan in every scene.
    - **리액션 삽입 → ≤2 scenes**: the scenes whose ``pattern_interrupt`` is
      ``tone_shift`` / ``pov_shift`` — the two interrupts that are about the narrator's
      own stance moving, which is what a reaction is.

    Fallbacks fill from the largest-budget middle scenes so an outline that declares no
    ``direct_address`` still gets its two, and never turns the hook or the closer into
    a second device carrier.
    """
    n = len(structure)
    interrupts = [str(scene.get("pattern_interrupt") or "none") for scene in structure]
    middle_by_budget = sorted(
        range(1, max(n - 1, 1)), key=lambda i: (-(structure[i].get("word_budget") or 0), i)
    )

    closers = [i for i, scene in enumerate(structure) if scene.get("loops_closed")]
    question = {0, closers[-1] if closers else n - 1}
    if len(question) < 2:  # degenerate outline: the hook is also the last closer
        question.add(n - 1)

    second_person = [i for i, kind in enumerate(interrupts) if kind == "direct_address"][:2]
    second_person += [i for i in middle_by_budget if i not in second_person][: 2 - len(second_person)]

    reaction = [i for i, kind in enumerate(interrupts) if kind in ("tone_shift", "pov_shift")][:2]
    reaction = reaction or middle_by_budget[:1]

    return [
        [
            name
            for name, owners in (
                ("dramatic_question", question),
                ("second_person", second_person),
                ("narrator_reaction", reaction),
            )
            if idx in owners
        ]
        for idx in range(n)
    ]


# ------------------------------------------------------------ prompt overrides

WRITING_DEVICE_BLOCK = """### 몰입 기법 — 이 씬에 배정된 것만 사용

이 기법들의 목표량은 **시나리오 전체** 기준입니다. 그런데 당신은 씬 하나만 씁니다 — 그래서
어느 씬이 어느 기법을 맡을지는 아웃라인 전체를 본 파이프라인이 이미 배정해 두었고, 그 배정은
이 씬 객체의 `assigned_devices` 필드에 들어 있습니다.

**아래 배정된 기법만 쓰고, 배정되지 않은 기법은 쓰지 마세요.** 빠뜨렸을까 봐 하나 더 넣으면
같은 기법이 대본 전체에서 씬 수만큼 반복되고, 그건 몰입이 아니라 버릇으로 들립니다.

1. **2인칭 (당신) / 상황 가정** — `assigned_devices`에 `second_person`이 있을 때만.
   시청자를 이야기 안에 집어넣거나 "만약 당신이 이 SCP를 만난다면" 상황을 제시하세요.
   - ✅ "당신이 그 문을 열었다고 생각해보세요. 안에서 뭔가 기다리고 있습니다."
   - 배정되지 않았다면 이 씬에서는 "당신"을 부르지 말고 관찰자 서술로 쓰세요.
2. **감각 묘사** — 배정과 무관하게 어느 씬에서나 자유롭게 쓰세요. 이건 기법이 아니라 질감입니다.
   - "축축한 콘크리트 냄새가 코를 찌릅니다. 어둠 속에서 무언가 긁히는 소리가 들립니다."
3. **극적 질문** — `assigned_devices`에 `dramatic_question`이 있을 때만. 시청자가 멈추고
   생각하게 만드는 질문을 **이 씬에 하나만** 던지세요.
   - "만약 세 명 모두가 동시에 눈을 깜빡인다면... 어떻게 될까요?"
   - 배정되지 않았다면 이 씬은 질문문 없이, 서술로 닫으세요.
4. **리액션 삽입** — `assigned_devices`에 `narrator_reaction`이 있을 때만. 나레이터의 감정적
   반응을 한 번 넣으세요.
   - "솔직히 이 부분 자료 읽으면서 소름 돋았습니다."

"""

# The ending-form rhythm rule is the SECOND place the prompt requires a question in
# every scene ("씬 전체에서 최소 다음 형태를 섞어 쓰세요 … 2. 의문형"). Leaving it
# untouched would keep 질문=1 in all 8 scenes and make the arm report a null result
# for a reason that has nothing to do with the quota being tested.
QUESTION_RHYTHM_OLD = '  2. 의문형 (-까요?/-을까요? — 위 "극적 질문" 기법과 동일)'
QUESTION_RHYTHM_NEW = (
    '  2. 의문형 (-까요?/-을까요?) — **이 씬에 `dramatic_question`이 배정된 경우에만**. '
    "배정되지 않았다면 의문형을 쓰지 말고 1·3·4 로 리듬을 만드세요."
)

# The fact-grounding section says the techniques are "여전히 전부 필수" — a direct
# contradiction of the block above once the block is replaced.
ALL_MANDATORY_OLD = "여전히 전부 필수지만"
ALL_MANDATORY_NEW = "배정된 기법은 여전히 필수지만"

SENTENCE_LENGTH_OLD = "- 문장 길이: 15~25자 (TTS 최적화용 — 짧고 펀치있게)"
SENTENCE_LENGTH_NEW = """- 문장 길이: 기본 15~25자로 짧고 펀치있게. **단, 인과·대조를 나타내는 연결 구문**
  (때문에 / 그래서 / ~하자 / ~인데도 / ~지만 / ~할수록 / ~기 위해)이 필요한 문장은 **40자까지
  허용**합니다. 그 논리를 잘라 두 문장으로 나누면 왜 그렇게 됐는지·그런데도 무엇이 이상한지가
  사라지고 단언만 남습니다 — 사실을 나열하지 말고 이어 붙이세요. 40자급 문장은 한 씬에
  두세 개까지, 나머지는 짧게."""

CONNECTIVE_OLD = "- 자연스러운 연결어 사용: 그때, 이후, 하지만, 게다가, 근데, 그런데 말이죠"
CONNECTIVE_NEW = """- 자연스러운 연결어 사용: 그때, 이후, 하지만, 게다가, 근데, 그런데 말이죠
- **이 씬의 첫 문장은 앞 씬과의 연결을 세우고 시작하세요.** `previous_scene_context`가 남긴
  상태·결과를 한 번 짚은 다음 이 씬의 사실로 들어갑니다 — 맨 사실 문장으로 열지 마세요.
  (Scene 1 은 예외입니다. 그 자리는 훅이고, 연결할 앞 씬이 없습니다.)
  - ❌ "격리 장소는 표준 인간형 격리 셀입니다." (앞과 무관한 사실로 시작)
  - ✅ "그 침착함이 어디서 오는지 알려면, 재단이 이 존재를 어떻게 가둬 뒀는지부터 봐야 합니다."
"""

# The repair pass rewrites flagged scenes through a DIFFERENT prompt, which never
# mentions the quotas — but it also never mentions the allocation, so a repair could
# reintroduce a device the arm just took away. One line keeps the arm coherent.
REPAIR_OLD = "- `pattern_interrupt`가 `none`이 아니면 그 기법을 계속 사용하세요."
REPAIR_NEW = (
    "- `pattern_interrupt`가 `none`이 아니면 그 기법을 계속 사용하세요.\n"
    "- 구조 항목의 `assigned_devices`가 이 씬에 배정된 몰입 기법의 전부입니다. 배정되지 않은 "
    "기법(2인칭·극적 질문·리액션)을 수리하면서 새로 추가하지 마세요."
)

DEVICE_BLOCK_START = "### 필수 몰입 기법 (전부 사용)"
DEVICE_BLOCK_END = "### 문장 & 페이싱 규칙"


def _replace_block(text: str, start: str, end: str, new: str) -> str:
    i, j = text.index(start), text.index(end)
    if not i < j:
        raise SystemExit(f"anchors out of order: {start!r} at {i}, {end!r} at {j}")
    return text[:i] + new + text[j:]


def _replace(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"override anchor appears {text.count(old)}× (need exactly 1): {old[:60]!r}")
    return text.replace(old, new)


def writing_overrides(arm: str):
    """The compiled-text transform for ``scenario/writing`` under this arm."""

    def apply(text: str) -> str:
        text = _replace_block(text, DEVICE_BLOCK_START, DEVICE_BLOCK_END, WRITING_DEVICE_BLOCK)
        text = _replace(text, QUESTION_RHYTHM_OLD, QUESTION_RHYTHM_NEW)
        text = _replace(text, ALL_MANDATORY_OLD, ALL_MANDATORY_NEW)
        if arm == "B":
            text = _replace(text, SENTENCE_LENGTH_OLD, SENTENCE_LENGTH_NEW)
            text = _replace(text, CONNECTIVE_OLD, CONNECTIVE_NEW)
        return text

    return apply


class _Overridden:
    """A Langfuse prompt whose compiled text is rewritten on the way out.

    Substitution happens AFTER ``compile`` so the anchors are matched against the same
    static prose a human reads in ``prompts/scenario/writing.md`` — the variables are
    already filled in by then and cannot straddle an anchor.
    """

    def __init__(self, inner, apply, sink: dict, name: str):
        self._inner, self._apply, self._sink, self._name = inner, apply, sink, name

    def __getattr__(self, item):  # everything except compile stays the real prompt
        return getattr(self._inner, item)

    def compile(self, **variables):
        text = self._apply(self._inner.compile(**variables))
        self._sink.setdefault(self._name, text)  # first render of each prompt, as the receipt
        return text


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", required=True, choices=["A", "B"])
    parser.add_argument("--scp-id", default="SCP-049")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scps = json.loads((ROOT / "data" / "scps.json").read_text(encoding="utf-8"))
    scp_text = next(s for s in scps if s["id"] == args.scp_id)["scp_text"]

    # --- prompt override seam -------------------------------------------------
    rendered: dict[str, str] = {}
    apply_writing = writing_overrides(args.arm)
    real_get_prompt = prompt_service.get_prompt

    def get_prompt(name: str, *, label: str | None = None):
        prompt = real_get_prompt(name, label=label)
        if name == "scenario/writing":
            return _Overridden(prompt, apply_writing, rendered, name)
        if name == "scenario/writing_scene_repair":
            return _Overridden(
                prompt, lambda text: _replace(text, REPAIR_OLD, REPAIR_NEW), rendered, name
            )
        return prompt

    prompt_service.get_prompt = get_prompt

    # Fail before spending a single LLM call if an anchor has moved: a silent no-op
    # would produce an arm identical to control and a null result that is really a bug.
    apply_writing(real_get_prompt("scenario/writing").compile())
    _replace(real_get_prompt("scenario/writing_scene_repair").compile(), REPAIR_OLD, REPAIR_NEW)

    # --- allocation seam ------------------------------------------------------
    # `_writing_scene_brief` builds its payload as `{**structure[idx], ...}`, so writing
    # a field onto the outline IS injecting it into the brief — and the scene-repair
    # pass, which json.dumps the same dicts, sees it too. No src/ edit, one write.
    outline: list[dict] = []
    real_structure = sc.structure_step

    async def capturing_structure(*a, **k):
        scenes = await real_structure(*a, **k)
        for scene, devices in zip(scenes, allocate(scenes)):
            scene["assigned_devices"] = devices
        outline.extend(scenes)
        return scenes

    sc.structure_step = capturing_structure

    stages: list[dict] = []
    state = {
        "run_id": f"12-6-arm{args.arm}-{args.scp_id}",
        "scp_id": args.scp_id,
        "scp_text": scp_text,
        "scenes": [],
        "video_path": None,
        "current_stage": "scenario",
        "gate_states": {},
        # Langfuse prompt VARIANT, not the ablation arm: "A" means label=None, i.e. the
        # production prompt — the same fetch the control run made. Both ablation arms
        # keep it so the only difference from control is this driver's substitutions.
        "prompt_variant": "A",
        "error": None,
    }
    out = await sc.scenario_node(state, trace_sink=stages)
    if out.get("error"):
        raise SystemExit(f"scenario failed: {out['error']}")

    scenes = [dict(scene) for scene in out["scenes"]]
    for idx, scene in enumerate(scenes):  # positional pairing, as run_after.py does
        if idx < len(outline):
            scene["word_budget"] = outline[idx].get("word_budget")
            scene["assigned_devices"] = outline[idx].get("assigned_devices")

    Path(args.out).write_text(
        json.dumps(
            {
                "run_id": state["run_id"],
                "arm": args.arm,
                "scp_id": args.scp_id,
                "scp_text": scp_text,
                "scenes": scenes,
                "structure": outline,
                "allocation": {
                    str(idx + 1): scene.get("assigned_devices") for idx, scene in enumerate(outline)
                },
                "scenario_quality": out.get("scenario_quality"),
                "story_archetype": out.get("story_archetype"),
                "stages": stages,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    for name, text in rendered.items():
        receipt = Path(args.out).with_name(f"arm{args.arm}_prompt_{name.split('/')[-1]}.txt")
        receipt.write_text(text, encoding="utf-8")
        print(f"receipt: {receipt}", file=sys.stderr)
    print(f"wrote {args.out}: {len(scenes)} scenes", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
