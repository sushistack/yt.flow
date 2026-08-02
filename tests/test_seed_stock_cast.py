import asyncio
import importlib.util
import re

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

        async def fake_generate(key, *, descriptor, pose="standing", anchor_path=None, **kwargs):
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

        async def fake_generate(
            key, *, descriptor, pose="standing", anchor_path=None, negative_suffix=None, enrich_ban=None, **kwargs
        ):
            assert key == "SCP-049-2"
            assert descriptor == "reanimated human"
            assert pose == "standing"
            assert anchor_path is None
            assert negative_suffix is None  # STOCK-only suppression, not derived keys
            assert enrich_ban is None  # derived keys are SCP entities; nothing to scrub
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

        async def fake_generate(key, *, descriptor, pose="standing", anchor_path=None, **kwargs):
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


async def test_seed_key_stage_bypasses_guard_and_threads_stage_and_negative(tmp_path, monkeypatch):
    """Story 8.15: --stage always regenerates (into a parallel epoch) and carries
    the STOCK negative suffix, even when the live standing library is complete."""
    seed = _load_script()
    db.init("sqlite://")
    from sqlmodel import Session
    from yt_flow.db import _engine

    with Session(_engine) as session:
        service = CharacterService(session, settings=Settings(workspace_path=str(tmp_path)))
        character = service.create_character("STOCK-d-class", "D-class")
        live = {}
        for angle in ("front", "back", "side", "three_quarter"):
            path = tmp_path / f"{angle}.png"
            path.write_bytes(TINY_PNG)
            live[f"angle_{angle}_path"] = str(path)
        service.update_character(character.id, **live)
        calls = []

        async def fake_generate(key, **kwargs):
            calls.append(kwargs)
            return [f"/tmp/{angle}.png" for angle in ("front", "back", "side", "three_quarter")]

        monkeypatch.setattr(service, "generate_cards_from_descriptor", fake_generate)
        paths = await seed.seed_key(
            service, "STOCK-d-class", seed.STOCK_DESCRIPTORS["STOCK-d-class"], stage=True
        )

    assert len(paths) == 4
    assert calls[0]["stage"] is True
    assert calls[0]["negative_suffix"] == seed.STOCK_NEGATIVE
    # Vision enrichment overwrites visual_descriptor with text from a prompt that says
    # "an SCP Foundation character" — the token these descriptors exist to avoid. The
    # read-back is kept (it holds the four angles to one face) with the token scrubbed.
    assert calls[0]["enrich_ban"] == seed.BANNED_STOCK_TOKEN


def test_stock_descriptors_pin_a_bare_human_face():
    """The descriptor is the only face constraint reaching ComfyUI, so it states the
    head/face affirmatively and names no prohibition — text encoders do not negate,
    so "no mask" in the positive prompt summons masks. Prohibitions belong in
    STOCK_NEGATIVE. "SCP Foundation" is banned outright: live probing showed that
    token alone collapses these extras into masked, hazmat-suited figures."""
    seed = _load_script()
    # "solo, 1boy" leads: AnimagineXL is Danbooru-tagged, and prose alone let the
    # model compose a four-up character sheet whose figures touched — one alpha
    # component, so the largest-component cut could not remove them either.
    # Colours are pinned concretely, not as "dark": the non-front angles are prompted
    # from this text and vague colour let the front's black hair return brown on one
    # angle and teal on another. The enrichment read-back cannot cover for it — its
    # prompt has no hair/eye/face dimension.
    required = (
        "solo, 1boy",
        "short straight black hair",
        "brown eyes",
        "ordinary human face",
    )
    forbidden = (
        "mask", "helmet", "skull", "glowing", "undead", "monster", "plague",
        "hazmat", "scp foundation", "doctor",
    )

    assert set(seed.STOCK_DESCRIPTORS) == {"STOCK-d-class", "STOCK-researcher", "STOCK-security"}
    for key, descriptor in seed.STOCK_DESCRIPTORS.items():
        text = descriptor.lower()
        for phrase in required:
            assert phrase in text, f"{key} descriptor is missing {phrase!r}"
        for term in forbidden:
            assert term not in text, f"{key} descriptor names {term!r}"
        assert not re.search(r"\bno\b", text), f"{key} descriptor negates; move it to STOCK_NEGATIVE"


def test_stock_negative_carries_the_prohibitions():
    """Every head-covering the descriptor no longer mentions has to be suppressed here
    instead — as concrete nouns only, and sparingly."""
    seed = _load_script()
    text = seed.STOCK_NEGATIVE.lower()
    for term in (
        "skull mask", "plague doctor mask", "gas mask", "respirator",
        "helmet", "visor", "hazmat suit", "glowing eyes", "undead", "monster",
        # Multi-subject suppression: the checkpoint composes character sheets, and
        # touching figures form one alpha component that no cutout rule can split.
        "character sheet", "multiple views", "2boys",
    ):
        assert term in text, f"STOCK_NEGATIVE is missing {term!r}"
    for term in ("faceless", "no face"):
        assert term not in text, f"STOCK_NEGATIVE names {term!r}, which blanks the head"
    # CLIP negative conditioning is a token bag, not a set of phrases: an earlier list
    # spread "face" over full-face mask / face shield / hood covering face / monster
    # face / horror creature face and suppressed the word itself — the staged fronts
    # came back as a blank white face and a black void with eye slits.
    assert text.count("face") <= 1, "STOCK_NEGATIVE repeats 'face'; it will erase faces"


def test_stage_rejects_targets_the_approve_script_cannot_promote():
    """approve_stock_cast.py only ever looks for ``{angle}_candidate_1.png`` under a
    stock key, so staging a non-standing pose (``{pose}_{angle}.png``) or a derived key
    would produce files that can be neither promoted nor rejected."""
    seed = _load_script()
    for argv in (
        ["--stage", "--pose", "sitting"],
        ["--stage", "--key", "SCP-049-2", "--descriptor", "reanimated human"],
    ):
        args = seed.build_parser().parse_args(argv)
        try:
            asyncio.run(seed.run(args))
        except SystemExit as exc:
            assert "--stage supports" in str(exc)
        else:
            raise AssertionError(f"expected SystemExit for {argv}")


def test_parser_rejects_unknown_pose():
    seed = _load_script()
    try:
        seed.build_parser().parse_args(["--pose", "crouching"])
    except SystemExit:
        pass
    else:
        raise AssertionError("expected SystemExit")
