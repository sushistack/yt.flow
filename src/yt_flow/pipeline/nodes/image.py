"""image_node — the ComfyUI image-generation stage (Story 1.6).

Consumes ``SceneState.shots`` from ``scenario_node`` and, per shot, submits the
configured ComfyUI workflow with the shot's prompts injected into the nodes whose
``_meta.title`` is ``ytflow:positive_prompt`` / ``ytflow:negative_prompt``
(Story 13.3 — resolved once at load, never addressed by node id: the ComfyUI UI
renumbers nodes on re-export, and the old hardcoded ``"6"``/``"7"`` would then
write a prompt into an unrelated node), writing each output under
``workspace/{run_id}/images/``. Pure function of state: reads a few fields and
returns only the changed ones (``scenes``, ``current_stage``, and ``error`` on
failure). No DB / SSE writes and no ``interrupt()`` — gate behaviour stays in
``gates.py``. [AD-1, AD-4]

The image-generation unit is a *shot*, not a scene: every shot gets its own
image. [AD-5]

Background-only (Story 8.3): image_node generates entity-free backgrounds
only — segmentation/inpaint and the layered-asset path were retired outright.
Per-shot character overlays are compositor concerns now: ``video_node``
resolves and composites transparent character cards from ``ShotData.cast``
(Story 8.1/8.2/8.3). ``BG_NEGATIVE_SUFFIX`` is the code-side belt to the
prompt-side (8.1) suspenders keeping entities out of the generated image.

Story 10.2 adds the only enforcement that looks at pixels: each generated
background is shown to Qwen-VL and, if it already contains a person, re-rendered
on the next rung of a fixed-length seed ladder. Bounded, fail-open, and never
able to fail the stage — an undecidable verdict accepts the frame and is counted.

Story 14.2 asks a SECOND pixel question, once, about the render that ladder
already accepted: can a whole body stand in this plate? A `false` verdict does not
re-render — it empties that shot's ``cast``, so the compositor never puts a card on
a frame with nowhere to put it (7/33 of run 4b35c0ed's cast-bearing shots). It sits
OUTSIDE the ladder on purpose: the terminal action is not regeneration, so one
verdict per shot is enough and rung accounting stays a single predicate's business.

Mock mode (``YTFLOW_COMFYUI_MOCK=true``) never instantiates the HTTP client: a
fixture image from ``tests/fixtures/images/`` is materialized into the run
workspace so downstream code sees an identical artifact layout in mock and real
runs.
"""

import asyncio
import copy
import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
import typing
from typing import Any

from yt_flow.observability import get_client, observe

from yt_flow.config import (
    BACKGROUND_PERSON_GUARD_BREAKER_STREAK,
    BACKGROUND_PERSON_GUARD_BREAKER_TOTAL,
    BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS,
    Settings,
)
from yt_flow.domain.state import PipelineState, RunWarning, SceneState, ShotData
from yt_flow.domain.warnings import cap_samples, make_warning, merge as merge_warnings
from yt_flow.pipeline.nodes.scenario_chain import _CAMERA_ANGLES
from yt_flow.services import comfyui_client, vision_check
from yt_flow.services.comfyui_client import ComfyUIError

logger = logging.getLogger(__name__)

# Story 13.3: manifest keys, resolved to node ids by exact ``_meta.title`` match.
# There is deliberately no id fallback — a silent re-target is the failure being
# removed, so an unresolvable title fails the stage at load.
POSITIVE_KEY = "ytflow:positive_prompt"
NEGATIVE_KEY = "ytflow:negative_prompt"

# The ComfyUI-Manager snapshot pinned into every render's provenance (Story 13.3
# AC6/AC7). Repo-relative, resolved against ``YTFLOW_PROJECT_ROOT`` at read time
# the same way ``character_image_provider._load_workflow`` resolves workflow
# paths — that helper exists precisely because the app does not always run from
# the repo root, and a pin that quietly stops pinning is the failure this story
# removes. ponytail: a module constant, not a config field; it does not vary per
# deployment and there is no restore automation.
ENV_SNAPSHOT_PATH = "data/comfyui/env-snapshot.json"

# ── Location plate resolution injection (Story 8.5) ────────────────────────
# Injected by the service layer to avoid AD-1 violation (LocationService needs
# a DB session). Same pattern as video.py's inject_cast_resolver.
_location_service: Any = None


def inject_location_service(fn: Any) -> None:
    """Inject the approved-plate lookup callable.

    ``fn`` signature: ``async fn(location_key: str) -> list[dict]`` returning
    approved plates for the key ordered by variant, each
    ``{"variant": str, "path": <absolute file path>}``. Empty list = no
    approved plate — image_node falls back to generation.
    """
    global _location_service
    _location_service = fn


# ── Depth companion resolution injection (Story 11.5) ──────────────────────
# Same seam and same reason as the location service above: the depth estimator
# is a service (it drives ComfyUI and owns the shared content-addressed cache
# Story 8.16 created), so pipeline/ receives it as a callable [AD-1].
_depth_resolver: Any = None


def inject_depth_resolver(fn: Any) -> None:
    """Inject the image→depth-companion resolver.

    ``fn`` signature: ``async fn(image_path: str) -> dict`` returning
    ``{"path": <depth map path> | None, "cached": bool}``. ``path=None`` means no
    depth is available for that image (mock mode, ComfyUI down, a refused
    non-commercial checkpoint) — the shot then carries no ``depth_map_path`` and
    the video stage's renderer ladder degrades visibly (Story 11.5 AC9).
    """
    global _depth_resolver
    _depth_resolver = fn

# Story 5.14: integrity floor for resume — matches the E2E baseline's deterministic
# image-gate check ("0-byte/placeholder ≤1KB"). ponytail: module constant, no config.
MIN_VALID_IMAGE_BYTES = 1024

# Story 8.3 AC2: code-side entity exclusion — belt to the prompt-side (8.1)
# suspenders. Values proven in the retired layered workflow's inpaint negative.
BG_NEGATIVE_SUFFIX = ", person, people, human, character, creature, figure, silhouette"

# ponytail: mock fixtures live in the test tree per the story contract; a module
# constant keeps the node dependency-free and lets tests monkeypatch the source.
MOCK_FIXTURES_DIR = Path("tests/fixtures/images")


def _settings() -> Settings:
    # ponytail: one seam so unit tests can inject fake settings without a real .env.
    return Settings()


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _load_workflow(path: str) -> tuple[dict, dict[str, str]]:
    """Load the API-format workflow and resolve its prompt nodes by declared title.

    Returns ``(workflow, nodes)`` where ``nodes`` maps manifest key -> node id.
    Resolution is eager because ComfyUI validation belongs at ``image_node``
    entry [AD-10]: a workflow whose titles no longer resolve must fail before the
    first shot, not silently paint a prompt onto the wrong node.

    The class-type check survives the switch to titles — it just runs on the
    *resolved* nodes now, so a ``ytflow:positive_prompt`` title pasted onto a
    ``LoraLoader`` in the UI still fails loudly.
    """
    try:
        workflow = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError subclass
        raise ValueError(f"cannot load ComfyUI workflow at {path!r}: {exc}") from exc
    if not isinstance(workflow, dict):
        raise ValueError(f"ComfyUI workflow at {path!r} is not an API-format object")
    nodes = comfyui_client.resolve_nodes(workflow, (POSITIVE_KEY, NEGATIVE_KEY))
    for key, node_id in nodes.items():
        node = workflow[node_id]
        if node.get("class_type") != "CLIPTextEncode" or not isinstance(node.get("inputs"), dict):
            raise ValueError(
                f"workflow node {node_id!r} ({key}) must be a CLIPTextEncode with an 'inputs' dict"
            )
    return workflow, nodes


def _effective_negative_prompt(negative_prompt: str) -> str:
    """Negative prompt actually submitted to ComfyUI and pinned in resume sidecars."""
    return negative_prompt + BG_NEGATIVE_SUFFIX


def _shot_seed(run_id: str, scene_num: int, shot_id: str, attempt: int = 0) -> int:
    """Deterministic per-shot KSampler seed (Story 11.1 AC1).

    Uses sha256, not the builtin ``hash()`` — CPython salts str hashing per
    process (PYTHONHASHSEED), so ``hash()`` would compute a different seed for
    the same shot after a process restart (e.g. a resumed run), breaking the
    sidecar seed comparison. Same rationale as ``_plate_variant_index``.

    ``attempt`` is Story 10.2's regeneration rung. Attempt 0 hashes the pre-10.2
    string byte-identically, so every workspace written before this story keeps
    resuming; only bumped rungs get the suffix.
    """
    key = f"{run_id}:{scene_num}:{shot_id}" if attempt == 0 else f"{run_id}:{scene_num}:{shot_id}:{attempt}"
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % 2**32


