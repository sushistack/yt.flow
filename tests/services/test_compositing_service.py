"""Tests for Story 8.16 depth-aware placement (compositing_service).

Pixel-level, fully offline: ComfyUI is a fake client object, depth maps are
synthetic numpy arrays, and every write goes to tmp_path.
"""

import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from yt_flow.services import compositing_service as cs

WALL = 60.0
NEAREST = 255.0


def _wall_and_floor(h: int = 180, w: int = 320) -> np.ndarray:
    """A plate's depth map, DepthAnything convention (brighter = nearer): a flat
    back wall over the top half, a floor receding from the wall's depth at the
    horizon to the camera at the bottom edge."""
    arr = np.full((h, w), WALL)
    floor_rows = h - h // 2
    arr[h // 2:, :] = np.linspace(WALL, NEAREST, floor_rows)[:, None]
    return arr


def _gray_png(size=(64, 64), value=128) -> bytes:
    buf = io.BytesIO()
    Image.new("L", size, value).save(buf, format="PNG")
    return buf.getvalue()


def _rgba_card(path: Path, size=(50, 100)) -> Path:
    Image.new("RGBA", size, (255, 0, 0, 255)).save(path)
    return path


def _settings(tmp_path, *, mock=False, workflow=None) -> SimpleNamespace:
    return SimpleNamespace(
        comfyui_url="http://127.0.0.1:8188",
        comfyui_mock=mock,
        depth_comfyui_workflow_path=str(workflow or _workflow_file(tmp_path)),
    )


def _workflow_file(tmp_path) -> Path:
    path = tmp_path / "depth_workflow.json"
    path.write_text(json.dumps({
        "1": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
        "2": {"class_type": "DepthAnythingV2Preprocessor", "inputs": {"image": ["1", 0]}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "d"}},
    }), encoding="utf-8")
    return path


class _FakeClient:
    def __init__(self, png: bytes | None = None, fail: bool = False) -> None:
        self._png = png if png is not None else _gray_png()
        self._fail = fail
        self.uploads: list[str] = []
        self.submits: list[dict] = []

    async def upload_image(self, url: str, data: bytes, name: str) -> str:
        if self._fail:
            raise RuntimeError("comfyui unreachable")
        self.uploads.append(name)
        return name

    async def submit_and_fetch(self, url: str, workflow: dict) -> bytes:
        self.submits.append(workflow)
        return self._png


# ── ground_line ──────────────────────────────────────────────────────────────


def test_ground_line_monotonic_in_depth():
    """far sits measurably higher in frame than mid, which sits higher than near. [AC:1]"""
    dm = _wall_and_floor()
    far = cs.ground_line(dm, "center", "far")
    mid = cs.ground_line(dm, "center", "mid")
    near = cs.ground_line(dm, "center", "near")
    assert far < mid < near
    assert cs._GROUND_BAND[0] <= far and near <= cs._GROUND_BAND[1]


def test_ground_line_monotonic_for_every_position():
    dm = _wall_and_floor()
    for position in ("left", "center", "right"):
        values = [cs.ground_line(dm, position, d) for d in ("far", "mid", "near")]
        assert values == sorted(values) and values[0] < values[-1], position


def test_ground_line_no_depth_map_uses_per_depth_default():
    assert cs.ground_line(None, "center", "far") == cs._DEFAULT_GROUND["far"]
    assert cs.ground_line(None, "center", "near") == cs._DEFAULT_GROUND["near"]
    values = [cs.ground_line(None, "center", d) for d in ("far", "mid", "near")]
    assert values == sorted(values) and values[0] < values[-1]


def test_ground_line_defaults_are_the_measured_library_medians():
    """The fallback ground lines were originally chosen so `near` equalled the pre-8.16
    hardcoded shadow constant (0.85) — which meant every far/mid fallback shadow moved on
    two numbers nobody had measured. These are the medians over the 41 readable plates in
    the approved library; the assertion here is that they stay ordered and inside the
    band, so a future edit cannot quietly put a fallback floor above the horizon."""
    values = [cs._DEFAULT_GROUND[d] for d in ("far", "mid", "near")]
    assert values == sorted(values)
    assert cs._GROUND_BAND[0] <= values[0] and values[-1] <= cs._GROUND_BAND[1]
    assert values[-1] - values[0] >= cs._MIN_GROUND_SPREAD


def test_ground_line_flat_depth_map_falls_back():
    flat = np.full((120, 200), 90.0)
    assert cs.ground_line(flat, "center", "mid") == cs._DEFAULT_GROUND["mid"]


