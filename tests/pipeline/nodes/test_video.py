"""Tests for src/yt_flow/pipeline/nodes/video.py (Story 1.9 + 1.9b).

No live FFmpeg / Langfuse: _run_ffmpeg and _record_trace are monkeypatched.
Covers: select_effect, zoompan filter, xfade offset math, happy/error paths,
observability, AD-1 layer guards, integration (skippable without ffmpeg+ffprobe).
"""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import yt_flow.pipeline.nodes.video as video
from yt_flow.domain.state import PipelineState, SceneState, ShotData
from yt_flow.pipeline.nodes.video import (
    XFADE_DURATION,
    EffectSpec,
    _character_scale_filter,
    _join_with_xfade,
    _overlay_filter,
    _validate_scene_assets,
    _zoompan_filter,
    select_effect,
    video_node,
)


# ── Fixtures / helpers ────────────────────────────────────────────────────────


def _settings_ns(tmp_path, *, chapter_cards: bool = False, chapter_card_duration_sec: float = 1.75):
    # ponytail: fake settings default cards OFF so pre-existing tests (written
    # before Story 5.1) don't need touching; the real Settings() default is True
    # (AC:2) — see test_config_chapter_cards_default_true.
    return SimpleNamespace(
        workspace_path=str(tmp_path),
        chapter_cards=chapter_cards,
        chapter_card_duration_sec=chapter_card_duration_sec,
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
    background_path: str | None = None,
    character_path: str | None = None,
) -> ShotData:
    return {  # type: ignore[return-value]
        "shot_id": "S001",
        "sentence_indices": [0],
        "image_prompt": "p",
        "negative_prompt": "n",
        "camera_angle": None,
        "camera_movement": camera_movement,
        "image_path": image_path,
        "background_path": background_path,
        "character_path": character_path,
    }


