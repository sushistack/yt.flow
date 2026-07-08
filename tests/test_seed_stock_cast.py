import asyncio
import importlib.util

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.services.character_service import CharacterService
from tests.stubs.fakes import TINY_PNG


def _load_script():
    spec = importlib.util.spec_from_file_location("seed_stock_cast", "scripts/seed_stock_cast.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


async def test_seed_key_skips_completed_standing_library(tmp_path, monkeypatch):
    seed = _load_script()
    db.init("sqlite://")
    from sqlmodel import Session
    from yt_flow.db import _engine

    with Session(_engine) as session:
        service = CharacterService(session, settings=Settings(workspace_path=str(tmp_path)))
        character = service.create_character("STOCK-d-class", "D-class")
        paths = {}
        for angle in ("front", "back", "side", "three_quarter"):
            path = tmp_path / f"{angle}.png"
            path.write_bytes(TINY_PNG)
            paths[angle] = str(path)
        service.update_character(
            character.id,
            angle_front_path=paths["front"],
            angle_back_path=paths["back"],
            angle_side_path=paths["side"],
            angle_three_quarter_path=paths["three_quarter"],
        )

        async def fail_generate(*args, **kwargs):
            raise AssertionError("must skip completed standing cards")

        monkeypatch.setattr(service, "generate_cards_from_descriptor", fail_generate)
        paths = await seed.seed_key(service, "STOCK-d-class", "descriptor")

    assert paths == []


async def test_seed_key_regenerates_when_completed_paths_are_missing(tmp_path, monkeypatch):
    seed = _load_script()
    db.init("sqlite://")
    from sqlmodel import Session
    from yt_flow.db import _engine

    with Session(_engine) as session:
        service = CharacterService(session, settings=Settings(workspace_path=str(tmp_path)))
        character = service.create_character("STOCK-d-class", "D-class")
        service.update_character(
            character.id,
            angle_front_path=str(tmp_path / "missing-front.png"),
            angle_back_path=str(tmp_path / "missing-back.png"),
            angle_side_path=str(tmp_path / "missing-side.png"),
            angle_three_quarter_path=str(tmp_path / "missing-three.png"),
        )

        async def fake_generate(key, *, descriptor, pose="standing", anchor_path=None):
            return [f"/tmp/{angle}.png" for angle in ("front", "back", "side", "three_quarter")]

        monkeypatch.setattr(service, "generate_cards_from_descriptor", fake_generate)
        paths = await seed.seed_key(service, "STOCK-d-class", "descriptor")

    assert len(paths) == 4


async def test_seed_key_generates_derived_descriptor(tmp_path, monkeypatch):
    seed = _load_script()
    db.init("sqlite://")
    from sqlmodel import Session
    from yt_flow.db import _engine

    with Session(_engine) as session:
        service = CharacterService(session, settings=Settings(workspace_path=str(tmp_path)))

        async def fake_generate(key, *, descriptor, pose="standing", anchor_path=None):
            assert key == "SCP-049-2"
            assert descriptor == "reanimated human"
            assert pose == "standing"
            assert anchor_path is None
            return [f"/tmp/{angle}.png" for angle in ("front", "back", "side", "three_quarter")]

        monkeypatch.setattr(service, "generate_cards_from_descriptor", fake_generate)
        paths = await seed.seed_key(service, "SCP-049-2", "reanimated human")

    assert len(paths) == 4


async def test_seed_key_rejects_incomplete_generation(tmp_path, monkeypatch):
    seed = _load_script()
    db.init("sqlite://")
    from sqlmodel import Session
    from yt_flow.db import _engine

    with Session(_engine) as session:
        service = CharacterService(session, settings=Settings(workspace_path=str(tmp_path)))

        async def fake_generate(key, *, descriptor, pose="standing", anchor_path=None):
            return ["/tmp/front.png"]

        monkeypatch.setattr(service, "generate_cards_from_descriptor", fake_generate)
        try:
            await seed.seed_key(service, "SCP-049-2", "reanimated human")
        except RuntimeError as exc:
            assert "1/4 cards" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")


def test_parser_rejects_anchor_without_single_key():
    seed = _load_script()
    args = seed.build_parser().parse_args(["--anchor", "curated.png"])
    try:
        asyncio.run(seed.run(args))
    except SystemExit as exc:
        assert "--anchor requires --key" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_anchor_search_stock_key_uses_builtin_descriptor(monkeypatch):
    seed = _load_script()
    args = seed.build_parser().parse_args(["--key", "STOCK-d-class", "--anchor-search"])
    calls = []

    async def fake_anchor_search(service, key, descriptor, settings):
        calls.append((key, descriptor))
        return 0

    monkeypatch.setattr(seed, "_anchor_search", fake_anchor_search)

    assert asyncio.run(seed.run(args)) == 0
    assert calls == [("STOCK-d-class", seed.STOCK_DESCRIPTORS["STOCK-d-class"])]


async def test_anchor_search_skips_malformed_results(tmp_path, monkeypatch):
    seed = _load_script()
    service = object()
    settings = Settings(workspace_path=str(tmp_path))

    class FakeSearch:
        async def search(self, query, max_results):
            return [{"title": "missing url"}]

    monkeypatch.setattr(seed, "DuckDuckGoImageSearch", FakeSearch)

    assert await seed._anchor_search(service, "STOCK-d-class", "descriptor", settings) == 0


def test_parser_rejects_unknown_pose():
    seed = _load_script()
    try:
        seed.build_parser().parse_args(["--pose", "crouching"])
    except SystemExit:
        pass
    else:
        raise AssertionError("expected SystemExit")
