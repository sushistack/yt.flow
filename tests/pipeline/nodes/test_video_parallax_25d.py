"""Tests for Story 11.5's video-side integration: the shared motion seam, the
layered card parallax, and the visible fallback ladder.

Offline: the 2.5D renderer is a fake injected callable, ffmpeg is captured not
run. What is pinned here is invariants, not call shapes — no primary-path
zoompan, no double camera stage, closed 0.60-0.80 layer ratios, full excursion
on-frame, all four render branches on one seam, and byte-identical legacy output
when the switch is off.
"""

import dataclasses
import math
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from yt_flow.pipeline.nodes import camera_path as cp
from yt_flow.pipeline.nodes import video
from yt_flow.pipeline.nodes.video import EffectSpec

FPS = video.FPS


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_injected_renderer():
    """Every test starts from "no renderer wired", and none leaks into the next."""
    before = video._motion_renderer
    video.inject_motion_renderer(None)
    yield
    video.inject_motion_renderer(before)


@pytest.fixture
def assets(tmp_path):
    image = tmp_path / "bg.png"
    Image.new("RGB", (1920, 1080), (7, 7, 7)).save(image)
    depth = tmp_path / "bg.depth.png"
    Image.new("L", (1920, 1080), 128).save(depth)
    clip = tmp_path / "motion.mp4"
    clip.write_bytes(b"fake clip bytes")
    card = tmp_path / "card.png"
    Image.new("RGBA", (832, 1216), (255, 0, 0, 255)).save(card)
    return SimpleNamespace(image=str(image), depth=str(depth), clip=str(clip), card=str(card))


def _shot(assets, movement="push_in", *, depth=True):
    shot = {
        "shot_id": "S001", "sentence_indices": [0], "image_prompt": "p",
        "negative_prompt": "n", "camera_angle": None, "camera_movement": movement,
        "image_path": assets.image, "cast": [], "location_key": None,
    }
    if depth:
        shot["depth_map_path"] = assets.depth
    return shot


def _settings_ns(tmp_path, **kw):
    base = dict(parallax_25d_enabled=True, parallax_displacement_frac=0.02,
                character_idle_motion_enabled=True,
                background_camera_motion_enabled=True)
    base.update(kw)
    return SimpleNamespace(**base)


def _fake_renderer(assets, *, path=True, renderer="depth_warp", reason=None, captured=None):
    async def render(**kw):
        if captured is not None:
            captured.append(kw)
        return {
            "path": assets.clip if path else None,
            "renderer": renderer if path else None,
            "cached": False, "latency_ms": 42,
            "fallback_reason": reason,
        }

    return render


async def _motion(monkeypatch, tmp_path, assets, *, movement="push_in", depth=True,
                  renderer=None, k=0, trauma=0.0, duration=4.0, **settings_kw):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, **settings_kw))
    if renderer is not None:
        video.inject_motion_renderer(renderer)
    return await video.build_motion_source(
        _shot(assets, movement, depth=depth), duration,
        k=k, trauma=trauma, motion_dir=tmp_path / "motion",
        parallax_enabled=True, camera_shake="SHAKE",
    )


# ── AC8: one seam, four branches ─────────────────────────────────────────────


async def test_no_renderer_injected_is_the_legacy_zoompan_path(monkeypatch, tmp_path, assets):
    """AC9 kill switch / no wiring: byte-identical to pre-11.5."""
    m = await _motion(monkeypatch, tmp_path, assets)
    assert m.renderer == "legacy"
    assert m.is_clip is False
    assert m.bg_chain == video._zoompan_filter(m.spec, 4.0)
    assert m.bg_input == ["-loop", "1", "-framerate", str(FPS), "-i", assets.image]
    assert m.camera_shake == "SHAKE"      # 11.3's stage still applies
    assert m.parallax_enabled is True     # 7.3's card coupling still applies
    assert m.fallback_reason is None      # not a degradation, a configuration


