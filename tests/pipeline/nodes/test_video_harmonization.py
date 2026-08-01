"""Tests for Story 8.7 composite harmonization wiring into video.py.

No live FFmpeg / Langfuse: _run_ffmpeg and _record_trace are monkeypatched,
same convention as test_video.py. Covers tier 0/1/2/3 filter_complex content,
the composite-then-grade regression invariant, and Tier 3 relit_map
substitution.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import yt_flow.pipeline.nodes.video as video
from yt_flow.pipeline.nodes.video import video_node


def _make_rgba_png() -> bytes:
    """Minimal 1x1 RGBA PNG (color_type=6) — same construction as test_video.py's
    _make_png(6)/RGBA_CARD_BYTES, duplicated here to keep this file standalone."""
    import struct
    import zlib

    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\x80"))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _make_rgb_png() -> bytes:
    import struct
    import zlib

    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _write_silent_wav(path) -> None:
    """A real, ffmpeg-decodable 1-second silent WAV (real-ffmpeg test needs a
    valid audio stream, unlike the monkeypatched _run_ffmpeg tests above)."""
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)


# ── Fixtures / helpers (mirrors test_video.py's conventions) ────────────────


def _settings_ns(tmp_path, *, composite_harmonization_tier=0):
    return SimpleNamespace(
        workspace_path=str(tmp_path),
        chapter_cards=False,
        chapter_card_duration_sec=1.75,
        sound_design_enabled=False,
        post_fx_enabled=False,
        parallax_enabled=False,
        cc_attribution=False,
        composite_harmonization_tier=composite_harmonization_tier,
        min_shot_clip_sec=2.0,
        camera_noise_enabled=False,  # Story 11.3: off, same as the other feature flags above
    )


def _cast_member(card_key="SCP-096", *, position="center", depth="near"):
    return {"card_key": card_key, "position": position, "depth": depth, "pose": "standing"}


def _card(path, *, card_key="SCP-096", position="center", depth="near"):
    return {
        "card_key": card_key, "pose": "standing", "angle": "front", "path": path,
        "fallback": False, "position": position, "depth": depth,
        "motion_style": "breath", "motion_energy": "medium",
    }


def _inject_resolver(monkeypatch, mapping=None):
    async def _default(scp_id, scenes):
        return mapping or {}
    monkeypatch.setattr(video, "_cast_resolver", _default)


def _scene(scene_num, *, image, audio, subtitle, cast=None, location_key=None):
    return {
        "scene_num": scene_num,
        "narration": "n",
        "shots": [{
            "shot_id": "S001", "sentence_indices": [0], "image_prompt": "p",
            "negative_prompt": "n", "camera_angle": None, "camera_movement": None,
            "image_path": image, "cast": cast or [], "location_key": location_key,
        }],
        "audio_path": audio, "audio_duration": 2.0, "word_timings": [],
        "subtitle_path": subtitle, "mood": "dread", "title": "", "kicker": "",
        "display_narration": "n",
    }


def _state(scenes, run_id="run-001"):
    return {
        "run_id": run_id, "scp_id": "SCP-TEST", "scp_text": "", "scenes": scenes,
        "video_path": None, "current_stage": "video", "gate_states": {},
        "prompt_variant": None, "error": None,
    }


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


@pytest.fixture
def assets(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    subtitle = tmp_path / "scene.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n\n", encoding="utf-8")
    character = tmp_path / "character.png"
    character.write_bytes(_make_rgba_png())
    return SimpleNamespace(image=str(image), audio=str(audio), subtitle=str(subtitle), character=str(character))


@pytest.fixture(autouse=True)
def _silent_trace(monkeypatch):
    monkeypatch.setattr(video, "_record_trace", lambda **kw: None)


@pytest.fixture(autouse=True)
def _fake_which(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/ffmpeg")


# ── Tier 0 (regression) ──────────────────────────────────────────────────────


async def test_tier0_no_harmonization_filters_present(monkeypatch, tmp_path, assets):
    """tier=0: byte-for-byte pre-8.7 filter_complex — no colorbalance/geq/edgedetect. [AC:13]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=0))
    captured = _capture_filter_complex(monkeypatch)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, cast=[_cast_member()])
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    fc = captured[0]
    assert "colorbalance" not in fc
    assert "geq=" not in fc
    assert "edgedetect" not in fc


