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
        character_idle_motion_enabled=True,
        background_camera_motion_enabled=True,
        # Story 11.5: the 2.5D renderer is never injected in these tests, so the
        # kill-switch value only has to exist; build_motion_source takes the
        # legacy zoompan path either way.
        parallax_25d_enabled=False,
        parallax_displacement_frac=0.02,
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
        return {("STOCK-d-class__standing__front", "corridor"): relit_path}, {"computed": 1, "failed": 0}

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
        return {("STOCK-d-class__standing__front", "corridor"): relit_path}, {"computed": 1, "failed": 0}

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
        return {("STOCK-d-class__standing__front", "corridor"): relit_path}, {"computed": 1, "failed": 0}

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


@pytest.mark.asyncio
async def test_tier3_two_poses_of_one_card_key_get_their_own_sprites(monkeypatch, tmp_path, assets):
    """The pose-swap symptom, pinned at the substitution site (Story 10.1b).

    `precompute_relights` keying by variant is only half the fix — video.py has to
    look up by the same key. Keyed on bare `card_key`, both cards in this shot
    would collapse onto whichever sprite the map happened to hold, which is the
    defect: on run 8a9a288b, STOCK-d-class's `hint:` sprite (silhouette IoU 0.63
    against `standing`) landed on all 12 of its `standing` shots.
    """
    source = Path(assets.character).read_bytes()
    relit_standing = tmp_path / "relit_standing.png"
    relit_hinted = tmp_path / "relit_hinted.png"
    relit_standing.write_bytes(source)
    relit_hinted.write_bytes(source)
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=3))

    async def _resolver(scenes, cast_cards):
        return {
            ("STOCK-d-class__standing__front", "corridor"): relit_standing,
            ("STOCK-d-class__hint_a40ec9c170__front", "corridor"): relit_hinted,
        }, {"computed": 2, "failed": 0}

    monkeypatch.setattr(video, "_relight_resolver", _resolver)
    captured = []

    async def _fake(*args):
        captured.extend(list(args))
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    standing_card = _card(assets.character, card_key="STOCK-d-class", position="left")
    hinted_card = {**_card(assets.character, card_key="STOCK-d-class", position="right"),
                   "pose": "hint:a40ec9c170"}
    _inject_resolver(monkeypatch, {"1:S001": [standing_card, hinted_card]})

    scene = _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member(card_key="STOCK-d-class", position="left"),
              _cast_member(card_key="STOCK-d-class", position="right")],
        location_key="corridor",
    )
    out = await video_node(_state([scene]))

    assert out.get("error") is None
    # each pose got ITS OWN sprite — not one sprite twice
    assert str(relit_standing) in captured
    assert str(relit_hinted) in captured
    assert assets.character not in captured


# ── Story 13.1: Tier-3 relight degradations reach the gate ───────────────────


def _relight_scene(assets):
    return _scene(
        1, image=assets.image, audio=assets.audio, subtitle=assets.subtitle,
        cast=[_cast_member(card_key="STOCK-d-class")], location_key="corridor",
    )


async def _relight_warnings_for(monkeypatch, tmp_path, assets, *, resolver, cards=None):
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=3))
    monkeypatch.setattr(video, "_relight_resolver", resolver)

    async def _fake(*args):
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, cards if cards is not None else {
        "1:S001": [_card(assets.character, card_key="STOCK-d-class")],
    })
    out = await video_node(_state([_relight_scene(assets)]))
    assert out.get("error") is None      # relight degradation is never fatal (AC3)
    assert out["video_path"]
    return out["run_warnings"]


async def test_tier3_without_an_injected_resolver_warns_once(monkeypatch, tmp_path, assets):
    """Tier 3 was ASKED for and the seam is unwired — every card composites unlit."""
    warnings = await _relight_warnings_for(monkeypatch, tmp_path, assets, resolver=None)
    assert [w["code"] for w in warnings] == ["relight_resolver_unavailable"]
    assert warnings[0]["stage"] == "video"
    assert warnings[0]["context"] == {"reason": "resolver_not_injected"}


