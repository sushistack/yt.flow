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
    guard_exhausted: bool = False,
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

    ``provenance`` (Story 13.3) is additive for exactly the same reason, and more
    sharply: it changes whenever ComfyUI is upgraded or the env snapshot is
    refreshed, so putting it anywhere near ``_existing_complete_shot``'s three
    compared keys would re-render every cached background on the next upgrade.
    It is **required**, not defaulted: 11.1's lesson (``seed``) is that a writer
    path which silently omits a sidecar field is only discovered in a live run,
    and each of the three paths owes a *different, honest* provenance object.
    """
    _sidecar_path(out_dir, scene_num, shot).write_text(
        json.dumps({
            "image_prompt": shot["image_prompt"],
            "negative_prompt": _effective_negative_prompt(shot["negative_prompt"]),
            "seed": seed,
            "guard_exhausted": guard_exhausted,
            "provenance": provenance,
        }),
        encoding="utf-8",
    )


def _sidecar_guard_exhausted(out_dir: Path, scene_num: int, shot: ShotData) -> bool:
    """Did a previous run keep this shot with a background it knew was populated?

    Read on the resume path so the run-level warning still fires for a resumed
    run — otherwise a second pass over the same workspace reports a clean guard.
    """
    try:
        sidecar = json.loads(_sidecar_path(out_dir, scene_num, shot).read_text(encoding="utf-8"))
        return bool(sidecar.get("guard_exhausted")) if isinstance(sidecar, dict) else False
    except (OSError, ValueError):
        return False


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


def _plate_variant_index(run_id: str, scene_num: int, location_key: str, count: int) -> int:
    """Deterministic per-run variant pick: same run always picks the same variant
    for the same scene (spatial continuity); different runs vary naturally.

    Uses sha256, not the builtin ``hash()`` — CPython salts str hashing per
    process (PYTHONHASHSEED), so ``hash()`` would pick a different variant for
    the same run/scene after a process restart (e.g. a resumed run), breaking
    the continuity guarantee this function exists for.
    """
    digest = hashlib.sha256(f"{run_id}:{scene_num}:{location_key}".encode()).hexdigest()
    return int(digest, 16) % count


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
        if s.background_person_guard_attempts >= 1 and not s.character_vision_api_key:
            # One warning per run, not per shot — the key is a run-level fact.
            logger.warning(
                "background person guard disabled: YTFLOW_CHARACTER_VISION_API_KEY is unset; "
                "generated backgrounds are NOT screened for people this run",
            )
            # Story 13.1: run-level cause -> run-level warning. `attempts < 1` is NOT
            # warned: that is the operator's own config choice (the shipped default),
            # i.e. AC2's "intentionally non-applicable", whereas asking for the guard and
            # not getting it is a runtime degradation.
            warnings.append(make_warning(
                "background_guard_unscreened", reason="vision_api_key_missing",
                attempts=s.background_person_guard_attempts,
            ))

        async def _populated(image_bytes: bytes) -> bool:
            """True only when the detector positively says a person is in frame.

            Wraps the detector so nothing it does — including an unexpected
            raise — can reach image_node's AD-10 boundary and fail the stage.
            An undecidable verdict is counted and treated as "accept", never as
            "clean": the run-level warning below is what says it wasn't checked.
            """
            nonlocal guard_off, undecidable_streak, undecidable_total
            if guard_off:
                return False
            try:
                verdict = await vision_check.background_has_person(image_bytes, s)
            except Exception as exc:  # noqa: BLE001 — the detector's contract is not to raise; belt to its braces
                logger.warning("background person guard: detector raised, accepting frame: %s", exc)
                verdict = None
            if verdict is None:
                guard_counts["unavailable"] += 1
                undecidable_streak += 1
                undecidable_total += 1
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
                    if _sidecar_guard_exhausted(out_dir, scene["scene_num"], shot):
                        # A frame a previous run kept while knowing it was populated
                        # stays unverified on resume — the warning must still fire.
                        guard_counts["exhausted"] += 1
                        warnings.append(make_warning(
                            "background_guard_unscreened", scene_num=scene["scene_num"],
                            shot_id=shot["shot_id"], reason="ladder_exhausted_earlier_run",
                        ))
                    new_shots.append(await _with_depth(shot, existing))
                    continue

                location_key = shot.get("location_key")
                if s.stock_plate_substitution_enabled and location_key and _location_service is not None:
                    try:
                        if location_key not in plate_cache:
                            plate_cache[location_key] = await _location_service(location_key)
                        plates = plate_cache[location_key]
                        if plates:
                            plate = plates[_plate_variant_index(run_id, scene["scene_num"], location_key, len(plates))]
                            dest = out_dir / f"{_shot_base(scene['scene_num'], shot)}.png"
                            shutil.copyfile(plate["path"], dest)
                            _write_sidecar(out_dir, scene["scene_num"], shot, seed, {
                                **plate_provenance,
                                "stock_plate": {
                                    "location_key": location_key,
                                    "variant": plate["variant"],
                                    "path": plate["path"],
                                },
                            })
                            image_count += 1
                            stock_plate_count += 1
                            logger.info(
                                "shot %s using STOCK plate %s variant %s",
                                shot["shot_id"], location_key, plate["variant"],
                            )
                            new_shots.append(await _with_depth(shot, str(dest)))
                            continue
                        logger.warning(
                            "location_key %r has no approved plates, falling back to generation", location_key,
                        )
                        # Per SHOT, not per location key: the lookup is cached once per run
                        # (and stays cached), but "which shots ended up on a generated
                        # background instead of the plate the writer asked for" is the
                        # question this story exists to answer. The identity is
                        # code+stage+scene+shot+location, so a retry re-derives the same
                        # record and merges to the same list.
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
                        if not await _populated(image_bytes):
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
                generated_count += 1
                image_count += 1
                _write_sidecar(out_dir, scene["scene_num"], shot, seed, provenance,
                               guard_exhausted=exhausted)
                # Copy the shot; set only image_path/depth_map_path — never mutate the
                # input state. [AD-4]
                new_shots.append(await _with_depth(shot, str(dest)))
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
        _record_trace(
            comfyui_url=s.comfyui_url, workflow_path=s.comfyui_workflow_path,
            request_count=request_count, image_count=image_count,
            skipped_count=skipped_count, stock_plate_count=stock_plate_count,
            depth_counts=depth_counts, guard_counts=guard_counts, latency_ms=_ms(t0),
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
            depth_counts=depth_counts, guard_counts=guard_counts, latency_ms=_ms(t0), error=exc,
        )
        return {"current_stage": "image", "error": f"stage=image run_id={run_id}: {exc}",
                "run_warnings": merge_warnings(state.get("run_warnings", []), cap_samples(warnings))}
