"""Score whether a rendered shot reads as the sentence it illustrates (Story 10.4).

Jay's findings 2·4·7·9·16 ("무슨 배경인지 모르는 배경이 많음", "나레이션과 전혀 맞지
않는 이미지") are two different defects and one score conflates them, so every shot
gets **two** DashScope Qwen-VL calls, in this order:

1. ``BLIND_PROMPT`` — the frame alone, **the narration sentence is withheld**. The
   frame's own testimony about what it depicts: ``{place, event, readable}``. Finding
   2 is answerable from these rows by itself.
2. ``MATCH_PROMPT`` — the same frame **plus** its sentence: ``{match, evidence,
   missing}``. Finding 4.

Blind first and blind without the sentence is the whole claim to being a
measurement: shown the sentence first, a VLM finds a way to agree with it. The
blind row is the anchoring control.

Both prompts state that people are composited from separate character cards, so an
empty plate is correct — without that sentence every cast-bearing shot fails for the
wrong reason and the measurement is void.

Real: the checkpoint (via ``eval_service._load_state``), the frames on disk, the
DashScope calls. Nothing is simulated. The judge is ``qwen-vl-plus`` and it is the
instrument, not an oracle — see ``scripts/score_composites.py``'s measured ceiling.

    uv run python scripts/score_shot_narration.py \
        --run 8a9a288b-800f-4c73-88a2-25ae6b5a4d7d --json baseline.json

Exit code is 1 if any row errored or was skipped — the axis must never report a
clean sweep it did not measure. Rows that merely score *below* the thresholds are a
result, not a failure of the run, and do not change the exit code.

Iteration 2 changed two things about the instrument, both because iteration 1's own
data said so (see ``10-4-live-validation/README.md``):

* ``legible`` was a dead 1--5 Likert — 66 frames produced ``{4: 46, 5: 20}``, nothing
  below 4, while **9 of those same replies** wrote ``event: "unclear"``. The score
  refused to express what the reply already knew. It is now the **boolean**
  ``readable``, which is the discrete value the model was volunteering anyway.
* ``--pair-by sentence`` emits one row per narration **sentence** (the covering
  shot's verdict) beside the per-shot rows. Once a shot may cover several sentences
  or several shots may split one, two legs share no shot slots and a per-shot pairing
  is undefined; the sentence is the invariant both legs are built over.

Iteration 3 (Story 13.2) replaces the 1--5 ``match`` Likert with ``--dsg``, a
Davidsonian-Scene-Graph decomposition (`arxiv 2310.18235`, ICLR 2024). Both of the
Likert's measured defects are structural and neither is fixable by rewording it:

* **No resolution.** 29 of ``baseline_v2.json``'s 66 rows sit at exactly 3, and the
  §12 merge probe left 15 of 16 rows unmoved. A satisfied-fraction over ~5 atomic
  propositions is continuous and cannot pile on one integer.
* **The card-absence confound.** ``match`` docks a frame for people the card layer
  composites separately. v2 tried to fix this with a *prompt sentence*
  (``_CARD_NOTE``) and it did not work: ``S00202`` is a wall-texture study,
  ``readable: false``, ``event: "unclear"`` — and ``match: 5``, earned off the
  composited card's mask. v3 removes it **structurally**: person-kind propositions
  are generated, then excluded from both numerator and denominator, and the excluded
  count is recorded per row. That turns the confound removal into a number.

**Why DSG and not VQAScore, measured rather than assumed.** VQAScore
(`arxiv 2404.01291`) is one call scored by the probability of the "yes" token, so it
needs token logprobs from the judge. Probed this session against
``https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions``:
``qwen-vl-plus`` returns ``"logprobs": null`` even when sent ``logprobs: true,
top_logprobs: 5`` (HTTP 200, content ``'Yes.'``), while ``qwen-plus`` on the **same
endpoint and the same key** returns a full ``logprobs.content[0].top_logprobs``. So
the endpoint supports logprobs and our vision judge does not — VQAScore is not
implementable here. DSG needs no logprobs at all, only yes/no answers.

``--dsg`` also writes its report to ``<workspace_path>/<run>/visual_score.json``
(``eval_service.VISUAL_SCORE_FILENAME``), which is where ``evaluate_ab`` looks for
``unreadable_rate``/``mean_dsg_score``.
"""

import argparse
import asyncio
import base64
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx  # noqa: E402

from yt_flow.config import Settings  # noqa: E402
from yt_flow.pipeline.nodes.scenario_chain import split_sentences  # noqa: E402
from yt_flow.services.eval_service import VISUAL_SCORE_FILENAME, _load_state  # noqa: E402
from yt_flow.services.vision_check import _DASHSCOPE_VISION_ENDPOINT  # noqa: E402

# Story 5.14's integrity floor, reused: a sub-1KB file is a placeholder, not a frame.
MIN_VALID_IMAGE_BYTES = 1024

# Thresholds. The hook (scene 1's first shot) is held higher because it is the one
# frame a viewer decides on before the narration has earned any patience.
# ponytail: readability has no threshold constant any more — `readable` IS the
# threshold, for the hook and for every other shot alike.
MIN_MATCH = 3
MIN_MATCH_HOOK = 4

_CARD_NOTE = """This is a BACKGROUND PLATE. Every person, body or creature in this story is drawn
separately as a character card and composited on top of this plate afterwards. A plate
with nobody in it is CORRECT and complete — the absence of a person is NEVER a defect,
never "nothing is happening", and never a mismatch. Judge the place and the physical
evidence of what happened there."""