async def test_tier_below_three_is_warning_free(monkeypatch, tmp_path, assets):
    """`composite_harmonization_tier = 1` is the shipped default — a config choice,
    not a degradation (AC2)."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path, composite_harmonization_tier=1))
    monkeypatch.setattr(video, "_relight_resolver", None)

    async def _fake(*args):
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, card_key="STOCK-d-class")]})
    out = await video_node(_state([_relight_scene(assets)]))
    assert out["run_warnings"] == []


async def test_a_raising_relight_resolver_warns_with_bounded_detail(monkeypatch, tmp_path, assets):
    async def _boom(scenes, cast_cards):
        raise RuntimeError("IC-Light workflow missing")

    warnings = await _relight_warnings_for(monkeypatch, tmp_path, assets, resolver=_boom)
    assert [w["code"] for w in warnings] == ["relight_resolver_unavailable"]
    assert warnings[0]["context"]["reason"] == "resolver_raised"
    assert warnings[0]["context"]["detail"] == "RuntimeError: IC-Light workflow missing"


async def test_an_opaque_relit_sprite_warns_and_names_the_shot(monkeypatch, tmp_path, assets):
    """The original card still renders — the operator's only clue is this record."""
    relit_path = tmp_path / "relit-opaque.png"
    relit_path.write_bytes(_make_rgb_png())

    async def _resolver(scenes, cast_cards):
        return {("STOCK-d-class__standing__front", "corridor"): relit_path}, {"computed": 1, "failed": 0}

    warnings = await _relight_warnings_for(monkeypatch, tmp_path, assets, resolver=_resolver)
    assert [w["code"] for w in warnings] == ["relit_sprite_invalid"]
    assert warnings[0]["context"] == {
        "scene_num": 1, "shot_id": "S001", "card_key": "STOCK-d-class",
        "location_key": "corridor", "reason": "no_alpha",
    }


async def test_a_bailed_recompose_preflight_reaches_the_gate(monkeypatch, tmp_path, assets):
    """Story 10.1d: a run-level bail is otherwise INDISTINGUISHABLE from the feature being
    off — same overlay render, same cards, same filtergraph. This row is the difference."""
    settings = _settings_ns(tmp_path)
    settings.shot_recompose_enabled = True
    monkeypatch.setattr(video, "_settings", lambda: settings)

    # Shaped like the service's real text: headline first, then ~370 chars of argv repr and
    # the flags to add. make_warning truncates `detail` at 200, so passing the whole thing
    # would cut off everything actionable — the gate gets the headline alone.
    headline = "Shot recompose preflight failed: ComfyUI is missing --lowvram, --cache-lru."

    async def _bailed(scenes, cast_cards):
        return cast_cards, {"recomposed": 0, "skipped": 0, "failed": 0,
                            "preflight_failed": "missing_flags",
                            "preflight_detail": "\n".join([headline, "  observed argv: " + "y" * 400,
                                                           "  add to ComfyUI's launcher…"])}

    monkeypatch.setattr(video, "_recompose_resolver", _bailed)

    async def _fake(*args):
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, card_key="STOCK-d-class")]})

    out = await video_node(_state([_relight_scene(assets)]))

    assert out.get("error") is None      # a preflight bail is a degradation, never fatal
    warnings = out["run_warnings"]
    assert [w["code"] for w in warnings] == ["recompose_preflight_failed"]
    assert warnings[0]["stage"] == "video"
    assert warnings[0]["context"]["reason"] == "missing_flags"
    # Intact, not truncated at 200: the row's whole job is to name what is wrong.
    assert warnings[0]["context"]["detail"] == headline


async def test_a_raising_recompose_resolver_files_a_warning_too(monkeypatch, tmp_path, assets):
    """The blanket except is AD-10 (never fail the run), not a licence to be silent: a
    resolver that raises renders exactly like a preflight bail, so it needs the same row."""
    settings = _settings_ns(tmp_path)
    settings.shot_recompose_enabled = True
    monkeypatch.setattr(video, "_settings", lambda: settings)

    async def _boom(scenes, cast_cards):
        raise RuntimeError("recompose exploded")

    monkeypatch.setattr(video, "_recompose_resolver", _boom)

    async def _fake(*args):
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, card_key="STOCK-d-class")]})

    out = await video_node(_state([_relight_scene(assets)]))

    assert out.get("error") is None
    warnings = out["run_warnings"]
    assert [w["code"] for w in warnings] == ["recompose_preflight_failed"]
    assert warnings[0]["context"]["reason"] == "resolver_error"
    assert "recompose exploded" in warnings[0]["context"]["detail"]