async def test_successful_render_replaces_zoompan_entirely(monkeypatch, tmp_path, assets):
    """AC5: primary background motion does not call _zoompan_filter."""
    m = await _motion(monkeypatch, tmp_path, assets, renderer=_fake_renderer(assets))
    assert m.renderer == "depth_warp"
    assert m.is_clip is True
    assert m.bg_chain == "null"
    assert "zoompan" not in m.bg_chain
    assert m.bg_input == ["-i", assets.clip]
    assert "-loop" not in m.bg_input  # the clip carries its own frame count


async def test_2d5_path_owns_camera_motion_exactly_once(monkeypatch, tmp_path, assets):
    """AC7: no post-composite shake, no 7.3 macro parallax on top of the clip."""
    m = await _motion(monkeypatch, tmp_path, assets, renderer=_fake_renderer(assets), trauma=0.8)
    assert m.camera_shake == ""
    assert m.parallax_enabled is False


@pytest.mark.parametrize("cards", [[], [{"depth": "mid", "path": "c.png"}]])
async def test_all_four_branches_read_the_same_seam(monkeypatch, tmp_path, assets, cards):
    """AC8: fast x {cards, bg-only} and multi-clip x {cards, bg-only} — four
    branches, one MotionSource. Captured ffmpeg args must reference the clip and
    never zoompan on any of them."""
    calls = []

    async def fake_ffmpeg(*args):
        calls.append(args)
        (Path(args[-1])).write_bytes(b"seg")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    sub = tmp_path / "s.srt"
    sub.write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n")
    aud = tmp_path / "a.wav"
    aud.write_bytes(b"RIFF")
    if cards:
        cards = [{**cards[0], "path": assets.card}]

    video.inject_motion_renderer(_fake_renderer(assets))
    m = await video.build_motion_source(
        _shot(assets), 4.0, k=0, trauma=0.0, motion_dir=tmp_path / "motion",
        parallax_enabled=True, camera_shake="",
    )
    await video._render_scene_fast(
        m, 4.0, tmp_path / "fast.mp4", 1, cards=cards, mood="dread",
        audio_path=str(aud), subtitle_path=str(sub), sound_design_enabled=False,
        post_fx_enabled=False, include_stinger=True, composite_harmonization_tier=0,
    )
    await video._compose_shot_clip(
        _shot(assets), m, 4.0, tmp_path / "shot.mp4", cards=cards, mood=None,
        composite_harmonization_tier=0,
    )
    assert len(calls) == 2
    for args in calls:
        joined = " ".join(args)
        assert assets.clip in joined
        assert "zoompan" not in joined


# ── AC9: the visible fallback ladder ─────────────────────────────────────────


async def test_declined_render_falls_back_and_records_the_reason(monkeypatch, tmp_path, assets, caplog):
    counts: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    video.inject_motion_renderer(_fake_renderer(assets, path=False, reason="no_depth_map"))
    m = await video.build_motion_source(
        _shot(assets, depth=False), 4.0, k=0, trauma=0.0, motion_dir=tmp_path / "m",
        parallax_enabled=True, camera_shake="SHAKE", renderer_counts=counts,
    )
    assert m.renderer == "legacy"
    assert m.fallback_reason == "no_depth_map"
    assert m.camera_shake == "SHAKE"   # legacy path keeps 11.3's stage
    assert counts == {"fallback_no_depth_map": 1, "legacy": 1}
    assert "fell back to legacy zoompan (no_depth_map)" in caplog.text


async def test_renderer_exception_is_shot_local_not_stage_fatal(monkeypatch, tmp_path, assets, caplog):
    async def boom(**kw):
        raise RuntimeError("adapter exploded")

    counts: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    video.inject_motion_renderer(boom)
    m = await video.build_motion_source(
        _shot(assets), 4.0, k=0, trauma=0.0, motion_dir=tmp_path / "m",
        parallax_enabled=True, camera_shake="", renderer_counts=counts,
    )
    assert m.renderer == "legacy"
    assert counts["fallback_renderer_exception"] == 1
    assert "adapter exploded" in caplog.text


