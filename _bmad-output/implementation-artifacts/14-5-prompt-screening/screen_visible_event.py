#!/usr/bin/env python
"""Story 14.5: does the ``visual_breakdown`` edit put THIS SENTENCE'S EVENT in the prompt? GPU 0.

Spec: ``_bmad-output/implementation-artifacts/spec-14-5-narration-plate-pose-match.md``

Screens a generator-prompt change before a single frame is rendered
(`gotcha_screen-a-prompt-change-before-you-render-it`), on the axis 10.4b handed
forward: ``visible_event`` — does the written background prompt carry a visible
trace of the sentence's event, or only a place, a mood, lighting and textures?

    uv run python .../screen_visible_event.py 4b35c0ed --legs shipped --judge-reps 5
    uv run python .../screen_visible_event.py 4b35c0ed --legs old,new --gen-reps 5

Three legs, because two of them answer different questions:

* ``shipped``  — the 43 ``image_prompt`` strings this run actually shipped, judged
  ``--judge-reps`` times. This is the **re-baseline**. 10.4b's 84.9 % (56/66) is NOT
  today's number: those prompts came from run ``8a9a288b``'s scenario (written
  2026-08-07) and ``visual_breakdown.md`` was edited on 2026-08-10 by Story 10.2
  (``9d4ec43``, seeded production v14); 10.4b's own candidate edit was reverted
  byte-identical (``7744af1``). So the CURRENT generator has never been measured.
* ``old``      — regenerate the same 9 scenes with the OLD prompt text
  (``git show <--old-ref>:prompts/scenario/visual_breakdown.md``), ``--gen-reps``
  times. This is the control for **regeneration noise**: comparing shipped text
  against a fresh candidate generation would confound the prompt change with the
  variance of drawing again (`gotcha_same-prompt-reseed-flips-the-viewpoint`).
* ``new``      — the same, with the working-tree prompt. The verdict is ``new``
  vs ``old``; ``shipped`` anchors both to reality.

**The judge is imported, never copied** — ``JUDGE_PROMPT`` / ``judge()`` / ``_parse()``
come from ``10-4b-live-validation/check_prompt_compliance.py`` unchanged, so this
number is on the same instrument as the 84.9 % it replaces. Re-typing the judge
text would make the comparison self-verifying and void
(`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`).

**Blind by construction**, inherited from that judge: one prompt + one sentence per
call, no leg label, no siblings, no scene ordering. The judge cannot tell candidate
from control.

**Reconstructed, not replayed** (the checkpoint does not persist them). Both legs
receive the IDENTICAL dict, so every item below is a divergence from live, never a
difference between legs:

1. ``story_logline`` — never persisted. Rebuilt from ``scp_text``'s opening.
2. ``scene_role`` — ``structure`` is not persisted; passed as ``{}`` (the same path
   ``scenario.py`` takes when writing outran structure).
3. ``location`` / ``characters_present`` / ``color_palette`` / ``atmosphere`` — these
   are ``writing_step`` fields (`gotcha_location-is-a-writing-field-not-a-structure-field`)
   and the persisted scene has lost them, so ``visual_breakdown_step``'s own defaults
   apply.
4. ``cast_by_sentence`` — rebuilt from the shipped shots' ``cast`` + ``sentence_indices``
   (0-based there, 1-based in the step's dict). Authoritative: ``cast_decision_step``
   decided it and the shots carry its output, so this one is a replay, not a guess.
5. ``scp_visual_reference`` / ``entity_sheet`` — rebuilt from the ``characters`` rows
   (14.7's ``grounding()``, reused).
6. Sentences are split from ``display_narration`` when present — the persisted
   ``narration`` is TTS-normalized ("에스씨피 공사구"), written after this stage ran.

The **faithfulness check** is reported, not thresholded: ``old`` regenerated against
``shipped`` on the same axis. A large gap means the reconstruction is not close
enough to screen on, and the report must say so rather than a hidden exit code
deciding it (`gotcha_a-screening-gate-can-fail-on-its-own-threshold`).

**The verdict rides the EVENT-BEARING denominator, not the pooled one**, and the two
can disagree in sign — on run ``4b35c0ed`` the pooled rate FELL 2.81 pp while the
event-bearing rate rose 2.86 pp, because the guardrail improvement removes hits from
the no-event rows. Both are printed and both are stored; a report that quotes one
without the other is incomplete (see ``report.md`` §5).

Exit codes:
    0  screened, and ``new`` beat ``old`` on the EVENT-BEARING rate without losing
       ``present_subject`` and without raising the no-event guardrail
    1  falsified — one of those three failed
    2  usage error
    3  nothing to measure, or a refusal: no such run, no scenes, a leg with zero
       scored rows, too many judge errors (the spec's Block If), unequal scene
       coverage between legs, or ``old``/``new`` prompt texts that are identical
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROMPT = "prompts/scenario/visual_breakdown.md"
sys.path.insert(0, str(REPO / "src"))

_EXIT_OK, _EXIT_FALSIFIED, _EXIT_USAGE, _EXIT_NOTHING = 0, 1, 2, 3


def _load(path: Path, name: str):
    """Import a sibling story's harness by path — their directories are not modules."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ARTIFACTS = REPO / "_bmad-output" / "implementation-artifacts"
