"""Run-level orchestration for Story 10.1c shot recompose.

The domain half lives in `pipeline/nodes/shot_recompose.py` (prompt construction, pass
ordering, workflow assembly). This half is what that module deliberately cannot reach: the
ComfyUI client, the workspace, and the character descriptions the instruction needs.

Contract with `video_node` (see `inject_recompose_resolver`): rewrite each recomposed shot's
``image_path`` in place and drop that shot from the returned cast map, so the composition
stage takes its background-only path and nothing is overlaid on a frame that already has
the characters in it.
"""

import hashlib
import json
import logging
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from yt_flow.config import Settings
from yt_flow.pipeline.nodes.shot_recompose import (
    RECOMPOSED_DIR,
    order_cast,
    placement_instruction,
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
# The third prerequisite is not a flag: free system RAM >= `recompose_preflight_min_free_ram_gb`.
#
# REMOVED 2026-08-17 by Story 10.1e, on measurement: `--disable-smart-memory`. It was here
# on 10.1c's report that "without it the Qwen graph swap-deadlocks", observed on an older
# ComfyUI and never re-tested — `gotcha_qwen-image-edit-rejection-was-version-specific` is
# about exactly this class of inherited claim. On ComfyUI 0.12.3 the deadlock does not
# reproduce over the 40 passes of the 2026-08-17 sweep, and requiring the flag was
# ACTIVELY FATAL on this box:
# the graph's weights total 22.6 GB (12.6 unet + 8.95 fp8 encoder + 0.81 LoRA + 0.24 VAE)
# against 16 GB VRAM, so `--lowvram` streams them from system RAM and
# `--disable-smart-memory` then unloads them after every prompt — 22.6 GB re-read per
# pass on a 31 GB box. Measured, same hardware, same shots:
#     with the flag     385.66 -> 677 -> 609 s/pass, ram_free 19.35 -> 5.46 GiB, swap 8185/8191 MiB
#     without the flag  107.9 s/pass over 40 passes, ram_free flat ~17-13 GiB, 0 failures
#                       (the with-flag column is CONFOUNDED: a concurrent session ran four
#                        SDXL prompts between pass 1 and passes 2-3 — see
#                        `10-1e-live-validation/render_on_blocked.json`)
# i.e. the flag this table required is what breached this table's own RAM floor. The
# preflight was refusing the only configuration that works. Keep watching for the original
# deadlock: if it ever returns, it belongs here WITH the version it was seen on.
#
# DELIBERATELY NOT CHECKED: the fp8 text encoder. `qwen_2.5_vl_7b_fp8_scaled.safetensors`
# is pinned in the workflow JSON's `clip` node — a property of the graph file, absent from
# argv and from /system_stats — and a missing file fails fast at that node with ComfyUI's
# own error naming the file. Synthesising a worse version of that message here would need a
# second HTTP endpoint (`/object_info`) for no added information.
REQUIRED_FLAGS: dict[str, tuple[str, str]] = {
    "--lowvram": ("", "the graph's 22.6 GB of weights do not fit 16 GB VRAM; they stream"),
    "--cache-lru": (
        "10", "run e5ed4b3a: the default cache-classic evicts the checkpoint on every graph "
              "alternation (490s vs 14.8s per shot), and recompose adds a third graph to it"),
}


# The mirror of REQUIRED_FLAGS: a flag whose PRESENCE is disqualifying. Removing
# `--disable-smart-memory` from the required table is not enough — a launcher that still
# passes it (this box's run.sh did until 2026-08-17, and another host may) now sails through
# a preflight that has nothing to say about it, into the state 10.1e measured at 385-677
# s/pass against 108 without it. Refusing loudly is the same contract as a missing flag.
FORBIDDEN_FLAGS: dict[str, str] = {
    "--disable-smart-memory": (
        "10.1e: with --lowvram already streaming the graph's 22.6 GB from system RAM, this "
        "unloads it after every prompt — 385-677 s/pass vs 108, and it drove free RAM below "
        "this preflight's own floor mid-run"),
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
    of ``forbidden_flags`` / ``missing_flags`` / ``low_ram`` / ``stats_unavailable`` /
    ``stats_unreadable`` and
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

    # A disqualifying flag is checked FIRST: it is the one failure whose symptom is slowness
    # rather than an error, so nothing downstream would ever surface it. See FORBIDDEN_FLAGS.
    banned = [f"{flag} ({why})" for flag, why in FORBIDDEN_FLAGS.items()
              if _flag_value(flag, argv) is not None]
    if banned:
        return "forbidden_flags", _message(
            "ComfyUI was started with a flag this path must not run under: "
            + "; ".join(banned) + ". Remove it from the launcher and restart.",
            argv=argv, ram=ram)

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


# ── Story 14.3: attribution ───────────────────────────────────────────────────
# Until this story a recomposed frame's only trace on disk was the 16-hex digest in its
# filename, and that digest is not invertible: it hashes the plate bytes, the card paths
# and the placement FIELDS together, so nothing on disk says WHICH workflow or WHICH
# instruction text drew the frame. That is fatal for the next GPU session, whose whole job
# is a before/after pair — a pair you cannot attribute is not evidence. The block below is
# appended to the sidecar image_node already writes, next to `provenance`, and is
# ADDITIVE AND UNCOMPARED: `_existing_complete_shot` compares exactly three keys
# (image_prompt, negative_prompt, seed) and adding a fourth would invalidate every
# checkpoint in the workspace.


def _workflow_sha256(path: str) -> str | None:
    """sha256 of the recompose graph as shipped, or ``None`` if it cannot be read.

    Logged on the way out, the way `image._env_snapshot_sha256` logs: ``None`` is ALSO
    the deliberate value on a cache hit ("this pass did not draw the frame"), so on disk
    an unreadable graph and a correctly-unattributed cache hit are the same four
    characters. This log line is the only thing that tells them apart, and without it
    every frame of a run would record a null pin with nothing anywhere saying why.
    """
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        logger.warning(
            "Recompose workflow unreadable at %s — every frame this run renders records "
            "workflow_sha256=null, indistinguishable from a cache hit: %s", path, exc,
        )
        return None


def _instruction_sha256(cast: list[dict]) -> str | None:
    """sha256 over the placement instructions of this pass, joined in pass order.

    `workflow_sha256` covers the graph JSON and `digest` covers the plate bytes, the card
    paths and the placement *fields* — none of them covers the Python that turns
    ``depth="near"`` into a sentence. `placement_instruction`, `_DEPTH_PHRASE`,
    `_POSITION_PHRASE` and `CARD_LOOKS` are source, and the next fix queued in this area
    edits `_DEPTH_PHRASE["near"]`: without this hash every block written before and after
    that edit would say ``depth: "near"`` and reconstruct to *different* text, which is
    the misattribution the whole block exists to prevent.

    Reconstructed here rather than returned from `recompose_shot`: the arguments are the
    same closed vocabularies the render path reads (`CARD_LOOKS` membership is already a
    precondition of getting this far), the function is pure, and threading a string back
    out of a ComfyUI submission loop for a hash would be the wider change. Not invertible
    — it identifies a wording, and the wording is read off the source at that commit.
    """
    try:
        return hashlib.sha256("\n".join(
            placement_instruction(
                CARD_LOOKS[c["card_key"]], c.get("position", "center"),
                c.get("depth", "mid"), c.get("pose"),
            )
            for c in order_cast(cast)
        ).encode("utf-8")).hexdigest()
    except (KeyError, TypeError, ValueError) as exc:  # a hand-edited cast entry
        logger.warning("Recompose instruction hash unavailable: %s", exc)
        return None


def _digest_from_name(frame: Path) -> str | None:
    """The digest half of ``<shot_id>_<digest>.png``, or ``None`` if there is no separator.

    Guarded rather than ``rsplit("_", 1)[-1]``, which returns the WHOLE stem when the name
    has no ``_`` (a hand-placed frame, a rename) and so records a filename fragment in a
    field every reader treats as a content digest — a value that compares unequal to the
    real digest without ever admitting it is not one.
    """
    stem = frame.stem
    return stem.rsplit("_", 1)[1] if "_" in stem else None


def _sidecar_for(run_dir: Path, shot_id: str) -> Path | None:
    """image_node's completion sentinel for this shot, or ``None`` if there is none.

    Globbed rather than rebuilt from ``scene_{n:03d}_{shot_id}``: that format belongs to
    `image._shot_base`, and re-encoding it here would be a second place the naming is
    decided. Absent is NOT an error — a plate with no sentinel was not written by
    image_node (mock fixtures, hand-placed plates), so there is no record to annotate and
    inventing a partial one would put a sidecar with no `image_prompt` in front of the
    resume check. ponytail: no synthesis, no warning; the run that owns the shot stamps it.
    """
    return next(iter(sorted((run_dir / "images").glob(f"*_{shot_id}_done.json"))), None)


def _recompose_block(
    *, source: str, workflow_path: str, workflow_sha256: str | None,
    instruction_sha256: str | None, digest: str | None, out: Path, cast: list[dict],
) -> dict:
    """What drew this frame, in pass order.

    ``source`` is ``"rendered"`` when this pass actually submitted the graph and
    ``"cache"`` when the frame was already on disk. On ``"cache"`` the workflow and
    instruction shas are ``None`` ON PURPOSE: the cache key does not cover either, so
    stamping today's values onto a frame drawn by an older graph would attribute the frame
    to a workflow that never rendered it — a lie that is worse than the silence this story
    removes.

    ``recomposed_at`` obeys the same rule, which it did not at first: it is when the frame
    was DRAWN. On a cache fill the pixels are as old as the PNG (days, in the resume case
    this story is about), so the value is the file's mtime, and ``None`` when even that
    cannot be read — never today's clock, which is the identical misattribution one field
    across.
    """
    if source == "cache":
        try:
            drawn_at: str | None = datetime.fromtimestamp(
                out.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        except OSError as exc:
            logger.warning("Recomposed frame %s has no readable mtime: %s", out, exc)
            drawn_at = None
    else:
        drawn_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "recomposed_at": drawn_at,
        "source": source,
        "workflow_path": workflow_path,
        "workflow_sha256": workflow_sha256,
        "instruction_sha256": instruction_sha256,
        "digest": digest,
        "output_path": str(out),
        "passes": [
            {
                "card_key": c.get("card_key"),
                "card_path": str(c.get("path")),
                "position": c.get("position"),
                "depth": c.get("depth"),
                "pose": c.get("pose"),
            }
            for c in order_cast(cast)
        ],
    }


def _stamp_sidecar(sidecar: Path, block: dict, *, overwrite: bool) -> str | None:
    """Merge ``block`` into the sidecar. Returns an error detail, or ``None`` on success.

    Atomic (tmp + ``replace``): this file carries `image_prompt` and `seed`, so a torn
    write makes `_existing_complete_shot` miss and re-renders the shot on the next resume
    — spending a GPU pass to record that a GPU pass happened.

    ``overwrite=False`` (a cache hit) keeps an existing block untouched, so the original
    `workflow_sha256`/`recomposed_at` survive; it still WRITES when the key is absent or
    null, which is what makes a previously failed stamp recoverable instead of permanently
    silent. ``TypeError``/``ValueError`` are caught alongside ``OSError`` because the
    sidecar is JSON someone may have edited: a list where a dict belongs raises the former
    two, and attribution must never fail the run. [AD-10]
    """
    tmp = sidecar.with_name(f"{sidecar.name}.tmp")
    try:
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            return f"sidecar is {type(record).__name__}, not an object"
        if not overwrite and isinstance(record.get("recompose"), dict):
            return None
        record["recompose"] = block
        tmp.write_text(json.dumps(record), encoding="utf-8")
        tmp.replace(sidecar)
        return None
    except (OSError, TypeError, ValueError) as exc:
        # The tmp file is this function's own litter: `write_text` may have landed and
        # `replace` failed (ENOSPC, a read-only mount), and every failed stamp would
        # otherwise leave a stale `<name>.tmp` next to the sidecar — files an operator
        # finds and cannot tell from a torn write in progress. `suppress`, because the
        # cleanup must not replace the error it is cleaning up after.
        with suppress(OSError):
            tmp.unlink(missing_ok=True)
        return f"{type(exc).__name__}: {exc}"


async def recompose_run_shots(
    scenes: list, cast_cards: dict, settings: Settings | None = None,
) -> tuple[dict, dict]:
    """Recompose every cast-bearing shot. Returns ``(remaining_cast_cards, stats)``."""
    s = settings or Settings()
    workspace = Path(s.workspace_path)
    remaining = dict(cast_cards)
    # Annotated: the counts are ints but Story 14.3 adds a `warnings` list to the same
    # payload, and an inferred dict[str, int] rejects it.
    #
    # `skipped` and `reentered` are separate counters, and the split is a review fix, not
    # a nicety. Both used to increment `skipped`, whose every reader — the degraded
    # warning's copy ("rendered on the overlay"), the run trace's `recompose_skipped` —
    # takes it to mean "NOT recomposed". Re-entry means the opposite: the shot was already
    # recomposed on an earlier attempt of a retryable stage. A retried video stage over 33
    # recomposed shots traced `recomposed=0, recompose_skipped=33` and warned that 33 shots
    # had used the overlay, when all 33 were recomposed frames. `attributed` counts the
    # stamps that landed, so `recomposed` can be read as a coverage figure instead of an
    # assumption (a shot with no sidecar is silently un-stampable — see `_sidecar_for`).
    stats: dict = {"recomposed": 0, "skipped": 0, "reentered": 0, "failed": 0, "attributed": 0}

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

    # Read once per run, not per shot: the graph cannot change mid-loop, and a shipped
    # 5-node JSON hashed 43 times is 43 reads for one answer.
    workflow_sha = _workflow_sha256(s.shot_recompose_workflow_path)
    sidecar_failures: list[dict] = []

    def stamp(
        run_dir: Path, scene_num: object, shot_id: str, *, source: str,
        workflow_sha256: str | None, digest: str | None, out: Path, cast: list[dict],
        overwrite: bool, shot_key: str,
    ) -> None:
        """Record the attribution, or record that it could not be recorded.

        Both halves matter. The warning is raised on EVERY pass that finds the block
        missing — including the cached and re-entry passes below — because a stamp that
        failed once and then went quiet is exactly the permanent un-attribution this
        story exists to end (13.3 shipped the same shape and had to come back for it).

        The lookup and the block are built INSIDE the try, which is why they moved in
        here from the call sites. `_sidecar_for` globs the filesystem and `_recompose_block`
        walks caller-supplied dicts, so either can raise on ONE shot — and an escape here
        aborts the sweep mid-run, leaving the shots already swapped in place while the
        caller's blanket except restores the ORIGINAL cast map and composites every figure
        a second time onto a frame that has them. One shot's lost attribution may not cost
        the run its remaining shots.

        `scene_num` and `shot_id` are carried separately, not as the joined `shot_key`:
        the sibling warnings in `video_node` pass them as two fields, and a row whose
        `shot_id` is `"3:S00301"` never joins against them.
        """
        try:
            sidecar = _sidecar_for(run_dir, shot_id)
            if sidecar is None:
                return
            detail = _stamp_sidecar(sidecar, _recompose_block(
                source=source, workflow_path=s.shot_recompose_workflow_path,
                workflow_sha256=workflow_sha256,
                # Same rule as the workflow sha: a cached frame's instruction text is
                # whatever drew it, not whatever this checkout would render today.
                instruction_sha256=_instruction_sha256(cast) if source == "rendered" else None,
                digest=digest, out=out, cast=cast,
            ), overwrite=overwrite)
        except Exception as exc:  # noqa: BLE001 — AD-10: attribution never fails the run
            detail = f"{type(exc).__name__}: {exc}"
        if detail:
            logger.warning("Recompose sidecar write failed for %s: %s", shot_key, detail)
            sidecar_failures.append(
                {"scene_num": scene_num, "shot_id": shot_id, "detail": detail})
        else:
            stats["attributed"] += 1

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
                # Story 14.3: this shot still owes an attribution — before, a sidecar
                # whose first stamp failed passed through this `continue` and lost even
                # its warning. It counts as `reentered`, NOT `skipped`: it IS recomposed,
                # and every reader of `skipped` (the degraded warning's copy, the run
                # trace) means "not recomposed" by it.
                stamp(
                    plate_path.parent.parent, scene["scene_num"], shot["shot_id"],
                    source="cache", workflow_sha256=None,
                    digest=_digest_from_name(plate_path), out=plate_path, cast=cast,
                    overwrite=False, shot_key=shot_key,
                )
                remaining.pop(shot_key, None)
                stats["reentered"] += 1
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

            rendered = not out.exists()
            if rendered:
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
            stamp(
                run_dir, scene["scene_num"], shot["shot_id"],
                source="rendered" if rendered else "cache",
                workflow_sha256=workflow_sha if rendered else None,
                digest=digest, out=out, cast=cast,
                # A cache hit did not draw this frame, so it may not overwrite the record
                # of the pass that did — but it must still fill an absent one in.
                overwrite=rendered, shot_key=shot_key,
            )
            # The depth map describes the *empty plate*, not the characters the model just
            # drew into the frame, so warping the new image with it would slide the figures
            # against their own background. Dropping the key makes 11.5 report NO_DEPTH
            # ("no_depth_map") — a recorded degradation rather than a silent wrong warp.
            shot.pop("depth_map_path", None)
            remaining.pop(shot_key, None)   # nothing to overlay: the frame already has them
            stats["recomposed"] += 1

    if sidecar_failures:
        # Added BEFORE the log line on purpose: `stats` is what the log prints and what
        # video_node turns into warnings, and a log that omitted the failures would be
        # evidence against a payload that carries them.
        stats["warnings"] = sidecar_failures
    logger.info("Shot recompose: %s", stats)
    return remaining, stats
