#!/usr/bin/env python
"""Story 10.1e — paired recompose ON/OFF scoring over run ``e5ed4b3a``.

ONE harness, six stages, each writing its own JSON so any stage can be re-run without
redoing the one before it. Every stage boundary here is a place the run can legitimately
stop (ComfyUI busy, RAM under the floor, DashScope key absent), and five scripts would
carry five copies of the manifest schema.

    screen       baseline_v2.json  -> screening.json      (free: no GPU, no network)
    manifest     checkpoint        -> pairs.json          (LLM angle calls, no GPU)
    render-off   pairs.json        -> off/*.png, off.json (ffmpeg only)
    render-on    pairs.json        -> on/*.png,  on.json  (ComfyUI / GPU)
    score        off/+on/          -> results.json        (DashScope; blind first)
    report       results.json      -> README.md           (the pre-registered rule)
    grid         results.json      -> pairs_grid.jpg      (the adjudication images)

Nothing is simulated. The frames are the run's own plates and its own resolved cards, the
placement comes from the shipped resolvers, the ON arm goes through the shipped service
(so 10.1d's preflight is exercised live), and the scores come from 13-2's instrument,
imported rather than reimplemented.

The one thing this file must never do is decide anything. The rule lives in
``PREREGISTRATION.md``, committed before ``score`` runs; ``report`` applies it mechanically.
"""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import statistics
from math import comb
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)  # every plate path in the checkpoint is repo-relative

from yt_flow.config import Settings  # noqa: E402

HERE = Path(__file__).parent
RUN = "e5ed4b3a-fabb-46e6-8adb-5c1c0fc68889"
V2 = ROOT / "_bmad-output" / "implementation-artifacts" / "10-4-live-validation" / "baseline_v2.json"
# Read-only URI. Other agent sessions write this file concurrently; `mode=ro` is verified
# to take effect here (python 3.12's sqlite3 treats a `file:` prefix as a URI), and a
# write attempt through this handle raises "attempt to write a readonly database".
DB_RO = "file:yt_flow.db?mode=ro&uri=true"
SALT = "10-1e-recompose-verdict"  # fixed and committed; the blind ids are reproducible

OFF_DIR, ON_DIR, BLIND_DIR = HERE / "off", HERE / "on", HERE / "blind"

# `place` readings counted as the corridor misread. The same rule reproduces 10-4
# README §0's 29/4 exactly off baseline_v2.json — see screening.json.
CORRIDOR = "corridor"


def _axis():
    """13-2's instrument, imported from ``scripts/`` rather than copied."""
    spec = importlib.util.spec_from_file_location(
        "score_shot_narration", ROOT / "scripts" / "score_shot_narration.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {path.relative_to(ROOT)}", flush=True)


def _rel(p: Path) -> str:
    """Repo-relative string. cwd is ROOT, so manifest paths arrive relative already and
    `Path.relative_to(ROOT)` raises on them — this crashed `render-on`'s publish step
    after all 33 renders were paid for."""
    return str(p.relative_to(ROOT) if p.is_absolute() else p)


def _blind_id(shot_id: str, arm: str) -> str:
    return hashlib.sha256(f"{shot_id}|{arm}|{SALT}".encode("utf-8")).hexdigest()[:12]


# ── screen ───────────────────────────────────────────────────────────────────


def _cell(rows: list[dict]) -> dict:
    unreadable = [r["shot_id"] for r in rows if r.get("readable") is False]
    corridor = [r["shot_id"] for r in rows if CORRIDOR in (r.get("place") or "").lower()]
    return {
        "n": len(rows),
        "unreadable": len(unreadable),
        "unreadable_pct": round(100 * len(unreadable) / len(rows), 1) if rows else None,
        "corridor": len(corridor),
        "corridor_pct": round(100 * len(corridor) / len(rows), 1) if rows else None,
        "shot_ids": sorted(r["shot_id"] for r in rows),
    }


def cmd_screen(args) -> int:
    """Show — not assert — that 10.4's arm split IS its cast-presence split."""
    rows = json.loads(V2.read_text(encoding="utf-8"))["rows"]
    recomposed = [r for r in rows if "/recomposed/" in (r.get("frame") or "")]
    plates = [r for r in rows if "/images/" in (r.get("frame") or "")]
    cast_yes = [r for r in rows if r.get("cast")]
    cast_no = [r for r in rows if not r.get("cast")]

    by_arm = {"recomposed": _cell(recomposed), "plate": _cell(plates)}
    by_cast = {"cast_present": _cell(cast_yes), "cast_empty": _cell(cast_no)}
    overlap = sorted(set(by_arm["recomposed"]["shot_ids"]) & set(by_arm["plate"]["shot_ids"]))

    # The 2x2 that makes collinearity a number rather than a claim.
    contingency = {
        "recomposed_x_cast_present": sum(
            1 for r in recomposed if r.get("cast")),
        "recomposed_x_cast_empty": sum(1 for r in recomposed if not r.get("cast")),
        "plate_x_cast_present": sum(1 for r in plates if r.get("cast")),
        "plate_x_cast_empty": sum(1 for r in plates if not r.get("cast")),
    }
    identical = all(
        {k: v for k, v in by_arm[a].items() if k != "shot_ids"}
        == {k: v for k, v in by_cast[c].items() if k != "shot_ids"}
        for a, c in (("recomposed", "cast_present"), ("plate", "cast_empty"))
    ) and by_arm["recomposed"]["shot_ids"] == by_cast["cast_present"]["shot_ids"] \
        and by_arm["plate"]["shot_ids"] == by_cast["cast_empty"]["shot_ids"]

    payload = {
        "source": str(V2.relative_to(ROOT)),
        "rows": len(rows),
        "by_arm": by_arm,
        "by_cast_presence": by_cast,
        "arm_shot_id_overlap": overlap,
        "contingency": contingency,
        "splits_identical": identical,
        "corridor_rule": "case-insensitive substring 'corridor' in the blind `place` reading",
        "conclusion": (
            "arm and cast-presence are 100% collinear in baseline_v2.json: the two splits "
            "select byte-identical shot sets, so no arithmetic on these 66 rows can "
            "separate 'recompose hurt legibility' from 'shots containing characters read "
            "as corridors'. 10.4's 20%/13% and 57%/27% are not treatment measurements."
        ) if identical else "SPLITS DIFFER — the collinearity claim does not reproduce.",
    }

    print(f"screen: {len(rows)} rows from {V2.relative_to(ROOT)}")
    print(f"  by arm          recomposed n={by_arm['recomposed']['n']:>2} "
          f"unreadable={by_arm['recomposed']['unreadable']} "
          f"({by_arm['recomposed']['unreadable_pct']}%)  "
          f"corridor={by_arm['recomposed']['corridor']} ({by_arm['recomposed']['corridor_pct']}%)")
    print(f"                  plate      n={by_arm['plate']['n']:>2} "
          f"unreadable={by_arm['plate']['unreadable']} ({by_arm['plate']['unreadable_pct']}%)  "
          f"corridor={by_arm['plate']['corridor']} ({by_arm['plate']['corridor_pct']}%)")
    print(f"  by cast         present    n={by_cast['cast_present']['n']:>2} "
          f"unreadable={by_cast['cast_present']['unreadable']} "
          f"({by_cast['cast_present']['unreadable_pct']}%)  "
          f"corridor={by_cast['cast_present']['corridor']} "
          f"({by_cast['cast_present']['corridor_pct']}%)")
    print(f"                  empty      n={by_cast['cast_empty']['n']:>2} "
          f"unreadable={by_cast['cast_empty']['unreadable']} "
          f"({by_cast['cast_empty']['unreadable_pct']}%)  "
          f"corridor={by_cast['cast_empty']['corridor']} "
          f"({by_cast['cast_empty']['corridor_pct']}%)")
    print(f"  arm shot_id overlap: {len(overlap)}")
    print(f"  contingency: {contingency}")
    print(f"  splits identical: {identical}")
    _write(HERE / "screening.json", payload)
    return 0 if identical else 1


