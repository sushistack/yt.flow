"""Tests for src/yt_flow/pipeline/nodes/video.py (Story 1.9 + 1.9b).

No live FFmpeg / Langfuse: _run_ffmpeg and _record_trace are monkeypatched.
Covers: select_effect, zoompan filter, dip-to-black fade+concat join, happy/error paths,
observability, AD-1 layer guards, integration (skippable without ffmpeg+ffprobe).
"""

import asyncio
import json
import dataclasses
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import yt_flow.pipeline.nodes.character_motion as cm
import yt_flow.pipeline.nodes.video as video
from yt_flow.domain.state import PipelineState, SceneState, ShotData
from yt_flow.pipeline.nodes.color_grade import MOOD_GRADE_PARAMS
from yt_flow.pipeline.nodes.sound_design import DEFAULT_MOOD
from yt_flow.pipeline.nodes.video import (
    BLACK_HOLD_DURATION,
    FADE_DURATION,
    EffectSpec,
    _character_scale_filter,
    _character_spec,
    _character_zoom_filter,
    _join_with_fades,
    _overlay_filter,
    _validate_scene_assets,
    _zoompan_filter,
    select_effect,
    video_node,
)

_REAL_RECORD_TRACE = video._record_trace  # the autouse _silent_trace fixture below stubs this out


# ── Fixtures / helpers ────────────────────────────────────────────────────────


def _legacy_motion(image, spec, duration, *, shake="", bg_chain=None):
    """The legacy zoompan MotionSource (Story 11.5's AC9 final rung).

    These unit tests exercise the zoompan path directly, so they build the seam
    object rather than going through build_motion_source (which would need an
    injected renderer). `bg_chain` overrides the chain for callers that only care
    about the card side.
    """
    m = video._legacy_motion(
        {"image_path": str(image)}, spec, duration,
        parallax_enabled=False, camera_shake=shake,
    )
    return m if bg_chain is None else dataclasses.replace(m, bg_chain=bg_chain)


def _settings_ns(
    tmp_path, *, chapter_cards: bool = False, chapter_card_duration_sec: float = 1.75,
    sound_design_enabled: bool = False, post_fx_enabled: bool = False,
    parallax_enabled: bool = False, cc_attribution: bool = False,
    composite_harmonization_tier: int = 0, min_shot_clip_sec: float = 2.0,
    camera_noise_enabled: bool = False,
):
    # ponytail: fake settings default cards/sound-design/post-fx/parallax/
    # cc_attribution/composite_harmonization_tier OFF so pre-existing tests
    # (written before Story 5.1/7.1/7.2/7.3/5.20/8.7) don't need touching; the
    # real Settings() default is True (1 for the tier) — see
    # test_config_chapter_cards_default_true /
    # test_config_post_fx_enabled_default_true /
    # test_config_parallax_enabled_default_true / test_config_cc_attribution_default_true /
    # test_composite_harmonization_defaults.
    return SimpleNamespace(
        workspace_path=str(tmp_path),
        chapter_cards=chapter_cards,
        chapter_card_duration_sec=chapter_card_duration_sec,
        sound_design_enabled=sound_design_enabled,
        post_fx_enabled=post_fx_enabled,
        parallax_enabled=parallax_enabled,
        cc_attribution=cc_attribution,
        composite_harmonization_tier=composite_harmonization_tier,
        min_shot_clip_sec=min_shot_clip_sec,
        camera_noise_enabled=camera_noise_enabled,
        # Story 11.5: the 2.5D renderer is never injected in these tests, so the
        # kill-switch value only has to exist; build_motion_source takes the
        # legacy zoompan path either way.
        parallax_25d_enabled=False,
        parallax_displacement_frac=0.02,
    )


async def _fake_ffmpeg_ok(*args):
    """Creates the output file (last positional arg) and signals success."""
    # Last arg is always the output path for our call conventions
    Path(args[-1]).write_bytes(b"FAKE_MP4")
    return 0, ""


async def _fake_ffmpeg_fail(*args):
    return 1, "error: codec not found"


def _shot(
    image_path: str | None = None,
    camera_movement: str | None = None,
    *,
    shot_id: str = "S001",
    cast: list[dict] | None = None,
) -> ShotData:
    return {  # type: ignore[return-value]
        "shot_id": shot_id,
        "sentence_indices": [0],
        "image_prompt": "p",
        "negative_prompt": "n",
        "camera_angle": None,
        "camera_movement": camera_movement,
        "image_path": image_path,
        "cast": cast or [],
    }


def _card(
    path: str, *, card_key: str = "SCP-096", position: str = "center", depth: str = "near",
    pose: str = "standing", angle: str = "front", fallback: bool = False,
    motion_style: str = "breath", motion_energy: str = "medium",
    movement_mode: str = "anchored", movement_direction: str = "none", movement_pace: str = "slow",
) -> dict:
    """A resolved card dict, the shape resolve_cast_cards returns (Story 8.3
    Interfaces, Story 8.8 adds motion_style/motion_energy, Story 8.9 adds
    movement_mode/movement_direction/movement_pace)."""
    return {
        "card_key": card_key, "pose": pose, "angle": angle, "path": path,
        "fallback": fallback, "position": position, "depth": depth,
        "motion_style": motion_style, "motion_energy": motion_energy,
        "movement_mode": movement_mode, "movement_direction": movement_direction, "movement_pace": movement_pace,
    }


def _scene(
    scene_num: int,
    *,
    image: str | None = None,
    audio: str | None = None,
    subtitle: str | None = None,
    camera_movement: str | None = None,
    cast: list[dict] | None = None,
    audio_duration: float = 2.0,
    **over,
) -> SceneState:
    base: dict = {
        "scene_num": scene_num,
        "narration": f"narration {scene_num}",
        "shots": [_shot(image, camera_movement, cast=cast)],
        "audio_path": audio,
        "audio_duration": audio_duration,
        "word_timings": [],
        "subtitle_path": subtitle,
    }
    base.update(over)
    return base  # type: ignore[return-value]


def _state(scenes: list, run_id: str = "run-001", **over) -> PipelineState:
    base: dict = {
        "run_id": run_id,
        "scp_text": "SCP-173 test",
        "scenes": scenes,
        "video_path": None,
        "current_stage": "subtitle",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }
    base.update(over)
    return base  # type: ignore[return-value]


def _png_chunk(name: bytes, data: bytes) -> bytes:
    import struct
    import zlib
    crc = zlib.crc32(name + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)


def _make_png(color_type: int) -> bytes:
    """Minimal 1x1 PNG with the given color_type (2=RGB opaque, 6=RGBA)."""
    import struct
    import zlib
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, color_type, 0, 0, 0))
    raw = b"\x00\xff\x00\x00\x80" if color_type == 6 else b"\x00\xff\x80\x40"
    idat = _png_chunk(b"IDAT", zlib.compress(raw))
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


RGBA_CARD_BYTES = _make_png(6)
OPAQUE_CARD_BYTES = _make_png(2)


@pytest.fixture
def assets(tmp_path) -> SimpleNamespace:
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    subtitle = tmp_path / "scene.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n\n", encoding="utf-8")
    character = tmp_path / "character.png"
    character.write_bytes(RGBA_CARD_BYTES)
    character2 = tmp_path / "character2.png"
    character2.write_bytes(RGBA_CARD_BYTES)
    opaque_card = tmp_path / "opaque_card.png"
    opaque_card.write_bytes(OPAQUE_CARD_BYTES)
    return SimpleNamespace(
        image=str(image), audio=str(audio), subtitle=str(subtitle),
        character=str(character), character2=str(character2), opaque_card=str(opaque_card),
    )


@pytest.fixture(autouse=True)
def _silent_trace(monkeypatch):
    monkeypatch.setattr(video, "_record_trace", lambda **kw: None)


