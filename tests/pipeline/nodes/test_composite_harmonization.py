"""Tests for src/yt_flow/pipeline/nodes/composite_harmonization.py (Story 8.7)."""

import re
import struct
import zlib
from pathlib import Path
from typing import cast

import pytest

from yt_flow.pipeline.nodes.composite_harmonization import (
    RelightCache,
    MOOD_TINT_PARAMS,
    build_contact_shadow,
    build_light_wrap,
    build_sprite_tint,
    precompute_relights,
)
from yt_flow.domain.state import CastMember, SceneState, ShotData
from yt_flow.pipeline.nodes.sound_design import DEFAULT_MOOD, MOOD_VALUES


# ── build_sprite_tint [AC:1] ─────────────────────────────────────────────────


@pytest.mark.parametrize("mood", MOOD_VALUES)
def test_build_sprite_tint_all_moods(mood):
    f = build_sprite_tint(mood)
    p = MOOD_TINT_PARAMS[mood]
    assert f == (
        f"colorbalance=rs={p['rs']}:gs={p['gs']}:bs={p['bs']}:"
        f"rh={p['rh']}:gh={p['gh']}:bh={p['bh']},"
        f"eq=saturation={p['saturation']}:contrast={p['contrast']}"
    )


@pytest.mark.parametrize("mood", [None, "", "unknown-mood"])
def test_build_sprite_tint_unknown_mood_falls_back_to_dread(mood):
    assert build_sprite_tint(mood) == build_sprite_tint(DEFAULT_MOOD)
    assert DEFAULT_MOOD == "dread"


def test_mood_tint_params_match_mood_values():
    assert set(MOOD_TINT_PARAMS) == set(MOOD_VALUES)


# ── build_contact_shadow [AC:2] ──────────────────────────────────────────────


def _card(depth: str = "mid", position: str = "center") -> CastMember:
    return cast(CastMember, {
        "card_key": "SCP-049", "depth": depth, "position": position, "pose": "standing",
    })


@pytest.mark.parametrize("position", ["left", "center", "right"])
def test_build_contact_shadow_all_positions_produce_valid_geq(position):
    f = build_contact_shadow(_card(position=position))
    assert f.startswith("geq=r=0:g=0:b=0:a=")
    assert ",0)'" in f
    assert "boxblur=" in f


def _shadow_radii(filter_str: str) -> tuple[float, float]:
    """Extract the (rx, ry) ellipse radii baked into the geq alpha expression."""
    matches = re.findall(r"/\(([\d.]+)\*", filter_str)
    assert len(matches) == 2
    return float(matches[0]), float(matches[1])


def test_build_contact_shadow_depth_scales_monotonic():
    rx_near, ry_near = _shadow_radii(build_contact_shadow(_card(depth="near")))
    rx_mid, ry_mid = _shadow_radii(build_contact_shadow(_card(depth="mid")))
    rx_far, ry_far = _shadow_radii(build_contact_shadow(_card(depth="far")))
    assert rx_near > rx_mid > rx_far
    assert ry_near > ry_mid > ry_far


def test_build_contact_shadow_unknown_depth_defaults_to_mid():
    assert build_contact_shadow(_card(depth="unknown")) == build_contact_shadow(_card(depth="mid"))


def test_build_contact_shadow_unknown_position_defaults_to_center():
    assert build_contact_shadow(_card(position="unknown")) == build_contact_shadow(_card(position="center"))


# ── build_light_wrap [AC:5] ──────────────────────────────────────────────────


def test_build_light_wrap_syntax():
    f = build_light_wrap("bg", "c0", "wrapped")
    assert "edgedetect" in f
    assert "boxblur" in f
    assert "alphamerge" in f
    assert "[wrapped]" in f
    assert "[bg]" in f
    assert "[c0]" in f


def test_build_light_wrap_custom_blur_and_intensity():
    f = build_light_wrap("bg", "c0", "wrapped", blur_radius=20, intensity=0.5)
    assert "boxblur=20:1" in f
    assert "aa=0.5" in f


