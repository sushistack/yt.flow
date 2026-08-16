"""Run-level orchestration for Story 10.1c shot recompose.

The domain half lives in `pipeline/nodes/shot_recompose.py` (prompt construction, pass
ordering, workflow assembly). This half is what that module deliberately cannot reach: the
ComfyUI client, the workspace, and the character descriptions the instruction needs.

Contract with `video_node` (see `inject_recompose_resolver`): rewrite each recomposed shot's
``image_path`` in place and drop that shot from the returned cast map, so the composition
stage takes its background-only path and nothing is overlaid on a frame that already has
the characters in it.
"""

import logging
from pathlib import Path

from yt_flow.config import Settings
from yt_flow.pipeline.nodes.shot_recompose import (
    RECOMPOSED_DIR,
    recompose_cache_path,
    recompose_digest,
    recompose_shot,
)
from yt_flow.services import comfyui_client

logger = logging.getLogger(__name__)

# How each card key is described to the model. An appearance description, never "the second
# image" — ordinal references to its own inputs are not resolved (live 2026-08-09: two-card
# shots put the wrong figure on the wrong side at the wrong scale until this changed).
# ponytail: a module constant. A card key without an entry is skipped rather than guessed at,
# because a wrong description silently redraws the wrong character.
CARD_LOOKS: dict[str, str] = {
    "SCP-049": "the figure in the long black hooded coat and white plague-doctor beak mask",
    "SCP-049-2": "the reanimated figure in torn surgical scrubs",
    "STOCK-d-class": "the man in the orange prison jumpsuit",
    "STOCK-researcher": "the person in a white lab coat over office clothes",
    "STOCK-security": "the guard in black tactical gear",
}

# ── Story 10.1d: the ComfyUI startup state this path requires ─────────────────
# flag -> (the value the restart command must pass, why the path needs it). THE single
# declaration: this requirement lived only as prose inside a config comment, and prose is
# not enforcement — run e5ed4b3a (2026-08-15) burned 90 minutes and two wrong hypotheses
# on a box grinding at 491 s/shot while every health probe answered 200. A ComfyUI flag
# rename must have exactly one edit site, and the restart command below is derived from
# this table rather than written out a second time.
#
# A NON-EMPTY value means "this flag takes a positive-integer value", and the check
# enforces that, not just the flag's presence: ComfyUI declares `--cache-lru type=int
# default=0` (comfy/cli_args.py) and enables the LRU cache only `if args.cache_lru > 0`
# (main.py), so `--cache-lru 0` in argv is byte-for-byte the eviction behaviour this
# table exists to prevent. An empty value means presence is the whole requirement.
#
# The fourth prerequisite is not a flag: free system RAM >= `recompose_preflight_min_free_ram_gb`.
# It is listed with the flags on purpose — `--disable-smart-memory` buys its deadlock fix by
# offloading to system RAM, so the two conditions are one decision.
#
# DELIBERATELY NOT CHECKED: the fp8 text encoder. `qwen_2.5_vl_7b_fp8_scaled.safetensors`
# is pinned in the workflow JSON's `clip` node — a property of the graph file, absent from
# argv and from /system_stats — and a missing file fails fast at that node with ComfyUI's
# own error naming the file. Synthesising a worse version of that message here would need a
# second HTTP endpoint (`/object_info`) for no added information.
REQUIRED_FLAGS: dict[str, tuple[str, str]] = {
    "--lowvram": ("", "weights stream instead of staying resident on the GPU"),
    "--disable-smart-memory": (
        "", "10.1c: without it the Qwen graph swap-deadlocks — it pays for that with system RAM"),
    "--cache-lru": (
        "10", "run e5ed4b3a: the default cache-classic evicts the checkpoint on every graph "
              "alternation (490s vs 14.8s per shot), and recompose adds a third graph to it"),
}


def _gb(value: object) -> float | None:
    """Bytes -> GiB, or ``None`` when the field is not a number.

    ``bool`` is excluded explicitly: it is an ``int`` in Python, and a boolean RAM reading
    is a payload we cannot read, not 0.0 GiB of free memory.

    GiB, and the messages say GiB: ``/system_stats`` and ``free`` both report powers of
    two, so an operator comparing our number against theirs must not be handed a unit we
    divided one way and printed another.
    """
    return value / 2**30 if isinstance(value, int | float) and not isinstance(value, bool) else None