async def test_renderer_counts_tally_successes_and_latency(monkeypatch, tmp_path, assets):
    counts: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    video.inject_motion_renderer(_fake_renderer(assets))
    for k in range(3):
        await video.build_motion_source(
            _shot(assets), 4.0, k=k, trauma=0.0, motion_dir=tmp_path / "m",
            parallax_enabled=True, camera_shake="", renderer_counts=counts,
        )
    assert counts["depth_warp"] == 3
    assert counts["latency_ms"] == 126
    assert "legacy" not in counts


# ── AC4/AC6: what the renderer is actually asked for ─────────────────────────


async def test_renderer_receives_a_capped_deterministic_trajectory(monkeypatch, tmp_path, assets):
    captured: list = []
    await _motion(
        monkeypatch, tmp_path, assets, movement="shake", trauma=0.8, k=5,
        renderer=_fake_renderer(assets, captured=captured),
    )
    kw = captured[0]
    assert kw["fps"] == FPS
    assert len(kw["samples"]) == round(4.0 * FPS)
    assert kw["displacement_frac"] == 0.02
    assert kw["layer_ratios"] == video._LAYER_PARALLAX_RATIO
    assert kw["depth_map_path"] == assets.depth
    assert kw["provenance_extra"]["camera_path_version"] == cp.CAMERA_PATH_VERSION
    assert kw["provenance_extra"]["k"] == 5
    x_max = max(abs(s[1]) for s in kw["samples"])
    y_max = max(abs(s[2]) for s in kw["samples"])
    assert x_max <= 0.02 + 1e-9 and y_max <= 0.02 + 1e-9


@pytest.mark.parametrize("frac,expected", [(0.0, 0.01), (0.5, 0.03), (0.02, 0.02)])
async def test_configured_displacement_is_clamped_into_the_ac6_band(
    monkeypatch, tmp_path, assets, frac, expected,
):
    captured: list = []
    await _motion(
        monkeypatch, tmp_path, assets, renderer=_fake_renderer(assets, captured=captured),
        parallax_displacement_frac=frac,
    )
    assert captured[0]["displacement_frac"] == expected


async def test_overscan_margin_is_shared_with_the_renderer(monkeypatch, tmp_path, assets):
    """One owner: the margin the plate is scaled up by is the margin the card's
    floor tracking assumes. Two numbers here means feet leaving the floor."""
    captured: list = []
    m = await _motion(
        monkeypatch, tmp_path, assets, movement="shake", trauma=0.5,
        renderer=_fake_renderer(assets, captured=captured),
    )
    assert m.trajectory is not None
    assert captured[0]["overscan_margin"] == pytest.approx(m.trajectory.margin)


# ── AC7: layered card parallax ───────────────────────────────────────────────


def test_layer_ratios_are_a_closed_server_owned_band():
    assert video._LAYER_PARALLAX_RATIO == {"far": 0.60, "mid": 0.70, "near": 0.80}
    assert all(0.60 <= r <= 0.80 for r in video._LAYER_PARALLAX_RATIO.values())
    # Nearer layers travel further — that ordering IS the depth cue.
    r = video._LAYER_PARALLAX_RATIO
    assert r["far"] < r["mid"] < r["near"]


def test_legacy_motion_emits_no_layer_terms():
    m = video._legacy_motion(
        {"image_path": "x.png"}, EffectSpec("pan-right", 1.0, 1.15), 4.0,
        parallax_enabled=True, camera_shake="",
    )
    assert all(m.layer_terms(d) is None for d in ("far", "mid", "near"))


