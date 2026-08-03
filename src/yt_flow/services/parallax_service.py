"""parallax_service — the 2.5D background-motion renderer ladder (Story 11.5).

One narrow adapter that turns *(plate, depth map, numeric camera trajectory)*
into a validated silent clip at exactly ``COMP_W x COMP_H @ FPS``, plus the
structured metadata the video stage traces. video_node receives it as an
injected callable and never imports this module [AD-1]; the ladder itself lives
here because it drives an external runtime, numpy/PIL and ffprobe — none of
which belong inside the 2,100-line video.py (Dev Notes: "video.py owns only
routing/assembly").

The ladder, in order, with every rung's degradation logged AND traced (AC9 —
never a silent DepthFlow success):

1. ``depthflow`` — the upstream DepthFlow ray-marcher, run OUT OF PROCESS
   against a separate virtualenv (``Settings.depthflow_python`` +
   ``scripts/depthflow_render.py``). Out-of-process is not a nicety: it is AGPL
   isolation, OpenGL/context-cleanup isolation, and torch/ShaderFlow
   dependency isolation in one decision. Off by default until spiked on the
   target host — see ``docs/PARALLAX_RUNTIME.md``.
2. ``depth_warp`` — a deterministic float depth-displacement warp in numpy,
   ffmpeg used only to encode the frames it produces. No extra runtime, no GPU,
   no AGPL. This is the rung that actually renders depth today.
3. ``None`` — the caller falls back to Story 7.3/11.3's zoompan chain, the
   final compatibility rung.

Depth convention (from ``compositing_service.DEPTH_CONVENTION``): brighter =
nearer. Displacement is applied *proportionally to nearness*, so the far plane
is nearly pinned and the near plane travels the full budgeted excursion — that
difference is the depth cue.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from yt_flow.config import Settings

logger = logging.getLogger(__name__)

# Output geometry contract (AC5). Duplicated from video.py's COMP_W/COMP_H/FPS
# for the same AD-1 reason compositing_service duplicates _X_FRAC — services/
# may not import pipeline/. ``assert_geometry`` below is called by the test suite
# against video.py's own constants so the two cannot drift.
COMP_W = 1920
COMP_H = 1080
FPS = 25

# Bump when the warp math, the encode settings or the sidecar shape change — it
# is part of the clip cache key, so a bump invalidates exactly the dependent
# clips (same contract as CAMERA_PATH_VERSION and DEPTH_PREPROC_VERSION).
ADAPTER_VERSION = "1"

# Versioned deterministic depth preprocessing (AC6). A raw depth map has hard
# object edges; displacing across one tears the plate. Dilating the *nearer* side
# over the boundary and then softening it makes the disoccluded band stretch
# instead of split. Odd dilation size is a MaxFilter requirement.
# "2": the gain field is now framed with the SAME cover-crop the plate gets
# (_cover_resize). Under "1" it was plain-resized, which only agreed with the
# plate on an exactly-16:9 source — every freely generated background is 1216x832
# or 1344x768, so the depth was misaligned with the image it gates. Bumping this
# invalidates the clips rendered against the misaligned field.
DEPTH_EDGE_VERSION = "2"
DEPTH_DILATE_PX = 5
DEPTH_BLUR_PX = 3.0
# Percentile normalisation, not min/max: one blown-out speck otherwise compresses
# the entire usable depth range into a few percent and flattens the parallax.
DEPTH_NORM_PERCENTILES = (1.0, 99.0)

# How much of the budgeted displacement the FARTHEST pixel still receives. A
# fully pinned far plane reads as a matte painting sliding behind a hole; a
# little shared motion keeps it one photographed space. The nearest pixel always
# gets 1.0, so peak visible displacement == the AC6-capped budget exactly.
PARALLAX_FAR_GAIN = 0.25

# Overscan the source before warping so no frame can expose an uncovered border
# (AC6). Covers the peak translation (the AC6 cap), the peak rotation's corner
# swing, and the micro-zoom trough, with a 2px slack for even-dimension
# rounding — the same construction camera_path.overscan_margin uses.
OVERSCAN_SLACK_PX = 2.0

_ENCODE_ARGS = ("-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p")

# Failure taxonomy (AC5): the caller must be able to tell "no runtime installed"
# from "the runtime ran and produced garbage", because they need different
# operator responses. Every value appears verbatim in logs and trace metadata.
UNAVAILABLE = "unavailable"
HEADLESS_GL = "headless_gl_failure"
RENDER_FAILED = "render_failed"
TIMEOUT = "timeout"
MALFORMED_OUTPUT = "malformed_output"
VALIDATION_FAILED = "validation_failed"
NO_DEPTH = "no_depth_map"
DISABLED = "disabled"

# scripts/depthflow_render.py exits with this when DepthFlow itself cannot be
# imported or its documented API surface is absent — an upstream API drift then
# degrades visibly to depth_warp instead of looking like a render failure.
DEPTHFLOW_UNAVAILABLE_RC = 3
DEPTHFLOW_GL_RC = 4


def assert_geometry(comp_w: int, comp_h: int, fps: int) -> None:
    """Pin this module's duplicated geometry against video.py's own constants."""
    if (comp_w, comp_h, fps) != (COMP_W, COMP_H, FPS):
        raise AssertionError(
            f"parallax_service geometry {(COMP_W, COMP_H, FPS)} drifted from "
            f"video.py's {(comp_w, comp_h, fps)}"
        )


# ── Cache + provenance (AC10) ────────────────────────────────────────────────


def _sidecar_path(clip: Path) -> Path:
    return clip.with_suffix(".json")


def _sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _trajectory_hash(samples: list) -> str:
    """Digest of the exact sampled trajectory, not just its inputs. A profile
    constant changed without a CAMERA_PATH_VERSION bump would otherwise serve
    every cached clip unchanged."""
    return hashlib.sha256(
        json.dumps([[round(v, 9) for v in s] for s in samples], separators=(",", ":")).encode()
    ).hexdigest()


def build_provenance(
    *,
    image_path: str,
    depth_map_path: str,
    samples: list,
    duration: float,
    fps: int,
    renderer: str,
    displacement_frac: float,
    overscan_margin: float,
    layer_ratios: dict,
    extra: dict,
) -> dict:
    """The full AC10 contract a cached clip must match to be reused."""
    return {
        "image_sha256": _sha256_file(image_path),
        "depth_sha256": _sha256_file(depth_map_path),
        "adapter_version": ADAPTER_VERSION,
        "depth_edge_version": DEPTH_EDGE_VERSION,
        "renderer": renderer,
        "trajectory_sha256": _trajectory_hash(samples),
        "frames": len(samples),
        "duration": round(float(duration), 6),
        "fps": int(fps),
        "geometry": [COMP_W, COMP_H],
        "displacement_frac": round(float(displacement_frac), 6),
        "far_gain": PARALLAX_FAR_GAIN,
        "overscan_margin": round(float(overscan_margin), 6),
        "layer_ratios": dict(sorted(layer_ratios.items())),
        **extra,
    }


def verify_clip(clip: Path, provenance: dict) -> dict | None:
    """Strict cache check (AC10): returns the sidecar's recorded probe on a hit.

    Incomplete, legacy (no sidecar), non-dict, mismatched, undecodable and
    ``.tmp`` artifacts are all misses. The stored probe is returned rather than
    re-probing: it was validated before promotion, and a clip whose bytes changed
    since fails the size check below.
    """
    try:
        if not clip.is_file() or clip.name.endswith(".tmp") or clip.stat().st_size == 0:
            return None
        meta = json.loads(_sidecar_path(clip).read_text(encoding="utf-8"))
        if not isinstance(meta, dict) or not isinstance(meta.get("probe"), dict):
            return None
        if any(meta.get(k) != v for k, v in provenance.items()):
            return None
        if meta.get("clip_bytes") != clip.stat().st_size:
            return None
        return meta["probe"]
    except (OSError, ValueError):
        return None


# ── FFprobe output validation (AC5) ──────────────────────────────────────────


async def _run(*args: str, timeout: float | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
        raise
    return proc.returncode or 0, out.decode(errors="replace")


async def probe_clip(path: Path, *, frames: int, fps: int) -> dict:
    """FFprobe the rendered clip and enforce the AC5 output contract.

    Raises ``ValueError`` (classified as :data:`VALIDATION_FAILED`) on any
    mismatch — the whole point is that a truncated or wrongly-sized clip is
    caught HERE, before atomic promotion, rather than surfacing as a jump cut in
    the finished video.
    """
    rc, out = await _run(
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=width,height,codec_name,pix_fmt,nb_read_frames,r_frame_rate",
        "-of", "json", str(path), timeout=120,
    )
    if rc != 0:
        raise ValueError(f"ffprobe failed (rc={rc}): {out[-300:]}")
    streams = (json.loads(out) or {}).get("streams") or []
    if not streams:
        raise ValueError("ffprobe reported no video stream")
    st = streams[0]
    num, _, den = (st.get("r_frame_rate") or "0/1").partition("/")
    probe = {
        "width": int(st.get("width") or 0),
        "height": int(st.get("height") or 0),
        "codec_name": st.get("codec_name"),
        "pix_fmt": st.get("pix_fmt"),
        "frames": int(st.get("nb_read_frames") or 0),
        "fps": round(float(num) / float(den or 1), 6),
    }
    expected = {
        "width": COMP_W, "height": COMP_H, "codec_name": "h264",
        "pix_fmt": "yuv420p", "frames": frames, "fps": float(fps),
    }
    bad = {k: (probe[k], v) for k, v in expected.items() if probe[k] != v}
    if bad:
        raise ValueError(f"output contract violated: {bad}")
    return probe


# ── Depth preprocessing (AC6) ────────────────────────────────────────────────


def _cover_resize(im: Any, ow: int, oh: int, resample: Any) -> Any:
    """Scale to cover ``ow x oh`` preserving aspect, then centre-crop to it.

    [review fix] The ONE framing decision, shared by the plate and its depth map.
    They used to disagree: the plate was cover-cropped here and the depth map was
    plain-resized, which is the same thing only for an exactly-16:9 source. Stock
    plates are 1920x1080 so they agreed; every FREELY generated background is
    1216x832 or 1344x768, where the plate loses a vertical band and the depth map
    was stretched over it instead — measured up to ~100px of depth/image
    misalignment at the top and bottom of frame, i.e. foreground pixels driven by
    the far-plane gain and vice versa. Two framings is one framing too many.
    """
    scale = max(ow / im.width, oh / im.height)
    im = im.resize(
        (max(ow, int(math.ceil(im.width * scale))),
         max(oh, int(math.ceil(im.height * scale)))),
        resample,
    )
    left = (im.width - ow) // 2
    top = (im.height - oh) // 2
    return im.crop((left, top, left + ow, top + oh))


def depth_gain_field(depth_path: str | Path, size: tuple[int, int]) -> Any:
    """The per-pixel displacement multiplier, in ``[PARALLAX_FAR_GAIN, 1.0]``.

    Deterministic and versioned (:data:`DEPTH_EDGE_VERSION`): frame to the warp
    source's size with :func:`_cover_resize` — the SAME framing the plate gets, so
    a depth feature gates the pixels it actually belongs to — then dilate the
    nearer side over each depth edge, soften it, and normalise against robust
    percentiles.
    """
    import numpy as np
    from PIL import Image, ImageFilter

    with Image.open(depth_path) as im:
        d = _cover_resize(im.convert("L"), size[0], size[1], Image.BILINEAR)
    d = d.filter(ImageFilter.MaxFilter(DEPTH_DILATE_PX))
    d = d.filter(ImageFilter.GaussianBlur(DEPTH_BLUR_PX))
    arr = np.asarray(d, dtype=np.float32)
    lo, hi = np.percentile(arr, DEPTH_NORM_PERCENTILES)
    if hi - lo < 1e-6:  # a flat map carries no depth: uniform motion, no tearing
        return np.full(arr.shape, 1.0, dtype=np.float32)
    norm = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    return (PARALLAX_FAR_GAIN + (1.0 - PARALLAX_FAR_GAIN) * norm).astype(np.float32)


# ── Rung 2: the depth-displacement warp ──────────────────────────────────────


def _load_overscan_source(image_path: str, margin: float) -> Any:
    """The plate, scaled to cover the overscanned frame and centre-cropped to it.

    Mirrors ``_zoompan_filter``'s ``scale=…:-2,crop`` framing decision so the
    two renderers frame the same plate the same way; a plate narrower than 16:9
    loses the same vertical band it always did. :func:`depth_gain_field` frames
    its map through the same helper, which is what keeps depth and image aligned.
    """
    import numpy as np
    from PIL import Image

    ow = max(2, int(round(COMP_W * (1.0 + margin))))
    oh = max(2, int(round(COMP_H * (1.0 + margin))))
    with Image.open(image_path) as im:
        src = _cover_resize(im.convert("RGB"), ow, oh, Image.LANCZOS)
    return np.asarray(src, dtype=np.float32)


# The warp is memory-bandwidth bound, not compute bound: every output pixel is a
# random-ish gather out of a 27MB source. Measured on the target host (RX 9060 XT
# box, 16 cores), 1920x1080 bilinear + depth offset:
#
#   one whole-frame pass, 2D fancy indexing ......... 250 ms/frame
#   np.take + in-place lerp ........................ 159 ms/frame
#   + 32 row blocks (working set fits L3) .......... 101 ms/frame
#   + 4 worker threads over those blocks ............ 53 ms/frame
#
# 53ms is what keeps a full 54-clip run inside the PRD's two-hour ceiling
# (AC11): ~12 min of warping versus ~50 min at the naive rate. Both knobs are
# plain stdlib/numpy, no new dependency.
WARP_ROW_BLOCKS = 32
WARP_WORKERS = 4


def _row_grids(blocks: int = WARP_ROW_BLOCKS) -> list[tuple[Any, Any]]:
    """Frame-centred (U, V) coordinate grids, one per row block. Cached module-
    wide: identical for every frame of every clip."""
    import numpy as np

    cached = getattr(_row_grids, "_cache", None)
    if cached is not None and len(cached) == blocks:
        return cached
    step = COMP_H // blocks
    grids = []
    for i in range(blocks):
        y0, y1 = i * step, (COMP_H if i == blocks - 1 else (i + 1) * step)
        grids.append(np.meshgrid(
            np.arange(COMP_W, dtype=np.float32) - COMP_W / 2.0,
            np.arange(y0, y1, dtype=np.float32) - COMP_H / 2.0,
        ))
    _row_grids._cache = grids  # type: ignore[attr-defined]
    return grids


def _warp_block(src_flat: Any, gain: Any, shape: tuple[int, int], sample: Any, u: Any, v: Any) -> Any:
    """One row band of one output frame: inverse-affine the overscan source, add
    the depth-proportional offset, bilinear-gather. Pure and deterministic.

    ponytail: a backward warp sampled through the *source's* depth, not a
    forward splat with hole filling. Known ceiling, named: a disoccluded band
    behind a foreground object STRETCHES rather than revealing real content —
    that is why DEPTH_DILATE_PX/DEPTH_BLUR_PX exist and why displacement is
    capped to 1-3% of width. The upgrade path is DepthFlow's ray-marched
    inpainting on rung 1, not more numpy here.

    The lerp is written as in-place ops on the gathered buffers rather than the
    readable ``top + (bot-top)*fy`` form: each temporary is 24MB, and on a
    bandwidth-bound kernel the allocations *are* the runtime.
    """
    import numpy as np

    sh, sw = shape
    _, dx, dy, rot, zoom = sample
    k = np.float32(1.0 / (1.0 + zoom) if zoom > -0.99 else 1.0)
    ca, sa = np.float32(math.cos(-rot)) * k, np.float32(math.sin(-rot)) * k

    sx = u * ca
    sx -= v * sa
    sx += np.float32(sw / 2.0)
    sy = u * sa
    sy += v * ca
    sy += np.float32(sh / 2.0)

    # Depth is read at the affine-mapped position with a nearest sample — the
    # gain field is already dilated and blurred, so sub-pixel accuracy here buys
    # nothing but another pair of gathers.
    g = gain[
        np.clip(sy, 0, sh - 1).astype(np.int32),
        np.clip(sx, 0, sw - 1).astype(np.int32),
    ]
    sx -= g * np.float32(dx * COMP_W)
    sy -= g * np.float32(dy * COMP_W)
    np.clip(sx, 0, sw - 2, out=sx)
    np.clip(sy, 0, sh - 2, out=sy)

    xi, yi = sx.astype(np.int32), sy.astype(np.int32)
    fx, fy = (sx - xi)[..., None], (sy - yi)[..., None]
    base = yi * sw + xi
    p00 = np.take(src_flat, base, axis=0)
    p01 = np.take(src_flat, base + 1, axis=0)
    p10 = np.take(src_flat, base + sw, axis=0)
    p11 = np.take(src_flat, base + sw + 1, axis=0)
    p01 -= p00; p01 *= fx; p00 += p01   # noqa: E702 — one lerp per line reads better here
    p11 -= p10; p11 *= fx; p10 += p11   # noqa: E702
    p10 -= p00; p10 *= fy; p00 += p10   # noqa: E702
    return p00.astype(np.uint8)


def warp_frame(src: Any, gain: Any, sample: Any, pool: Any = None) -> Any:
    """One full output frame, assembled from :func:`_warp_block` row bands.

    THE production warp entry point — ``_render_depth_warp`` calls exactly this,
    so the determinism/direction/shape tests exercise the shipped code rather than
    a second copy of it. ``reshape(-1, 3)`` on the contiguous source is a view and
    ``ascontiguousarray`` of a contiguous array is a no-op, so re-deriving
    ``src_flat`` per frame costs nothing.
    """
    import numpy as np

    sh, sw = src.shape[:2]
    src_flat = np.ascontiguousarray(src.reshape(-1, 3))
    grids = _row_grids()

    def block(gv):
        return _warp_block(src_flat, gain, (sh, sw), sample, gv[0], gv[1])

    # pool.map preserves order, which the raw-video pipe requires.
    bands = list(pool.map(block, grids)) if pool else [block(gv) for gv in grids]
    return np.concatenate(bands)


async def _render_depth_warp(
    image_path: str, depth_path: str, samples: list, fps: int, out_path: Path,
    margin: float,
) -> None:
    """Warp every frame in-process and pipe raw RGB into one ffmpeg encode.

    ``margin`` is the overscan the trajectory needs, computed once by
    ``camera_path.sample_overscan_margin`` — the SAME value video.py feeds the
    card-side ground tracking, so the plate and the cards cannot disagree about
    how far the plate was scaled up before warping.
    """
    from concurrent.futures import ThreadPoolExecutor

    src = _load_overscan_source(image_path, margin)
    gain = depth_gain_field(depth_path, (src.shape[1], src.shape[0]))
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{COMP_W}x{COMP_H}", "-r", str(fps), "-i", "-",
        "-frames:v", str(len(samples)), *_ENCODE_ARGS, str(out_path),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdin is not None
    loop = asyncio.get_running_loop()
    try:
        # Threads, not processes: numpy releases the GIL inside take/ufuncs, and a
        # process pool would have to ship the 27MB source to every worker.
        with ThreadPoolExecutor(WARP_WORKERS) as pool:
            for sample in samples:
                # [review fix] Calls warp_frame rather than re-inlining it, so the
                # function the tests pin IS the one that renders.
                frame = await loop.run_in_executor(
                    None, lambda s=sample: warp_frame(src, gain, s, pool),
                )
                proc.stdin.write(frame.tobytes())
                await proc.stdin.drain()
        proc.stdin.close()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            await proc.stdin.wait_closed()
    except (BrokenPipeError, ConnectionResetError) as exc:
        raise RuntimeError(f"ffmpeg closed the pipe early: {exc}") from exc
    _, stderr = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(
            f"ffmpeg encode failed (rc={proc.returncode}): {stderr.decode(errors='replace')[-400:]}"
        )


# ── Rung 1: DepthFlow, out of process ────────────────────────────────────────

# [review fix] Anchored to the repo root via __file__, not the process CWD. A
# CWD-relative path made rung 1 report `unavailable` for any server not launched
# from the repo root — the most confusing possible outcome for Jay's Task 0 spike,
# because "DepthFlow is not installed" and "you started uvicorn from elsewhere"
# would look identical in the log.
DEPTHFLOW_RUNNER = Path(__file__).resolve().parents[3] / "scripts" / "depthflow_render.py"


def depthflow_available(settings: Settings) -> bool:
    """Both halves of the external-runtime contract must be present."""
    python = getattr(settings, "depthflow_python", "") or ""
    return bool(python) and Path(python).exists() and DEPTHFLOW_RUNNER.is_file()


async def _render_depthflow(
    image_path: str, depth_path: str, samples: list, fps: int, out_path: Path,
    settings: Settings,
) -> None:
    """Hand the render to the isolated DepthFlow venv and wait, bounded.

    The trajectory travels as a JSON spec file rather than argv: 125 frames of
    five floats each is not a command line. Exit codes above are mapped by the
    caller into the failure taxonomy.
    """
    spec = {
        "image": str(Path(image_path).resolve()),
        "depth": str(Path(depth_path).resolve()),
        "output": str(out_path.resolve()),
        "width": COMP_W, "height": COMP_H, "fps": int(fps),
        "samples": [[float(v) for v in s] for s in samples],
        "far_gain": PARALLAX_FAR_GAIN,
    }
    spec_path = out_path.with_name(f"{out_path.name}.spec.{uuid.uuid4().hex}.json")
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    try:
        rc, out = await _run(
            settings.depthflow_python, str(DEPTHFLOW_RUNNER), "--spec", str(spec_path),
            timeout=settings.depthflow_timeout_sec,
        )
    finally:
        spec_path.unlink(missing_ok=True)
    if rc == DEPTHFLOW_UNAVAILABLE_RC:
        raise FileNotFoundError(f"DepthFlow runtime unusable: {out[-300:]}")
    if rc == DEPTHFLOW_GL_RC:
        raise ConnectionError(f"headless OpenGL unavailable: {out[-300:]}")
    if rc != 0:
        raise RuntimeError(f"DepthFlow runner failed (rc={rc}): {out[-400:]}")


# ── The ladder ───────────────────────────────────────────────────────────────


async def render_motion_clip(
    *,
    image_path: str,
    depth_map_path: str | None,
    samples: list,
    duration: float,
    fps: int,
    out_path: str | Path,
    overscan_margin: float,
    displacement_frac: float,
    layer_ratios: dict,
    provenance_extra: dict | None = None,
    settings: Settings | None = None,
) -> dict:
    """Render one shot's moving background, or report why it could not.

    Returns ``{"path": str | None, "renderer": str | None, "cached": bool,
    "latency_ms": int, "fallback_reason": str | None, "probe": dict | None}``.
    ``path=None`` is a *shot-local* outcome: the caller drops to the legacy
    zoompan renderer for that shot only (AC9). Exhausting every renderer is the
    caller's decision to fail, not this module's — it never raises.
    """
    t0 = time.perf_counter()
    settings = settings or Settings()  # type: ignore[call-arg]
    out_path = Path(out_path)

    def result(**kw: Any) -> dict:
        return {
            "path": None, "renderer": None, "cached": False, "probe": None,
            "fallback_reason": None, "latency_ms": int((time.perf_counter() - t0) * 1000),
            **kw,
        }

    if not getattr(settings, "parallax_25d_enabled", False):
        return result(fallback_reason=DISABLED)
    if not depth_map_path or not Path(depth_map_path).is_file():
        return result(fallback_reason=NO_DEPTH)
    if not samples:
        return result(fallback_reason=RENDER_FAILED)

    # Candidate renderers in ladder order. DepthFlow's absence is not an error
    # worth a warning on every shot — it is the documented default state.
    backends: list[tuple[str, Any]] = []
    if getattr(settings, "depthflow_enabled", False):
        if depthflow_available(settings):
            backends.append(("depthflow", _render_depthflow))
        else:
            logger.warning(
                "depthflow_enabled but the runtime is not configured "
                "(depthflow_python=%r); degrading to depth_warp",
                getattr(settings, "depthflow_python", ""),
            )
    backends.append(("depth_warp", _render_depth_warp))

    reason: str | None = None
    for renderer, backend in backends:
        provenance = build_provenance(
            image_path=image_path, depth_map_path=depth_map_path, samples=samples,
            duration=duration, fps=fps, renderer=renderer,
            displacement_frac=displacement_frac, overscan_margin=overscan_margin,
            layer_ratios=layer_ratios,
            extra=provenance_extra or {},
        )
        probe = verify_clip(out_path, provenance)
        if probe is not None:
            return result(
                path=str(out_path), renderer=renderer, cached=True, probe=probe,
            )
        # Render to a temp sibling and promote only after FFprobe agrees: a
        # failed attempt must never overwrite a previously valid clip (AC10).
        tmp = out_path.with_name(f"{out_path.name}.{uuid.uuid4().hex}.tmp.mp4")
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if renderer == "depthflow":
                await backend(image_path, depth_map_path, samples, fps, tmp, settings)
            else:
                await backend(image_path, depth_map_path, samples, fps, tmp, overscan_margin)
            if not tmp.is_file() or tmp.stat().st_size == 0:
                raise ValueError("renderer produced no output")
            probe = await probe_clip(tmp, frames=len(samples), fps=fps)
        except asyncio.TimeoutError:
            reason = TIMEOUT
        except FileNotFoundError as exc:  # missing runtime OR missing ffmpeg/ffprobe
            reason = UNAVAILABLE
            logger.warning("%s renderer unavailable: %s", renderer, exc)
        except ConnectionError as exc:
            reason = HEADLESS_GL
            logger.warning("%s headless OpenGL failure: %s", renderer, exc)
        except ValueError as exc:
            reason = MALFORMED_OUTPUT if "no output" in str(exc) else VALIDATION_FAILED
            logger.warning("%s output rejected (%s): %s", renderer, reason, exc)
        except Exception as exc:  # noqa: BLE001 — every renderer failure is shot-local
            reason = RENDER_FAILED
            logger.warning("%s render failed: %s", renderer, exc)
        else:
            _sidecar_path(out_path).unlink(missing_ok=True)  # never a stale pair
            shutil.move(str(tmp), str(out_path))
            _sidecar_path(out_path).write_text(
                json.dumps(
                    {**provenance, "clip_bytes": out_path.stat().st_size, "probe": probe},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            return result(path=str(out_path), renderer=renderer, probe=probe)
        finally:
            tmp.unlink(missing_ok=True)
        if reason == TIMEOUT:
            logger.warning("%s renderer timed out, degrading", renderer)

    return result(fallback_reason=reason or RENDER_FAILED)