# ponytail: module constants, not Langfuse prompts — offline QA, not runtime
# (same reasoning as label_location_plates.LABEL_PROMPT / score_composites.SCORE_PROMPT).
BLIND_PROMPT = f"""You are looking at one rendered frame from an animated SCP Foundation video.
It illustrates one sentence of Korean narration. You are NOT being shown that sentence.

{_CARD_NOTE}

Reply with a single JSON object and nothing else:
{{"place": "one short English phrase", "event": "one short English phrase", "readable": true or false}}

Field rules:
- place: where this is, as concretely as the frame supports — "a tiled examination
  room", "a concrete corridor", "an extreme close-up of a floor". Write "unclear" if
  you cannot tell where this is.
- event: what has just happened in this place, read ONLY from what the frame shows —
  damage, disturbance, objects out of place, marks, aftermath. Write "unclear" if the
  frame shows a place but no evidence that anything happened.
- readable: true ONLY if someone seeing this frame for two seconds could say BOTH
  where they are AND what happened here. If either `place` or `event` is "unclear",
  readable is false. A texture study, a surface, a glow or an abstraction is false."""

MATCH_PROMPT = f"""You are grading one rendered frame from an animated SCP Foundation video
against the sentence of Korean narration it is supposed to illustrate.

{_CARD_NOTE}

The narration sentence(s) for this frame:
\"\"\"
{{sentences}}
\"\"\"

Reply with a single JSON object and nothing else:
{{{{"match": 1-5, "evidence": "one short sentence", "missing": "one short sentence"}}}}

Field rules:
- match: does a viewer hearing this sentence over this frame see the sentence's EVENT
  (who did what, and what it left behind) in the frame? 5 = the frame shows the
  event's place and its visible consequence; 4 = the place is right and the
  consequence is implied; 3 = the place is right but nothing of the event is visible;
  2 = only the mood matches; 1 = a texture or mood piece unrelated to this sentence.
- Do NOT lower `match` because the people the sentence mentions are not drawn — they
  are composited later. Grade the place and the event's physical consequence only.
- evidence: what in the frame carries this sentence's event.
- missing: what this sentence describes that the frame does not show. Empty string if
  nothing is missing."""

# ── DSG instrument (Story 13.2) ──────────────────────────────────────────────

# Question generation is TEXT-ONLY, so it does not need the vision judge — and must
# not use it: qwen-vl-plus is the weaker model at structured decomposition. Same
# DashScope key, same endpoint, no new provider and no new credential (verified this
# session: qwen-plus serves this endpoint under character_vision_api_key).
QG_MODEL = "qwen-plus"

# Every kind the decomposer may emit. `person` is generated deliberately and then
# excluded from scoring — see `dsg_score`.
_PROP_KINDS = ("place", "object", "state", "action", "attribute", "person")
_PERSON_KIND = "person"
# The prompt asks for 3-7. This is the runaway guard, not the target: each proposition
# past the first costs one paid image call per frame, so an unbounded reply is a bill.
_MAX_PROPOSITIONS = 12

QG_PROMPT = """You are decomposing one or more sentences of Korean narration from an animated
SCP Foundation video into atomic visual propositions, so a separate judge can check each one
against a single rendered still frame.

The narration sentence(s):
\"\"\"
{sentences}
\"\"\"

The frame is a BACKGROUND PLATE: every person, body and creature in this story is drawn
separately as a character card and composited on top afterwards, so the plate itself carries
the place and the physical evidence of what happened there. Your decomposition must therefore
cover BOTH layers, and label which is which.

Decompose them into 3-7 ATOMIC propositions. Atomic means exactly one fact per proposition:
one place, one object, one state of one object, one action, or one attribute. Never join two
facts with "and".

Always include the background layer. Even when the sentence is entirely about a person, ask
what PLACE it happens in and what PHYSICAL TRACE the event would leave there — a disturbed
floor, a moved object, an open door, a mark, debris, a light left on — and write those as
propositions. Only omit them if the sentence genuinely implies no place and no physical trace
whatsoever; in that case emit only body propositions, which is a true and useful answer.
Never invent a detail the sentence does not imply just to fill the list.

STEP 1 — for every proposition, first answer this to yourself: **is its subject a body?**
`subject` is the bare noun the proposition is about ("corridor", "hand", "robe", "door").
`about_body` is true when that subject is a person, a creature, a body, ANY body part
(hand, face, eye, leg, silhouette), clothing or a mask worn by someone, or an action or
posture performed by a body. Otherwise false. Judge the SUBJECT, not the sentence: "the
robe reaches the floor" is about_body true (a robe is worn); "the floor is cracked" is
about_body false. Getting this wrong is the single worst error you can make here.

`kind` is exactly one of: place, object, state, action, attribute, person.
Set `kind` to `person` whenever `about_body` is true. The two must agree.
These propositions are WANTED — write them, label them honestly, and do not omit or
disguise them. They are filtered out later by the scorer, not by you.

STEP 2 — build a DEPENDENCY GRAPH. If a proposition only means anything when another is
true — an object's state depends on the object existing, an object depends on the place —
set its `parent` to that proposition's `id`. A proposition that stands on its own has
`parent: null`. List every parent BEFORE its children.
**A proposition with `about_body` false must NEVER have a body proposition as its parent.**
A room, a door or a floor does not depend on anyone being present. Parent scenery to
scenery only; a body proposition may be parented to the place it is in.

Each `question` is one yes/no question in English, answerable by LOOKING AT ONE STILL FRAME,
phrased so that "yes" means the frame satisfies the proposition. A question must never
mention the narration, the sentence, sound, what happens before or after, or how a viewer
feels.

Worked example — narration "가냘픈 실루엣, 바닥까지 닿는 검은 로브." (a frail silhouette, a black
robe reaching the floor). EVERY proposition here is about a body, so all four are `person`:
{{"propositions": [
  {{"id": "p1", "kind": "person", "subject": "silhouette", "about_body": true, "parent": null, "question": "Is a human-shaped figure present?"}},
  {{"id": "p2", "kind": "person", "subject": "silhouette", "about_body": true, "parent": "p1", "question": "Is the figure's silhouette thin or frail?"}},
  {{"id": "p3", "kind": "person", "subject": "robe", "about_body": true, "parent": "p1", "question": "Is the figure wearing a black robe?"}},
  {{"id": "p4", "kind": "person", "subject": "robe", "about_body": true, "parent": "p3", "question": "Does the black robe reach down to the floor?"}}
]}}

Second worked example — "손이 닿는 순간, 그는 죽었습니다." (the moment the hand touched, he died).
A hand is a body part and dying is something a body does, so those are `person`; the marks
left behind on the floor are not:
{{"propositions": [
  {{"id": "p1", "kind": "place", "subject": "room", "about_body": false, "parent": null, "question": "Is this the interior of a room?"}},
  {{"id": "p2", "kind": "person", "subject": "hand", "about_body": true, "parent": null, "question": "Is a hand visible?"}},
  {{"id": "p3", "kind": "person", "subject": "body", "about_body": true, "parent": null, "question": "Is a motionless body present?"}},
  {{"id": "p4", "kind": "state", "subject": "floor", "about_body": false, "parent": "p1", "question": "Are there scuff marks or disturbance on the floor?"}}
]}}

Reply with a single JSON object in exactly that shape and nothing else."""