async def test_layer_terms_scale_with_depth_and_share_the_plate_direction(
    monkeypatch, tmp_path, assets,
):
    m = await _motion(
        monkeypatch, tmp_path, assets, movement="drift",
        renderer=_fake_renderer(assets),
    )
    assert m.trajectory is not None
    peaks = {}
    for depth in ("far", "mid", "near"):
        x_term, _ = m.layer_terms(depth)
        peaks[depth] = max(abs(_eval(x_term, t / FPS)) for t in range(100))
    assert peaks["far"] < peaks["mid"] < peaks["near"]
    # Same sign at every sampled instant: cards move WITH the plate, never against.
    x_far, _ = m.layer_terms("far")
    x_near, _ = m.layer_terms("near")
    for t in range(0, 100, 7):
        a, b = _eval(x_far, t / FPS), _eval(x_near, t / FPS)
        assert a == 0 or b == 0 or (a > 0) == (b > 0)


async def test_full_layer_excursion_stays_inside_the_reserved_box(
    monkeypatch, tmp_path, assets,
):
    """AC7's proof obligation: the FULL combined excursion cannot clip the card
    or expose a border. The motion-safe box reserves _MACRO_PAN_RESERVE_PX per
    side, so the worst layer term over every archetype x depth x trauma x frame
    must fit inside it.

    Note the two different numbers. _LAYER_MAX_PX (46.08px) is the ANALYTIC
    ceiling — the AC6 displacement cap times the widest layer ratio — and that is
    what the box reserves, because the reserve has to hold before any trajectory
    is sampled. The observed worst is lower (~29px here) because the fBm bands and
    the trauma envelope never all peak on the same frame. Asserting the observed
    value against the ceiling would be asserting a coincidence; the invariant is
    that the observed value never ESCAPES the reserve, and that the reserve is
    the analytic ceiling by construction.
    """
    worst = 0.0
    for movement in ("push_in", "pull_back", "drift", "locked", "shake"):
        for trauma in (0.0, 0.8):
            m = await _motion(
                monkeypatch, tmp_path, assets, movement=movement, trauma=trauma,
                renderer=_fake_renderer(assets), parallax_displacement_frac=0.03,
            )
            for depth in ("far", "mid", "near"):
                x_term, y_term = m.layer_terms(depth)
                for t in range(100):
                    worst = max(
                        worst, abs(_eval(x_term, t / FPS)), abs(_eval(y_term, t / FPS)),
                    )
    assert worst <= video._MACRO_PAN_RESERVE_PX + 1e-6
    # The reserve IS the analytic ceiling, derived not eyeballed.
    assert video._LAYER_MAX_PX == pytest.approx(
        cp.DISPLACEMENT_MAX * video.COMP_W * max(video._LAYER_PARALLAX_RATIO.values())
    )
    # ...and it is not absurdly slack: a real trajectory uses most of it, so the
    # box is not shrinking every card to reserve room nothing ever needs.
    assert worst > video._MACRO_PAN_RESERVE_PX * 0.5


def test_ground_clamp_reserves_the_same_pan_budget_as_the_card_box():
    """[review fix] AC7's excursion proof has TWO anchors, not one.

    CHAR_MAX_W/H reserve _MACRO_PAN_RESERVE_PX for a CENTRE-anchored card, which
    spends it half per side. A ground-anchored card (Story 8.16, the production
    path) spends the whole thing downward from _GROUND_Y_MAX, so the clamp has to
    reserve the same budget. It used to reserve 7.3's 12px, leaving the analytic
    worst case 34.1px past the bottom edge at 3% displacement (18.7px at the
    shipped 2%).

    Measured sampled trajectories only reached ~29px of the 46.08px ceiling, so
    the old clamp survived by ~5px of coincidence rather than clipping outright —
    which is precisely why this asserts the ANALYTIC reserve. This module's whole
    lineage (CHAR_MAX_W's "by construction, not by eyeball") is that a bound
    holding by luck is a bound not held. ``…card_bottom_never_leaves_the_frame``
    below is the observed-value companion, not the proof.
    """
    assert video._GROUND_Y_MAX * video.COMP_H + video._MAX_MOTION_Y_PX \
        + video._LAYER_MAX_PX <= video.COMP_H + 1e-9