def _scene(
    scene_num: int,
    *,
    image: str | None = None,
    audio: str | None = None,
    subtitle: str | None = None,
    camera_movement: str | None = None,
    background: str | None = None,
    character: str | None = None,
    audio_duration: float = 2.0,
    **over,
) -> SceneState:
    base: dict = {
        "scene_num": scene_num,
        "narration": f"narration {scene_num}",
        "shots": [_shot(image, camera_movement,
                        background_path=background, character_path=character)],
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


@pytest.fixture
def assets(tmp_path) -> SimpleNamespace:
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    subtitle = tmp_path / "scene.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n\n", encoding="utf-8")
    character = tmp_path / "character.png"
    character.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return SimpleNamespace(
        image=str(image), audio=str(audio), subtitle=str(subtitle), character=str(character)
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


# ── _join_with_xfade offset math ─────────────────────────────────────────────


async def test_xfade_offset_math_3_scenes(monkeypatch, tmp_path):
    """3-scene fixture: assert cumulative offset values in the filtergraph. [AC:2]

    With durations [3.0, 2.0, 4.0] and XFADE_DURATION=0.5:
      offset_1 = 3.0 - 1*0.5 = 2.5
      offset_2 = (3.0+2.0) - 2*0.5 = 4.0
    """
    segs = [(tmp_path / f"s{i}.mp4", float(d)) for i, d in enumerate([3.0, 2.0, 4.0])]
    for p, _ in segs:
        p.write_bytes(b"FAKE")

    captured_filter: list[str] = []

    async def _capture(*args):
        args_list = list(args)
        if "-filter_complex" in args_list:
            idx = args_list.index("-filter_complex")
            captured_filter.append(args_list[idx + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _capture)
    await _join_with_xfade(segs, tmp_path / "out.mp4")

    assert captured_filter, "filter_complex not captured"
    fc = captured_filter[0]
    assert "offset=2.5000" in fc or "offset=2.5" in fc
    assert "offset=4.0000" in fc or "offset=4.0" in fc


async def test_xfade_video_crossfades_audio_does_not(monkeypatch, tmp_path):
    """Video keeps xfade; audio must NOT crossfade (no volume dip). [Story 5.9 AC:1]

    Audio is joined via adelay (per-segment, positioned at the same offset the
    video xfade uses) + amix (normalize=0, so no dip in level) instead of
    acrossfade.
    """
    segs = [(tmp_path / f"s{i}.mp4", 2.0) for i in range(2)]
    for p, _ in segs:
        p.write_bytes(b"FAKE")

    captured_filter: list[str] = []

    async def _capture(*args):
        args_list = list(args)
        if "-filter_complex" in args_list:
            idx = args_list.index("-filter_complex")
            captured_filter.append(args_list[idx + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _capture)
    await _join_with_xfade(segs, tmp_path / "out.mp4")

    fc = captured_filter[0]
    assert "xfade" in fc
    assert "acrossfade" not in fc
    assert "adelay" in fc
    assert "amix=inputs=2" in fc
    assert "normalize=0" in fc


async def test_xfade_audio_delay_matches_video_offset_3_scenes(monkeypatch, tmp_path):
    """Audio adelay values must equal the video xfade offsets (zero-drift sync). [Story 5.9 AC:3]

    Same fixture as test_xfade_offset_math_3_scenes: durations [3.0, 2.0, 4.0],
    XFADE_DURATION=0.5 → offsets 2.5 and 4.0 → delays 2500ms and 4000ms.
    """
    segs = [(tmp_path / f"s{i}.mp4", float(d)) for i, d in enumerate([3.0, 2.0, 4.0])]
    for p, _ in segs:
        p.write_bytes(b"FAKE")

    captured_filter: list[str] = []

    async def _capture(*args):
        args_list = list(args)
        if "-filter_complex" in args_list:
            idx = args_list.index("-filter_complex")
            captured_filter.append(args_list[idx + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _capture)
    await _join_with_xfade(segs, tmp_path / "out.mp4")

    fc = captured_filter[0]
    assert "adelay=2500:all=1" in fc
    assert "adelay=4000:all=1" in fc
    assert "amix=inputs=3" in fc


async def test_xfade_uses_fadeblack_transition(monkeypatch, tmp_path):
    """Default transition must be fadeblack, not a plain image-over-image crossfade. [AC:1]"""
    segs = [(tmp_path / f"s{i}.mp4", 2.0) for i in range(2)]
    for p, _ in segs:
        p.write_bytes(b"FAKE")

    captured_filter: list[str] = []

    async def _capture(*args):
        args_list = list(args)
        if "-filter_complex" in args_list:
            idx = args_list.index("-filter_complex")
            captured_filter.append(args_list[idx + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _capture)
    await _join_with_xfade(segs, tmp_path / "out.mp4")

    assert video.XFADE_TRANSITION == "fadeblack"
    assert "transition=fadeblack" in captured_filter[0]


async def test_xfade_fail_raises(monkeypatch, tmp_path):
    segs = [(tmp_path / f"s{i}.mp4", 2.0) for i in range(2)]
    for p, _ in segs:
        p.write_bytes(b"FAKE")
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_fail)

    with pytest.raises(RuntimeError, match="xfade join failed"):
        await _join_with_xfade(segs, tmp_path / "out.mp4")


async def test_xfade_offset_negative_raises(monkeypatch, tmp_path):
    """A scene shorter than XFADE_DURATION drives offset negative — this must fail
    loudly rather than silently clamp the audio delay to 0 and desync from video.
    [Story 5.9 AC:3]"""
    segs = [(tmp_path / "s0.mp4", 0.1), (tmp_path / "s1.mp4", 2.0)]
    for p, _ in segs:
        p.write_bytes(b"FAKE")
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    with pytest.raises(AssertionError, match="offset went negative"):
        await _join_with_xfade(segs, tmp_path / "out.mp4")


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


def test_validate_ignores_unused_later_shot_missing_image(assets):
    """Only the first image-bearing shot is rendered, so a later shot's missing
    image must not abort the run."""
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    scene["shots"].append(_shot("/does/not/exist.png"))  # unused second shot
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
    """Character is capped to COMP minus sway/bob amplitude, downscale-only, AR-preserved.

    The box guarantees the centered overlay's full sine excursion stays on-frame:
    max width COMP_W-2*SWAY_AMPLITUDE ⇒ min centre offset ≥ SWAY_AMPLITUDE. [review:1.9c]
    """
    f = _character_scale_filter()
    assert "scale=" in f
    assert "force_original_aspect_ratio=decrease" in f   # never distort
    assert "min(iw" in f and "min(ih" in f               # never upscale a small cutout
    assert str(video.COMP_W - 2 * video.SWAY_AMPLITUDE) in f
    assert str(video.COMP_H - 2 * video.BOB_AMPLITUDE) in f


async def test_video_node_character_uses_filter_complex(monkeypatch, tmp_path, assets):
    """A shot with character_path renders via filter_complex overlay + eval=frame. [AC:1,2]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake, captured = _capture_arg_flag("-filter_complex")
    monkeypatch.setattr(video, "_run_ffmpeg", fake)

    scene = _scene(
        1, image=assets.image, background=assets.image,
        character=assets.character, audio=assets.audio, subtitle=assets.subtitle,
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert captured, "filter_complex not used for a character shot"
    fc = captured[0]
    assert "zoompan" in fc          # background still gets Ken Burns
    assert "overlay=" in fc         # character composited on top
    assert "eval=frame" in fc       # motion animates per-frame
    assert "subtitles=" in fc       # subtitles burned last
    assert "scale=" in fc           # character normalized to motion-safe box
    assert "[char]" in fc           # scaled character feeds the overlay


async def test_video_node_character_maps_output_and_audio(monkeypatch, tmp_path, assets):
    """filter_complex path maps the composed [out] and the audio input. [AC:1]"""
    calls: list[tuple] = []

    async def _rec(*args):
        calls.append(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _rec)

    scene = _scene(
        1, image=assets.image, background=assets.image,
        character=assets.character, audio=assets.audio, subtitle=assets.subtitle,
    )
    out = await video_node(_state([scene]))
    assert out.get("error") is None

    args = list(calls[0])
    assert "[out]" in args          # -map [out]
    # audio is the 3rd input (idx 2): bg, character, audio
    assert "2:a" in args


async def test_video_node_no_character_uses_vf_fallback(monkeypatch, tmp_path, assets):
    """No character_path → unchanged 1.9b -vf Ken-Burns path, no overlay. [AC:3]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    fake_vf, captured_vf = _capture_arg_flag("-vf")
    monkeypatch.setattr(video, "_run_ffmpeg", fake_vf)

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert captured_vf, "background-only shot must use -vf"
    assert "overlay=" not in captured_vf[0]
    assert "zoompan" in captured_vf[0]


def test_validate_character_path_set_but_missing(assets):
    """A set-but-missing character_path fails loudly (not silently dropped). [AC:1]"""
    scene = _scene(
        1, image=assets.image, background=assets.image,
        character="/no/such/character.png", audio=assets.audio, subtitle=assets.subtitle,
    )
    with pytest.raises(FileNotFoundError, match="character_path"):
        _validate_scene_assets([scene])


def test_validate_none_character_ok(assets):
    """character_path=None is a valid background-only shot. [AC:3]"""
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    _validate_scene_assets([scene])  # must not raise


async def test_trace_records_character_motion(monkeypatch, tmp_path, assets):
    """Trace metadata gains character-overlay flag + motion params + count. [AC:4]"""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scene = _scene(
        1, image=assets.image, background=assets.image,
        character=assets.character, audio=assets.audio, subtitle=assets.subtitle,
    )
    await video_node(_state([scene]))

    assert captured.get("character_scenes") == 1
    effects = captured["effects"]
    assert effects[0]["character_overlay"] is True


async def test_trace_character_overlay_false_when_absent(monkeypatch, tmp_path, assets):
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    await video_node(_state([scene]))

    assert captured.get("character_scenes") == 0
    assert captured["effects"][0]["character_overlay"] is False


# ── integration test (skipped without ffmpeg+ffprobe) ────────────────────────


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg or ffprobe not installed",
)
async def test_xfade_join_integration(tmp_path):
    """Real FFmpeg: 2 pre-made segments → xfade join; duration ≈ Σ − overlap.

    Tests _join_with_xfade directly with color-source segments (no image/subtitle
    complexity) to verify the offset accumulation math produces correct output.
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
    seg1, seg2 = tmp_path / "seg1.mp4", tmp_path / "seg2.mp4"
    await _make_seg(seg1, "blue", dur1)
    await _make_seg(seg2, "red", dur2)

    output = tmp_path / "out.mp4"
    await _join_with_xfade([(seg1, dur1), (seg2, dur2)], output)
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

    expected = dur1 + dur2 - XFADE_DURATION
    video_dur = _stream_duration("v:0")
    audio_dur = _stream_duration("a:0")
    assert abs(video_dur - expected) < 0.5, f"Video duration {video_dur:.2f}s ≠ expected {expected:.2f}s"
    # [Story 5.9 AC:3] audio must land on the same combined-output duration as
    # video — no accumulating drift from the adelay+amix audio join.
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


# ── Story 1.13: LLM angle pre-selection integration ───────────────────────────


async def test_angle_selector_injection_sets_character_path(monkeypatch, tmp_path, assets):
    """When angle selector is injected, character_path is overwritten with the selected angle."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    angle_asset = tmp_path / "angle_front.png"
    angle_asset.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    async def _selector(scp_id, scenes):
        return {"1:S001": {"angle": "front", "path": str(angle_asset)}}

    monkeypatch.setattr(video, "_angle_selector", _selector)

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        character=assets.character,
    )
    state = _state([scene], scp_id="SCP-096")
    out = await video_node(state)

    assert out.get("error") is None
    # character_path should have been overwritten by the angle selector
    assert scene["shots"][0]["character_path"] == str(angle_asset)


async def test_angle_selector_not_injected_does_not_crash(monkeypatch, tmp_path, assets):
    """Without an injected selector, video_node should work normally (no angle selection)."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_angle_selector", None)

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        character=assets.character,
    )
    state = _state([scene])
    out = await video_node(state)

    assert out.get("error") is None
    # character_path should remain unchanged
    assert scene["shots"][0]["character_path"] == assets.character


async def test_angle_selector_failure_is_non_fatal(monkeypatch, tmp_path, assets):
    """Angle selection failure must never fail the pipeline (AD-10)."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    async def _failing_selector(scp_id, scenes):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(video, "_angle_selector", _failing_selector)

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        character=assets.character,
    )
    state = _state([scene])
    out = await video_node(state)

    assert out.get("error") is None  # pipeline must not fail
    # character_path should remain unchanged (existing value preserved)
    assert scene["shots"][0]["character_path"] == assets.character


async def test_angle_selector_returns_none_skips(monkeypatch, tmp_path, assets):
    """When selector returns None (no character), shots keep their existing character_path."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)

    async def _selector(scp_id, scenes):
        return None

    monkeypatch.setattr(video, "_angle_selector", _selector)

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        character=assets.character,
    )
    state = _state([scene])
    out = await video_node(state)

    assert out.get("error") is None
    assert scene["shots"][0]["character_path"] == assets.character


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
    all 5 into one filtergraph. [AC:2,5]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=True))
    monkeypatch.setattr(video, "_drawtext_font", lambda: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
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
    assert len(seg_outputs) == 3
    assert len(card_outputs) == 2

    join_args = next(args for args in calls if isinstance(args[-1], str) and args[-1].endswith("video.mp4"))
    assert len([a for a in join_args if isinstance(a, str) and "/seg_" in a]) == 3
    assert len([a for a in join_args if isinstance(a, str) and "/card_" in a]) == 2

    # [Story 5.9 AC:2] card segments (silent anullsrc audio, Story 5.1) go through
    # the same adelay/amix join as ordinary scenes — no acrossfade, no special-casing.
    filter_complex = join_args[join_args.index("-filter_complex") + 1]
    assert "acrossfade" not in filter_complex
    assert "adelay" in filter_complex
    assert "amix=inputs=5" in filter_complex


async def test_chapter_card_duration_is_clamped(monkeypatch, tmp_path, assets):
    """Out-of-range config is clamped to the accepted 1.5-2.0s card range. [AC:2]"""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=True, chapter_card_duration_sec=99.0))
    monkeypatch.setattr(video, "_drawtext_font", lambda: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    await video_node(_state(scenes))

    assert captured.get("chapter_card_duration") == pytest.approx(2.0)
    assert video._chapter_card_duration(0.1) == pytest.approx(1.5)
    assert video._chapter_card_duration(1.75) == pytest.approx(1.75)


async def test_chapter_cards_disabled_no_card_render(monkeypatch, tmp_path, assets):
    """chapter_cards=False: no card render call; join still uses fadeblack only. [AC:4]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, chapter_cards=False))
    captured_filter: list[str] = []

    async def _fake(*args):
        args_list = list(args)
        if "-filter_complex" in args_list:
            captured_filter.append(args_list[args_list.index("-filter_complex") + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)

    scenes = [
        _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
        _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle),
    ]
    out = await video_node(_state(scenes))

    assert out.get("error") is None
    assert captured_filter, "join filtergraph not captured"
    assert "transition=fadeblack" in captured_filter[0]
    assert "card_" not in captured_filter[0]


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
    monkeypatch.setattr(video, "_drawtext_font", lambda: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
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


def test_card_label_ignores_ad_hoc_title_until_scene_state_defines_it(assets):
    scene = _scene(3, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    scene["title"] = "The Discovery"  # type: ignore[typeddict-unknown-key]
    assert video._card_label(scene) == "- 3 -"


@pytest.mark.skipif(shutil.which("fc-match") is None, reason="fontconfig not installed")
def test_drawtext_font_resolves_to_existing_file():
    font = video._drawtext_font()
    assert Path(font).exists()


def test_drawtext_font_tries_fallback_after_fc_match_timeout(monkeypatch, tmp_path):
    fallback = tmp_path / "fallback.ttf"
    fallback.write_bytes(b"font")
    calls = 0

    def _run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=str(fallback), stderr="")

    try:
        video._drawtext_font.cache_clear()
        monkeypatch.setattr(subprocess, "run", _run)
        font = video._drawtext_font()
        assert font == str(fallback)
    finally:
        video._drawtext_font.cache_clear()


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("fc-match") is None,
    reason="ffmpeg or fontconfig not installed",
)
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

    monkeypatch.setattr(video, "_drawtext_font", lambda: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    monkeypatch.setattr(video, "_run_ffmpeg", _fake)

    await video._compose_chapter_card("- 1 -", 1, tmp_path, 1.75)

    args = list(captured[0])
    assert "-t" in args
    assert args[args.index("-t") + 1] == "1.750"


async def test_angle_selector_trace_metadata(monkeypatch, tmp_path, assets):
    """Trace metadata includes angle_selection info when selector runs."""
    captured: dict = {}
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    monkeypatch.setattr(video, "_run_ffmpeg", _fake_ffmpeg_ok)
    monkeypatch.setattr(video, "_record_trace", lambda **kw: captured.update(kw))

    angle_asset = tmp_path / "angle_front.png"
    angle_asset.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    async def _selector(scp_id, scenes):
        return {"1:S001": {"angle": "front", "path": str(angle_asset)}}

    monkeypatch.setattr(video, "_angle_selector", _selector)

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        character=assets.character,
    )
    state = _state([scene], scp_id="SCP-096")
    out = await video_node(state)

    assert out.get("error") is None
    assert "angle_selection" in captured
    asel = captured["angle_selection"]
    assert asel["scp_id"] == "SCP-096"  # AC6: scp_id in angle_selection metadata
    assert asel["shots_analyzed"] == 1
    assert "front" in asel["angles_selected"]
    assert "latency_ms" in asel
