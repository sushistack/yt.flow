#!/usr/bin/env python
"""Story 14.7: text-only screening of the Stage-4 reviewer prompt edit (GPU 0).

Spec: ``_bmad-output/implementation-artifacts/spec-14-7-scenario-reviewer-recompose-alignment.md``

Renders the OLD reviewer prompt (``git show <--old-ref>:prompts/scenario/review.md``,
default the spec's ``baseline_revision``) and the NEW one (working tree) with
**identical** variables built from a real run's LangGraph checkpoint, and calls the
real review LLM ``--reps`` times per (version, scene) cell. Screens a prompt change
before spending a render (`gotcha_screen-a-prompt-change-before-you-render-it`), at
n>1 because one sample is not a verdict
(`gotcha_measure-densely-before-declaring-a-fix`).

    uv run python .../screen_review_prompt.py 4b35c0ed
    uv run python .../screen_review_prompt.py --selftest 0   # classifier only, no LLM

Reuses the runtime path wherever it exists: ``TextPromptClient.compile`` is the
same renderer ``scenario_chain._call_stage`` uses, ``scenario._call_gemini`` is the
same call site (so the shared token budget and provider config apply —
`gotcha_hand-rolled-llm-call-sites-miss-the-plumbing`), and
``scenario_chain._parse_yaml`` is the same parser.

**What is reconstructed, not replayed** (the checkpoint does not carry it):
``scp_visual_reference`` and ``entity_sheet`` (``research_step`` output, never
persisted) are rebuilt from the ``characters`` rows this run's own cards were cut
from, and ``entity_visible`` — the scene-level field clause (a) is entirely about —
is **injected** (``--entity-visible``), because ``writing_step``'s dict is not
persisted either. See ``variables()`` for the full divergence list.

**The harness self-checks before it reports.** A screening that cannot make the OLD
prompt emit the false positive it claims to have removed has not shown it can detect
the thing at all, so the run exits 3 (inconclusive) unless the old prompt reproduces
false-positive class (i) by a strict majority on at least one live scene. Same for a
``new`` cell whose every rep failed, for an ``old``/``new`` text that came out equal,
and for an empty ``scp_id``.

Exit codes:
    0  screened; the new prompt cleared both false-positive classes by majority,
       kept the forbidden-term finding, and fired the reverse-direction rule
    1  the screening falsified the fix (a false positive survived, the
       forbidden-term finding died, or the reverse rule never fired)
    2  usage error
    3  inconclusive — nothing to measure, or the harness failed its own self-check
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from langfuse.api import Prompt_Text
from langfuse.model import TextPromptClient
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from yt_flow.config import Settings  # noqa: E402
from yt_flow.pipeline.nodes import scenario, scenario_chain  # noqa: E402

_EXIT_OK, _EXIT_FALSIFIED, _EXIT_USAGE, _EXIT_INCONCLUSIVE = 0, 1, 2, 3

REPO = Path(__file__).resolve().parents[3]
PROMPT = "prompts/scenario/review.md"
BASELINE_REF = "003045c"  # spec front-matter `baseline_revision`
MAX_INFLIGHT = 8

# Stage-3.5 shot fields only. `image_path` is written by the image stage, long
# after the reviewer ran, so including it would show the reviewer a field the
# live call never saw.
_SHOT_FIELDS = ("shot_id", "sentence_indices", "image_prompt", "negative_prompt",
                "camera_angle", "camera_movement", "cast", "location_key")
# Likewise: audio/subtitle/word_timings are post-scenario. `display_narration` is
# not listed because it is substituted INTO `narration` (see `variables()`).
_SCENE_FIELDS = ("scene_num", "title", "kicker", "mood", "narration")

# Issue classification, over every free-text field of an entry.
#
# The buckets are NOT topics — three of them talk about the frozen descriptor.
# What separates them is (a) whether the finding is about a SHOT's prompt or about
# the NARRATION and (b) polarity: absence vs presence. A topic-only classifier was
# tried first and it put "the narration says SCP-049 is gloveless, contradicting
# the Frozen Descriptor" — a perfectly live §4/§9 narration finding — in the same
# bucket as the false positive it must be told apart from. So the primitives below
# are composed in `bucket()`, and `OTHER` is never a silent sink: every entry of
# every rep is printed verbatim under the table and written to the transcript.

# Is the finding about a shot's generated IMAGE prompt at all? `negative_prompt` is
# deliberately NOT here — it has its own bucket, and folding it in made a compliance
# note ("negative_prompt correctly includes person-exclusion terms") classify as the
# reverse-direction finding.
_SHOT_TOPIC = re.compile(
    r"image[_ ]prompts?|visual (?:prompt|description)|shots? S\d|cast (?:array|list)|프롬프트",
    re.IGNORECASE,
)
_FROZEN_TOPIC = re.compile(
    r"entity_visible|frozen(?:[ _]\w+){0,2}[ _]descriptor|visual identity profile|고정 서술자|시각 정체성",
    re.IGNORECASE,
)
# Absence polarity — the shape every one of run 4b35c0ed's false positives took.
# The `contains no` / `none of` families are here so a COMPLIANCE statement ("the
# image_prompt contains no person") is not read as the presence of a person, and so
# "none of the image prompts include the frozen descriptor" — a real old-prompt false
# positive from this screening — is not read as one either.
_ABSENT = re.compile(
    r"do(?:es)?\s+not\s+(?:contain|includ|incorporat|carr|have|name|describ|use)|"
    r"fail(?:s|ed)?\s+to\s+(?:contain|includ|incorporat|carr|use)|"
    r"(?:contain(?:s|ing)?|includ(?:es|ing)?|carr(?:y|ies|ying)|ha[sd]|list(?:s|ing)?)\s+no\b|"
    r"\bnone of\b|\bneither\b|\bwith no\b|\bfree of\b|\bwithout\b|"
    r"\black(?:s|ing|ed)?\b|\bmissing\b|\bomit|\babsent\b|not present|"
    r"누락|부재|빠져|없습니다|없다|없음",
    re.IGNORECASE,
)
# A PRESCRIPTION is not a finding. "…`image_prompt` must remain background-only and
# free of entity details" describes the required state, so reading polarity off the
# whole sentence made the reverse-direction finding look like an absence claim and
# dropped 2 of 3 control reps into `other`. Prescriptive clauses are removed before
# absence is measured; the cost is that a class-(i) false positive phrased ONLY as a
# prescription ("the prompts must carry the descriptor") degrades to `other` rather
# than being counted, which errs toward inconclusive.
_PRESCRIPTION = re.compile(
    r"[^.\n]*\b(?:must|should|shall|needs?\s+to|has\s+to|is\s+required)\b[^.\n]*",
    re.IGNORECASE,
)
# Presence polarity, and specifically the presence of a PERSON/ENTITY — not of a
# forbidden mood word, which is a different (live) finding.
_PRESENT = re.compile(
    r"\b(?:contain|includ|name|describ|mention|carr|ha[sd]|list|explicit)",
    re.IGNORECASE,
)
_ENTITY_THING = re.compile(
    r"SCP-\d|designat|character (?:detail|description)|human figure|silhouette|"
    r"\bperson\b|\bbody\b|\bface\b|\bpose\b|clothing|\bentity\b|배경 전용|background-only",
    re.IGNORECASE,
)
# The person-exclusion contract in `negative_prompt`, treated as a defect.
_NEGATIVE_TOPIC = re.compile(
    r"negative_prompt|person-exclusion|사람 배제|"
    r"person,\s*human figure|silhouette of a person",
    re.IGNORECASE,
)
_REMOVAL = re.compile(
    r"\bremov|\bdelete|\bdrop\b|should not|must not|erroneous|incorrect|삭제|제거",
    re.IGNORECASE,
)
# The mandated person-exclusion list as a contiguous literal (`visual_breakdown.md:201`).
# A `corrections[]` entry can demand its removal *implicitly*, by dropping it from
# `corrected` and naming no verb at all — so that comma-list, and only that shape, is
# matched here. A background plate legitimately describing "a silhouette of a person"
# never writes the comma-list, which is why the loose single terms are not used.
_EXCLUSION_LIST = re.compile(r"person,\s*human figure|character,\s*silhouette of a person",
                             re.IGNORECASE)
# A forbidden-generic-term finding — the LIVE rule, all 11 terms.
_FORBIDDEN = re.compile(
    r"forbidden|금지|\bgeneric term\b|"
    r'"(?:dark|scary|horror|creepy|mysterious|eerie|ominous|sinister|menacing|foreboding|unsettling)"',
    re.IGNORECASE,
)

FROZEN_FP, NEGATIVE_FP, FORBIDDEN = "frozen_fp", "negative_fp", "forbidden"
ENTITY_IN_PROMPT, NARRATION, OTHER = "entity_in_prompt", "narration", "other"
_COLUMNS = (FROZEN_FP, NEGATIVE_FP, FORBIDDEN, ENTITY_IN_PROMPT, NARRATION, OTHER)

# Free-text fields across `issues[]`, `corrections[]` and `grounded_contradictions[]`.
# `corrections[]` is bucketed too because run 4b35c0ed's scene-9 false positive put
# its `negative_prompt` demand ONLY in a correction.
_TEXT_FIELDS = ("field", "description", "correction", "original", "corrected",
                "explanation", "narration_quote", "grounding_quote")
# The fields that state what WAS FOUND. `correction`/`corrected` hold the remedy, and
# a remedy for "the entity is in the plate" naturally describes an absence — so
# polarity is read off these fields only, never off the fix.
_CLAIM_FIELDS = ("field", "description", "explanation", "narration_quote", "original")


def entry_text(entry: dict) -> str:
    return "\n".join(str(entry[f]) for f in _TEXT_FIELDS if entry.get(f))


def claim_text(entry: dict) -> str:
    """What the entry says it FOUND, with prescriptive clauses removed."""
    claim = "\n".join(str(entry[f]) for f in _CLAIM_FIELDS if entry.get(f))
    return _PRESCRIPTION.sub(" ", claim)


def bucket(entry: dict) -> str:
    """The ONE bucket this entry belongs to. Mutually exclusive by construction.

    Exclusivity is not cosmetic: `majority("new", syn, ENTITY_IN_PROMPT)` is the
    only gate that tells "the rule flipped direction" apart from "the rule went
    silent", and an entry that could land in two buckets at once made that gate
    unreadable. `negative_fp` takes precedence — a demand to strip the
    person-exclusion contract is the finding that matters most, whatever else the
    same sentence also says.
    """
    text = entry_text(entry)
    shot, frozen = bool(_SHOT_TOPIC.search(text)), bool(_FROZEN_TOPIC.search(text))
    absent = bool(_ABSENT.search(claim_text(entry)))
    if _NEGATIVE_TOPIC.search(text) and _REMOVAL.search(text):
        return NEGATIVE_FP  # (ii) "remove the person-exclusion terms" — the FP
    if (_EXCLUSION_LIST.search(str(entry.get("original") or ""))
            and not _EXCLUSION_LIST.search(str(entry.get("corrected") or ""))):
        return NEGATIVE_FP  # (ii) again, demanded silently by a `corrections[]` diff
    if frozen and absent and shot:
        return FROZEN_FP  # (i) "the plate omits the frozen descriptor" — the FP
    if shot and not absent and _PRESENT.search(text) and _ENTITY_THING.search(text):
        return ENTITY_IN_PROMPT  # the reverse-direction finding the edit adds
    if frozen and not shot:
        return NARRATION  # a live §4/§9 narration-vs-descriptor contradiction
    if _FORBIDDEN.search(text):
        return FORBIDDEN  # the live forbidden-generic-term rule
    return OTHER


def load_checkpoint(db: Path, thread_prefix: str) -> dict:
    """The last checkpoint of the matching thread carrying a non-empty ``scenes``.

    Lifted from ``14-0-angle-conflict/measure_angle_agreement.py`` (same DB, same
    blob format): deserialization failures go to stderr rather than being
    swallowed, and an ambiguous prefix REFUSES rather than mixing two runs.
    """
    empty: dict = {"scenes": []}
    if not db.exists():
        print(f"no checkpoint DB at {db}", file=sys.stderr)
        return empty
    serde = JsonPlusSerializer()
    found: dict = dict(empty)
    threads: set[str] = set()
    skipped = 0
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT thread_id, checkpoint_id, type, checkpoint FROM checkpoints "
            "WHERE thread_id LIKE ? ORDER BY checkpoint_id",
            (thread_prefix + "%",),
        )
        for thread_id, checkpoint_id, typ, blob in rows:
            threads.add(thread_id)
            try:
                values = serde.loads_typed((typ, blob)).get("channel_values") or {}
            except Exception as exc:  # noqa: BLE001 — a foreign blob is not our problem
                skipped += 1
                print(f"skipped checkpoint {thread_id}/{checkpoint_id}: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            if values.get("scenes"):
                found = {
                    "scenes": values["scenes"],
                    "scp_id": values.get("scp_id") or "",
                    "scp_text": values.get("scp_text") or "",
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                    "quality": values.get("scenario_quality") or {},
                }
    finally:
        conn.close()
    if skipped:
        print(f"{skipped} checkpoint(s) skipped (undeserializable)", file=sys.stderr)
    if len(threads) > 1:
        print(f"prefix '{thread_prefix}' matches {len(threads)} thread_ids "
              f"({', '.join(sorted(threads)[:3])}, …) — refusing to mix runs", file=sys.stderr)
        return empty
    return found


def grounding(db: Path, scp_id: str) -> tuple[str, str]:
    """``(scp_visual_reference, entity_sheet)`` rebuilt from the ``characters``
    rows of this SCP — the roster the run's own cards were cut from.

    ponytail: not the byte-identical research_step output (never persisted), and it
    does not need to be. Both prompt versions receive the SAME string, and the old
    version reproducing the run's false positive on it is the self-check that it is
    faithful enough to screen on.
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT scp_id, canonical_name, visual_descriptor FROM characters "
            "WHERE scp_id LIKE ? ORDER BY scp_id",
            (scp_id + "%",),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return "", ""
    frozen = "\n".join(f"- **{name or key}** (Frozen Descriptor): {desc or ''}".strip()
                       for key, name, desc in rows)
    sheet = "\n".join(f"- {name or key} — {(desc or '').split('.')[0]}" for key, name, desc in rows)
    return frozen, sheet