async def test_ground_anchored_card_bottom_never_leaves_the_frame(
    monkeypatch, tmp_path, assets,
):
    """The same obligation, proven on the real emitted expression instead of the
    constants: floor tracking + idle bob + layer parallax, worst frame, worst
    archetype, at the top of the AC6 band.

    ``k`` walks ``_PAN_POOL`` so the DOWNWARD pan directions are covered — a
    horizontal-only sweep sees a ~9px y layer term and proves nothing about the
    bottom edge."""
    worst = 0.0
    cases = [("drift", k) for k in range(len(video._PAN_POOL))]
    cases += [(mv, 0) for mv in ("push_in", "pull_back", "shake")]
    for movement, k in cases:
        m = await _motion(
            monkeypatch, tmp_path, assets, movement=movement, trauma=0.8, k=k,
            renderer=_fake_renderer(assets), parallax_displacement_frac=0.03,
        )
        chain, _ = video._build_card_chain(
            m,
            [{"depth": "near", "path": assets.card, "position": "center",
              "ground_y": video._GROUND_Y_MAX, "motion_style": "sway"}],
            4.0, None, composite_harmonization_tier=0,
        )
        overlay = next(p for p in chain if "overlay=" in p)
        y_expr = re.search(r"y='([^']+)'", overlay).group(1)
        # `- overlay_h` puts the card's TOP at y; dropping it reads the bottom edge.
        bottom = y_expr.replace("main_h", "1080").replace("-overlay_h", "")
        worst = max(worst, max(_eval(bottom, t / FPS) for t in range(100)))
    assert worst <= video.COMP_H + 1e-6, f"card bottom reached {worst}px of 1080"


async def test_contact_shadow_rides_the_layer_translation(monkeypatch, tmp_path, assets):
    """[review fix] The shadow is the card's own footprint, so it belongs to the
    card's LAYER. Left pinned it slid up to 30.7px out from under the character at
    the shipped 2% displacement — the detached puddle 8.16's shadow_y tracking
    exists to prevent."""
    m = await _motion(
        monkeypatch, tmp_path, assets, movement="drift", renderer=_fake_renderer(assets),
    )
    chain, _ = video._build_card_chain(
        m, [{"depth": "near", "path": assets.card, "ground_y": 0.85, "card_key": "K"}],
        4.0, "dread", composite_harmonization_tier=1,
    )
    shadow = next(p for p in chain if "[sh0]overlay=" in p)
    x_term, y_term = m.layer_terms("near")
    assert x_term in shadow and y_term in shadow


def test_legacy_contact_shadow_is_unchanged(assets):
    """The shadow fix is scoped to the 2.5D path — legacy keeps x=0."""
    m = video._legacy_motion(
        {"image_path": assets.image}, EffectSpec("pan-right", 1.0, 1.15), 4.0,
        parallax_enabled=True, camera_shake="",
    )
    chain, _ = video._build_card_chain(
        m, [{"depth": "near", "path": assets.card, "ground_y": 0.85, "card_key": "K"}],
        4.0, "dread", composite_harmonization_tier=1,
    )
    shadow = next(p for p in chain if "[sh0]overlay=" in p)
    assert "overlay=x='0':y='" in shadow


async def test_layer_terms_reach_the_overlay_and_replace_the_73_macro_pan(
    monkeypatch, tmp_path, assets,
):
    m = await _motion(
        monkeypatch, tmp_path, assets, movement="pan-right",
        renderer=_fake_renderer(assets),
    )
    chain, _ = video._build_card_chain(
        m, [{"depth": "near", "path": assets.card}], 4.0, None,
        composite_harmonization_tier=0,
    )
    overlay = next(p for p in chain if "overlay=" in p)
    x_term, _ = m.layer_terms("near")
    assert x_term in overlay
    # 7.3's macro pan is `(<signed px>)*t/<duration>` — must not co-exist.
    assert not re.search(r"\(-?\d+\.?\d*\)\*t/4\.0", overlay)


