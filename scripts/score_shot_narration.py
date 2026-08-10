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
from yt_flow.services.eval_service import _load_state  # noqa: E402
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
    only: set[str] | None = None, tmp: Path | None = None,
) -> list[dict]:
    """One row per shot, blind call before match call, in scene/shot order."""
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
                mark = "✓" if row["fail_reason"] is None else "✗"
                print(f"  {mark} {row['shot_id']}{' [HOOK]' if row['hook'] else ''}: "
                      f"readable={readable} match={match_score} place={blind.get('place')!r} "
                      f"event={blind.get('event')!r}"
                      + ("" if row["fail_reason"] is None else f"  [FAIL: {row['fail_reason']}]"),
                      flush=True)
                rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["status"] == "scored"]
    failed = [r for r in scored if r["fail_reason"]]
    hook = next((r for r in rows if r["hook"]), None)
    covered = [i for r in rows for i in (r.get("sentence_indices") or [])]
    return {
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
    rows = await score_run(settings, state, args.run,
                           frames=args.frames, reps=args.reps, limit=args.limit)
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
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"rows -> {args.json}")
    return 1 if summary["skipped"] or summary["errored"] else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--run", required=True, help="run id whose checkpoint holds the scenes")
    ap.add_argument("--json", help="write the full report (rows + prompts + summary) here")
    ap.add_argument("--reps", type=int, default=1, help="samples per question; the median is the score")
    ap.add_argument("--frames", choices=("images", "shots"), default="images",
                    help="'images' = the generated plate (default), 'shots' = the composited clip's mid-frame")
    ap.add_argument("--limit", type=int, help="score only the first N shots")
    ap.add_argument("--pair-by", choices=("shot", "sentence"), default="shot",
                    help="'sentence' also emits one row per narration sentence (the covering "
                         "shot's verdict) — the only pairing two legs with different shot counts share")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