# ── manifest ─────────────────────────────────────────────────────────────────


async def cmd_manifest(args) -> int:
    """Freeze the shot set, the plates and ONE resolution of the cast cards.

    Resolved once and written down because ``resolve_cast_cards`` spends an LLM angle
    call per distinct ``card_key``: resolving separately per arm would let the two arms
    receive different cards and confound the treatment with angle selection.
    """
    from sqlmodel import Session, create_engine

    from yt_flow.services import compositing_service
    from yt_flow.services.character_service import CharacterService
    from yt_flow.services.eval_service import _load_state
    from yt_flow.services.recompose_service import CARD_LOOKS

    settings = Settings()
    axis = _axis()
    state = await _load_state(RUN, DB_RO)
    scenes = state["scenes"]
    scp_id = state["scp_id"]

    total_shots = sum(len(sc.get("shots") or []) for sc in scenes)
    dropped: list[dict] = []

    # Eligibility as `recompose_run_shots` itself defines it, read off the checkpoint.
    eligible: list[tuple[dict, dict]] = []
    for scene in scenes:
        for shot in scene.get("shots") or []:
            cast = shot.get("cast") or []
            if not cast:
                dropped.append({"shot_id": shot["shot_id"], "scene_num": scene["scene_num"],
                                "reason": "empty cast — ineligible for recompose"})
                continue
            unknown = [c.get("card_key") for c in cast if c.get("card_key") not in CARD_LOOKS]
            if unknown:
                dropped.append({"shot_id": shot["shot_id"], "scene_num": scene["scene_num"],
                                "reason": f"no CARD_LOOKS description for {unknown}"})
                continue
            eligible.append((scene, shot))
    print(f"manifest: {total_shots} shots, {len(eligible)} recompose-eligible, "
          f"{sum(len(s.get('cast') or []) for _, s in eligible)} placements")

    # ONE resolution, over the eligible subset only.
    m_scenes = [
        {"scene_num": sc["scene_num"], "mood": sc.get("mood"), "narration": sc.get("narration", ""),
         "shots": [sh for s2, sh in eligible if s2 is sc]}
        for sc in scenes if any(s2 is sc for s2, _ in eligible)
    ]
    engine = create_engine(f"sqlite:///{DB_RO}", connect_args={"check_same_thread": False})
    with Session(engine) as session:
        cast_cards = await CharacterService(session, settings=settings).resolve_cast_cards(
            scp_id, m_scenes)
    print(f"  resolve_cast_cards: {len(cast_cards)} shots, "
          f"{sum(len(v) for v in cast_cards.values())} cards")

    # Drop shots the resolver could not fully serve — from BOTH arms, with the reason.
    kept_cast: dict[str, list[dict]] = {}
    kept: list[tuple[dict, dict]] = []
    for scene, shot in eligible:
        key = f"{scene['scene_num']}:{shot['shot_id']}"
        cards = [c for c in cast_cards.get(key) or [] if c.get("path")]
        expected = len(shot.get("cast") or [])
        plate = Path(shot.get("image_path") or "")
        if len(cards) != expected:
            dropped.append({"shot_id": shot["shot_id"], "scene_num": scene["scene_num"],
                            "reason": f"resolver returned {len(cards)} of {expected} card paths"})
            continue
        if not plate.is_file():
            dropped.append({"shot_id": shot["shot_id"], "scene_num": scene["scene_num"],
                            "reason": f"plate missing on disk: {plate}"})
            continue
        missing = [c["path"] for c in cards if not Path(c["path"]).is_file()]
        if missing:
            dropped.append({"shot_id": shot["shot_id"], "scene_num": scene["scene_num"],
                            "reason": f"card asset missing on disk: {missing}"})
            continue
        kept_cast[key] = cards
        kept.append((scene, shot))

    # Ground placement, from the SAME resolver api/main.py injects. Its depth maps must
    # already be cached: a miss would spend GPU inference inside a stage this run treats
    # as GPU-free, and the ON arm's server has not been restarted yet.
    plates = sorted({str(sh["image_path"]) for _, sh in kept})
    misses = [
        p for p in plates
        if not compositing_service.verify_depth_pair(
            compositing_service.depth_map_cache_path(p, settings),
            hashlib.sha256(Path(p).read_bytes()).hexdigest(),
            compositing_service.depth_contract(settings))
    ]
    print(f"  depth cache: {len(plates) - len(misses)}/{len(plates)} plates cached")
    if misses and not args.allow_depth_inference:
        print(f"STOP: {len(misses)} plate(s) have no valid cached depth pair, so "
              "resolve_placements would run depth inference on ComfyUI from a stage that "
              "is supposed to be GPU-free. Re-run with --allow-depth-inference to accept "
              f"that cost.\n  first: {misses[0]}")
        return 2

    m_scenes_kept = [
        {"scene_num": sc["scene_num"], "mood": sc.get("mood"), "narration": sc.get("narration", ""),
         "shots": [sh for s2, sh in kept if s2 is sc]}
        for sc in scenes if any(s2 is sc for s2, _ in kept)
    ]
    from yt_flow.pipeline.nodes import video as video_node

    placements = await compositing_service.resolve_placements(m_scenes_kept, kept_cast, settings)
    merged = video_node._merge_placements(kept_cast, placements)
    placed = sum(1 for cards in merged.values() for c in cards if "ground_y" in c)
    occluded = sum(1 for cards in merged.values() for c in cards if c.get("occlusion_mask"))
    print(f"  placements: {placed} cards carry ground_y, {occluded} carry an occlusion_mask")

    shots = []
    for scene, shot in kept:
        key = f"{scene['scene_num']}:{shot['shot_id']}"
        shots.append({
            "shot_key": key,
            "scene_num": scene["scene_num"],
            "shot_id": shot["shot_id"],
            "mood": scene.get("mood"),
            "plate": str(shot["image_path"]),
            "sentence_indices": shot.get("sentence_indices") or [],
            "sentences": axis.shot_sentences(scene, shot),
            "image_prompt": shot.get("image_prompt", ""),
            "cast": [{k: (str(v) if isinstance(v, Path) else v) for k, v in c.items()}
                     for c in merged[key]],
        })

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run": RUN,
        "scp_id": scp_id,
        "checkpoint": DB_RO,
        "totals": {
            "shots_in_run": total_shots,
            "recompose_eligible": len(eligible),
            "paired": len(shots),
            "recompose_passes": sum(len(s["cast"]) for s in shots),
        },
        "settings_snapshot": {
            "composite_harmonization_tier": settings.composite_harmonization_tier,
            "depth_placement_enabled": settings.depth_placement_enabled,
            "parallax_25d_enabled": settings.parallax_25d_enabled,
            "shot_recompose_enabled": settings.shot_recompose_enabled,
            "shot_recompose_workflow_path": settings.shot_recompose_workflow_path,
            "recompose_preflight_min_free_ram_gb": settings.recompose_preflight_min_free_ram_gb,
            "comfyui_url": settings.comfyui_url,
        },
        "dropped": dropped,
        "shots": shots,
    }
    _write(HERE / "pairs.json", payload)
    return 0


def _manifest() -> dict:
    return json.loads((HERE / "pairs.json").read_text(encoding="utf-8"))


# ── render-off ───────────────────────────────────────────────────────────────