# Deliberately WITHOUT `_CARD_NOTE`. The card confound is removed structurally here
# (person-kind propositions leave the fraction entirely), not by asking the judge to
# be lenient — v2 asked, and `S00202` still scored `match: 5` off a composited mask.
# This judge answers one factual question about one frame and nothing else.
QA_PROMPT = """You are answering ONE yes/no question about a single rendered frame from an
animated SCP Foundation video.

Question: {question}

Answer only from what this frame actually shows. If the frame does not show it, the answer is
false. Reply with a single JSON object and nothing else:
{{"answer": true or false}}"""


def _parse(text: str) -> dict:
    """Outermost brace slice — Qwen-VL fences its JSON or prefaces it with prose.

    Deliberately strict (``label_location_plates._parse_verdict``'s posture): a
    chatty or truncated reply is an error, never a pass.
    """
    if "{" not in text or "}" not in text:
        raise ValueError(f"no JSON object in reply: {text[:120]!r}")
    verdict = json.loads(text[text.index("{"):text.rindex("}") + 1])
    if not isinstance(verdict, dict):
        raise ValueError(f"verdict is not an object: {verdict!r}")
    return verdict


def _int_score(verdict: dict, field: str) -> int:
    """The field as an int in 1..5, or raise. Never coerced: ``True`` is an ``int``
    subtype and would otherwise read as 1, and ``"high"`` must not become a score."""
    value = verdict.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValueError(f"{field}={value!r} is not an int in 1..5")
    return value


def _bool_field(verdict: dict, field: str) -> bool:
    """The field as a real ``bool``, or raise. ``"yes"``/``1``/``"true"`` are NOT
    coerced: a judge that would not answer the question asked is an errored row, and
    coercion here would silently manufacture the very readings this axis exists to
    count."""
    value = verdict.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"{field}={value!r} is not a boolean")
    return value