def _seed_ladder(run_id: str, scene_num: int, shot_id: str) -> list[int]:
    """Every seed this shot could legitimately have been accepted on (Story 10.2).

    Fixed length — ``BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS`` rungs — deliberately
    NOT derived from the run's current ``background_person_guard_attempts``. The
    resume check compares against the whole ladder, so lowering the knob (or
    losing the vision key) can never invalidate a shot that a previous run
    accepted on a bumped seed and send it regenerating forever.
    """
    return [_shot_seed(run_id, scene_num, shot_id, a) for a in range(BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS + 1)]


def _inject_prompts(
    template: dict, nodes: dict[str, str], image_prompt: str, negative_prompt: str, seed: int,
) -> dict:
    """Return a deep copy of the workflow with prompts injected into the nodes
    ``_load_workflow`` resolved, and ``seed`` into every KSampler node
    (class_type match, Story 11.1 AC1).

    Titles resolve *interchange* nodes (which prompt is which); class_type drives
    *uniform* writes (every sampler gets the seed). That split is deliberate —
    don't convert the KSampler loop to titles.

    Pure: never mutates ``template`` so one loaded workflow can be reused per shot.
    Appends ``BG_NEGATIVE_SUFFIX`` to the negative prompt (AC2) unconditionally —
    background-only is the only path left, so every generation gets it.
    """
    workflow = copy.deepcopy(template)
    workflow[nodes[POSITIVE_KEY]]["inputs"]["text"] = image_prompt
    workflow[nodes[NEGATIVE_KEY]]["inputs"]["text"] = _effective_negative_prompt(negative_prompt)
    for node in workflow.values():
        if isinstance(node, dict) and node.get("class_type") == "KSampler":
            node["inputs"]["seed"] = seed
    return workflow


def _mock_source() -> Path:
    """First fixture image to stand in for a real ComfyUI render."""
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        matches = sorted(MOCK_FIXTURES_DIR.glob(pattern))
        if matches:
            return matches[0]
    raise ValueError(f"no fixture images under {MOCK_FIXTURES_DIR} for mock mode")


def _shot_base(scene_num: int, shot: ShotData) -> str:
    return f"scene_{scene_num:03d}_{shot['shot_id']}"


def _sidecar_path(out_dir: Path, scene_num: int, shot: ShotData) -> Path:
    return out_dir / f"{_shot_base(scene_num, shot)}_done.json"


def _card_keys(shot: ShotData) -> str:
    """The shot's cast as a comma-joined key list, for Story 14.2's warning context.

    ``len(cast)`` says a card was dropped; it does not say WHICH character left the
    frame, which is the only part an operator can act on. A joined string rather than a
    list: ``make_warning`` stringifies non-scalars anyway, and the value is part of the
    row identity, so a stable rendering is what lets a resumed pass converge on the row
    already in the checkpoint.
    """
    return ",".join(str(member.get("card_key")) for member in (shot.get("cast") or []))


def _env_snapshot_sha256() -> str | None:
    """sha256 of the committed ComfyUI-Manager snapshot, ``None`` if absent. [AD-10]

    Non-fatal, but never silent: an unreadable snapshot means every render this
    run records an unpinned environment, which is the exact blind spot AC6 exists
    to close — so the miss is logged with the path it actually tried.
    """
    path = Path(os.environ.get("YTFLOW_PROJECT_ROOT", os.getcwd())) / ENV_SNAPSHOT_PATH
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        logger.warning(
            "ComfyUI env snapshot unreadable at %s, recording null provenance pin: %s", path, exc,
        )
        return None


def _build_provenance(
    workflow_path: str, template: dict | None, nodes: dict[str, str] | None, stats: dict | None,
    env_snapshot_sha256: str | None,
) -> dict:
    """What produced this run's renders (Story 13.3 AC7) — computed once per run.

    ``workflow_sha256`` hashes the loaded **template**, before per-shot
    injection: a hash of the submitted graph would differ for every shot and be
    useless for comparing two runs.

    Nulls are the honest answer on the paths that never load a workflow or touch
    ComfyUI (mock mode, stock plates, an unreachable ``/system_stats``). Pure and
    non-raising: provenance is observability and must never fail the stage.

    ``env_snapshot_sha256`` is passed in rather than read here: this is called
    twice per run (generation + stock-plate objects) and reading the file twice
    logged the same "snapshot unreadable" WARNING twice, which teaches the reader
    to ignore it.

    ``stats`` is read defensively down to each key. ``/system_stats``' payload
    differs across ComfyUI versions — which is the reason to record it at all —
    so an unexpected shape must produce nulls, not an AttributeError that kills
    the image stage [AD-10].
    """
    stats_map = stats if isinstance(stats, dict) else {}
    system = stats_map.get("system")
    system = system if isinstance(system, dict) else {}
    devices = stats_map.get("devices")
    devices = devices if isinstance(devices, list) else []
    device = devices[0] if devices and isinstance(devices[0], dict) else {}
    return {
        "workflow_path": workflow_path if template is not None else None,
        "workflow_sha256": hashlib.sha256(
            json.dumps(template, sort_keys=True).encode("utf-8")
        ).hexdigest() if template is not None else None,
        "nodes": nodes,
        "env_snapshot_sha256": env_snapshot_sha256,
        # Which stock plate was copied, filled in by the plate branch only — the
        # key exists (as null) on every path so "generated/mock" and "plate" are
        # positively distinguishable rather than told apart by an absent key.
        "stock_plate": None,
        # Whatever the server returned, read defensively — the key set differs
        # across ComfyUI versions, which is the reason to record it at all.
        # ``is not None``, not truthiness: a server answering ``{}`` is reachable,
        # and recording null for it makes it indistinguishable from unreachable —
        # the same defensive posture as ``stats_map`` three lines above.
        "comfyui": {
            "comfyui_version": system.get("comfyui_version"),
            "pytorch_version": system.get("pytorch_version"),
            "device": device.get("name"),
        } if stats is not None else None,
    }


def _write_sidecar(
    out_dir: Path, scene_num: int, shot: ShotData, seed: int, provenance: dict,
    guard_exhausted: bool = False, guard_undecidable: bool = False,
    affordance_unusable: bool = False, affordance_undecidable: bool = False,
) -> None:
    """Completion sentinel, written last after the shot's image file.

    Records the prompts + deterministic seed so a later retry can tell a stale
    (post-prompt-edit or pre-11.1) output from a genuinely complete one. The
    seed is a pure function of (run_id, scene_num, shot_id), so all three
    writer paths (stock plate / mock / generation) record the identical value —
    the resume check runs before path selection and must compare uniformly.
    [AC1, AC2] [Story 11.1 AC2]

    ``guard_exhausted`` (Story 10.2) marks a frame the guard KNOWS is populated
    and kept anyway. It is deliberately NOT part of the resume equality check:
    sidecars written before this key existed must keep matching.

    ``guard_undecidable`` (Story 14.4) is the same idea for the opposite outcome —
    a frame the detector could not judge, i.e. one that was never screened. It has
    to be on disk rather than only in ``run_warnings`` because those live in the
    LangGraph checkpoint, and a crash inside ``image_node`` (or a resume after its
    error path) comes back with the images on disk and the accounting gone: without
    this key the second pass skips every shot and the frame comes back looking
    verified-clean, which is the exact defect this story exists to remove. Additive
    and uncompared, for the reasons above.

    ``affordance_unusable`` (Story 14.2) is the third of the same shape: this shot's
    ``cast`` was emptied because the plate has no standing room. It has to be on disk
    because the resume path returns before any verdict is asked for, and without it the
    card comes back on the next pass — the frame is cached, the emptied cast is not.
    Additive and uncompared, like the two above.

    ``affordance_undecidable`` (Story 14.2) is its counterpart, and exists for the same
    reason ``guard_undecidable`` does: a cast-bearing shot that shipped WITHOUT a verdict
    — refused by the endpoint, breaker tripped, no API key, mock fixture, stock plate —
    must not resume looking like a plate the gate approved. A clean affordance tally on a
    frame nobody judged is the defect Story 13.1 exists to remove. Written on every path
    (a cast-free shot is a legitimate `False`: there was nothing to judge). Additive and
    uncompared.

    ``provenance`` (Story 13.3) is additive for exactly the same reason, and more
    sharply: it changes whenever ComfyUI is upgraded or the env snapshot is
    refreshed, so putting it anywhere near ``_existing_complete_shot``'s three
    compared keys would re-render every cached background on the next upgrade.
    It is **required**, not defaulted: 11.1's lesson (``seed``) is that a writer
    path which silently omits a sidecar field is only discovered in a live run,
    and each of the three paths owes a *different, honest* provenance object.

    ``recompose`` (Story 14.3) is a KEY LITERAL, not a parameter. image_node never
    recomposes, so there is no argument to take and no caller to take it from
    (ponytail: no scaffolding for a writer that does not exist). ``recompose_service``
    fills it in later, in place.

    The explicit ``null`` (rather than an omitted key) is for a READER OF THE FILE, and
    the distinction is not one any code makes: ``recompose_service._stamp_sidecar``
    treats absent and null identically (``isinstance(record.get("recompose"), dict)``),
    and there is no other reader. What it buys is forensic — a sidecar with the key at
    null was written by a 14.3-or-later run that did not recompose this shot, one
    without the key predates the story, and that is the difference between "the
    attribution was never owed" and "the attribution may have been lost". Claiming the
    service depends on it would be inventing a consumer, which is what the key itself
    is careful not to do. Additive and uncompared, like every key above.
    """
    _sidecar_path(out_dir, scene_num, shot).write_text(
        json.dumps({
            "image_prompt": shot["image_prompt"],
            "negative_prompt": _effective_negative_prompt(shot["negative_prompt"]),
            "seed": seed,
            "guard_exhausted": guard_exhausted,
            "guard_undecidable": guard_undecidable,
            "affordance_unusable": affordance_unusable,
            "affordance_undecidable": affordance_undecidable,
            "provenance": provenance,
            "recompose": None,
        }),
        encoding="utf-8",
    )