async def test_recompose_resolver_is_untouched_while_the_flag_is_off(monkeypatch, tmp_path, assets):
    """The test Settings stubs omit `shot_recompose_enabled` entirely, and absent == off
    via `getattr(s, ..., False)`. That must keep holding now that the shipped default is
    True (10.1e): this asserts the GATE, not the default, and it is also what keeps the
    preflight's `/system_stats` request off any run that never asked for recompose."""
    monkeypatch.setattr(video, "_settings", lambda: _settings_ns(tmp_path))
    calls = []

    async def _resolver(scenes, cast_cards):
        calls.append(1)
        return cast_cards, {}

    monkeypatch.setattr(video, "_recompose_resolver", _resolver)

    async def _fake(*args):
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, card_key="STOCK-d-class")]})

    out = await video_node(_state([_relight_scene(assets)]))

    assert calls == []
    assert out["run_warnings"] == []


async def test_an_unreadable_relit_sprite_warns_with_the_os_error(monkeypatch, tmp_path, assets):
    missing = tmp_path / "vanished.png"  # in the map, never on disk

    async def _resolver(scenes, cast_cards):
        return {("STOCK-d-class__standing__front", "corridor"): missing}, {"computed": 1, "failed": 0}

    warnings = await _relight_warnings_for(monkeypatch, tmp_path, assets, resolver=_resolver)
    assert [w["code"] for w in warnings] == ["relit_sprite_invalid"]
    assert warnings[0]["context"]["reason"] == "unreadable"
    assert "FileNotFoundError" in warnings[0]["context"]["detail"]


async def test_precompute_counts_become_warnings_at_the_gate(monkeypatch, tmp_path, assets):
    """`precompute_relights` can only report aggregates for pairs it never materialised;
    those counts are what reach the operator."""
    async def _resolver(scenes, cast_cards):
        return {}, {"computed": 0, "failed": 2, "skipped": 3,
                    "skipped_details": [{"reason": "card_asset_unverified", "scene_num": 1,
                                          "shot_id": "S001", "location_key": "corridor"}]}

    warnings = await _relight_warnings_for(monkeypatch, tmp_path, assets, resolver=_resolver)
    assert [w["code"] for w in warnings] == [
        "relight_failed", "relight_pair_skipped", "relight_pair_skipped"]
    assert warnings[0]["context"] == {"failed_count": 2}
    assert warnings[1]["context"]["reason"] == "card_asset_unverified"
    assert warnings[2]["context"] == {"skipped_count": 3}


async def test_a_clean_tier3_run_is_warning_free(monkeypatch, tmp_path, assets):
    relit_path = tmp_path / "relit.png"
    relit_path.write_bytes(Path(assets.character).read_bytes())

    async def _resolver(scenes, cast_cards):
        return {("STOCK-d-class__standing__front", "corridor"): relit_path}, {"computed": 1, "failed": 0}

    assert await _relight_warnings_for(monkeypatch, tmp_path, assets, resolver=_resolver) == []


async def test_partial_recompose_degradation_files_its_own_warning(monkeypatch, tmp_path, assets):
    """Story 10.1e ships the flag True, so "preflight passed and then some shots fell back"
    is a production state. Until this row existed the only reported recompose outcome was
    the all-or-nothing preflight bail, so a half-recomposed run read as a clean one."""
    settings = _settings_ns(tmp_path)
    settings.shot_recompose_enabled = True
    monkeypatch.setattr(video, "_settings", lambda: settings)

    async def _resolver(scenes, cast_cards):
        return cast_cards, {"recomposed": 12, "skipped": 3, "failed": 2}

    monkeypatch.setattr(video, "_recompose_resolver", _resolver)

    async def _fake(*args):
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, card_key="STOCK-d-class")]})

    out = await video_node(_state([_relight_scene(assets)]))

    codes = [w["code"] for w in out["run_warnings"]]
    assert codes.count("recompose_shots_degraded") == 1
    row = next(w for w in out["run_warnings"] if w["code"] == "recompose_shots_degraded")
    assert row["context"]["reason"] == "failed=2 skipped=3"