def prompt_text(version: str, old_ref: str) -> str:
    """The prompt body, or ``""`` if it could not be read (caller bails)."""
    try:
        if version == "new":
            return (REPO / PROMPT).read_text(encoding="utf-8")
        out = subprocess.run(["git", "-C", str(REPO), "show", f"{old_ref}:{PROMPT}"],
                             capture_output=True, text=True, check=True)
        return out.stdout
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"cannot read {version} {PROMPT}: {type(exc).__name__}: "
              f"{str(detail).strip()[:200]}", file=sys.stderr)
        return ""


def client(version: str, text: str) -> TextPromptClient:
    """The runtime's own renderer, over a local file instead of a Langfuse fetch."""
    return TextPromptClient(Prompt_Text(
        type="text", name=f"scenario/review[{version}]", version=0, prompt=text,
        config={}, labels=[], tags=[],
    ))


def variables(scene: dict, scp_id: str, scp_text: str, frozen: str, sheet: str,
              guide: str, total: int, entity_visible: bool | None) -> dict:
    """The reviewer's variable dict, reconstructed — NOT a byte replay.

    ``scenario_chain.review_step`` builds the live dict; this one differs from it in
    six named ways, all forced by what the checkpoint keeps:

    1. ``narration_script`` wraps ``{"scp_id": …, "scenes": [scene]}``; live it is
       ``{**writing, "scenes": [scene]}``, so the live call also carries
       ``writing``'s title/metadata siblings.
    2. Scenes are **field-trimmed** to ``_SCENE_FIELDS`` — the checkpoint scene has
       picked up ``audio_path``/``word_timings``/``subtitle_path``/``audio_duration``
       from stages that ran after the reviewer, and has lost ``writing_step``'s
       ``fact_tags``/``location``/``characters_present``/``color_palette``/``atmosphere``.
    3. ``narration`` is fed from ``display_narration`` when present: the persisted
       ``narration`` is the **TTS-normalized** text ("에스씨피 공사구"), which
       ``tts_normalize_step`` writes *after* the review ran.
    4. ``entity_visible`` is **injected** (scene-level, ``writing.md:219,236-238``),
       because ``writing_step``'s dict is not persisted. This is the field clause
       (a) is about; without it clause (a)'s literal trigger is never exercised.
       The run's own gate warnings quote "entity_visible is set to true for Scene 8"
       and "Scene 9 has entity_visible set to true", so ``True`` is on the record —
       but it is a reconstruction, overridable with ``--entity-visible``.
    5. ``scp_visual_reference``/``entity_sheet`` are rebuilt from ``characters``
       (see ``grounding()``).
    6. ``parse_error: ""`` is set here because ``_call_stage_with_retry`` — which
       normally injects it on attempt 1 — is bypassed. Rendered text therefore
       equals the live **first attempt**; tallies are pre-filter, i.e. they include
       findings the live ``_make_parse`` evidence check would have dropped.

    Shot dicts are trimmed to ``_SHOT_FIELDS`` for the same reason as (2):
    ``image_path`` was written by the image stage, long after the reviewer ran.
    Both prompt versions get the identical dict.
    """
    idx = int(scene["scene_num"]) - 1
    trimmed = {k: scene[k] for k in _SCENE_FIELDS if k in scene}
    if scene.get("display_narration"):
        trimmed["narration"] = scene["display_narration"]
    if entity_visible is not None:
        trimmed["entity_visible"] = entity_visible
    shots = [{k: shot[k] for k in _SHOT_FIELDS if k in shot} for shot in scene.get("shots") or []]
    return {
        "scp_id": scp_id,
        "scp_fact_sheet": scp_text,
        "narration_script": scenario_chain._scene_review_brief(idx, total)
        + json.dumps({"scp_id": scp_id, "scenes": [trimmed]}, ensure_ascii=False),
        "visual_descriptions": json.dumps(shots, ensure_ascii=False),
        "scp_visual_reference": frozen,
        "entity_sheet": sheet,
        "format_guide": guide,
        "glossary_section": "",
        "parse_error": "",
    }