async def test_tier0_composite_harmonization_not_imported(monkeypatch, tmp_path, assets):
    """tier=0 never imports composite_harmonization.py (AC:13 ponytail lazy-import)."""
    import sys
    sys.modules.pop("yt_flow.pipeline.nodes.composite_harmonization", None)
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=0))
    _capture_filter_complex(monkeypatch)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, cast=[_cast_member()])
    await video_node(_state([scene]))

    assert "yt_flow.pipeline.nodes.composite_harmonization" not in sys.modules


# ── Tier 1 ────────────────────────────────────────────────────────────────────


async def test_tier1_adds_tint_and_shadow(monkeypatch, tmp_path, assets):
    """tier=1: filter_complex contains colorbalance (tint) and geq (contact shadow). [AC:1,2,4]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=1))
    captured = _capture_filter_complex(monkeypatch)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, cast=[_cast_member()])
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    fc = captured[0]
    assert "colorbalance=" in fc
    assert "geq=" in fc
    assert "edgedetect" not in fc  # tier 2 only


async def test_tier1_composite_before_grade(monkeypatch, tmp_path, assets):
    """post_fx grade runs after the last overlay, not before (AC:3 regression). [AC:3]"""
    settings = _settings_ns(tmp_path, composite_harmonization_tier=1)
    settings.post_fx_enabled = True
    monkeypatch.setattr(video, "_settings", lambda: settings)
    captured = _capture_filter_complex(monkeypatch)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, cast=[_cast_member()])
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    fc = captured[0]
    assert "overlay=" in fc and "eq=saturation=" in fc
    assert fc.rindex("overlay=") < fc.rindex("eq=saturation=")


async def test_tier0_vs_tier1_background_only_unaffected(monkeypatch, tmp_path, assets):
    """Background-only shots (no cast) are unaffected by any tier (AC:4)."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=1))
    captured = []

    async def _fake(*args):
        args_list = list(args)
        captured.append(args_list)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)  # no cast
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    args = captured[0]
    assert "-filter_complex" not in args  # unchanged background-only -vf path
    vf = args[args.index("-vf") + 1]
    assert "colorbalance" not in vf and "geq=" not in vf


# ── Tier 2 ────────────────────────────────────────────────────────────────────