async def ask(settings: Settings, prompt: str, image_bytes: bytes) -> dict:
    """One Qwen-VL call. Same shape as ``services/vision_check`` (temperature 0)."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
        resp = await client.post(
            _DASHSCOPE_VISION_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.character_vision_api_key}"},
            json={
                "model": settings.character_vision_model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": settings.character_vision_max_tokens,
                "temperature": 0,
            },
        )
    resp.raise_for_status()
    return _parse(resp.json()["choices"][0]["message"]["content"])


async def _ask_once(settings: Settings, prompt: str, image_bytes: bytes, field: str, check=_int_score) -> dict:
    """One usable sample, with a single retry — a prose reply gets one more chance
    before it costs the row."""
    try:
        verdict = await ask(settings, prompt, image_bytes)
        check(verdict, field)
        return verdict
    except Exception:  # noqa: BLE001 — retried once, then it is the row's error
        verdict = await ask(settings, prompt, image_bytes)
        check(verdict, field)
        return verdict


async def sample(
    settings: Settings, prompt: str, image_bytes: bytes, field: str, reps: int, check=_int_score
) -> tuple[int | bool, list[dict]]:
    """``(score, samples)``. The score is the **median** of the usable reps.

    ``median_low`` rather than ``median`` so an even rep count still yields an int —
    a 3.5 is not a verdict this axis can compare against an int threshold. The same
    call is the **majority vote** for the boolean ``readable``: ``median_low`` over
    bools returns a bool, and an even split breaks to ``False`` — the conservative
    direction, since a frame only earns "readable" when most looks agree it is.
    A rep that errors is dropped but kept in ``samples``; fewer than ``min(2, reps)``
    usable reps raises, so the row is marked ``error`` instead of resting on one
    surviving sample of a run that was asked for several.
    """
    samples: list[dict] = []
    scores: list = []
    for _ in range(reps):
        try:
            verdict = await _ask_once(settings, prompt, image_bytes, field, check)
        except Exception as exc:  # noqa: BLE001 — a dead rep is data, not a crash
            samples.append({"error": f"{type(exc).__name__}: {exc}"})
            continue
        samples.append(verdict)
        scores.append(check(verdict, field))
    if len(scores) < min(2, reps):
        # Carry the last rep's own error out with the count: "0 usable of 1" alone
        # says the row died without saying what killed it.
        last = next((s["error"] for s in reversed(samples) if "error" in s), "no samples taken")
        raise ValueError(f"{field}: only {len(scores)} usable sample(s) of {reps} reps — last: {last}")
    return statistics.median_low(scores), samples


def _propositions_field(verdict: dict, field: str = "propositions") -> list[dict]:
    """The proposition list, validated, or raise.

    Strict for the same reason ``_bool_field`` is: a malformed graph does not fail
    loudly, it silently produces a wrong denominator. Requires a non-empty list of
    objects, each with a unique string ``id``, a ``kind`` from ``_PROP_KINDS``, a
    non-empty ``question``, and a ``parent`` that is either null or an id *already
    listed* — which is also what guarantees a parent is answered before its child.
    """
    props = verdict.get(field)
    if not isinstance(props, list) or not props:
        raise ValueError(f"{field}={props!r} is not a non-empty list")
    # The prompt asks for 3-7; nothing but this stops a runaway reply, and every
    # proposition past the first costs one paid image call per frame.
    if len(props) > _MAX_PROPOSITIONS:
        raise ValueError(f"{len(props)} propositions is not a decomposition (max {_MAX_PROPOSITIONS})")
    seen: set[str] = set()
    for prop in props:
        if not isinstance(prop, dict):
            raise ValueError(f"proposition is not an object: {prop!r}")
        pid, kind, question = prop.get("id"), prop.get("kind"), prop.get("question")
        if not isinstance(pid, str) or not pid or pid in seen:
            raise ValueError(f"proposition id={pid!r} is missing, empty or duplicated")
        if kind not in _PROP_KINDS:
            raise ValueError(f"proposition {pid}: kind={kind!r} not one of {_PROP_KINDS}")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"proposition {pid}: question={question!r} is not a non-empty string")
        # `about_body` is THE field the confound removal rests on, so it is required and
        # must be a real bool. `"true"` or `1` would make `_is_person`'s `is True` test
        # fail and put a body proposition straight back into the denominator — the
        # precise failure the QG prompt's worked examples exist to prevent. A missing
        # field is worse than a wrong one: it silently degrades `_is_person` to
        # kind-only AND reads as perfect compliance in `dsg_label_disagreements`.
        if not isinstance(prop.get("about_body"), bool):
            raise ValueError(f"proposition {pid}: about_body={prop.get('about_body')!r} is not a boolean")
        parent = prop.get("parent")
        if parent is not None and parent not in seen:
            raise ValueError(f"proposition {pid}: parent={parent!r} is not an earlier proposition")
        seen.add(pid)
    return props


def _is_person(prop: dict) -> bool:
    """Does this proposition's subject belong to the composited card layer?

    ``kind == "person"`` OR ``about_body is True`` — either one is enough, deliberately.
    The QG prompt requires the two to agree, and when they disagree the honest reading
    is that the model noticed a body and then mislabelled it, so the union is the safe
    direction: a stray exclusion costs one proposition of denominator, whereas a missed
    one puts the card-absence confound back into the score.

    Measured reason this exists (smoke run, 3 rows / 13 propositions, before the QG
    prompt carried worked examples): ``qwen-plus`` labelled "Is there a hand visible in
    the frame?" as ``object``, "Is a human figure present inside the containment cell?"
    as ``object``, and a black robe's length as ``state`` — so 3 of 3 rows scored
    almost entirely on body propositions the plate is not supposed to contain. No
    regex over the question text: ``gotcha_person-token-regex-is-unusable-on-image-prompt``
    is the recorded cost of that shortcut. The fix is the prompt plus this union, and
    the residual disagreement is REPORTED (``dsg_label_disagreements``) rather than
    silently patched.
    """
    return prop.get("kind") == _PERSON_KIND or prop.get("about_body") is True


async def ask_text(settings: Settings, prompt: str) -> dict:
    """One text-only ``QG_MODEL`` call. Same key, endpoint and ``temperature: 0`` as
    ``ask`` — the only differences are the model and the absence of an image part."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
        resp = await client.post(
            _DASHSCOPE_VISION_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.character_vision_api_key}"},
            json={
                "model": QG_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": settings.character_vision_max_tokens,
                "temperature": 0,
            },
        )
    resp.raise_for_status()
    return _parse(resp.json()["choices"][0]["message"]["content"])


async def _propositions(settings: Settings, sentences: list[str]) -> list[dict]:
    """QG: the narration sentence(s) → atomic typed propositions + dependency graph.

    One retry on a chatty/fenced/invalid reply (``_ask_once``'s posture), then it is
    the *row's* ``dsg_error`` — never the run's. The frame is not consulted at all:
    the decomposition is a property of the sentence, so it must not be able to see
    what was rendered.
    """
    prompt = QG_PROMPT.format(sentences="\n".join(sentences))
    for attempt in range(2):
        try:
            return _propositions_field(await ask_text(settings, prompt))
        except Exception:  # noqa: BLE001 — retried once, then it is the row's error
            if attempt == 1:
                raise
    raise AssertionError("unreachable")  # loop always returns or raises


async def _answer_propositions(settings: Settings, props: list[dict], image_bytes: bytes) -> list[dict]:
    """One yes/no VLM call per non-person proposition, parents before children.

    DSG's dependency semantics, which is the whole reason to prefer it over TIFA: a
    proposition whose parent answered **no** is *invalidated* — counted unsatisfied
    and **its own question is never asked**. "There is no bed" followed by "the bed is
    disturbed: yes" is exactly the inconsistency independent questions let through.
    Invalidation is transitive, because an invalidated parent is itself recorded as
    ``answer: False``. Skipping the call is also a real saving on a deep graph.

    **Person propositions are never asked, and count as SATISFIED for dependency
    resolution.** This is the research's "marked as satisfied by the card layer", and
    it is load-bearing, not an optimisation: the card layer composites every body
    afterwards, so asking the plate about a body can only produce a false negative, and
    a false negative on a *parent* propagates — the smoke run had "is the person moving
    toward the interior" answer False and invalidate its child "is the cell door open",
    which is a legitimate plate proposition. Excluding person propositions from the
    fraction is therefore not sufficient on its own; they must also be unable to
    invalidate scenery. They still cost a QG slot and are counted, which is what makes
    the confound removal a measured quantity.

    A QA call that errors after its retry counts unsatisfied and records ``error``,
    keeping the row scorable — same row-level posture as ``sample``'s dead reps.
    """
    answers: list[dict] = []
    satisfied: dict[str, bool] = {}
    for prop in props:
        if _is_person(prop):
            satisfied[prop["id"]] = True  # the card layer supplies it
            answers.append({**prop, "answer": None, "invalidated": False, "excluded": True})
            continue
        parent = prop.get("parent")
        if parent is not None and not satisfied.get(parent, False):
            satisfied[prop["id"]] = False
            answers.append({**prop, "answer": False, "invalidated": True, "excluded": False})
            continue
        try:
            verdict = await _ask_once(settings, QA_PROMPT.format(question=prop["question"]),
                                      image_bytes, "answer", _bool_field)
        except Exception as exc:  # noqa: BLE001 — a dead proposition is data, not a crash
            satisfied[prop["id"]] = False
            answers.append({**prop, "answer": False, "invalidated": False, "excluded": False,
                            "error": f"{type(exc).__name__}: {exc}"})
            continue
        answer = _bool_field(verdict, "answer")
        satisfied[prop["id"]] = answer
        answers.append({**prop, "answer": answer, "invalidated": False, "excluded": False})
    return answers


