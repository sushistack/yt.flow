"""Tests for Story 8.16 depth-aware placement wiring into video.py.

Three layers, none of which existed before this story:
* the no-resolver default is byte-identical to pre-8.16,
* feet (overlay y) and shadow (geq ellipse Y) derive from ONE ground value,
* real-ffmpeg pixel checks — the composited character's bounding box actually
  lands on the ground line, and an occlusion mask actually hides it.

ComfyUI is never touched: the ground resolver is a plain fake.
"""

import re
import shutil
import struct
import subprocess
import wave
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import yt_flow.pipeline.nodes.video as video
from yt_flow.pipeline.nodes.composite_harmonization import build_contact_shadow
from yt_flow.pipeline.nodes.video import COMP_H, _merge_placements, _overlay_filter, video_node

# ── fixtures / helpers (same conventions as test_video_harmonization.py) ─────


def _png(color_type: int, width: int = 1, height: int = 1, payload: bytes | None = None) -> bytes:
    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    raw = payload if payload is not None else b"\x00\xff\x00\x00\x80"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _settings_ns(tmp_path, *, tier=1):
    return SimpleNamespace(
        workspace_path=str(tmp_path),
        chapter_cards=False,
        chapter_card_duration_sec=1.75,
        sound_design_enabled=False,
        post_fx_enabled=False,
        parallax_enabled=False,
        cc_attribution=False,
        composite_harmonization_tier=tier,
        min_shot_clip_sec=2.0,
        camera_noise_enabled=False,
        # Story 11.5: the 2.5D renderer is never injected in these tests, so the
        # kill-switch value only has to exist; build_motion_source takes the
        # legacy zoompan path either way.
        parallax_25d_enabled=False,
        parallax_displacement_frac=0.02,
    )


def _card(path, *, card_key="SCP-096", position="center", depth="near", motion_style="hold"):
    return {
        "card_key": card_key, "pose": "standing", "angle": "front", "path": str(path),
        "fallback": False, "position": position, "depth": depth,
        "motion_style": motion_style, "motion_energy": "medium",
    }


def _scene(scene_num, *, image, audio, subtitle, cast=None):
    return {
        "scene_num": scene_num, "narration": "n",
        "shots": [{
            "shot_id": "S001", "sentence_indices": [0], "image_prompt": "p",
            "negative_prompt": "n", "camera_angle": None, "camera_movement": None,
            "image_path": str(image), "cast": cast or [], "location_key": None,
        }],
        "audio_path": str(audio), "audio_duration": 2.0, "word_timings": [],
        "subtitle_path": str(subtitle), "mood": "dread", "title": "", "kicker": "",
        "display_narration": "n",
    }


def _state(scenes, run_id="run-816"):
    return {
        "run_id": run_id, "scp_id": "SCP-TEST", "scp_text": "", "scenes": scenes,
        "video_path": None, "current_stage": "video", "gate_states": {},
        "prompt_variant": None, "error": None,
    }


@pytest.fixture
def assets(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    subtitle = tmp_path / "scene.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n\n", encoding="utf-8")
    character = tmp_path / "character.png"
    character.write_bytes(_png(6))
    return SimpleNamespace(image=image, audio=audio, subtitle=subtitle, character=character)


@pytest.fixture(autouse=True)
def _silent_trace(monkeypatch):
    monkeypatch.setattr(video, "_record_trace", lambda **kw: None)


@pytest.fixture(autouse=True)
def _fake_which(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/ffmpeg")


@pytest.fixture(autouse=True)
def _no_ground_resolver(monkeypatch):
    """Never leak an injected resolver between tests (module-level global)."""
    monkeypatch.setattr(video, "_ground_resolver", None)


def _capture_filter_complex(monkeypatch):
    captured = []

    async def _fake(*args):
        args_list = list(args)
        if "-filter_complex" in args_list:
            captured.append(args_list[args_list.index("-filter_complex") + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    return captured


def _inject_cast(monkeypatch, mapping):
    async def _resolver(scp_id, scenes):
        return mapping
    monkeypatch.setattr(video, "_cast_resolver", _resolver)


def _inject_ground(monkeypatch, placements):
    async def _resolver(scenes, cast_cards):
        return placements
    monkeypatch.setattr(video, "_ground_resolver", _resolver)


async def _render(monkeypatch, tmp_path, assets, *, tier=1, run_id="run-816"):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, tier=tier))
    captured = _capture_filter_complex(monkeypatch)
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
                   cast=[{"card_key": "SCP-096", "position": "center", "depth": "near"}])
    out = await video_node(_state([scene], run_id=run_id))
    assert out.get("error") is None
    return captured[0]