async def test_tier2_adds_light_wrap(monkeypatch, tmp_path, assets):
    """tier=2: filter_complex additionally contains edgedetect (light wrap). [AC:5,6]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=2))
    captured = _capture_filter_complex(monkeypatch)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, cast=[_cast_member()])
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    fc = captured[0]
    assert "colorbalance=" in fc
    assert "geq=" in fc
    assert "edgedetect" in fc
    assert "alphamerge" in fc


async def test_tier1_vs_tier2_differ(monkeypatch, tmp_path, assets):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=1))
    captured1 = _capture_filter_complex(monkeypatch)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, cast=[_cast_member()])
    await video_node(_state([scene], run_id="run-tier1"))

    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=2))
    captured2 = _capture_filter_complex(monkeypatch)
    await video_node(_state([scene], run_id="run-tier2"))

    assert captured1[0] != captured2[0]


# ── Tier 3: relit_map substitution ───────────────────────────────────────────


async def test_tier3_relit_map_substitution(monkeypatch, tmp_path, assets):
    """A STOCK (card_key, location_key) pair in relit_map substitutes the sprite path. [AC:10]"""
    relit_path = tmp_path / "relit.png"
    relit_path.write_bytes(assets.character and Path(assets.character).read_bytes())
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=3))

    async def _resolver(scenes, cast_cards):
        return {("STOCK-d-class", "corridor"): relit_path}, {"computed": 1, "failed": 0}

    monkeypatch.setattr(video, "_relight_resolver", _resolver)
    captured_paths = []

    async def _fake(*args):
        args_list = list(args)
        # record every -i argument that isn't the audio/bg path, to see which
        # sprite path actually got fed into ffmpeg
        captured_paths.extend(args_list)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {
        "1:S001": [_card(assets.character, card_key="STOCK-d-class")],
    })

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member(card_key="STOCK-d-class")], location_key="corridor",
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert str(relit_path) in captured_paths
    assert assets.character not in captured_paths


async def test_tier3_missing_pair_uses_original(monkeypatch, tmp_path, assets):
    """A pair absent from relit_map falls back to the original card path. [AC:10]"""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=3))

    async def _resolver(scenes, cast_cards):
        return {}, {"computed": 0, "failed": 1}

    monkeypatch.setattr(video, "_relight_resolver", _resolver)
    captured_paths = []

    async def _fake(*args):
        captured_paths.extend(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {
        "1:S001": [_card(assets.character, card_key="STOCK-d-class")],
    })

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member(card_key="STOCK-d-class")], location_key="corridor",
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert assets.character in captured_paths


async def test_tier3_opaque_relit_sprite_uses_original(monkeypatch, tmp_path, assets):
    """A relit_map hit with an opaque PNG must not bypass sprite alpha validation."""
    relit_path = tmp_path / "relit-opaque.png"
    relit_path.write_bytes(_make_rgb_png())
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=3))

    async def _resolver(scenes, cast_cards):
        return {("STOCK-d-class", "corridor"): relit_path}, {"computed": 1, "failed": 0}

    monkeypatch.setattr(video, "_relight_resolver", _resolver)
    captured_paths = []

    async def _fake(*args):
        captured_paths.extend(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {
        "1:S001": [_card(assets.character, card_key="STOCK-d-class")],
    })

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member(card_key="STOCK-d-class")], location_key="corridor",
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert assets.character in captured_paths
    assert str(relit_path) not in captured_paths


async def test_tier3_malformed_card_without_key_uses_original(monkeypatch, tmp_path, assets):
    """A resolver card with path but no card_key must not crash relit substitution."""
    relit_path = tmp_path / "relit.png"
    relit_path.write_bytes(Path(assets.character).read_bytes())
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=3))

    async def _resolver(scenes, cast_cards):
        return {("STOCK-d-class", "corridor"): relit_path}, {"computed": 1, "failed": 0}

    monkeypatch.setattr(video, "_relight_resolver", _resolver)
    captured_paths = []

    async def _fake(*args):
        captured_paths.extend(args)
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {"1:S001": [{"path": assets.character, "position": "center", "depth": "mid"}]})
    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, location_key="corridor")
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert assets.character in captured_paths
    assert str(relit_path) not in captured_paths


async def test_tier3_relight_resolver_failure_is_non_fatal(monkeypatch, tmp_path, assets):
    """A raising relight resolver never fails the video stage (AC:11)."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=3))

    async def _resolver(scenes, cast_cards):
        raise RuntimeError("comfyui unreachable")

    monkeypatch.setattr(video, "_relight_resolver", _resolver)
    captured = _capture_filter_complex(monkeypatch)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, card_key="STOCK-d-class")]})

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member(card_key="STOCK-d-class")], location_key="corridor",
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    assert captured  # rendered anyway, with the original sprite