def test_legacy_path_keeps_the_73_macro_pan(assets):
    """The replacement is scoped to the 2.5D path only (AC7's last clause)."""
    m = video._legacy_motion(
        {"image_path": assets.image}, EffectSpec("pan-right", 1.0, 1.15), 4.0,
        parallax_enabled=True, camera_shake="",
    )
    chain, _ = video._build_card_chain(
        m, [{"depth": "near", "path": assets.card}], 4.0, None,
        composite_harmonization_tier=0,
    )
    overlay = next(p for p in chain if "overlay=" in p)
    assert re.search(r"\*t/4\.0", overlay)


# ── AC7/8.16 interaction: floor tracking on the 2.5D path ────────────────────


def test_legacy_ground_expr_is_8_16s_zoompan_tracker(assets):
    spec = EffectSpec("in-center", 1.0, 1.15)
    m = video._legacy_motion(
        {"image_path": assets.image}, spec, 4.0, parallax_enabled=True, camera_shake="",
    )
    assert m.ground_expr(0.85, 4.0) == video.ground_y_expr(spec, 4.0, 0.85)


async def test_2d5_ground_expr_tracks_zoom_and_omits_translation(
    monkeypatch, tmp_path, assets,
):
    """The card's translation is already in layer_terms; adding it to the floor
    expression too would move the card twice (AC7's "exactly once")."""
    m = await _motion(
        monkeypatch, tmp_path, assets, movement="push_in",
        renderer=_fake_renderer(assets),
    )
    expr = m.ground_expr(0.85, 4.0)
    assert "zoompan" not in expr
    assert m.trajectory is not None and m.trajectory.zoom_expr in expr
    # A floor below centre must descend as the push-in progresses, and never
    # break the motion-safe ceiling.
    start = _eval(expr.replace("main_h", "1080").replace("-overlay_h", ""), 0.0)
    end = _eval(expr.replace("main_h", "1080").replace("-overlay_h", ""), 3.9)
    assert end > start
    assert end <= 1080 * video._GROUND_Y_MAX + 1e-6


# ── AC10: trace metadata ─────────────────────────────────────────────────────


def test_trace_metadata_carries_the_2d5_block(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        video, "get_client",
        lambda: SimpleNamespace(update_current_span=lambda **kw: captured.update(kw["metadata"])),
    )
    video._record_trace(
        run_id="r", scene_count=1, latency_ms=1,
        renderer_counts={"depth_warp": 5, "legacy": 2, "fallback_no_depth_map": 2,
                         "cache_hit": 1, "latency_ms": 900},
        parallax_25d_enabled=True, displacement_frac=0.02,
    )
    block = captured["parallax_25d"]
    assert block["enabled"] is True
    assert block["displacement_frac"] == 0.02
    assert block["layer_ratios"] == video._LAYER_PARALLAX_RATIO
    assert block["renderer_counts"]["depth_warp"] == 5
    assert block["renderer_counts"]["fallback_no_depth_map"] == 2
    assert block["renderer_counts"]["cache_hit"] == 1


def test_trace_metadata_reports_the_block_even_when_nothing_rendered(monkeypatch):
    """A run with zero 2.5D shots must still say so — an absent key reads as
    "feature not in this build", which is the ambiguity AC9 forbids."""
    captured: dict = {}
    monkeypatch.setattr(
        video, "get_client",
        lambda: SimpleNamespace(update_current_span=lambda **kw: captured.update(kw["metadata"])),
    )
    video._record_trace(run_id="r", scene_count=1, latency_ms=1)
    assert captured["parallax_25d"]["renderer_counts"] == {}
    assert captured["parallax_25d"]["enabled"] is False


# ── AC4: expression/sample parity at the integration level ───────────────────