def synthetic(scene: dict) -> dict:
    """The reverse-direction control: the entity put back INTO ``image_prompt``.

    A rule that vanished into silence and a rule that flipped direction look the
    same on the two false-positive cells. This cell is the only thing that tells
    them apart, so it is not optional.

    Every shot is KEPT and only shot 1's prose is prefixed, so this input differs
    from its own baseline in exactly the injected text. Deleting the other shots
    (the first version of this control did) independently violates §6's
    shot-count-vs-sentence-count rule and orphans their ``sentence_indices``,
    which is a second difference and therefore a confound.
    """
    scene = json.loads(json.dumps(scene))
    shots = scene.get("shots") or []
    if shots:
        shots[0]["image_prompt"] = (
            "SCP-049 stands beside an empty steel autopsy table, a tall gaunt figure in a "
            "black hooded plague-doctor robe with a white beaked mask, gloved hands raised "
            "palm-up, its head tilted toward the tiled floor, "
        ) + shots[0].get("image_prompt", "")
    return scene


async def one_call(compiled: TextPromptClient, variables: dict, s: Settings) -> dict:
    """One rep. ``error`` is REPORTED, never counted as "0 issues"."""
    try:
        rendered = compiled.compile(**variables)
        raw, _usage, finish = await scenario._call_gemini(rendered, s)
    except Exception as exc:  # noqa: BLE001
        return {"entries": [], "error": f"{type(exc).__name__}: {exc}", "raw": ""}
    if finish == "length":
        return {"entries": [], "error": "truncated (finish_reason=length)", "raw": raw}
    try:
        data = scenario_chain._parse_yaml(raw)
    except Exception as exc:  # noqa: BLE001 — a YAML failure is a reported cell, not a 0
        return {"entries": [], "raw": raw,
                "error": f"YAML {type(exc).__name__}: {str(exc).splitlines()[0][:120]}"}
    if not isinstance(data, dict):
        return {"entries": [], "raw": raw, "error": f"unparseable payload ({type(data).__name__})"}
    entries = []
    for kind in ("issues", "corrections", "grounded_contradictions"):
        items = data.get(kind)
        if items is None:
            continue
        if not isinstance(items, list):
            return {"entries": [], "raw": raw, "error": f"`{kind}` is not a list"}
        entries += [(kind, item) for item in items if isinstance(item, dict)]
    if data.get("issues") is None:
        return {"entries": [], "raw": raw, "error": "payload carried no `issues` key"}
    return {"entries": entries, "error": "", "raw": raw}