def dsg_score(answers: list[dict]) -> tuple[float | None, int, int, int, int]:
    """``(score, scored_n, excluded_person_n, invalidated_n, label_disagreements)``.

    The score is satisfied ÷ scored over the **non-person** propositions. Person ones
    are dropped from numerator *and* denominator — the card layer composites every body
    separately, so a plate with nobody in it is correct and must not be docked for it.
    They are generated first precisely so the removal is a counted quantity rather than
    an assertion, and ``_answer_propositions`` additionally stops them invalidating
    scenery.

    ``None`` — never 0.0 and never 1.0 — when every proposition was person-kind (a
    sentence purely about a person, e.g. "아주 협조적으로요"). That row is *unscorable*,
    which is a different fact from "the frame shows none of it", and the two must not
    be averaged together. ``invalidated_n`` counts only propositions inside the
    denominator, since those are the ones the score was actually affected by.

    ``label_disagreements`` counts propositions where ``kind == "person"`` and
    ``about_body`` disagree. ``_is_person`` takes the union, so a disagreement never
    silently pollutes the score — but it is a live measure of how well the decomposer
    obeys the one rule the whole confound removal rests on, so it is reported instead
    of hidden.
    """
    scored = [a for a in answers if not _is_person(a)]
    excluded = len(answers) - len(scored)
    invalidated = sum(1 for a in scored if a.get("invalidated"))
    disagreements = sum(
        1 for a in answers
        if "about_body" in a and (a.get("kind") == _PERSON_KIND) != (a.get("about_body") is True)
    )
    if not scored:
        return None, 0, excluded, invalidated, disagreements
    satisfied = sum(1 for a in scored if a["answer"])
    return round(satisfied / len(scored), 4), len(scored), excluded, invalidated, disagreements


async def _score_dsg(settings: Settings, row: dict, sentences: list[str], image_bytes: bytes) -> None:
    """Fill ``row``'s DSG fields in place. Never raises — QG failure is row-level.

    A row that loses its decomposition keeps ``readable``/``match_score``: the whole
    point of scoring both instruments in one sweep is that one dying does not cost the
    other. ``dsg_score: None`` here means "not measured", same as an all-person row
    means "not scorable" — neither is a zero.
    """
    try:
        props = await _propositions(settings, sentences)
    except Exception as exc:  # noqa: BLE001 — an unscored row is data, not a crash
        row.update(dsg_error=f"{type(exc).__name__}: {exc}", dsg_score=None,
                   dsg_scored_n=0, dsg_excluded_person_n=0, dsg_invalidated_n=0,
                   dsg_label_disagreements=0)
        return
    answers = await _answer_propositions(settings, props, image_bytes)
    score, scored_n, excluded, invalidated, disagreements = dsg_score(answers)
    row.update(propositions=props, proposition_answers=answers, dsg_score=score,
               dsg_scored_n=scored_n, dsg_excluded_person_n=excluded,
               dsg_invalidated_n=invalidated, dsg_label_disagreements=disagreements,
               # A QA call that died after its retry counts unsatisfied, so a transient
               # DashScope failure LOWERS this row's score. Without this counter that is
               # indistinguishable from the frame genuinely not showing the thing —
               # exactly the "silently produces a wrong measurement" case.
               dsg_qa_errors_n=sum(1 for a in answers if "error" in a))


def shot_sentences(scene: dict, shot: dict) -> list[str]:
    """The sentence(s) this shot illustrates, in narration order.

    ``sentence_indices`` holds more than one entry whenever the ordered cover let one
    shot span several sentences (or ``build_scenes`` merged an empty-``image_prompt``
    transition sentence into the previous shot); those are joined and scored once.
    """
    sentences = split_sentences(scene.get("narration") or "")
    return [sentences[i] for i in sorted(shot.get("sentence_indices") or []) if 0 <= i < len(sentences)]


def shot_base(scene_num: int, shot_id: str) -> str:
    return f"scene_{scene_num:03d}_{shot_id}"