def _message(headline: str, argv: list[str] | None = None, ram: str | None = None) -> str:
    """Compose the whole operator text: what is missing, then what *is* present.

    Same contract as ``comfyui_client.resolve_nodes``' error — an operator who reads this
    one log line must be able to restart ComfyUI correctly without opening a source file.

    HEADLINE FIRST, and self-contained: ``video_node`` files ``splitlines()[0]`` as the
    run_warning's ``detail``, which ``make_warning`` truncates at 200 chars. The whole
    text is ~370 with the argv repr in the middle, so anything but the first line would
    be cut out of the gate payload entirely.
    """
    flags = " ".join(f"{flag} {value}".strip() for flag, (value, _) in REQUIRED_FLAGS.items())
    return "\n".join(filter(None, [
        f"Shot recompose preflight failed: {headline}",
        f"  observed argv: {argv}" if argv is not None else "",
        f"  free RAM: {ram}" if ram else "",
        # ADD, never replace: this machine's ComfyUI starts from `~/workspaces/ComfyUI/run.sh`,
        # which activates the venv and exports HSA_OVERRIDE_GFX_VERSION / PYTORCH_HIP_ALLOC_CONF
        # before `python main.py --preview-method auto ...`. An operator who pastes a bare
        # `python main.py …` in its place loses the venv and the ROCm override with it.
        f"  add to ComfyUI's launcher (e.g. run.sh) and restart: {flags}",
        "Recompose is skipped for this run; every shot renders through the overlay path.",
    ]))


def _flag_value(flag: str, argv: list[str]) -> str | None:
    """What the running server passed for ``flag``, or ``None`` when it is absent.

    Both spellings argparse accepts: ``--cache-lru=10`` carries the value inline, plain
    ``--cache-lru`` takes the next argv entry (``""`` when the flag ends argv). An
    operator who wrote the working spelling must not be sent off to fix a non-problem.
    """
    for i, a in enumerate(argv):
        if a.startswith(f"{flag}="):
            return a.split("=", 1)[1]
        if a == flag:
            return argv[i + 1] if i + 1 < len(argv) else ""
    return None


async def _preflight(s: Settings) -> tuple[str, str] | None:
    """Check the RUNNING server against REQUIRED_FLAGS + the RAM floor, once per run.

    ``None`` when the path may proceed, else ``(reason, message)`` where ``reason`` is one
    of ``missing_flags`` / ``low_ram`` / ``stats_unavailable`` / ``stats_unreadable`` and
    ``message`` is headline-first (see ``_message``).

    The *server* is asked — never ``.env``, ``run.sh`` or our own ``Settings`` — because
    ComfyUI may be on another host and the only argv that decides the outcome is the one
    the live process was actually started with.

    ``stats`` is read defensively down to each key, the same posture as image_node's
    provenance block: ``/system_stats``' payload differs across ComfyUI versions, and an
    unexpected shape must produce a named bail, not a TypeError out of a best-effort path.
    """
    stats = await comfyui_client.get_system_stats(s.comfyui_url)
    # get_system_stats is best-effort by contract [AD-10] and answers None for every
    # failure mode. "Could not ask" is not "prerequisites met": the state this exists to
    # catch is indistinguishable from a healthy one without the answer, so an unanswered
    # probe bails rather than gambling ~12 minutes of swap-deadlock per shot.
    if stats is None:
        return "stats_unavailable", _message(
            f"ComfyUI at {s.comfyui_url} did not answer /system_stats, so its startup flags "
            "and free RAM are unknown."
        )

    system = stats.get("system")
    if not isinstance(system, dict):
        return "stats_unreadable", _message(
            f"/system_stats has no readable 'system' object (got {type(system).__name__}); "
            f"keys present: {sorted(stats)}."
        )
    argv = system.get("argv")
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return "stats_unreadable", _message(
            f"/system_stats 'system.argv' is not a list of strings (got {argv!r}); "
            f"keys present: {sorted(system)}."
        )
    # getattr for the same reason as video_node's `shot_recompose_enabled` check: test
    # Settings stubs are per-test SimpleNamespaces, and an AttributeError here escapes into
    # video_node's blanket except — which logs a WARNING and files NO run_warning, i.e.
    # exactly the silent skip this preflight exists to end.
    floor = getattr(s, "recompose_preflight_min_free_ram_gb", 12.0)
    free_gb, total_gb = _gb(system.get("ram_free")), _gb(system.get("ram_total"))
    ram = None if free_gb is None else (
        f"{free_gb:.1f} / {total_gb:.1f} GiB (threshold {floor:.1f})" if total_gb is not None
        else f"{free_gb:.1f} GiB free (threshold {floor:.1f})")

    # Flags BEFORE the RAM read: they are the actionable half. A box with flags absent and
    # an unreadable `ram_free` used to be told only "payload unreadable", which names the
    # one thing the operator cannot do anything about and hides the one thing they can.
    missing, inert = [], []
    for flag, (value, _) in REQUIRED_FLAGS.items():
        passed = _flag_value(flag, argv)
        if passed is None:
            missing.append(flag)
        elif value and not (passed.isdigit() and int(passed) > 0):
            # Present but inert — see REQUIRED_FLAGS' header. `--cache-lru 0` IS the
            # default, so reporting it as satisfied gives back the 490 s/shot state.
            inert.append(f"{flag} is present but set to {passed!r}, "
                         "which is the same as not passing it")
    if missing or inert:
        return "missing_flags", _message(" ".join(filter(None, [
            f"ComfyUI is missing {', '.join(missing)}." if missing else "",
            *(f"{note}." for note in inert),
        ])), argv=argv, ram=ram)

    if free_gb is None:
        return "stats_unreadable", _message(
            f"/system_stats 'system.ram_free' is not a number (got {system.get('ram_free')!r}); "
            f"keys present: {sorted(system)}.", argv=argv,
        )
    if free_gb < floor:
        return "low_ram", _message(
            f"free system RAM is below the recompose floor — {free_gb:.1f} GiB < {floor:.1f} GiB.",
            argv=argv, ram=ram)
    return None