@pytest.fixture(autouse=True)
def _fake_which(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/ffmpeg")


# ── select_effect ─────────────────────────────────────────────────────────────


def test_select_effect_zoom_in_hint():
    shot = _shot(camera_movement="zoom in")
    spec = select_effect(shot, 0)
    assert spec.direction == "in-center"
    assert spec.end_zoom == pytest.approx(video.ZOOM_IN_MAX)


def test_select_effect_zoom_out_hint():
    shot = _shot(camera_movement="zoom out")
    spec = select_effect(shot, 0)
    assert spec.direction == "out-center"
    assert spec.start_zoom == pytest.approx(video.ZOOM_IN_MAX)
    assert spec.end_zoom == pytest.approx(1.0)


def test_select_effect_pan_left():
    shot = _shot(camera_movement="pan left")
    assert select_effect(shot, 0).direction == "pan-left"


def test_select_effect_pan_right():
    shot = _shot(camera_movement="pan right")
    assert select_effect(shot, 0).direction == "pan-right"


def test_select_effect_pan_up():
    shot = _shot(camera_movement="pan up")
    assert select_effect(shot, 0).direction == "pan-up"


def test_select_effect_pan_down():
    shot = _shot(camera_movement="pan down")
    assert select_effect(shot, 0).direction == "pan-down"


def test_select_effect_static_near_zero():
    shot = _shot(camera_movement="static")
    spec = select_effect(shot, 0)
    # static reuses zoompan path with near-zero drift
    assert spec.start_zoom == pytest.approx(1.0)
    assert spec.end_zoom == pytest.approx(1.005)


def test_select_effect_none_rotates_pool():
    """None/unknown hint rotates through pool; no two consecutive indices give same direction."""
    shot = _shot(camera_movement=None)
    directions = [select_effect(shot, i).direction for i in range(len(video._DIRECTION_POOL) + 1)]
    # No two consecutive entries should be identical
    for a, b in zip(directions, directions[1:]):
        assert a != b, f"consecutive same direction: {a}"


def test_select_effect_unknown_rotates_pool():
    shot = _shot(camera_movement="wiggle")  # unrecognized hint
    directions = [select_effect(shot, i).direction for i in range(len(video._DIRECTION_POOL))]
    # All directions come from the pool
    assert set(directions) == set(video._DIRECTION_POOL)


def test_select_effect_pool_wraps():
    """Indices beyond pool length still cycle correctly."""
    shot = _shot(camera_movement=None)
    pool = video._DIRECTION_POOL
    for i in range(len(pool) * 3):
        spec = select_effect(shot, i)
        assert spec.direction == pool[i % len(pool)]


@pytest.mark.parametrize("hint", ["pan  right", "pan\tright", " Pan Right "])
def test_select_effect_normalizes_internal_whitespace(hint):
    """Internal double-space/tab hints still honor the author's intent, not the pool."""
    assert select_effect(_shot(camera_movement=hint), 3).direction == "pan-right"



# ── select_effect: camera archetypes (Story 11.2) ─────────────────────────────


def test_select_effect_push_in_archetype():
    # Pre-existing _HINT_MAP coincidence, pinned by test per AC5.
    spec = select_effect(_shot(camera_movement="push_in"), 0)
    assert spec.direction == "in-center"
    assert spec.start_zoom == pytest.approx(1.0)
    assert spec.end_zoom == pytest.approx(video.ZOOM_IN_MAX)


def test_select_effect_pull_back_archetype():
    spec = select_effect(_shot(camera_movement="pull_back"), 0)
    assert spec.direction == "out-center"
    assert spec.start_zoom == pytest.approx(video.ZOOM_IN_MAX)
    assert spec.end_zoom == pytest.approx(1.0)


def test_select_effect_locked_archetype_micro_drift():
    # locked joins the "static" branch: 1.0 -> 1.005 micro drift.
    spec = select_effect(_shot(camera_movement="locked"), 0)
    assert spec.direction == "in-center"
    assert spec.start_zoom == pytest.approx(1.0)
    assert spec.end_zoom == pytest.approx(1.005)


def test_select_effect_drift_archetype_rotates_pan_subset():
    shot = _shot(camera_movement="drift")
    pan_pool = [d for d in video._DIRECTION_POOL if d.startswith("pan-")]
    for i in range(len(pan_pool) * 2):
        spec = select_effect(shot, i)
        assert spec.direction == pan_pool[i % len(pan_pool)]
        assert spec.end_zoom == pytest.approx(video.ZOOM_IN_MAX)  # pan keeps the zoom-in idiom


def test_select_effect_shake_archetype_placeholder_push():
    # Story 11.2 placeholder: in-center push until 11.3's fBm/trauma shake.
    # scene_index 1 so the round-robin fallback (pan-right) can't fake a pass.
    spec = select_effect(_shot(camera_movement="shake"), 1)
    assert spec.direction == "in-center"
    assert spec.end_zoom == pytest.approx(video.ZOOM_IN_MAX)


def test_select_effect_archetypes_deterministic():
    from yt_flow.domain.state import CAMERA_ARCHETYPES

    for arch in CAMERA_ARCHETYPES:
        a = select_effect(_shot(camera_movement=arch), 7)
        b = select_effect(_shot(camera_movement=arch), 7)
        assert a == b


# ── _zoompan_filter ───────────────────────────────────────────────────────────


def test_zoompan_filter_contains_zoompan():
    spec = EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    filt = _zoompan_filter(spec, duration=2.0)
    assert "zoompan" in filt


def test_zoompan_filter_contains_upscale():
    """Pre-scale=8000 jitter fix must be present. [Story 1.9b AC:1]"""
    spec = EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    filt = _zoompan_filter(spec, duration=2.0)
    assert "scale=8000" in filt


def test_zoompan_filter_correct_frame_count():
    spec = EffectSpec(direction="pan-right", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    filt = _zoompan_filter(spec, duration=4.0)
    expected_frames = round(4.0 * video.FPS)
    assert f"d={expected_frames}" in filt


def test_zoompan_filter_zoom_out_uses_conditional():
    """Zoom-out must use if(lte(zoom,1.0),...) workaround for stateful zoompan."""
    spec = EffectSpec(direction="out-center", start_zoom=video.ZOOM_IN_MAX, end_zoom=1.0)
    filt = _zoompan_filter(spec, duration=2.0)
    assert "if(lte(zoom,1.0)" in filt


def test_zoompan_filter_honors_spec_zoom_range():
    """[review:G] 'static' EffectSpec (1.0→1.005) must produce a subtle drift, not a
    full push-in to ZOOM_IN_MAX. The filter previously ignored start_zoom/end_zoom."""
    spec = select_effect(_shot(camera_movement="static"), 0)  # → 1.0→1.005 in-center
    filt = _zoompan_filter(spec, duration=2.0)
    assert "1.005" in filt                        # honors spec.end_zoom
    assert str(video.ZOOM_IN_MAX) not in filt      # not the hardcoded ZOOM_IN_MAX target


def test_zoom_in_max_within_recommended_range():
    """[Story 5.3 AC:1] Normal Ken Burns strength must sit in the visible-but-not
    -nauseating 1.08-1.15 band, strengthened from the pre-5.3 1.08 baseline."""
    assert 1.08 <= video.ZOOM_IN_MAX <= 1.15


def test_zoompan_filter_all_directions_build():
    """Every pool direction (including Story 5.3 diagonals) produces a valid filter."""
    for direction in video._DIRECTION_POOL:
        if direction == "out-center":
            spec = EffectSpec(direction=direction, start_zoom=video.ZOOM_IN_MAX, end_zoom=1.0)
        else:
            spec = EffectSpec(direction=direction, start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
        filt = _zoompan_filter(spec, duration=2.0)
        assert "zoompan" in filt
        assert "scale=8000" in filt


@pytest.mark.parametrize(
    ("direction", "x_expr", "y_expr"),
    [
        ("pan-up-right", "(iw-iw/zoom)*on/50", "(ih-ih/zoom)*on/50"),
        ("pan-up-left", "(iw-iw/zoom)*(1-on/50)", "(ih-ih/zoom)*on/50"),
        ("pan-down-right", "(iw-iw/zoom)*on/50", "(ih-ih/zoom)*(1-on/50)"),
        ("pan-down-left", "(iw-iw/zoom)*(1-on/50)", "(ih-ih/zoom)*(1-on/50)"),
    ],
)
def test_zoompan_filter_diagonal_has_expected_axis_expressions(direction, x_expr, y_expr):
    """[Story 5.3 AC:2] Each diagonal direction must animate the intended x/y pair."""
    spec = EffectSpec(direction=direction, start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    filt = _zoompan_filter(spec, duration=2.0)
    assert f":x='{x_expr}'" in filt
    assert f":y='{y_expr}'" in filt


# ── _join_with_fades (Story 5.16) ────────────────────────────────────────────


def _capture_filter(monkeypatch):
    """Patch video._run_ffmpeg to record each call's -filter_complex value."""
    captured: list[str] = []

    async def _capture(*args):
        args_list = list(args)
        if "-filter_complex" in args_list:
            captured.append(args_list[args_list.index("-filter_complex") + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _capture)
    return captured


async def test_join_with_fades_uses_concat_not_xfade(monkeypatch, tmp_path):
    """[AC:1,2] The join is plain concat — no xfade/acrossfade/adelay/amix anywhere."""
    segs = [
        (tmp_path / "s0.mp4", 3.0, 0.0, FADE_DURATION),
        (tmp_path / "s1.mp4", 2.0, FADE_DURATION, 0.0),
    ]
    for p, *_ in segs:
        p.write_bytes(b"FAKE")
    captured = _capture_filter(monkeypatch)

    await _join_with_fades(segs, tmp_path / "out.mp4")

    fc = captured[0]
    assert "concat=n=2:v=1:a=1" in fc
    for token in ("xfade=", "acrossfade", "adelay", "amix"):
        assert token not in fc


async def test_join_with_fades_per_segment_fade_points(monkeypatch, tmp_path):
    """[AC:1] Each segment fades in/out over its OWN edges at the right start time."""
    segs = [
        (tmp_path / "s0.mp4", 3.0, 0.0, FADE_DURATION),
        (tmp_path / "s1.mp4", 2.0, FADE_DURATION, FADE_DURATION),
        (tmp_path / "s2.mp4", 4.0, FADE_DURATION, 0.0),
    ]
    for p, *_ in segs:
        p.write_bytes(b"FAKE")
    captured = _capture_filter(monkeypatch)

    await _join_with_fades(segs, tmp_path / "out.mp4")

    fc = captured[0]
    # segment 0: fade-out only, starting at 3.0 - 0.5 = 2.5
    assert "[0:v]fade=t=out:st=2.500:d=0.500[v0]" in fc
    # segment 1: fade-in at 0, fade-out at 2.0 - 0.5 = 1.5
    assert "[1:v]fade=t=in:st=0:d=0.500,fade=t=out:st=1.500:d=0.500[v1]" in fc
    # segment 2: fade-in only, no fade-out (last segment)
    assert "[2:v]fade=t=in:st=0:d=0.500[v2]" in fc
    assert "[v0][0:a][v1][1:a][v2][2:a]concat=n=3:v=1:a=1[vout][aout]" in fc


async def test_join_with_fades_zero_fade_segment_skips_filter(monkeypatch, tmp_path):
    """[AC:5] A segment with no join-fades (card/hold) is concat'd directly, unfiltered."""
    segs = [
        (tmp_path / "s0.mp4", 3.0, 0.0, FADE_DURATION),
        (tmp_path / "card.mp4", BLACK_HOLD_DURATION, 0.0, 0.0),
        (tmp_path / "s1.mp4", 2.0, FADE_DURATION, 0.0),
    ]
    for p, *_ in segs:
        p.write_bytes(b"FAKE")
    captured = _capture_filter(monkeypatch)

    await _join_with_fades(segs, tmp_path / "out.mp4")

    fc = captured[0]
    assert "[1:v]fade=" not in fc
    assert "[v0][0:a][1:v][1:a][v2][2:a]concat=n=3:v=1:a=1[vout][aout]" in fc


async def test_join_with_fades_clamps_fade_to_segment_duration(monkeypatch, tmp_path):
    """[Task 1] A fade longer than the segment's own duration is clamped defensively."""
    segs = [
        (tmp_path / "s0.mp4", 0.2, 0.0, FADE_DURATION),
        (tmp_path / "s1.mp4", 2.0, FADE_DURATION, 0.0),
    ]
    for p, *_ in segs:
        p.write_bytes(b"FAKE")
    captured = _capture_filter(monkeypatch)

    await _join_with_fades(segs, tmp_path / "out.mp4")

    assert "fade=t=out:st=0.000:d=0.200" in captured[0]


async def test_join_with_fades_overlapping_windows_dont_double_up(monkeypatch, tmp_path):
    """A segment shorter than fade_in+fade_out gets a fade_out clamped against the
    remaining duration AFTER fade_in, not just against dur — so the two windows
    never overlap on the same segment."""
    segs = [
        (tmp_path / "s0.mp4", 2.0, 0.0, FADE_DURATION),
        (tmp_path / "s1.mp4", 0.3, FADE_DURATION, FADE_DURATION),
        (tmp_path / "s2.mp4", 2.0, FADE_DURATION, 0.0),
    ]
    for p, *_ in segs:
        p.write_bytes(b"FAKE")
    captured = _capture_filter(monkeypatch)

    await _join_with_fades(segs, tmp_path / "out.mp4")

    # segment 1: dur=0.3, fade_in clamped to 0.3, leaving 0 for fade_out (skipped).
    assert "[1:v]fade=t=in:st=0:d=0.300[v1]" in captured[0]


async def test_join_with_fades_fail_raises(monkeypatch, tmp_path):
    segs = [(tmp_path / f"s{i}.mp4", 2.0, 0.0, 0.0) for i in range(2)]
    for p, *_ in segs:
        p.write_bytes(b"FAKE")
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_fail)

    with pytest.raises(RuntimeError, match="fade join failed"):
        await _join_with_fades(segs, tmp_path / "out.mp4")

# ── _validate_scene_assets ────────────────────────────────────────────────────


def test_validate_missing_image_path(assets):
    scene = _scene(1, audio=assets.audio, subtitle=assets.subtitle)
    scene["shots"] = [_shot(None)]
    with pytest.raises(ValueError, match="no shot has a valid image_path"):
        _validate_scene_assets([scene])


def test_validate_image_not_found(assets):
    scene = _scene(1, image="/no/such/file.png", audio=assets.audio, subtitle=assets.subtitle)
    with pytest.raises(FileNotFoundError, match="image_path not found"):
        _validate_scene_assets([scene])


def test_validate_missing_audio(assets):
    scene = _scene(1, image=assets.image, audio=None, subtitle=assets.subtitle)
    with pytest.raises(FileNotFoundError, match="audio_path missing"):
        _validate_scene_assets([scene])


def test_validate_audio_not_found(assets):
    scene = _scene(1, image=assets.image, audio="/no/audio.wav", subtitle=assets.subtitle)
    with pytest.raises(FileNotFoundError, match="audio_path missing or not found"):
        _validate_scene_assets([scene])


def test_validate_missing_subtitle(assets):
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=None)
    with pytest.raises(FileNotFoundError, match="subtitle_path missing"):
        _validate_scene_assets([scene])


def test_validate_subtitle_not_found(assets):
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle="/no/sub.srt")
    with pytest.raises(FileNotFoundError, match="subtitle_path missing or not found"):
        _validate_scene_assets([scene])


def test_validate_passes_with_valid_assets(assets):
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    _validate_scene_assets([scene])  # should not raise


@pytest.mark.parametrize("bad", [0, -1.0, None])
def test_validate_rejects_nonpositive_audio_duration(assets, bad):
    """[review:D] missing/≤0 audio_duration must fail fast, not silently default to 2.0."""
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
                   audio_duration=bad)
    with pytest.raises(ValueError, match="audio_duration must be a positive number"):
        _validate_scene_assets([scene])


def test_validate_fails_on_later_shot_missing_image(assets):
    """[Story 8.11][review fix] A later shot's missing image fails validation
    when that shot is actually part of the render plan (its own sentence
    window) — not just because it happens to have an image_path."""
    words = ["첫", "문장", "이다", "둘째", "문장", "이다"]
    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        narration="첫 문장 이다. 둘째 문장 이다.",
        word_timings=[
            {"word": w, "start_sec": i * 1.5, "end_sec": (i + 1) * 1.5} for i, w in enumerate(words)
        ],
        audio_duration=9.0,
    )
    scene["shots"].append(_shot("/does/not/exist.png", shot_id="S002"))
    scene["shots"][1]["sentence_indices"] = [1]
    with pytest.raises(FileNotFoundError, match="shot S002: image_path not found"):
        _validate_scene_assets([scene])


def test_validate_ignores_unused_later_shot_missing_image_in_degrade_path(assets):
    """[Story 8.11][review fix] With no usable word_timings, plan_shot_clips
    degrades to a single full-duration clip using only the first rendered
    shot — a later shot's missing image is never rendered, so it must not
    abort the run (restores the pre-8.11 rule for the degrade path)."""
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    scene["shots"].append(_shot("/does/not/exist.png", shot_id="S002"))
    _validate_scene_assets([scene])  # should not raise


# ── video_node: happy path ────────────────────────────────────────────────────


async def test_video_node_single_scene(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    state = _state([_scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)])
    out = await video_node(state)

    assert out["current_stage"] == "video"
    assert out.get("error") is None
    assert out["video_path"].endswith("video.mp4")
    assert Path(out["video_path"]).exists()
    assert "run-001" in out["video_path"]


async def test_video_node_multi_scene(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out["current_stage"] == "video"
    assert out.get("error") is None
    assert Path(out["video_path"]).exists()


async def test_video_node_output_under_run_dir(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    state = _state(
        [_scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)],
        run_id="run-xyz",
    )
    out = await video_node(state)

    assert Path(tmp_path / "run-xyz" / "video.mp4") == Path(out["video_path"])


async def test_video_node_scenes_sorted_by_scene_num(monkeypatch, tmp_path, assets):
    ffmpeg_calls: list[tuple] = []

    async def _recording_fake(*args):
        ffmpeg_calls.append(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _recording_fake)

    scenes = [
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))
    assert out.get("error") is None

    seg_calls = [args for args in ffmpeg_calls if any("seg_" in a for a in args if isinstance(a, str))]
    seg_outputs = [next(a for a in args if "seg_" in a) for args in seg_calls]
    assert seg_outputs[0].endswith("seg_001.mp4")
    assert seg_outputs[1].endswith("seg_002.mp4")


async def test_video_node_input_not_mutated(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    state = _state([_scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)])
    snapshot = json.loads(json.dumps(state))
    await video_node(state)
    assert state == snapshot  # AD-4 purity


# ── video_node: zoompan applied ───────────────────────────────────────────────


async def test_video_node_zoompan_in_vf(monkeypatch, tmp_path, assets):
    """Every segment render must include zoompan. [AC:1]"""
    captured_vfs: list[str] = []

    async def _capture_vf(*args):
        args_list = list(args)
        if "-vf" in args_list:
            captured_vfs.append(args_list[args_list.index("-vf") + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _capture_vf)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))
    assert out.get("error") is None
    assert len(captured_vfs) == 2
    for vf in captured_vfs:
        assert "zoompan" in vf, f"zoompan missing from vf: {vf}"


async def test_video_node_camera_movement_hint_used(monkeypatch, tmp_path, assets):
    """camera_movement hint propagates to the filtergraph direction. [AC:3]"""
    captured_vfs: list[str] = []

    async def _capture_vf(*args):
        args_list = list(args)
        if "-vf" in args_list:
            captured_vfs.append(args_list[args_list.index("-vf") + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _capture_vf)

    state = _state([_scene(1, image=assets.image, audio=assets.audio,
                            subtitle=assets.subtitle, camera_movement="pan right")])
    out = await video_node(state)
    assert out.get("error") is None
    # pan-right uses x='(iw-iw/zoom)*on/<frames>' so 'iw-iw/zoom' appears in the filter
    assert "iw-iw/zoom" in captured_vfs[0]


# ── video_node: error paths ───────────────────────────────────────────────────


async def test_video_node_ffmpeg_not_found(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(shutil, "which", lambda x: None)

    state = _state([_scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)])
    out = await video_node(state)

    assert out["current_stage"] == "video"
    assert "stage=video" in out["error"]
    assert "run-001" in out["error"]
    assert out.get("video_path") is None


async def test_video_node_ffmpeg_nonzero_exit(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_fail)

    state = _state([_scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)])
    out = await video_node(state)

    assert out["current_stage"] == "video"
    assert "stage=video" in out["error"]
    assert out.get("video_path") is None