def test_ground_line_unknown_position_and_depth_default_to_centre_mid():
    dm = _wall_and_floor()
    assert cs.ground_line(dm, "nowhere", "mid") == cs.ground_line(dm, "center", "mid")
    assert cs.ground_line(dm, "center", "sideways") == cs.ground_line(dm, "center", "mid")


def test_ground_line_reads_the_column_band_under_the_card():
    """A floor that only recedes on the right gives the right anchor a lower
    ground line than the left one."""
    h, w = 200, 300
    dm = np.full((h, w), WALL)
    dm[h // 2:, w // 2:] = np.linspace(WALL, NEAREST, h - h // 2)[:, None]
    assert cs.ground_line(dm, "right", "near") != cs.ground_line(dm, "left", "near")


def test_ground_line_degenerate_shapes_fall_back():
    assert cs.ground_line(np.zeros((1, 10)), "center", "mid") == cs._DEFAULT_GROUND["mid"]
    assert cs.ground_line(np.zeros((4, 4, 3)), "center", "mid") == cs._DEFAULT_GROUND["mid"]


# ── occlusion_mask ───────────────────────────────────────────────────────────


def test_occlusion_mask_masks_the_nearer_object(tmp_path):
    """A plate object nearer than the card blacks out exactly its footprint. [AC:3]"""
    dm = _wall_and_floor()
    ground = cs.ground_line(dm, "center", "mid")
    box = cs.card_box(dm.shape, "center", ground, "mid", 0.5)
    # a foreground pillar across the bottom third of the card's box
    x0, y0, x1, y1 = box
    pillar_top = y0 + (y1 - y0) * 2 // 3
    dm[pillar_top:y1, x0:x1] = NEAREST

    out = cs.occlusion_mask(dm, box, "mid", tmp_path / "occ.png", card_size=(60, 120))
    assert out is not None and out.exists()
    mask = np.asarray(Image.open(out).convert("L"))
    assert mask.shape == (120, 60)
    assert mask[:20, :].min() > 200      # card head: unmasked
    assert mask[-10:, :].max() < 60      # feet region: masked by the pillar


def test_occlusion_mask_none_without_an_occluder(tmp_path):
    dm = _wall_and_floor()
    ground = cs.ground_line(dm, "center", "far")
    box = cs.card_box(dm.shape, "center", ground, "far", 0.5)
    # a far card in front of the wall, nothing nearer inside its own box
    dm[: dm.shape[0] // 2, :] = WALL
    assert cs.occlusion_mask(dm, box, "far", tmp_path / "none.png") is None


def test_occlusion_mask_none_for_flat_or_missing_map(tmp_path):
    assert cs.occlusion_mask(None, (0, 0, 10, 10), "mid", tmp_path / "a.png") is None
    flat = np.full((80, 80), 100.0)
    assert cs.occlusion_mask(flat, (0, 0, 40, 40), "mid", tmp_path / "b.png") is None


def test_occlusion_mask_none_for_degenerate_box(tmp_path):
    dm = _wall_and_floor()
    assert cs.occlusion_mask(dm, (10, 10, 11, 11), "mid", tmp_path / "c.png") is None
    assert cs.occlusion_mask(dm, (-50, -50, -10, -10), "mid", tmp_path / "d.png") is None


def test_occlusion_mask_fully_occluded_box_is_rejected(tmp_path):
    """Everything-in-front means the plane estimate is wrong, not that the card
    should vanish."""
    dm = _wall_and_floor()
    dm[:, :] = WALL
    dm[100:, :] = NEAREST
    box = (0, 100, 200, 180)
    assert cs.occlusion_mask(dm, box, "far", tmp_path / "e.png") is None


def test_frame_fraction_undoes_the_ken_burns_centre_crop():
    """A 1344x768 generated plate (1.75) is scaled to the safe width and centre-cropped
    to 16:9 before zoompan, so a floor measured on the plate is a few pixels higher in
    the frame. A 16:9 plate loses nothing and must pass through untouched."""
    assert cs.frame_fraction(1920 / 1080, 0.85) == 0.85
    assert cs.frame_fraction(1920 / 1080, 0.0) == 0.0

    corrected = cs.frame_fraction(1344 / 768, 0.85)
    assert corrected > 0.85
    # Derived independently: scaled height 1728/1.75 = 987.4 rows, crop keeps the
    # middle 972, so row 0.85*987.4 lands at (839.3 - 7.7)/972 of the crop.
    assert abs(corrected - (0.85 * 987.43 - 7.71) / 972) < 0.001

    # A plate WIDER than the frame cannot be cropped taller than it is (ffmpeg clamps),
    # so it must not be "corrected" the other way.
    assert cs.frame_fraction(2.35, 0.85) == 0.85
    assert cs.frame_fraction(0.0, 0.85) == 0.85  # degenerate: no correction, no crash


async def test_resolve_placements_ground_is_in_frame_space_but_mask_is_in_plate_space(tmp_path):
    """The two live in different coordinate systems; mixing them shifted the mask box."""
    plate = tmp_path / "narrow.png"
    Image.new("RGB", (1344, 768), (9, 9, 9)).save(plate)
    card = _rgba_card(tmp_path / "card.png")
    depth = np.full((768, 1344), 40, dtype=np.uint8)
    depth[500:, :] = np.linspace(40, 250, 268, dtype=np.uint8)[:, None]
    buf = io.BytesIO()
    Image.fromarray(depth, "L").save(buf, format="PNG")
    client = _FakeClient(buf.getvalue())
    settings = _settings(tmp_path)

    scenes = [{"scene_num": 1, "shots": [{"shot_id": "S001", "image_path": str(plate)}]}]
    cast = {"1:S001": [{"card_key": "A", "path": str(card), "position": "center", "depth": "mid"}]}
    out = await cs.resolve_placements(scenes, cast, settings, comfyui_client=client)

    dm = cs.load_depth_map(cs.depth_map_cache_path(plate, settings))
    plate_ground = cs.ground_line(dm, "center", "mid")
    assert out["1:S001"][0]["ground_y"] == round(cs.frame_fraction(1344 / 768, plate_ground), 4)
    assert out["1:S001"][0]["ground_y"] != round(plate_ground, 4)


def test_card_box_bottom_edge_sits_on_the_ground_line():
    box = cs.card_box((1080, 1920), "center", 0.8, "near", 0.5)
    assert box[3] == pytest.approx(0.8 * 1080, abs=1)
    assert box[1] < box[3] and box[0] < box[2]


# ── depth map computation + caching ──────────────────────────────────────────


async def test_depth_map_computed_once_and_cached_beside_the_plate(tmp_path):
    plate = tmp_path / "corridor" / "a.png"
    plate.parent.mkdir()
    Image.new("RGB", (64, 32), (10, 10, 10)).save(plate)
    client = _FakeClient()

    first = await cs.depth_map_file(plate, _settings(tmp_path), comfyui_client=client)
    assert first == plate.parent / "a.depth.png"
    assert first.exists()
    assert len(client.submits) == 1

    second = await cs.depth_map_file(plate, _settings(tmp_path), comfyui_client=client)
    assert second == first
    assert len(client.submits) == 1  # cache hit: no ComfyUI call


async def test_depth_map_injects_the_uploaded_filename(tmp_path):
    plate = tmp_path / "b.png"
    Image.new("RGB", (8, 8)).save(plate)
    client = _FakeClient()
    await cs.depth_map_file(plate, _settings(tmp_path), comfyui_client=client)
    assert client.submits[0][cs.DEPTH_IMAGE_NODE]["inputs"]["image"] == "b.png"


async def test_depth_map_failure_returns_none_and_leaves_no_cache(tmp_path):
    plate = tmp_path / "c.png"
    Image.new("RGB", (8, 8)).save(plate)
    assert await cs.depth_map_file(
        plate, _settings(tmp_path), comfyui_client=_FakeClient(fail=True),
    ) is None
    assert not (tmp_path / "c.depth.png").exists()
    assert list(tmp_path.glob("*.tmp")) == []


async def test_depth_map_rejects_a_workflow_without_the_interchange_node(tmp_path):
    plate = tmp_path / "d.png"
    Image.new("RGB", (8, 8)).save(plate)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {}}}), encoding="utf-8")
    client = _FakeClient()
    assert await cs.depth_map_file(
        plate, _settings(tmp_path, workflow=bad), comfyui_client=client,
    ) is None
    assert client.submits == []