async def cmd_render_off(args) -> int:
    """The incumbent, as it ships: `render_composite_still` drives `_build_card_chain`.

    Not a bare plate (that is the confound this story exists to remove) and not a frame
    lifted out of `shots/*.mp4` (zoompan start-zoom + t=0 shake + a yuv420p round-trip).
    """
    from yt_flow.pipeline.nodes import video as video_node

    settings = Settings()
    manifest = _manifest()
    OFF_DIR.mkdir(parents=True, exist_ok=True)
    rows, failed = [], []
    t0 = time.monotonic()
    for shot in manifest["shots"]:
        out = OFF_DIR / f"{shot['shot_id']}.png"
        started = time.monotonic()
        result = await video_node.render_composite_still(
            {"shot_id": shot["shot_id"], "image_path": shot["plate"]},
            shot["cast"], out,
            mood=shot["mood"],
            composite_harmonization_tier=settings.composite_harmonization_tier,
        )
        elapsed = round(time.monotonic() - started, 2)
        if result is None or not out.is_file():
            failed.append(shot["shot_id"])
            print(f"  ! {shot['shot_id']}: render_composite_still returned None", flush=True)
            continue
        rows.append({"shot_id": shot["shot_id"], "path": str(out.relative_to(ROOT)),
                     "size": _dimensions(out), "seconds": elapsed})
        print(f"  ✓ {shot['shot_id']}  {rows[-1]['size']}  {elapsed}s", flush=True)
    _write(HERE / "off.json", {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "arm": "off",
        "renderer": "video.render_composite_still (production _build_card_chain)",
        "composite_harmonization_tier": settings.composite_harmonization_tier,
        "total_seconds": round(time.monotonic() - t0, 1),
        "rendered": len(rows), "failed": failed, "frames": rows,
    })
    return 0


def _dimensions(path: Path) -> str:
    from yt_flow.domain.png import dimensions

    size = dimensions(path.read_bytes())
    return f"{size[0]}x{size[1]}" if size else "?"


# ── render-on ────────────────────────────────────────────────────────────────


async def cmd_render_on(args) -> int:
    """The treatment, through `recompose_run_shots` — so 10.1d's preflight runs live.

    `recompose_shot` would skip it, and the preflight has never met a real server.
    """
    from yt_flow.pipeline.nodes import video as video_node
    from yt_flow.services import recompose_service

    settings = Settings()
    manifest = _manifest()
    scenes: list[dict] = []
    cast_cards: dict[str, list[dict]] = {}
    for shot in manifest["shots"]:
        scene = next((s for s in scenes if s["scene_num"] == shot["scene_num"]), None)
        if scene is None:
            scene = {"scene_num": shot["scene_num"], "shots": []}
            scenes.append(scene)
        scene["shots"].append({"shot_id": shot["shot_id"], "image_path": shot["plate"]})
        cast_cards[shot["shot_key"]] = [dict(c) for c in shot["cast"]]

    passes = manifest["totals"]["recompose_passes"]
    print(f"render-on: {sum(len(s['shots']) for s in scenes)} shots, {passes} passes")
    t0 = time.monotonic()
    call_started = time.time()
    remaining, stats = await recompose_service.recompose_run_shots(scenes, cast_cards, settings)
    total = round(time.monotonic() - t0, 1)
    print(f"  stats={stats}  total={total}s", flush=True)

    if stats.get("preflight_failed"):
        # The message IS the artifact — reproduced verbatim, nothing rendered.
        print("\n--- ComfyUI preflight message (verbatim) ---")
        print(stats.get("preflight_detail"))
        print("--- end ---")
        _write(HERE / "on.json", {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "arm": "on", "stats": stats, "total_seconds": total,
            "preflight_failed": stats["preflight_failed"],
            "preflight_detail": stats.get("preflight_detail"),
            "rendered": 0, "failed": [s["shot_id"] for s in manifest["shots"]], "frames": [],
        })
        return 3

    ON_DIR.mkdir(parents=True, exist_ok=True)
    # Framed through the SAME chain the OFF arm's still uses (scale 1728 -> crop
    # 1728x972 -> 1920x1080), so neither resolution nor crop can identify the arm.
    chain = video_node._zoompan_filter(video_node._FUSION_STILL_SPEC, 1.0)
    rows, failed, mtimes = [], [], []
    for shot in manifest["shots"]:
        scene = next(s for s in scenes if s["scene_num"] == shot["scene_num"])
        entry = next(s for s in scene["shots"] if s["shot_id"] == shot["shot_id"])
        src = Path(entry["image_path"])
        if "recomposed" not in src.parts or not src.is_file():
            failed.append(shot["shot_id"])
            print(f"  ! {shot['shot_id']}: no recomposed frame ({src})", flush=True)
            continue
        out = ON_DIR / f"{shot['shot_id']}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(video_node.FPS),
             "-i", str(src), "-vf", chain, "-frames:v", "1", "-update", "1", str(out)],
            check=True, capture_output=True)
        mtimes.append((shot["shot_id"], src.stat().st_mtime, len(shot["cast"])))
        # cwd is ROOT, so the plate/recomposed paths off the manifest are already relative.
        rows.append({"shot_id": shot["shot_id"], "path": _rel(out),
                     "source": _rel(src), "source_size": _dimensions(src),
                     "size": _dimensions(out), "passes": len(shot["cast"])})
        print(f"  ✓ {shot['shot_id']}  {rows[-1]['source_size']} -> {rows[-1]['size']}", flush=True)

    # Per-shot wall clock from the recomposed files' own mtimes: `recompose_run_shots`
    # writes each frame as its shot completes, so the deltas are the render, measured
    # rather than instrumented (and the service is called once, exactly as production
    # calls it — a per-shot loop would run the preflight 33 times instead of once).
    # A shot whose file predates this call was served from cache, not rendered now.
    rendered_now = sum(n for _, m, n in mtimes if m >= call_started)
    mtimes.sort(key=lambda t: t[1])
    per_shot: list[dict] = []
    prev_t = None
    for shot_id, mtime, n_passes in mtimes:
        if prev_t is not None:
            per_shot.append({"shot_id": shot_id, "seconds": round(mtime - prev_t, 1),
                             "passes": n_passes,
                             "seconds_per_pass": round((mtime - prev_t) / max(1, n_passes), 1)})
        prev_t = mtime
    done_passes = sum(r["passes"] for r in rows)
    # PUBLISHED, not rendered — a cache hit publishes without rendering. `passes_failed`
    # feeds the pre-registered veto, which `report` applies BEFORE anything else, so the
    # same cache-blindness that faked the cost figure would have made the veto unfireable
    # on any warm-cache re-run. Failure means a shot the service could not produce a frame
    # for, which is exactly `stats["failed"]` plus anything absent from `rows`.
    failed_passes = passes - done_passes
    _write(HERE / "on.json", {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "arm": "on",
        "renderer": "recompose_service.recompose_run_shots (one call, production entry)",
        "stats": stats,
        "remaining_cast_shots": sorted(remaining),
        "total_seconds": total,
        "passes_attempted": passes, "passes_completed": done_passes,
        "passes_failed": failed_passes,
        # Passes this CALL actually rendered — the rest were content-addressed cache hits.
        # Dividing wall clock by all published passes reported 7.8 s/pass for a re-run that
        # rendered 3 of 40, and `report` cited it as the cost figure until this was fixed.
        "passes_rendered_this_call": rendered_now,
        "seconds_per_pass_mean": round(total / rendered_now, 1) if rendered_now else None,
        "seconds_per_pass_mean_note": (
            "None means every pass was a cache hit; use per_shot_from_mtime instead"),
        "per_shot_from_mtime": per_shot,
        "comfyui_argv": (await _stats_argv(settings)),
        "rendered": len(rows), "failed": failed, "frames": rows,
        "note": ("per_shot_from_mtime omits the first completed shot: its start is the "
                 "service call, not a previous file's mtime. seconds_per_pass_mean uses "
                 "the whole call and is the number the cost line quotes."),
    })
    return 0 if not failed else 4


