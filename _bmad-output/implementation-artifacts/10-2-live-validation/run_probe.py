#!/usr/bin/env python
"""Story 10.2 live probe — does a generated background come out populated, and
does the guard's regeneration ladder actually clear it?

Two modes (ComfyUI must be up, YTFLOW_CHARACTER_VISION_API_KEY set):

    # scan real prompts until one renders populated, then run the ladder on it
    uv run python _bmad-output/implementation-artifacts/10-2-live-validation/run_probe.py
      → before.png / before_verdict.json, after.png / after_verdict.json, probe_log_guard.json

    # re-render the ALREADY-RECORDED hit and re-run the ladder against it
    uv run python _bmad-output/implementation-artifacts/10-2-live-validation/run_probe.py --replay-hit
      → confirm_before.png / …_verdict.json, confirm_after.png / …, probe_log_confirm.json

Probe prompts are real ``image_prompt`` values read out of a prior run's resume
sidecars — the true production distribution, not invented text — rendered
exactly the way ``image_node`` does: same workflow file (``AnimagineXL_v31``),
same ``_inject_prompts`` (so the frozen ``BG_NEGATIVE_SUFFIX`` is appended),
same ``_shot_seed`` rungs. Every frame is then shown to
``vision_check.background_has_person`` — the same Qwen-VL call the runtime guard
makes.

``--replay-hit`` reads ``before_verdict.json`` and re-renders that exact prompt
at that exact seed, so it is a confirmation of the recorded observation rather
than a fresh sample. It never overwrites the recorded before/after pair.

The story's text-scrub arm (``--arm scrub``) was CANCELLED before iteration 2:
replayed over 313 real prompts it damaged 27 of them and its one live
measurement was negative. Nothing in this script scrubs prompt text any more.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import yt_flow.pipeline.nodes.image as img  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.services import comfyui_client, vision_check  # noqa: E402

HERE = Path(__file__).parent
# Full E2E run (2026-07-12, SCP-049, 155 shots) — the largest real corpus on disk.
DEFAULT_SOURCE_RUN = "c6be1954-da0f-4dee-ab07-a2b4f3bcf21e"


def load_shots(source_run: str) -> list[dict]:
    """Real (run_id, scene_num, shot_id, image_prompt, negative_prompt) tuples."""
    out = []
    for sidecar in sorted((ROOT / "workspace" / source_run / "images").glob("*_done.json")):
        base = sidecar.name[: -len("_done.json")]  # scene_001_S00100
        _, scene, shot_id = base.split("_")
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        if not data.get("image_prompt"):
            continue
        out.append({
            "run_id": source_run, "scene_num": int(scene), "shot_id": shot_id,
            "image_prompt": data["image_prompt"],
            # the sidecar stores the EFFECTIVE negative (BG suffix already appended);
            # strip it so _inject_prompts re-appends exactly once, never twice
            "negative_prompt": data.get("negative_prompt", "").removesuffix(img.BG_NEGATIVE_SUFFIX),
        })
    return out


async def render(s: Settings, template: dict, shot: dict, seed: int) -> bytes:
    workflow = img._inject_prompts(template, shot["image_prompt"], shot["negative_prompt"], seed)
    return await comfyui_client.submit_and_fetch(s.comfyui_url, workflow)


def write_pair(prefix: str, tag: str, image_bytes: bytes, verdict: dict) -> None:
    (HERE / f"{prefix}{tag}.png").write_bytes(image_bytes)
    (HERE / f"{prefix}{tag}_verdict.json").write_text(
        json.dumps({"file": f"{prefix}{tag}.png", **verdict}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def replay_target(corpus: list[dict]) -> tuple[dict, int]:
    """The recorded hit: its exact prompt and its exact attempt-0 seed."""
    recorded = json.loads((HERE / "before_verdict.json").read_text(encoding="utf-8"))
    negative = next(
        (sh["negative_prompt"] for sh in corpus if sh["shot_id"] == recorded["shot_id"]), "")
    return {
        "run_id": DEFAULT_SOURCE_RUN, "scene_num": recorded["scene_num"],
        "shot_id": recorded["shot_id"], "image_prompt": recorded["image_prompt"],
        "negative_prompt": negative,
    }, recorded["seed"]


async def main(args) -> int:
    s = Settings()
    if not s.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — the probe needs the Qwen-VL key")
    await comfyui_client.check_health(s.comfyui_url)
    template = img._load_workflow(s.comfyui_workflow_path)

    corpus = load_shots(args.source_run)
    prefix, arm = ("confirm_", "confirm") if args.replay_hit else ("", "guard")

    log = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "arm": arm,
        "source_run": args.source_run,
        "checkpoint_workflow": s.comfyui_workflow_path,
        "vision_model": s.character_vision_model,
        "corpus_size": len(corpus),
        "probe_offset": args.offset,
        # --replay-hit has a probe set of exactly one recorded target, so the scan
        # limit means nothing there and is not recorded.
        **({} if args.replay_hit else {"probe_limit": args.limit}),
        "guard_attempts": args.attempts,
        "probes": [],
    }

    hit = None
    probe_set = [replay_target(corpus)] if args.replay_hit else \
        [(sh, img._shot_seed(sh["run_id"], sh["scene_num"], sh["shot_id"]))
         for sh in corpus[args.offset:][: args.limit]]
    for i, (shot, seed) in enumerate(probe_set):
        t0 = time.perf_counter()
        image_bytes = await render(s, template, shot, seed)
        has_person = await vision_check.background_has_person(image_bytes, s)
        log["probes"].append({
            "index": args.offset + i, "shot_id": shot["shot_id"], "scene_num": shot["scene_num"],
            "seed": seed, "has_person": has_person, "sec": round(time.perf_counter() - t0, 1),
        })
        print(f"[{i + 1}/{len(probe_set)}] {shot['shot_id']} seed={seed} "
              f"has_person={has_person} ({log['probes'][-1]['sec']}s)", flush=True)
        if has_person is True:
            hit = (shot, seed, image_bytes)
            break

    log["probe_set_size"] = len(log["probes"])

    def finish(code: int) -> int:
        (HERE / f"probe_log_{arm}.json").write_text(
            json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
        print(log.get("result", ""))
        return code

    if hit is None:
        log["result"] = (f"NO POPULATED BACKGROUND in {log['probe_set_size']} probe(s) "
                         f"(arm={arm}) — nothing to demonstrate on")
        return finish(1)

    shot, seed, image_bytes = hit
    write_pair(prefix, "before", image_bytes, {
        "shot_id": shot["shot_id"], "scene_num": shot["scene_num"], "seed": seed,
        "has_person": True, "image_prompt": shot["image_prompt"],
    })

    # The runtime guard's bounded ladder, from the same pure seed function image_node uses.
    log["guard"] = []
    for attempt, retry_seed in enumerate(
            img._seed_ladder(shot["run_id"], shot["scene_num"], shot["shot_id"])
            [1: args.attempts + 1], start=1):
        retry_bytes = await render(s, template, shot, retry_seed)
        verdict = await vision_check.background_has_person(retry_bytes, s)
        log["guard"].append({"attempt": attempt, "seed": retry_seed, "has_person": verdict})
        print(f"[guard attempt {attempt}] seed={retry_seed} has_person={verdict}", flush=True)
        if verdict is not True:
            write_pair(prefix, "after", retry_bytes, {
                "shot_id": shot["shot_id"], "seed": retry_seed, "attempt": attempt,
                "has_person": verdict,
                "change": "same prompt, guard-derived retry seed _shot_seed(run,scene,shot,attempt)",
                "image_prompt": shot["image_prompt"],
            })
            log["result"] = (f"caught after {log['probe_set_size']} probe(s), "
                             f"cleared on guard attempt {attempt}")
            return finish(0)
    log["result"] = "populated on every attempt — the guard would keep the last render"
    return finish(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--replay-hit", action="store_true",
                   help="re-render the recorded before.png hit instead of scanning the corpus")
    p.add_argument("--source-run", default=DEFAULT_SOURCE_RUN)
    p.add_argument("--offset", type=int, default=0, help="skip this many corpus shots first")
    p.add_argument("--limit", type=int, default=40, help="max backgrounds to render while scanning")
    p.add_argument("--attempts", type=int, default=2,
                   help="ladder rungs to try after a hit — explicit, NOT the config "
                        "default (background_person_guard_attempts ships as 0 = off)")
    raise SystemExit(asyncio.run(main(p.parse_args())))