# ── The default must not move ────────────────────────────────────────────────


def test_overlay_filter_default_y_is_the_pre_816_expression():
    assert "y='(main_h-overlay_h)/2'" in _overlay_filter(motion_style="hold")


def test_contact_shadow_default_ellipse_y_is_unchanged():
    assert "(Y/H-0.85)" in build_contact_shadow({"depth": "near", "position": "center"})


async def test_no_ground_resolver_filtergraph_is_byte_identical(monkeypatch, tmp_path, assets):
    """A run with no resolver and a run whose resolver annotates nothing produce
    the same filtergraph as each other, and it still carries the centre anchor. [AC:2]"""
    _inject_cast(monkeypatch, {"1:S001": [_card(assets.character)]})
    without = await _render(monkeypatch, tmp_path, assets, run_id="run-none")

    _inject_ground(monkeypatch, {})
    empty = await _render(monkeypatch, tmp_path, assets, run_id="run-empty")

    assert without == empty
    assert "y='(main_h-overlay_h)/2'" in without
    assert "(Y/H-0.85)" in without
    assert "movie=" not in without


# ── One ground value drives both feet and shadow ─────────────────────────────


def test_overlay_filter_ground_y_anchors_the_bottom_edge():
    assert "y='main_h*0.8-overlay_h'" in _overlay_filter(ground_y=0.8, motion_style="hold")


@pytest.mark.parametrize("ground_y", [0.55, 0.72, 0.9])
def test_feet_and_shadow_sit_on_the_same_line(ground_y):
    """The overlay's bottom edge and the shadow ellipse's centre resolve to the
    same absolute row. [AC:1]"""
    card = {"depth": "mid", "position": "center", "ground_y": ground_y}
    overlay = _overlay_filter("center", ground_y=ground_y, motion_style="hold")
    shadow = build_contact_shadow(card)

    y_expr = overlay.split("y='")[1].split("'")[0]
    feet = eval(y_expr.replace("main_h", str(COMP_H)).replace("overlay_h", "400")) + 400  # noqa: S307
    shadow_centre = float(shadow.split("(Y/H-")[1].split(")")[0]) * COMP_H
    assert abs(feet - shadow_centre) < 1.0


def test_far_cards_sit_higher_in_frame_than_near_cards():
    """Ground lines from the real service, rendered through the real filter
    builders: far's feet land above near's. [AC:1]"""
    import numpy as np

    from yt_flow.services import compositing_service as cs

    depth_map = np.full((180, 320), 60.0)
    depth_map[90:, :] = np.linspace(60.0, 255.0, 90)[:, None]

    def feet(depth: str) -> float:
        ground = cs.ground_line(depth_map, "center", depth)
        expr = _overlay_filter("center", ground_y=ground, motion_style="hold")
        y_expr = expr.split("y='")[1].split("'")[0]
        return eval(y_expr.replace("main_h", str(COMP_H)).replace("overlay_h", "0"))  # noqa: S307

    assert feet("far") < feet("mid") < feet("near")


def test_card_height_fractions_match_video_pys_own_scale_math():
    """compositing_service duplicates the rendered card height per depth to place the
    occlusion crop box. Wrong values become a vertical STRETCH of the occluder pattern
    (the shipped 0.45/0.65/0.82 were off by 11-18% of frame height, ~100px on mid), so
    re-derive them here from video.py's constants rather than trusting the copy."""
    from yt_flow.pipeline.nodes.video import CHAR_MAX_H, CHAR_MAX_W, _DEPTH_SCALE
    from yt_flow.services.compositing_service import _CARD_HEIGHT_FRAC

    sprite_w, sprite_h = 832, 1216  # the card generator's canvas
    for depth, scale in _DEPTH_SCALE.items():
        # force_original_aspect_ratio=decrease: whichever axis binds first.
        fit = min(CHAR_MAX_W * scale / sprite_w, CHAR_MAX_H * scale / sprite_h)
        assert _CARD_HEIGHT_FRAC[depth] == pytest.approx(sprite_h * fit / COMP_H, abs=0.005), depth