def cmd_publish_on(args) -> int:
    """Publish whatever recomposed frames exist, without calling the service.

    `render-on` publishes at the end of one `recompose_run_shots` call, so a run killed
    mid-sweep leaves its finished frames stranded in the run's `recomposed/` dir — which
    is exactly what happened on 2026-08-16 (2 of 33 shots). The cache path is
    content-addressed, so the frames are findable from the committed manifest alone.
    """
    from yt_flow.pipeline.nodes import shot_recompose, video as video_node

    manifest = _manifest()
    ON_DIR.mkdir(parents=True, exist_ok=True)
    chain = video_node._zoompan_filter(video_node._FUSION_STILL_SPEC, 1.0)
    rows, missing = [], []
    for shot in manifest["shots"]:
        plate = Path(shot["plate"])
        cast = [dict(c) for c in shot["cast"]]
        # The three digest inputs are copied verbatim from recompose_service's loop
        # (manifest order, NOT order_cast) — a different digest here would silently
        # look for a file the service never wrote.
        digest = shot_recompose.recompose_digest(
            plate.read_bytes(),
            [str(c["path"]) for c in cast],
            [f"{c.get('card_key')}|{c.get('position')}|{c.get('depth')}|{c.get('pose')}"
             for c in cast])
        run_dir = plate.parent.parent if plate.parent.name == "images" else Path(Settings().workspace_path)
        src = shot_recompose.recompose_cache_path(run_dir, shot["shot_id"], digest)
        if not src.is_file():
            missing.append(shot["shot_id"])
            continue
        out = ON_DIR / f"{shot['shot_id']}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(video_node.FPS),
             "-i", str(src), "-vf", chain, "-frames:v", "1", "-update", "1", str(out)],
            check=True, capture_output=True)
        # cwd is ROOT, so a plate path out of the manifest is already repo-relative.
        rows.append({"shot_id": shot["shot_id"], "path": _rel(out),
                     "source": _rel(src), "source_size": _dimensions(src),
                     "size": _dimensions(out), "passes": len(shot["cast"])})
        print(f"  ✓ {shot['shot_id']}  {rows[-1]['source_size']} -> {rows[-1]['size']}", flush=True)
    print(f"publish-on: {len(rows)} published, {len(missing)} not rendered yet")
    _write(HERE / "on_partial.json", {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "arm": "on", "source": "publish-on (recovered from a killed render-on)",
        "published": len(rows), "not_rendered": missing, "frames": rows,
        "note": ("`report` reads on.json, NOT this file. A recovered partial arm is not a "
                 "measured sweep — it has no single-call wall clock and its pass accounting "
                 "is unknown, so publish-on deliberately does not overwrite on.json. Run "
                 "`render-on` to completion before `report`."),
    })
    if missing:
        print(f"NOTE: {len(missing)} shots not rendered. `report` will read the LAST "
              "complete on.json, which does not describe this partial state — finish "
              "`render-on` first.")
    return 0


async def _stats_argv(settings) -> list | None:
    from yt_flow.services import comfyui_client

    stats = await comfyui_client.get_system_stats(settings.comfyui_url)
    return ((stats or {}).get("system") or {}).get("argv")


# ── score ────────────────────────────────────────────────────────────────────


async def cmd_score(args) -> int:
    """Blind axis first (frame bytes only), then DSG (sentence-fed, secondary).

    The VLM is blind by construction — it receives image bytes and a prompt that names
    no arm. The opaque filenames exist for the *human* reading the grids.
    """
    settings = Settings()
    if not settings.character_vision_api_key:
        print("STOP: YTFLOW_CHARACTER_VISION_API_KEY is absent — the instrument cannot run.")
        return 2
    axis = _axis()
    manifest = _manifest()
    by_id = {s["shot_id"]: s for s in manifest["shots"]}

    # Only shots present in BOTH arms are scored: an unpaired frame is not a pair.
    frames = []
    for shot_id in sorted(by_id):
        off, on = OFF_DIR / f"{shot_id}.png", ON_DIR / f"{shot_id}.png"
        if not (off.is_file() and on.is_file()):
            print(f"  - {shot_id}: unpaired (off={off.is_file()} on={on.is_file()}), skipped")
            continue
        for arm, path in (("off", off), ("on", on)):
            frames.append({"blind_id": _blind_id(shot_id, arm), "shot_id": shot_id,
                           "arm": arm, "source": str(path.relative_to(ROOT))})
    frames.sort(key=lambda f: f["blind_id"])  # order carries no arm information

    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    for frame in frames:
        shutil.copyfile(ROOT / frame["source"], BLIND_DIR / f"{frame['blind_id']}.png")
    _write(HERE / "pairs_key.json", {
        "salt": SALT,
        "id_rule": "sha256(f'{shot_id}|{arm}|{salt}').hexdigest()[:12]",
        "frames": frames,
    })

    progress = HERE / "score_progress.jsonl"
    done = {}
    if progress.is_file() and not args.fresh:
        for line in progress.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["blind_id"]] = row
        print(f"score: resuming, {len(done)} rows already on disk")

    rows = []
    with progress.open("a", encoding="utf-8") as log:
        for i, frame in enumerate(frames, 1):
            if frame["blind_id"] in done:
                rows.append(done[frame["blind_id"]])
                continue
            image = (BLIND_DIR / f"{frame['blind_id']}.png").read_bytes()
            row = dict(frame)
            try:
                verdict = await axis._ask_once(
                    settings, axis.BLIND_PROMPT, image, "readable", axis._bool_field)
                row.update(status="scored", readable=verdict["readable"],
                           place=verdict.get("place"), event=verdict.get("event"))
            except Exception as exc:  # noqa: BLE001 — a dead frame is data, not a crash
                row.update(status="error", blind_error=f"{type(exc).__name__}: {exc}",
                           readable=None, place=None, event=None)
            if row["status"] == "scored":
                await axis._score_dsg(settings, row, by_id[frame["shot_id"]]["sentences"], image)
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
            log.flush()
            rows.append(row)
            print(f"  [{i}/{len(frames)}] {frame['blind_id']} readable={row.get('readable')} "
                  f"dsg={row.get('dsg_score')} place={(row.get('place') or '')[:38]!r}", flush=True)

    _write(HERE / "results.json", {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run": RUN,
        "instrument": "scripts/score_shot_narration.py (Story 13.2), imported unmodified",
        "vision_model": settings.character_vision_model,
        "qg_model": axis.QG_MODEL,
        "reps": 1,
        "blind_prompt": axis.BLIND_PROMPT,
        "salt": SALT,
        "arms": {arm: _arm_summary(axis, [r for r in rows if r["arm"] == arm])
                 for arm in ("off", "on")},
        "rows": rows,
    })
    return 0


def _arm_summary(axis, rows: list[dict]) -> dict:
    scored = [r for r in rows if r["status"] == "scored"]
    dsg = [r["dsg_score"] for r in scored if r.get("dsg_score") is not None]
    unreadable = [r["shot_id"] for r in scored if r["readable"] is False]
    corridor = [r["shot_id"] for r in scored if CORRIDOR in (r.get("place") or "").lower()]
    return {
        "frames": len(rows), "scored": len(scored),
        "errored": [r["shot_id"] for r in rows if r["status"] == "error"],
        "readable": sum(1 for r in scored if r["readable"] is True),
        "unreadable": len(unreadable), "unreadable_shots": sorted(unreadable),
        "unreadable_pct": round(100 * len(unreadable) / len(scored), 1) if scored else None,
        "corridor": len(corridor), "corridor_shots": sorted(corridor),
        "corridor_pct": round(100 * len(corridor) / len(scored), 1) if scored else None,
        "place_unclear": sum(1 for r in scored if (r.get("place") or "").strip().lower() == "unclear"),
        "event_unclear": sum(1 for r in scored if (r.get("event") or "").strip().lower() == "unclear"),
        "mean_dsg": round(statistics.fmean(dsg), 4) if dsg else None,
        "dsg_scorable": len(dsg),
        "dsg_errored": sum(1 for r in scored if "dsg_error" in r),
        **{k: v for k, v in axis.summarize_dsg(scored).items()
           if k in ("dsg_unscorable", "dsg_qa_errors_total", "dsg_excluded_person_total",
                    "dsg_invalidated_total", "dsg_label_disagreements_total")},
    }