def _sidecar_guard_flag(out_dir: Path, scene_num: int, shot: ShotData, key: str) -> bool:
    """Did a previous run leave this shot unverified, and how?

    ``guard_exhausted`` = kept a background it KNEW was populated;
    ``guard_undecidable`` = could not judge it at all;
    ``affordance_unusable`` = the plate had no standing room and the cast was dropped;
    ``affordance_undecidable`` = the shot carried a cast and shipped with no verdict at all
    (Story 14.2 — generic by key already, so no new reader was needed). Read on the
    resume path so the warnings still fire for a resumed run — otherwise a second
    pass over the same workspace reports a clean guard. Absent key / malformed sidecar / unreadable file
    all mean False: this runs inside image_node's AD-10 boundary.
    """
    try:
        sidecar = json.loads(_sidecar_path(out_dir, scene_num, shot).read_text(encoding="utf-8"))
        return bool(sidecar.get(key)) if isinstance(sidecar, dict) else False
    except (OSError, ValueError):
        return False


def _sidecar_plate_room(out_dir: Path, scene_num: int, shot: ShotData) -> bool | None:
    """The standing-room verdict the stock plate serving this shot carried, or ``None``.

    Story 14.1 D4. ``None`` means "no verdict on record" — no sidecar, a generated shot,
    a pre-14.1 sidecar (whose ``stock_plate`` block has no such key), or a plate the vision
    endpoint refused. ``False`` is a real verdict and is NOT ``None``: with the affordance
    knob down the selector serves a measured-roomless plate on purpose, and that shot was
    judged, just not favourably. Same AD-10 posture as ``_sidecar_guard_flag``, plus
    ``AttributeError`` because ``provenance`` is nested and an older/edited sidecar may
    hold a string where a dict is expected.
    """
    try:
        sidecar = json.loads(_sidecar_path(out_dir, scene_num, shot).read_text(encoding="utf-8"))
        return ((sidecar.get("provenance") or {}).get("stock_plate") or {}).get("standing_room")
    except (OSError, ValueError, AttributeError):
        return None


def _existing_complete_shot(out_dir: Path, scene_num: int, shot: ShotData, seeds: list[int]) -> str | None:
    """Return the existing image path iff a prior attempt fully completed this shot.

    Pure file/sidecar check only (retry re-enters with state paths nulled, so
    disk is the only truth). Any filesystem hiccup (missing/racing file,
    malformed sidecar) is treated as incomplete rather than raised — this check
    runs inside image_node's AD-10 boundary and must never fail a whole run
    over one shot's resume check. [AC1-3]

    ``seeds`` is the whole fixed-length ladder (Story 10.2), not one seed: a shot
    the guard accepted on a bumped rung must still resume after the knob changes.

    A legacy sidecar without a ``seed`` key mismatches and regenerates —
    intended one-time cache invalidation (Story 11.1 AC2).
    """
    try:
        sidecar = json.loads(_sidecar_path(out_dir, scene_num, shot).read_text(encoding="utf-8"))
        if not isinstance(sidecar, dict) \
                or sidecar.get("image_prompt") != shot["image_prompt"] \
                or sidecar.get("negative_prompt") != _effective_negative_prompt(shot["negative_prompt"]) \
                or sidecar.get("seed") not in seeds:
            return None

        img_dest = out_dir / f"{_shot_base(scene_num, shot)}.png"
        if not (img_dest.is_file() and img_dest.stat().st_size > MIN_VALID_IMAGE_BYTES):
            return None
        return str(img_dest)
    except (OSError, ValueError):
        return None


def _record_trace(
    *,
    comfyui_url,
    workflow_path,
    request_count,
    image_count,
    latency_ms,
    skipped_count=0,
    stock_plate_count=0,
    depth_counts=None,
    guard_counts=None,
    affordance_counts=None,
    error=None,
) -> None:
    """Best-effort enrich the current ``image`` span. [AD-10 — tracing is non-fatal]"""
    try:
        get_client().update_current_span(
            metadata={
                "comfyui_url": comfyui_url,
                "workflow_path": workflow_path,
                "comfyui_request_count": request_count,
                "image_count": image_count,
                "skipped_count": skipped_count,
                "stock_plate_count": stock_plate_count,
                "latency_ms": latency_ms,
                # Story 11.5 AC10: depth source/cache behaviour is the only signal
                # that distinguishes "parallax rendered from a real depth map" from
                # "parallax silently fell back", so it rides the image span.
                **({f"depth_{k}": v for k, v in depth_counts.items()} if depth_counts else {}),
                # Story 10.2 AC: an exhausted ladder or an undecidable detector means
                # the frame was NOT verified unpopulated — it must be visible in the
                # trace, otherwise a dead guard reads exactly like a clean pass.
                **({f"guard_{k}": v for k, v in guard_counts.items()} if guard_counts else {}),
                # Story 14.2: same argument, one question over. A shot that lost its
                # cast, or whose plate was never judged, is invisible otherwise.
                **({f"affordance_{k}": v for k, v in affordance_counts.items()}
                   if affordance_counts else {}),
                **({"error": repr(error)} if error is not None else {}),
            },
        )
    except Exception:  # noqa: BLE001 — a tracing failure must never break the pipeline
        pass


async def _wait_for_comfyui_recovery(
    base_url: str, *, poll_sec: float, timeout_sec: float, shots_done: int, total_shots: int,
) -> None:
    """Bounded wait-and-recheck loop for a mid-batch ComfyUI crash. [AC2-5]

    Called after a health-check or ``submit_and_fetch`` failure past shot 0's
    initial fail-fast check — a crash is a crash regardless of which call
    first notices it. Polls ``check_health`` every ``poll_sec`` until it
    succeeds or ``timeout_sec`` elapses; re-raises the last failure on timeout
    so the stage fails with the existing AD-10 error format. [AC3]
    """
    logger.warning(
        "ComfyUI health check failed after %d/%d shots, waiting for recovery", shots_done, total_shots,
    )
    start = time.monotonic()
    while True:
        try:
            await comfyui_client.check_health(base_url)
        except ComfyUIError:  # still down, keep polling within budget
            if time.monotonic() - start >= timeout_sec:
                logger.warning("ComfyUI did not recover within %ds, failing stage", int(timeout_sec))
                raise
            await asyncio.sleep(poll_sec)
            continue
        logger.info("ComfyUI recovered after %ds, resuming", int(time.monotonic() - start))
        return


