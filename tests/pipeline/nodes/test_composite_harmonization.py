"""Tests for src/yt_flow/pipeline/nodes/composite_harmonization.py (Story 8.7)."""

import json
import re
import struct
import zlib
from pathlib import Path
from typing import cast

import pytest

from yt_flow.pipeline.nodes.composite_harmonization import (
    BACKGROUND_IMAGE_NODE,
    CARD_IMAGE_NODE,
    RelightCache,
    MOOD_TINT_PARAMS,
    _inject_relight_inputs,
    _load_iclight_workflow,
    _upload_name,
    build_contact_shadow,
    card_variant,
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
        self.uploaded: list[str] = []

    async def upload_image(self, url, image_bytes, filename):
        self.uploaded.append(filename)
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
    assert ("STOCK-d-class__standing__front", "corridor") in relit_map
    assert len(relit_map) == 1
    assert stats == {"computed": 1, "failed": 0}


@pytest.mark.asyncio
async def test_precompute_relights_includes_entity_card(tmp_path, workflow_path):
    """Story 10.1b: an entity card over a verified location is eligible.

    Until 10.1b the ``STOCK_CAST_KEYS`` gate excluded these, which on run
    8a9a288b left exactly one eligible pair and relit none of the SCP-049
    cards the finding-3 adjudication frames are built from.
    """
    (tmp_path / "bg.png").write_bytes(b"bg")
    (tmp_path / "card.png").write_bytes(b"card")
    scenes = [_scene(1, [_shot("S001", location_key="corridor", image_path=str(tmp_path / "bg.png"))])]
    cast_cards = {"1:S001": [{"card_key": "SCP-049", "path": str(tmp_path / "card.png")}]}
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)
    svc.add_approved_asset(
        "SCP-049/standing_front", "card.png",
        source={"type": "comfyui_generation"}, card_key="SCP-049", pose="standing", angle="front",
    )
    relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, _FakeComfyUIClient(), workflow_path, tmp_path, "http://fake",
    )
    assert ("SCP-049__standing__front", "corridor") in relit_map
    assert stats == {"computed": 1, "failed": 0}


@pytest.mark.asyncio
async def test_precompute_relights_excludes_unverified_card(tmp_path, workflow_path):
    """Widening eligibility to entity cards must not widen it to unverified ones."""
    (tmp_path / "bg.png").write_bytes(b"bg")
    (tmp_path / "card.png").write_bytes(b"card")
    scenes = [_scene(1, [_shot("S001", location_key="corridor", image_path=str(tmp_path / "bg.png"))])]
    cast_cards = {"1:S001": [{"card_key": "SCP-049", "path": str(tmp_path / "card.png")}]}
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)  # location verified, SCP-049 card never registered
    client = _FakeComfyUIClient()
    relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, client, workflow_path, tmp_path, "http://fake",
    )
    assert relit_map == {}
    # Story 13.1: the skip is now *accounted for*, with the card and shot named — an
    # unverified card silently compositing unlit is exactly the class of miss the
    # {computed, failed} pair could not express.
    assert stats["computed"] == 0
    assert stats["failed"] == 0
    assert stats["skipped"] == 1
    assert stats["skipped_details"] == [{
        "reason": "card_asset_unverified", "scene_num": 1, "shot_id": "S001",
        "card_key": "SCP-049", "location_key": "corridor",
    }]
    assert client.calls == 0


@pytest.mark.asyncio
async def test_precompute_relights_skips_shot_without_location_key(tmp_path, workflow_path):
    """A free-text background has no stable identity to cache against — a skip, not an error."""
    (tmp_path / "bg.png").write_bytes(b"bg")
    (tmp_path / "card.png").write_bytes(b"card")
    scenes = [_scene(1, [_shot("S001", location_key=None, image_path=str(tmp_path / "bg.png"))])]
    cast_cards = {"1:S001": [{"card_key": "STOCK-d-class", "path": str(tmp_path / "card.png")}]}
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)
    client = _FakeComfyUIClient()
    relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, client, workflow_path, tmp_path, "http://fake",
    )
    assert relit_map == {}
    assert stats == {"computed": 0, "failed": 0}
    assert client.calls == 0


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
    assert stats["computed"] == 0
    assert stats["failed"] == 1
    assert stats["failed_details"] == [{
        "reason": "render_failed", "card_variant": "STOCK-d-class__standing__front",
        "location_key": "corridor",
    }]


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
    assert stats["computed"] == 0
    assert stats["failed"] == 1
    assert [d["reason"] for d in stats["failed_details"]] == ["render_failed"]


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
    assert stats["computed"] == 0
    assert stats["failed"] == 0
    assert stats["skipped"] == 1
    assert stats["skipped_details"] == [
        {"reason": "unsafe_location_key", "scene_num": 1, "shot_id": "S001"},
    ]