# ── report ───────────────────────────────────────────────────────────────────

# The pre-registered rule, restated as code. Committed in PREREGISTRATION.md before
# `score` ran; nothing here reads a score to choose a threshold.
FLIP_SLACK = 1          # FLIP iff b - c <= 1
VETO_FAILED_PASSES = 5  # >= this many failed passes -> STAY OFF regardless
COST_BUDGET_HOURS = 1.0
RUN_SHOTS = 43          # the full run the cost line is projected onto


def cmd_report(args) -> int:
    results = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    manifest = _manifest()
    on_meta = json.loads((HERE / "on.json").read_text(encoding="utf-8"))
    screening = json.loads((HERE / "screening.json").read_text(encoding="utf-8"))
    if on_meta.get("preflight_failed"):
        # A preflight bail writes an on.json with zero frames and no cost data. Reading it
        # applies the veto to 0 and the cost line to nothing, i.e. prints FLIP for a run
        # that rendered nothing at all.
        print(f"STOP: on.json is a preflight bail ({on_meta['preflight_failed']}) — no cost "
              "or pass data. Fix ComfyUI's launcher and re-run `render-on`.")
        return 2

    rows = {(r["shot_id"], r["arm"]): r for r in results["rows"]}
    shot_ids = sorted({s for s, _ in rows})
    paired = [s for s in shot_ids
              if rows.get((s, "off"), {}).get("status") == "scored"
              and rows.get((s, "on"), {}).get("status") == "scored"]

    b = [s for s in paired if rows[(s, "off")]["readable"] and not rows[(s, "on")]["readable"]]
    c = [s for s in paired if not rows[(s, "off")]["readable"] and rows[(s, "on")]["readable"]]
    both = [s for s in paired if rows[(s, "off")]["readable"] and rows[(s, "on")]["readable"]]
    neither = [s for s in paired
               if not rows[(s, "off")]["readable"] and not rows[(s, "on")]["readable"]]

    failed_passes = on_meta.get("passes_failed", 0)
    delta = len(b) - len(c)
    vetoed = failed_passes >= VETO_FAILED_PASSES
    axis_verdict = "FLIP" if delta <= FLIP_SLACK else "STAY OFF"
    # NOT `seconds_per_pass_mean`: that is total-wall-clock / passes-PUBLISHED, and
    # `recompose_run_shots` skips a shot whose content-addressed output already exists, so
    # a re-run publishes 40 passes having rendered 3 and reports 7.8 s/pass. The per-shot
    # mtime deltas are written by the render itself and a cache hit leaves its file (and
    # therefore its delta) untouched, so they survive re-runs. Weighted by passes/shot.
    mt = on_meta.get("per_shot_from_mtime") or []
    # A delta that spans two `recompose_run_shots` invocations is wall clock between runs,
    # not render time — it includes whatever a human did in between. On this run S00101 and
    # S00102 were re-rendered ~4 min after the sweep ended, contributing 227.6 s and 130.9 s
    # deltas for 3 passes. Drop any row above 3x the median s/pass. MEASURED ON THIS RUN:
    # the filter drops NOTHING — S00101/S00102 are 113.8 and 130.9 s/pass against a 91.0
    # median, so the contamination is 107.9 vs 106.9 s/pass (1.199 h vs 1.188 h, both over
    # the 1.0 h line). The guard is here for the case it was written for: a run resumed the
    # next day, where one delta is hours of idle time.
    if len(mt) >= 5:
        med = statistics.median(e["seconds_per_pass"] for e in mt)
        kept = [e for e in mt if e["seconds_per_pass"] <= 3 * med]
        dropped = [e["shot_id"] for e in mt if e["seconds_per_pass"] > 3 * med]
    else:
        kept, dropped, med = mt, [], None
    secs = sum(e["seconds"] for e in kept)
    npass = sum(e["passes"] for e in kept)
    # The power of the deciding axis, computed rather than asserted: config.py and the
    # override record both quote these, and "every number re-derives with `report`" has to
    # include the ones that weaken the result.
    npaired = len(paired)
    disc = len(b) + len(c)
    p_two_sided = min(1.0, 2 * sum(comb(disc, k) for k in range(min(len(b), len(c)) + 1)) / 2**disc) \
        if disc else 1.0
    _d = (len(b) - len(c)) / npaired if npaired else 0.0
    _se = (((len(b) + len(c)) - ((len(b) - len(c)) ** 2) / npaired) ** 0.5) / npaired \
        if npaired else 0.0
    ci = [round(100 * (_d - 1.96 * _se), 1), round(100 * (_d + 1.96 * _se), 1)]

    if not npass:
        # REFUSE, do not default. `seconds_per_pass_mean` is None on an all-cache-hit
        # re-run, and `None or 0` made projected_h 0.0 -> cost_blocks False -> FLIP. An
        # unmeasured cost must never be the reason a gate opens.
        print("STOP: no per-shot mtime data in on.json — cost is unmeasured and the "
              "pre-registered cost line cannot be applied. Re-run `render-on`.")
        return 2
    per_pass = round(secs / npass, 1)
    per_pass_source = (f"mtime deltas over {len(kept)} shots / {npass} passes"
                       + (f"; dropped {dropped} as cross-invocation gaps (>3x median "
                          f"{med:.1f}s/pass)" if dropped else ""))
    projected_h = round(per_pass * manifest["totals"]["recompose_passes"] / 3600, 2)
    cost_blocks = projected_h > COST_BUDGET_HOURS

    if vetoed:
        verdict, flag = "STAY OFF (veto)", False
    elif axis_verdict == "STAY OFF":
        verdict, flag = "STAY OFF", False
    elif cost_blocks:
        verdict, flag = "(a) closed PASS, (c) still blocks", False
    else:
        verdict, flag = "FLIP", True

    override = None
    ovr = HERE / "VERDICT_OVERRIDE.md"
    if ovr.is_file():
        override = ovr.read_text(encoding="utf-8").strip()
        print("  (a VERDICT_OVERRIDE.md is present — recorded alongside, never merged in)")

    off, on = results["arms"]["off"], results["arms"]["on"]
    lines = _readme(screening, manifest, on_meta, results, off, on, paired,
                    b, c, both, neither, delta, failed_passes, vetoed, axis_verdict,
                    per_pass, per_pass_source, projected_h, cost_blocks, verdict, flag, rows)
    if override:
        lines += "\n\n## HUMAN OVERRIDE\n\n" + override + "\n"
    (HERE / "README.md").write_text(lines, encoding="utf-8")
    print(f"  -> {(HERE / 'README.md').relative_to(ROOT)}")
    _write(HERE / "verdict.json", {
        "paired_n": len(paired), "b": len(b), "c": len(c), "b_minus_c": delta,
        "b_shots": b, "c_shots": c, "both_readable": len(both), "neither_readable": len(neither),
        "exact_mcnemar_p_two_sided": round(p_two_sided, 4),
        "unreadable_difference_pp": round(100 * _d, 1),
        "unreadable_difference_ci95_pp": ci,
        "power_note": ("computed from b/c/n by `report`. n=33 with 3 discordant pairs rules "
                       "out a catastrophe and nothing finer; the CI contains the incumbent's "
                       "own 7 pp claim, so this measurement does not refute the figures it "
                       "withdrew — the collinearity arithmetic does."),
        "failed_passes": failed_passes, "veto_triggered": vetoed,
        "deciding_axis_verdict": axis_verdict,
        "seconds_per_pass": per_pass, "seconds_per_pass_source": per_pass_source,
        "projected_hours_43_shot_run": projected_h,
        "cost_blocks": cost_blocks, "verdict": verdict,
        # What the RULE yields. The shipped flag can differ: a human viewing verdict may
        # override, and that is recorded in VERDICT_OVERRIDE.md rather than folded in here,
        # so this file always shows what the pre-registered rule alone concluded.
        "shot_recompose_enabled_per_rule": flag,
        "human_override": override,
    })
    print(f"\nVERDICT: {verdict}   (b={len(b)}, c={len(c)}, b-c={delta}, n={len(paired)}, "
          f"failed passes={failed_passes})")
    print(f"shot_recompose_enabled -> {flag}")
    return 0