@pytest.mark.parametrize(("position", "crop_x"), [
    ("left", "0"),
    ("center", "iw/3"),
    ("right", "2*iw/3"),
])
def test_build_light_wrap_samples_position_band(position, crop_x):
    f = build_light_wrap("bg", "c0", "wrapped", position=position)
    assert f"[bg]crop=w=iw/3:h=ih:x={crop_x}:y=0" in f


def test_build_light_wrap_labels_dont_collide_across_cards():
    f0 = build_light_wrap("bg", "c0", "cw0")
    f1 = build_light_wrap("shg1", "c1", "cw1")
    labels0 = set(re.findall(r"\[([^\]]+)\]", f0))
    labels1 = set(re.findall(r"\[([^\]]+)\]", f1))
    assert labels0.isdisjoint(labels1)


# ── RelightCache [AC:8] ──────────────────────────────────────────────────────


class _FakeAssetService:
    """Approve-on-write, filesystem-integrity-checked stand-in for AssetService."""

    def __init__(self, root: Path):
        self._root = root
        self.assets: dict[str, dict] = {}
        self.style_epoch = 1

    def get_asset(self, key, *, include_drafts=False):
        entry = self.assets.get(key)
        if entry is None:
            return None
        if not include_drafts and entry["status"] != "approved":
            return None
        return entry

    def add_asset(self, key, path, source, **meta):
        self.assets[key] = {"path": path, "source": source, "status": "draft", **meta}

    def add_approved_asset(self, key, path, source=None, **meta):
        self.add_asset(key, path, source or {}, **meta)
        self.approve_asset(key)

    def approve_asset(self, key):
        self.assets[key]["status"] = "approved"

    def verify_asset(self, key):
        entry = self.assets.get(key)
        return entry is not None and (self._root / entry["path"]).exists()

    def load_manifest(self):
        return {"style_epoch": self.style_epoch, "assets": self.assets}


def _seed_stock_assets(svc: _FakeAssetService, card_path="card.png", location_path="bg.png"):
    svc.add_approved_asset(
        "STOCK-d-class/standing_front", card_path,
        source={"type": "comfyui_generation"}, card_key="STOCK-d-class", pose="standing", angle="front",
    )
    svc.add_approved_asset(
        "corridor/wide", location_path,
        source={"type": "comfyui_generation"}, location_key="corridor", variant="wide",
    )


def test_relight_cache_miss_when_absent(tmp_path):
    svc = _FakeAssetService(tmp_path)
    cache = RelightCache(tmp_path, svc)
    assert cache.get_or_compute("STOCK-d-class", "corridor", 1) is None


def test_relight_cache_store_then_hit(tmp_path):
    svc = _FakeAssetService(tmp_path)
    cache = RelightCache(tmp_path, svc)
    path = cache.store("STOCK-d-class", "corridor", 1, _make_png(6))
    assert path.exists()
    assert path.read_bytes() == _make_png(6)
    hit = cache.get_or_compute("STOCK-d-class", "corridor", 1)
    assert hit == path


def test_relight_cache_stale_epoch_is_a_miss(tmp_path):
    svc = _FakeAssetService(tmp_path)
    cache = RelightCache(tmp_path, svc)
    cache.store("STOCK-d-class", "corridor", 1, _make_png(6))
    assert cache.get_or_compute("STOCK-d-class", "corridor", 2) is None


def test_relight_cache_miss_when_integrity_fails(tmp_path):
    svc = _FakeAssetService(tmp_path)
    cache = RelightCache(tmp_path, svc)
    path = cache.store("STOCK-d-class", "corridor", 1, _make_png(6))
    path.unlink()  # corrupt: manifest entry now points at a missing file
    assert cache.get_or_compute("STOCK-d-class", "corridor", 1) is None


