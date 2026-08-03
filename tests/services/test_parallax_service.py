"""Tests for Story 11.5's 2.5D renderer ladder (parallax_service).

Fully offline and CI-safe: no DepthFlow runtime, no OpenGL context, no GPU, no
ComfyUI, no model weights. The depth-warp rung DOES run for real on tiny
fixtures (a 64x36 plate is a few ms) because the warp math is the thing worth
proving; every ffmpeg/ffprobe interaction is either real-but-tiny or faked.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from yt_flow.services import parallax_service as ps

# A trajectory is a list of (t, x, y, rot, zoom) tuples — the plain-data contract
# video.py hands over, deliberately not a camera_path type (services/ may not
# import pipeline/).
FLAT = [(i / 25, 0.0, 0.0, 0.0, 0.0) for i in range(5)]
MOVING = [(i / 25, 0.02 * i / 4, 0.0, 0.0, 0.05 * i / 4) for i in range(5)]


def _settings(tmp_path, **kw):
    base = dict(
        parallax_25d_enabled=True,
        depthflow_enabled=False,
        depthflow_python="",
        depthflow_timeout_sec=30.0,
        workspace_path=str(tmp_path),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _plate(path: Path, size=(64, 36)) -> Path:
    # A gradient, not flat colour: a flat plate warps to itself and would hide
    # every displacement bug in this file.
    im = Image.new("RGB", size)
    im.putdata([(x * 4 % 256, y * 7 % 256, 90) for y in range(size[1]) for x in range(size[0])])
    im.save(path)
    return path


def _depth(path: Path, size=(64, 36), split=True) -> Path:
    """Brighter = nearer (the pipeline's convention): near left, far right."""
    im = Image.new("L", size)
    im.putdata([
        (230 if (split and x < size[0] // 2) else 30)
        for y in range(size[1]) for x in range(size[0])
    ])
    im.save(path)
    return path


async def _render(tmp_path, *, samples=None, depth=True, depth_path=None, **settings_kw):
    plate = _plate(tmp_path / "plate.png")
    if depth_path is None and depth:
        depth_path = str(_depth(tmp_path / "depth.png"))
    elif not depth:
        depth_path = None
    return await ps.render_motion_clip(
        image_path=str(plate), depth_map_path=depth_path,
        samples=samples if samples is not None else MOVING,
        duration=len(MOVING) / 25, fps=25, out_path=tmp_path / "out.mp4",
        overscan_margin=0.05, displacement_frac=0.02,
        layer_ratios={"far": 0.6, "mid": 0.7, "near": 0.8},
        provenance_extra={"archetype": "push_in", "k": 1},
        settings=_settings(tmp_path, **settings_kw),
    )


# ── Geometry contract (AC5) ──────────────────────────────────────────────────


def test_geometry_matches_video_pys_own_constants():
    """parallax_service duplicates COMP_W/COMP_H/FPS (AD-1: services/ may not
    import pipeline/). Pin them against the real source so they cannot drift."""
    from yt_flow.pipeline.nodes.video import COMP_H, COMP_W, FPS

    ps.assert_geometry(COMP_W, COMP_H, FPS)  # raises on drift


def test_geometry_drift_is_caught():
    with pytest.raises(AssertionError):
        ps.assert_geometry(1280, 720, 30)


# ── The depth gain field (AC6) ───────────────────────────────────────────────


def test_depth_gain_field_is_bounded_and_ordered(tmp_path):
    """Nearest pixel gets the full budget, farthest gets PARALLAX_FAR_GAIN — that
    difference IS the depth cue, and neither end may escape the range."""
    gain = ps.depth_gain_field(_depth(tmp_path / "d.png"), (64, 36))
    assert gain.min() >= ps.PARALLAX_FAR_GAIN - 1e-6
    assert gain.max() <= 1.0 + 1e-6
    near_side = gain[:, :20].mean()
    far_side = gain[:, -20:].mean()
    assert near_side > far_side


def test_flat_depth_map_yields_uniform_motion(tmp_path):
    """A failed/flat estimate must not tear the plate: uniform gain, no parallax."""
    gain = ps.depth_gain_field(_depth(tmp_path / "flat.png", split=False), (64, 36))
    assert gain.min() == gain.max() == 1.0


def test_depth_preprocessing_is_deterministic(tmp_path):
    d = _depth(tmp_path / "d.png")
    a = ps.depth_gain_field(d, (64, 36))
    b = ps.depth_gain_field(d, (64, 36))
    assert (a == b).all()


def test_depth_edge_version_is_recorded():
    # "2": [review fix] the gain field is framed with the plate's cover-crop, not a
    # plain resize. The bump is what invalidates clips warped against the
    # misaligned field — see test_depth_field_is_framed_exactly_like_the_plate.
    assert ps.DEPTH_EDGE_VERSION == "2"
    assert ps.DEPTH_DILATE_PX % 2 == 1  # MaxFilter requires an odd window


# ── The warp itself ──────────────────────────────────────────────────────────


def test_warp_displaces_near_pixels_more_than_far(tmp_path):
    """AC6's depth cue, measured: with a horizontal shift, the near half of the
    plate moves further than the far half."""
    import numpy as np

    src = ps._load_overscan_source(str(_plate(tmp_path / "p.png", (256, 144))), 0.05)
    gain = ps.depth_gain_field(_depth(tmp_path / "d.png", (256, 144)), (src.shape[1], src.shape[0]))
    still = ps.warp_frame(src, gain, (0.0, 0.0, 0.0, 0.0, 0.0))
    shifted = ps.warp_frame(src, gain, (0.0, 0.02, 0.0, 0.0, 0.0))
    near_delta = np.abs(shifted[:, :400].astype(int) - still[:, :400].astype(int)).mean()
    far_delta = np.abs(shifted[:, -400:].astype(int) - still[:, -400:].astype(int)).mean()
    assert near_delta > far_delta > 0


def test_warp_is_deterministic(tmp_path):
    src = ps._load_overscan_source(str(_plate(tmp_path / "p.png", (128, 72))), 0.05)
    gain = ps.depth_gain_field(_depth(tmp_path / "d.png", (128, 72)), (src.shape[1], src.shape[0]))
    a = ps.warp_frame(src, gain, MOVING[3])
    b = ps.warp_frame(src, gain, MOVING[3])
    assert (a == b).all()


def test_warp_output_is_exactly_the_frame_size(tmp_path):
    src = ps._load_overscan_source(str(_plate(tmp_path / "p.png", (128, 72))), 0.05)
    gain = ps.depth_gain_field(_depth(tmp_path / "d.png", (128, 72)), (src.shape[1], src.shape[0]))
    assert ps.warp_frame(src, gain, MOVING[0]).shape == (ps.COMP_H, ps.COMP_W, 3)


def test_row_blocks_tile_the_frame_exactly():
    """Row blocking is a performance decision; a gap or overlap would be a
    visible band, so the tiling is asserted rather than trusted."""
    grids = ps._row_grids()
    assert sum(u.shape[0] for u, _ in grids) == ps.COMP_H
    assert all(u.shape[1] == ps.COMP_W for u, _ in grids)


def test_overscan_source_covers_the_margin(tmp_path):
    """No warped frame may expose a border, so the source must be at least the
    overscanned frame in both axes — including for a non-16:9 plate."""
    for size in ((64, 36), (1344, 768), (100, 300)):
        src = ps._load_overscan_source(str(_plate(tmp_path / "p.png", size)), 0.08)
        assert src.shape[0] >= round(ps.COMP_H * 1.08)
        assert src.shape[1] >= round(ps.COMP_W * 1.08)


@pytest.mark.parametrize("size", [(1216, 832), (1344, 768), (1920, 1080), (900, 1600)])
def test_depth_field_is_framed_exactly_like_the_plate(tmp_path, size):
    """[review fix] The depth map and the plate must be framed by the SAME
    decision, or the gain field gates the wrong pixels.

    A plate wider or narrower than 16:9 is cover-cropped (a vertical or horizontal
    band is discarded); a plain resize of its depth map STRETCHES that band back in
    instead. Stock plates are 1920x1080 so the bug was invisible there, but every
    freely generated background is 1216x832 or 1344x768 — measured ~100px of
    vertical misalignment at the frame edges, which drives foreground pixels with
    the far-plane gain.

    Proven with a matched horizontal split in image and depth: after framing, the
    two boundaries must land on the same row.
    """
    import numpy as np
    from PIL import Image

    w, h = size
    split = int(h * 0.4)
    img = np.zeros((h, w, 3), np.uint8)
    img[:split] = 255
    Image.fromarray(img).save(tmp_path / "plate.png")
    dep = np.zeros((h, w), np.uint8)
    dep[:split] = 255
    Image.fromarray(dep, "L").save(tmp_path / "depth.png")

    src = ps._load_overscan_source(str(tmp_path / "plate.png"), 0.06)
    gain = ps.depth_gain_field(str(tmp_path / "depth.png"), (src.shape[1], src.shape[0]))
    mid = src.shape[1] // 2
    image_edge = int(np.argmax(src[:, mid, 0] < 128))
    gain_edge = int(np.argmax(gain[:, mid] < (ps.PARALLAX_FAR_GAIN + 1.0) / 2))
    # DEPTH_DILATE_PX pushes the *nearer* side over the boundary on purpose, so the
    # gain edge sits a couple of px low by design. Anything beyond that is the
    # framing disagreement.
    assert abs(gain_edge - image_edge) <= ps.DEPTH_DILATE_PX, (
        f"{size}: image boundary row {image_edge}, gain boundary row {gain_edge}"
    )


# ── The ladder and its failure taxonomy (AC5, AC9) ───────────────────────────


async def test_kill_switch_declines_without_rendering(tmp_path):
    out = await _render(tmp_path, parallax_25d_enabled=False)
    assert out["path"] is None
    assert out["fallback_reason"] == ps.DISABLED
    assert not (tmp_path / "out.mp4").exists()


async def test_missing_depth_map_declines_visibly(tmp_path):
    out = await _render(tmp_path, depth=False)
    assert out["path"] is None and out["fallback_reason"] == ps.NO_DEPTH


async def test_nonexistent_depth_path_declines_visibly(tmp_path):
    plate = _plate(tmp_path / "plate.png")
    out = await ps.render_motion_clip(
        image_path=str(plate), depth_map_path=str(tmp_path / "gone.png"),
        samples=MOVING, duration=0.2, fps=25, out_path=tmp_path / "o.mp4",
        overscan_margin=0.05, displacement_frac=0.02, layer_ratios={},
        settings=_settings(tmp_path),
    )
    assert out["path"] is None and out["fallback_reason"] == ps.NO_DEPTH


async def test_empty_trajectory_declines(tmp_path):
    out = await _render(tmp_path, samples=[])
    assert out["path"] is None and out["fallback_reason"] == ps.RENDER_FAILED


async def test_depth_warp_renders_and_validates(tmp_path):
    out = await _render(tmp_path)
    assert out["renderer"] == "depth_warp"
    assert out["path"] == str(tmp_path / "out.mp4")
    assert out["fallback_reason"] is None
    assert out["probe"] == {
        "width": ps.COMP_W, "height": ps.COMP_H, "codec_name": "h264",
        "pix_fmt": "yuv420p", "frames": len(MOVING), "fps": 25.0,
    }


async def test_depthflow_enabled_without_runtime_degrades_to_depth_warp(tmp_path, caplog):
    """AC9: an unconfigured DepthFlow must never look like a DepthFlow success."""
    out = await _render(tmp_path, depthflow_enabled=True, depthflow_python="/nope/python")
    assert out["renderer"] == "depth_warp"
    assert "depthflow_enabled but the runtime is not configured" in caplog.text


async def test_depthflow_backend_failure_falls_through_to_depth_warp(tmp_path, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("GL context died")

    monkeypatch.setattr(ps, "_render_depthflow", boom)
    monkeypatch.setattr(ps, "depthflow_available", lambda s: True)
    out = await _render(tmp_path, depthflow_enabled=True, depthflow_python="/bin/sh")
    assert out["renderer"] == "depth_warp"


async def test_every_renderer_failing_reports_a_reason_and_no_path(tmp_path, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("nope")

    monkeypatch.setattr(ps, "_render_depth_warp", boom)
    out = await _render(tmp_path)
    assert out["path"] is None
    assert out["fallback_reason"] == ps.RENDER_FAILED


async def test_timeout_is_classified_distinctly(tmp_path, monkeypatch):
    async def slow(*a, **kw):
        raise asyncio.TimeoutError

    monkeypatch.setattr(ps, "_render_depth_warp", slow)
    out = await _render(tmp_path)
    assert out["fallback_reason"] == ps.TIMEOUT


async def test_missing_runtime_is_classified_distinctly(tmp_path, monkeypatch):
    async def gone(*a, **kw):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(ps, "_render_depth_warp", gone)
    assert (await _render(tmp_path))["fallback_reason"] == ps.UNAVAILABLE


async def test_headless_gl_is_classified_distinctly(tmp_path, monkeypatch):
    async def nogl(*a, **kw):
        raise ConnectionError("no EGL display")

    monkeypatch.setattr(ps, "_render_depth_warp", nogl)
    assert (await _render(tmp_path))["fallback_reason"] == ps.HEADLESS_GL


async def test_empty_output_is_malformed_not_a_success(tmp_path, monkeypatch):
    async def nothing(image, depth, samples, fps, out, margin):
        out.write_bytes(b"")

    monkeypatch.setattr(ps, "_render_depth_warp", nothing)
    out = await _render(tmp_path)
    assert out["fallback_reason"] == ps.MALFORMED_OUTPUT
    assert not (tmp_path / "out.mp4").exists()


async def test_wrong_geometry_fails_validation_and_is_not_promoted(tmp_path, monkeypatch):
    """AC5: FFprobe is the gate. A 320x180 clip must never reach the assembler."""
    async def small(image, depth, samples, fps, out, margin):
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=red:s=320x180:r={fps}",
            "-frames:v", str(len(samples)), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    monkeypatch.setattr(ps, "_render_depth_warp", small)
    out = await _render(tmp_path)
    assert out["fallback_reason"] == ps.VALIDATION_FAILED
    assert not (tmp_path / "out.mp4").exists()


async def test_probe_rejects_a_truncated_clip(tmp_path):
    """Frame count is part of the contract: a short clip is a jump cut later."""
    clip = tmp_path / "short.mp4"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=red:s={ps.COMP_W}x{ps.COMP_H}:r=25",
        "-frames:v", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    assert (await ps.probe_clip(clip, frames=3, fps=25))["frames"] == 3
    with pytest.raises(ValueError, match="output contract violated"):
        await ps.probe_clip(clip, frames=25, fps=25)


# ── Cache, provenance, atomicity (AC10) ──────────────────────────────────────


async def test_valid_pair_is_a_cache_hit_with_zero_rendering(tmp_path, monkeypatch):
    first = await _render(tmp_path)
    assert not first["cached"]

    async def must_not_run(*a, **kw):
        raise AssertionError("re-rendered a valid cached clip")

    monkeypatch.setattr(ps, "_render_depth_warp", must_not_run)
    second = await _render(tmp_path)
    assert second["cached"] and second["renderer"] == "depth_warp"
    assert second["probe"] == first["probe"]


async def test_sidecar_records_the_full_provenance_contract(tmp_path):
    await _render(tmp_path)
    meta = json.loads((tmp_path / "out.json").read_text())
    for key in (
        "image_sha256", "depth_sha256", "adapter_version", "depth_edge_version",
        "renderer", "trajectory_sha256", "frames", "duration", "fps", "geometry",
        "displacement_frac", "far_gain", "overscan_margin", "layer_ratios",
        "archetype", "k", "clip_bytes", "probe",
    ):
        assert key in meta, key
    assert meta["layer_ratios"] == {"far": 0.6, "mid": 0.7, "near": 0.8}


async def test_a_changed_trajectory_invalidates_the_clip(tmp_path):
    await _render(tmp_path)
    other = [(t, x * 1.5, y, r, z) for t, x, y, r, z in MOVING]
    assert not (await _render(tmp_path, samples=other))["cached"]


async def test_a_changed_depth_map_invalidates_the_clip(tmp_path):
    await _render(tmp_path)
    other = _depth(tmp_path / "depth2.png", split=False)  # a genuinely different map
    assert not (await _render(tmp_path, depth_path=str(other)))["cached"]


async def test_legacy_clip_without_a_sidecar_is_a_miss(tmp_path):
    (tmp_path / "out.mp4").write_bytes(b"not really a clip")
    out = await _render(tmp_path)
    assert not out["cached"] and out["renderer"] == "depth_warp"


@pytest.mark.parametrize("body", ["[]", "null", "{}", '{"probe": 5}', "not json"])
def test_malformed_sidecars_are_misses(tmp_path, body):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    (tmp_path / "c.json").write_text(body)
    assert ps.verify_clip(clip, {"renderer": "depth_warp"}) is None


def test_tmp_artifacts_are_never_cache_hits(tmp_path):
    clip = tmp_path / "c.mp4.tmp"
    clip.write_bytes(b"x")
    assert ps.verify_clip(clip, {}) is None


def test_a_clip_whose_bytes_changed_is_a_miss(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"1234")
    (tmp_path / "c.json").write_text(json.dumps({"probe": {"width": 1}, "clip_bytes": 4}))
    assert ps.verify_clip(clip, {}) == {"width": 1}
    clip.write_bytes(b"12345")
    assert ps.verify_clip(clip, {}) is None


async def test_a_failed_render_never_overwrites_a_valid_clip(tmp_path, monkeypatch):
    """AC10's hardest guarantee: yesterday's good clip survives today's failure."""
    good = await _render(tmp_path)
    original = (tmp_path / "out.mp4").read_bytes()

    async def boom(*a, **kw):
        raise RuntimeError("render blew up")

    monkeypatch.setattr(ps, "_render_depth_warp", boom)
    # A different trajectory, so the cache does NOT answer and the renderer runs.
    out = await _render(tmp_path, samples=[(t, x * 2, y, r, z) for t, x, y, r, z in MOVING])
    assert out["path"] is None
    assert (tmp_path / "out.mp4").read_bytes() == original
    assert ps.verify_clip(Path(good["path"]), json.loads((tmp_path / "out.json").read_text()))


async def test_no_tmp_files_are_left_behind(tmp_path, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("x")

    monkeypatch.setattr(ps, "_render_depth_warp", boom)
    await _render(tmp_path)
    assert not list(tmp_path.glob("*.tmp*"))


# ── DepthFlow runtime contract (AC5, AC11) ───────────────────────────────────


def test_depthflow_availability_needs_both_halves(tmp_path):
    assert not ps.depthflow_available(_settings(tmp_path, depthflow_python=""))
    assert not ps.depthflow_available(_settings(tmp_path, depthflow_python="/nonexistent"))
    assert ps.depthflow_available(_settings(tmp_path, depthflow_python="/bin/sh"))


def test_depthflow_runner_ships_in_the_repo_and_imports_nothing_from_yt_flow():
    """AGPL isolation is structural: the runner executes under a DIFFERENT
    interpreter, so importing yt_flow would pull AGPL deps into this graph."""
    assert ps.DEPTHFLOW_RUNNER.is_file()
    source = ps.DEPTHFLOW_RUNNER.read_text()
    # No import of the app package — mentions in prose are fine, an import is not.
    assert "import yt_flow" not in source and "from yt_flow" not in source


def test_depthflow_is_not_a_project_dependency():
    """AC11: DepthFlow (AGPL-3.0) must stay an external runtime, never a
    yt.flow dependency — that is the whole compliance decision."""
    pyproject = Path("pyproject.toml").read_text().lower()
    assert "depthflow" not in pyproject
    assert "shaderflow" not in pyproject