async def test_flag_on_without_an_injected_resolver_is_not_silent(monkeypatch, tmp_path, assets):
    """Only `api/main.py`'s lifespan injects the resolver. With the flag now True by default,
    any other entry point would render the overlay while the config says recompose is on."""
    settings = _settings_ns(tmp_path)
    settings.shot_recompose_enabled = True
    monkeypatch.setattr(video, "_settings", lambda: settings)
    monkeypatch.setattr(video, "_recompose_resolver", None)

    async def _fake(*args):
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, card_key="STOCK-d-class")]})

    out = await video_node(_state([_relight_scene(assets)]))

    row = next(w for w in out["run_warnings"] if w["code"] == "recompose_shots_degraded")
    assert row["context"]["reason"] == "resolver_not_injected"


# ── Story 14.3: recompose attribution reaches the gate and the trace ──────────


async def test_precompute_relights_is_unreachable_at_the_shipped_tier(monkeypatch, tmp_path, assets):
    """The disproof of the coupling handover, pinned.

    Story 14.1 handed 14.3 a relight/harmonization pair-key defect described as "already
    firing in run 4b35c0ed". It cannot fire: the pair key lives inside
    `composite_harmonization.precompute_relights`, `video_node` calls that function only
    at `composite_harmonization_tier >= 3`, and the shipped default is 1 (tier 3 is
    IC-Light, which Jay's 10.1b viewing rejected). Asserting the default here as well as
    the branch is deliberate — a test that only checked the branch would keep passing if
    someone raised the default, which is precisely the state that would make the
    handover true.
    """
    from yt_flow.config import Settings

    shipped = Settings.model_fields["composite_harmonization_tier"].default
    assert shipped == 1, "the shipped tier moved; re-open the 14.1 relight handover"

    called = []

    async def _resolver(scenes, cast_cards):
        called.append(1)
        return {}, {"computed": 0, "failed": 0}

    monkeypatch.setattr(video, "_settings",
                        lambda: _settings_ns(tmp_path, composite_harmonization_tier=shipped))
    monkeypatch.setattr(video, "_relight_resolver", _resolver)

    async def _fake(*args):
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", _fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, card_key="STOCK-d-class")]})

    out = await video_node(_state([_relight_scene(assets)]))

    assert out.get("error") is None
    assert called == []          # the pair key is never built, so it cannot collide
    assert [w for w in out["run_warnings"] if w["code"].startswith("relight")] == []


async def _recompose_run(
    monkeypatch, tmp_path, assets, *, resolver, ffmpeg=None, enabled=True, prior_warnings=None,
):
    settings = _settings_ns(tmp_path)
    settings.shot_recompose_enabled = enabled
    monkeypatch.setattr(video, "_settings", lambda: settings)
    monkeypatch.setattr(video, "_recompose_resolver", resolver)

    async def _fake(*args):
        Path(args[-1]).write_bytes(b"FAKE_MP4")
        return 0, ""

    monkeypatch.setattr(video, "_run_ffmpeg", ffmpeg or _fake)
    _inject_resolver(monkeypatch, {"1:S001": [_card(assets.character, card_key="STOCK-d-class")]})
    state = _state([_relight_scene(assets)])
    if prior_warnings is not None:
        state["run_warnings"] = prior_warnings
    return await video_node(state)


async def test_a_lost_recompose_attribution_reaches_the_gate(monkeypatch, tmp_path, assets):
    """Its own code, not `recompose_shots_degraded`: the frame is correct and only the
    record is gone, so the operator must be told NOT to re-render it."""
    async def _resolver(scenes, cast_cards):
        return cast_cards, {
            "recomposed": 1, "skipped": 0, "failed": 0,
            "warnings": [
                {"scene_num": 1, "shot_id": "S001", "detail": "OSError: [Errno 28]"}]}

    out = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver)

    assert out.get("error") is None
    row = next(w for w in out["run_warnings"] if w["code"] == "recompose_sidecar_failed")
    assert row["stage"] == "video"
    # scene and shot as SEPARATE fields, the way every sibling warning in this node
    # carries them — a row whose `shot_id` were "1:S001" would never join against them.
    assert row["context"] == {
        "scene_num": 1, "shot_id": "S001", "detail": "OSError: [Errno 28]"}