async def recompose_run_shots(
    scenes: list, cast_cards: dict, settings: Settings | None = None,
) -> tuple[dict, dict]:
    """Recompose every cast-bearing shot. Returns ``(remaining_cast_cards, stats)``."""
    s = settings or Settings()
    workspace = Path(s.workspace_path)
    remaining = dict(cast_cards)
    stats = {"recomposed": 0, "skipped": 0, "failed": 0}

    # Story 10.1d — run-level refusal, distinct in kind from the per-shot skips below: a
    # misconfigured ComfyUI is wrong for every shot, so bail the whole run out to the
    # overlay with the cast map UNTOUCHED rather than degrade 43 shots one at a time while
    # the operator believes recompose ran. Not memoised on purpose: this runs once per
    # video_node invocation, and a process-level cache would outlive the operator's fix
    # and keep reporting the old failure on retry.
    failure = await _preflight(s)
    if failure:
        reason, message = failure
        logger.error("%s", message)
        # `remaining` is already the untouched copy — nothing below has run yet.
        return remaining, {**stats, "preflight_failed": reason, "preflight_detail": message}

    for scene in scenes:
        for shot in scene.get("shots") or []:
            shot_key = f"{scene['scene_num']}:{shot['shot_id']}"
            cast = [c for c in remaining.get(shot_key, []) if isinstance(c, dict) and c.get("path")]
            plate = shot.get("image_path")
            if not cast or not plate:
                continue
            if any(c.get("card_key") not in CARD_LOOKS for c in cast):
                # No description means no way to name the character in the instruction.
                # Leaving it to the overlay path is honest; guessing a description is not.
                logger.warning(
                    "Recompose skipped for %s: no appearance description for %s",
                    shot_key, [c.get("card_key") for c in cast if c.get("card_key") not in CARD_LOOKS],
                )
                stats["skipped"] += 1
                continue

            plate_path = Path(plate)
            if plate_path.parent.name == RECOMPOSED_DIR:
                # Re-entry: this shot's "plate" is a frame we already recomposed, so it
                # ALREADY contains the characters. Feeding it back in draws every figure a
                # second time (the duplicate-figure failure this story spent a round on),
                # and the run_dir derivation below would miss too. video is retryable and
                # the rewrite is in place, so this state is reachable — treat it as done.
                remaining.pop(shot_key, None)
                stats["skipped"] += 1
                continue
            try:
                plate_bytes = plate_path.read_bytes()
            except OSError as exc:
                logger.warning("Recompose skipped for %s: unreadable plate %s: %s", shot_key, plate, exc)
                stats["skipped"] += 1
                continue

            digest = recompose_digest(
                plate_bytes,
                [str(c["path"]) for c in cast],
                [f"{c.get('card_key')}|{c.get('position')}|{c.get('depth')}|{c.get('pose')}" for c in cast],
            )
            # Plates live at <run_dir>/images/<shot>.png, so the run dir is two up. Deriving
            # it from the plate keeps the output beside the run that owns it without
            # threading a run_id through a node that is a pure function of state.
            run_dir = plate_path.parent.parent if plate_path.parent.name == "images" else workspace
            out = recompose_cache_path(run_dir, shot["shot_id"], digest)

            if not out.exists():
                image = await recompose_shot(
                    plate_path, cast, CARD_LOOKS, comfyui_client,
                    s.shot_recompose_workflow_path, s.comfyui_url, shot_id=shot["shot_id"],
                )
                if not image:
                    stats["failed"] += 1
                    continue
                try:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    tmp = out.with_name(f"{out.name}.tmp")
                    tmp.write_bytes(image)
                    tmp.replace(out)
                except OSError as exc:
                    # Contained here on purpose. Shots are rewritten in place as the loop
                    # goes, so letting ENOSPC out would leave the run half-recomposed: the
                    # caller's blanket except keeps the ORIGINAL cast_cards, and the shots
                    # already swapped would get their characters composited on top of a
                    # frame that has them. One failed shot, not a torn run.
                    logger.warning("Recompose write failed for %s: %s", shot_key, exc)
                    stats["failed"] += 1
                    continue

            shot["image_path"] = str(out)
            # The depth map describes the *empty plate*, not the characters the model just
            # drew into the frame, so warping the new image with it would slide the figures
            # against their own background. Dropping the key makes 11.5 report NO_DEPTH
            # ("no_depth_map") — a recorded degradation rather than a silent wrong warp.
            shot.pop("depth_map_path", None)
            remaining.pop(shot_key, None)   # nothing to overlay: the frame already has them
            stats["recomposed"] += 1

    logger.info("Shot recompose: %s", stats)
    return remaining, stats