async def test_video_node_no_scenes_sets_error(monkeypatch, tmp_path):
    """Zero scenes must fail explicitly (not via a stripped-under-O assert). [AC:4]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    out = await video_node(_state([]))

    assert "stage=video" in out["error"]
    assert "no scenes" in out["error"]
    assert out.get("video_path") is None


async def test_video_node_escapes_subtitle_path(monkeypatch, tmp_path, assets):
    """subtitles= path with filtergraph-special chars must be escaped + quoted. [1.9b hardening]"""
    captured_vfs: list[str] = []

    async def _capture_vf(*args):
        args_list = list(args)
        if "-vf" in args_list:
            captured_vfs.append(args_list[args_list.index("-vf") + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _capture_vf)

    # subtitle path containing a colon and a space — both break an unescaped filtergraph
    srt = tmp_path / "a b:c.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n\n", encoding="utf-8")
    state = _state([_scene(1, image=assets.image, audio=assets.audio, subtitle=str(srt))])
    out = await video_node(state)

    assert out.get("error") is None
    vf = captured_vfs[0]
    assert "subtitles='" in vf and "\\:" in vf  # single-quoted value, colon escaped
    assert "a b:c.srt" not in vf  # raw unescaped colon must not appear
    assert "fontsdir='" in vf  # Story 5.18 AC:6 — bundled Pretendard, no system-font dependency


async def test_video_node_missing_image_sets_error(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    scene = _scene(1, image=None, audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert "stage=video" in out["error"]
    assert out.get("video_path") is None


async def test_video_node_missing_audio_sets_error(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))

    scene = _scene(1, image=assets.image, audio=None, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert "stage=video" in out["error"]
    assert out.get("video_path") is None


async def test_video_node_missing_subtitle_sets_error(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=None)
    out = await video_node(_state([scene]))

    assert "stage=video" in out["error"]
    assert out.get("video_path") is None


async def test_video_node_error_does_not_set_video_path(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(shutil, "which", lambda x: None)

    state = _state([_scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)])
    out = await video_node(state)

    assert "video_path" not in out or out.get("video_path") is None


# ── observability ─────────────────────────────────────────────────────────────


async def test_trace_receives_effects_metadata(monkeypatch, tmp_path, assets):
    """effects list with per-scene direction must appear in trace metadata. [AC:5]"""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    await video_node(_state(scenes))

    assert "effects" in captured
    assert len(captured["effects"]) == 2
    for effect in captured["effects"]:
        assert "scene_num" in effect
        assert "direction" in effect
        assert "start_zoom" in effect
        assert "end_zoom" in effect


async def test_trace_receives_transition_metadata(monkeypatch, tmp_path, assets):
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    await video_node(_state([_scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)]))

    # transition metadata must be recorded regardless of scene count
    assert captured.get("upscale_pass") is True


def test_record_trace_reports_dip_to_black_grammar(monkeypatch):
    """[Story 5.16 AC:7] Trace metadata names the new grammar, not the retired xfade one."""
    captured: dict = {}
    fake_client = SimpleNamespace(update_current_span=lambda **kw: captured.update(kw["metadata"]))
    monkeypatch.setattr(video, "get_client", lambda: fake_client)

    _REAL_RECORD_TRACE(run_id="r", scene_count=2, latency_ms=10)

    assert captured["transition"] == "dip-to-black"
    assert captured["fade_duration"] == video.FADE_DURATION
    assert captured["black_hold_sec"] == video.BLACK_HOLD_DURATION


def test_record_trace_reports_motion_table_version_and_style_counts(monkeypatch):
    """[Story 8.8 AC:10] character_motion metadata carries the table version
    (for "why did this render differently" debugging) and per-style counts."""
    captured: dict = {}
    fake_client = SimpleNamespace(update_current_span=lambda **kw: captured.update(kw["metadata"]))
    monkeypatch.setattr(video, "get_client", lambda: fake_client)

    _REAL_RECORD_TRACE(
        run_id="r", scene_count=1, latency_ms=10,
        motion_style_counts={"breath": 3, "tremble": 1},
    )

    assert captured["character_motion"] == {
        "table_version": cm.MOTION_TABLE_VERSION,
        "style_counts": {"breath": 3, "tremble": 1},
    }


async def test_trace_captures_error_on_failure(monkeypatch, tmp_path, assets):
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(shutil, "which", lambda x: None)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    await video_node(_state([_scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)]))
    assert captured.get("error") is not None


def test_record_trace_is_non_fatal(monkeypatch):
    monkeypatch.setattr(
        video, "get_client",
        lambda: (_ for _ in ()).throw(RuntimeError("langfuse down")),
    )
    video._record_trace(run_id="r", scene_count=1, latency_ms=10)


# ── layering guard ────────────────────────────────────────────────────────────


def test_no_db_api_service_imports():
    """AD-1: video.py must not import db, api, or services layers."""
    source = Path(video.__file__).read_text()
    for forbidden in (
        "from yt_flow.db",
        "from yt_flow.api",
        "from yt_flow.services",
        "import yt_flow.db",
        "import yt_flow.api",
        "import yt_flow.services",
    ):
        assert forbidden not in source, f"video.py must not import {forbidden}"


# ── character idle-motion overlay (Story 1.9c) ────────────────────────────────


def _capture_arg_flag(flag: str):
    """Return (ffmpeg_fake, captured_list) that records the value after ``flag``."""
    captured: list[str] = []

    async def _fake(*args):
        al = list(args)
        if flag in al:
            captured.append(al[al.index(flag) + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    return _fake, captured


def test_overlay_filter_has_sinusoidal_motion():
    """Overlay must animate both axes with sin(t). [AC:1]"""
    f = _overlay_filter()
    assert "overlay=" in f
    assert "sin(t*" in f
    # both axes carry motion
    assert f.count("sin(t*") >= 2


def test_overlay_filter_eval_frame_not_init():
    """eval=frame is REQUIRED; eval=init freezes motion (t/n → NAN). [AC:2]"""
    f = _overlay_filter()
    assert "eval=frame" in f
    assert "eval=init" not in f


def test_character_scale_filter_downscale_only_within_motion_box():
    """Character is capped to the motion-safe box, downscale-only, AR-preserved.

    The box reserves room for the peak parallax zoom *and* the full sine excursion:
    the cap is (COMP-2*amp)/CHAR_MAX_ZOOM (Story 7.3 AC:4), so a capped character
    zoomed to its peak lands back inside COMP minus sway/bob. [review:1.9c]
    """
    f = _character_scale_filter()
    assert "scale=" in f
    assert "force_original_aspect_ratio=decrease" in f   # never distort
    assert "min(iw" in f and "min(ih" in f               # never upscale a small cutout
    assert str(video.CHAR_MAX_W) in f
    assert str(video.CHAR_MAX_H) in f


# ── Character parallax (Story 7.3) ────────────────────────────────────────────


def test_character_spec_in_center_amplifies_zoom():
    """in-center 1.0→1.15 background ⇒ character 1.0→1.195 (delta ×1.3). [AC:1]"""
    bg = EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    ch = _character_spec(bg)
    assert ch.direction == "in-center"                 # pass-through
    assert ch.start_zoom == pytest.approx(1.0)
    assert ch.end_zoom == pytest.approx(1.0 + (video.ZOOM_IN_MAX - 1.0) * video.CHAR_DEPTH_FACTOR)
    assert ch.end_zoom == pytest.approx(1.195)


def test_character_spec_out_center_amplifies_zoom():
    """out-center 1.15→1.0 background ⇒ character 1.195→1.0. [AC:1]"""
    bg = EffectSpec(direction="out-center", start_zoom=video.ZOOM_IN_MAX, end_zoom=1.0)
    ch = _character_spec(bg)
    assert ch.direction == "out-center"
    assert ch.start_zoom == pytest.approx(1.195)
    assert ch.end_zoom == pytest.approx(1.0)


def test_character_spec_static_stays_tiny():
    """static 1.0→1.005 ⇒ character 1.0→1.0065 — tiny after amplification, no special-case. [AC:1]"""
    bg = select_effect(_shot(camera_movement="static"), 0)  # 1.0→1.005 in-center
    ch = _character_spec(bg)
    assert ch.start_zoom == pytest.approx(1.0)
    assert ch.end_zoom == pytest.approx(1.0065)


def test_character_spec_direction_passthrough():
    """Direction is copied verbatim from the background (parallax needs same direction). [AC:1]"""
    for d in video._DIRECTION_POOL:
        bg = EffectSpec(direction=d, start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
        assert _character_spec(bg).direction == d


def test_character_zoom_filter_uses_scale_eval_frame():
    """Character zoom is a time-varying scale (not zoompan) with eval=frame. [AC:2]"""
    ch = _character_spec(EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX))
    f = _character_zoom_filter(ch, duration=2.0)
    assert "scale=" in f
    assert "eval=frame" in f
    assert "zoompan" not in f          # crop-free near plane
    assert "iw*" in f and "ih*" in f   # both axes ramp


def test_overlay_filter_parallax_off_is_unchanged():
    """spec=None ⇒ exact fixed-size sway/bob-only string (parallax off). [AC:5]"""
    f = _overlay_filter()
    assert "overlay=" in f and "eval=frame" in f
    assert f.count("sin(t*") == 2      # only the two idle sines
    assert "t/" not in f               # no duration-ramped pan term


def test_overlay_filter_parallax_pan_adds_term_over_sines():
    """spec=pan-right ⇒ a macro pan term rides on top of the sway/bob sines. [AC:3]"""
    ch = _character_spec(EffectSpec(direction="pan-right", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX), "near")
    f = _overlay_filter(spec=ch, duration=2.0, depth="near")
    assert f.count("sin(t*") == 2                       # sway/bob preserved
    near_amp = video.CHAR_PAN_AMPLITUDE_PX * video._DEPTH_PARALLAX["near"]
    assert f"({-near_amp})*t/2.0" in f   # pan-right drifts -x on-screen, full amplitude at near
    assert f != _overlay_filter()                       # differs from parallax-off


def test_overlay_filter_center_directions_contribute_zero_pan():
    """in-center/out-center have no apparent drift ⇒ overlay == parallax-off string. [AC:3]"""
    for d in ("in-center", "out-center"):
        ch = _character_spec(EffectSpec(direction=d, start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX))
        assert _overlay_filter(spec=ch, duration=2.0) == _overlay_filter()


# ── Character locomotion / screen blocking (Story 8.9) ──────────────────────


def test_overlay_filter_anchored_movement_is_unchanged():
    """movement_mode='anchored' (the default) reproduces the pre-8.9 string
    byte-for-byte, with and without parallax. [AC:10]"""
    assert _overlay_filter() == _overlay_filter(movement_mode="anchored")
    ch = _character_spec(EffectSpec(direction="pan-right", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX), "near")
    parallax_on = _overlay_filter(spec=ch, duration=2.0, depth="near")
    assert parallax_on == _overlay_filter(spec=ch, duration=2.0, depth="near", movement_mode="anchored")


def test_overlay_filter_enter_adds_main_w_term():
    """A movement mode other than anchored contributes a main_w-scaled term. [AC:7]"""
    f = _overlay_filter(duration=2.0, movement_mode="enter", movement_direction="left")
    assert "main_w*(1-" in f
    assert f != _overlay_filter(duration=2.0)


def test_overlay_filter_movement_composes_before_parallax_and_idle_motion():
    """Composition order (AC:5): anchor -> movement -> parallax -> idle motion.
    The movement term must appear in the x string BEFORE the parallax pan term
    and BEFORE the idle-motion sine term."""
    ch = _character_spec(EffectSpec(direction="pan-right", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX), "near")
    f = _overlay_filter(
        spec=ch, duration=2.0, depth="near", motion_style="sway", motion_energy="medium",
        movement_mode="enter", movement_direction="left",
    )
    x_expr = f.split("x='", 1)[1].split("'", 1)[0]
    movement_pos = x_expr.index("main_w*(1-")
    pan_pos = x_expr.index(")*t/2.0")
    sine_pos = x_expr.index("sin(t*")
    assert movement_pos < pan_pos < sine_pos


def test_overlay_filter_drift_and_cross_add_single_x_term():
    anchored = _overlay_filter(duration=2.0)
    drift = _overlay_filter(duration=2.0, movement_mode="drift")
    cross = _overlay_filter(duration=2.0, movement_mode="cross", movement_direction="right", position="left")
    assert drift != anchored and str(video.character_movement.DRIFT_PX) in drift
    assert cross != anchored


def test_movement_scale_filter_empty_for_non_scale_modes():
    for mode in ("anchored", "drift", "enter", "exit", "cross"):
        assert video._movement_scale_filter(mode, "none", "slow", "center", "mid", 2.0) == ""


def test_movement_scale_filter_approach_retreat_produce_scale_terms():
    for mode in ("approach", "retreat"):
        f = video._movement_scale_filter(mode, "in" if mode == "approach" else "out", "slow", "center", "near", 2.0)
        assert f.startswith("scale=w='iw*(1+(")
        assert "eval=frame" in f


def test_movement_scale_filter_zero_duration_is_empty():
    assert video._movement_scale_filter("approach", "in", "slow", "center", "near", 0.0) == ""


# ── Multi-card cast compositing (Story 8.3) ───────────────────────────────────


def test_overlay_filter_position_anchors_rule_of_thirds():
    """position selects a 1/3, 1/2, or 2/3 horizontal anchor. [AC:6]"""
    for position, frac in video._POSITION_X_FRAC.items():
        f = _overlay_filter(position=position)
        assert f"main_w*{frac}" in f


def test_overlay_filter_phase_decorrelates_by_index():
    """Card index k offsets the sine phase so N cards never sway in lockstep. [AC:6]"""
    f0 = _overlay_filter(position="center", k=0)
    f1 = _overlay_filter(position="center", k=1)
    assert f0 != f1
    assert f"+{video.PHASE_STEP})" in f1 or f"+{1 * video.PHASE_STEP})" in f1


def test_overlay_filter_pan_amplitude_scales_by_depth():
    """Parallax pan amplitude is scaled down for mid/far cards vs near. [AC:7]"""
    spec = EffectSpec(direction="pan-right", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    near = _overlay_filter(position="center", spec=spec, duration=2.0, depth="near")
    mid = _overlay_filter(position="center", spec=spec, duration=2.0, depth="mid")
    far = _overlay_filter(position="center", spec=spec, duration=2.0, depth="far")
    for depth, filt in (("near", near), ("mid", mid), ("far", far)):
        amp = video.CHAR_PAN_AMPLITUDE_PX * video._DEPTH_PARALLAX[depth]
        assert f"({-amp})*t/2.0" in filt


# ── Character micro-motion techniques (Story 8.8) ───────────────────────────


def test_overlay_filter_default_matches_pre_8_8_sway():
    """motion_style='sway'/energy='medium' defaults reproduce the exact
    pre-8.8 two-sine overlay string — no regression for existing callers."""
    assert _overlay_filter() == _overlay_filter(motion_style="sway", motion_energy="medium")
    assert _overlay_filter().count("sin(t*") == 2


def test_overlay_filter_hold_has_no_idle_motion():
    """hold: no sine/pulse/glitch term at all — position is static (parallax
    pan, if any, still applies separately). [AC:6]"""
    f = _overlay_filter(motion_style="hold", motion_energy="medium")
    assert "sin(" not in f
    assert "eval=frame" in f  # still required per the docstring rule


def test_overlay_filter_hold_with_parallax_keeps_pan_term():
    """hold + parallax on: idle motion is suppressed but the macro pan term
    from `spec` still rides through — `motion_style` disables idle motion
    only, never parallax. [Story 8.8 AC:6, Interfaces: 'parallax_enabled=False
    disables parallax only, not micro-motion']"""
    ch = _character_spec(EffectSpec(direction="pan-right", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX), "near")
    f = _overlay_filter(spec=ch, duration=2.0, depth="near", motion_style="hold", motion_energy="medium")
    assert "sin(" not in f  # no idle motion
    near_amp = video.CHAR_PAN_AMPLITUDE_PX * video._DEPTH_PARALLAX["near"]
    assert f"({-near_amp})*t/2.0" in f  # pan term unaffected by motion_style


def test_overlay_filter_breath_has_single_y_sine():
    f = _overlay_filter(motion_style="breath", motion_energy="medium")
    assert f.count("sin(t*") == 1
    assert f"sin(t*{cm.BOB_FREQ}+0.0)" in f


def test_overlay_filter_tremble_adds_shake_on_top_of_breath():
    """tremble = breath's bob + its own x/y shake — 1 x-term, 2 y-terms. [AC:6]

    Updated for Story 11.3 AC:5: the shake terms are 2-octave fBm strings now
    (smoothstep-interpolated lattice hash), so the old "three plain sines /
    sin(t*TREMBLE_FREQ)" assertions no longer describe the table.
    """
    f = _overlay_filter(motion_style="tremble", motion_energy="medium")
    assert f.count("sin(t*") == 1          # breath's bob sine, unchanged
    assert f"sin(t*{cm.BOB_FREQ}+0.0)" in f
    assert "3-2*" in f                      # the fBm tremor band (smoothstep marker)


def test_overlay_filter_pulse_has_no_position_motion():
    """pulse only pulses scale (Story 8.8 AC:6) — position sines are silent."""
    f = _overlay_filter(motion_style="pulse", motion_energy="medium")
    assert "sin(" not in f


def test_overlay_filter_glitch_uses_quantized_floor_not_smooth_sine():
    f = _overlay_filter(motion_style="glitch", motion_energy="medium")
    assert "floor(" in f
    assert "random(" not in f  # deterministic, no ffmpeg random() filter state


def test_overlay_filter_energy_scales_amplitude():
    low = _overlay_filter(motion_style="sway", motion_energy="low")
    high = _overlay_filter(motion_style="sway", motion_energy="high")
    assert low != high
    assert f"*{cm.SWAY_AMPLITUDE * cm._ENERGY_MULT['high']}" in high
    assert f"*{cm.SWAY_AMPLITUDE * cm._ENERGY_MULT['low']}" in low


def test_motion_scale_filter_empty_for_hold_and_glitch():
    assert video._motion_scale_filter("hold", "medium") == ""
    assert video._motion_scale_filter("glitch", "medium") == ""


def test_motion_scale_filter_breath_and_pulse_produce_scale_pulse():
    breath = video._motion_scale_filter("breath", "medium")
    pulse = video._motion_scale_filter("pulse", "medium")
    for f in (breath, pulse):
        assert f.startswith("scale=w='iw*(1+(")
        assert "eval=frame" in f
    assert breath != pulse  # different amplitude/frequency


def test_motion_scale_filter_phase_decorrelates_by_index():
    """Same style, different card index k → different scale-pulse phase, so N
    breathing cards never pulse in lockstep either. [AC:8]"""
    f0 = video._motion_scale_filter("breath", "medium", k=0)
    f1 = video._motion_scale_filter("breath", "medium", k=1)
    assert f0 != f1


def test_character_scale_filter_depth_caps():
    """Depth-scaled size cap: far < mid < near, all within the motion-safe box. [AC:6]"""
    near = _character_scale_filter("near")
    mid = _character_scale_filter("mid")
    far = _character_scale_filter("far")
    assert str(video.CHAR_MAX_W) in near and str(video.CHAR_MAX_H) in near
    assert str(video.CHAR_MAX_W * video._DEPTH_SCALE["mid"]) in mid
    assert str(video.CHAR_MAX_W * video._DEPTH_SCALE["far"]) in far
    assert far != mid != near


def test_character_spec_depth_scales_amplification():
    """Depth scales the zoom-delta amplification — near amplifies most. [AC:7]"""
    bg = EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    near = _character_spec(bg, "near")
    mid = _character_spec(bg, "mid")
    far = _character_spec(bg, "far")
    assert near.end_zoom > mid.end_zoom > far.end_zoom > bg.end_zoom


def test_char_max_box_reserves_zoom_growth():
    """[AC:8] The shrunk box, zoomed to its peak, must land within the frame with room
    left for BOTH the idle-motion excursion AND the macro pan ramp — the worst-case
    corner (peak zoom + peak idle motion + full pan, e.g. pan-* directions) stays
    on-screen by construction, so off-frame prevention doesn't depend on a visual
    eyeball. [review:D1]"""
    assert video.CHAR_MAX_W * video.CHAR_MAX_ZOOM <= (
        video.COMP_W - 2 * (video._MAX_MOTION_X_PX + video.CHAR_PAN_AMPLITUDE_PX) + 1e-6
    )
    assert video.CHAR_MAX_H * video.CHAR_MAX_ZOOM <= (
        video.COMP_H - 2 * (video._MAX_MOTION_Y_PX + video.CHAR_PAN_AMPLITUDE_PX) + 1e-6
    )


def test_char_max_box_reserves_scale_pulse_growth():
    """[Story 8.8 AC:7] max_scaled_width + 2*max_x_excursion <= COMP_W (and the
    height equivalent) — the box must also leave room for the loudest scale
    pulse (pulse style, high energy) on top of the peak parallax zoom, for every
    style/energy/depth combination. The near/full-zoom case is the worst case;
    smaller depth-scaled boxes are strictly safer (Interfaces: motion amplitude
    is depth-independent, only the box size shrinks per depth)."""
    max_scaled_width = video.CHAR_MAX_W * video.CHAR_MAX_ZOOM * video._MAX_MOTION_SCALE
    max_scaled_height = video.CHAR_MAX_H * video.CHAR_MAX_ZOOM * video._MAX_MOTION_SCALE
    assert max_scaled_width + 2 * video._MAX_MOTION_X_PX <= video.COMP_W + 1e-6
    assert max_scaled_height + 2 * video._MAX_MOTION_Y_PX <= video.COMP_H + 1e-6
    # The AC:7 inequality above has slack from the reserved pan margin, so it
    # alone can't catch a dropped CHAR_PAN_AMPLITUDE_PX reservation (review finding).
    # Pin the box formula's actual (near-zero-slack) budget too.
    assert max_scaled_width + 2 * (video._MAX_MOTION_X_PX + video.CHAR_PAN_AMPLITUDE_PX) <= video.COMP_W + 1e-6
    assert max_scaled_height + 2 * (video._MAX_MOTION_Y_PX + video.CHAR_PAN_AMPLITUDE_PX) <= video.COMP_H + 1e-6


def test_config_parallax_enabled_default_true():
    """Settings.parallax_enabled defaults true, per AC:5."""
    from yt_flow.config import Settings

    assert Settings.model_fields["parallax_enabled"].default is True


def _cast_member(
    card_key="SCP-096", *, position="center", depth="near", pose="standing",
    motion_style=None, motion_energy=None,
):
    member = {"card_key": card_key, "position": position, "depth": depth, "pose": pose}
    if motion_style is not None:
        member["motion_style"] = motion_style
    if motion_energy is not None:
        member["motion_energy"] = motion_energy
    return member


def _inject_resolver(monkeypatch, mapping: dict[str, list[dict]] | None = None, *, fn=None):
    """Wire video._cast_resolver like api/main.py does — mapping keyed by "scene:shot"."""
    async def _default(scp_id, scenes):
        return mapping or {}
    monkeypatch.setattr(video, "_cast_resolver", fn or _default)


async def test_video_node_parallax_on_adds_char_zoom_and_pan(monkeypatch, tmp_path, assets):
    """parallax_enabled=True: card stream gets a scale-zoom ramp + the overlay
    carries a pan term, on top of the existing scale-cap + sway/bob. [AC:2,3,5]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, parallax_enabled=True))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(
        1, image=assets.image, cast=[_cast_member()],
        audio=assets.audio, subtitle=assets.subtitle, camera_movement="pan right",
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    fc = captured[0]
    # card chain = scale-cap, scale-zoom(eval=frame), breath's scale-pulse
    # (default motion_style="breath") → three scale= on the [c0] branch
    char_branch = fc.split("[c0]")[0].split("[bg];")[-1]
    assert char_branch.count("scale=") == 3
    assert "eval=frame" in char_branch
    # overlay carries the pan term for pan-right
    near_amp = video.CHAR_PAN_AMPLITUDE_PX * video._DEPTH_PARALLAX["near"]
    assert f"({-near_amp})*t/" in fc


async def test_video_node_parallax_off_no_char_zoom(monkeypatch, tmp_path, assets):
    """parallax_enabled=False: today's behavior — single scale-cap, no zoom ramp, no pan. [AC:5]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, parallax_enabled=False))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(
        1, image=assets.image, cast=[_cast_member()],
        audio=assets.audio, subtitle=assets.subtitle, camera_movement="pan right",
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    fc = captured[0]
    char_branch = fc.split("[c0]")[0].split("[bg];")[-1]
    # cap + breath's scale-pulse (default motion_style), no parallax zoom ramp
    assert char_branch.count("scale=") == 2
    assert "t/" not in fc.split("[o0]")[0]     # no pan-term ramp in the overlay


async def test_video_node_character_uses_filter_complex(monkeypatch, tmp_path, assets):
    """A shot with a resolved cast card renders via filter_complex overlay + eval=frame. [AC:1,2]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert captured, "filter_complex not used for a cast-card shot"
    fc = captured[0]
    assert "zoompan" in fc          # background still gets Ken Burns
    assert "overlay=" in fc         # card composited on top
    assert "eval=frame" in fc       # motion animates per-frame
    assert "subtitles=" in fc       # subtitles burned last
    assert "fontsdir='" in fc       # Story 5.18 AC:6 — bundled Pretendard, cast-card branch too
    assert "scale=" in fc           # card normalized to motion-safe box
    assert "[c0]" in fc             # scaled card feeds the overlay


async def test_video_node_character_maps_output_and_audio(monkeypatch, tmp_path, assets):
    """filter_complex path maps the composed [out] and the audio input. [AC:1]"""
    calls: list[tuple] = []

    async def _rec(*args):
        calls.append(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _rec)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))
    assert out.get("error") is None

    args = list(calls[0])
    assert "[out]" in args          # -map [out]
    # audio is the 3rd input (idx 2): bg, card, audio
    assert "2:a" in args


async def test_video_node_no_character_uses_vf_fallback(monkeypatch, tmp_path, assets):
    """Empty cast → unchanged 1.9b -vf Ken-Burns path, no overlay. [AC:3,8]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake_vf, captured_vf = _capture_arg_flag("-vf")
    monkeypatch.setattr(video, "_run_ffmpeg", fake_vf)

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert captured_vf, "background-only shot must use -vf"
    assert "overlay=" not in captured_vf[0]
    assert "zoompan" in captured_vf[0]


async def test_video_node_two_cards_stacking_and_positions(monkeypatch, tmp_path, assets):
    """N=2 cards: far-before-near overlay chain order, distinct rule-of-thirds x anchors. [AC:6]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    # cast order: near first, far second — resolver output preserves cast order,
    # but the compositor must still paint far before near (stable depth sort).
    _inject_resolver(monkeypatch, {"1:S001": [
        _card(assets.character, card_key="SCP-096", position="left", depth="near"),
        _card(assets.character2, card_key="STOCK-d-class", position="right", depth="far"),
    ]})

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member("SCP-096", position="left", depth="near"),
              _cast_member("STOCK-d-class", position="right", depth="far")],
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    fc = captured[0]
    # cast order is [near, far] but stacking is derived (stable sort by depth):
    # far (STOCK-d-class) must be input 1 / [c0], near (SCP-096) input 2 / [c1].
    assert fc.index("[c0]") < fc.index("[c1]")
    left_anchor = f"main_w*{video._POSITION_X_FRAC['left']}"
    right_anchor = f"main_w*{video._POSITION_X_FRAC['right']}"
    assert left_anchor in fc and right_anchor in fc
    # far/right's overlay stage is painted before near/left's
    assert fc.index(right_anchor) < fc.index(left_anchor)


async def test_video_node_moving_card_keeps_depth_derived_stacking(monkeypatch, tmp_path, assets):
    """[Story 8.9 AC:9] A card with movement fields still stacks purely by
    depth — z-order is never dynamically re-derived from movement_mode."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [
        _card(assets.character, card_key="SCP-096", position="left", depth="near",
              movement_mode="cross", movement_direction="right"),
        _card(assets.character2, card_key="STOCK-d-class", position="right", depth="far"),
    ]})

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member("SCP-096", position="left", depth="near"),
              _cast_member("STOCK-d-class", position="right", depth="far")],
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    fc = captured[0]
    # far (STOCK-d-class, no movement) still paints first regardless of the
    # near card's movement_mode — depth alone drives stacking.
    assert fc.index("[c0]") < fc.index("[c1]")


