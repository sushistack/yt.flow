"""One-off verification script for Story 5.22 review findings.

Not committed (workflow_decision: no code changes). Measures:
  - AC6/AC7: 3 golden SCPs x 5 reps, research->structure->writing->tts_normalize,
    candidate label. Max consecutive same-ending-form run + tts_normalize
    sanity (no new serial designations, no sentence-count mismatch fallback).
  - AC4: one hand-crafted scene with a deliberate 4-in-a-row ending run AND a
    serial designation, run through review_step, checking overall_pass/issues
    for ending_monotony / designation_violation.

Results written to verify_5_22_results.json in this same directory.
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path("/mnt/work/projects/yt.flow/src")))

from yt_flow.config import Settings
from yt_flow.pipeline.nodes.scenario import _call_deepseek
from yt_flow.pipeline.nodes.scenario_chain import (
    research_step, structure_step, writing_step, tts_normalize_step,
    review_step, split_sentences,
)
from yt_flow.services.prompt_service import get_prompt_with_fallback

sys.path.insert(0, "/mnt/work/projects/yt.flow/scripts")
from eval_prompts import load_golden_scps  # noqa: E402

REPS = 5
LABEL = "candidate"
OUT = Path(__file__).parent / "verify_5_22_results.json"


def classify_ending(sentence: str) -> str:
    s = sentence.strip()
    if s.endswith("?") or re.search(r"까요\??$", s):
        return "question"
    if re.search(r"(했|았|였)습니다\.?$", s):
        return "past-습니다"
    if re.search(r"입니다\.?$", s):
        return "입니다"
    if re.search(r"(ㅂ니다|습니다)\.?$", s):
        return "습니다"
    return "other"


def max_run(sentences: list[str]) -> tuple[int, list[str]]:
    forms = [classify_ending(s) for s in sentences]
    best, cur, cur_form = 1, 1, forms[0] if forms else None
    for f in forms[1:]:
        if f == cur_form and f != "other":
            cur += 1
        else:
            cur, cur_form = 1, f
        best = max(best, cur)
    return best, forms


async def run_ac6_ac7(scps: dict[str, str]) -> dict:
    s = Settings()
    format_guide = get_prompt_with_fallback("scenario/format_guide", label=LABEL).compile()
    results = {}
    for scp_id, scp_text in scps.items():
        reps_out = []
        for rep in range(REPS):
            try:
                research = await research_step(scp_id, scp_text, format_guide, s, _call_deepseek, label=LABEL)
                structure = await structure_step(scp_id, research, format_guide, s, _call_deepseek, label=LABEL)
                writing = await writing_step(
                    scp_id, structure, research["frozen_descriptor"], format_guide, "", s, _call_deepseek, label=LABEL
                )
                tts = await tts_normalize_step(writing, format_guide, s, _call_deepseek, label=LABEL)

                scene_runs = []
                designations_found = []
                for scene in writing["scenes"]:
                    sentences = split_sentences(scene["narration"])
                    run, _ = max_run(sentences)
                    scene_runs.append(run)
                for scene in tts["scenes"]:
                    text = scene.get("narration", "") + " " + scene.get("display_narration", "")
                    if re.search(r"D-\d+|Dr\. ?███", text):
                        designations_found.append(scene.get("scene_num"))
                reps_out.append({
                    "rep": rep + 1, "max_run_per_scene": scene_runs, "max_run": max(scene_runs) if scene_runs else None,
                    "tts_designations_found": designations_found, "ok": True,
                })
                print(f"[{scp_id}] rep {rep+1}: max_run={max(scene_runs) if scene_runs else None} tts_designations={designations_found}", flush=True)
            except Exception as exc:
                reps_out.append({"rep": rep + 1, "ok": False, "error": str(exc)})
                print(f"[{scp_id}] rep {rep+1}: FAILED {exc}", flush=True)
        results[scp_id] = reps_out
        OUT.write_text(json.dumps({"ac6_ac7": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


async def run_ac4(scps: dict[str, str]) -> dict:
    s = Settings()
    format_guide = get_prompt_with_fallback("scenario/format_guide", label=LABEL).compile()
    any_scp_id, any_scp_text = next(iter(scps.items()))
    synthetic_narration = (
        "D-9341은 격리실에 입장했습니다. 문이 닫혔습니다. 조명이 꺼졌습니다. 비명이 들렸습니다."
    )
    writing = {
        "scp_id": any_scp_id,
        "title": "verification synthetic scene",
        "scenes": [{
            "scene_num": 1, "narration": synthetic_narration, "mood": "tense",
            "entity_visible": True, "location": "containment chamber",
            "characters_present": ["D-9341"], "color_palette": "gray", "atmosphere": "tense",
        }],
    }
    visual_by_scene = {1: {"visual_descriptions": []}}
    try:
        review = await review_step(
            any_scp_text, writing, visual_by_scene, "frozen descriptor placeholder", format_guide, s, _call_deepseek,
            label=LABEL,
        )
        result = {"ok": True, "overall_pass": review.get("overall_pass"), "issues": review.get("issues", [])}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    print(f"AC4 review result: {json.dumps(result, ensure_ascii=False, indent=2)}", flush=True)
    return result


async def main():
    scps = load_golden_scps()
    ac6_ac7 = await run_ac6_ac7(scps)
    ac4 = await run_ac4(scps)
    OUT.write_text(json.dumps({"ac6_ac7": ac6_ac7, "ac4": ac4}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote results to {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