@pytest.mark.parametrize("payload", ["not a dict", None, ["recomposed", 1]])
async def test_a_malformed_stats_payload_is_not_reported_as_a_preflight_bail(
    monkeypatch, tmp_path, assets, payload,
):
    """Not a preflight bail, but not silent either.

    By the time the resolver returns it has already rewritten `image_path` on every shot
    it recomposed, so `recompose_preflight_failed` ("recompose did not run, everything is
    on the overlay") would be a false statement about swapped frames. Coercing to `{}`
    with nothing filed was the opposite failure and shipped first: the trace reads 0/0/0
    and no warning exists, which is byte-identical to "recompose was off" — after 33
    frames were already swapped. The outcome is unreadable, and unreadable is a finding.
    """
    async def _resolver(scenes, cast_cards):
        return cast_cards, payload

    out = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver)

    assert out.get("error") is None
    assert [w["code"] for w in out["run_warnings"] if w["code"].startswith("recompose")] == [
        "recompose_shots_degraded"]
    row = next(w for w in out["run_warnings"] if w["code"] == "recompose_shots_degraded")
    assert row["context"]["reason"] == "stats_payload_unreadable"
    assert type(payload).__name__ in row["context"]["detail"]


@pytest.mark.parametrize("bad_cast", ["not a dict", None, [("1:S001", [])]])
async def test_an_unreadable_cast_map_does_not_silently_empty_the_render(
    monkeypatch, tmp_path, assets, bad_cast,
):
    """A non-dict FIRST element drops every card, and "no cards composited" is exactly
    what a fully successful recompose looks like — so the shot would ship people-less
    with nothing said anywhere."""
    async def _resolver(scenes, cast_cards):
        return bad_cast, {"recomposed": 0, "skipped": 0, "failed": 0}

    out = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver)

    assert out.get("error") is None
    row = next(w for w in out["run_warnings"] if w["code"] == "recompose_shots_degraded")
    assert row["context"]["reason"] == "cast_payload_unreadable"


@pytest.mark.parametrize(
    "warnings_payload", ["boom", {"shot_id": "x"}, [None, 3, "y"], [{"oops": 1}], [{"shot_id": 7}],
    # `""` and `"   "` are `str`, so they sailed through the type check into exactly the
    # context-free operator row the key check was added to prevent.
    [{"shot_id": ""}], [{"shot_id": "   ", "detail": "OSError"}]])
async def test_a_malformed_sidecar_warning_list_is_ignored_not_fatal(
    monkeypatch, tmp_path, assets, warnings_payload,
):
    async def _resolver(scenes, cast_cards):
        return cast_cards, {"recomposed": 1, "skipped": 0, "failed": 0,
                            "warnings": warnings_payload}

    out = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver)

    assert out.get("error") is None
    assert [w for w in out["run_warnings"] if w["code"] == "recompose_sidecar_failed"] == []


async def test_recompose_counts_reach_the_trace(monkeypatch, tmp_path, assets):
    traces = []
    monkeypatch.setattr(video, "_record_trace", lambda **kw: traces.append(kw))

    async def _resolver(scenes, cast_cards):
        return cast_cards, {"recomposed": 12, "skipped": 3, "reentered": 4,
                            "failed": 2, "attributed": 11}

    await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver)

    assert traces[-1]["recomposed"] == 12
    assert traces[-1]["recompose_skipped"] == 3
    assert traces[-1]["recompose_failed"] == 2
    # Re-entry is its own field, never folded into `skipped` — a retried video stage over
    # already-recomposed shots would otherwise trace "33 shots were not recomposed".
    assert traces[-1]["recompose_reentered"] == 4
    # And how many of the recomposed frames actually carry a sidecar block, so
    # `recomposed` is readable as coverage instead of assumed to be.
    assert traces[-1]["recompose_attributed"] == 11


