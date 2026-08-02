"""Tests for scripts/seed_location_plates.py (Story 8.5 gates + Story 8.17 batch fixes).

Fully offline: the ComfyUI seam is faked in every test, so nothing here spends GPU.
Settings is pointed at a tmp DB, tmp assets root and tmp anchor dir via env overrides —
never the repo's own assets/, yt_flow.db or data/anchors/, which hold the real
curated library.
"""

import asyncio
import importlib.util
import io
import json
import struct

import pytest
from sqlmodel import Session, select

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import LocationPlate
from yt_flow.services.comfyui_client import ComfyUIError


def _load_script():
    spec = importlib.util.spec_from_file_location("seed_location_plates", "scripts/seed_location_plates.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _png(width: int, height: int) -> bytes:
    """A real PNG of the given size — PIL, the same library the upscale uses."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (32, 34, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _fake_plate(width: int = 1920, height: int = 1080, size: int = 4096) -> bytes:
    """Just enough PNG for ``_valid_plate``: signature, IHDR dimensions, and bulk."""
    head = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)
    return head + b"\x00" * (size - len(head))


def _dimensions(path) -> tuple[int, int]:
    return struct.unpack(">II", path.read_bytes()[16:24])


def _env(tmp_path, monkeypatch, *, mock=False, anchors=True, lookdev=True):
    """Point Settings at tmp everything and seed the anchor gate as requested."""
    assets = tmp_path / "assets"
    anchor_dir = tmp_path / "anchors"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("YTFLOW_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(assets))
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "workspace"))
    monkeypatch.setenv("YTFLOW_LOCATION_ANCHOR_DIR", str(anchor_dir))
    monkeypatch.setenv("YTFLOW_COMFYUI_MOCK", "true" if mock else "false")
    if anchors:
        (anchor_dir / "anchor.png").write_bytes(_png(64, 64))
    if lookdev:
        (anchor_dir / "LOOKDEV_DECISION.md").write_text("chosen: candidate_2\n", encoding="utf-8")
    db.init(f"sqlite:///{tmp_path / 'test.db'}")
    return assets, anchor_dir


def _fake_comfy(monkeypatch, module, *, fail_on=(), image=None):
    """Replace the ComfyUI HTTP seam; returns the list of submitted workflows.

    ``fail_on`` holds 1-based submit call numbers that raise ComfyUIError — the shape
    a hipErrorIllegalAddress abort takes at this seam.
    """
    calls: list[dict] = []

    async def fake_submit(url, workflow):
        calls.append(workflow)
        if len(calls) in fail_on:
            raise ComfyUIError("hipErrorIllegalAddress (simulated)")
        return image if image is not None else _png(1344, 768)

    async def fake_upload(url, image_bytes, filename):
        return filename

    monkeypatch.setattr(module.comfyui_client, "submit_and_fetch", fake_submit)
    monkeypatch.setattr(module.comfyui_client, "upload_image", fake_upload)
    return calls


def _rows() -> list[LocationPlate]:
    with Session(db._engine) as session:
        return list(session.exec(select(LocationPlate)).all())


def _run(module, argv) -> int:
    return asyncio.run(module.run(module.build_parser().parse_args(argv)))


# ── Preflight gates (AC1: explain what is missing, spend no GPU) ──────────────

def test_missing_lookdev_decision_halts_before_any_submission(tmp_path, monkeypatch):
    seed = _load_script()
    _env(tmp_path, monkeypatch, lookdev=False)
    calls = _fake_comfy(monkeypatch, seed)

    with pytest.raises(SystemExit) as exc:
        _run(seed, [])

    assert "Lookdev decision not recorded" in str(exc.value)
    assert calls == []


def test_missing_anchor_image_halts_before_any_submission(tmp_path, monkeypatch):
    seed = _load_script()
    _env(tmp_path, monkeypatch, anchors=False)
    calls = _fake_comfy(monkeypatch, seed)

    with pytest.raises(SystemExit) as exc:
        _run(seed, [])

    assert "No anchor images found" in str(exc.value)
    assert calls == []


# ── _valid_plate ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "payload,expected",
    [
        (_fake_plate(), True),
        (_fake_plate(width=1344, height=768), False),          # the render bucket, not the contract
        (_fake_plate(size=512), False),                        # a truncated/blank render
        (b"not a png at all" + b"\x00" * 2048, False),         # wrong signature
    ],
)
def test_valid_plate_enforces_the_on_disk_contract(tmp_path, payload, expected):
    seed = _load_script()
    path = tmp_path / "plate.png"
    path.write_bytes(payload)

    assert seed._valid_plate(path, mock=False) is expected


def test_valid_plate_is_false_for_a_missing_file(tmp_path):
    seed = _load_script()

    assert seed._valid_plate(tmp_path / "absent.png", mock=False) is False


def test_valid_plate_in_mock_mode_only_checks_the_signature(tmp_path):
    """Mock mode copies a tiny fixture, never a rendered plate."""
    seed = _load_script()
    path = tmp_path / "plate.png"
    path.write_bytes(_fake_plate(width=1, height=1, size=64))

    assert seed._valid_plate(path, mock=True) is True


# ── Seed determinism + reroll ────────────────────────────────────────────────

def test_plate_seed_is_salt_sensitive_and_collision_free():
    """The shipped little-endian truncation made the seed a function of the first four
    bytes only: "containment-chamber" and "control-room" collided, and an appended salt
    was discarded entirely."""
    seed = _load_script()

    assert seed._plate_seed("corridor", "a") == seed._plate_seed("corridor", "a")
    assert seed._plate_seed("corridor", "a") != seed._plate_seed("corridor", "b")
    assert seed._plate_seed("containment-chamber", "a") != seed._plate_seed("control-room", "a")
    assert seed._plate_seed("corridor", "a") != seed._plate_seed("corridor", "a", "deadbeef")
    assert seed._plate_seed("corridor", "a", "deadbeef") == seed._plate_seed("corridor", "a", "deadbeef")
    assert 0 <= seed._plate_seed("corridor", "a", "deadbeef") < 2**31


def test_reroll_produces_a_different_image_and_records_a_reproducible_salt(tmp_path, monkeypatch):
    seed = _load_script()
    assets, _ = _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    argv = ["--key", "corridor", "--variant", "a"]

    assert _run(seed, argv) == 0
    assert _run(seed, [*argv, "--reroll"]) == 0
    assert _run(seed, [*argv, "--reroll"]) == 0

    seeds = [call[seed.SAMPLER_NODE]["inputs"]["seed"] for call in calls]
    assert len(set(seeds)) == 3, "a bare --reroll must draw a fresh salt every invocation"

    source = json.loads((assets / "manifest.json").read_text())["assets"]["corridor/a"]["source"]
    assert source["seed"] == seeds[-1]
    assert source["reroll_salt"]

    # The recorded salt is what makes a re-rolled keeper reproducible.
    assert _run(seed, [*argv, "--reroll", source["reroll_salt"]]) == 0
    assert calls[-1][seed.SAMPLER_NODE]["inputs"]["seed"] == seeds[-1]


# ── Render bucket + upscale ──────────────────────────────────────────────────

def test_upscale_to_contract_yields_exactly_1920x1080(tmp_path):
    seed = _load_script()

    out = seed._upscale_to_contract(_png(seed.PLATE_RENDER_WIDTH, seed.PLATE_RENDER_HEIGHT))

    assert struct.unpack(">II", out[16:24]) == (1920, 1080)


def test_plate_renders_at_the_native_bucket_and_is_saved_at_the_contract(tmp_path, monkeypatch):
    seed = _load_script()
    assets, _ = _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)

    assert _run(seed, ["--key", "corridor", "--variant", "a"]) == 0

    latent = calls[0][seed.LATENT_NODE]["inputs"]
    assert (latent["width"], latent["height"]) == (seed.PLATE_RENDER_WIDTH, seed.PLATE_RENDER_HEIGHT)
    assert _dimensions(assets / "locations" / "corridor" / "a.png") == (1920, 1080)


# ── Resume / skip / force ────────────────────────────────────────────────────

def test_an_existing_draft_with_a_file_is_not_regenerated(tmp_path, monkeypatch):
    """AC: after an abort, a re-run must continue rather than re-render the batch."""
    seed = _load_script()
    _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    argv = ["--key", "corridor", "--variant", "a"]

    assert _run(seed, argv) == 0
    assert _run(seed, argv) == 0

    assert len(calls) == 1
    assert len(_rows()) == 1


def test_a_draft_whose_file_vanished_is_regenerated(tmp_path, monkeypatch):
    seed = _load_script()
    assets, _ = _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    argv = ["--key", "corridor", "--variant", "a"]

    assert _run(seed, argv) == 0
    (assets / "locations" / "corridor" / "a.png").unlink()
    assert _run(seed, argv) == 0

    assert len(calls) == 2


def test_an_approved_plate_is_skipped_but_force_regenerates_it(tmp_path, monkeypatch):
    seed = _load_script()
    _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed)
    argv = ["--key", "corridor", "--variant", "a"]
    assert _run(seed, argv) == 0
    with Session(db._engine) as session:
        plate = session.exec(select(LocationPlate)).one()
        plate.status = "approved"
        session.add(plate)
        session.commit()

    assert _run(seed, argv) == 0
    assert len(calls) == 1, "an approved plate must not be re-rendered"

    assert _run(seed, [*argv, "--force"]) == 0
    assert len(calls) == 2
    with Session(db._engine) as session:
        assert session.exec(select(LocationPlate)).one().status == "draft"


# ── Crash recovery (Story 5.23's loop, reused) ───────────────────────────────

def test_a_mid_batch_abort_recovers_and_continues_with_the_next_plate(tmp_path, monkeypatch):
    seed = _load_script()
    _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed, fail_on={2})
    recoveries = []

    async def fake_recovery(url, *, poll_sec, timeout_sec, shots_done, total_shots):
        recoveries.append((shots_done, total_shots))

    monkeypatch.setattr(seed, "_wait_for_comfyui_recovery", fake_recovery)

    assert _run(seed, ["--key", "corridor"]) == 0

    assert len(calls) == 4, "3 plates + one retry of the aborted submit"
    assert recoveries == [(1, 3)]
    assert sorted(row.variant for row in _rows()) == ["a", "b", "c"]


def test_an_exhausted_recovery_window_aborts_and_names_the_remaining_plates(tmp_path, monkeypatch, capsys):
    seed = _load_script()
    _env(tmp_path, monkeypatch)
    calls = _fake_comfy(monkeypatch, seed, fail_on={2})

    async def never_recovers(url, **kwargs):
        raise ComfyUIError("ComfyUI unreachable")

    monkeypatch.setattr(seed, "_wait_for_comfyui_recovery", never_recovers)

    assert _run(seed, ["--key", "corridor"]) == 1

    out = capsys.readouterr().out
    assert "not generated: corridor b, corridor c" in out
    assert len(calls) == 2, "the batch must not keep submitting against a dead server"
    assert [row.variant for row in _rows()] == ["a"]


# ── Anchor candidates ────────────────────────────────────────────────────────

def test_anchor_candidates_render_unconditioned_and_touch_no_library_state(tmp_path, monkeypatch):
    seed = _load_script()
    assets, _ = _env(tmp_path, monkeypatch, anchors=False, lookdev=False)
    calls = _fake_comfy(monkeypatch, seed)

    assert _run(seed, ["--anchor-candidates", "3"]) == 0

    review_dir = tmp_path / "workspace" / "location-anchor-candidates"
    assert sorted(p.name for p in review_dir.glob("*.png")) == [
        "candidate_1.png", "candidate_2.png", "candidate_3.png",
    ]
    assert len(calls) == 3
    assert len({call[seed.SAMPLER_NODE]["inputs"]["seed"] for call in calls}) == 3
    for call in calls:
        # No anchor exists yet, so the candidate cannot be style-anchored to one.
        assert seed.ANCHOR_NODE not in call and seed.IPADAPTER_NODE not in call
        assert not any("IPAdapter" in node.get("class_type", "") for node in call.values())
        assert call[seed.SAMPLER_NODE]["inputs"]["model"] == [seed.MODEL_NODE, 0]
    # Candidates are review material, not library assets.
    assert not (assets / "manifest.json").exists()
    assert _rows() == []


def test_anchor_candidates_are_refused_in_mock_mode(tmp_path, monkeypatch):
    seed = _load_script()
    _env(tmp_path, monkeypatch, mock=True)
    calls = _fake_comfy(monkeypatch, seed)

    with pytest.raises(SystemExit) as exc:
        _run(seed, ["--anchor-candidates", "2"])

    assert "--anchor-candidates" in str(exc.value)
    assert calls == []


def test_prompts_cover_every_location_key():
    """LOCATION_PROMPTS is the batch's only prompt source; a missing key is a KeyError
    mid-batch, after GPU has already been spent on the earlier ones."""
    seed = _load_script()
    settings = Settings()

    assert set(seed.LOCATION_PROMPTS) == set(seed.LOCATION_KEYS)
    assert seed.ANCHOR_CANDIDATE_KEY in seed.LOCATION_PROMPTS
    assert settings.location_plate_workflow_path.endswith(".json")
