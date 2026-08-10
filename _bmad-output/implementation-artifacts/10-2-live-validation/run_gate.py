#!/usr/bin/env python
"""Story 10.2 live GATE — the real ``image_node`` on real ComfyUI + real Qwen-VL.

``run_probe.py`` reimplements the guard's ladder inline, so it proves the *idea*
and never executes the node. This script drives ``yt_flow.pipeline.nodes.image.
image_node`` itself: real workflow, real submissions, real detector, guard knob
explicitly at 2. Everything it reports (verdicts, counters, sidecars) is produced
by the shipped node, not by the script.

    uv run python _bmad-output/implementation-artifacts/10-2-live-validation/run_gate.py

Shot set (all real prompts, nothing invented):
  S00114  the recorded hit — its exact prompt from before_verdict.json, so rung 0
          is seed 3285965459 and the node should be seen detecting + regenerating
  S00104  } the two shots epic-10's finding 5·12 handoff actually named; neither
  S00403  } had ever been run through the node
  S00305  a DEPICTED human (a medical diagram of a human body on the wall)
  S00713  a DEPICTED human (a human skull on a shelf)
          — the narrowed has_person definition must NOT fire on set dressing;
            until now that narrowing was only checked by asserting words appear
            in a prompt string.

Outputs, all under this directory (the preserved before/after pair is never
touched — every file this writes is prefixed ``gate_``):
  gate_<shot>_a<rung>.png   every frame ComfyUI returned, accepted or rejected
  gate_<shot>_done.json     the sidecar the node wrote for that shot
  gate_log.json             per-render verdicts, the node's guard counters, logs
"""

import argparse
import asyncio
import json
import logging
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import yt_flow.pipeline.nodes.image as img  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.services import comfyui_client, vision_check  # noqa: E402

HERE = Path(__file__).parent
SOURCE_RUN = "c6be1954-da0f-4dee-ab07-a2b4f3bcf21e"
# (scene_num, shot_id, why it is in the set)
SHOT_SET = [
    (1, "S00114", "recorded hit (prompt from before_verdict.json)"),
    (1, "S00104", "finding 5.12 handoff shot, never run through the node"),
    (3, "S00305", "depicted human: medical diagram of a human body"),
    (4, "S00403", "finding 5.12 handoff shot, never run through the node"),
    (7, "S00713", "depicted human: a human skull on a shelf"),
]


def build_shot(scene_num: int, shot_id: str) -> dict:
    """Real prompts off disk: the run's resume sidecar, or before_verdict.json."""
    sidecar = json.loads(
        (ROOT / "workspace" / SOURCE_RUN / "images" / f"scene_{scene_num:03d}_{shot_id}_done.json")
        .read_text(encoding="utf-8"))
    image_prompt = sidecar["image_prompt"]
    if shot_id == "S00114":  # the exact text that produced before.png
        image_prompt = json.loads((HERE / "before_verdict.json").read_text(encoding="utf-8"))["image_prompt"]
    return {
        "shot_id": shot_id, "sentence_indices": [0], "image_prompt": image_prompt,
        # the sidecar stores the EFFECTIVE negative (BG suffix already appended);
        # strip it so the node re-appends exactly once, never twice
        "negative_prompt": sidecar.get("negative_prompt", "").removesuffix(img.BG_NEGATIVE_SUFFIX),
        "camera_angle": None, "camera_movement": None, "image_path": None, "cast": [],
    }


def build_state() -> dict:
    scenes = []
    for scene_num in sorted({sc for sc, _, _ in SHOT_SET}):
        scenes.append({
            "scene_num": scene_num, "narration": "", "audio_path": None, "audio_duration": None,
            "word_timings": [], "subtitle_path": None,
            "shots": [build_shot(sc, sid) for sc, sid, _ in SHOT_SET if sc == scene_num],
        })
    return {
        "run_id": SOURCE_RUN, "scp_text": "SCP-049", "scenes": scenes,
        "video_path": None, "current_stage": "", "gate_states": {},
        "prompt_variant": None, "error": None,
    }