async def test_recompose_counts_survive_a_later_stage_failure(monkeypatch, tmp_path, assets):
    """The error path used to trace 0/0/0, which is also what "recompose ran and did
    nothing" looks like. Recompose runs early and its frames are already on disk."""
    traces = []
    monkeypatch.setattr(video, "_record_trace", lambda **kw: traces.append(kw))

    async def _resolver(scenes, cast_cards):
        return cast_cards, {"recomposed": 12, "skipped": 3, "failed": 2}

    async def _dying_ffmpeg(*args):
        raise RuntimeError("ffmpeg died after the frames were swapped")

    out = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver, ffmpeg=_dying_ffmpeg)

    assert out["error"]
    assert traces[-1]["error"] is not None
    assert traces[-1]["recomposed"] == 12
    assert traces[-1]["recompose_skipped"] == 3
    assert traces[-1]["recompose_failed"] == 2


@pytest.mark.parametrize("bad", [True, "12", 1.5])
async def test_a_non_int_recompose_count_traces_as_zero_and_reaches_the_gate(
    monkeypatch, tmp_path, assets, bad,
):
    """`True` is an `int` in Python and would trace as 1; a `str` would break the span
    encoder inside `_record_trace`'s blanket except and lose the whole metadata dict.

    Zeroing it is not enough on its own. `{"recomposed": "33"}` after 33 frames were
    swapped traces `recomposed=0` with no recompose warning anywhere — byte-identical to
    "recompose was off", which is the state the sibling `stats_payload_unreadable` fix
    closed for a non-dict payload and left open one level down.
    """
    traces = []
    monkeypatch.setattr(video, "_record_trace", lambda **kw: traces.append(kw))

    async def _resolver(scenes, cast_cards):
        return cast_cards, {"recomposed": bad, "skipped": 0, "failed": 0}

    out = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver)

    assert traces[-1]["recomposed"] == 0
    row = next(w for w in out["run_warnings"] if w["code"] == "recompose_shots_degraded")
    assert row["context"]["reason"] == "stats_payload_unreadable"
    assert repr(bad) in row["context"]["detail"]


async def test_an_explicitly_unmeasured_recompose_count_stays_silent(monkeypatch, tmp_path, assets):
    """`None` is how a producer says "not measured", and absent legitimately means the
    stage never ran — the same rule `_stat_count` already applies, so the warning and the
    trace cannot disagree."""
    traces = []
    monkeypatch.setattr(video, "_record_trace", lambda **kw: traces.append(kw))

    async def _resolver(scenes, cast_cards):
        return cast_cards, {"recomposed": None, "skipped": 0, "failed": 0}

    out = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver)

    assert traces[-1]["recomposed"] == 0
    assert [w for w in out["run_warnings"] if w["code"].startswith("recompose")] == []


# ── Story 14.3 follow-up review patches ──────────────────────────────────────


async def test_an_unreadable_cast_map_keeps_the_cards_of_shots_recompose_did_not_swap(
    monkeypatch, tmp_path, assets,
):
    """The blanket drop was justified by "the resolver may already have swapped
    `image_path`" — which is true only of the shots it RECOMPOSED. A shot it skipped or
    failed still needs its cards on the overlay, and dropping them shipped it people-less
    while the two warnings filed here describe a different failure entirely."""
    traces = []
    monkeypatch.setattr(video, "_record_trace", lambda **kw: traces.append(kw))

    async def _resolver(scenes, cast_cards):
        # Nothing swapped: 43-shot production shape is `skipped`, and this shot's
        # `image_path` still points at its plate.
        return None, {"recomposed": 0, "skipped": 1, "failed": 0}

    out = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver)

    row = next(w for w in out["run_warnings"] if w["code"] == "recompose_shots_degraded")
    assert row["context"]["reason"] == "cast_payload_unreadable"
    assert traces[-1]["card_counts"] == [1]          # the figure still reaches the screen


async def test_an_unreadable_cast_map_still_drops_the_cards_of_recomposed_shots(
    monkeypatch, tmp_path, assets,
):
    """The half the blanket drop got right, kept: a recomposed frame already contains the
    figures, so overlaying onto it draws everyone twice. Identified by the frame's
    parent directory, which is what a recompose swap always writes into."""
    traces = []
    monkeypatch.setattr(video, "_record_trace", lambda **kw: traces.append(kw))
    frame = tmp_path / "recomposed" / "S001_abc.png"
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(Path(assets.image).read_bytes())

    async def _resolver(scenes, cast_cards):
        scenes[0]["shots"][0]["image_path"] = str(frame)
        return None, {"recomposed": 1, "skipped": 0, "failed": 0}

    out = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver)

    assert next(w for w in out["run_warnings"]
                if w["code"] == "recompose_shots_degraded")["context"]["reason"] == \
        "cast_payload_unreadable"
    assert traces[-1]["card_counts"] == [0]