async def test_ground_resolver_drives_both_overlay_and_shadow(monkeypatch, tmp_path, assets):
    _inject_cast(monkeypatch, {"1:S001": [_card(assets.character)]})
    _inject_ground(monkeypatch, {"1:S001": [{"ground_y": 0.7}]})
    fc = await _render(monkeypatch, tmp_path, assets)

    assert "(Y/H-0.7)" in fc          # ellipse drawn at the measured ground line
    assert "(main_h-overlay_h)/2" not in fc

    # Feet and shadow both track the plate under Ken Burns, and they coincide on
    # every frame — not just the first. A static anchor would leave the card
    # hovering by the last frame of every moving shot.
    def ev(expr: str, t: float, overlay_h: float) -> float:
        return eval(  # noqa: S307
            expr.replace("main_h", str(COMP_H)).replace("overlay_h", str(overlay_h))
            .replace("t", str(t)),
            {"min": min, "max": max},
        )

    # zoompan's y= has no overlay_h; the shadow's is the card expression plus a
    # constant offset — the card's own is the last.
    feet_expr = [e for e in re.findall(r"y='([^']+)'", fc) if "overlay_h" in e][-1]
    # The shadow's x= is quoted too (Story 11.5 carries the layer term through it),
    # so match the stage rather than one literal spelling of its x argument.
    shadow_expr = re.search(r"\[sh0\]overlay=x='?[^:]*?'?:y='([^']+)'", fc).group(1)
    assert "t" in feet_expr
    rows = []
    for t in (0.0, 3.0):
        feet = ev(feet_expr, t, 400) + 400
        # The shadow plane is a full-frame canvas: its ellipse centre lands at
        # its own offset plus the drawn fraction.
        centre = ev(shadow_expr, t, COMP_H) + 0.7 * COMP_H
        assert abs(feet - centre) < 1.0, f"feet {feet} vs shadow {centre} at t={t}"
        rows.append(feet)
    assert rows[0] != rows[1]


# ── Resolver contract / degradation ──────────────────────────────────────────


def test_merge_placements_folds_keys_in_order():
    cards = {"1:S001": [{"card_key": "A"}, {"card_key": "B"}]}
    merged = _merge_placements(cards, {"1:S001": [{"ground_y": 0.6}, {"ground_y": 0.9}]})
    assert merged["1:S001"] == [
        {"card_key": "A", "ground_y": 0.6}, {"card_key": "B", "ground_y": 0.9},
    ]


@pytest.mark.parametrize("placements", [
    {},                                  # shot absent
    {"1:S001": [{"ground_y": 0.6}]},     # wrong length
    {"1:S001": {"ground_y": 0.6}},       # not a list
    {"1:S001": [None, None]},            # not dicts
])
def test_merge_placements_ignores_any_shape_mismatch(placements):
    cards = {"1:S001": [{"card_key": "A"}, {"card_key": "B"}]}
    assert _merge_placements(cards, placements) == cards


async def test_ground_resolver_failure_is_non_fatal(monkeypatch, tmp_path, assets):
    _inject_cast(monkeypatch, {"1:S001": [_card(assets.character)]})

    async def _boom(scenes, cast_cards):
        raise RuntimeError("depth estimation exploded")

    monkeypatch.setattr(video, "_ground_resolver", _boom)
    fc = await _render(monkeypatch, tmp_path, assets)
    assert "y='(main_h-overlay_h)/2'" in fc  # degraded to the pre-816 anchor


async def test_ground_resolver_not_called_without_cards(monkeypatch, tmp_path, assets):
    calls = []

    async def _resolver(scenes, cast_cards):
        calls.append(cast_cards)
        return {}

    monkeypatch.setattr(video, "_ground_resolver", _resolver)
    monkeypatch.setattr(video, "_cast_resolver", None)
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))

    async def _fake(*args):
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene]))
    assert out.get("error") is None
    assert calls == []


# ── Occlusion mask in the card chain ─────────────────────────────────────────