async def test_depth_map_skipped_in_mock_mode(tmp_path):
    plate = tmp_path / "e.png"
    Image.new("RGB", (8, 8)).save(plate)
    client = _FakeClient()
    assert await cs.depth_map_file(
        plate, _settings(tmp_path, mock=True), comfyui_client=client,
    ) is None
    assert client.submits == []


def test_load_depth_map_reads_gray_values(tmp_path):
    path = tmp_path / "g.png"
    Image.fromarray(np.tile(np.linspace(0, 255, 16, dtype=np.uint8), (8, 1)), "L").save(path)
    arr = cs.load_depth_map(path)
    assert arr.shape == (8, 16)
    assert arr[0, 0] < arr[0, -1]


def test_load_depth_map_tolerates_missing_or_corrupt_files(tmp_path):
    assert cs.load_depth_map(None) is None
    corrupt = tmp_path / "x.png"
    corrupt.write_bytes(b"not a png")
    assert cs.load_depth_map(corrupt) is None


def test_shipped_depth_workflow_is_loadable_with_the_interchange_node():
    workflow = json.loads(
        Path("data/workflows/comfyui_depth_anything_v2_api.json").read_text(encoding="utf-8")
    )
    assert workflow[cs.DEPTH_IMAGE_NODE]["class_type"] == "LoadImage"
    assert any(n["class_type"] == "DepthAnythingV2Preprocessor" for n in workflow.values())