def _pct(n, d):
    return f"{n} ({round(100 * n / d, 1)}%)" if d else f"{n} (n/a)"


def _readme(screening, manifest, on_meta, results, off, on, paired, b, c, both, neither,
            delta, failed_passes, vetoed, axis_verdict, per_pass, per_pass_source,
            projected_h, cost_blocks, verdict, flag, rows) -> str:
    arm = screening["by_arm"]
    cast = screening["by_cast_presence"]
    n = len(paired)
    out = [
        "# Story 10.1e — recompose ON/OFF paired scoring, and the default verdict",
        "",
        f"Run `{RUN}`, scored {results['generated_at']}. Every number below is re-derivable "
        "from `results.json` + `pairs.json` + `on.json` with `run_pairs.py report`.",
        "",
        f"## VERDICT: **{verdict}** — `shot_recompose_enabled = {flag}`",
        "",
        f"Deciding axis (blind `readable`, paired, n={n}): **b={len(b)}, c={len(c)}, "
        f"b−c={delta}** against the pre-registered `b−c ≤ {FLIP_SLACK}` ⇒ {axis_verdict}.  ",
        f"Veto (≥{VETO_FAILED_PASSES} of {manifest['totals']['recompose_passes']} passes fail): "
        f"{failed_passes} failed ⇒ {'TRIGGERED' if vetoed else 'not triggered'}.  ",
        f"Cost: {per_pass}s/pass ({per_pass_source}) × "
        f"{manifest['totals']['recompose_passes']} passes = "
        f"{projected_h} h added to a {RUN_SHOTS}-shot run ⇒ "
        f"{'over' if cost_blocks else 'within'} the 1.0 h line in 10.1c item (c).",
        "",
        "## 1. Screening — why 10.4's claim (a) is not a treatment measurement",
        "",
        "`baseline_v2.json`'s 66 rows, split two ways:",
        "",
        "| split | n | unreadable | blind `place` = corridor |",
        "|---|---:|---:|---:|",
        f"| frame is `recomposed/` | {arm['recomposed']['n']} | "
        f"{arm['recomposed']['unreadable']} ({arm['recomposed']['unreadable_pct']}%) | "
        f"{arm['recomposed']['corridor']} ({arm['recomposed']['corridor_pct']}%) |",
        f"| frame is `images/` (plate) | {arm['plate']['n']} | "
        f"{arm['plate']['unreadable']} ({arm['plate']['unreadable_pct']}%) | "
        f"{arm['plate']['corridor']} ({arm['plate']['corridor_pct']}%) |",
        f"| shot cast is non-empty | {cast['cast_present']['n']} | "
        f"{cast['cast_present']['unreadable']} ({cast['cast_present']['unreadable_pct']}%) | "
        f"{cast['cast_present']['corridor']} ({cast['cast_present']['corridor_pct']}%) |",
        f"| shot cast is empty | {cast['cast_empty']['n']} | "
        f"{cast['cast_empty']['unreadable']} ({cast['cast_empty']['unreadable_pct']}%) | "
        f"{cast['cast_empty']['corridor']} ({cast['cast_empty']['corridor_pct']}%) |",
        "",
        f"Shot-id overlap between the two arms: **{len(screening['arm_shot_id_overlap'])}**. "
        f"Contingency `{screening['contingency']}`. The two splits select byte-identical shot "
        f"sets (`splits_identical: {screening['splits_identical']}`).",
        "",
        f"> {screening['conclusion']}",
        "",
        "## 2. The paired set",
        "",
        f"- {manifest['totals']['shots_in_run']} shots in the run, "
        f"{manifest['totals']['recompose_eligible']} recompose-eligible, "
        f"**{manifest['totals']['paired']} paired**, "
        f"{manifest['totals']['recompose_passes']} recompose passes.",
        "- Cast cards resolved **once** (`pairs.json`) and consumed by both arms, so angle "
        "selection is held constant.",
        f"- OFF: `render_composite_still` → `_build_card_chain` "
        f"(harmonization tier {manifest['settings_snapshot']['composite_harmonization_tier']}, "
        "production `ground_y`/`occlusion_mask` from `compositing_service.resolve_placements`), "
        "1920×1080.",
        f"- ON: `recompose_run_shots`, one call, preflight live — "
        f"`{on_meta.get('stats')}`; frames re-framed through the OFF arm's own "
        "`_zoompan_filter` chain so resolution and crop cannot identify the arm.",
        f"- Scored blind (frame bytes only) with 13-2's `BLIND_PROMPT`, then DSG. "
        f"Judge `{results['vision_model']}`, QG `{results['qg_model']}`, temperature 0, reps 1.",
        "",
        "## 3. Deciding axis — blind `readable`, paired",
        "",
        "| | ON readable | ON unreadable |",
        "|---|---:|---:|",
        f"| **OFF readable** | {len(both)} | **b = {len(b)}** |",
        f"| **OFF unreadable** | **c = {len(c)}** | {len(neither)} |",
        "",
        f"`b − c = {delta}`. Pre-registered: FLIP iff `b − c ≤ {FLIP_SLACK}`, STAY OFF iff "
        f"`b − c ≥ {FLIP_SLACK + 1}` ⇒ **{axis_verdict}**.",
        "",
        f"- b (readable OFF, unreadable ON): {', '.join(f'`{s}`' for s in b) or '—'}",
        f"- c (unreadable OFF, readable ON): {', '.join(f'`{s}`' for s in c) or '—'}",
        "",
        "Per-arm marginals (record-only — the paired table above is the decision):",
        "",
        "| arm | scored | readable | unreadable | `place`=corridor | `place` unclear | "
        "`event` unclear | mean DSG |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        f"| OFF (overlay) | {off['scored']} | {off['readable']} | "
        f"{off['unreadable']} ({off['unreadable_pct']}%) | {off['corridor']} "
        f"({off['corridor_pct']}%) | {off['place_unclear']} | {off['event_unclear']} | "
        f"{off['mean_dsg']} |",
        f"| ON (recompose) | {on['scored']} | {on['readable']} | "
        f"{on['unreadable']} ({on['unreadable_pct']}%) | {on['corridor']} "
        f"({on['corridor_pct']}%) | {on['place_unclear']} | {on['event_unclear']} | "
        f"{on['mean_dsg']} |",
        "",
        "**Both directions, as the rule requires.** Secondary axes never override the "
        "deciding axis; they are printed here so a reader can see which way each one "
        "points, including the ones that point against the verdict:",
        "",
        f"- corridor misread: OFF {off['corridor_pct']}% vs ON {on['corridor_pct']}% "
        f"({'ON worse' if (on['corridor_pct'] or 0) > (off['corridor_pct'] or 0) else 'ON better or equal'})",
        f"- mean DSG: OFF {off['mean_dsg']} vs ON {on['mean_dsg']} "
        f"({'ON worse' if (on['mean_dsg'] or 0) < (off['mean_dsg'] or 0) else 'ON better or equal'}); "
        f"DSG errored OFF {off['dsg_errored']} / ON {on['dsg_errored']}, "
        f"QA errors OFF {off['dsg_qa_errors_total']} / ON {on['dsg_qa_errors_total']} "
        "(a nonzero QA-error count biases that arm's mean DOWN and is not a frame defect)",
        f"- `event` unclear: OFF {off['event_unclear']} vs ON {on['event_unclear']}",
        "",
        "## 4. Cost (10.1c item (c), record-only for the (a) decision)",
        "",
        f"- ON arm wall clock: **{on_meta.get('total_seconds')}s** for "
        f"{on_meta.get('passes_completed')} completed passes across "
        f"{on_meta.get('rendered')} shots ⇒ **{per_pass}s/pass**.",
        f"- Projected onto this run's {manifest['totals']['recompose_passes']} passes: "
        f"**{projected_h} h** added to a {RUN_SHOTS}-shot run.",
        f"- ComfyUI argv during the render: `{on_meta.get('comfyui_argv')}`.",
        "",
        "## 5. Per-shot rows",
        "",
        "| shot | OFF readable | ON readable | OFF place | ON place | OFF DSG | ON DSG |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for s in paired:
        o, n_ = rows[(s, "off")], rows[(s, "on")]
        mark = " **b**" if s in b else (" **c**" if s in c else "")
        out.append(
            f"| `{s}`{mark} | {o['readable']} | {n_['readable']} | "
            f"{(o.get('place') or '')[:34]} | {(n_.get('place') or '')[:34]} | "
            f"{o.get('dsg_score')} | {n_.get('dsg_score')} |")
    out += [
        "",
        "## 6. Re-derive",
        "",
        "```",
        "uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py screen",
        "uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py manifest",
        "uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py render-off",
        "uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py render-on",
        "uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py score",
        "uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py report",
        "uv run python _bmad-output/implementation-artifacts/10-1e-live-validation/run_pairs.py grid",
        "```",
        "",
        "`off/`, `on/` and `blind/` are gitignored raw renders — see this directory's "
        "`.gitignore` for what regenerates them and what must never be blanket-deleted.",
        "",
        "## 7. Sample band",
        "",
        f"Every rate above is over the **{n} paired shots** of run `{RUN}` "
        f"(scenes {sorted({s['scene_num'] for s in manifest['shots']})}), one blind call per "
        "frame at temperature 0, `qwen-vl-plus`. The blind prompt is 13-2's `BLIND_PROMPT` "
        "unchanged, including its `_CARD_NOTE` sentence — which tells the judge the frame is "
        "a background plate whose people are composited later. That sentence is wrong for "
        "BOTH arms here (both carry figures) and is deliberately left in: changing it would "
        "make this not 13-2's instrument, and it biases both arms identically.",
    ]
    return "\n".join(out) + "\n"


# ── grid ─────────────────────────────────────────────────────────────────────


def cmd_grid(args) -> int:
    """The adjudication images: one contact sheet + one pair sheet per discordant shot."""
    from PIL import Image, ImageDraw

    manifest = _manifest()
    # Blocked-run mode: no scoring happened, so there is no verdict to cite and no blind
    # package to protect. The sheet is then labelled by shot_id and answers a different,
    # still-necessary question — did the two renderers produce sane frames at all.
    partial = not (HERE / "verdict.json").is_file()
    verdict = {"b_shots": [], "c_shots": []} if partial else \
        json.loads((HERE / "verdict.json").read_text(encoding="utf-8"))
    key = {} if partial else {
        (f["shot_id"], f["arm"]): f["blind_id"]
        for f in json.loads((HERE / "pairs_key.json").read_text(encoding="utf-8"))["frames"]}
    shots = [s["shot_id"] for s in manifest["shots"]
             if (OFF_DIR / f"{s['shot_id']}.png").is_file()
             and (partial or (ON_DIR / f"{s['shot_id']}.png").is_file())]

    tw, th = 256, 144   # 512px per pair on the long edge
    cols = 6
    rowsn = -(-len(shots) // cols)
    sheet = Image.new("RGB", (cols * tw * 2 + (cols + 1) * 8, rowsn * (th + 20) + 8), "black")
    draw = ImageDraw.Draw(sheet)
    for i, shot_id in enumerate(shots):
        cx, cy = i % cols, i // cols
        x = 8 + cx * (tw * 2 + 8)
        y = 8 + cy * (th + 20)
        for j, arm in enumerate(("off", "on")):
            src = (OFF_DIR if arm == "off" else ON_DIR) / f"{shot_id}.png"
            if not src.is_file():   # partial mode: the ON arm stopped after 2 shots
                draw.rectangle([x + j * tw, y, x + j * tw + tw - 1, y + th - 1], fill="#222222")
                draw.text((x + j * tw + 6, y + th // 2 - 6), "not rendered", fill="#777777")
                continue
            with Image.open(src) as im:
                sheet.paste(im.convert("RGB").resize((tw, th)), (x + j * tw, y))
        # The blind ids, NOT the arm: the grid is the human-blind package.
        label = shot_id if partial else \
            f"{key[(shot_id, 'off')][:6]} | {key[(shot_id, 'on')][:6]}"
        draw.text((x, y + th + 4), label, fill="white")
    out_name = "partial_grid.jpg" if partial else "pairs_grid.jpg"
    sheet.save(HERE / out_name, quality=88)
    print(f"  -> {(HERE / out_name).relative_to(ROOT)}  {sheet.size}")

    # Pair sheets for every discordant shot — these are what the verdict cites, so they
    # are labelled with the arm (the reveal comes after the grid above is read blind).
    pair_dir = HERE / "pair_sheets"
    pair_dir.mkdir(exist_ok=True)
    cited = verdict["b_shots"] + verdict["c_shots"] if not partial else \
        [s for s in shots if (ON_DIR / f"{s}.png").is_file()]
    for shot_id in cited:
        which = ("unscored_both-arms-rendered" if partial
                 else "b_readable-OFF_unreadable-ON" if shot_id in verdict["b_shots"]
                 else "c_unreadable-OFF_readable-ON")
        pw, ph = 512, 288
        sheet = Image.new("RGB", (pw * 2 + 24, ph + 34), "black")
        draw = ImageDraw.Draw(sheet)
        for j, arm in enumerate(("off", "on")):
            src = (OFF_DIR if arm == "off" else ON_DIR) / f"{shot_id}.png"
            with Image.open(src) as im:
                sheet.paste(im.convert("RGB").resize((pw, ph)), (8 + j * (pw + 8), 26))
            draw.text((8 + j * (pw + 8), 8),
                      f"{arm.upper()}  {key.get((shot_id, arm), '')}", fill="white")
        draw.text((8, ph + 30 - 12), f"{shot_id}  {which}", fill="#ffcc00")
        sheet.save(pair_dir / f"{shot_id}_{which}.jpg", quality=88)
    print(f"  -> {(pair_dir).relative_to(ROOT)}/  {len(cited)} pair sheet(s)")
    return 0


# ── viewing (the human gate the scored axis does not cover) ──────────────────

VIEW_DIR = HERE / "viewing"
# Shots chosen to exercise the three questions the blind axis cannot answer:
# grounding (near/mid cast with feet in frame), the motion the ON arm removes
# (movement_mode set), and the 3 shots the deciding axis split on.
VIEW_SHOTS = ["S00101", "S00104", "S00202", "S00405", "S00501", "S00600", "S00800", "S00903"]
VIEW_FALLBACK_SEC = 4.0


def _clip_duration(scene_num: int, shot_id: str) -> float:
    """The shipped clip's own duration, so the Ken Burns runs at production speed.

    A fixed duration would change zoom velocity, and velocity is exactly what a
    'does it float' judgement reads. Falls back only where the run has no clip.
    """
    src = Path(f"workspace/{RUN}/shots/scene_{scene_num:03d}_{shot_id}.mp4")
    if not src.is_file():
        return VIEW_FALLBACK_SEC
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(src)], capture_output=True, text=True)
    try:
        return round(float(out.stdout.strip()), 2)
    except ValueError:
        return VIEW_FALLBACK_SEC


async def cmd_viewing(args) -> int:
    """Side-by-side OFF|ON motion clips + a per-character identity sheet. No GPU.

    Both arms go through the SHIPPED `_compose_shot_clip`, so the OFF arm keeps card
    scale, ground_y, occlusion, contact shadow, z-order and 1.9c idle motion, and the
    ON arm takes the recomposed frame with no cards — the production fork, exactly.

    EXCLUDED, and stated rather than hidden: 11.5 depth parallax. It needs the injected
    2.5D renderer; with none injected `build_motion_source` falls back to legacy, so
    BOTH arms here are legacy Ken Burns. Parallax is an OFF-arm-only motion layer, so
    its absence understates the incumbent on exactly the axis being judged.
    """
    from yt_flow.pipeline.nodes import video as video_node

    manifest = _manifest()
    by_id = {s["shot_id"]: s for s in manifest["shots"]}
    # PRODUCTION tier, never a literal. This was hardcoded 0 for one build, which switched
    # off `build_sprite_tint` AND `build_contact_shadow` (video.py:1577/1650, gated on
    # tier >= 1) — i.e. it handicapped the OFF arm on exactly the two things the flip
    # rationale cites as the ON arm's advantage, and the scored OFF arm used tier 1.
    tier = Settings().composite_harmonization_tier
    VIEW_DIR.mkdir(parents=True, exist_ok=True)
    made = []
    for i, shot_id in enumerate(VIEW_SHOTS):
        shot = by_id.get(shot_id)
        on_png = ON_DIR / f"{shot_id}.png"
        if not shot or not on_png.is_file():
            print(f"  - {shot_id}: skipped (manifest={bool(shot)} on={on_png.is_file()})")
            continue
        dur = _clip_duration(shot["scene_num"], shot_id)
        spec = video_node.select_effect({"shot_id": shot_id, "camera_movement": None},
                                        shot["scene_num"] - 1)
        legs = {}
        for arm, bg, cards in (("off", shot["plate"], [dict(c) for c in shot["cast"]]),
                               ("on", str(on_png), [])):
            sd = {"shot_id": shot_id, "image_path": bg}
            motion = video_node._legacy_motion(
                sd, spec, dur, parallax_enabled=False, camera_shake="")
            out = VIEW_DIR / f"_{arm}_{shot_id}.mp4"
            await video_node._compose_shot_clip(
                sd, motion, dur, out, cards=cards, mood=shot.get("mood"),
                composite_harmonization_tier=tier, idle_motion_enabled=(arm == "off"))
            legs[arm] = out
        pair = VIEW_DIR / f"{i:02d}_{shot_id}.mp4"
        lbl = ("drawtext=text='OFF overlay':x=16:y=16:fontsize=34:fontcolor=white:"
               "box=1:boxcolor=black@0.6[l];")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(legs["off"]), "-i", str(legs["on"]),
             "-filter_complex",
             f"[0:v]{lbl}"
             "[1:v]drawtext=text='ON recompose':x=16:y=16:fontsize=34:fontcolor=white:"
             "box=1:boxcolor=black@0.6[r];[l][r]hstack=inputs=2,scale=1920:-2[v]",
             "-map", "[v]", "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
             str(pair)], check=True, capture_output=True)
        legs["off"].unlink()
        legs["on"].unlink()
        made.append({"shot_id": shot_id, "seconds": dur, "clip": _rel(pair),
                     "cast": [c["card_key"] for c in shot["cast"]],
                     "duration_source": "shipped clip" if dur != VIEW_FALLBACK_SEC else "fallback"})
        print(f"  ✓ {shot_id}  {dur}s  {_rel(pair)}", flush=True)

    if made:
        lst = VIEW_DIR / "_concat.txt"
        lst.write_text("".join(f"file '{Path(m['clip']).name}'\n" for m in made))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(VIEW_DIR / "all_pairs.mp4")],
                       check=True, capture_output=True)
        lst.unlink()
        print(f"  -> {_rel(VIEW_DIR / 'all_pairs.mp4')}")

    # Identity drift: recompose redraws every figure per shot, so the same character can
    # wander across shots. Full frames, not crops — the ON arm's figure position is the
    # model's choice, so there is no reliable box to crop to.
    from PIL import Image, ImageDraw
    sheets = []
    for key in ("SCP-049", "SCP-049-2", "STOCK-researcher", "STOCK-d-class"):
        shots = [s["shot_id"] for s in manifest["shots"]
                 if any(c["card_key"] == key for c in s["cast"])
                 and (ON_DIR / f"{s['shot_id']}.png").is_file()]
        if len(shots) < 3:
            continue
        tw, th, cols = 256, 144, 8
        rows = -(-len(shots) // cols)
        sheet = Image.new("RGB", (cols * tw + 8, rows * 2 * (th + 16) + 8), "black")
        d = ImageDraw.Draw(sheet)
        for j, sid in enumerate(shots):
            cx, cy = j % cols, j // cols
            for k, arm in enumerate(("off", "on")):
                y = 4 + (cy * 2 + k) * (th + 16)
                with Image.open((OFF_DIR if arm == "off" else ON_DIR) / f"{sid}.png") as im:
                    sheet.paste(im.convert("RGB").resize((tw, th)), (4 + cx * tw, y))
                d.text((8 + cx * tw, y + th + 2), f"{arm.upper()} {sid}",
                       fill="#ffcc00" if arm == "on" else "#88ccff")
        out = VIEW_DIR / f"identity_{key}.jpg"
        sheet.save(out, quality=88)
        sheets.append({"card_key": key, "shots": shots, "sheet": _rel(out)})
        print(f"  -> {_rel(out)}  ({len(shots)} shots, OFF row over ON row)")

    prev = {}
    if (HERE / "viewing.json").is_file():   # a human's read-once notes outlive a re-render
        prev = json.loads((HERE / "viewing.json").read_text(encoding="utf-8"))
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "purpose": ("the human gate 10.1e's scored axis does not cover: grounding, the "
                    "motion the ON arm removes by design, and per-shot identity drift"),
        "excluded": ("11.5 depth parallax — needs the injected 2.5D renderer; both arms "
                     "here are legacy Ken Burns, which understates the OFF arm"),
        "harmonization_tier": tier,
        "clips": made, "identity_sheets": sheets,
    }
    if "read_once_observations" in prev:
        payload["read_once_observations"] = prev["read_once_observations"]
    _write(HERE / "viewing.json", payload)
    return 0


# ── cli ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("screen")
    m = sub.add_parser("manifest")
    m.add_argument("--allow-depth-inference", action="store_true")
    sub.add_parser("render-off")
    sub.add_parser("render-on")
    sub.add_parser("publish-on")
    s = sub.add_parser("score")
    s.add_argument("--fresh", action="store_true", help="ignore score_progress.jsonl")
    sub.add_parser("report")
    sub.add_parser("grid")
    sub.add_parser("viewing")
    args = parser.parse_args()

    handlers = {
        "screen": cmd_screen, "manifest": cmd_manifest, "render-off": cmd_render_off,
        "render-on": cmd_render_on, "publish-on": cmd_publish_on,
        "score": cmd_score, "report": cmd_report, "grid": cmd_grid,
        "viewing": cmd_viewing,
    }
    handler = handlers[args.cmd]
    return asyncio.run(handler(args)) if asyncio.iscoroutinefunction(handler) else handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