async def test_occlusion_mask_enters_the_card_chain(monkeypatch, tmp_path, assets):
    mask = tmp_path / "occ.png"
    mask.write_bytes(_png(0, payload=b"\x00\xff"))
    _inject_cast(monkeypatch, {"1:S001": [_card(assets.character)]})
    _inject_ground(monkeypatch, {"1:S001": [{"ground_y": 0.8, "occlusion_mask": str(mask)}]})
    fc = await _render(monkeypatch, tmp_path, assets)

    assert f"movie='{mask}',format=gray[om0mask]" in fc
    assert "[om0alpha][om0mask]blend=all_mode=multiply[om0alpha2]" in fc
    assert "[om0b][om0alpha2]alphamerge[om0]" in fc
    assert "[om0]boxblur" in fc  # the masked sprite, not [1:v], feeds the card chain


async def test_no_occlusion_mask_leaves_the_chain_untouched(monkeypatch, tmp_path, assets):
    _inject_cast(monkeypatch, {"1:S001": [_card(assets.character)]})
    _inject_ground(monkeypatch, {"1:S001": [{"ground_y": 0.8}]})
    fc = await _render(monkeypatch, tmp_path, assets)
    assert "movie=" not in fc and "alphamerge" not in fc
    assert "[1:v]boxblur" in fc


async def test_two_cards_get_distinct_occlusion_labels(monkeypatch, tmp_path, assets):
    mask = tmp_path / "occ.png"
    mask.write_bytes(_png(0, payload=b"\x00\xff"))
    _inject_cast(monkeypatch, {"1:S001": [
        _card(assets.character, position="left", depth="far"),
        _card(assets.character, card_key="SCP-999", position="right", depth="near"),
    ]})
    _inject_ground(monkeypatch, {"1:S001": [
        {"ground_y": 0.6, "occlusion_mask": str(mask)},
        {"ground_y": 0.9, "occlusion_mask": str(mask)},
    ]})
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, tier=1))
    captured = _capture_filter_complex(monkeypatch)
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, cast=[
        {"card_key": "SCP-096", "position": "left", "depth": "far"},
        {"card_key": "SCP-999", "position": "right", "depth": "near"},
    ])
    out = await video_node(_state([scene]))
    assert out.get("error") is None
    fc = captured[0]
    for label in ("[om0]", "[om1]", "[om0alpha2]", "[om1alpha2]"):
        assert label in fc


# ── Real ffmpeg: pixels, not filter strings ──────────────────────────────────


def _silent_wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)
    return path


def _solid_png(path: Path, size, color) -> Path:
    from PIL import Image

    Image.new("RGBA", size, color).save(path)
    return path


def _first_frame(video_path: Path, out_path: Path):
    import numpy as np
    from PIL import Image

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-frames:v", "1", "-update", "1", str(out_path)],
        check=True, capture_output=True,
    )
    return np.asarray(Image.open(out_path).convert("RGB"))