@pytest.mark.asyncio
async def test_precompute_relights_cache_hit_skips_comfyui(tmp_path, workflow_path):
    (tmp_path / "bg.png").write_bytes(b"bg")
    scenes = [_scene(1, [_shot("S001", location_key="corridor", image_path=str(tmp_path / "bg.png"))])]
    cast_cards = {"1:S001": [{"card_key": "STOCK-d-class", "path": str(tmp_path / "card.png")}]}
    (tmp_path / "card.png").write_bytes(b"card")
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)
    RelightCache(tmp_path, svc).store("STOCK-d-class__standing__front", "corridor", 1, _make_png(6))
    client = _FakeComfyUIClient()
    _relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, client, workflow_path, tmp_path, "http://fake",
    )
    assert client.calls == 0
    assert stats == {"computed": 1, "failed": 0}


# ── the shipped workflow file (Story 10.1b) ──────────────────────────────────
# Nothing guarded data/workflows/comfyui_iclight_relight_api.json before 10.1b:
# every test above builds its own two-node stub, so an edit that renumbered the
# injection points or undid a wiring fix would land silently.


@pytest.fixture()
def shipped_workflow() -> dict:
    import json

    from yt_flow.config import Settings

    path = Path(Settings().iclight_comfyui_workflow_path)
    assert path.exists(), f"shipped IC-Light workflow missing at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_shipped_workflow_matches_injection_contract(shipped_workflow):
    """The two nodes ``_inject_relight_inputs`` writes must exist and be LoadImage."""
    for node_id in (CARD_IMAGE_NODE, BACKGROUND_IMAGE_NODE):
        assert shipped_workflow[node_id]["class_type"] == "LoadImage"
        assert "image" in shipped_workflow[node_id]["inputs"]


def test_shipped_workflow_is_marked_verified(shipped_workflow):
    """The shipped graph is live-verified, and the marker must stay `true`.

    The previous version of this test branched on the file's current value and
    asserted consistency either way, so it passed whether the marker was `true`
    or `false` — zero protection for the single bit Story 10.1b flipped after the
    live probe. Tier 3 silently produces nothing if this regresses, so pin it.
    """
    assert shipped_workflow.get("ytflow_verified_iclight") is True


def test_unverified_workflow_is_rejected(tmp_path, shipped_workflow):
    """...and the gate still refuses a graph that has not been verified."""
    unverified = dict(shipped_workflow)
    unverified["ytflow_verified_iclight"] = False
    path = tmp_path / "unverified.json"
    path.write_text(json.dumps(unverified), encoding="utf-8")
    with pytest.raises(ValueError, match="ytflow_verified_iclight"):
        _load_iclight_workflow(str(path))


def test_shipped_workflow_foreground_latent_is_grey_matted(shipped_workflow):
    """LoadImage drops alpha, so the card's transparent region is pure black.

    Encoding that straight into ICLightConditioning.foreground tells fbc the
    subject sits in a void — the near-black output of the 2026-08-02 probe.
    The foreground VAEEncode must read the grey composite, not node "1".
    """
    fg_encode = shipped_workflow[shipped_workflow["14"]["inputs"]["foreground"][0]]
    assert fg_encode["class_type"] == "VAEEncode"
    matte = shipped_workflow[fg_encode["inputs"]["pixels"][0]]
    assert matte["class_type"] == "ImageCompositeMasked"
    assert matte["inputs"]["destination"] == [CARD_IMAGE_NODE, 0]
    # LoadImage's MASK is already 1-alpha and ImageCompositeMasked pastes source
    # where mask == 1 — an InvertMask here inverts the silhouette (correlation -1.0).
    assert matte["inputs"]["mask"] == [CARD_IMAGE_NODE, 1]
    grey = shipped_workflow[matte["inputs"]["source"][0]]
    assert grey["class_type"] == "EmptyImage"
    assert grey["inputs"]["color"] == 0x7F7F7F