# Story 14.1, amended by Story 14.8 — the seven-value `camera_angle` vocabulary split
# into the five framings a room plate can serve and the two it cannot.
#
# 14.8 RETIRED THIS MAPPING FROM THE SELECTOR ENTIRELY. `_select_plate` does not read it
# at all any more — not the values, and (since the review that added `_SERVABLE_ANGLES`
# below) not the keys either — because the adopted matching axis does not involve
# viewpoint (`14-8-plate-reuse-shipping/AXIS-CANDIDATES.md` ②). The values are KEPT, and
# that is a deliberate non-deletion after a reader census, not an oversight:
# `14-1-approved-plate-sets/replay_coverage.py` needs them twice — for the servable
# denominator (24) and for C4′, the pre-registered disclosure of how many assigned plates
# sit at a viewpoint the shot's framing did NOT ask for. That number is precisely what
# 14.8 chose to accept, so deleting the values would delete the record of the cost, and
# `tests/pipeline/nodes/test_image.py` pins the VALUES for that reason (14.8 review: the
# map's values were pinned by no test although C4′'s disclosure depends on them).
#
# `close-up`, `POV` and `None` are ABSENT ON PURPOSE — their absence IS the decision,
# not an oversight, and `tests/pipeline/nodes/test_image.py` pins both halves against
# `scenario_chain._CAMERA_ANGLES` so that a new angle added to that vocabulary fails
# loudly here instead of quietly becoming `unservable_framing`:
#   * `close-up` / `POV`: a room plate is a photograph of a whole room. No framing of it
#     is an instrument-tray close-up or a ceiling POV, so there is nothing to pick and
#     the shot renders (7/31 of run 4b35c0ed — permanent by design, not a shortfall).
#   * `None`: not guessed. 14.0 §4-4 measured the SAME prompt flipping viewpoint on a
#     reseed in 2 of 5 controlled pairs, so anything inferred from the prompt text
#     instead of the field is weaker than that noise.
_ANGLE_VIEWPOINT = {
    "wide": "EYE",
    "medium": "EYE",
    "over-the-shoulder": "EYE",
    "low-angle": "LOW",
    "high-angle": "HIGH",
}
# Separated from "we do not recognise this string at all": these two are a *documented,
# permanent* refusal, and the report counts them apart from framing we failed to parse.
_UNSERVABLE_ANGLES = frozenset({"close-up", "POV"})
# WHAT THE SELECTOR ACTUALLY ASKS: "is this framing one a room plate can serve?". Derived
# from the vocabulary minus the documented refusal, NOT from `_ANGLE_VIEWPOINT`'s keys —
# a 14.8 review finding. Keying servability off the retired axis's map meant an eighth
# `camera_angle` could only be served by inventing an EYE/LOW/HIGH value in a dict this
# function no longer reads, i.e. the retired measurement would still be gating assignment.
# The two sets are equal today and `tests/pipeline/nodes/test_image.py` pins that they are;
# what changes is which one is the definition. `_CAMERA_ANGLES` is imported rather than
# re-listed here for the reason that constant's own comment gives — it was module-private
# until a consumer outside `scenario_chain` had to COMPARE against the vocabulary, and this
# is that consumer (`gotcha_deleting-a-constant-needs-a-reader-census`).
_SERVABLE_ANGLES = frozenset(_CAMERA_ANGLES) - _UNSERVABLE_ANGLES


def _select_plate(
    shot: ShotData, plates: list[dict], run_id: str, scene_num: int, *, affordance_gate: bool,
) -> tuple[dict | None, str]:
    """Pick the approved plate that fits THIS shot, or say why none does. [14.1, axis by 14.8]

    Replaces 8.17's ``_plate_variant_index``, whose key was ``(run, scene, location)`` —
    scene-keyed assignment gave every shot of a 21-shot scene the same plate and threw
    away the shot's own framing, which is the named reason
    ``stock_plate_substitution_enabled`` has shipped ``False`` since 8.17.

    **The matching axis is ``location_key``, and only ``location_key`` (Story 14.8).**
    14.1 matched the shot's ``camera_angle`` against each plate's MEASURED ``viewpoint``;
    that axis was retired on measurement, not on taste — the ``y_h`` reading it stands on
    reproduces to 0.072 mean / 0.12 max between judges (category flips 2/5) against an
    EYE band only 0.20 wide, so assignments near a boundary were a coin toss
    (`14-8-plate-reuse-shipping/AXIS-CANDIDATES.md`, candidate ④). The replacement makes
    the reproduction error structurally 0 by REMOVING the measurement rather than fixing
    it: ``location_key`` is a closed 14-value enum the scenario LLM writes
    (`domain/state.py` ``LOCATION_KEYS``) and the plate side is a manifest key, so the
    comparison is string equality on unordered values — there is no "near a boundary".
    That equality is applied HERE, on the pool this function is handed, even though every
    caller already looked the pool up by key: 14.8's review found the axis had escaped
    into the two call sites, which made this docstring and `replay_coverage.py`'s "nothing
    is re-implemented" both untrue. NOTHING here reads ``viewpoint`` any more — not the
    filters, not the digest, not the pool-entry sentinel (14.8's review found the sentinel
    still keyed on it, which made the "does not read viewpoint" claim false and left a
    rename able to route every plate to ``no_metadata`` with no test to notice).

    ⚠️ WHAT (b)=0 DOES NOT COVER: the *comparison* is exact, the *production* of
    ``shot.location_key`` by the scenario LLM was never measured. The same replay reports
    12/43 shots with no key at all, 7 of which name a ``LOCATION_KEYS`` room in their own
    ``image_prompt`` — a measured producer-side emission gap, registered in
    `deferred-work.md`. A wrongly emitted key serves the WRONG ROOM, which is a larger
    defect than the viewpoint mismatch C4′ discloses.

    THE PRICE, measured, not hidden: 7 shots of run 4b35c0ed that 14.1 refused with
    ``no_viewpoint_match`` (4 high-angle, 3 low-angle) now take eye-level plates, and 5 of
    them carry cast — ``camera_angle`` is NOT render-inert, ``character_service.py:1556``
    copies it into the per-shot catalog and ``_select_entity_angles`` picks the cast
    card's angle from it, so a high/low-angle card gets composited onto an eye-level
    plate. This function does not claim that is acceptable; `replay_coverage.py`'s C4′
    prints the list every time and the verdict is Jay's, on rendered frames.

    Pure by construction: no I/O, no clock, no settings read (the one knob it honours
    arrives as ``affordance_gate``), so `replay_coverage.py` can run the SHIPPED selector
    over a finished run's checkpoint offline and get the numbers report.md quotes.
    Returns ``(plate, "match")`` or ``(None, reason)``; every reason is a documented
    ``stock_plate_unfit`` value (``domain/state.py``) and every one of them means "this
    shot renders instead", never "this shot is lost".

    Filter order is the reason vocabulary's precedence, and it is chosen so the warning
    names the thing a human would have to act on:

    1. a framing no room plate can serve -> ``unservable_framing`` / ``unknown_framing``.
       The framing step SURVIVES the axis change: it is not a viewpoint match, it is the
       statement that a whole-room photograph cannot stand in for an instrument close-up.
       Its set is ``_SERVABLE_ANGLES`` (the vocabulary minus the documented refusal), not
       ``_ANGLE_VIEWPOINT``'s keys;
    2. no plate of this key carries a PERSON VERDICT -> ``no_metadata``, FAIL OPEN. An
       unjudged plate is never picked: 8.17 shipped exactly that (take anything approved)
       and it is what this story exists to undo. Both curators must have answered — see
       the convention note under 3;
    3. **D1** every judged candidate shows a person -> ``plate_shows_person``. This filter
       is not optional and is not gated on any knob: the plate branch ``continue``s past
       the Story 10.2/14.4 people-free guard, so with the viewpoint step gone it is the
       ONLY content filter between `entrance-checkpoint/b` (labeler: two people in the
       guard booth, still `approved`) and a cast card composited on top of them, with no
       warning at all. Refusing to *assign* an asset is not un-approving it — the row
       keeps ``status='approved'`` and goes to report.md's human queue.

       CONVENTION, made deliberate by 14.8's review: ``is False``, never truthiness, the
       same direction D2 uses below. Until 14.8 this read ``not p.get("has_person")``, so
       a plate NOBODY had judged counted as people-free — the opposite convention from
       D2's ``is True``, in the one filter that had become the last line of defence. An
       absent or null verdict is undecidable, and undecidable is not "there is no person
       here"; it is ``no_metadata``, which says the true thing ("judge these plates")
       instead of silently serving one. Measured cost of the tightening on today's corpus:
       ZERO — all 42 approved plates carry both verdicts (``label.has_person`` 42/42 via
       `location_service`'s OR fold, ``plate_meta.depicts_person`` 42/42), so the pool is
       byte-identical to the truthiness form. It only bites on a plate seeded without a
       label, which is exactly the case that used to slip through;
    4. **D2** cast-bearing shot, gate ON, no candidate with standing room ->
       ``no_standing_room``. Gated on the knob because 14.2 designed knob-down as the ONE
       recovery path for its measured 1/25 false positive, and a second un-gated hard
       filter would take that back. With the knob down the measured-bad plate is served:
       the alternative is a generated frame with no affordance verdict at all, i.e.
       refusing a measured "no" in favour of an unmeasured nothing.

    NOT a filter, and deliberately so: ``label.matches_location``. `interview-room/b` is
    labelled ``matches_location=false`` by the 8.17 labeler and is still assignable here
    with ``reason="match"``. That label is PATH B of this axis's own two-path check
    (`14-8-plate-reuse-shipping/verify_two_paths.py`), whose pre-registered band was
    committed BEFORE the measurement and which the axis passed at 1/42 = 2.4% against a
    5.0% bar — that one row IS the measured disagreement the band admitted. ⚠️ Carry the
    band's own disclosed limitation with the number: PREREGISTRATION §0 records that the
    5.0% was written AFTER a manifest field sweep, so it is NOT blind and the 2.4% reads as
    an UPPER BOUND on reproducibility, not a floor. Promoting it
    to a runtime filter after seeing which row it was would be re-cutting the gate on its
    own result, the mirror image of lowering a bar. It stays visible instead: printed by
    `verify_two_paths.py` every run, written up in `14-8-plate-reuse-shipping/report.md`,
    and registered in `deferred-work.md` for whoever owns the plate approval queue (that
    key has no demand in run 4b35c0ed, so nothing turns on it today).

    ``no_viewpoint_match`` and ``partial_metadata`` were RETIRED with the axis, in the
    same commit as ``domain/state.py``'s list, ``domain/warnings.py``'s prose and
    `tests/domain/test_run_warnings.py`'s registration (FIVE readers, not the four the
    spec named). Both described the step this function no longer has, and neither can
    fire: with no post-metadata match step, a non-empty judged pool is a non-empty
    candidate pool. A mixed pool of unjudged and person-bearing plates reports
    ``plate_shows_person`` — the judged plates' finding, which is the actionable half.
    Keeping a reason that can never fire would leave the retired axis documented as if it
    were shipped.

    Determinism/continuity: the tie-break indexes the surviving pool by a sha256 digest of
    ``(run_id, scene_num, location_key, the pool itself)``. sha256, not builtin ``hash()``
    — CPython salts str hashing per process, so ``hash()`` picks a different plate after a
    restart and a resumed run re-copies every background
    (`test_stock_variant_selection_is_deterministic_across_processes` runs it in three
    subprocesses under three ``PYTHONHASHSEED``s; do not replace that with a same-process
    re-derivation of this formula, which pins the code to itself). **The pool is part of
    the key** (D3): the older form hashed ``(run, scene, location)`` and took a modulo
    over a list the cast filter had already shortened, so within one scene a cast shot and
    a cast-free shot could land on different plates while the docstring claimed one plate
    per scene. Including the pool makes the claim exact and self-maintaining. ``viewpoint``
    LEFT the digest key with the axis (14.8): keeping it there would have made two shots of
    one room differ by a value nothing else in the function reads any more — a hidden
    dependency on a retired measurement, and worse continuity than 14.1 had. The surviving
    claim: **one plate per (run, scene, location_key, candidate set)**. A run RESUMED
    across this commit keeps whatever the old digest gave its already-rendered shots and
    draws the new digest for the rest; the ``stock_plate.axis`` marker in the sidecar
    (`image_node` below) is what tells the two apart afterwards.
    """
    angle = shot.get("camera_angle")
    if angle not in _SERVABLE_ANGLES:
        # Anything else — including a pre-14.0 checkpoint's raw prose string — is
        # `unknown_framing`, NOT `unservable_framing`: that reason is documented as
        # "close-up/POV, permanent by design", and lending it to a string we simply
        # failed to recognise would hide a parser gap inside a designed refusal.
        return None, "unservable_framing" if angle in _UNSERVABLE_ANGLES else "unknown_framing"
    # THE MATCHING AXIS, applied HERE and not left to the caller (14.8 review). Callers
    # hand this function a pool they looked up by key — `resolve_stock_plates(key)` at
    # runtime, `plates[key]` in the replay — and while the axis lived only in those
    # lookups the docstring's claim and `replay_coverage.py`'s "nothing is re-implemented"
    # were both false: the axis was a property of two call sites, not of the reviewed
    # function. String equality on a closed enum, so this is the whole axis.
    pool = [p for p in plates if p.get("location_key") == shot.get("location_key")]
    # The pool-entry sentinel is the PERSON VERDICT — a field D1 immediately below
    # actually uses — and no longer `"viewpoint" in p`, a field this function stopped
    # reading when the axis changed. `resolve_stock_plates` merges `source.label` and
    # `source.plate_meta`, and an unseeded/unmeasured plate arrives with the keys ABSENT
    # (not `{}`, not `None`), so presence is the honest test for "has anyone judged this".
    judged = [p for p in pool
              if p.get("has_person") is not None and p.get("depicts_person") is not None]
    if not judged:
        return None, "no_metadata"
    candidates = [p for p in judged
                  if p["has_person"] is False and p["depicts_person"] is False]
    if not candidates:
        return None, "plate_shows_person"
    if affordance_gate and shot.get("cast"):
        # `is True`, never truthiness: an undecidable verdict is recorded as an ABSENT
        # key (the endpoint rejects corpse/medical plates deterministically — 14.2), and
        # `None` must never read as "there is room here".
        candidates = [p for p in candidates if p.get("standing_room") is True]
        if not candidates:
            return None, "no_standing_room"
    key = ":".join([run_id, str(scene_num), shot.get("location_key") or "",
                    *(str(p.get("variant")) for p in candidates)])
    return candidates[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(candidates)], "match"