async def test_video_node_threads_resolved_card_movement_fields(monkeypatch, tmp_path, assets):
    """A card's movement_mode/direction/pace from the resolver reaches the
    filtergraph. [AC:5,7]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [
        _card(assets.character, movement_mode="approach", movement_direction="in", movement_pace="medium"),
    ]})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    char_chain = captured[0].split("[1:v]", 1)[1].split("[c0]", 1)[0]
    assert "scale=w='iw*(1+(" in char_chain


# ── Character micro-motion technique threading (Story 8.8) ─────────────────────


async def test_video_node_threads_resolved_card_motion_style(monkeypatch, tmp_path, assets):
    """A card's motion_style/motion_energy from the resolver reaches the
    filtergraph — a "hold" card gets no idle sine at all. [AC:6]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, motion_style="hold")]})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    overlay_stage = captured[0].split("[o0]")[0].rsplit(";", 1)[-1]
    assert "sin(" not in overlay_stage


async def test_video_node_two_cards_different_styles_decorrelate(monkeypatch, tmp_path, assets):
    """Two simultaneous cards with distinct motion_style each render their own
    technique — a tremble card's shake sits alongside a hold card's silence. [AC:8]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [
        _card(assets.character, card_key="SCP-096", position="left", depth="near", motion_style="tremble"),
        _card(assets.character2, card_key="STOCK-d-class", position="right", depth="far", motion_style="hold"),
    ]})

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member("SCP-096", position="left", depth="near"),
              _cast_member("STOCK-d-class", position="right", depth="far")],
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    fc = captured[0]
    # [Story 11.3 AC:5] tremble's shake is fBm now — smoothstep marker instead
    # of the retired sin(t*TREMBLE_FREQ) sine.
    assert "3-2*" in fc  # the tremble card's shake is present
    # far/hold is card index 0 (stable depth sort) → input [1:v], char_chain up to [c0]
    hold_chain = fc.split("[1:v]", 1)[1].split("[c0]", 1)[0]
    # Story 11.1: drop the motion-agnostic feather stage first — its radius
    # clamp contains floor(), which this no-motion-terms proxy would trip on.
    hold_chain = hold_chain.removeprefix(f"{video.CARD_EDGE_FEATHER},")
    assert "sin(" not in hold_chain and "floor(" not in hold_chain


# ── Post-processing filters integration (Story 7.2) ────────────────────────────


async def test_video_node_character_post_fx_placement(monkeypatch, tmp_path, assets):
    """Post filter sits after overlay, before subtitles, on the cast-card path. [AC:4,6]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, post_fx_enabled=True))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(
        1, image=assets.image, cast=[_cast_member()],
        audio=assets.audio, subtitle=assets.subtitle, mood="dread",
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    fc = captured[0]
    p = MOOD_GRADE_PARAMS["dread"]
    assert f"eq=saturation={p['saturation']}" in fc
    assert "vignette=angle=PI/5" in fc
    assert "noise=alls=8:allf=t+u" in fc
    assert fc.index("overlay=") < fc.index("eq=saturation=") < fc.index("subtitles=")


async def test_video_node_background_only_post_fx_placement(monkeypatch, tmp_path, assets):
    """Post filter sits between zoompan and subtitles on the background-only path. [AC:5,6]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, post_fx_enabled=True))
    fake_vf, captured_vf = _capture_arg_flag("-vf")
    monkeypatch.setattr(video, "_run_ffmpeg", fake_vf)

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, mood="clinical")
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    vf = captured_vf[0]
    p = MOOD_GRADE_PARAMS["clinical"]
    assert f"eq=saturation={p['saturation']}" in vf
    assert vf.index("zoompan") < vf.index("eq=saturation=") < vf.index("subtitles=")


async def test_video_node_post_fx_disabled_no_fragment(monkeypatch, tmp_path, assets):
    """post_fx_enabled=False: today's ungraded output, no eq/vignette/noise. [AC:8]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, post_fx_enabled=False))
    fake_vf, captured_vf = _capture_arg_flag("-vf")
    monkeypatch.setattr(video, "_run_ffmpeg", fake_vf)

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, mood="dread")
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    vf = captured_vf[0]
    assert "eq=" not in vf
    assert "vignette=" not in vf
    assert "noise=" not in vf


async def test_video_node_post_fx_unknown_mood_falls_back(monkeypatch, tmp_path, assets):
    """Missing mood key (pre-mood checkpointed scene) still renders via DEFAULT_MOOD. [AC:9]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, post_fx_enabled=True))
    fake_vf, captured_vf = _capture_arg_flag("-vf")
    monkeypatch.setattr(video, "_run_ffmpeg", fake_vf)

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)  # no mood key
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    p = MOOD_GRADE_PARAMS[DEFAULT_MOOD]
    assert f"eq=saturation={p['saturation']}" in captured_vf[0]


async def test_chapter_card_post_fx_placement(monkeypatch, tmp_path):
    """Chapter card's post filter sits before drawtext. [AC:7]"""
    captured: list[tuple] = []

    async def _fake(*args):
        captured.append(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)

    await video._compose_chapter_card(
        "- 1 -", 1, tmp_path, 1.75, mood="escalation", post_fx_enabled=True,
    )

    args = list(captured[0])
    vf = args[args.index("-vf") + 1]
    p = MOOD_GRADE_PARAMS["escalation"]
    assert f"eq=saturation={p['saturation']}" in vf
    assert vf.index("eq=saturation=") < vf.index("drawtext=")


async def test_chapter_card_post_fx_disabled_no_fragment(monkeypatch, tmp_path):
    """post_fx_enabled=False (default): card renders exactly today's vf. [AC:8]"""
    captured: list[tuple] = []

    async def _fake(*args):
        captured.append(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)

    await video._compose_chapter_card("- 1 -", 1, tmp_path, 1.75)

    args = list(captured[0])
    vf = args[args.index("-vf") + 1]
    assert "eq=" not in vf
    assert vf.startswith("drawtext=")


async def test_video_node_chapter_card_uses_upcoming_scene_mood(monkeypatch, tmp_path, assets):
    """[AC:7] The card between scene 1 and 2 is graded to scene 2's mood, not scene 1's."""
    monkeypatch.setattr(
        video, "_settings",
        lambda: _settings_ns(tmp_path, chapter_cards=True, post_fx_enabled=True),
    )
    calls: list[tuple] = []

    async def _rec(*args):
        calls.append(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _rec)

    scene1 = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, mood="dread")
    scene2 = _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, mood="revelation")
    out = await video_node(_state([scene1, scene2]))

    assert out.get("error") is None
    card_call = next(c for c in calls if "drawtext=" in c[c.index("-vf") + 1])
    vf = card_call[card_call.index("-vf") + 1]
    p = MOOD_GRADE_PARAMS["revelation"]
    assert f"eq=saturation={p['saturation']}" in vf and f"gamma={p['gamma']}" in vf


def test_config_post_fx_enabled_default_true():
    """Settings.post_fx_enabled defaults true, per AC:8."""
    from yt_flow.config import Settings

    assert Settings.model_fields["post_fx_enabled"].default is True