async def run(args) -> int:  # noqa: PLR0911, PLR0912, PLR0915 — one linear screening
    db = Path(Settings().db_path)
    if not db.is_absolute():
        db = REPO / db
    ck = load_checkpoint(db, args.run)
    scenes = ck["scenes"]
    if not scenes:
        print(f"inconclusive: no checkpoint with a non-empty `scenes` for "
              f"thread_id LIKE '{args.run}%'")
        return _EXIT_INCONCLUSIVE

    nums = [sc.get("scene_num") for sc in scenes]
    if any(type(n) is not int for n in nums):
        print(f"inconclusive: checkpoint has a non-integer scene_num ({nums}) — "
              f"positional pairing would be a guess")
        return _EXIT_INCONCLUSIVE
    if len(set(nums)) != len(nums):
        print(f"inconclusive: checkpoint has duplicate scene_num ({nums}) — refusing "
              f"to screen a scene chosen by last-write-wins")
        return _EXIT_INCONCLUSIVE
    if len(set(args.scenes)) != len(args.scenes):
        print(f"inconclusive: --scenes has duplicates ({args.scenes})")
        return _EXIT_INCONCLUSIVE
    by_num = {n: sc for n, sc in zip(nums, scenes, strict=True)}
    missing = [n for n in args.scenes if n not in by_num]
    if missing:
        print(f"inconclusive: run has no scene(s) {missing} (has {sorted(by_num)})")
        return _EXIT_INCONCLUSIVE

    s = Settings()
    scp_id = ck["scp_id"] or args.scp_id
    if not scp_id:
        print("inconclusive: empty scp_id — the `characters LIKE ?` pattern would "
              "degenerate to '%' and rebuild the Visual Identity Profile from every SCP",
              file=sys.stderr)
        return _EXIT_INCONCLUSIVE
    frozen, sheet = grounding(db, scp_id)
    if not frozen:
        print(f"inconclusive: no `characters` rows for {scp_id!r} — the Visual Identity "
              f"Profile would be empty and neither false positive could fire", file=sys.stderr)
        return _EXIT_INCONCLUSIVE
    try:
        guide = (REPO / "prompts" / "scenario" / "format_guide.md").read_text(encoding="utf-8")
    except OSError as exc:
        print(f"inconclusive: cannot read format_guide.md: {exc}", file=sys.stderr)
        return _EXIT_INCONCLUSIVE

    texts = {v: prompt_text(v, args.old_ref) for v in ("old", "new")}
    if not texts["old"] or not texts["new"]:
        return _EXIT_INCONCLUSIVE
    if texts["old"] == texts["new"]:
        print(f"inconclusive: {args.old_ref}:{PROMPT} is byte-identical to the working "
              f"tree — the screening would compare the prompt to itself. Pass "
              f"--old-ref <pre-edit rev>.", file=sys.stderr)
        return _EXIT_INCONCLUSIVE
    compiled = {v: client(v, texts[v]) for v in texts}

    ev = None if args.entity_visible == "off" else (args.entity_visible == "true")
    syn_scene = args.scenes[-1]
    syn = f"{syn_scene}-syn"
    cells: list[tuple[str, str, dict]] = [
        (version, str(n),
         variables(by_num[n], scp_id, ck["scp_text"], frozen, sheet, guide, len(scenes), ev))
        for n in args.scenes for version in ("old", "new")
    ]
    # The reverse-direction control runs on BOTH versions: the old prompt's score
    # here is the baseline the new one must at least match.
    for version in ("old", "new"):
        cells.append((version, syn,
                      variables(synthetic(by_num[syn_scene]), scp_id, ck["scp_text"],
                                frozen, sheet, guide, len(scenes), ev)))

    q = ck["quality"]
    print(f"run {args.run}: screening {PROMPT} old({args.old_ref}) vs new(worktree)")
    print(f"thread_id {ck['thread_id']} @ checkpoint_id {ck['checkpoint_id']}")
    print(f"checkpoint provenance: final_pass_index {q.get('final_pass_index')} | "
          f"retry_scope {q.get('retry_scope')!r} | review_overall_pass "
          f"{q.get('review_overall_pass')} | critic_verdict {q.get('critic_verdict')!r}")
    if q.get("final_pass_index") not in (None, 1):
        print("  ^ CAVEAT: this is POST-repair text — the narration screened here was "
              "already rewritten in response to these very warnings.")
    print(f"scp_id {scp_id} | scenes {args.scenes} | reverse-direction control on "
          f"scene {syn_scene} (cell {syn}) | reps {args.reps} "
          f"(verdicts are STRICT majority: > reps_ok/2, so an even --reps tie is NOT a majority)")
    print(f"entity_visible: {'not injected' if ev is None else f'injected {ev}'} "
          f"(reconstruction — not in the checkpoint; --entity-visible)")
    print("narration: display_narration where present (pre-TTS-normalize), else narration")
    print(f"model {s.gemini_writing_model} (max_tokens {s.gemini_writing_max_tokens}) | "
          f"max {MAX_INFLIGHT} concurrent")
    print(f"cells {len(cells)} x {args.reps} reps = {len(cells) * args.reps} "
          f"text-only LLM calls, GPU 0\n")

    gate = asyncio.Semaphore(MAX_INFLIGHT)

    async def guarded(version: str, variables_: dict) -> dict:
        async with gate:
            return await one_call(compiled[version], variables_, s)

    results = await asyncio.gather(*[
        guarded(version, variables_)
        for version, _label, variables_ in cells for _ in range(args.reps)
    ], return_exceptions=True)

    transcript = Path(__file__).resolve().parent / f"transcript-{time.strftime('%Y%m%dT%H%M%S')}.jsonl"
    tallies: dict[tuple[str, str], Counter] = {}
    errors: dict[tuple[str, str], list[str]] = {}
    detail: list[str] = []
    with transcript.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "kind": "header", "run": args.run, "thread_id": ck["thread_id"],
            "checkpoint_id": ck["checkpoint_id"], "old_ref": args.old_ref,
            "reps": args.reps, "scenes": args.scenes, "synthetic_cell": syn,
            "entity_visible": ev, "model": s.gemini_writing_model,
            "final_pass_index": q.get("final_pass_index"), "retry_scope": q.get("retry_scope"),
        }, ensure_ascii=False) + "\n")
        for cell_index, (version, label, _v) in enumerate(cells):
            key = (version, label)
            tally, failed = Counter(), []
            for rep in range(args.reps):
                result = results[cell_index * args.reps + rep]
                if isinstance(result, BaseException):
                    result = {"entries": [], "raw": "",
                              "error": f"gather: {type(result).__name__}: {result}"}
                line = {"kind": "call", "version": version, "cell": label, "rep": rep + 1,
                        "error": result["error"], "raw": result["raw"], "entries": []}
                if result["error"]:
                    failed.append(f"rep{rep + 1}: {result['error']}")
                    fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                    continue
                tally["reps_ok"] += 1
                seen: set[str] = set()
                for kind, entry in result["entries"]:
                    name = bucket(entry)
                    seen.add(name)
                    line["entries"].append({"collection": kind, "bucket": name, "entry": entry})
                    detail.append(
                        f"  [{version:3} s{label:5} rep{rep + 1}] {name:16} {kind[:12]:12} "
                        f"{str(entry.get('type') or entry.get('field')):22} "
                        f"{str(entry.get('severity') or ''):8} "
                        f"{' '.join(entry_text(entry).split())[:240]}"
                    )
                for name in seen:  # per-rep presence, so 3 quotes of "dark" is still 1 rep
                    tally[name] += 1
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            tallies[key] = tally
            errors[key] = failed

    header = f"{'cell':12} {'reps_ok':>7}" + "".join(f" {c[:10]:>10}" for c in _COLUMNS)
    print(header + "  failures")
    print("(counts are REPS in which the bucket appeared, out of reps_ok — not entry counts;"
          " buckets are mutually exclusive)")
    for version, label, _v in cells:
        tally, failed = tallies[(version, label)], errors[(version, label)]
        row = (f"{version + ' s' + label:12} {tally['reps_ok']:>7}"
               + "".join(f" {tally[c]:>10}" for c in _COLUMNS))
        print(row + f"  {'; '.join(failed) or '-'}")

    print("\nper-entry detail (every entry every rep reported, nothing dropped):")
    for line in detail:
        print(line)
    print(f"\ntranscript: {transcript}")

    def majority(version: str, label: str, name: str) -> bool:
        tally = tallies[(version, label)]
        return tally["reps_ok"] > 0 and tally[name] * 2 > tally["reps_ok"]

    live = [str(n) for n in args.scenes]
    all_cells = live + [syn]
    ok_cells = sum(tallies[(v, cell)]["reps_ok"] for v, cell, _ in cells)
    fp_survivors = [("new", cell, b) for cell in live
                    for b in (FROZEN_FP, NEGATIVE_FP) if majority("new", cell, b)]
    fp_reproduced = [cell for cell in live if majority("old", cell, FROZEN_FP)]
    forbidden_old = [cell for cell in live if majority("old", cell, FORBIDDEN)]
    forbidden_new = [cell for cell in live if majority("new", cell, FORBIDDEN)]
    # The forbidden-term axis is ONE rule, so the run-level hit total is its unit, not
    # per-cell majority membership. A cell whose true rate is ~10-25% crosses the 50%
    # line at random for small `reps`: at reps 3 scene 6 read old 2/3 vs new 1/3 and
    # FALSIFIED, while at reps 9 it read old 1/9 vs new 2/9 — the same PROMPT_POLICY
    # Story 6.10 finding that single-trial zero-tolerance makes a gate un-passable by
    # noise alone. So falsify on a total regression, or on a cell that went from a
    # majority to a flat zero (that is a kill, not a wobble).
    forbidden_total_old = sum(tallies[("old", cell)][FORBIDDEN] for cell in live)
    forbidden_total_new = sum(tallies[("new", cell)][FORBIDDEN] for cell in live)
    forbidden_killed = [cell for cell in forbidden_old
                        if tallies[("new", cell)][FORBIDDEN] == 0]
    unmeasured = [(v, cell) for v in ("old", "new") for cell in all_cells
                  if tallies[(v, cell)]["reps_ok"] == 0]

    print("\nverdict")
    print(f"  self-check — OLD prompt reproduced false-positive class (i) by majority on: "
          f"{fp_reproduced or 'NONE'}")
    print(f"  false positives surviving on NEW (majority): {fp_survivors or 'none'}")
    print(f"  forbidden-term finding by majority — old: {forbidden_old or 'none'} "
          f"new: {forbidden_new or 'none'}")
    print(f"  forbidden-term hits over all live cells — old {forbidden_total_old} "
          f"new {forbidden_total_new} (the gated unit; per-cell majority is descriptive)")
    print(f"  reverse-direction control {syn} (entity IS in image_prompt) — "
          f"old {tallies[('old', syn)][ENTITY_IN_PROMPT]}/{tallies[('old', syn)]['reps_ok']} "
          f"new {tallies[('new', syn)][ENTITY_IN_PROMPT]}/{tallies[('new', syn)]['reps_ok']} reps flagged")

    if not ok_cells:
        print("\ninconclusive: every rep failed — see failures column")
        return _EXIT_INCONCLUSIVE
    if unmeasured:
        print(f"\ninconclusive: cell(s) {unmeasured} have reps_ok == 0 — an unmeasured "
              f"cell reads as cleared, because majority() of nothing is False")
        return _EXIT_INCONCLUSIVE
    if not fp_reproduced:
        print("\ninconclusive: the OLD prompt did not reproduce false-positive class (i) "
              "by majority on any live scene, so this harness has not shown it can detect "
              "the thing the edit removed. 'new = 0' proves nothing here.")
        return _EXIT_INCONCLUSIVE
    if fp_survivors:
        print("\nFALSIFIED: a false-positive class survived the new prompt")
        return _EXIT_FALSIFIED
    if forbidden_total_new < forbidden_total_old:
        print(f"\nFALSIFIED: forbidden-term hits regressed over all live cells "
              f"({forbidden_total_old} -> {forbidden_total_new}) — the edit weakened a live rule")
        return _EXIT_FALSIFIED
    if forbidden_killed:
        print(f"\nFALSIFIED: forbidden-term finding went from a majority to ZERO on "
              f"scene(s) {sorted(forbidden_killed)} — the edit killed a live rule there")
        return _EXIT_FALSIFIED
    if not majority("new", syn, ENTITY_IN_PROMPT):
        print(f"\nFALSIFIED: the reverse-direction rule did not fire on {syn} — the edit "
              f"removed the false positive by going silent, not by flipping direction")
        return _EXIT_FALSIFIED
    return _EXIT_OK