# The judge, unchanged. Importing this also chdir's to REPO and puts src on the path.
GATE = _load(ARTIFACTS / "10-4b-live-validation" / "check_prompt_compliance.py", "gate_10_4b")
# 14.7's checkpoint loader, grounding rebuild and local-file prompt renderer.
SCREEN147 = _load(ARTIFACTS / "14-7-prompt-screening" / "screen_review_prompt.py", "screen_14_7")

from yt_flow.config import Settings  # noqa: E402
from yt_flow.pipeline.nodes import scenario  # noqa: E402
from yt_flow.pipeline.nodes import scenario_chain  # noqa: E402
from yt_flow.services import prompt_service  # noqa: E402


def prompt_body(version: str, old_ref: str) -> str:
    """The generator prompt: working tree for ``new``, ``git show`` for ``old``."""
    if version == "new":
        return (REPO / PROMPT).read_text(encoding="utf-8")
    try:
        out = subprocess.run(["git", "-C", str(REPO), "show", f"{old_ref}:{PROMPT}"],
                             capture_output=True, text=True, check=True)
        return out.stdout
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"cannot read {version} {PROMPT}: {type(exc).__name__}: "
              f"{str(detail).strip()[:200]}", file=sys.stderr)
        return ""


def logline(scp_id: str, scp_text: str) -> str:
    """Divergence (1): ``story_logline`` is not persisted. Same string for both legs."""
    head = " ".join((scp_text or "").split())[:400]
    return f"{scp_id}: {head}" if head else scp_id


def cast_by_sentence(scene: dict) -> dict[int, list]:
    """Divergence (4) — a replay, not a guess: ``cast_decision_step``'s output rides
    the shipped shots. ``sentence_indices`` is 0-based; the step's dict is 1-based
    (``_cast_union`` walks ``range(start, end + 1)`` over sentence NUMBERS)."""
    out: dict[int, list] = {}
    for shot in scene.get("shots") or []:
        for idx in shot.get("sentence_indices") or []:
            if isinstance(idx, int):
                out.setdefault(idx + 1, list(shot.get("cast") or []))
    return out


def sentences_of(scene: dict) -> list[str]:
    """Divergence (6): the un-normalized narration when the run kept it."""
    return scenario_chain.split_sentences(scene.get("display_narration") or scene.get("narration") or "")


def shipped_rows(scenes: list[dict]) -> list[dict]:
    """One row per shipped shot. Empty ``image_prompt`` (effect/transition sentences)
    is excluded from the denominator and counted separately — a rate without its
    denominator is not a measurement (`gotcha_a-measurement-without-its-sample-band`)."""
    rows: list[dict] = []
    for scene in scenes:
        sentences = sentences_of(scene)
        for shot in scene.get("shots") or []:
            picked = [sentences[i] for i in sorted(shot.get("sentence_indices") or [])
                      if 0 <= i < len(sentences)]
            rows.append({"scene_num": scene.get("scene_num"), "shot_id": shot.get("shot_id"),
                         "sentence": "\n".join(picked),
                         "image_prompt": shot.get("image_prompt") or ""})
    return rows