# ── Sound design integration (Story 7.1) ───────────────────────────────────────


@pytest.fixture
def sound_assets(tmp_path, monkeypatch):
    """Point sound_design.MOOD_ASSET_PATHS at real tmp files for the default mood."""
    import yt_flow.pipeline.nodes.sound_design as sound_design
    paths = {
        "bgm": tmp_path / "bgm.mp3",
        "ambient": tmp_path / "ambient.mp3",
        "stinger": tmp_path / "stinger.mp3",
    }
    for p in paths.values():
        p.write_bytes(b"\x00")
    monkeypatch.setitem(sound_design.MOOD_ASSET_PATHS, sound_design.DEFAULT_MOOD, paths)
    return paths


async def test_video_node_character_sound_design_enabled(monkeypatch, tmp_path, assets, sound_assets):
    """Cast-card branch + sound_design_enabled: bgm/ambient/stinger inputs + [aout] map. [AC:3,4]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, sound_design_enabled=True))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    args = list(calls[0])
    assert str(sound_assets["bgm"]) in args
    assert str(sound_assets["ambient"]) in args
    assert str(sound_assets["stinger"]) in args
    assert "[aout]" in args
    fc = args[args.index("-filter_complex") + 1]
    assert "sidechaincompress=" in fc
    assert "[2:a]" in fc  # narration referenced inside the ducking fragment


async def test_video_node_background_only_sound_design_enabled(monkeypatch, tmp_path, assets, sound_assets):
    """Background-only branch migrates -vf -> -filter_complex when sound design is on
    (ffmpeg forbids -vf + -filter_complex together). [AC:3,4]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, sound_design_enabled=True))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    args = list(calls[0])
    assert "-vf" not in args
    assert "-filter_complex" in args
    assert "[vout]" in args
    assert "[aout]" in args
    fc = args[args.index("-filter_complex") + 1]
    assert "subtitles=" in fc
    assert "fontsdir='" in fc  # Story 5.18 AC:6 — bundled Pretendard, background-only sound-design branch too
    assert "zoompan" in fc


async def test_video_node_sound_design_disabled_unchanged(monkeypatch, tmp_path, assets, sound_assets):
    """sound_design_enabled=False: no sound-design inputs, no [aout], -vf path preserved. [AC:8]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, sound_design_enabled=False))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    args = list(calls[0])
    assert "-vf" in args
    assert "-filter_complex" not in args
    assert str(sound_assets["bgm"]) not in args
    assert "[aout]" not in args


async def test_video_node_character_sound_design_and_post_fx_together(
    monkeypatch, tmp_path, assets, sound_assets,
):
    """[Review] Story 7.1 + 7.2 intersection, cast-card path: sound-design mix and the
    post-fx fragment both land in the same filter_complex."""
    monkeypatch.setattr(
        video, "_settings",
        lambda: _settings_ns(tmp_path, sound_design_enabled=True, post_fx_enabled=True),
    )
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(
        1, image=assets.image, cast=[_cast_member()],
        audio=assets.audio, subtitle=assets.subtitle, mood="dread",
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    args = list(calls[0])
    fc = args[args.index("-filter_complex") + 1]
    assert "sidechaincompress=" in fc
    assert "[aout]" in args
    p = MOOD_GRADE_PARAMS["dread"]
    assert f"eq=saturation={p['saturation']}" in fc
    assert fc.index("overlay=") < fc.index("eq=saturation=") < fc.index("subtitles=")


async def test_video_node_background_only_sound_design_and_post_fx_together(
    monkeypatch, tmp_path, assets, sound_assets,
):
    """[Review] Story 7.1 + 7.2 intersection, background-only path: sound-design mix
    and the post-fx fragment both land in the same filter_complex."""
    monkeypatch.setattr(
        video, "_settings",
        lambda: _settings_ns(tmp_path, sound_design_enabled=True, post_fx_enabled=True),
    )
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, mood="clinical")
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    args = list(calls[0])
    fc = args[args.index("-filter_complex") + 1]
    assert "sidechaincompress=" in fc
    assert "[aout]" in args
    p = MOOD_GRADE_PARAMS["clinical"]
    assert f"eq=saturation={p['saturation']}" in fc
    assert fc.index("zoompan") < fc.index("eq=saturation=") < fc.index("subtitles=")


def test_validate_scene_assets_sound_design_enabled_missing_asset_fails_fast(assets, tmp_path, monkeypatch):
    """[AC:5] Missing mood asset file fails before ffmpeg when sound design is on."""
    import yt_flow.pipeline.nodes.sound_design as sound_design
    monkeypatch.setitem(
        sound_design.MOOD_ASSET_PATHS, sound_design.DEFAULT_MOOD,
        {
            "bgm": tmp_path / "missing.mp3",
            "ambient": tmp_path / "missing2.mp3",
            "stinger": tmp_path / "missing3.mp3",
        },
    )
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    with pytest.raises(FileNotFoundError, match="sound design"):
        _validate_scene_assets([scene], sound_design_enabled=True)


def test_validate_scene_assets_sound_design_disabled_skips_check(assets):
    """[AC:8] sound_design_enabled=False: no mood-asset lookup even if files don't exist."""
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    _validate_scene_assets([scene], sound_design_enabled=False)  # must not raise


async def test_trace_records_card_counts(monkeypatch, tmp_path, assets):
    """Trace metadata gains per-scene card counts + motion params. [AC:4] [Story 8.3]"""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    await video_node(_state([scene]))

    assert captured.get("card_counts") == [1]
    effects = captured["effects"]
    assert effects[0]["character_overlay"] is True


async def test_trace_records_motion_style_counts(monkeypatch, tmp_path, assets):
    """[Story 8.8 AC:10] Trace metadata aggregates counts per motion_style plus
    the active constants table version."""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))
    _inject_resolver(monkeypatch, {"1:S001": [
        _card(assets.character, card_key="SCP-096", position="left", motion_style="tremble"),
        _card(assets.character2, card_key="STOCK-d-class", position="right", motion_style="hold"),
    ]})

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member("SCP-096", position="left"), _cast_member("STOCK-d-class", position="right")],
    )
    await video_node(_state([scene]))

    assert captured.get("motion_style_counts") == {"tremble": 1, "hold": 1}


async def test_trace_records_movement_mode_and_pace_counts(monkeypatch, tmp_path, assets):
    """[Story 8.9 AC:12] Trace metadata aggregates counts per movement_mode and
    movement_pace, non-fatal like 8.8's motion_style_counts."""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))
    _inject_resolver(monkeypatch, {"1:S001": [
        _card(assets.character, card_key="SCP-096", position="left",
              movement_mode="enter", movement_direction="left", movement_pace="fast"),
        _card(assets.character2, card_key="STOCK-d-class", position="right"),
    ]})

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member("SCP-096", position="left"), _cast_member("STOCK-d-class", position="right")],
    )
    await video_node(_state([scene]))

    assert captured.get("movement_mode_counts") == {"enter": 1, "anchored": 1}
    assert captured.get("movement_pace_counts") == {"fast": 1, "slow": 1}


async def test_trace_character_overlay_false_when_absent(monkeypatch, tmp_path, assets):
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    await video_node(_state([scene]))

    assert captured.get("card_counts") == [0]
    assert captured["effects"][0]["character_overlay"] is False


async def test_trace_records_cast_resolution_metadata(monkeypatch, tmp_path, assets):
    """cast_resolution metadata (replaces 1.13's angle_selection) reports fallback usage."""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, fallback=True)]})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    await video_node(_state([scene]))

    assert captured["cast_resolution"]["total_cards"] == 1
    assert captured["cast_resolution"]["fallback_used"] == 1


# ── integration test (skipped without ffmpeg+ffprobe) ────────────────────────


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg or ffprobe not installed",
)
async def test_join_with_fades_integration(tmp_path):
    """Real FFmpeg: scene + black hold + scene → fade+concat join. [Story 5.16 AC:1,6]

    Tests _join_with_fades directly with color-source segments (no image/subtitle
    complexity) to verify the new no-overlap duration formula: total = Σdur +
    holds × BLACK_HOLD_DURATION (no offset subtraction, unlike xfade).
    """
    dur1, dur2 = 1.0, 1.0

    async def _make_seg(path: Path, color: str, dur: float) -> None:
        rc, _ = await _run_ffmpeg(
            "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=64x36:r=25:d={dur}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=8000:duration={dur}",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(path),
        )
        assert rc == 0, f"segment creation failed for {path}"

    from yt_flow.pipeline.nodes.video import _run_ffmpeg
    seg1, hold, seg2 = tmp_path / "seg1.mp4", tmp_path / "hold.mp4", tmp_path / "seg2.mp4"
    await _make_seg(seg1, "blue", dur1)
    await _make_seg(hold, "black", BLACK_HOLD_DURATION)
    await _make_seg(seg2, "red", dur2)

    output = tmp_path / "out.mp4"
    await _join_with_fades(
        [
            (seg1, dur1, 0.0, FADE_DURATION),
            (hold, BLACK_HOLD_DURATION, 0.0, 0.0),
            (seg2, dur2, FADE_DURATION, 0.0),
        ],
        output,
    )
    assert output.exists()

    def _stream_duration(stream: str) -> float:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", stream,
             "-show_entries", "stream=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(output)],
            capture_output=True, text=True,
        )
        out = result.stdout.strip()
        assert out, f"ffprobe returned no duration for stream {stream!r} — stream missing? stderr: {result.stderr}"
        return float(out)

    expected = dur1 + dur2 + BLACK_HOLD_DURATION
    video_dur = _stream_duration("v:0")
    audio_dur = _stream_duration("a:0")
    assert abs(video_dur - expected) < 0.5, f"Video duration {video_dur:.2f}s ≠ expected {expected:.2f}s"
    # [Story 5.9 AC:3, preserved] audio lands on the same combined-output
    # duration as video — now trivially true, concat has no drift to accumulate.
    assert abs(audio_dur - expected) < 0.5, f"Audio duration {audio_dur:.2f}s ≠ expected {expected:.2f}s"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_character_overlay_filtergraph_renders(tmp_path):
    """Real FFmpeg: the layered zoompan→overlay(eval=frame) filtergraph is valid and
    renders rc=0. Guards against a syntax/eval regression that live ffmpeg would reject."""
    from yt_flow.pipeline.nodes.video import _run_ffmpeg, _zoompan_filter

    spec = EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    zp = _zoompan_filter(spec, duration=1.0)
    fc = (
        f"[0:v]{zp}[bg];"
        f"[1:v]{_character_scale_filter()}[char];"
        f"[bg][char]{_overlay_filter()}[out]"
    )

    out = tmp_path / "ov.mp4"
    rc, stderr = await _run_ffmpeg(
        "-y",
        "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=1",
        "-f", "lavfi", "-i", "color=c=red@0.5:s=64x64:r=25:d=1,format=rgba",
        "-filter_complex", fc,
        "-map", "[out]",
        "-frames:v", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out),
    )
    assert rc == 0, f"layered filtergraph rejected by ffmpeg: {stderr[-500:]}"
    assert out.exists()


def test_build_card_chain_feathers_card_alpha_first():
    """Story 11.1 AC6: the 41 existing card assets keep their binary cutout edge,
    so the shared card chain (fast-path + 8.11 per-shot both route here) feathers
    the alpha at composite time. Must be the FIRST stage of the card chain so
    every later scale stage preserves/shrinks the soft edge instead of re-hardening it."""
    spec = EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    chain_parts, _ = video._build_card_chain(
        _legacy_motion("x.png", spec, 2.0, bg_chain="null"),
        [{"depth": "mid"}], 2.0, None, composite_harmonization_tier=0,
    )
    card_stage = next(p for p in chain_parts if p.startswith("[1:v]"))
    assert card_stage.startswith(f"[1:v]{video.CARD_EDGE_FEATHER},")
    # alpha-only: color planes untouched (lr/cr zero)
    assert "lr=0" in video.CARD_EDGE_FEATHER and "cr=0" in video.CARD_EDGE_FEATHER


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_card_feather_filtergraph_renders(tmp_path):
    """Real FFmpeg: the feather stage prepended to the card chain is accepted and
    renders rc=0 (Story 11.1 AC6 live check — boxblur inline, no split needed,
    so the 'label consumed twice' hazard never arises)."""
    from yt_flow.pipeline.nodes.video import _run_ffmpeg, _zoompan_filter

    spec = EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    zp = _zoompan_filter(spec, duration=1.0)
    fc = (
        f"[0:v]{zp}[bg];"
        f"[1:v]{video.CARD_EDGE_FEATHER},{_character_scale_filter()}[char];"
        f"[bg][char]{_overlay_filter()}[out]"
    )

    out = tmp_path / "feather.mp4"
    rc, stderr = await _run_ffmpeg(
        "-y",
        "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=1",
        "-f", "lavfi", "-i", "color=c=red@0.5:s=64x64:r=25:d=1,format=rgba",
        "-filter_complex", fc,
        "-map", "[out]",
        "-frames:v", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out),
    )
    assert rc == 0, f"feathered filtergraph rejected by ffmpeg: {stderr[-500:]}"
    assert out.exists()


@pytest.mark.parametrize("style", sorted(cm._STYLE_TERMS))
async def test_motion_style_filtergraph_renders_real_ffmpeg(tmp_path, style):
    """Real FFmpeg: every motion_style's overlay + scale-pulse expressions parse
    and render rc=0 — a syntax regression in axis_terms/_term_expr would be
    caught here even though the string-level unit tests above never invoke
    ffmpeg. [Story 8.8 AC:11]"""
    from yt_flow.pipeline.nodes.video import _run_ffmpeg, _zoompan_filter

    spec = EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    zp = _zoompan_filter(spec, duration=1.0)
    char_chain = _character_scale_filter()
    pulse = video._motion_scale_filter(style, "high")
    if pulse:
        char_chain += f",{pulse}"
    overlay = _overlay_filter(motion_style=style, motion_energy="high")
    fc = f"[0:v]{zp}[bg];[1:v]{char_chain}[char];[bg][char]{overlay}[out]"

    out = tmp_path / f"ov_{style}.mp4"
    rc, stderr = await _run_ffmpeg(
        "-y",
        "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=1",
        "-f", "lavfi", "-i", "color=c=red@0.5:s=64x64:r=25:d=1,format=rgba",
        "-filter_complex", fc,
        "-map", "[out]",
        "-frames:v", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out),
    )
    assert rc == 0, f"style={style!r} filtergraph rejected by ffmpeg: {stderr[-500:]}"
    assert out.exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize(
    ("mode", "direction"),
    [("enter", "left"), ("exit", "right"), ("cross", "right"), ("approach", "in"), ("retreat", "out")],
)
async def test_movement_mode_filtergraph_renders_real_ffmpeg(tmp_path, mode, direction):
    """Real FFmpeg: every movement_mode's overlay + movement-scale expressions
    parse and render rc=0 — a syntax regression in build_movement_terms would
    be caught here even though the string-level unit tests never invoke
    ffmpeg. [Story 8.9 AC:13]"""
    from yt_flow.pipeline.nodes.video import _run_ffmpeg, _zoompan_filter

    spec = EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=video.ZOOM_IN_MAX)
    zp = _zoompan_filter(spec, duration=1.0)
    char_chain = _character_scale_filter()
    movement_scale = video._movement_scale_filter(mode, direction, "medium", "center", "near", 1.0)
    if movement_scale:
        char_chain += f",{movement_scale}"
    overlay = _overlay_filter(
        duration=1.0, movement_mode=mode, movement_direction=direction, movement_pace="medium",
    )
    fc = f"[0:v]{zp}[bg];[1:v]{char_chain}[char];[bg][char]{overlay}[out]"

    out = tmp_path / f"ov_{mode}.mp4"
    rc, stderr = await _run_ffmpeg(
        "-y",
        "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=1",
        "-f", "lavfi", "-i", "color=c=red@0.5:s=64x64:r=25:d=1,format=rgba",
        "-filter_complex", fc,
        "-map", "[out]",
        "-frames:v", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out),
    )
    assert rc == 0, f"mode={mode!r} filtergraph rejected by ffmpeg: {stderr[-500:]}"
    assert out.exists()


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg or ffprobe not installed",
)
async def test_compose_scene_sound_design_terminates_and_matches_duration(tmp_path, monkeypatch):
    """Real FFmpeg, both branches: sound-design-enabled `_compose_scene` must
    finish quickly and produce a segment whose length matches the scene's
    audio_duration. Regression guard: `-shortest` alone does not reliably
    bound the infinitely-looped `-loop 1` background image against a
    filter-graph-produced `[aout]` pad — verified to hang indefinitely on real
    ffmpeg without an explicit `-t {duration}` cap. [AC:3,4]"""
    import yt_flow.pipeline.nodes.sound_design as sound_design

    bg = tmp_path / "bg.png"
    rc, _ = await video._run_ffmpeg(
        "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x36:r=25:d=1", "-frames:v", "1", str(bg),
    )
    assert rc == 0
    narration_dur = 2.0
    narration = tmp_path / "narr.mp3"
    rc, _ = await video._run_ffmpeg(
        "-y", "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=8000:duration={narration_dur}", str(narration),
    )
    assert rc == 0
    subtitle = tmp_path / "sub.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:02,000\nhi\n\n", encoding="utf-8")

    mood_paths = {}
    for role, freq in (("bgm", 440), ("ambient", 330), ("stinger", 550)):
        p = tmp_path / f"{role}.mp3"
        rc, _ = await video._run_ffmpeg(
            "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=8000:duration=1.0", str(p),
        )
        assert rc == 0
        mood_paths[role] = p
    monkeypatch.setitem(sound_design.MOOD_ASSET_PATHS, sound_design.DEFAULT_MOOD, mood_paths)

    def _stream_duration(path: Path) -> float:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True,
        )
        return float(result.stdout.strip())

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    for label, scene_num, cards in (("background-only", 1, []), ("cast-card", 2, [_card(str(bg))])):
        scene = _scene(
            scene_num, image=str(bg), audio=str(narration), subtitle=str(subtitle),
            audio_duration=narration_dur,
        )
        seg_path, _spec, _has_char = await asyncio.wait_for(
            video._compose_scene(
                scene, scene_num, out_dir, cards_by_shot={"S001": cards}, sound_design_enabled=True,
            ),
            timeout=15,
        )
        assert seg_path.exists()
        seg_dur = _stream_duration(seg_path)
        assert abs(seg_dur - narration_dur) < 0.5, (
            f"{label} branch: segment duration {seg_dur:.2f}s should match "
            f"narration ({narration_dur}s), not run away on the looped sound-design beds"
        )