def test_shipped_workflow_init_latent_is_a_light_shape(shipped_workflow):
    """ICLightConditioning's third output is torch.zeros_like — never the init latent."""
    ksampler = shipped_workflow["3"]
    assert ksampler["inputs"]["latent_image"] != ["14", 2]
    assert ksampler["inputs"]["denoise"] == 1.0
    init_encode = shipped_workflow[ksampler["inputs"]["latent_image"][0]]
    assert init_encode["class_type"] == "VAEEncode"
    assert shipped_workflow[init_encode["inputs"]["pixels"][0]]["class_type"] == "LightSource"


def test_shipped_workflow_alpha_is_reattached_from_loadimage_mask(shipped_workflow):
    """The sprite contract: a relit card keeps the source silhouette."""
    join = shipped_workflow["17"]
    assert join["class_type"] == "JoinImageWithAlpha"
    # JoinImageWithAlpha applies alpha = 1.0 - mask, cancelling LoadImage's inversion.
    assert join["inputs"]["alpha"] == [CARD_IMAGE_NODE, 1]


# ── pose-blind relight key (Story 10.1b regression) ──────────────────────────


def test_card_variant_separates_poses_and_folds_unsafe_pose():
    """Two poses of one card_key are different sprites, so different keys.

    Story 8.7 keyed the relight on card_key alone. On run 8a9a288b that handed
    STOCK-d-class's `hint:a40ec9c170` relit sprite to all 12 of its `standing`
    shots — silhouette IoU 0.63, i.e. a visible pose swap. `:` is not a safe
    path component and must fold to `_` rather than raise.
    """
    standing = card_variant({"card_key": "STOCK-d-class", "pose": "standing", "angle": "front"})
    hinted = card_variant({"card_key": "STOCK-d-class", "pose": "hint:a40ec9c170", "angle": "front"})
    assert standing == "STOCK-d-class__standing__front"
    assert hinted == "STOCK-d-class__hint_a40ec9c170__front"
    assert standing != hinted
    # angle separates too, and the pose/angle defaults match resolve_cast_cards'
    assert card_variant({"card_key": "SCP-049"}) == "SCP-049__standing__front"
    assert card_variant({"card_key": "SCP-049", "angle": "side"}) == "SCP-049__standing__side"


@pytest.mark.asyncio
async def test_precompute_relights_keys_two_poses_separately(tmp_path, workflow_path):
    """Two poses of one card in one location produce two pairs, not one."""
    (tmp_path / "bg.png").write_bytes(b"bg")
    (tmp_path / "card.png").write_bytes(b"card")  # what _seed_stock_assets verifies against
    (tmp_path / "standing.png").write_bytes(b"standing")
    (tmp_path / "hinted.png").write_bytes(b"hinted")
    scenes = [_scene(1, [_shot("S001", location_key="corridor", image_path=str(tmp_path / "bg.png"))])]
    cast_cards = {
        "1:S001": [
            {"card_key": "STOCK-d-class", "pose": "standing", "angle": "front",
             "path": str(tmp_path / "standing.png")},
            {"card_key": "STOCK-d-class", "pose": "hint:a40ec9c170", "angle": "front",
             "path": str(tmp_path / "hinted.png")},
        ],
    }
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)
    svc.add_approved_asset(
        "STOCK-d-class/hint:a40ec9c170_front", "hinted.png",
        source={"type": "comfyui_generation"}, card_key="STOCK-d-class",
        pose="hint:a40ec9c170", angle="front",
    )
    client = _FakeComfyUIClient()
    relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, client, workflow_path, tmp_path, "http://fake",
    )
    assert ("STOCK-d-class__standing__front", "corridor") in relit_map
    assert ("STOCK-d-class__hint_a40ec9c170__front", "corridor") in relit_map
    assert len(relit_map) == 2
    assert stats == {"computed": 2, "failed": 0}
    # and the two relights were computed from different source sprites — uploads are
    # digest-named (see test_upload_name_disambiguates_shared_basenames), so compare
    # against the names the two distinct paths resolve to.
    assert {_upload_name(tmp_path / "standing.png"), _upload_name(tmp_path / "hinted.png")} <= set(client.uploaded)


# ── ComfyUI input-namespace collisions (Story 10.1b review, HIGH) ─────────────