def extract_mid_frame(video: Path, out: Path) -> Path | None:
    """The composited frame at the clip's midpoint, or ``None``.

    Midpoint, not t=0: card compositing and the 2.5D parallax move both develop over
    the shot, and the head of the clip is the least representative moment of it.
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(["ffmpeg", "-y", "-ss", f"{float(probe.stdout.strip()) / 2:.3f}",
                    "-i", str(video), "-frames:v", "1", str(out)],
                   capture_output=True, check=True)
    return out if out.exists() and out.stat().st_size >= MIN_VALID_IMAGE_BYTES else None


def frame_for(run_id: str, scene_num: int, shot: dict, source: str, tmp: Path) -> tuple[Path | None, str]:
    """``(frame, reason)`` — the file to judge, or ``None`` and why there is none."""
    base = shot_base(scene_num, shot["shot_id"])
    if source == "shots":
        video = Path("workspace") / run_id / "shots" / f"{base}.mp4"
        if not video.is_file():
            return None, f"no composited clip at {video}"
        frame = extract_mid_frame(video, tmp / f"{base}.png")
        return (frame, "") if frame else (None, f"ffmpeg produced no usable frame from {video}")
    path = Path(shot.get("image_path") or (Path("workspace") / run_id / "images" / f"{base}.png"))
    if not path.is_file():
        return None, f"no frame at {path}"
    if path.stat().st_size < MIN_VALID_IMAGE_BYTES:
        return None, f"{path} is {path.stat().st_size}B (< {MIN_VALID_IMAGE_BYTES}B placeholder floor)"
    return path, ""


def fail_reason(row: dict) -> str | None:
    """``None`` if the row clears its thresholds, else every threshold it missed."""
    min_match = MIN_MATCH_HOOK if row["hook"] else MIN_MATCH
    reasons = []
    if not row["readable"]:
        reasons.append("readable=False")
    if row["match_score"] < min_match:
        reasons.append(f"match={row['match_score']}<{min_match}")
    return ", ".join(reasons) or None


async def score_run(
    settings: Settings, state: dict, run_id: str, *,
    frames: str = "images", reps: int = 1, limit: int | None = None,
    only: set[str] | None = None, tmp: Path | None = None, dsg: bool = False,
) -> list[dict]:
    """One row per shot, blind call before match call, in scene/shot order.

    ``dsg=True`` adds the Story 13.2 decomposition after the two Likert calls, so a
    single sweep produces v2's and v3's numbers on the identical frame and the two are
    comparable by construction.
    """
    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = tmp or Path(td)
        for scene in state["scenes"]:
            scene_num = scene["scene_num"]
            for index, shot in enumerate(scene["shots"]):
                if only is not None and shot["shot_id"] not in only:
                    continue
                if limit is not None and len(rows) >= limit:
                    return rows
                sentences = shot_sentences(scene, shot)
                row: dict = {
                    "scene_num": scene_num, "shot_id": shot["shot_id"],
                    # The one frame a viewer decides on before the narration has
                    # earned any patience — judged against the hook thresholds.
                    "hook": scene_num == 1 and index == 0,
                    "sentence_indices": list(shot.get("sentence_indices") or []),
                    "sentences": sentences, "frame_source": frames,
                    "image_prompt": shot.get("image_prompt"),
                    "cast": [c.get("card_key") for c in (shot.get("cast") or []) if isinstance(c, dict)],
                }
                frame, reason = frame_for(run_id, scene_num, shot, frames, tmp)
                if frame is None or not sentences:
                    row.update(status="skipped", reason=reason or "shot resolves to no sentence")
                    rows.append(row)
                    print(f"  - {row['shot_id']}: SKIPPED — {row['reason']}", flush=True)
                    continue
                row["frame"] = str(frame)
                image_bytes = frame.read_bytes()
                try:
                    # Blind FIRST and without the sentence: this call is the control.
                    readable, blind_samples = await sample(
                        settings, BLIND_PROMPT, image_bytes, "readable", reps, _bool_field)
                    match_score, match_samples = await sample(
                        settings, MATCH_PROMPT.format(sentences="\n".join(sentences)),
                        image_bytes, "match", reps)
                except Exception as exc:  # noqa: BLE001 — an unscored row is data, not a crash
                    row.update(status="error", reason=f"{type(exc).__name__}: {exc}")
                    rows.append(row)
                    print(f"  ! {row['shot_id']}: ERROR — {row['reason']}", flush=True)
                    continue
                blind = next((s for s in blind_samples if "error" not in s), {})
                match = next((s for s in match_samples if "error" not in s), {})
                row.update(
                    status="scored", readable=readable, match_score=match_score,
                    place=blind.get("place"), event=blind.get("event"),
                    evidence=match.get("evidence"), missing=match.get("missing"),
                    blind_samples=blind_samples, match_samples=match_samples,
                )
                row["fail_reason"] = fail_reason(row)
                if dsg:
                    await _score_dsg(settings, row, sentences, image_bytes)
                mark = "✓" if row["fail_reason"] is None else "✗"
                print(f"  {mark} {row['shot_id']}{' [HOOK]' if row['hook'] else ''}: "
                      f"readable={readable} match={match_score} place={blind.get('place')!r} "
                      f"event={blind.get('event')!r}"
                      + (f" dsg={row['dsg_score']} ({row['dsg_scored_n']} props, "
                         f"-{row['dsg_excluded_person_n']} person, "
                         f"{row['dsg_invalidated_n']} invalidated)" if dsg and "dsg_error" not in row else "")
                      + (f" dsg=ERROR {row['dsg_error']}" if dsg and "dsg_error" in row else "")
                      + ("" if row["fail_reason"] is None else f"  [FAIL: {row['fail_reason']}]"),
                      flush=True)
                rows.append(row)
    return rows


def summarize_dsg(rows: list[dict]) -> dict:
    """The v3 block, merged into ``summarize`` only when ``--dsg`` actually ran.

    ``mean_dsg`` averages the **scorable** rows only. An all-person row is excluded
    rather than counted as 0.0 — counting it would say the frame failed a test it was
    never given, which is the exact conflation this instrument exists to end.
    ``dsg_distribution`` is keyed by the score's own value (not a bucket), because the
    claim under test is "more distinct values than v2's five".
    """
    attempted = [r for r in rows if "dsg_score" in r or "dsg_error" in r]
    scorable = [r for r in attempted if r.get("dsg_score") is not None]
    distribution: dict[str, int] = {}
    for row in scorable:
        key = str(row["dsg_score"])
        distribution[key] = distribution.get(key, 0) + 1
    return {
        "dsg_rows": len(attempted),
        "dsg_scorable": len(scorable),
        "dsg_errored": sum("dsg_error" in r for r in attempted),
        "mean_dsg": round(statistics.fmean(r["dsg_score"] for r in scorable), 4) if scorable else None,
        "dsg_distribution": dict(sorted(distribution.items(), key=lambda kv: float(kv[0]))),
        "dsg_distinct_values": len(distribution),
        # Unscorable ≠ zero: every proposition was person-kind (a sentence purely
        # about a person). Reported as its own count, never folded into mean_dsg.
        "dsg_unscorable": sum(r.get("dsg_score") is None and "dsg_error" not in r for r in attempted),
        "dsg_propositions_total": sum(r.get("dsg_scored_n", 0) + r.get("dsg_excluded_person_n", 0)
                                      for r in attempted),
        # The card-absence confound, as a number: how many person-propositions left
        # the fraction, and how many rows were carrying at least one.
        "dsg_excluded_person_total": sum(r.get("dsg_excluded_person_n", 0) for r in attempted),
        "dsg_rows_with_person_prop": sum(r.get("dsg_excluded_person_n", 0) > 0 for r in attempted),
        "dsg_invalidated_total": sum(r.get("dsg_invalidated_n", 0) for r in attempted),
        # How often the decomposer's own `kind`/`about_body` disagreed. `_is_person`
        # takes the union so the score is unaffected, but this is the compliance rate
        # of the one rule the confound removal rests on — reported, never hidden.
        "dsg_label_disagreements_total": sum(r.get("dsg_label_disagreements", 0) for r in attempted),
        # Propositions whose QA call died after its retry. They count unsatisfied, so a
        # nonzero total here means mean_dsg is biased DOWN by API failures rather than
        # by frames. Read this before reading mean_dsg.
        "dsg_qa_errors_total": sum(r.get("dsg_qa_errors_n", 0) for r in attempted),
    }


def summarize(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["status"] == "scored"]
    failed = [r for r in scored if r["fail_reason"]]
    hook = next((r for r in rows if r["hook"]), None)
    covered = [i for r in rows for i in (r.get("sentence_indices") or [])]
    dsg = summarize_dsg(rows) if any("dsg_score" in r or "dsg_error" in r for r in rows) else {}
    return {
        **dsg,
        "rows": len(rows), "scored": len(scored),
        "skipped": sum(r["status"] == "skipped" for r in rows),
        "errored": sum(r["status"] == "error" for r in rows),
        "failed": len(failed),
        "failure_rate": round(len(failed) / len(scored), 3) if scored else None,
        "mean_match": round(statistics.fmean(r["match_score"] for r in scored), 3) if scored else None,
        "below_min_match": sum(r["match_score"] < MIN_MATCH for r in scored),
        "unreadable": sum(not r["readable"] for r in scored),
        # The cover makes shot count a *result*, not a constant — a leg that merged
        # four sentences away renders four fewer frames, and that has to be visible
        # next to any mean it moved.
        "n_shots": len(rows),
        "sentences_per_shot": round(len(covered) / len(rows), 3) if rows else None,
        # Finding 2 vs finding 4: a frame nobody can read is not the same defect as a
        # frame that reads clearly and shows the wrong thing. Never merged.
        "unreadable_only": sum(not r["readable"] and r["match_score"] >= MIN_MATCH for r in scored),
        "mismatch_only": sum(r["readable"] and r["match_score"] < MIN_MATCH for r in scored),
        "both": sum(not r["readable"] and r["match_score"] < MIN_MATCH for r in scored),
        "hook": None if hook is None else {
            "shot_id": hook["shot_id"], "status": hook["status"],
            "readable": hook.get("readable"), "match": hook.get("match_score"),
            "fail_reason": hook.get("fail_reason"), "reason": hook.get("reason"),
        },
        "worst": [
            {"shot_id": r["shot_id"], "scene_num": r["scene_num"], "readable": r["readable"],
             "match": r["match_score"], "place": r.get("place"), "missing": r.get("missing")}
            for r in sorted(scored, key=lambda r: (r["match_score"], r["readable"]))[:10]
        ],
    }


def pair_by_sentence(state: dict, rows: list[dict]) -> list[dict]:
    """One row per narration **sentence**, carrying the verdict of the shot(s) covering it.

    Once the sentence↔shot mapping is an ordered cover, two legs no longer share shot
    slots — ``S00103`` in one leg and ``S00103`` in the other can be different
    sentences — so a per-shot pairing is not a pairing at all. The sentence is what
    both legs are built over, and it is what the paired statistic runs on.

    A sentence covered by several shots (a split) takes the **mean** of their
    ``match``: the viewer hears that one sentence across all of those frames, and mean
    is the only summary that neither rewards splitting (``max``) nor punishes it
    (``min``). ``readable`` is ``all()`` over the covering shots for the same reason —
    the sentence is not cleanly readable if any frame it plays over is not.
    """
    by_scene: dict[int, list[dict]] = {}
    for row in rows:
        by_scene.setdefault(row["scene_num"], []).append(row)
    out: list[dict] = []
    for scene in state["scenes"]:
        sentences = split_sentences(scene.get("narration") or "")
        scene_rows = by_scene.get(scene["scene_num"], [])
        for index, sentence in enumerate(sentences):
            covering = [r for r in scene_rows if index in (r.get("sentence_indices") or [])]
            scored = [r for r in covering if r["status"] == "scored"]
            entry = {
                "scene_num": scene["scene_num"], "sentence_index": index, "sentence": sentence,
                "shot_ids": [r["shot_id"] for r in covering],
                "hook": any(r["hook"] for r in covering),
            }
            if not scored:
                # An uncovered sentence is a cover bug; an unscored one is a skipped
                # or errored frame. Both are recorded, neither is silently averaged in.
                entry["status"] = "uncovered" if not covering else covering[0]["status"]
                entry["reason"] = next((r.get("reason") for r in covering if r.get("reason")),
                                       "no shot covers this sentence")
            else:
                entry.update(
                    status="scored",
                    match=round(statistics.fmean(r["match_score"] for r in scored), 3),
                    readable=all(r["readable"] for r in scored),
                    n_covering=len(scored),
                )
            out.append(entry)
    return out


def summarize_sentences(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["status"] == "scored"]
    return {
        "sentences": len(rows), "scored": len(scored),
        "uncovered": sum(r["status"] == "uncovered" for r in rows),
        "unscored": sum(r["status"] not in ("scored", "uncovered") for r in rows),
        "mean_match": round(statistics.fmean(r["match"] for r in scored), 3) if scored else None,
        "unreadable": sum(not r["readable"] for r in scored),
        "below_min_match": sum(r["match"] < MIN_MATCH for r in scored),
        "split_sentences": sum(r.get("n_covering", 1) > 1 for r in scored),
    }


def report(rows: list[dict], settings: Settings, run_id: str, args, state: dict | None = None) -> dict:
    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "run": run_id,
        "frame_source": args.frames,
        "reps": args.reps,
        "vision_model": settings.character_vision_model,
        "endpoint": _DASHSCOPE_VISION_ENDPOINT,
        "thresholds": {
            "readable": "boolean — no threshold, the field IS the verdict",
            "MIN_MATCH": MIN_MATCH, "MIN_MATCH_HOOK": MIN_MATCH_HOOK,
        },
        "blind_prompt": BLIND_PROMPT,
        "match_prompt": MATCH_PROMPT,
        "summary": summarize(rows),
        "rows": rows,
    }
    # getattr, not args.dsg: run_baseline.py feeds `report` a synthesized
    # argparse.Namespace, and adding a required attribute there would break it.
    if getattr(args, "dsg", False):
        out.update(dsg=True, qg_model=QG_MODEL, qg_prompt=QG_PROMPT, qa_prompt=QA_PROMPT)
    if getattr(args, "pair_by", "shot") == "sentence" and state is not None:
        sentence_rows = pair_by_sentence(state, rows)
        out["sentence_summary"] = summarize_sentences(sentence_rows)
        out["sentence_rows"] = sentence_rows
    return out


async def run(args) -> int:
    settings = Settings()  # type: ignore[call-arg]
    if not settings.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — the axis needs the Qwen-VL key")
    state = await _load_state(args.run, settings.db_path)
    rows = await score_run(settings, state, args.run, frames=args.frames, reps=args.reps,
                           limit=args.limit, dsg=getattr(args, "dsg", False))
    out = report(rows, settings, args.run, args, state)
    summary = out["summary"]
    print(f"\n{summary['scored'] - summary['failed']}/{summary['scored']} shots passed "
          f"(readable, match>={MIN_MATCH}; hook match>={MIN_MATCH_HOOK})"
          f" — failure rate {summary['failure_rate']}, mean match {summary['mean_match']}, "
          f"unreadable {summary['unreadable']}")
    print(f"unreadable only={summary['unreadable_only']} mismatch only={summary['mismatch_only']} "
          f"both={summary['both']} skipped={summary['skipped']} errored={summary['errored']} "
          f"shots={summary['n_shots']} sentences/shot={summary['sentences_per_shot']}")
    if "sentence_summary" in out:
        print(f"per sentence: {json.dumps(out['sentence_summary'], ensure_ascii=False)}")
    if "mean_dsg" in summary:
        print(f"dsg: mean={summary['mean_dsg']} distinct={summary['dsg_distinct_values']} "
              f"dist={summary['dsg_distribution']} unscorable={summary['dsg_unscorable']} "
              f"errored={summary['dsg_errored']} person-props excluded="
              f"{summary['dsg_excluded_person_total']} from {summary['dsg_rows_with_person_prop']} rows")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"rows -> {args.json}")
    if getattr(args, "dsg", False):
        # The consumer's path, spelled once (eval_service owns the constant): this is
        # where `evaluate_ab` reads unreadable_rate / mean_dsg_score from.
        #
        # PUBLISHED ONLY FOR A COMPLETE SWEEP OF THE PLATES. Nothing downstream can tell
        # a partial report from a full one — `_unreadable_rate` divides
        # summary.unreadable by summary.scored and has no idea 3 of 66 shots were
        # scored — so a `--limit 3` smoke run would otherwise persist a 3-frame
        # readability rate as the run's readability, ingest it into Langfuse and render
        # it in the UI. `--frames shots` is excluded for a different reason: those are
        # composited clip mid-frames, a different population from the plates the axis
        # is calibrated on.
        reasons = []
        if args.limit:
            reasons.append(f"--limit {args.limit} scored a subset")
        if args.frames != "images":
            reasons.append(f"--frames {args.frames} is not the plate population")
        if summary["skipped"] or summary["errored"]:
            reasons.append(f"{summary['skipped']} skipped / {summary['errored']} errored shots")
        if summary.get("dsg_errored"):
            reasons.append(f"{summary['dsg_errored']} rows failed decomposition")
        if reasons:
            print(f"visual scores NOT published ({'; '.join(reasons)}) — a partial sweep "
                  f"cannot be told apart from a full one downstream")
        else:
            artifact = Path(settings.workspace_path) / args.run / VISUAL_SCORE_FILENAME
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"visual scores -> {artifact}")
    # dsg_errored counts too: a --dsg run where every decomposition failed measured
    # nothing, and exiting 0 on it would report a clean sweep it did not take.
    return 1 if summary["skipped"] or summary["errored"] or summary.get("dsg_errored") else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--run", required=True, help="run id whose checkpoint holds the scenes")
    ap.add_argument("--json", help="write the full report (rows + prompts + summary) here")
    ap.add_argument("--reps", type=int, default=1, help="samples per question; the median is the score")
    ap.add_argument("--frames", choices=("images", "shots"), default="images",
                    help="'images' = the generated plate (default), 'shots' = the composited clip's mid-frame")
    ap.add_argument("--limit", type=int, help="score only the first N shots")
    ap.add_argument("--dsg", action="store_true",
                    help="also run the Story 13.2 DSG decomposition (proposition fraction, "
                         "person-kind propositions excluded and counted) and write the report "
                         f"to <workspace>/<run>/{VISUAL_SCORE_FILENAME}")
    ap.add_argument("--pair-by", choices=("shot", "sentence"), default="shot",
                    help="'sentence' also emits one row per narration sentence (the covering "
                         "shot's verdict) — the only pairing two legs with different shot counts share")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