async def test_card_expressions_and_plate_samples_are_one_trajectory(
    monkeypatch, tmp_path, assets,
):
    """The plate is warped from SAMPLES, the cards move on EXPRESSIONS. If those
    two diverge, cards slide against their own background — so the card term at
    ratio 1.0 must equal the sampled plate displacement at the same instant."""
    captured: list = []
    m = await _motion(
        monkeypatch, tmp_path, assets, movement="shake", trauma=0.6, k=4,
        renderer=_fake_renderer(assets, captured=captured),
    )
    samples = captured[0]["samples"]
    assert m.trajectory is not None
    for i in (0, 7, 33, len(samples) - 1):
        t, sx, sy, _, _ = samples[i]
        assert _eval(m.trajectory.x_expr, t) == pytest.approx(sx, abs=1e-9)
        assert _eval(m.trajectory.y_expr, t) == pytest.approx(sy, abs=1e-9)


async def test_zoom_expression_matches_the_sampled_zoom(monkeypatch, tmp_path, assets):
    captured: list = []
    m = await _motion(
        monkeypatch, tmp_path, assets, movement="push_in", k=2,
        renderer=_fake_renderer(assets, captured=captured),
    )
    samples = captured[0]["samples"]
    assert m.trajectory is not None
    for i in (0, 50, len(samples) - 1):
        t, _, _, _, sz = samples[i]
        assert _eval(m.trajectory.zoom_expr, t) == pytest.approx(sz, abs=1e-9)


def _eval(expr: str, t: float) -> float:
    """Evaluate a generated ffmpeg expression in Python (see the same helper in
    test_camera_path.py — the generated subset is valid Python)."""
    return float(eval(expr, {  # noqa: S307 — fixed, code-generated expressions
        "__builtins__": {},
        "sin": math.sin, "floor": math.floor, "pow": pow, "max": max, "min": min, "t": t,
    }))


# ── live ffmpeg: the seam actually renders ────────────────────────────────────


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_2d5_card_filtergraph_is_accepted_by_real_ffmpeg(monkeypatch, tmp_path, assets):
    """The layer terms and the 2.5D ground expression are strings ffmpeg has to
    parse; only real ffmpeg proves the filtergraph is well-formed."""
    clip = tmp_path / "real.mp4"
    proc = await video.asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        f"color=c=navy:s={video.COMP_W}x{video.COMP_H}:r={FPS}",
        "-frames:v", str(2 * FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
        stdout=video.asyncio.subprocess.DEVNULL, stderr=video.asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    assets.clip = str(clip)

    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    video.inject_motion_renderer(_fake_renderer(assets))
    m = await video.build_motion_source(
        _shot(assets, "shake"), 2.0, k=1, trauma=0.7, motion_dir=tmp_path / "m",
        parallax_enabled=True, camera_shake="",
    )
    cards = [{"depth": "near", "path": assets.card, "position": "center",
              "ground_y": 0.85, "card_key": "K"}]
    out = tmp_path / "composited.mp4"
    await video._compose_shot_clip(
        _shot(assets, "shake"), m, 2.0, out, cards=cards, mood="dread",
        composite_harmonization_tier=1,
    )
    assert out.is_file() and out.stat().st_size > 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_legacy_seam_still_renders_after_the_refactor(tmp_path, assets):
    """AC8 regression: the legacy branch must survive the seam extraction."""
    m = video._legacy_motion(
        {"image_path": assets.image}, EffectSpec("in-center", 1.0, 1.15), 1.0,
        parallax_enabled=True, camera_shake="",
    )
    out = tmp_path / "legacy.mp4"
    await video._compose_shot_clip(
        _shot(assets), m, 1.0, out, cards=[], mood=None, composite_harmonization_tier=0,
    )
    assert out.is_file() and out.stat().st_size > 0


def test_motion_source_is_a_frozen_shaped_seam():
    """Every field a branch reads must exist on every MotionSource, so a branch
    cannot silently work on one path and AttributeError on the other."""
    fields = {f.name for f in dataclasses.fields(video.MotionSource)}
    assert fields == {
        "bg_input", "bg_chain", "spec", "camera_shake", "parallax_enabled",
        "trajectory", "renderer", "fallback_reason", "latency_ms", "cached",
    }