async def test_tier_below_3_never_calls_relight_resolver(monkeypatch, tmp_path, assets):
    """tier<3 never invokes the injected relight resolver at all."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=2))
    calls = []

    async def _resolver(scenes, cast_cards):
        calls.append(1)
        return {}, {"computed": 0, "failed": 0}

    monkeypatch.setattr(video, "_relight_resolver", _resolver)
    _capture_filter_complex(monkeypatch)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character)]})

    scene = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle, cast=[_cast_member()])
    await video_node(_state([scene]))

    assert calls == []


# ── Chapter card unaffected ──────────────────────────────────────────────────


async def test_chapter_card_unchanged_regardless_of_tier(monkeypatch, tmp_path, assets):
    """_compose_chapter_card's filter chain never touches composite_harmonization at any tier."""
    settings = _settings_ns(tmp_path, composite_harmonization_tier=3)
    settings.chapter_cards = True
    monkeypatch.setattr(video, "_settings", lambda: settings)
    captured_vf = []

    async def _fake(*args):
        args_list = list(args)
        if "-vf" in args_list:
            captured_vf.append(args_list[args_list.index("-vf") + 1])
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {})

    scene1 = _scene(1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    scene2 = _scene(2, image=assets.image, audio=assets.audio, subtitle=assets.subtitle)
    out = await video_node(_state([scene1, scene2]))

    assert out.get("error") is None
    card_vf = [vf for vf in captured_vf if "drawtext" in vf]
    assert card_vf
    for vf in card_vf:
        assert "colorbalance" not in vf
        assert "geq=" not in vf
        assert "edgedetect" not in vf


# ── Real-ffmpeg integration (skipped without ffmpeg) ─────────────────────────
# Same convention as test_video.py's test_character_overlay_filtergraph_renders:
# a live syntax regression here would slip past every monkeypatched test above.


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("tier", [1, 2])
async def test_tier1_tier2_filtergraph_renders_real_ffmpeg(tmp_path, tier):
    """Real FFmpeg: the actual single-card filter_complex _compose_scene builds
    at tier=1/2 is valid and renders rc=0."""
    from yt_flow.pipeline.nodes.video import _compose_scene

    scene = _scene(
        1,
        image=str(tmp_path / "bg.png"), audio=str(tmp_path / "a.wav"),
        subtitle=str(tmp_path / "s.srt"), cast=[_cast_member()],
    )
    (tmp_path / "bg.png").write_bytes(_make_rgba_png())
    _write_silent_wav(tmp_path / "a.wav")
    (tmp_path / "s.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n", encoding="utf-8")
    character = tmp_path / "character.png"
    character.write_bytes(_make_rgba_png())

    seg_path, _spec, has_char = await _compose_scene(
        scene, 0, tmp_path,
        cards_by_shot={"S001": [{
            "card_key": "SCP-096", "pose": "standing", "angle": "front",
            "path": str(character), "fallback": False, "position": "center",
            "depth": "near", "motion_style": "sway", "motion_energy": "medium",
        }]},
        composite_harmonization_tier=tier,
    )
    assert has_char is True
    assert seg_path.exists()
    assert seg_path.stat().st_size > 0


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_tier2_two_cards_no_label_collision_real_ffmpeg(tmp_path):
    """Real FFmpeg: tier=2 with 2 cards (far+near) — per-card labels (wbg{k}a/b,
    cw{k}, sh{k}...) must not collide across cards. [AC:14]"""
    from yt_flow.pipeline.nodes.video import _compose_scene

    scene = _scene(
        1,
        image=str(tmp_path / "bg.png"), audio=str(tmp_path / "a.wav"),
        subtitle=str(tmp_path / "s.srt"),
        cast=[_cast_member(depth="far", position="left"), _cast_member(card_key="SCP-999", depth="near", position="right")],
    )
    (tmp_path / "bg.png").write_bytes(_make_rgba_png())
    _write_silent_wav(tmp_path / "a.wav")
    (tmp_path / "s.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n", encoding="utf-8")
    character = tmp_path / "character.png"
    character.write_bytes(_make_rgba_png())

    seg_path, _spec, has_char = await _compose_scene(
        scene, 0, tmp_path,
        cards_by_shot={"S001": [
            {
                "card_key": "SCP-096", "pose": "standing", "angle": "front",
                "path": str(character), "fallback": False, "position": "left",
                "depth": "far", "motion_style": "sway", "motion_energy": "medium",
            },
            {
                "card_key": "SCP-999", "pose": "standing", "angle": "front",
                "path": str(character), "fallback": False, "position": "right",
                "depth": "near", "motion_style": "breath", "motion_energy": "low",
            },
        ]},
        composite_harmonization_tier=2,
    )
    assert has_char is True
    assert seg_path.exists()
    assert seg_path.stat().st_size > 0
