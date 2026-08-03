"""Tests for the Story 11.5 AC1 depth-only backfill of the approved plates.

The whole point of this script is what it must NOT touch: the 42 approved RGB
plates, their DB rows, their status, their manifest provenance. Those are the
assertions here — a passing "it wrote some depth maps" test would miss the
failure mode that matters (8.17's review caught destructive replacement before
success, and that lesson is what this script is built around).
"""

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlmodel import Session, SQLModel, create_engine, select

from yt_flow.db.models import LocationPlate
from yt_flow.services import compositing_service as cs

SCRIPT = Path("scripts/backfill_location_depth_maps.py")


@pytest.fixture
def backfill():
    spec = importlib.util.spec_from_file_location("_backfill_mod", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_backfill_mod"] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("_backfill_mod", None)


@pytest.fixture
def library(tmp_path):
    """A miniature approved plate library: DB rows plus real files on disk."""
    assets = tmp_path / "assets"
    plates = []
    for i, (key, variant, status) in enumerate(
        [("corridor", "a", "approved"), ("corridor", "b", "approved"), ("office", "a", "draft")]
    ):
        rel = f"locations/{key}/{variant}.png"
        path = assets / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 9), (i + 1, i + 2, i + 3)).save(path)
        plates.append(LocationPlate(
            id=f"p{i}", location_key=key, variant=variant, image_path=rel, status=status,
        ))
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for p in plates:
            session.add(p)
        session.commit()
    return SimpleNamespace(assets=assets, engine=engine, db_path=str(tmp_path / "db.sqlite"))


def _settings(tmp_path, library, **kw):
    base = dict(
        assets_path=str(library.assets),
        db_path=library.db_path,
        workspace_path=str(tmp_path / "ws"),
        comfyui_url="http://127.0.0.1:8188",
        comfyui_mock=False,
        depth_model_ckpt="depth_anything_v2_vits.pth",
        depth_model_resolution=1024,
        depth_allow_noncommercial_model=False,
        depth_comfyui_workflow_path=str(tmp_path / "wf.json"),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _fake_depth(monkeypatch, calls, *, fail=False):
    async def depth_map_file(background, settings, **kw):
        calls.append(str(background))
        if fail:
            return None
        cache = cs.depth_map_cache_path(background, settings)
        cache.parent.mkdir(parents=True, exist_ok=True)
        png = _gray_png()
        cache.write_bytes(png)
        cs._write_depth_sidecar(
            cache,
            source_sha=hashlib.sha256(Path(background).read_bytes()).hexdigest(),
            depth_bytes=png, contract=cs.depth_contract(settings),
            source_size=None, depth_size=None,
        )
        return cache

    monkeypatch.setattr(cs, "depth_map_file", depth_map_file)


def _gray_png() -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("L", (16, 9), 120).save(buf, format="PNG")
    return buf.getvalue()


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*.png"))}


async def test_backfills_only_the_approved_plates(backfill, library, tmp_path, monkeypatch):
    calls: list[str] = []
    _fake_depth(monkeypatch, calls)
    rc = await backfill.backfill(_settings(tmp_path, library), status="approved", dry_run=False)
    assert rc == 0
    assert len(calls) == 2
    assert all("office" not in c for c in calls)


async def test_all_flag_includes_drafts(backfill, library, tmp_path, monkeypatch):
    calls: list[str] = []
    _fake_depth(monkeypatch, calls)
    await backfill.backfill(_settings(tmp_path, library), status=None, dry_run=False)
    assert len(calls) == 3


async def test_approved_plate_bytes_are_never_touched(backfill, library, tmp_path, monkeypatch):
    """AC1's core guarantee: backfill never regenerates or modifies approved RGB
    bytes. Snapshot every file in the library and compare afterwards."""
    before = _snapshot(library.assets)
    _fake_depth(monkeypatch, [])
    await backfill.backfill(_settings(tmp_path, library), status="approved", dry_run=False)
    assert _snapshot(library.assets) == before


async def test_db_rows_and_status_are_never_touched(backfill, library, tmp_path, monkeypatch):
    _fake_depth(monkeypatch, [])
    await backfill.backfill(_settings(tmp_path, library), status="approved", dry_run=False)
    with Session(library.engine) as session:
        rows = {
            p.id: (p.status, p.image_path)
            for p in session.exec(select(LocationPlate)).all()
        }
    assert rows == {
        "p0": ("approved", "locations/corridor/a.png"),
        "p1": ("approved", "locations/corridor/b.png"),
        "p2": ("draft", "locations/office/a.png"),
    }


async def test_rerun_is_a_pure_cache_hit_with_zero_inference(backfill, library, tmp_path, monkeypatch):
    calls: list[str] = []
    _fake_depth(monkeypatch, calls)
    settings = _settings(tmp_path, library)
    await backfill.backfill(settings, status="approved", dry_run=False)
    calls.clear()
    rc = await backfill.backfill(settings, status="approved", dry_run=False)
    assert rc == 0 and calls == []


async def test_dry_run_estimates_nothing(backfill, library, tmp_path, monkeypatch):
    calls: list[str] = []
    _fake_depth(monkeypatch, calls)
    rc = await backfill.backfill(_settings(tmp_path, library), status="approved", dry_run=True)
    assert rc == 0 and calls == []


async def test_one_plates_failure_does_not_stop_the_others(backfill, library, tmp_path, monkeypatch):
    """8.17's per-item isolation precedent: a failed plate is reported, not fatal."""
    calls: list[str] = []
    first = {"seen": False}

    async def flaky(background, settings, **kw):
        calls.append(str(background))
        if not first["seen"]:
            first["seen"] = True
            raise RuntimeError("comfyui died")
        cache = cs.depth_map_cache_path(background, settings)
        cache.parent.mkdir(parents=True, exist_ok=True)
        png = _gray_png()
        cache.write_bytes(png)
        cs._write_depth_sidecar(
            cache, source_sha=hashlib.sha256(Path(background).read_bytes()).hexdigest(),
            depth_bytes=png, contract=cs.depth_contract(settings),
            source_size=None, depth_size=None,
        )
        return cache

    monkeypatch.setattr(cs, "depth_map_file", flaky)
    rc = await backfill.backfill(_settings(tmp_path, library), status="approved", dry_run=False)
    assert len(calls) == 2   # the second plate was still attempted
    assert rc == 1           # ...and the loss is reported, not swallowed


async def test_a_missing_plate_file_is_reported_not_crashed(backfill, library, tmp_path, monkeypatch):
    (library.assets / "locations/corridor/a.png").unlink()
    calls: list[str] = []
    _fake_depth(monkeypatch, calls)
    rc = await backfill.backfill(_settings(tmp_path, library), status="approved", dry_run=False)
    assert rc == 1 and len(calls) == 1


async def test_a_noncommercial_checkpoint_refuses_before_touching_anything(
    backfill, library, tmp_path, monkeypatch,
):
    """AC3 has to bite here too — a backfill is the easiest place to bulk-produce
    42 non-commercially-licensed derivatives."""
    calls: list[str] = []
    _fake_depth(monkeypatch, calls)
    before = _snapshot(library.assets)
    settings = _settings(tmp_path, library, depth_model_ckpt="depth_anything_v2_vitl.pth")
    with pytest.raises(cs.NonCommercialDepthModel):
        await backfill.backfill(settings, status="approved", dry_run=False)
    assert calls == []
    assert _snapshot(library.assets) == before