# ── resolve_placements (video_node's seam contract) ──────────────────────────


def _scene(scene_num, image, shot_id="S001"):
    return {"scene_num": scene_num, "shots": [{"shot_id": shot_id, "image_path": str(image)}]}


async def _placements(tmp_path, cards, *, depth_png=None, scenes=None, plate_name="plate.png"):
    plate = tmp_path / plate_name
    Image.new("RGB", (320, 180), (5, 5, 5)).save(plate)
    if depth_png is not None:
        (tmp_path / f"{plate.stem}.depth.png").write_bytes(depth_png)
    return await cs.resolve_placements(
        scenes or [_scene(1, plate)], {"1:S001": cards}, _settings(tmp_path, mock=True),
    )


def _depth_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.fromarray(_wall_and_floor().astype(np.uint8), "L").save(buf, format="PNG")
    return buf.getvalue()


async def test_resolve_placements_grounds_every_card_in_order(tmp_path):
    card = _rgba_card(tmp_path / "card.png")
    cards = [
        {"card_key": "A", "path": str(card), "position": "left", "depth": "far"},
        {"card_key": "B", "path": str(card), "position": "center", "depth": "near"},
    ]
    out = await _placements(tmp_path, cards, depth_png=_depth_png_bytes())
    assert list(out) == ["1:S001"]
    far, near = out["1:S001"]
    assert far["ground_y"] < near["ground_y"]


async def test_resolve_placements_falls_back_without_a_depth_map(tmp_path):
    card = _rgba_card(tmp_path / "card.png")
    out = await _placements(
        tmp_path, [{"card_key": "A", "path": str(card), "position": "center", "depth": "mid"}],
    )
    assert out["1:S001"] == [{"ground_y": cs._DEFAULT_GROUND["mid"]}]


async def test_resolve_placements_emits_an_occlusion_mask_when_something_is_in_front(tmp_path):
    dm = _wall_and_floor()
    # A pillar narrower than the card's column band: it crosses the card, but the band's
    # median still reads the floor behind it, so a ground line IS resolvable. (Widen it to
    # swallow the whole band and the band has no floor at all — see
    # test_a_band_swallowed_by_a_near_object_has_no_readable_floor.)
    dm[60:, 140:160] = NEAREST
    buf = io.BytesIO()
    Image.fromarray(dm.astype(np.uint8), "L").save(buf, format="PNG")
    card = _rgba_card(tmp_path / "card.png")
    out = await _placements(
        tmp_path, [{"card_key": "STOCK-d-class", "path": str(card), "position": "center", "depth": "far"}],
        depth_png=buf.getvalue(),
    )
    mask = out["1:S001"][0].get("occlusion_mask")
    assert mask is not None and Path(mask).exists()
    assert Image.open(mask).size == (50, 100)  # authored at the sprite's own size


def test_a_band_swallowed_by_a_near_object_has_no_readable_floor():
    """A near object filling the card's whole column band leaves no floor to read, and
    the honest answer is "no reading" — not a clamped value that looks like a floor.
    Measured on the real library: 7 of 41 plates resolved all three depths onto one
    clamped number before this guard, which is the depth-independent anchor this story
    exists to remove."""
    dm = _wall_and_floor()
    dm[60:, 120:200] = NEAREST  # covers centre band (w//12 either side of 160)
    assert cs.ground_plane(dm, "center", "far") is None
    # ...and the public helper then hands back the measured fallback.
    assert cs.ground_line(dm, "center", "far") == cs._DEFAULT_GROUND["far"]
    # A card at another position still reads its own floor — the guard is per-band.
    assert cs.ground_plane(dm, "left", "far") is not None