@observe(name="image")
async def image_node(state: PipelineState) -> dict:
    run_id = state.get("run_id", "?")
    t0 = time.perf_counter()
    s: Settings | None = None
    request_count = 0
    image_count = 0
    skipped_count = 0
    stock_plate_count = 0
    generated_count = 0  # Story 5.23: drives the periodic mid-batch health re-check
    health_checked = False  # Story 5.14: lazy — never touched at all if every shot resumes
    requests_since_health_check = 0  # Story 10.2: cadence counts submissions, see below
    # Declared before the try so the error path can report them too: a stage that
    # fails mid-run must not lose its guard/depth accounting.
    guard_counts = {"regenerated": 0, "exhausted": 0, "unavailable": 0, "unscreened": 0}
    # Story 14.2, its own tallies rather than more keys on `guard_counts`: these count a
    # different predicate on a different loop, and folding them in would make the 10.2
    # summary log line below read about two guards at once.
    affordance_counts = {"unusable": 0, "undecidable": 0, "unjudged": 0}
    depth_counts = {"hit": 0, "miss": 0, "unavailable": 0}
    # Story 13.1: same reason they are declared out here — a stage that fails mid-run
    # must not lose the degradations it already accumulated.
    warnings: list[RunWarning] = []
    try:
        s = _settings()  # inside try: a config/env failure surfaces as PipelineState.error too
        out_dir = Path(s.workspace_path) / run_id / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        template: dict | None = None
        prompt_nodes: dict[str, str] | None = None
        stats: dict | None = None
        if not s.comfyui_mock:
            template, prompt_nodes = _load_workflow(s.comfyui_workflow_path)
            # Once per run, not per shot, and best-effort: a failure records null
            # and logs rather than failing the stage [AD-10]. Skipped entirely in
            # mock mode, which never talks to ComfyUI at all.
            stats = await comfyui_client.get_system_stats(s.comfyui_url)
        env_sha = _env_snapshot_sha256()  # read once: two objects, one file, one warning
        provenance = _build_provenance(s.comfyui_workflow_path, template, prompt_nodes, stats, env_sha)
        # A stock plate was rendered by the plate script weeks ago, from another
        # graph, on another machine. Stamping this run's workflow hash and today's
        # ComfyUI version onto it would be provenance that actively lies — worse
        # than absent provenance, which is the whole premise of Epic 13. The
        # env-snapshot pin survives because it is a fact about the checkout that
        # wrote the sidecar, and the ``stock_plate`` block below says what actually
        # produced the image — without it this object is byte-identical to mock
        # mode's, i.e. honest but empty.
        plate_provenance = _build_provenance(s.comfyui_workflow_path, None, None, None, env_sha)
        total_shots = sum(len(scene["shots"]) for scene in state.get("scenes", []))

        async def _recover() -> None:
            # shots_done spans every path (resumed/plate/generated) so the AC5 log
            # reflects true run progress, not just the newly-generated subset.
            await _wait_for_comfyui_recovery(
                s.comfyui_url,
                poll_sec=s.comfyui_crash_recovery_poll_sec,
                timeout_sec=s.comfyui_crash_recovery_timeout_sec,
                shots_done=generated_count + skipped_count + stock_plate_count,
                total_shots=total_shots,
            )

        # ── Story 10.2: background-person guard ────────────────────────────
        guard_off = s.background_person_guard_attempts < 1 or not s.character_vision_api_key
        undecidable_streak = 0
        undecidable_total = 0
        # Per-shot, reset by the generation loop before each ladder: the sidecar has to
        # record whether THIS frame went out unjudged, and `_populated` is the only place
        # that knows. A counter delta would be equivalent and less obvious.
        undecidable_frame = False
        if s.background_person_guard_attempts >= 1 and not s.character_vision_api_key:
            # One warning per run, not per shot — the key is a run-level fact.
            logger.warning(
                "background person guard disabled: YTFLOW_CHARACTER_VISION_API_KEY is unset; "
                "generated backgrounds are NOT screened for people this run",
            )
            # Story 13.1: run-level cause -> run-level warning. `attempts < 1` is NOT
            # warned: that is the operator's own config choice, i.e. AC2's "intentionally
            # non-applicable", whereas asking for the guard and not getting it is a
            # runtime degradation. Story 14.4 kept that policy but changed what 0 MEANS:
            # the shipped default is 2 now, so 0 is an operator override deviating from a
            # recorded decision — visible in `scripts/report_decision_drift.py`, which is
            # the right layer for it, and still not a run warning.
            warnings.append(make_warning(
                "background_guard_unscreened", reason="vision_api_key_missing",
                attempts=s.background_person_guard_attempts,
            ))

        async def _populated(image_bytes: bytes, scene_num: int, shot_id: str) -> bool:
            """True only when the detector positively says a person is in frame.

            Wraps the detector so nothing it does — including an unexpected
            raise — can reach image_node's AD-10 boundary and fail the stage.
            An undecidable verdict is counted and treated as "accept", never as
            "clean": the warnings below are what say it wasn't checked.

            ``scene_num``/``shot_id`` are threaded in from the generation loop
            (Story 14.4) purely to name the shot on the per-shot warning — the
            closure is defined out here because it owns the run-level breaker
            state, and a single undecidable verdict is a SHOT-level fact.
            """
            nonlocal guard_off, undecidable_streak, undecidable_total, undecidable_frame
            if guard_off:
                return False
            try:
                verdict = await vision_check.background_has_person(image_bytes, s)
            except Exception as exc:  # noqa: BLE001 — the detector's contract is not to raise; belt to its braces
                logger.warning("background person guard: detector raised, accepting frame: %s", exc)
                verdict = None
            if verdict is None:
                undecidable_frame = True
                guard_counts["unavailable"] += 1
                undecidable_streak += 1
                undecidable_total += 1
                # Story 14.4: name the shot. Run 4b35c0ed had exactly ONE undecidable
                # verdict and it produced zero warnings — below the breaker, the only
                # trace was a counter on the image span, so an unscreened frame was
                # indistinguishable in the UI from a verified-clean one, which is the
                # defect 13.1 exists to remove. Bounded by the breaker (6 total) and
                # then by `cap_samples`, so an undecidable storm cannot flood the gate.
                warnings.append(make_warning(
                    "background_guard_unscreened", scene_num=scene_num, shot_id=shot_id,
                    reason="detector_undecidable_shot",
                ))
                # Total as well as streak: an intermittent detector (fail, ok, fail…)
                # resets the streak every other call and would never trip the breaker,
                # which is exactly the 120s-per-call cost it exists to bound.
                if undecidable_streak >= BACKGROUND_PERSON_GUARD_BREAKER_STREAK \
                        or undecidable_total >= BACKGROUND_PERSON_GUARD_BREAKER_TOTAL:
                    guard_off = True
                    logger.warning(
                        "background person guard disabled for the rest of the run after %d "
                        "consecutive / %d total undecidable verdicts",
                        undecidable_streak, undecidable_total,
                    )
                    # Fires at most once — `guard_off` short-circuits this closure from
                    # here on. Run-level cause again: every later shot is unscreened.
                    warnings.append(make_warning(
                        "background_guard_unscreened", reason="detector_undecidable",
                        undecidable_streak=undecidable_streak, undecidable_total=undecidable_total,
                    ))
                return False
            undecidable_streak = 0
            return verdict

        # ── Story 14.2: plate affordance gate ──────────────────────────────
        # The knob, kept separate from `affordance_off`: the knob being down is the
        # operator's own choice, while a missing key or a tripped breaker is a
        # degradation of a gate that was asked for. Only the latter goes in the sidecar
        # (same policy 10.2 applies to `attempts < 1` vs a missing key).
        affordance_enabled = s.plate_affordance_gate_enabled
        # No key is a CONFIG state, not a dead detector: without this the gate would fire
        # 33 doomed calls, file an undecidable row per shot and then a breaker row, all
        # describing one run-level fact. 10.2 folds the same condition into `guard_off`.
        affordance_off = not affordance_enabled or not s.character_vision_api_key
        affordance_streak = 0
        affordance_total = 0
        # Per shot, reset by the generation loop: did THIS cast-bearing frame ship with
        # no verdict? The sidecar has to carry it or a resume reports a clean tally.
        affordance_unjudged_frame = False
        if affordance_enabled and not s.character_vision_api_key:
            logger.warning(
                "plate affordance gate disabled: YTFLOW_CHARACTER_VISION_API_KEY is unset; "
                "cast-bearing shots are NOT screened for standing room this run",
            )
            # One row for the run, like 10.2's — a run-level cause gets a run-level
            # warning (Story 13.1 AC2). The knob being off files nothing at all.
            warnings.append(make_warning(
                "plate_affordance_unusable", reason="vision_api_key_missing"))

        async def _no_standing_room(image_bytes: bytes, scene_num: int, shot_id: str) -> bool:
            """True only when the detector positively says nothing can stand here.

            Same fail-open posture as ``_populated``, and the same belt to the
            detector's braces: nothing in here — including an unexpected raise —
            may reach image_node's AD-10 boundary. Takes the render's ``image_bytes``,
            the same object ``_populated`` is handed: they are already in memory,
            and re-reading ``dest`` would judge a different read of the same file.

            Undecidable is NOT "no standing room" and never will be. The endpoint
            refuses corpse/medical plates deterministically (`data_inspection_failed`,
            reproduced twice on `S00601`, which is also `None` for the 10.2 guard), and
            SCP shots of exactly that kind are standing output — reading a refusal as
            failure would delete their cast on every run, forever.
            """
            nonlocal affordance_off, affordance_streak, affordance_total
            nonlocal affordance_unjudged_frame
            if affordance_off:
                # The knob is off, no key, or the breaker tripped. Counted, never silent:
                # an unjudged cast-bearing shot must not read like a plate that passed.
                affordance_counts["unjudged"] += 1
                # …and it has to survive a resume, unless the knob itself is down: then
                # nothing was asked for and there is nothing to re-fire.
                affordance_unjudged_frame = affordance_enabled
                return False
            try:
                verdict = await vision_check.plate_has_standing_room(image_bytes, s)
            except Exception as exc:  # noqa: BLE001 — the detector's contract is not to raise; belt to its braces
                logger.warning("plate affordance gate: detector raised, keeping the cast: %s", exc)
                verdict = None
            if verdict is None:
                affordance_counts["undecidable"] += 1
                affordance_unjudged_frame = True
                affordance_streak += 1
                affordance_total += 1
                warnings.append(make_warning(
                    "plate_affordance_unusable", scene_num=scene_num, shot_id=shot_id,
                    reason="detector_undecidable",
                ))
                # Reuses 10.2's thresholds rather than inventing a second pair — same
                # endpoint, same key, same 120s-per-call worst case. Its own streak /
                # total / off-switch, though: an affordance refusal must not silence the
                # person guard, which is a different question that may still be answerable.
                if affordance_streak >= BACKGROUND_PERSON_GUARD_BREAKER_STREAK \
                        or affordance_total >= BACKGROUND_PERSON_GUARD_BREAKER_TOTAL:
                    affordance_off = True
                    logger.warning(
                        "plate affordance gate disabled for the rest of the run after %d "
                        "consecutive / %d total undecidable verdicts",
                        affordance_streak, affordance_total,
                    )
                    warnings.append(make_warning(
                        "plate_affordance_unusable", reason="detector_undecidable_run",
                        undecidable_streak=affordance_streak, undecidable_total=affordance_total,
                    ))
                return False
            affordance_streak = 0
            return verdict is False

        plate_cache: dict[str, list[dict]] = {}  # one lookup per location_key per run, not per shot
        depth_memo: dict[str, str | None] = {}  # one resolve per distinct image path per run

        async def _with_depth(shot: ShotData, image_path: str) -> ShotData:
            """Attach the shot's depth companion (Story 11.5 AC2).

            Runs on ALL three writer paths — resumed, STOCK plate, generated — so
            a cached image whose depth map is missing or stale regenerates the
            depth map ONLY, never the image. A valid pair costs zero inference:
            the resolver's own content+contract cache answers it.

            The STOCK pair comes from one variant by construction: the depth key
            is the copied file's bytes, which are that variant's bytes.
            """
            done: dict = {**shot, "image_path": image_path}
            if _depth_resolver is None:
                return done  # type: ignore[return-value]
            if image_path not in depth_memo:
                try:
                    result = await _depth_resolver(image_path) or {}
                    depth_memo[image_path] = result.get("path")
                    if result.get("path") is None:
                        depth_counts["unavailable"] += 1
                    else:
                        depth_counts["hit" if result.get("cached") else "miss"] += 1
                except Exception as exc:  # noqa: BLE001 — AD-10: no depth is a valid outcome
                    logger.warning("depth resolution failed for %s: %s", image_path, exc)
                    depth_memo[image_path] = None
                    depth_counts["unavailable"] += 1
            depth = depth_memo[image_path]
            if depth is not None:
                done["depth_map_path"] = depth
            return done  # type: ignore[return-value]

        new_scenes: list[SceneState] = []
        for scene in state.get("scenes", []):
            new_shots: list[ShotData] = []
            for shot in scene["shots"]:
                # Story 11.1: one deterministic seed per shot, shared by the
                # resume check, all sidecar writers, and the KSampler injection.
                # Story 10.2: rungs 1..N are the guard's regeneration ladder; the
                # resume check accepts any rung, generation starts at rung 0.
                seeds = _seed_ladder(run_id, scene["scene_num"], shot["shot_id"])
                seed = seeds[0]
                existing = _existing_complete_shot(out_dir, scene["scene_num"], shot, seeds)
                if existing is not None:
                    skipped_count += 1
                    image_count += 1
                    for key, counter, reason in (
                        ("guard_exhausted", "exhausted", "ladder_exhausted_earlier_run"),
                        ("guard_undecidable", "unavailable", "detector_undecidable_earlier_run"),
                    ):
                        # A frame a previous run kept while knowing it was populated, or
                        # never managed to judge, stays unverified on resume — the warning
                        # must still fire. Both flags can be set on the same shot.
                        if _sidecar_guard_flag(out_dir, scene["scene_num"], shot, key):
                            guard_counts[counter] += 1
                            warnings.append(make_warning(
                                "background_guard_unscreened", scene_num=scene["scene_num"],
                                shot_id=shot["shot_id"], reason=reason,
                            ))
                    resumed = shot
                    # Story 14.2. Guarded on the shot ACTUALLY having a cast: a shot whose
                    # cast is already `[]` (8.19's marker, an edited checkpoint) has nothing
                    # to drop, and a warning claiming a drop would be false.
                    if shot.get("cast"):
                        if affordance_enabled and _sidecar_guard_flag(
                                out_dir, scene["scene_num"], shot, "affordance_unusable"):
                            # The frame is cached, the emptied cast is not — it lives in the
                            # checkpoint, which a crash inside this node (or a resume after
                            # its error path) comes back without while the images survive.
                            # Re-apply from disk or the card comes back on this pass.
                            #
                            # The knob condition is what makes the measured 1/25 false
                            # positive RECOVERABLE: the drop is re-applied only while the
                            # gate is on, so an operator who disagrees with a verdict flips
                            # the knob down and the card returns on the next pass without
                            # re-rendering anything. The KNOB, not `affordance_off` — a
                            # missing key or a tripped breaker says the detector is
                            # unreachable now, not that its earlier verdict was wrong.
                            affordance_counts["unusable"] += 1
                            warnings.append(make_warning(
                                "plate_affordance_unusable", scene_num=scene["scene_num"],
                                shot_id=shot["shot_id"], reason="no_standing_room_earlier_run",
                                card_keys=_card_keys(shot),
                            ))
                            resumed = typing.cast(ShotData, {**shot, "cast": []})
                        elif _sidecar_plate_room(out_dir, scene["scene_num"], shot) is None:
                            # Cached frame, no verdict asked on THIS pass (the gate sits after
                            # the render). Counted so the tally cannot read as coverage, and
                            # if the earlier pass could not judge it either, that says so.
                            #
                            # Story 14.1 D4 carved out the one case where a verdict DOES
                            # exist: a shot served from a stock plate has the plate's
                            # curation-time standing-room judgement in its sidecar. Counting
                            # that `unjudged` would put a judged shot in the never-screened
                            # bucket — the distinction 14.2 exists to make, running backwards,
                            # and silently, because `affordance_undecidable` is `False` on
                            # exactly those sidecars so no warning explains the count.
                            affordance_counts["unjudged"] += 1
                            if _sidecar_guard_flag(out_dir, scene["scene_num"], shot,
                                                   "affordance_undecidable"):
                                warnings.append(make_warning(
                                    "plate_affordance_unusable", scene_num=scene["scene_num"],
                                    shot_id=shot["shot_id"], reason="unjudged_earlier_run",
                                ))
                    new_shots.append(await _with_depth(resumed, existing))
                    continue

                location_key = shot.get("location_key")
                if s.stock_plate_substitution_enabled and location_key and _location_service is not None:
                    try:
                        if location_key not in plate_cache:
                            plate_cache[location_key] = await _location_service(location_key)
                        plates = plate_cache[location_key]
                        # Story 14.1: per SHOT, on the shot's own framing. `affordance_gate`
                        # is the knob alone, not `affordance_off` — this verdict came off
                        # the asset weeks ago and needs no API key today.
                        plate, reason = _select_plate(
                            shot, plates, run_id, scene["scene_num"],
                            affordance_gate=affordance_enabled,
                        ) if plates else (None, "")
                        if plate is not None:
                            dest = out_dir / f"{_shot_base(scene['scene_num'], shot)}.png"
                            shutil.copyfile(plate["path"], dest)
                            # Story 14.2 asked nothing here and counted the shot `unjudged`,
                            # with a note that pre-judging a copied plate was 14.1's job.
                            # It is done: the plate carries a curation-time verdict, so a
                            # cast-bearing shot served from a plate that HAS one is judged —
                            # by an asset-scoped call that cost this run nothing. Only a plate
                            # whose verdict is absent (the endpoint refused it) is unjudged.
                            room = plate.get("standing_room")
                            plate_unjudged = bool(shot.get("cast")) and room is None
                            if plate_unjudged:
                                affordance_counts["unjudged"] += 1
                            _write_sidecar(out_dir, scene["scene_num"], shot, seed, {
                                **plate_provenance,
                                "stock_plate": {
                                    "location_key": location_key,
                                    "variant": plate["variant"],
                                    "path": plate["path"],
                                    # WHICH RULE ASSIGNED THIS — FORWARD provenance, and
                                    # that is the whole of its justification. An earlier
                                    # draft justified it with a resume hazard (a run
                                    # straddling the 14.8 commit mixing two axes); 14.8's
                                    # review killed that: `stock_plate_substitution_enabled`
                                    # has never shipped `True`, so ZERO `stock_plate`
                                    # sidecars written under 14.1's axis exist anywhere and
                                    # the mixture cannot occur. What it earns instead is
                                    # the NEXT replacement: the first frames this project
                                    # ever assigns from a plate set will be judged by a
                                    # human, and a later axis change must be able to tell
                                    # that verdict's frames from its own.
                                    # A HARDCODED LITERAL, deliberately: nothing derives it
                                    # from the selector, so `test_stock_plate_sidecar…`
                                    # asserts only that the string is stamped — it is not
                                    # evidence about which axis the selector ran.
                                    "axis": "location_key",
                                    # The verdict that RODE THE ASSET, not the basis of the
                                    # selection: since 14.8 `_select_plate` does not read
                                    # `viewpoint` at all. It is recorded because C4′ (the
                                    # pre-registered disclosure of the axis change's cost)
                                    # is computed from it, and because 14.2's D4 resume
                                    # path reads `standing_room` back instead of counting
                                    # every cached cast shot as never-judged.
                                    "viewpoint": plate.get("viewpoint"),
                                    "standing_room": room,
                                    "reason": reason,
                                },
                            }, affordance_undecidable=plate_unjudged and affordance_enabled)
                            image_count += 1
                            stock_plate_count += 1
                            logger.info(
                                "shot %s using STOCK plate %s variant %s (axis=location_key, "
                                "measured viewpoint %s — not the selection basis since 14.8)",
                                shot["shot_id"], location_key, plate["variant"], plate.get("viewpoint"),
                            )
                            new_shots.append(await _with_depth(shot, str(dest)))
                            continue
                        # Per SHOT, not per location key: the lookup is cached once per run
                        # (and stays cached), but "which shots ended up on a generated
                        # background instead of the plate the writer asked for" is the
                        # question this story exists to answer. The identity is
                        # code+stage+scene+shot+location, so a retry re-derives the same
                        # record and merges to the same list.
                        if plates:
                            # Kept apart from `stock_plate_missing` (Story 8.5): "this key
                            # has no approved plate at all" and "this key has plates, none
                            # of which can serve this framing" have different fixes, and
                            # the second is the normal, permanent outcome for 7/31 shots.
                            logger.info(
                                "shot %s: no approved %s plate fits (%s), generating",
                                shot["shot_id"], location_key, reason,
                            )
                            warnings.append(make_warning(
                                "stock_plate_unfit", scene_num=scene["scene_num"],
                                shot_id=shot["shot_id"], location_key=location_key,
                                reason=reason,
                            ))
                        else:
                            logger.warning(
                                "location_key %r has no approved plates, falling back to generation",
                                location_key,
                            )
                            warnings.append(make_warning(
                                "stock_plate_missing", scene_num=scene["scene_num"],
                                shot_id=shot["shot_id"], location_key=location_key,
                            ))
                    except Exception as exc:  # noqa: BLE001 — AD-10: plate lookup is best-effort, never fails the stage
                        logger.warning(
                            "stock plate resolution failed for %r, falling back to generation: %s", location_key, exc,
                        )
                        warnings.append(make_warning(
                            "stock_plate_resolution_failed", scene_num=scene["scene_num"],
                            shot_id=shot["shot_id"], location_key=location_key,
                            detail=f"{type(exc).__name__}: {exc}",
                        ))
                elif s.stock_plate_substitution_enabled and location_key:
                    # Substitution is ON and the writer named a location, but the service
                    # seam was never injected — the shot silently generates instead. Not
                    # warned when substitution is off: that is a config choice, not a
                    # degradation (it is the shipped default, Story 8.19).
                    warnings.append(make_warning(
                        "stock_plate_resolver_unavailable", scene_num=scene["scene_num"],
                        shot_id=shot["shot_id"], location_key=location_key,
                    ))

                if not s.comfyui_mock:
                    if not health_checked:
                        await comfyui_client.check_health(s.comfyui_url)
                        health_checked = True
                        requests_since_health_check = 0
                    # Story 10.2: counts submissions, not shots — a guard retry is a
                    # second submission, and the cadence exists to bound how many
                    # requests can be fired at a crashed ComfyUI before we look. It is
                    # a "requests since last check" threshold, not `count % N == 0`:
                    # a shot may fire 1..N submissions, so a modulo test evaluated once
                    # per shot steps straight over its multiples and loosens the bound.
                    elif requests_since_health_check >= s.comfyui_health_poll_every_n_shots:
                        requests_since_health_check = 0
                        try:
                            await comfyui_client.check_health(s.comfyui_url)
                        except ComfyUIError:  # a NEW mid-batch failure, not the fail-fast first check
                            await _recover()

                dest = out_dir / f"{_shot_base(scene['scene_num'], shot)}.png"
                exhausted = False
                # ponytail: 빈 사다리는 `attempts >= 0` 로 불가능하고 mock 경로는 14.2 게이트에
                # 닿지 않지만, 바인딩이 rung 루프 안에서만 일어나므로 타입체커는 둘 다 모른다.
                # 리더가 둘(`dest.write_bytes` + 어포던스 게이트)이라 사전 바인딩 한 줄이
                # 리더마다 assert 를 붙이는 것보다 짧다.
                image_bytes = b""
                undecidable_frame = False
                affordance_unjudged_frame = False
                if s.comfyui_mock:
                    shutil.copyfile(_mock_source(), dest)
                else:
                    if template is None or prompt_nodes is None:
                        raise ValueError("workflow must be loaded in real mode")
                    # Story 10.2: bounded regeneration ladder. The first render the
                    # guard does not call populated wins and `seed` is left bound to
                    # it, so the sidecar records the accepted rung (otherwise every
                    # resume would regenerate). Reaching `else` means every rung was
                    # populated: keep the last render rather than degrade the run.
                    ladder = seeds[: s.background_person_guard_attempts + 1]
                    for rung, seed in enumerate(ladder):
                        workflow = _inject_prompts(
                            template, prompt_nodes, shot["image_prompt"], shot["negative_prompt"], seed,
                        )
                        try:
                            image_bytes = await comfyui_client.submit_and_fetch(s.comfyui_url, workflow)
                        except ComfyUIError:  # AC4: a submit-time crash reuses the same recovery loop
                            await _recover()
                            image_bytes = await comfyui_client.submit_and_fetch(s.comfyui_url, workflow)
                        request_count += 1
                        requests_since_health_check += 1
                        if not await _populated(image_bytes, scene["scene_num"], shot["shot_id"]):
                            break
                        if rung + 1 < len(ladder):
                            # Only a rung another render actually follows is a
                            # regeneration; the last rung is the `else` below.
                            guard_counts["regenerated"] += 1
                            logger.info(
                                "shot %s: generated background is populated (seed %s), regenerating",
                                shot["shot_id"], seed,
                            )
                    else:
                        exhausted = True
                        guard_counts["exhausted"] += 1
                        logger.warning(
                            "shot %s: background still populated after %d attempt(s), keeping last render",
                            shot["shot_id"], len(ladder),
                        )
                        warnings.append(make_warning(
                            "background_guard_unscreened", scene_num=scene["scene_num"],
                            shot_id=shot["shot_id"], reason="ladder_exhausted",
                        ))
                    if guard_off:
                        # Knob 0, no key, or the breaker tripped: this frame was never
                        # screened. Without its own count it is indistinguishable in the
                        # trace from a background the guard verified as unpopulated.
                        guard_counts["unscreened"] += 1
                    dest.write_bytes(image_bytes)
                # Story 14.2: ONE verdict on the render the ladder settled on, and only
                # when a card is actually going to land here — affordance is not a
                # question about a background-only shot, so an empty `cast` costs 0 calls.
                # Skipped in mock mode for the same reason the 10.2 guard is: the fixture
                # PNG is not this shot's plate, and judging it would drop a real cast.
                # `.get`, like every other cast reader (run_service, video, character_service):
                # a pre-8.x checkpoint shot without the key must not fail the whole stage here.
                cast = shot.get("cast") or []
                affordance_unusable = False
                if cast and s.comfyui_mock:
                    # Counted, not asked: the fixture is not this shot's plate. Same
                    # accounting a knob-off shot gets — never judged, never clean.
                    affordance_counts["unjudged"] += 1
                    affordance_unjudged_frame = affordance_enabled
                elif cast:
                    affordance_unusable = await _no_standing_room(
                        image_bytes, scene["scene_num"], shot["shot_id"])
                if affordance_unusable:
                    affordance_counts["unusable"] += 1
                    logger.warning(
                        "shot %s: plate has no standing room, dropping cast %s",
                        shot["shot_id"], _card_keys(shot),
                    )
                    warnings.append(make_warning(
                        "plate_affordance_unusable", scene_num=scene["scene_num"],
                        shot_id=shot["shot_id"], reason="no_standing_room",
                        card_keys=_card_keys(shot),
                    ))
                generated_count += 1
                image_count += 1
                _write_sidecar(out_dir, scene["scene_num"], shot, seed, provenance,
                               guard_exhausted=exhausted,
                               guard_undecidable=undecidable_frame,
                               affordance_unusable=affordance_unusable,
                               affordance_undecidable=affordance_unjudged_frame)
                # Copy the shot; set only image_path/depth_map_path (and, when the gate
                # fired, an emptied `cast`) — never mutate the input state. [AD-4]
                done = typing.cast(ShotData, {**shot, "cast": []}) if affordance_unusable else shot
                new_shots.append(await _with_depth(done, str(dest)))
            new_scenes.append({**scene, "shots": new_shots})

        if skipped_count > 0:
            logger.info(
                "image stage resume: skipped %d complete shot(s), generated %d",
                skipped_count, image_count - skipped_count,
            )
        if guard_counts["exhausted"] or guard_counts["unavailable"] or guard_counts["unscreened"]:
            # A dead, off or exhausted guard must not read as a clean pass. [Story 10.2]
            logger.warning(
                "background person guard: %d shot(s) exhausted the ladder, %d undecidable verdict(s), "
                "%d shot(s) never screened — those backgrounds were NOT verified unpopulated",
                guard_counts["exhausted"], guard_counts["unavailable"], guard_counts["unscreened"],
            )
        if any(affordance_counts.values()):
            # Its own line, beside 10.2's: a dropped cast is a visible change to the
            # screen and an unjudged plate must not read as one that passed. [Story 14.2]
            logger.warning(
                "plate affordance gate: %d shot(s) lost their cast (no standing room), "
                "%d undecidable verdict(s), %d cast-bearing shot(s) never judged",
                affordance_counts["unusable"], affordance_counts["undecidable"],
                affordance_counts["unjudged"],
            )
        _record_trace(
            comfyui_url=s.comfyui_url, workflow_path=s.comfyui_workflow_path,
            request_count=request_count, image_count=image_count,
            skipped_count=skipped_count, stock_plate_count=stock_plate_count,
            depth_counts=depth_counts, guard_counts=guard_counts,
            affordance_counts=affordance_counts, latency_ms=_ms(t0),
        )
        return {"scenes": new_scenes, "current_stage": "image", "error": None,
                # Whole-field replacement, merged against what the checkpoint already
                # holds: no reducer in this graph, and a re-run must not double the list.
                # cap_samples bounds the per-shot families (plate misses, unscreened
                # backgrounds) — one outage on a 155-shot run must not put 155 rows in
                # front of the Approve button. The true total rides an aggregate row.
                "run_warnings": merge_warnings(state.get("run_warnings", []), cap_samples(warnings))}
    except Exception as exc:  # noqa: BLE001 — surfaced as PipelineState.error, never raised past the node
        _record_trace(
            comfyui_url=s.comfyui_url if s else "?",
            workflow_path=s.comfyui_workflow_path if s else "?",
            request_count=request_count, image_count=image_count,
            skipped_count=skipped_count, stock_plate_count=stock_plate_count,
            depth_counts=depth_counts, guard_counts=guard_counts,
            affordance_counts=affordance_counts, latency_ms=_ms(t0), error=exc,
        )
        return {"current_stage": "image", "error": f"stage=image run_id={run_id}: {exc}",
                "run_warnings": merge_warnings(state.get("run_warnings", []), cap_samples(warnings))}