async def regenerate(version: str, text: str, scenes: list[dict], scp_id: str, scp_text: str,
                     frozen: str, sheet: str, rep: int, s: Settings,
                     limit: asyncio.Semaphore) -> list[dict]:
    """One generation rep of all scenes under one prompt version.

    ``visual_breakdown_step`` is the real stage — its parse, its ordered-cover
    validation, its cast attachment, its truncation re-roll. Only the prompt FETCH is
    redirected, through the seam the tests already use (``prompt_service.get_prompt``),
    so nothing has to be seeded to screen it.
    """
    compiled = SCREEN147.client(f"visual_breakdown[{version}]", text)
    rows: list[dict] = []
    failures: list[dict] = []

    async def one(scene: dict) -> list[dict]:
        sentences = sentences_of(scene)
        async with limit:
            try:
                shots = await scenario_chain.visual_breakdown_step(
                    scp_id, scene, sentences, cast_by_sentence(scene), frozen, sheet,
                    logline(scp_id, scp_text), {}, s, scenario._call_deepseek,
                )
            except Exception as exc:  # noqa: BLE001 — a failed scene is a reported cell, not a crash
                # RECORDED, not just printed. A scene that raises every rep would otherwise
                # leave the leg's rate computed over a smaller, easier slate while the report
                # reads as complete — and generation failures correlate with the hardest
                # scenes, so the bias runs toward flattering whichever leg failed more.
                failures.append({"rep": rep, "scene_num": scene.get("scene_num"),
                                 "error": f"{type(exc).__name__}: {exc}"})
                print(f"  ! {version} rep{rep} scene {scene.get('scene_num')}: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                return []
        out = []
        # 0-BASED, matching production `scenario_chain.py:3342`
        # (`for i, raw_shot in enumerate(raw_shots)` → `S{scene:03d}{i:02d}`). The first
        # version of this line used `start=1` and minted `S00101…` against the shipped
        # leg's `S00100…`; every cross-leg comparison keyed on `shot_id` then compared
        # position N against position N+1. Analysis joins on the SENTENCE for that reason
        # (see `report.md` §4) — this id is a label, and it must still be the real one.
        for position, shot in enumerate(shots):
            start, end = int(shot["sentence_start"]), int(shot["sentence_end"])
            picked = [sentences[i - 1] for i in range(start, end + 1) if 1 <= i <= len(sentences)]
            out.append({"scene_num": scene.get("scene_num"),
                        "shot_id": f"S{int(scene.get('scene_num') or 0):03d}{position:02d}",
                        "sentence": "\n".join(picked),
                        "image_prompt": shot.get("image_prompt") or "",
                        "cast_n": len(shot.get("cast") or [])})
        return out

    original = prompt_service.get_prompt
    prompt_service.get_prompt = lambda name, **kw: (  # type: ignore[assignment]
        compiled if name == "scenario/visual_breakdown" else original(name, **kw))
    try:
        for produced in await asyncio.gather(*(one(scene) for scene in scenes),
                                             return_exceptions=True):
            if isinstance(produced, BaseException):
                failures.append({"rep": rep, "scene_num": None,
                                 "error": f"{type(produced).__name__}: {produced}"})
                print(f"  ! {version} rep{rep}: {type(produced).__name__}: {produced}",
                      file=sys.stderr, flush=True)
                continue
            rows.extend(produced)
    finally:
        prompt_service.get_prompt = original  # type: ignore[assignment]
    return rows, failures


_EVENT_PROMPT = """You are reading ONE sentence of Korean narration from an SCP documentary video.

The sentence:
\"\"\"
{sentence}
\"\"\"

Answer ONE yes/no question about the SENTENCE ALONE. You are not shown any image or
image prompt, and you must not speculate about one.

`has_event` — does this sentence state that something HAPPENS or CHANGES: an action, a
motion, an onset, a collapse, a contact, an utterance, an arrival, a failure? Answer
false if the sentence only describes an appearance, a physical trait, an identity
("the figure is SCP-049"), a standing state, a rhetorical question, or quoted document
/ procedure text — anything where nothing occurs.

Reply with a single JSON object and nothing else:
{{"has_event": true or false}}"""


async def classify_sentences(rows: list[dict], store: dict, s: Settings,
                             limit: asyncio.Semaphore, reps: int = 5) -> dict[str, bool]:
    """``{sentence: has_event}`` — the DENOMINATOR SPLIT, judged from the narration only.

    This is not the confound Story 14.0 §4-5 measured. That one decomposed propositions
    out of ``image_prompt`` and then asked a VLM about them, so the question carried its
    own answer and unreadable frames scored HIGHEST. This classifier never sees an
    ``image_prompt`` — it reads the Korean sentence, is identical across legs, and is
    computed once. It cannot flatter a candidate prompt because it does not know one
    exists.

    It exists because the re-baseline's 13 failures are not one class. Eight of them are
    sentences whose entire content is the entity's appearance, its identity, or quoted
    containment-procedure text — for those a background plate has no event to carry, and
    a prompt that invented one would be inventing narration (exactly what Story 10.4
    warned against). Pooling them with the real misses puts an unreachable floor in the
    denominator and points the edit at the wrong rows.
    """
    # The cache is keyed to the classifier that produced it. Editing `_EVENT_PROMPT` or
    # bumping the judge model must not silently reuse the previous instrument's labels.
    fingerprint = hashlib.sha256(
        (_EVENT_PROMPT + "|" + GATE.JUDGE_MODEL + f"|reps={reps}").encode()).hexdigest()[:16]
    if store.get("has_event_fingerprint") != fingerprint:
        store["has_event"] = {}
    store["has_event_fingerprint"] = fingerprint
    cache: dict[str, bool] = dict(store.get("has_event") or {})
    # Keyed on the INDIVIDUAL sentence, not the row: a merged shot's `sentence` is several
    # joined with "\n", and classifying that blob would leave its parts unclassified.
    parts = {part for row in rows for part in row["sentence"].split("\n") if part.strip()}
    todo = sorted(parts - set(cache))

    async def once(sentence: str) -> bool | None:
        body = {"model": GATE.JUDGE_MODEL,
                "messages": [{"role": "user", "content": _EVENT_PROMPT.format(sentence=sentence)}],
                "max_tokens": s.character_vision_max_tokens, "temperature": 0}
        for attempt in range(2):
            try:
                async with GATE.httpx.AsyncClient(timeout=GATE.httpx.Timeout(120.0)) as client:
                    resp = await client.post(
                        GATE._DASHSCOPE_VISION_ENDPOINT,
                        headers={"Authorization": f"Bearer {s.character_vision_api_key}"},
                        json=body)
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"]
                verdict = json.loads(text[text.index("{"):text.rindex("}") + 1])
                if not isinstance(verdict.get("has_event"), bool):
                    raise ValueError(f"has_event={verdict.get('has_event')!r} is not a boolean")
                return verdict["has_event"]
            except Exception as exc:  # noqa: BLE001
                if attempt == 1:
                    print(f"  ! classify: {type(exc).__name__}: {exc}", file=sys.stderr,
                          flush=True)
        return None

    async def one(sentence: str) -> None:
        """`reps` votes, majority wins; a tie or an all-error sentence stays UNCLASSIFIED.

        The classifier defines the headline's denominator, so it gets the same `반복 ≥5`
        discipline the spec imposes on everything else. n=1 here would make one sentence's
        coin-flip move the target axis by ~3.6 pp on a 28-shot denominator.
        """
        async with limit:
            votes = [v for v in [await once(sentence) for _ in range(reps)] if v is not None]
        if not votes:
            return
        yes = sum(votes)
        if yes * 2 == len(votes):
            print(f"  ~ classify tie ({yes}/{len(votes)}), left unclassified: "
                  f"{sentence[:40]}", file=sys.stderr, flush=True)
            return
        cache[sentence] = yes * 2 > len(votes)
        unanimous.append(yes in (0, len(votes)))

    unanimous: list[bool] = []
    if todo:
        print(f"classifying {len(todo)} distinct sentences for has_event "
              f"({reps} reps each, majority)", flush=True)
        await asyncio.gather(*(one(sentence) for sentence in todo))
        if unanimous:
            print(f"  classifier unanimity: {sum(unanimous)}/{len(unanimous)}", flush=True)
            store["has_event_unanimous"] = f"{sum(unanimous)}/{len(unanimous)}"
    store["has_event"] = cache
    for row in rows:
        # A merged shot covers several sentences; it inherits an event if ANY of them has
        # one, because the shot is answerable for all of them. Unclassified -> None, which
        # `tally` reports as its own bucket rather than silently joining either side.
        wanted = [part for part in row["sentence"].split("\n") if part.strip()]
        parts = [cache[part] for part in wanted if part in cache]
        # PARTIAL classification is also None. `any([False])` on a 2-sentence shot whose
        # first sentence failed to classify would file the shot as a guardrail row on the
        # strength of half its content; only a COMPLETE reading decides a denominator.
        row["has_event"] = (any(parts) if len(parts) == len(wanted) and wanted else None)
    return cache


async def judge_all(rows: list[dict], s: Settings, limit: asyncio.Semaphore) -> None:
    """Fill each row in place with the imported judge's two booleans."""
    async def one(row: dict) -> None:
        if not row["image_prompt"].strip():
            row["skipped"] = "empty image_prompt"
            return
        async with limit:
            try:
                row.update(await GATE.judge(s, row["sentence"], row["image_prompt"]))
            except Exception as exc:  # noqa: BLE001 — an unjudged prompt is data, not a crash
                row["error"] = f"{type(exc).__name__}: {exc}"
                print(f"  ! judge {row.get('leg')}/{row.get('rep')}/{row['shot_id']}: "
                      f"{row['error']}", file=sys.stderr, flush=True)
    await asyncio.gather(*(one(row) for row in rows))


def _rate(rows: list[dict], field: str) -> dict:
    """``rate`` is ALWAYS present. An empty slice returning ``{"n": 0}`` alone made every
    consumer (`verdict`, the faithfulness check, `paired_test`) a `KeyError` away from a
    traceback in the one case that matters: a classifier that labelled nothing."""
    if not rows:
        return {"n": 0, "hits": 0, "rate": None}
    hits = sum(bool(r[field]) for r in rows)
    return {"n": len(rows), "hits": hits, "rate": round(hits / len(rows), 4)}


def tally(rows: list[dict]) -> dict:
    """Pooled counts WITH denominators, split by ``has_event``, plus per-rep rates.

    ``event_bearing`` is the headline: the rows where a background plate CAN carry the
    sentence's event. ``no_event`` is reported beside it and never pooled into it — a
    false there is the correct answer, so mixing them would make the metric reward
    inventing narration.
    """
    scored = [r for r in rows if "present_subject" in r]
    out: dict = {"rows": len(rows), "scored": len(scored),
                 "empty_prompt": sum("skipped" in r for r in rows),
                 "errored": sum("error" in r for r in rows)}
    if not scored:
        return out
    bearing = [r for r in scored if r.get("has_event") is True]
    no_event = [r for r in scored if r.get("has_event") is False]
    out.update({
        "pooled_visible_event": _rate(scored, "visible_event"),
        "event_bearing_visible_event": _rate(bearing, "visible_event"),
        "no_event_visible_event": _rate(no_event, "visible_event"),
        "unclassified": sum(r.get("has_event") is None for r in scored),
        "present_subject": _rate(scored, "present_subject"),
        "failing_visible_event": sorted({r["shot_id"] for r in bearing if not r["visible_event"]}),
        "failing_visible_event_no_event_rows": sorted(
            {r["shot_id"] for r in no_event if not r["visible_event"]}),
        "failing_present_subject": sorted({r["shot_id"] for r in scored
                                           if not r["present_subject"]}),
    })
    per_rep = {}
    for rep in sorted({r.get("rep", 0) for r in scored}):
        cell = [r for r in bearing if r.get("rep", 0) == rep]
        per_rep[rep] = _rate(cell, "visible_event")
    out["per_rep_event_bearing"] = per_rep
    rates = [v["rate"] for v in per_rep.values() if v.get("n")]
    if rates:
        out["per_rep_spread"] = {"min": min(rates), "max": max(rates),
                                 "mean": round(sum(rates) / len(rates), 4)}
    return out


async def run(args) -> int:
    db = REPO / "yt_flow.db"
    found = SCREEN147.load_checkpoint(db, args.run)
    scenes = found.get("scenes") or []
    if not scenes:
        print(f"nothing to measure for thread_id LIKE '{args.run}%'", file=sys.stderr)
        return _EXIT_NOTHING
    scp_id = found.get("scp_id") or ""
    frozen, sheet = SCREEN147.grounding(db, scp_id)
    s = Settings()  # type: ignore[call-arg]
    if not s.character_vision_api_key:
        print("YTFLOW_CHARACTER_VISION_API_KEY is not set — this is a live judgement",
              file=sys.stderr)
        return _EXIT_USAGE

    legs = [leg.strip() for leg in args.legs.split(",") if leg.strip()]
    unknown = [leg for leg in legs if leg not in ("shipped", "old", "new")]
    if unknown:
        # `--legs New` used to fall through `prompt_body`'s else-branch and measure the OLD
        # text under a leg name no verdict looks for — then exit 0 with no verdict at all.
        print(f"unknown leg(s) {unknown}; choose from shipped, old, new", file=sys.stderr)
        return _EXIT_USAGE
    if "old" in legs and "new" in legs:
        if prompt_body("old", args.old_ref).strip() == prompt_body("new", args.old_ref).strip():
            print(f"the working tree {PROMPT} is identical to {args.old_ref} — there is no "
                  "edit to screen (14.7's harness halts on the same condition)",
                  file=sys.stderr)
            return _EXIT_NOTHING
    out_path = HERE / "visible_event.json"
    store: dict = {}
    if out_path.is_file() and not args.fresh:
        store = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"reusing {out_path.name} ({', '.join(store.get('legs', {}))})", flush=True)
    store.setdefault("legs", {})
    store["sample_band"] = {
        "run": args.run, "thread_id": found.get("thread_id"),
        "checkpoint_id": found.get("checkpoint_id"), "scp_id": scp_id,
        "scenes": len(scenes), "shipped_shots": sum(len(sc.get("shots") or []) for sc in scenes),
        "judge_model": GATE.JUDGE_MODEL, "endpoint": GATE._DASHSCOPE_VISION_ENDPOINT,
        "generator_model": "deepseek (scenario._call_deepseek)",
        "old_ref": args.old_ref, "gen_reps": args.gen_reps, "judge_reps": args.judge_reps,
        "judge_prompt_sha_source": str(
            (ARTIFACTS / "10-4b-live-validation" / "check_prompt_compliance.py").relative_to(REPO)),
    }
    print(json.dumps(store["sample_band"], indent=2, ensure_ascii=False), flush=True)

    if args.retally:
        # Re-derive the denominators from the STORED judged rows without spending a single
        # judge or generation call. Added when review found the classifier had run at n=1
        # while defining the headline's denominator: the fix is a better classifier over the
        # same evidence, not a fresh (and differently-drawn) set of prompts.
        if not store.get("legs"):
            print("nothing stored to re-tally", file=sys.stderr)
            return _EXIT_NOTHING
        every = [row for leg in store["legs"] for row in store["legs"][leg]["rows"]]
        await classify_sentences(every, store, s, asyncio.Semaphore(args.judge_concurrency),
                                 reps=args.classify_reps)
        for leg in store["legs"]:
            store["legs"][leg]["tally"] = tally(store["legs"][leg]["rows"])
            print(f"[{leg}] " + json.dumps(
                {k: v for k, v in store["legs"][leg]["tally"].items()
                 if k.endswith("visible_event") or k in ("scored", "unclassified",
                                                         "empty_prompt", "present_subject")},
                ensure_ascii=False), flush=True)
        out_path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nre-tallied -> {out_path.name}", flush=True)
        return _EXIT_OK

    gen_limit = asyncio.Semaphore(args.gen_concurrency)
    judge_limit = asyncio.Semaphore(args.judge_concurrency)
    attrition: list[dict] = []
    t0 = time.perf_counter()

    for leg in legs:
        rows: list[dict] = []
        if leg == "shipped":
            for rep in range(1, args.judge_reps + 1):
                for row in shipped_rows(scenes):
                    rows.append({**row, "leg": leg, "rep": rep})
        else:
            text = prompt_body(leg, args.old_ref)
            if not text.strip():
                return _EXIT_USAGE
            for rep in range(1, args.gen_reps + 1):
                produced, failed = await regenerate(leg, text, scenes, scp_id,
                                                    found.get("scp_text") or "", frozen, sheet,
                                                    rep, s, gen_limit)
                rows.extend({**row, "leg": leg, "rep": rep} for row in produced)
                attrition.extend(failed)
                print(f"  {leg} rep{rep}: {len(produced)} shots generated "
                      f"({time.perf_counter() - t0:.0f}s)", flush=True)
        await classify_sentences(rows, store, s, judge_limit, reps=args.classify_reps)
        await judge_all(rows, s, judge_limit)
        errored = sum("error" in r for r in rows)
        if errored > args.max_judge_errors:
            print(f"{errored} judge errors on leg {leg} (> {args.max_judge_errors}) — "
                  "HALT rather than report a partial distribution as the baseline "
                  "(the spec's Block If)", file=sys.stderr)
            return _EXIT_NOTHING
        store["legs"][leg] = {
            "tally": tally(rows), "rows": rows,
            # Per-leg provenance. Without it a stale leg from a different run, a different
            # `--old-ref`, or a since-edited prompt silently enters the comparison, and
            # `sample_band` (stamped by the LAST invocation) would not reveal it.
            "fingerprint": {
                "run": args.run, "thread_id": found.get("thread_id"),
                "prompt_sha256": hashlib.sha256(
                    (prompt_body(leg, args.old_ref) if leg != "shipped" else "").encode()
                ).hexdigest()[:16],
                "old_ref": args.old_ref if leg == "old" else None,
                "gen_reps": args.gen_reps if leg != "shipped" else None,
                "judge_reps": args.judge_reps if leg == "shipped" else 1,
            },
            "attrition": [f for f in attrition],
        }
        attrition.clear()
        out_path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[{leg}] " + json.dumps(
            {k: v for k, v in store["legs"][leg]["tally"].items()
             if k not in ("failing_visible_event", "failing_present_subject")},
            indent=2, ensure_ascii=False), flush=True)

    tallies = {leg: store["legs"][leg]["tally"] for leg in store["legs"]}
    if any(not t.get("scored") for t in tallies.values()):
        print("a leg scored zero rows — nothing to compare", file=sys.stderr)
        return _EXIT_NOTHING
    # A cached leg from another run / ref / prompt revision is not a control.
    runs = {store["legs"][leg].get("fingerprint", {}).get("run") for leg in store["legs"]
            if store["legs"][leg].get("fingerprint")}
    if len(runs) > 1:
        print(f"legs come from different runs {sorted(runs)} — refusing to compare",
              file=sys.stderr)
        return _EXIT_NOTHING
    for leg in ("old", "new"):
        att = store["legs"].get(leg, {}).get("attrition") or []
        if att:
            print(f"leg {leg}: {len(att)} scene generation(s) failed — the legs do not "
                  f"cover the same slate; refusing a verdict. {att[:3]}", file=sys.stderr)
            return _EXIT_NOTHING
    if "shipped" in tallies and "old" in tallies:
        gap = round(tallies["old"]["event_bearing_visible_event"]["rate"]
                    - tallies["shipped"]["event_bearing_visible_event"]["rate"], 4)
        store["faithfulness_check"] = {
            "old_regen_minus_shipped_visible_event": gap,
            "note": ("Reported, never thresholded. A large gap means the reconstruction "
                     "(see module docstring) is not close enough to screen on; that is a "
                     "finding for report.md, not a hidden exit code."),
        }
        print(f"\nfaithfulness: old-regen − shipped = {gap:+.4f}", flush=True)
    verdict = None
    if "old" in tallies and "new" in tallies:
        # The verdict rides the event-bearing denominator only. The no-event delta is
        # reported as a GUARDRAIL: it must not rise, because a rise there means the edit
        # taught the model to invent events for description sentences.
        d_event = round(tallies["new"]["event_bearing_visible_event"]["rate"]
                        - tallies["old"]["event_bearing_visible_event"]["rate"], 4)
        d_present = round(tallies["new"]["present_subject"]["rate"]
                          - tallies["old"]["present_subject"]["rate"], 4)
        d_noevent = round(tallies["new"]["no_event_visible_event"]["rate"]
                          - tallies["old"]["no_event_visible_event"]["rate"], 4)
        # The guardrail is a PASS CONDITION, not a footnote. Documented as "must not rise"
        # while sitting outside the boolean, it would have let `d_event=+0.01` with
        # `d_noevent=+0.20` — the edit teaching the model to invent events for description
        # sentences — exit 0.
        verdict = {"event_bearing_delta": d_event, "present_subject_delta": d_present,
                   "no_event_delta_guardrail": d_noevent,
                   "pooled_delta_reported_not_gated": round(
                       (tallies["new"]["pooled_visible_event"]["rate"] or 0)
                       - (tallies["old"]["pooled_visible_event"]["rate"] or 0), 4),
                   "passed": bool(d_event > 0 and d_present >= 0 and d_noevent <= 0)}
        store["verdict"] = verdict
        print(f"\nverdict: event-bearing {d_event:+.4f}, present_subject {d_present:+.4f}, "
              f"no-event guardrail {d_noevent:+.4f}, "
              f"POOLED {verdict['pooled_delta_reported_not_gated']:+.4f} (reported, not gated) "
              f"-> {'PASS' if verdict['passed'] else 'FALSIFIED'}", flush=True)
    out_path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nelapsed {time.perf_counter() - t0:.0f}s -> {out_path.name}", flush=True)
    if verdict is not None and not verdict["passed"]:
        return _EXIT_FALSIFIED
    return _EXIT_OK


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("run", help="thread_id prefix of the run to screen, e.g. 4b35c0ed")
    p.add_argument("--legs", default="shipped",
                   help="comma-separated: shipped, old, new (default: shipped)")
    p.add_argument("--gen-reps", type=int, default=5, help="generation reps per old/new leg")
    p.add_argument("--judge-reps", type=int, default=5, help="judge reps for the shipped leg")
    p.add_argument("--old-ref", default="7485e57",
                   help="git ref for the OLD prompt (default: the spec's baseline_revision)")
    p.add_argument("--classify-reps", type=int, default=5,
                   help="has_event votes per sentence (majority; ties stay unclassified)")
    p.add_argument("--max-judge-errors", type=int, default=5,
                   help="the spec's Block If: more errored rows than this on a leg HALTs")
    p.add_argument("--gen-concurrency", type=int, default=4)
    p.add_argument("--judge-concurrency", type=int, default=6)
    p.add_argument("--fresh", action="store_true", help="ignore any cached visible_event.json")
    p.add_argument("--retally", action="store_true",
                   help="re-classify and recompute tallies from stored rows; no judge calls")
    args = p.parse_args(argv)
    for name in ("gen_reps", "judge_reps", "classify_reps", "gen_concurrency",
                 "judge_concurrency"):
        if getattr(args, name) < 1:
            # Semaphore(0) hangs forever with no output; Semaphore(-1) raises deep in the
            # run after the checkpoint read. Both are usage errors, not runtime surprises.
            p.error(f"--{name.replace('_', '-')} must be >= 1")
    if args.max_judge_errors < 0:
        p.error("--max-judge-errors must be >= 0")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