async def test_the_trace_separates_recompose_off_from_recompose_on_and_noop(
    monkeypatch, tmp_path, assets,
):
    """An off run and an on-but-noop run traced identically — the exact ambiguity the
    counters were added to remove. `.env` can flip `shot_recompose_enabled` off
    (`gotcha_env-file-beats-code-default`) and only `api/main.py` injects the resolver,
    so `recomposed=0` had three indistinguishable causes."""
    traces = []
    monkeypatch.setattr(video, "_record_trace", lambda **kw: traces.append(kw))

    async def _noop(scenes, cast_cards):
        return cast_cards, {"recomposed": 0, "skipped": 0, "reentered": 0,
                            "failed": 0, "attributed": 0}

    await _recompose_run(monkeypatch, tmp_path, assets, resolver=_noop)
    on = traces[-1]
    await _recompose_run(monkeypatch, tmp_path, assets, resolver=None, enabled=False)
    off = traces[-1]

    assert (on["recompose_enabled"], on["recompose_resolver_injected"]) == (True, True)
    assert (off["recompose_enabled"], off["recompose_resolver_injected"]) == (False, False)
    assert on["recomposed"] == off["recomposed"] == 0     # the counts alone cannot tell


async def test_a_sidecar_failure_is_retracted_once_a_retry_re_stamps_it(
    monkeypatch, tmp_path, assets,
):
    """`merge` is whole-field replacement over the checkpoint, so a row filed on attempt 1
    outlived the retry that restored the attribution — and the gate then told the operator
    the record was lost after it came back."""
    prior = [
        video.make_warning("recompose_sidecar_failed", scene_num=1, shot_id="S001",
                           detail="OSError: [Errno 28]"),
        video.make_warning("recompose_sidecar_failed", scene_num=1, shot_id="S002",
                           detail="OSError: [Errno 28]"),
        video.make_warning("cast_resolution_failed", scp_id="SCP-TEST"),
    ]

    async def _resolver(scenes, cast_cards):
        # S001 re-stamped; S002 still cannot be written.
        return cast_cards, {"recomposed": 2, "skipped": 0, "failed": 0, "attributed": 1,
                            "warnings": [{"scene_num": 1, "shot_id": "S002",
                                          "detail": "OSError: [Errno 28]"}]}

    out = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_resolver,
                               prior_warnings=prior)

    lost = [w["context"]["shot_id"] for w in out["run_warnings"]
            if w["code"] == "recompose_sidecar_failed"]
    assert lost == ["S002"]
    # Only this code is retracted, and only by a pass entitled to speak about it.
    assert any(w["code"] == "cast_resolution_failed" for w in out["run_warnings"])


async def test_a_run_that_cannot_speak_to_attribution_retracts_nothing(
    monkeypatch, tmp_path, assets,
):
    """A run with recompose off, or with an unreadable stats payload, knows nothing about
    which shots still owe an attribution — so it must leave every row standing rather than
    clear the gate by ignorance."""
    prior = [video.make_warning("recompose_sidecar_failed", scene_num=1, shot_id="S001",
                                detail="OSError: [Errno 28]")]

    off = await _recompose_run(monkeypatch, tmp_path, assets, resolver=None,
                               enabled=False, prior_warnings=prior)

    async def _unreadable(scenes, cast_cards):
        return cast_cards, "not a dict"

    unreadable = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_unreadable,
                                      prior_warnings=prior)

    async def _malformed_rows(scenes, cast_cards):
        # A readable payload whose failure LIST is garbage: the counts are known, the
        # shots that still owe an attribution are not.
        return cast_cards, {"recomposed": 1, "skipped": 0, "failed": 0, "warnings": "boom"}

    malformed = await _recompose_run(monkeypatch, tmp_path, assets, resolver=_malformed_rows,
                                     prior_warnings=prior)

    for out in (off, unreadable, malformed):
        assert [w["context"]["shot_id"] for w in out["run_warnings"]
                if w["code"] == "recompose_sidecar_failed"] == ["S001"]
