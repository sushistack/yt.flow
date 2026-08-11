#!/usr/bin/env python
"""Story 10.4b — does the new requirement actually land in the written prompts? No GPU.

**This is a diagnostic gate, NOT the pre-registered verdict.** PRE-REGISTRATION.md fixes the
verdict on rendered frames (paired boolean ``readable``); this script never decides seeding.
It exists to answer one cheap question before ~6 GPU-hours are spent on the render A/B:

    did the model's PROMPTS change in the direction the instruction demanded?

If compliance does not rise, rendering them is pointless and the story needs rescoping. If it
does rise, the render A/B is worth its cost and this gives the attribution layer for it.

    uv run python _bmad-output/implementation-artifacts/10-4b-live-validation/check_prompt_compliance.py

Reads the prompts both legs already wrote (``ab_old_scenes.json`` / ``ab_new_scenes.json``,
66 and 63 shots) and asks a text-only judge two booleans per prompt:

* ``present_subject`` — is the prompt's subject a physically present object/surface/trace,
  rather than an emptiness ("open air", "a blank wall", "the space where something should be")?
* ``visible_event`` — does the prompt put at least one visible mark/displacement/residue of
  THIS sentence's event in the frame?

Those are the two halves of the requirement 10.4b added, so this measures the instruction
directly instead of through a keyword list. The marker-count in ``run_absence_ab.py`` stays as
a crude cross-check; this replaces it as the primary compliance number, because a keyword list
is not the mechanism (`gotcha_person-token-regex-is-unusable-on-image-prompt`).

**Blind by construction:** each call carries one prompt and one sentence and nothing else — no
leg label, no scene ordering, no sibling prompts. The judge cannot tell candidate from control,
so it cannot flatter either.

``qwen-plus`` on the DashScope endpoint under the vision key — the same text model Story 13.2's
question generation uses, verified on that endpoint. No new provider, no new credential, no GPU.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

import httpx  # noqa: E402

from yt_flow.config import Settings  # noqa: E402
from yt_flow.pipeline.nodes.scenario_chain import split_sentences  # noqa: E402
from yt_flow.services.vision_check import _DASHSCOPE_VISION_ENDPOINT  # noqa: E402

HERE = Path(__file__).parent
JUDGE_MODEL = "qwen-plus"

JUDGE_PROMPT = """You are auditing ONE background-image prompt written for ONE sentence of Korean
narration in an animated SCP video. The image is a BACKGROUND PLATE: people are drawn separately
as character cards and composited on top afterwards, so a prompt containing no person is correct
and is never a defect.

The narration sentence:
\"\"\"
{sentence}
\"\"\"

The background prompt written for it:
\"\"\"
{prompt}
\"\"\"

Answer two independent yes/no questions about the PROMPT TEXT (not about any image):

1. `present_subject` — is the main subject of this prompt a physically present thing: an object,
   a surface, or a trace/mark that exists? Answer false if the subject is an absence or a void —
   "open air", "empty floor", "a blank wall", "featureless expanse", "the space where something
   should be", "no visible subject". A large empty AREA is fine as long as some present object or
   mark is the subject within it.

2. `visible_event` — does the prompt place at least one VISIBLE trace of this sentence's event in
   the frame: a mark, a displacement, damage, residue, something out of place, an aftermath
   detail? Answer false if the prompt only establishes a place, a mood, lighting and textures with
   nothing indicating that anything happened. Do NOT require the people to be shown — a body,
   face or gesture is composited later and its absence is never a reason to answer false; judge
   only whether the environment carries a consequence.