def _green_rows(frame) -> tuple[int, int]:
    import numpy as np

    green = (frame[:, :, 1] > 120) & (frame[:, :, 0] < 100)
    rows = np.flatnonzero(green.any(axis=1))
    assert rows.size, "no green character pixels in the composited frame"
    return int(rows[0]), int(rows[-1])


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_grounded_card_bbox_sits_on_the_ground_line_real_ffmpeg(tmp_path):
    """Real FFmpeg + real pixels: the composited character's bounding box bottom
    lands on ground_y * frame height. [AC:1]"""
    from yt_flow.pipeline.nodes.video import _compose_scene

    ground_y = 0.8
    card = _solid_png(tmp_path / "card.png", (200, 400), (0, 255, 0, 255))
    _solid_png(tmp_path / "bg.png", (1920, 1080), (0, 0, 0, 255))
    _silent_wav(tmp_path / "a.wav")
    (tmp_path / "s.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n \n\n", encoding="utf-8")
    scene = _scene(1, image=tmp_path / "bg.png", audio=tmp_path / "a.wav", subtitle=tmp_path / "s.srt",
                   cast=[{"card_key": "SCP-096", "position": "center", "depth": "near"}])

    seg_path, _spec, has_char = await _compose_scene(
        scene, 0, tmp_path,
        cards_by_shot={"S001": [{**_card(card), "ground_y": ground_y}]},
        composite_harmonization_tier=0,
    )
    assert has_char
    top, bottom = _green_rows(_first_frame(seg_path, tmp_path / "frame.png"))
    assert abs(bottom - ground_y * 1080) <= 8, (top, bottom)
    assert abs((bottom - top) - 400) <= 8


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_ungrounded_card_still_renders_at_frame_centre_real_ffmpeg(tmp_path):
    """The same render without a ground value keeps the pre-8.16 centre anchor —
    the regression guard for the byte-identical default, measured in pixels."""
    from yt_flow.pipeline.nodes.video import _compose_scene

    card = _solid_png(tmp_path / "card.png", (200, 400), (0, 255, 0, 255))
    _solid_png(tmp_path / "bg.png", (1920, 1080), (0, 0, 0, 255))
    _silent_wav(tmp_path / "a.wav")
    (tmp_path / "s.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n \n\n", encoding="utf-8")
    scene = _scene(1, image=tmp_path / "bg.png", audio=tmp_path / "a.wav", subtitle=tmp_path / "s.srt",
                   cast=[{"card_key": "SCP-096", "position": "center", "depth": "near"}])

    seg_path, _spec, _has_char = await _compose_scene(
        scene, 0, tmp_path, cards_by_shot={"S001": [_card(card)]},
        composite_harmonization_tier=0,
    )
    top, bottom = _green_rows(_first_frame(seg_path, tmp_path / "frame.png"))
    assert abs(bottom - (1080 + 400) / 2) <= 8, (top, bottom)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_occlusion_mask_actually_masks_real_ffmpeg(tmp_path):
    """Real FFmpeg + real pixels: where the mask is black, the card is gone and
    the background shows through. [AC:3]"""
    import numpy as np
    from PIL import Image

    from yt_flow.pipeline.nodes.video import _compose_scene

    ground_y = 0.8
    card = _solid_png(tmp_path / "card.png", (200, 400), (0, 255, 0, 255))
    mask_arr = np.full((400, 200), 255, np.uint8)
    mask_arr[200:, :] = 0  # bottom half of the sprite is behind an occluder
    Image.fromarray(mask_arr, "L").save(tmp_path / "mask.png")
    _solid_png(tmp_path / "bg.png", (1920, 1080), (0, 0, 0, 255))
    _silent_wav(tmp_path / "a.wav")
    (tmp_path / "s.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n \n\n", encoding="utf-8")
    scene = _scene(1, image=tmp_path / "bg.png", audio=tmp_path / "a.wav", subtitle=tmp_path / "s.srt",
                   cast=[{"card_key": "SCP-096", "position": "center", "depth": "near"}])

    seg_path, _spec, _has_char = await _compose_scene(
        scene, 0, tmp_path,
        cards_by_shot={"S001": [{
            **_card(card), "ground_y": ground_y, "occlusion_mask": str(tmp_path / "mask.png"),
        }]},
        composite_harmonization_tier=0,
    )
    frame = _first_frame(seg_path, tmp_path / "frame.png")
    top, bottom = _green_rows(frame)
    # feet unchanged (the sprite still occupies the same rect), but only its top
    # half survives: the masked half is background.
    assert abs(bottom - (ground_y * 1080 - 200)) <= 8, (top, bottom)
    assert frame[int(ground_y * 1080) - 20, 960, 1] < 60


def test_ground_y_is_clamped_to_keep_the_cards_motion_in_frame():
    """A bottom-anchored card spends its whole vertical margin below itself, but
    CHAR_MAX_H was derived for a centre anchor with that margin on both sides. Without a
    clamp a measured ground line near the band's old 0.98 ceiling left 21px for a 28.5px
    idle-bob-plus-parallax excursion, so the character walked off the bottom of frame."""
    from yt_flow.pipeline.nodes import video

    needed = (video._MAX_MOTION_Y_PX + video.CHAR_PAN_AMPLITUDE_PX) / video.COMP_H
    assert video._GROUND_Y_MAX <= 1.0 - needed + 1e-9

    out = video._apply_placement({"card_key": "X"}, {"ground_y": 0.99})
    assert out["ground_y"] <= video._GROUND_Y_MAX


def test_a_non_numeric_ground_y_is_dropped_rather_than_reaching_the_filtergraph():
    """ground_y lands in an f-string format spec, so a string there raises out of the
    chain builder long after the resolver's own try/except returned — failing the whole
    video stage on a bad annotation instead of degrading to the pre-8.16 anchor."""
    from yt_flow.pipeline.nodes import video

    assert "ground_y" not in video._apply_placement({"card_key": "X"}, {"ground_y": "0.8"})
    assert "ground_y" not in video._apply_placement({"card_key": "X"}, {"ground_y": True})
    assert video._apply_placement({"card_key": "X"}, {"ground_y": 0.8})["ground_y"] == 0.8