def test_upload_name_disambiguates_shared_basenames():
    """`front_candidate_1.png` is the basename of eight different characters' cards.

    ComfyUI keys its input dir on the basename and uploads with overwrite=true,
    and LoadImage reads at node-execution time, not submit time — so two
    concurrent relights of same-named cards would make the later upload win for
    the earlier, still-queued job. That relights one character from another's
    sprite and caches it, auto-approved, under the first one's key.
    """
    a = Path("/assets/characters/SCP-049/epoch_1/front_candidate_1.png")
    b = Path("/assets/characters/SCP-049-2/epoch_1/front_candidate_1.png")
    assert a.name == b.name  # the hazard
    assert _upload_name(a) != _upload_name(b)  # the fix
    assert _upload_name(a) == _upload_name(a)  # stable across calls
    assert _upload_name(a).endswith(".png")
    # the uploaded name must itself be a safe, path-free basename
    assert "/" not in _upload_name(a) and not _upload_name(a).startswith(".")


def test_inject_relight_sizes_generated_canvases_to_the_card():
    """The graph ships 832x1216, but eight approved cards are 1664x928.

    LoadImage loads a card natively; the grey matte and the light-source gradient
    are generated. If those stay hardcoded, ICLightConditioning center-crops the
    subject to the graph's aspect while JoinImageWithAlpha re-attaches the full
    original mask — a garbage sprite that still passes has_alpha and gets cached.
    """
    template = {
        "ytflow_verified_iclight": True,
        "_ytflow_note": "not a node",
        "1": {"class_type": "LoadImage", "inputs": {"image": "x.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "y.png"}},
        "20": {"class_type": "EmptyImage", "inputs": {"width": 832, "height": 1216, "color": 8355711}},
        "22": {"class_type": "LightSource", "inputs": {"width": 832, "height": 1216, "multiplier": 1.0}},
    }
    out = _inject_relight_inputs(template, "card.png", "bg.png", (1664, 928))
    assert (out["20"]["inputs"]["width"], out["20"]["inputs"]["height"]) == (1664, 928)
    assert (out["22"]["inputs"]["width"], out["22"]["inputs"]["height"]) == (1664, 928)
    assert out["20"]["inputs"]["color"] == 8355711  # untouched
    # non-node keys must not reach ComfyUI's validate_prompt
    assert "ytflow_verified_iclight" not in out and "_ytflow_note" not in out
    # and the template itself is never mutated
    assert template["20"]["inputs"]["width"] == 832


def test_inject_relight_without_size_leaves_canvases_alone():
    template = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "x.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "y.png"}},
        "20": {"class_type": "EmptyImage", "inputs": {"width": 832, "height": 1216}},
    }
    out = _inject_relight_inputs(template, "card.png", "bg.png", None)
    assert (out["20"]["inputs"]["width"], out["20"]["inputs"]["height"]) == (832, 1216)


@pytest.mark.asyncio
async def test_a_malformed_shot_does_not_disable_tier3_for_the_run(tmp_path, workflow_path):
    """The isolation this function's docstring promises. Story 13.1 briefly moved the
    `shot.get(...)` identifier binding ABOVE the try, which let one non-dict shot raise
    an AttributeError out of `precompute_relights` and cost the whole run its relights.
    """
    (tmp_path / "bg.png").write_bytes(b"bg")
    (tmp_path / "card.png").write_bytes(b"card")
    good = _shot("S002", location_key="corridor", image_path=str(tmp_path / "bg.png"))
    scenes = [_scene(1, ["not a shot at all", good])]
    cast_cards = {"1:S002": [{"card_key": "STOCK-d-class", "path": str(tmp_path / "card.png")}]}
    svc = _FakeAssetService(tmp_path)
    _seed_stock_assets(svc)

    relit_map, stats = await precompute_relights(
        scenes, cast_cards, svc, _FakeComfyUIClient(), workflow_path, tmp_path, "http://fake",
    )

    # The healthy pair still relit…
    assert ("STOCK-d-class__standing__front", "corridor") in relit_map
    assert stats["computed"] == 1
    # …and the malformed one is accounted for rather than silently swallowed.
    assert stats["skipped"] == 1
    assert stats["skipped_details"] == [
        {"reason": "shot_metadata_error", "scene_num": 1, "shot_id": None}]