async def test_resolve_placements_skips_shots_without_cards_or_background(tmp_path):
    plate = tmp_path / "p.png"
    Image.new("RGB", (32, 32)).save(plate)
    scenes = [
        {"scene_num": 1, "shots": [{"shot_id": "S001", "image_path": str(plate)}]},
        {"scene_num": 2, "shots": [{"shot_id": "S002", "image_path": None}]},
    ]
    out = await cs.resolve_placements(
        scenes, {"2:S002": [{"card_key": "A", "path": str(plate)}]},
        _settings(tmp_path, mock=True),
    )
    assert out == {}


async def test_resolve_placements_computes_one_depth_map_per_background(tmp_path):
    plate = tmp_path / "shared.png"
    Image.new("RGB", (64, 64), (9, 9, 9)).save(plate)
    card = _rgba_card(tmp_path / "card.png")
    scenes = [
        {"scene_num": 1, "shots": [
            {"shot_id": "S001", "image_path": str(plate)},
            {"shot_id": "S002", "image_path": str(plate)},
        ]},
    ]
    cast = {
        "1:S001": [{"card_key": "A", "path": str(card), "position": "left", "depth": "mid"}],
        "1:S002": [{"card_key": "A", "path": str(card), "position": "right", "depth": "mid"}],
    }
    client = _FakeClient(_gray_png(size=(64, 64)))
    out = await cs.resolve_placements(scenes, cast, _settings(tmp_path), comfyui_client=client)
    assert set(out) == {"1:S001", "1:S002"}
    assert len(client.submits) == 1  # two shots, one plate, one estimation


async def test_per_shot_copies_of_one_plate_cost_one_estimation(tmp_path):
    """image_node copies an approved stock plate into every shot that uses it, so
    the shots hold N distinct paths with identical bytes. A path-keyed cache
    estimated each one (80-shot run = 80 estimations); the content key does not."""
    source = tmp_path / "plate.png"
    Image.new("RGB", (64, 64), (9, 9, 9)).save(source)
    card = _rgba_card(tmp_path / "card.png")
    shots, cast = [], {}
    for i in range(5):
        copy_path = tmp_path / f"scene_{i}_shot.png"
        copy_path.write_bytes(source.read_bytes())      # exactly what shutil.copyfile does
        shots.append({"shot_id": f"S00{i}", "image_path": str(copy_path)})
        cast[f"1:S00{i}"] = [
            {"card_key": "A", "path": str(card), "position": "center", "depth": "mid"},
        ]
    settings = _settings(tmp_path)
    settings.workspace_path = str(tmp_path / "ws")
    client = _FakeClient(_gray_png(size=(64, 64)))

    out = await cs.resolve_placements(
        [{"scene_num": 1, "shots": shots}], cast, settings, comfyui_client=client,
    )
    assert len(out) == 5
    assert len(client.submits) == 1
    # ...and the next run over the same plate hits the same cache entry.
    assert await cs.depth_map_file(source, settings, comfyui_client=client) is not None
    assert len(client.submits) == 1


def test_ground_line_survives_a_wide_near_object_high_in_the_band():
    """The running max used to accumulate downward from the top, so anything bright high
    in the column band — a ceiling pipe, a foreground railing, a desk crossing frame —
    saturated every row beneath it. Measured, a near-depth object wider than half the
    band collapsed far/mid/near to one identical clamped value: the depth-independent
    anchor this story exists to remove."""
    import numpy as np

    from yt_flow.services import compositing_service as cs

    h, w = 400, 600
    plate = np.zeros((h, w))
    plate[:200, :] = 40                                    # wall
    plate[200:, :] = np.linspace(60, 240, 200)[:, None]    # floor receding upward
    clean = [cs.ground_line(plate, "center", d) for d in ("far", "mid", "near")]
    assert clean[0] < clean[1] < clean[2]

    blocked = plate.copy()
    blocked[10:50, :] = 250  # a near object spanning the whole band, high in frame
    got = [cs.ground_line(blocked, "center", d) for d in ("far", "mid", "near")]
    assert got[0] < got[1] < got[2], f"collapsed to {got}"