def test_relight_cache_miss_when_cached_png_lacks_alpha(tmp_path):
    svc = _FakeAssetService(tmp_path)
    cache = RelightCache(tmp_path, svc)
    path = cache.store("STOCK-d-class", "corridor", 1, _make_png(6))
    path.write_bytes(_make_png(2))
    assert cache.get_or_compute("STOCK-d-class", "corridor", 1) is None


def test_relight_cache_rejects_manifest_path_escape(tmp_path):
    svc = _FakeAssetService(tmp_path)
    (tmp_path.parent / "outside.png").write_bytes(_make_png(6))
    key = "relit/STOCK-d-class/corridor"
    svc.assets[key] = {
        "path": "../outside.png",
        "source": {},
        "status": "approved",
        "style_epoch": 1,
    }
    assert RelightCache(tmp_path, svc).get_or_compute("STOCK-d-class", "corridor", 1) is None


def test_relight_cache_restores_existing_file_when_manifest_write_fails(tmp_path):
    class _FailingAssetService(_FakeAssetService):
        def add_asset(self, key, path, source, **meta):
            raise RuntimeError("manifest unavailable")

    svc = _FakeAssetService(tmp_path)
    cache = RelightCache(tmp_path, svc)
    path = cache.store("STOCK-d-class", "corridor", 1, _make_png(6))
    before = path.read_bytes()

    failing = _FailingAssetService(tmp_path)
    failing.assets = svc.assets
    with pytest.raises(RuntimeError):
        RelightCache(tmp_path, failing).store(
            "STOCK-d-class", "corridor", 1, _make_png(6, b"\xff\x00\x00\xff")
        )

    assert path.read_bytes() == before


# ── precompute_relights [AC:9,11] ────────────────────────────────────────────


def _scene(scene_num: int, shots: list) -> SceneState:
    return cast(SceneState, {"scene_num": scene_num, "shots": shots, "mood": "dread"})


def _shot(shot_id: str, location_key: str | None = None, image_path: str = "bg.png") -> ShotData:
    return cast(ShotData, {
        "shot_id": shot_id, "image_path": image_path, "location_key": location_key,
        "cast": [], "camera_angle": None, "camera_movement": None,
        "image_prompt": "", "negative_prompt": "", "sentence_indices": [],
    })


class _FakeComfyUIClient:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = 0

    async def upload_image(self, url, image_bytes, filename):
        return filename

    async def submit_and_fetch(self, url, workflow):
        self.calls += 1
        if self.fail:
            raise RuntimeError("comfyui unreachable")
        return _make_png(6)


def _png_chunk(name: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)


def _make_png(color_type: int, sample: bytes | None = None) -> bytes:
    if sample is None:
        sample = b"\x00\x00\x00\x00" if color_type == 6 else b"\x00\x00\x00"
    raw = b"\x00" + sample
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, color_type, 0, 0, 0))
    idat = _png_chunk(b"IDAT", zlib.compress(raw))
    iend = _png_chunk(b"IEND", b"")
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


@pytest.fixture()
def workflow_path(tmp_path):
    import json

    path = tmp_path / "iclight.json"
    path.write_text(json.dumps({
        "ytflow_verified_iclight": True,
        "1": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
    }))
    return str(path)


@pytest.fixture()
def unverified_workflow_path(tmp_path):
    import json

    path = tmp_path / "placeholder-iclight.json"
    path.write_text(json.dumps({
        "1": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
    }))
    return str(path)


@pytest.mark.asyncio
async def test_precompute_relights_only_stock_pairs(tmp_path, workflow_path):
    (tmp_path / "bg.png").write_bytes(b"bg")
    scenes = [
        _scene(1, [_shot("S001", location_key="corridor", image_path=str(tmp_path / "bg.png"))]),
        _scene(2, [_shot("S002", location_key=None, image_path=str(tmp_path / "bg.png"))]),  # non-STOCK bg, excluded
    ]
    cast_cards = {
        "1:S001": [{"card_key": "STOCK-d-class", "path": str(tmp_path / "card.png")}],
        "2:S002": [{"card_key": "STOCK-security", "path": str(tmp_path / "card2.png")}],
    }
    (tmp_path / "card.png").write_bytes(b"card")
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)
    client = _FakeComfyUIClient()
    relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, client, workflow_path, tmp_path, "http://fake",
    )
    assert ("STOCK-d-class", "corridor") in relit_map
    assert len(relit_map) == 1
    assert stats == {"computed": 1, "failed": 0}