async def main(args) -> int:
    s = Settings(
        background_person_guard_attempts=args.attempts,
        # a scratch workspace: the gate must never write into the real run dir
        workspace_path=str(HERE / "gate_workspace"),
    )
    if not s.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — the gate needs the Qwen-VL key")
    img._settings = lambda: s  # the node's only settings seam
    if not args.resume:  # otherwise a second run resumes and renders nothing
        shutil.rmtree(s.workspace_path, ignore_errors=True)
    await comfyui_client.check_health(s.comfyui_url)

    # seed → (shot_id, rung), so every render can be filed against the node's ladder
    rung_of = {
        seed: (shot_id, rung)
        for scene_num, shot_id, _ in SHOT_SET
        for rung, seed in enumerate(img._seed_ladder(SOURCE_RUN, scene_num, shot_id))
    }
    renders: list[dict] = []
    real_fetch, real_check = comfyui_client.submit_and_fetch, vision_check.background_has_person

    async def taps_fetch(url, workflow):
        seed = next(n["inputs"]["seed"] for n in workflow.values()
                    if isinstance(n, dict) and n.get("class_type") == "KSampler")
        t0 = time.perf_counter()
        image_bytes = await real_fetch(url, workflow)
        shot_id, rung = rung_of[seed]
        name = f"gate_{shot_id}_a{rung}.png"
        (HERE / name).write_bytes(image_bytes)
        renders.append({"shot_id": shot_id, "rung": rung, "seed": seed, "file": name,
                        "render_sec": round(time.perf_counter() - t0, 1), "has_person": "not called"})
        print(f"  rendered {shot_id} rung {rung} seed={seed} ({renders[-1]['render_sec']}s)", flush=True)
        return image_bytes

    async def taps_check(image_bytes, settings):
        t0 = time.perf_counter()
        verdict = await real_check(image_bytes, settings)
        renders[-1]["has_person"] = verdict
        renders[-1]["verdict_sec"] = round(time.perf_counter() - t0, 1)
        print(f"    has_person={verdict} ({renders[-1]['verdict_sec']}s)", flush=True)
        return verdict

    comfyui_client.submit_and_fetch = taps_fetch
    vision_check.background_has_person = taps_check
    trace: dict = {}
    real_trace = img._record_trace
    img._record_trace = lambda **kw: (trace.update(kw), real_trace(**kw))[0]

    log_lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            log_lines.append(f"{record.levelname} {record.name}: {record.getMessage()}")

    logging.getLogger("yt_flow").addHandler(Capture())
    logging.getLogger("yt_flow").setLevel(logging.INFO)

    t0 = time.perf_counter()
    out = await img.image_node(build_state())
    elapsed = round(time.perf_counter() - t0, 1)

    ws = Path(s.workspace_path) / SOURCE_RUN / "images"
    sidecars = {}
    for scene_num, shot_id, _ in SHOT_SET:
        src = ws / f"scene_{scene_num:03d}_{shot_id}_done.json"
        if src.is_file():
            sidecars[shot_id] = json.loads(src.read_text(encoding="utf-8"))
            shutil.copyfile(src, HERE / f"gate_{shot_id}_done.json")

    log = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "arm": "gate — real image_node",
        "source_run": SOURCE_RUN,
        "checkpoint_workflow": s.comfyui_workflow_path,
        "vision_model": s.character_vision_model,
        "guard_attempts": s.background_person_guard_attempts,
        "shot_set": [{"scene_num": sc, "shot_id": sid, "why": why} for sc, sid, why in SHOT_SET],
        "renders": renders,
        "guard_counts": trace.get("guard_counts"),
        "request_count": trace.get("request_count"),
        "image_count": trace.get("image_count"),
        "skipped_count": trace.get("skipped_count"),
        "error": out.get("error"),
        "accepted_seed_per_shot": {sid: sc.get("seed") for sid, sc in sidecars.items()},
        "guard_exhausted_per_shot": {sid: sc.get("guard_exhausted") for sid, sc in sidecars.items()},
        "elapsed_sec": elapsed,
        "log": log_lines,
    }
    (HERE / ("gate_log_resume.json" if args.resume else "gate_log.json")).write_text(
        json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: log[k] for k in
                      ("guard_counts", "request_count", "image_count", "error",
                       "accepted_seed_per_shot", "guard_exhausted_per_shot")},
                     indent=2, ensure_ascii=False))
    return 1 if out.get("error") else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--attempts", type=int, default=2,
                   help="guard knob for this gate run (the config default is 0 = off)")
    p.add_argument("--resume", action="store_true",
                   help="keep gate_workspace/ so the node takes its resume path")
    raise SystemExit(asyncio.run(main(p.parse_args())))