def _selftest() -> int:
    """Classifier self-check. No LLM, no DB — `--selftest` runs only this.

    ponytail: an assert-based function in the module instead of a test file. The
    script is story evidence and moves with the report; a pytest module would put
    the check somewhere the re-derive command does not reach.
    """
    # (ii) The real scene-9 false positive of run 4b35c0ed. It names the frozen
    # descriptor AND demands the negative_prompt edit, so before precedence was
    # introduced it landed in two buckets at once and unread the reverse-rule gate.
    assert bucket({
        "type": "descriptor_violation",
        "description": "Scene 9 has entity_visible set to true, but the visual prompts "
                       "generated in Stage 3.5 omitted the SCP-049 Frozen Descriptor from the "
                       "image prompts and included character terms in negative_prompt.",
        "correction": "remove 'person, human figure, character, silhouette of a person' "
                      "from negative_prompt",
    }) == NEGATIVE_FP
    # The same demand arriving ONLY as a `corrections[]` entry (B6): the live run put
    # it there, so `issues[]`-only bucketing under-counted class (ii) by one.
    assert bucket({
        "field": "visual_description",
        "original": "person, human figure, character, silhouette of a person",
        "corrected": "blurry, watermark, text",
    }) == NEGATIVE_FP
    # A COMPLIANCE statement phrased as negated presence must not be tallied as the
    # reverse-direction finding.
    for text in ("The image_prompt for S00800 contains no person, human figure or "
                 "character, as required.",
                 "S00801's image_prompt is free of any body, face or pose detail.",
                 "negative_prompt correctly includes person-exclusion terms."):
        assert bucket({"description": text}) != ENTITY_IN_PROMPT, text
        assert bucket({"description": text}) != NEGATIVE_FP, text
    # (i) The real scene-8 false positive.
    assert bucket({
        "description": "entity_visible is set to true for Scene 8, but the stage 3.5 image "
                       "prompts omit the required SCP-049 frozen descriptor from the Visual "
                       "Identity Profile.",
    }) == FROZEN_FP
    # The reverse-direction finding the edit adds.
    assert bucket({
        "description": "The image_prompt for S00900 names SCP-049 and describes a hooded "
                       "figure with gloved hands raised palm-up; the plate must be "
                       "background-only.",
    }) == ENTITY_IN_PROMPT
    # A live §4/§9 narration-vs-descriptor contradiction — same topic, different subject.
    assert bucket({
        "description": "The narration says SCP-049 has 장갑도 끼지 않은 bare fingers, which "
                       "contradicts the Frozen Descriptor's dark gloves.",
    }) == NARRATION
    # The live forbidden-generic-term rule.
    assert bucket({
        "description": 'Image prompt 2 contains the forbidden term "dark" ("soft dark blur").',
    }) == FORBIDDEN
    # Real samples from the 2026-08-22 screening that the first classifier misread.
    # (1) The reverse-direction finding whose own sentence prescribes the absence.
    for text in (
        "In shot S00900, the `image_prompt` contains explicit entity/character rendering "
        "prose: \"SCP-049 stands beside an empty steel autopsy table\". `image_prompt` must "
        "remain background-only and free of entity or character details.",
        "Shot S00900 image_prompt contains entity identification and character description "
        "(\"SCP-049 ... gloved hands raised palm-up\"). The background plate must be rendered "
        "empty without entity prose.",
    ):
        assert bucket({"description": text}) == ENTITY_IN_PROMPT, text
    # (2) The class-(i) false positive phrased with "none of".
    assert bucket({
        "description": "`entity_visible` is true and SCP-049 is listed in the cast for shots "
                       "S00600 and S00601, but none of the image prompts include the required "
                       "Frozen Descriptor.",
    }) == FROZEN_FP
    # Nothing this axis knows about.
    assert bucket({"description": "종결어미 -습니다가 4회 연속 반복됩니다."}) == OTHER
    print("selftest: 14 classifier cases OK")
    return _EXIT_OK


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("run", help="thread_id prefix, e.g. 4b35c0ed")
    p.add_argument("--reps", type=int, default=3, help="calls per (version, scene) cell")
    p.add_argument("--scenes", type=int, nargs="+", default=[6, 8, 9],
                   help="the LAST one also carries the reverse-direction control")
    p.add_argument("--scp-id", default="SCP-049", help="fallback when scenes carry no scp_id")
    p.add_argument("--old-ref", default=BASELINE_REF,
                   help=f"git rev for the pre-edit prompt (default {BASELINE_REF}, the "
                        f"spec's baseline_revision — NOT HEAD, which becomes the new "
                        f"prompt the moment this story is committed)")
    p.add_argument("--entity-visible", choices=("true", "false", "off"), default="true",
                   help="inject this scene-level field, absent from the checkpoint "
                        "('off' = do not inject; clause (a) is then untested)")
    p.add_argument("--selftest", action="store_true", help="classifier self-check only")
    try:
        args = p.parse_args(argv[1:])
    except SystemExit:
        return _EXIT_USAGE
    if args.selftest:
        return _selftest()
    if args.reps < 1:
        print("--reps must be >= 1", file=sys.stderr)
        return _EXIT_USAGE
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