async def test_assemble_scene_normalizes_sar_before_concat(monkeypatch, tmp_path):
    """[Story 8.11] Every clip is scale/pad/setsar-normalized before concat.

    Regression guard: a 1344x768 generated background scaled to the canvas
    leaves SAR 4600:4599, and mixing it with SAR 1:1 clips made concat abort
    the whole video stage ("Input link ... do not match the corresponding
    output link").
    """
    captured = _capture_filter(monkeypatch)
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4"]

    await video._assemble_scene_from_clips(
        clips, 2.0, tmp_path / "seg_001.mp4",
        audio_path=str(tmp_path / "n.wav"), subtitle_path=str(tmp_path / "s.srt"),
        mood="clinical", sound_design_enabled=False, post_fx_enabled=False,
        include_stinger=False,
    )

    fc = captured[0]
    for i in range(len(clips)):
        assert (
            f"[{i}:v]scale={video.COMP_W}:{video.COMP_H}:force_original_aspect_ratio=decrease,"
            f"pad={video.COMP_W}:{video.COMP_H}:(ow-iw)/2:(oh-ih)/2,setsar=1[cn{i}]"
        ) in fc
    # concat consumes the normalized labels, not the raw inputs — and stays a hard cut.
    assert "[cn0][cn1]concat=n=2:v=1:a=0[concat_v]" in fc
    assert "[0:v][1:v]concat" not in fc
    assert "xfade" not in fc


# ── Per-shot cut assembly integration (Story 8.11) ────────────────────────────


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg or ffprobe not installed",
)
async def test_per_shot_cut_assembly_integration(monkeypatch, tmp_path):
    """Real FFmpeg: a 3-shot scene cuts into 3 distinct-color clips, each
    timed to its own sentence window, joined into one segment. [AC:1,2,3,9]

    Regression guard for the bug this story fixes: 87 shots generated, 8 used
    (one frozen Ken-Burns image per scene) — here 3 shots must all appear on
    screen at their own window, not just the first.
    """
    async def _solid_png(path: Path, color: str) -> None:
        rc, _ = await video._run_ffmpeg(
            "-y", "-f", "lavfi", "-i", f"color=c={color}:s=4x4:r=1:d=1", "-frames:v", "1", str(path),
        )
        assert rc == 0, f"solid-color fixture render failed for {color}"

    red, green, blue = tmp_path / "red.png", tmp_path / "green.png", tmp_path / "blue.png"
    await _solid_png(red, "red")
    await _solid_png(green, "green")
    await _solid_png(blue, "blue")
    image2 = tmp_path / "image2.png"
    await _solid_png(image2, "white")

    narration_dur = 6.0
    narration = tmp_path / "narr.wav"
    rc, _ = await video._run_ffmpeg(
        "-y", "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=8000:duration={narration_dur}", str(narration),
    )
    assert rc == 0
    subtitle = tmp_path / "sub.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:06,000\nhi\n\n", encoding="utf-8")

    audio2 = tmp_path / "narr2.wav"
    rc, _ = await video._run_ffmpeg(
        "-y", "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=8000:duration=1.0", str(audio2),
    )
    assert rc == 0
    subtitle2 = tmp_path / "sub2.srt"
    subtitle2.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n", encoding="utf-8")

    def _bg_shot(shot_id: str, sentence_idx: int, image_path: Path) -> dict:
        return {
            "shot_id": shot_id, "sentence_indices": [sentence_idx], "image_prompt": "p",
            "negative_prompt": "n", "camera_angle": None, "camera_movement": None,
            "image_path": str(image_path), "cast": [], "location_key": None,
        }

    scene1 = {
        "scene_num": 1,
        "narration": "빨강. 초록. 파랑.",
        "shots": [_bg_shot("S001", 0, red), _bg_shot("S002", 1, green), _bg_shot("S003", 2, blue)],
        "audio_path": str(narration), "audio_duration": narration_dur,
        "word_timings": [
            {"word": "빨강", "start_sec": 0.0, "end_sec": 2.0},
            {"word": "초록", "start_sec": 2.0, "end_sec": 4.0},
            {"word": "파랑", "start_sec": 4.0, "end_sec": 6.0},
        ],
        "subtitle_path": str(subtitle), "mood": "clinical", "title": "", "kicker": "",
        "display_narration": "빨강. 초록. 파랑.",
    }
    scene2 = {
        "scene_num": 2,
        "narration": "하나.",
        "shots": [_bg_shot("S001", 0, image2)],
        "audio_path": str(audio2), "audio_duration": 1.0, "word_timings": [],
        "subtitle_path": str(subtitle2), "mood": "clinical", "title": "", "kicker": "",
        "display_narration": "하나.",
    }

    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, min_shot_clip_sec=0.0))
    out = await video_node(_state([scene1, scene2], run_id="run-cut"))

    assert out.get("error") is None
    run_dir = tmp_path / "run-cut"
    shot_clips = sorted((run_dir / "shots").glob("scene_001_*.mp4"))
    assert len(shot_clips) == 3  # AC:9 — cut count == kept-shot count, no merge at min=0.0

    seg1 = run_dir / "seg_001.mp4"
    assert seg1.exists()

    async def _frame_rgb(path: Path, t: float) -> tuple[int, int, int]:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-ss", str(t), "-i", str(path),
            "-vframes", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        assert len(stdout) >= 3, f"no frame decoded at t={t}"
        return stdout[0], stdout[1], stdout[2]

    # Window midpoints: shot1 [0,2)->1.0, shot2 [2,4)->3.0, shot3 [4,6)->5.0.
    r1 = await _frame_rgb(seg1, 1.0)
    r2 = await _frame_rgb(seg1, 3.0)
    r3 = await _frame_rgb(seg1, 5.0)
    assert r1[0] > r1[1] + 40 and r1[0] > r1[2] + 40, f"expected red at t=1.0, got {r1}"
    assert r2[1] > r2[0] + 40 and r2[1] > r2[2] + 40, f"expected green at t=3.0, got {r2}"
    assert r3[2] > r3[0] + 40 and r3[2] > r3[1] + 40, f"expected blue at t=5.0, got {r3}"


# ── Story 1.13 / 8.3: cast card resolver injection integration ────────────────


async def test_cast_resolver_injection_composites_card(monkeypatch, tmp_path, assets):
    """When the resolver is injected, its card is composited into the segment."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    state = _state([scene], scp_id="SCP-096")
    out = await video_node(state)

    assert out.get("error") is None
    assert "overlay=" in captured[0]


async def test_cast_resolver_receives_scp_id_and_scenes(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    calls = []

    async def _resolver(scp_id, scenes):
        calls.append((scp_id, scenes))
        return {}

    _inject_resolver(monkeypatch, fn=_resolver)

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    await video_node(_state([scene], scp_id="SCP-096"))

    assert calls[0][0] == "SCP-096"
    assert calls[0][1][0]["scene_num"] == 1


async def test_cast_resolver_not_injected_renders_background_only(monkeypatch, tmp_path, assets):
    """Without an injected resolver, video_node works normally — background-only. [AD-10]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake_vf, captured_vf = _capture_arg_flag("-vf")
    monkeypatch.setattr(video, "_run_ffmpeg", fake_vf)
    monkeypatch.setattr(video, "_cast_resolver", None)

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert "overlay=" not in captured_vf[0]


async def test_cast_resolver_failure_is_non_fatal(monkeypatch, tmp_path, assets):
    """Resolver/LLM failure must never fail the pipeline — degrades to background-only. [AD-10]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake_vf, captured_vf = _capture_arg_flag("-vf")
    monkeypatch.setattr(video, "_run_ffmpeg", fake_vf)

    async def _failing_resolver(scp_id, scenes):
        raise RuntimeError("LLM down")

    _inject_resolver(monkeypatch, fn=_failing_resolver)

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None  # pipeline must not fail
    assert "overlay=" not in captured_vf[0]


async def test_cast_resolver_empty_dict_renders_background_only(monkeypatch, tmp_path, assets):
    """Resolver returning {} (nothing to overlay anywhere) → background-only render."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake_vf, captured_vf = _capture_arg_flag("-vf")
    monkeypatch.setattr(video, "_run_ffmpeg", fake_vf)
    _inject_resolver(monkeypatch, {})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert "overlay=" not in captured_vf[0]