Reply with a single JSON object and nothing else:
{{"present_subject": true or false, "visible_event": true or false}}"""


def _parse(text: str) -> dict:
    if "{" not in text or "}" not in text:
        raise ValueError(f"no JSON object in reply: {text[:120]!r}")
    verdict = json.loads(text[text.index("{"):text.rindex("}") + 1])
    if not isinstance(verdict, dict):
        raise ValueError(f"verdict is not an object: {verdict!r}")
    for field in ("present_subject", "visible_event"):
        if not isinstance(verdict.get(field), bool):
            raise ValueError(f"{field}={verdict.get(field)!r} is not a boolean")
    return verdict


async def judge(settings: Settings, sentence: str, prompt: str) -> dict:
    """One text-only call, retried once — a chatty reply gets one more chance."""
    body = {
        "model": JUDGE_MODEL,
        "messages": [{"role": "user", "content": JUDGE_PROMPT.format(
            sentence=sentence, prompt=prompt)}],
        "max_tokens": settings.character_vision_max_tokens,
        "temperature": 0,
    }
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                resp = await client.post(
                    _DASHSCOPE_VISION_ENDPOINT,
                    headers={"Authorization": f"Bearer {settings.character_vision_api_key}"},
                    json=body)
            resp.raise_for_status()
            return _parse(resp.json()["choices"][0]["message"]["content"])
        except Exception:  # noqa: BLE001 — retried once, then it is this row's error
            if attempt == 1:
                raise
    raise AssertionError("unreachable")


def rows_of(leg: str) -> list[dict]:
    """One row per shot: its sentences (joined, as the scorer does) and its prompt."""
    scenes = json.loads((HERE / f"ab_{leg}_scenes.json").read_text(encoding="utf-8"))
    out = []
    for scene in scenes:
        sentences = split_sentences(scene["narration"])
        for shot in scene["shots"]:
            picked = [sentences[i] for i in sorted(shot["sentence_indices"])
                      if 0 <= i < len(sentences)]
            out.append({"leg": leg, "scene_num": scene["scene_num"], "shot_id": shot["shot_id"],
                        "sentence_indices": shot["sentence_indices"],
                        "sentence": "\n".join(picked), "image_prompt": shot["image_prompt"]})
    return out


def summarize(rows: list[dict]) -> dict:
    scored = [r for r in rows if "error" not in r]
    n = len(scored)
    if not n:
        return {"shots": len(rows), "scored": 0, "errored": len(rows) - n}
    present = sum(r["present_subject"] for r in scored)
    event = sum(r["visible_event"] for r in scored)
    both = sum(r["present_subject"] and r["visible_event"] for r in scored)
    return {
        "shots": len(rows), "scored": n, "errored": len(rows) - n,
        # The two halves of the requirement, separately — they are different clauses and
        # the absence half was already measured to be rare, so pooling them would hide
        # which one (if either) moved.
        "present_subject": present, "present_subject_rate": round(present / n, 4),
        "visible_event": event, "visible_event_rate": round(event / n, 4),
        "both": both, "both_rate": round(both / n, 4),
        "neither": sum(not r["present_subject"] and not r["visible_event"] for r in scored),
        "failing_present_subject": [r["shot_id"] for r in scored if not r["present_subject"]],
        "failing_visible_event": [r["shot_id"] for r in scored if not r["visible_event"]],
    }


async def main() -> int:
    settings = Settings()  # type: ignore[call-arg]
    if not settings.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — this is a live judgement")
    out_path = HERE / "prompt_compliance.json"
    done: dict[str, dict] = {}
    if out_path.is_file():
        previous = json.loads(out_path.read_text(encoding="utf-8"))
        done = {f"{r['leg']}/{r['shot_id']}": r for r in previous.get("rows", [])}
        print(f"reusing {len(done)} judged prompts from {out_path.name}", flush=True)

    rows: list[dict] = []
    t0 = time.perf_counter()
    for leg in ("old", "new"):
        for row in rows_of(leg):
            key = f"{leg}/{row['shot_id']}"
            if key in done and "error" not in done[key]:
                rows.append(done[key])
                continue
            try:
                verdict = await judge(settings, row["sentence"], row["image_prompt"])
            except Exception as exc:  # noqa: BLE001 — an unjudged prompt is data, not a crash
                row["error"] = f"{type(exc).__name__}: {exc}"
                print(f"  ! {key}: {row['error']}", flush=True)
            else:
                row.update(verdict)
                mark = "✓" if verdict["present_subject"] and verdict["visible_event"] else "✗"
                print(f"  {mark} {key}: subject={verdict['present_subject']} "
                      f"event={verdict['visible_event']}", flush=True)
            rows.append(row)
            out_path.write_text(json.dumps({"rows": rows}, indent=2, ensure_ascii=False),
                                encoding="utf-8")

    by_leg = {leg: summarize([r for r in rows if r["leg"] == leg]) for leg in ("old", "new")}
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "judge_model": JUDGE_MODEL,
        "endpoint": _DASHSCOPE_VISION_ENDPOINT,
        "judge_prompt": JUDGE_PROMPT,
        "note": ("DIAGNOSTIC GATE, not the pre-registered verdict. PRE-REGISTRATION.md fixes the "
                 "verdict on rendered frames (paired boolean `readable`); this measures only "
                 "whether the written prompts moved in the direction the instruction demanded. "
                 "Blind by construction: one prompt + one sentence per call, no leg label."),
        "legs": by_leg,
        "deltas": {
            key: (None if by_leg["old"].get(key) is None or by_leg["new"].get(key) is None
                  else round(by_leg["new"][key] - by_leg["old"][key], 4))
            for key in ("present_subject_rate", "visible_event_rate", "both_rate")
        },
        "rows": rows,
    }
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    printable = {k: report[k] for k in ("legs", "deltas")}
    print("\n" + json.dumps(printable, indent=2, ensure_ascii=False), flush=True)
    print(f"\nelapsed {time.perf_counter() - t0:.0f}s -> {out_path.name}", flush=True)
    errored = sum("error" in r for r in rows)
    return 1 if errored > len(rows) * 0.1 else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