@pytest.mark.asyncio
async def test_precompute_relights_excludes_non_stock_card(tmp_path, workflow_path):
    scenes = [_scene(1, [_shot("S001", location_key="corridor")])]
    cast_cards = {"1:S001": [{"card_key": "SCP-049", "path": str(tmp_path / "card.png")}]}
    svc = _FakeAssetService(tmp_path)
    client = _FakeComfyUIClient()
    relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, client, workflow_path, tmp_path, "http://fake",
    )
    assert relit_map == {}
    assert stats == {"computed": 0, "failed": 0}


@pytest.mark.asyncio
async def test_precompute_relights_non_fatal_on_comfyui_failure(tmp_path, workflow_path):
    (tmp_path / "bg.png").write_bytes(b"bg")
    scenes = [_scene(1, [_shot("S001", location_key="corridor", image_path=str(tmp_path / "bg.png"))])]
    cast_cards = {"1:S001": [{"card_key": "STOCK-d-class", "path": str(tmp_path / "card.png")}]}
    (tmp_path / "card.png").write_bytes(b"card")
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)
    client = _FakeComfyUIClient(fail=True)
    relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, client, workflow_path, tmp_path, "http://fake",
    )
    assert relit_map == {}
    assert stats == {"computed": 0, "failed": 1}


@pytest.mark.asyncio
async def test_precompute_relights_unverified_workflow_is_non_fatal(tmp_path, unverified_workflow_path):
    (tmp_path / "bg.png").write_bytes(b"bg")
    (tmp_path / "card.png").write_bytes(b"card")
    scenes = [_scene(1, [_shot("S001", location_key="corridor", image_path=str(tmp_path / "bg.png"))])]
    cast_cards = {"1:S001": [{"card_key": "STOCK-d-class", "path": str(tmp_path / "card.png")}]}
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)
    relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, _FakeComfyUIClient(),
        unverified_workflow_path, tmp_path, "http://fake",
    )
    assert relit_map == {}
    assert stats == {"computed": 0, "failed": 1}


@pytest.mark.asyncio
async def test_precompute_relights_skips_unsafe_cache_keys(tmp_path, workflow_path):
    (tmp_path / "bg.png").write_bytes(b"bg")
    (tmp_path / "card.png").write_bytes(b"card")
    scenes = [_scene(1, [_shot("S001", location_key="../outside", image_path=str(tmp_path / "bg.png"))])]
    cast_cards = {"1:S001": [{"card_key": "STOCK-d-class", "path": str(tmp_path / "card.png")}]}
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)
    relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, _FakeComfyUIClient(),
        workflow_path, tmp_path, "http://fake",
    )
    assert relit_map == {}
    assert stats == {"computed": 0, "failed": 0}


@pytest.mark.asyncio
async def test_precompute_relights_cache_hit_skips_comfyui(tmp_path, workflow_path):
    (tmp_path / "bg.png").write_bytes(b"bg")
    scenes = [_scene(1, [_shot("S001", location_key="corridor", image_path=str(tmp_path / "bg.png"))])]
    cast_cards = {"1:S001": [{"card_key": "STOCK-d-class", "path": str(tmp_path / "card.png")}]}
    (tmp_path / "card.png").write_bytes(b"card")
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)
    RelightCache(tmp_path, svc).store("STOCK-d-class", "corridor", 1, _make_png(6))
    client = _FakeComfyUIClient()
    _relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, client, workflow_path, tmp_path, "http://fake",
    )
    assert client.calls == 0
    assert stats == {"computed": 1, "failed": 0}