async def test_cast_resolver_malformed_cards_are_skipped(monkeypatch, tmp_path, assets):
    """Malformed resolver entries degrade per-card, not by crashing video_node."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake_vf, captured_vf = _capture_arg_flag("-vf")
    monkeypatch.setattr(video, "_run_ffmpeg", fake_vf)
    _inject_resolver(monkeypatch, {"1:S001": ["bad-card", {"card_key": "SCP-096"}]})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert "overlay=" not in captured_vf[0]


async def test_opaque_card_fails_the_stage(monkeypatch, tmp_path, assets):
    """AC10: a resolved card that isn't RGBA is a hard, named error — no silent skip (D13)."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.opaque_card, card_key="SCP-096", angle="front")]})

    scene = _scene(1, image=assets.image, cast=[_cast_member()], audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is not None
    assert "SCP-096" in out["error"]
    assert "front" in out["error"]
    assert "opaque" in out["error"]


# ── chapter cards (Story 5.1) ─────────────────────────────────────────────────


def _capture_ffmpeg_calls():
    """Return (fake, calls) recording every ffmpeg invocation's arg list."""
    calls: list[tuple] = []

    async def _fake(*args):
        calls.append(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    return _fake, calls


def _output_files(calls, substr: str) -> list[str]:
    """Match each call's own output (last arg) — not the inputs it references —
    against a path-separator-anchored substring, so a tmp_path directory name
    that happens to contain the word (e.g. a test named ..._no_card_...) can't
    produce a false positive."""
    return [args[-1] for args in calls if isinstance(args[-1], str) and f"/{substr}" in args[-1]]


async def test_chapter_cards_enabled_creates_card_segments(monkeypatch, tmp_path, assets):
    """3-scene run with cards enabled renders 3 scene segs + 2 card segs and joins
    all 5 into one filtergraph, no black holds. [AC:2,5] [Story 5.16 AC:1,5]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=True))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(3, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    seg_outputs = _output_files(calls, "seg_")
    card_outputs = _output_files(calls, "card_")
    hold_outputs = _output_files(calls, "hold_")
    assert len(seg_outputs) == 3
    assert len(card_outputs) == 2
    assert not hold_outputs

    join_args = next(args for args in calls if isinstance(args[-1], str) and args[-1].endswith("video.mp4"))
    assert len([a for a in join_args if isinstance(a, str) and "/seg_" in a]) == 3
    assert len([a for a in join_args if isinstance(a, str) and "/card_" in a]) == 2

    # [Story 5.16 AC:1,2] card segments (audio bed, Story 5.1/5.16) go through the
    # same fade+concat join as ordinary scenes — no xfade/adelay/amix, no special-casing.
    filter_complex = join_args[join_args.index("-filter_complex") + 1]
    assert "concat=n=5:v=1:a=1" in filter_complex
    for token in ("xfade=", "acrossfade", "adelay", "amix"):
        assert token not in filter_complex


async def test_chapter_card_duration_is_clamped(monkeypatch, tmp_path, assets):
    """Out-of-range config is clamped to the accepted 1.5-2.5s card range. [AC:2] [Story 5.17 AC:6]"""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=True, chapter_card_duration_sec=99.0))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    await video_node(_state(scenes))

    assert captured.get("chapter_card_duration") == pytest.approx(2.5)
    assert video._chapter_card_duration(0.1) == pytest.approx(1.5)
    assert video._chapter_card_duration(1.75) == pytest.approx(1.75)


# ── Chapter-card title + kicker content (Story 5.17) ────────────────────────────


async def test_compose_chapter_card_writes_title_and_kicker_textfiles(tmp_path, monkeypatch):
    """[AC:4] Two drawtext chains when kicker is present; each textfile carries
    the exact Korean string (never inlined into the filtergraph)."""
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    await video._compose_chapter_card("첫 면담", 1, tmp_path, 1.75, kicker="개체가 입을 열다")

    vf = calls[0][calls[0].index("-vf") + 1]
    assert vf.count("drawtext=") == 2
    assert f"fontsize={video.CARD_FONT_SIZE}" in vf
    assert f"fontsize={video.CARD_KICKER_FONT_SIZE}" in vf
    assert (tmp_path / "card_001_label.txt").read_text(encoding="utf-8") == "첫 면담"
    assert (tmp_path / "card_001_kicker.txt").read_text(encoding="utf-8") == "개체가 입을 열다"


async def test_compose_chapter_card_title_stripped_to_first_line(tmp_path, monkeypatch):
    """A multi-line title is defended at the render layer too (not just
    build_scenes) — mirrors the kicker's own first-line stripping."""
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    await video._compose_chapter_card("  첫 면담  \n둘째 줄", 1, tmp_path, 1.75)

    assert (tmp_path / "card_001_label.txt").read_text(encoding="utf-8") == "첫 면담"


async def test_compose_chapter_card_no_kicker_renders_single_drawtext(tmp_path, monkeypatch):
    """[AC:4,8] Empty kicker (incl. today's "- N -" fallback): exactly one drawtext,
    no kicker textfile written."""
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    await video._compose_chapter_card("- 1 -", 1, tmp_path, 1.75)

    vf = calls[0][calls[0].index("-vf") + 1]
    assert vf.count("drawtext=") == 1
    assert not (tmp_path / "card_001_kicker.txt").exists()


async def test_compose_chapter_card_uses_bundled_fontfile(tmp_path, monkeypatch):
    """[AC:5] drawtext fontfile= points at the bundled Pretendard path, not a
    fontconfig-resolved system font."""
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    await video._compose_chapter_card("제목", 1, tmp_path, 1.75, kicker="상황")

    vf = calls[0][calls[0].index("-vf") + 1]
    assert f"fontfile='{video.CARD_FONT_PATH}'" in vf


async def test_video_node_card_passes_upcoming_scene_kicker(monkeypatch, tmp_path, assets):
    """[Task 3] video_node passes scenes[i+1]'s kicker to the card render."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=True))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
               title="둘째 씬", kicker="맥락 한 줄"),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    # boundary between scene 0 and scene 1 (index i=0) renders card index i+1=1
    assert (tmp_path / "run-001" / "card_001_label.txt").read_text(encoding="utf-8") == "둘째 씬"
    assert (tmp_path / "run-001" / "card_001_kicker.txt").read_text(encoding="utf-8") == "맥락 한 줄"


async def test_video_node_card_no_kicker_when_title_missing(monkeypatch, tmp_path, assets):
    """[AC:8] A kicker with no title is a partial/inconsistent state — the "- N -"
    fallback card must render with no kicker line, not fallback-title-plus-kicker."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=True))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
               kicker="맥락 한 줄"),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    assert (tmp_path / "run-001" / "card_001_label.txt").read_text(encoding="utf-8") == "- 2 -"
    assert not (tmp_path / "run-001" / "card_001_kicker.txt").exists()


# ── Stinger-on-card-entry sync (Story 5.17 AC:7) ────────────────────────────────


async def test_video_node_card_stinger_present_scene_after_card_suppressed(
    monkeypatch, tmp_path, assets, sound_assets,
):
    """The card carries the boundary's stinger; the scene right after a card omits
    its own baked scene-entry stinger. Scene 0 (no preceding card) keeps it."""
    monkeypatch.setattr(
        video, "_settings",
        lambda: _settings_ns(tmp_path, chapter_cards=True, sound_design_enabled=True),
    )
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    card_call = next(args for args in calls if isinstance(args[-1], str) and "/card_" in args[-1])
    assert str(sound_assets["stinger"]) in list(card_call)

    seg_calls = [args for args in calls if isinstance(args[-1], str) and "/seg_" in args[-1]]
    seg0_args, seg1_args = seg_calls[0], seg_calls[1]
    assert str(sound_assets["stinger"]) in list(seg0_args)  # scene 0: no preceding card
    assert str(sound_assets["stinger"]) not in list(seg1_args)  # scene 1: right after the card


async def test_video_node_no_cards_scene_stinger_unchanged(monkeypatch, tmp_path, assets, sound_assets):
    """[AC:7] Cards off: every scene keeps its own baked scene-entry stinger."""
    monkeypatch.setattr(
        video, "_settings",
        lambda: _settings_ns(tmp_path, chapter_cards=False, sound_design_enabled=True),
    )
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    seg_calls = [args for args in calls if isinstance(args[-1], str) and "/seg_" in args[-1]]
    for args in seg_calls:
        assert str(sound_assets["stinger"]) in list(args)


async def test_chapter_cards_disabled_no_card_render(monkeypatch, tmp_path, assets):
    """chapter_cards=False: no card render call; a black hold marks the dip instead.
    [AC:4] [Story 5.16 AC:1,5]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=False))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    assert not _output_files(calls, "card_")
    assert len(_output_files(calls, "hold_")) == 1

    join_args = next(args for args in calls if isinstance(args[-1], str) and args[-1].endswith("video.mp4"))
    filter_complex = join_args[join_args.index("-filter_complex") + 1]
    assert "concat=n=3:v=1:a=1" in filter_complex
    assert "card_" not in filter_complex


# ── Black-hold insertion (Story 5.16) ────────────────────────────────────────


async def test_black_hold_inserted_at_every_card_less_boundary(monkeypatch, tmp_path, assets):
    """[AC:5] Cards off, 3 scenes (2 boundaries): the join gets exactly (n-1) hold
    inputs, zero card inputs. Sound design off (default) reuses one shared hold
    file across both boundaries — same file, referenced twice in the join."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=False))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(3, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    assert not _output_files(calls, "card_")
    # ffmpeg renders to a .tmp.mp4 path, then _compose_black_hold renames it into
    # place atomically — the captured ffmpeg call's own output arg is the tmp name.
    assert _output_files(calls, "hold_") == [str(tmp_path / "run-001" / "hold_shared.tmp.mp4")]

    join_args = next(args for args in calls if isinstance(args[-1], str) and args[-1].endswith("video.mp4"))
    hold_inputs = [a for a in join_args if isinstance(a, str) and "/hold_" in a]
    assert hold_inputs == [str(tmp_path / "run-001" / "hold_shared.mp4")] * 2  # final (renamed) path, shared file


async def test_black_hold_per_boundary_file_when_sound_design_enabled(
    monkeypatch, tmp_path, assets, sound_assets,
):
    """[AC:3,5] Sound design on: each boundary's hold is a distinct render (moods
    may differ), so 2 boundaries render 2 hold files."""
    monkeypatch.setattr(
        video, "_settings",
        lambda: _settings_ns(tmp_path, chapter_cards=False, sound_design_enabled=True),
    )
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(3, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    assert not _output_files(calls, "card_")
    assert len(_output_files(calls, "hold_")) == 2


async def test_black_hold_zero_when_cards_enabled(monkeypatch, tmp_path, assets):
    """[AC:5] Cards on: zero hold segments render — the card is the dip."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=True))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    assert not _output_files(calls, "hold_")
    assert len(_output_files(calls, "card_")) == 1


async def test_black_hold_uses_ambient_bed_when_sound_design_enabled(
    monkeypatch, tmp_path, assets, sound_assets,
):
    """[AC:3] Hold audio is the incoming scene's mood ambient asset when sound
    design is on, looped and at AMBIENT_VOLUME — not anullsrc."""
    monkeypatch.setattr(
        video, "_settings",
        lambda: _settings_ns(tmp_path, chapter_cards=False, sound_design_enabled=True),
    )
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    hold_call = next(args for args in calls if isinstance(args[-1], str) and "/hold_" in args[-1])
    args = list(hold_call)
    assert str(sound_assets["ambient"]) in args
    assert "anullsrc" not in args
    assert f"volume={video.AMBIENT_VOLUME}" in args[args.index("-af") + 1]


async def test_black_hold_uses_anullsrc_when_sound_design_disabled(monkeypatch, tmp_path, assets):
    """[AC:3] Hold audio stays anullsrc silence when sound design is off (unchanged)."""
    monkeypatch.setattr(
        video, "_settings",
        lambda: _settings_ns(tmp_path, chapter_cards=False, sound_design_enabled=False),
    )
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    hold_call = next(args for args in calls if isinstance(args[-1], str) and "/hold_" in args[-1])
    args = list(hold_call)
    assert "anullsrc=channel_layout=stereo:sample_rate=44100" in args


async def test_card_uses_ambient_bed_when_sound_design_enabled(
    monkeypatch, tmp_path, assets, sound_assets,
):
    """[AC:3] Card audio bed is the upcoming scene's mood ambient asset when sound
    design is on, mixed with its mood stinger via -filter_complex (Story 5.17
    AC:7); card visuals (drawtext, self-fades) are unaffected."""
    monkeypatch.setattr(
        video, "_settings",
        lambda: _settings_ns(tmp_path, chapter_cards=True, sound_design_enabled=True),
    )
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    card_call = next(args for args in calls if isinstance(args[-1], str) and "/card_" in args[-1])
    args = list(card_call)
    assert str(sound_assets["ambient"]) in args
    assert str(sound_assets["stinger"]) in args
    fc = args[args.index("-filter_complex") + 1]
    assert "fade=t=in:st=0:d=0.25" in fc
    assert "drawtext=" in fc
    assert f"volume={video.AMBIENT_VOLUME}" in fc
    assert f"volume={video.STINGER_VOLUME}" in fc


async def test_card_and_hold_receive_zero_join_fades(monkeypatch, tmp_path, assets):
    """[AC:1,5] Cards/holds keep their own internal fades but get 0.0 join-fades
    from _join_with_fades — no double fade at their own edges."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=True))
    captured_filter = _capture_filter(monkeypatch)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    join_filter = captured_filter[-1]
    # scene0 fade-out, card gets no join-fade filter (index 1), scene1 fade-in.
    assert "[1:v]fade=" not in join_filter
    assert "concat=n=3:v=1:a=1" in join_filter


async def test_single_scene_no_card_no_join(monkeypatch, tmp_path, assets):
    """Single-scene run: no card, no join call — only the scene segment render. [AC:6]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=True))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    state = _state([_scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)])
    out = await video_node(state)

    assert out.get("error") is None
    assert len(calls) == 1  # only the single scene render, no card, no join
    assert not _output_files(calls, "card_")


async def test_trace_chapter_card_metadata(monkeypatch, tmp_path, assets):
    """Trace metadata reflects fadeblack transition + chapter-card state/count/duration. [AC:7]"""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=True, chapter_card_duration_sec=1.75))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    await video_node(_state(scenes))

    assert captured.get("chapter_cards_enabled") is True
    assert captured.get("chapter_card_count") == 1
    assert captured.get("chapter_card_duration") == pytest.approx(1.75)


async def test_trace_chapter_cards_disabled_metadata(monkeypatch, tmp_path, assets):
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=False))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    await video_node(_state(scenes))

    assert captured.get("chapter_cards_enabled") is False
    assert captured.get("chapter_card_count") == 0


def test_config_chapter_cards_default_true():
    """Settings.chapter_cards defaults true, per AC:2 ("YTFLOW_CHAPTER_CARDS=true (default true)")."""
    from yt_flow.config import Settings

    assert Settings.model_fields["chapter_cards"].default is True
    assert 1.5 <= Settings.model_fields["chapter_card_duration_sec"].default <= 2.0


def test_card_label_uses_fallback_when_no_title(assets):
    scene = _scene(3, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    assert video._card_label(scene) == "- 3 -"


def test_card_label_uses_real_title_when_scene_state_defines_it(assets):
    """[Story 5.17 AC:8] A non-empty scene title wins over the "- N -" fallback."""
    scene = _scene(3, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    scene["title"] = "The Discovery"  # type: ignore[typeddict-unknown-key]
    assert video._card_label(scene) == "The Discovery"


def test_card_font_resolves_to_bundled_pretendard():
    font = video._card_font()
    assert Path(font).exists()
    assert font == str(video.CARD_FONT_PATH)


def test_card_font_raises_when_bundled_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(video, "CARD_FONT_PATH", tmp_path / "missing.otf")
    with pytest.raises(RuntimeError, match="bundled card font not found"):
        video._card_font()


async def test_compose_chapter_card_integration(tmp_path):
    """Real FFmpeg: card segment renders with video+audio streams. [AC:2]"""
    from yt_flow.pipeline.nodes.video import _compose_chapter_card

    card_path = await _compose_chapter_card("- 1 -", 1, tmp_path, 1.75)
    assert card_path.exists()

    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(card_path)],
        capture_output=True, text=True,
    )
    stream_types = result.stdout.split()
    assert "video" in stream_types
    assert "audio" in stream_types


async def test_compose_chapter_card_bounds_infinite_audio(monkeypatch, tmp_path):
    captured: list[tuple] = []

    async def _fake(*args):
        captured.append(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)

    await video._compose_chapter_card("- 1 -", 1, tmp_path, 1.75)

    args = list(captured[0])
    assert "-t" in args
    assert args[args.index("-t") + 1] == "1.750"


# ── CC BY-SA attribution (Story 5.20) ─────────────────────────────────────────


def test_config_cc_attribution_default_true():
    from yt_flow.config import Settings

    assert Settings.model_fields["cc_attribution"].default is True


@pytest.mark.parametrize(("scp_id", "slug"), [
    ("SCP-049", "scp-049"),
    ("SCP-096", "scp-096"),
    ("SCP-682", "scp-682"),
    (" scp-999 ", "scp-999"),
])
def test_scp_wiki_slug(scp_id, slug):
    assert video._scp_wiki_slug(scp_id) == slug


def test_scp_nickname_known(monkeypatch):
    monkeypatch.setattr(video, "_scp_nicknames", None)
    assert video._scp_nickname("SCP-049") == "Plague Doctor"


def test_scp_nickname_unknown_is_tolerant(monkeypatch):
    monkeypatch.setattr(video, "_scp_nicknames", None)
    assert video._scp_nickname("SCP-9999") is None


def test_scp_nickname_missing_file_is_tolerant(monkeypatch):
    monkeypatch.setattr(video, "_scp_nicknames", None)
    monkeypatch.setattr(video, "SCP_DATA_PATH", Path("/no/such/scps.json"))
    assert video._scp_nickname("SCP-049") is None


def test_build_description_with_nickname():
    """[AC:3] SCP-049 → includes 'Plague Doctor'."""
    text = video.build_description_text("SCP-049", scp_nickname="Plague Doctor")
    assert "[SCP-049] Plague Doctor — SCP Foundation Wiki" in text
    assert "https://scp-wiki.wikidot.com/scp-049" in text


def test_build_description_without_nickname():
    """[AC:3] Unknown scp_id: no nickname, '— SCP Foundation Wiki' still present."""
    text = video.build_description_text("SCP-9999")
    assert "[SCP-9999] — SCP Foundation Wiki" in text
    assert "Plague Doctor" not in text


def test_build_description_slug():
    assert "scp-049" in video.build_description_text("SCP-049")
    assert "scp-682" in video.build_description_text("SCP-682")


def test_build_description_includes_license_links():
    text = video.build_description_text("SCP-049")
    assert "Licensed under CC BY-SA 3.0" in text
    assert video.CC_LICENSE_URL in text
    assert 'derivative work based on "SCP-049"' in text


def test_build_description_includes_image_source_line():
    """[AC:4] Image source is the same deterministic wiki URL regardless of
    whether the run's reference image actually came from the wiki or DDG."""
    text = video.build_description_text("SCP-049")
    assert "Image source: https://scp-wiki.wikidot.com/scp-049" in text


async def test_write_description_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "_scp_nicknames", None)
    path = await video._write_description_artifact(tmp_path, "SCP-999")
    assert path is not None
    assert path == tmp_path / "description.txt"
    text = path.read_text(encoding="utf-8")
    assert "The Tickle Monster" in text
    assert "scp-999" in text


async def test_write_description_artifact_failure_non_fatal(tmp_path, monkeypatch):
    def _raise(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", _raise)
    assert await video._write_description_artifact(tmp_path, "SCP-999") is None


async def test_compose_ending_credit_uses_distinct_filename(tmp_path, monkeypatch):
    """[Task 2 CRITICAL] never card_NNN.mp4 — must not collide with a chapter card."""
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    path = await video._compose_ending_credit("SCP-049", tmp_path)

    assert path == tmp_path / "credit_ending.mp4"
    assert path.exists()
    assert not (tmp_path / "card_000.mp4").exists()
    assert calls[0][-1] == str(tmp_path / "card_000.mp4")  # ffmpeg itself still wrote the card name


async def test_ending_credit_appended(monkeypatch, tmp_path, assets):
    """[AC:2] cc_attribution=True: a self-fading credit_ending.mp4 segment is
    appended after the last scene, carrying the attribution text/URL, at
    MAX_CARD_DURATION."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, cc_attribution=True))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes, scp_id="SCP-049"))

    assert out.get("error") is None
    assert len(_output_files(calls, "card_000")) == 1

    join_args = next(args for args in calls if isinstance(args[-1], str) and args[-1].endswith("video.mp4"))
    assert any(isinstance(a, str) and a.endswith("credit_ending.mp4") for a in join_args)

    label_file = tmp_path / "run-001" / "card_000_label.txt"
    kicker_file = tmp_path / "run-001" / "card_000_kicker.txt"
    assert label_file.read_text(encoding="utf-8") == "Based on 'SCP-049' from the SCP Foundation Wiki"
    kicker_text = kicker_file.read_text(encoding="utf-8")
    assert "CC BY-SA 3.0" in kicker_text and "scp-wiki.wikidot.com/scp-049" in kicker_text

    card_call = next(args for args in calls if str(args[-1]) == str(tmp_path / "run-001" / "card_000.mp4"))
    assert card_call[card_call.index("-t") + 1] == f"{video.MAX_CARD_DURATION:.3f}"


async def test_ending_credit_single_scene(monkeypatch, tmp_path, assets):
    """[AC:2] Single-scene run + cc_attribution=True: the join path is used
    (not the direct-replace fast path) so the ending card can be appended."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, cc_attribution=True))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    state = _state(
        [_scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)],
        scp_id="SCP-999",
    )
    out = await video_node(state)

    assert out.get("error") is None
    join_args = next(args for args in calls if isinstance(args[-1], str) and args[-1].endswith("video.mp4"))
    assert "-filter_complex" in join_args
    assert any(isinstance(a, str) and a.endswith("credit_ending.mp4") for a in join_args)


async def test_ending_credit_skipped_when_disabled(monkeypatch, tmp_path, assets):
    """cc_attribution=False (fixture default): no credit segment, no card_000
    textfiles, no description.txt, no ending_credit_error in the return dict."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake, calls = _capture_ffmpeg_calls()
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    assert not _output_files(calls, "card_000")
    assert not (tmp_path / "run-001" / "description.txt").exists()
    assert "ending_credit_error" not in out


async def test_ending_credit_failure_non_fatal(monkeypatch, tmp_path, assets):
    """[AC:5] Ending-card ffmpeg failure never fails the run — the join proceeds
    without the credit, and the error is recorded rather than raised."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, cc_attribution=True))
    captured: dict = {}
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    async def _fake(*args):
        out_path = str(args[-1])
        if "card_000" in out_path:
            return 1, "boom: codec missing"
        Path(out_path).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes, scp_id="SCP-049"))

    assert out.get("error") is None
    assert Path(out["video_path"]).exists()
    assert out["ending_credit_error"] is not None
    assert "boom" in out["ending_credit_error"]
    assert captured.get("ending_credit") is False
    assert "boom" in captured.get("ending_credit_error", "")


async def test_description_txt_written_when_enabled(monkeypatch, tmp_path, assets):
    """[AC:3] description.txt lands under workspace/{run_id}/ alongside video.mp4."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, cc_attribution=True))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene], scp_id="SCP-999"))

    assert out.get("error") is None
    desc = tmp_path / "run-001" / "description.txt"
    assert desc.exists()
    assert "The Tickle Monster" in desc.read_text(encoding="utf-8")


async def test_trace_metadata_includes_credit_fields(monkeypatch, tmp_path, assets):
    """[AC:6] _record_trace receives ending_credit/ending_credit_error."""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, cc_attribution=True))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    await video_node(_state([scene], scp_id="SCP-049"))

    assert captured.get("ending_credit") is True
    assert captured.get("ending_credit_error") is None


async def test_trace_metadata_credit_off(monkeypatch, tmp_path, assets):
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    await video_node(_state([scene]))

    assert captured.get("ending_credit") is False


# ── Camera noise stage (Story 11.3) ──────────────────────────────────────────


def _capture_args(monkeypatch):
    """Patch video._run_ffmpeg to record each call's full argument list."""
    calls: list[list[str]] = []

    async def _capture(*args):
        calls.append(list(args))
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _capture)
    return calls


def _video_filter_of(args: list[str]) -> str:
    """The call's video filter string, whichever of -vf/-filter_complex it used."""
    for flag in ("-vf", "-filter_complex"):
        if flag in args:
            return args[args.index(flag) + 1]
    raise AssertionError(f"no video filter flag in {args}")


def test_camera_shake_filter_locked_or_static_is_empty():
    """[AC:2] all-zero profile → "" → stage not attached, chain byte-identical."""
    assert video._camera_shake_filter("locked", 4.0, k=0) == ""
    assert video._camera_shake_filter("static", 4.0, k=3) == ""


def test_camera_shake_filter_chain_shape():
    """[AC:2] overscan scale → rotate → crop back to COMP, all t-driven."""
    f = video._camera_shake_filter("shake", 4.0, k=1)
    assert f.index("scale=") < f.index("rotate=") < f.index("crop=")
    assert "eval=frame" in f
    assert f"crop={video.COMP_W}:{video.COMP_H}" in f
    assert "random" not in f


def test_camera_shake_filter_k_decorrelates():
    """[AC:2] adjacent shots must not ride the same noise curve."""
    assert video._camera_shake_filter("shake", 4.0, k=0) != video._camera_shake_filter("shake", 4.0, k=1)


def test_camera_shake_filter_trauma_adds_decay_event():
    """[AC:3] trauma>0 adds the decaying event term; 0 leaves the idle band only."""
    calm = video._camera_shake_filter("shake", 4.0, k=0)
    hit = video._camera_shake_filter("shake", 4.0, k=0, trauma=0.8)
    assert calm != hit
    assert "max(0,1-" in hit and "max(0,1-" not in calm


def test_camera_shake_filter_margin_covers_crop():
    """[AC:2] the overscan scale factor must exceed 1 so crop never underruns."""
    from yt_flow.pipeline.nodes import camera_path as cp
    f = video._camera_shake_filter("shake", 4.0, k=0, trauma=0.8)
    assert f"{1.0 + cp.overscan_margin('shake', trauma=0.8):.6g}" in f
    assert "clip(" in f  # belt-and-suspenders clamp on crop x/y


async def test_render_fast_bg_only_shake_before_postfx_before_subtitles(monkeypatch, tmp_path, assets):
    """[AC:2] order invariant: shake → post-fx (lens space) → subtitles (screen space)."""
    calls = _capture_args(monkeypatch)
    shake = video._camera_shake_filter("shake", 2.0, k=0)
    await video._render_scene_fast(
        _legacy_motion(assets.image, EffectSpec("in-center", 1.0, 1.15), 2.0, shake=shake),
        2.0, tmp_path / "seg.mp4", 1,
        cards=[], mood="dread", audio_path=assets.audio, subtitle_path=assets.subtitle,
        sound_design_enabled=False, post_fx_enabled=True,
        include_stinger=True, composite_harmonization_tier=0,
    )
    vf = _video_filter_of(calls[0])
    assert vf.index("rotate=") < vf.index("vignette") < vf.index("subtitles=")


async def test_render_fast_card_branch_shake_before_postfx_before_subtitles(monkeypatch, tmp_path, assets):
    calls = _capture_args(monkeypatch)
    shake = video._camera_shake_filter("shake", 2.0, k=0)
    await video._render_scene_fast(
        _legacy_motion(assets.image, EffectSpec("in-center", 1.0, 1.15), 2.0, shake=shake),
        2.0, tmp_path / "seg.mp4", 1,
        cards=[_card(assets.character)], mood="dread", audio_path=assets.audio,
        subtitle_path=assets.subtitle,
        sound_design_enabled=False, post_fx_enabled=True,
        include_stinger=True, composite_harmonization_tier=0,
    )
    fc = _video_filter_of(calls[0])
    assert fc.index("overlay") < fc.index("rotate=") < fc.index("vignette") < fc.index("subtitles=")


async def test_render_fast_empty_shake_leaves_chain_unchanged(monkeypatch, tmp_path, assets):
    """[AC:2,6] "" → stage not attached: identical args to a call without the feature."""
    calls = _capture_args(monkeypatch)
    common = dict(
        cards=[], mood="dread", audio_path=assets.audio, subtitle_path=assets.subtitle,
        sound_design_enabled=False, post_fx_enabled=True,
        include_stinger=True, composite_harmonization_tier=0,
    )
    spec = EffectSpec("in-center", 1.0, 1.15)
    await video._render_scene_fast(
        _legacy_motion(assets.image, spec, 2.0, shake=""), 2.0, tmp_path / "a.mp4", 1, **common)
    await video._render_scene_fast(
        _legacy_motion(assets.image, spec, 2.0), 2.0, tmp_path / "a.mp4", 1, **common)
    assert calls[0] == calls[1]
    assert "rotate=" not in _video_filter_of(calls[0])


async def test_compose_shot_clip_attaches_shake_both_branches(monkeypatch, tmp_path, assets):
    calls = _capture_args(monkeypatch)
    shake = video._camera_shake_filter("shake", 2.0, k=0)
    shot = _shot(assets.image, "shake")
    spec = EffectSpec("in-center", 1.0, 1.15)
    await video._compose_shot_clip(
        shot, _legacy_motion(assets.image, spec, 2.0, shake=shake), 2.0, tmp_path / "bg.mp4",
        cards=[], mood=None, composite_harmonization_tier=0,
    )
    await video._compose_shot_clip(
        shot, _legacy_motion(assets.image, spec, 2.0, shake=shake), 2.0, tmp_path / "card.mp4",
        cards=[_card(assets.character)], mood=None, composite_harmonization_tier=0,
    )
    bg_vf = _video_filter_of(calls[0])
    assert "rotate=" in bg_vf and bg_vf.index("zoompan") < bg_vf.index("rotate=")
    card_fc = _video_filter_of(calls[1])
    assert "rotate=" in card_fc and card_fc.index("overlay") < card_fc.index("rotate=")
    # the shake stage output is what gets mapped
    assert calls[1][calls[1].index("-map") + 1] == "[shk]"


async def test_compose_scene_camera_off_attaches_no_stage(monkeypatch, tmp_path, assets):
    """[AC:6] kill switch: camera_noise_enabled=False → pre-11.3 chain."""
    calls = _capture_args(monkeypatch)
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
                   camera_movement="shake")
    await video._compose_scene(scene, 0, tmp_path, camera_noise_enabled=False)
    assert "rotate=" not in _video_filter_of(calls[0])


async def test_compose_scene_locked_attaches_no_stage(monkeypatch, tmp_path, assets):
    """[AC:2] locked profile is all-zero → no stage even with the feature on."""
    calls = _capture_args(monkeypatch)
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
                   camera_movement="locked")
    await video._compose_scene(scene, 0, tmp_path, camera_noise_enabled=True)
    assert "rotate=" not in _video_filter_of(calls[0])


async def test_compose_scene_camera_on_attaches_stage(monkeypatch, tmp_path, assets):
    calls = _capture_args(monkeypatch)
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
                   camera_movement="shake")
    await video._compose_scene(scene, 0, tmp_path, camera_noise_enabled=True)
    assert "rotate=" in _video_filter_of(calls[0])


# ── trauma wiring (Story 11.3 AC:3) ──────────────────────────────────────────


def _two_clip_scene(assets, tmp_path):
    """A scene whose plan_shot_clips yields two clips (two sentences, two shots)."""
    words = ["첫", "문장", "이다", "둘째", "문장", "이다"]
    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        camera_movement="shake", mood="escalation",
        narration="첫 문장 이다. 둘째 문장 이다.",
        word_timings=[
            {"word": w, "start_sec": i * 1.5, "end_sec": (i + 1) * 1.5} for i, w in enumerate(words)
        ],
        audio_duration=9.0,
    )
    second = _shot(assets.image, "shake", shot_id="S002")
    second["sentence_indices"] = [1]
    scene["shots"].append(second)
    return scene


@pytest.mark.parametrize("sound,stinger,expect_trauma", [
    (True, True, True),    # stinger plays at scene t=0 → synced by construction
    (True, False, False),  # chapter card carries the hit → scene shake would desync
    (False, True, False),  # no sound design → no hit to sync to
    (False, False, False),
])
async def test_compose_scene_trauma_conditions(monkeypatch, tmp_path, assets, sound, stinger, expect_trauma):
    calls = _capture_args(monkeypatch)
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
                   camera_movement="shake", mood="escalation")
    await video._compose_scene(
        scene, 0, tmp_path, camera_noise_enabled=True,
        sound_design_enabled=sound, include_stinger=stinger,
    )
    assert ("max(0,1-" in _video_filter_of(calls[0])) is expect_trauma


async def test_compose_scene_trauma_first_clip_only(monkeypatch, tmp_path, assets):
    """[AC:3] multi-clip scene: the decaying event term rides only clip 0 (scene t=0)."""
    calls = _capture_args(monkeypatch)
    scene = _two_clip_scene(assets, tmp_path)
    await video._compose_scene(
        scene, 0, tmp_path, camera_noise_enabled=True,
        sound_design_enabled=True, include_stinger=True, min_shot_clip_sec=0.0,
    )
    # calls: clip S001, clip S002, assembly — clips carry the camera stage
    assert "max(0,1-" in _video_filter_of(calls[0])
    assert "max(0,1-" not in _video_filter_of(calls[1])
    assert "rotate=" in _video_filter_of(calls[1])  # idle band still present


async def test_compose_scene_multi_clip_k_decorrelates_shots(monkeypatch, tmp_path, assets):
    """[AC:2] per-shot k offset: adjacent clips get different noise curves."""
    calls = _capture_args(monkeypatch)
    scene = _two_clip_scene(assets, tmp_path)
    await video._compose_scene(
        scene, 0, tmp_path, camera_noise_enabled=True, min_shot_clip_sec=0.0,
    )
    first = _video_filter_of(calls[0])
    second = _video_filter_of(calls[1])
    assert first[first.index("rotate=") :] != second[second.index("rotate=") :]


# ── trace metadata (Story 11.3 AC:7) ─────────────────────────────────────────


async def test_trace_metadata_includes_camera_path_block(monkeypatch, tmp_path, assets):
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    await video_node(_state([scene]))

    assert captured.get("camera_noise_enabled") is False  # _settings_ns default


def test_record_trace_emits_camera_path_block(monkeypatch):
    """The real _record_trace forwards version+enabled under 'camera_path' (8.8 idiom)."""
    from yt_flow.pipeline.nodes import camera_path as cp
    seen: dict = {}

    class _Client:
        def update_current_span(self, metadata):
            seen.update(metadata)

    monkeypatch.setattr(video, "get_client", lambda: _Client())
    _REAL_RECORD_TRACE(run_id="r", scene_count=1, latency_ms=1, camera_noise_enabled=True)
    assert seen["camera_path"] == {"version": cp.CAMERA_PATH_VERSION, "enabled": True}


def test_config_camera_noise_enabled_default_true():
    """Settings.camera_noise_enabled defaults true (Story 11.3 AC:6); the fake
    _settings_ns defaults False so pre-11.3 tests stay untouched."""
    from yt_flow.config import Settings

    assert Settings.model_fields["camera_noise_enabled"].default is True


def test_char_max_box_reserves_the_widest_macro_pan_budget():
    """[Story 11.3 AC:5 / Story 11.5 AC:7] tremble's fBm rework keeps total
    amplitude 3.0px, so the idle-motion half of the motion-safe box must not move.

    Story 11.5 widened the *macro-pan* half: a card can now take either 7.3's
    zoompan parallax (CHAR_PAN_AMPLITUDE_PX = 12px) or the 2.5D layer parallax
    (3% of width x the 0.80 near ratio = 46.08px), and the box has to hold for
    whichever runs — so it reserves the larger. Asserting the formula rather than
    a literal keeps this a real invariant instead of a number to re-paste.
    """
    assert cm.max_excursion() == (18.0, 16.5, 1.075)
    assert video._MACRO_PAN_RESERVE_PX == max(video.CHAR_PAN_AMPLITUDE_PX, video._LAYER_MAX_PX)
    assert video._LAYER_MAX_PX == pytest.approx(0.03 * 1920 * 0.80)
    assert video.CHAR_MAX_W == (
        1920 - 2 * (18.0 + video._MACRO_PAN_RESERVE_PX)
    ) / video.CHAR_MAX_ZOOM / 1.075
    assert video.CHAR_MAX_H == (
        1080 - 2 * (16.5 + video._MACRO_PAN_RESERVE_PX)
    ) / video.CHAR_MAX_ZOOM / 1.075
