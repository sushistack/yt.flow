"""Story 5.8 — automatic entity reference generation, pre-graph trigger in start_run.

Unit-tests ``run_service._ensure_character_reference`` directly rather than
driving the full graph: the interesting behavior (search/generation trigger,
dedup, non-fatal failure) all happens inside that one function before
``_graph.astream()`` is ever invoked. Search/generation/download are faked
exactly like ``tests/services/test_character_service*.py`` fake them — no
network, no ComfyUI.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlmodel import Session, select

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Character as CharacterModel
from yt_flow.domain.state import BANNED_STOCK_TOKEN, DERIVED_DESCRIPTORS, STOCK_NEGATIVE
from yt_flow.services import character_service, run_service
from yt_flow.services.character_service import CANONICAL_ANGLES, CharacterService, pose_hint_key
from tests.stubs.fakes import TINY_PNG


class _FakeImageSearch:
    def __init__(self, results=None):
        self._results = results or []
        self.calls: list[str] = []

    async def search(self, query, max_results=10):
        self.calls.append(query)
        return self._results[:max_results]


class _FakeProvider:
    supports_i2i = True

    def __init__(self, generate_ok: bool = True):
        self._ok = generate_ok
        self.calls = 0

    async def generate(
        self, prompt, ref_image_path, *, width=832, height=1216, ipadapter_weight=None, negative_suffix=None,
    ):
        self.calls += 1
        if not self._ok:
            raise RuntimeError("provider unavailable")
        return TINY_PNG


def _settings(tmp_path) -> Settings:
    return Settings(
        langfuse_host="http://localhost",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        workspace_path=str(tmp_path / "ws"),
        assets_path=str(tmp_path / "assets"),
    )


async def _fake_download(self, url, refs_dir, num):
    refs_dir.mkdir(parents=True, exist_ok=True)
    (refs_dir / f"ref_{num}.png").write_bytes(b"\x89PNG")
    return "png"


def _get_character(scp_id: str) -> CharacterModel | None:
    with Session(db._engine) as session:
        return session.exec(
            select(CharacterModel).where(CharacterModel.scp_id == scp_id)
        ).first()


async def test_no_existing_character_triggers_search_and_generation_once(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    fake_search = _FakeImageSearch([
        {"url": "https://example.com/a.png", "thumbnail_url": "", "title": "a"},
    ])
    monkeypatch.setattr(character_service, "DuckDuckGoImageSearch", lambda: fake_search)
    monkeypatch.setattr(character_service.CharacterService, "_download_reference_image", _fake_download)
    provider = _FakeProvider()
    monkeypatch.setattr(character_service.CharacterService, "_get_image_provider", lambda self: provider)

    await run_service._ensure_character_reference("SCP-096")

    assert fake_search.calls == ["SCP-096 SCP Foundation"]  # AC1 — exactly one search
    assert provider.calls == len(CANONICAL_ANGLES)  # one generation call per angle

    character = _get_character("SCP-096")
    assert character is not None
    assert character.angle_front_path
    assert character.angle_back_path
    assert character.angle_side_path
    assert character.angle_three_quarter_path
    assert character.selected_image_path == character.angle_front_path


async def test_existing_character_does_not_retrigger(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    with Session(db._engine) as session:
        svc = character_service.CharacterService(session, settings=settings)
        svc.create_character("SCP-096", "Pre-existing")

    fake_search = _FakeImageSearch([])
    monkeypatch.setattr(character_service, "DuckDuckGoImageSearch", lambda: fake_search)

    await run_service._ensure_character_reference("SCP-096")

    assert fake_search.calls == []  # AC2/AC4 — no search triggered, character already exists


async def test_search_failure_is_non_fatal(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    class _BrokenSearch:
        async def search(self, query, max_results=10):
            raise RuntimeError("network unreachable")

    monkeypatch.setattr(character_service, "DuckDuckGoImageSearch", _BrokenSearch)

    await run_service._ensure_character_reference("SCP-096")  # must not raise (AC3)

    # AD-10 fallback: resolve_cast_cards (Story 8.3) sees no CharacterModel at all
    # and skips every cast member referencing it, same as the pre-Story-5.8
    # no-character case. The row this function created is rolled back (not left
    # permanently empty) so a future run — after e.g. a transient rate limit
    # clears — can retry the search.
    assert _get_character("SCP-096") is None


async def test_generation_failure_is_non_fatal(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    fake_search = _FakeImageSearch([
        {"url": "https://example.com/a.png", "thumbnail_url": "", "title": "a"},
    ])
    monkeypatch.setattr(character_service, "DuckDuckGoImageSearch", lambda: fake_search)
    monkeypatch.setattr(character_service.CharacterService, "_download_reference_image", _fake_download)
    provider = _FakeProvider(generate_ok=False)
    monkeypatch.setattr(character_service.CharacterService, "_get_image_provider", lambda self: provider)

    await run_service._ensure_character_reference("SCP-096")  # must not raise (AC3)

    # Same rollback as a total search failure — all 4 angles failed, so nothing
    # usable was produced; the row is removed rather than left permanently empty.
    assert _get_character("SCP-096") is None


async def test_partial_generation_failure_keeps_only_successful_angles(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    fake_search = _FakeImageSearch([
        {"url": "https://example.com/a.png", "thumbnail_url": "", "title": "a"},
    ])
    monkeypatch.setattr(character_service, "DuckDuckGoImageSearch", lambda: fake_search)
    monkeypatch.setattr(character_service.CharacterService, "_download_reference_image", _fake_download)

    class _PartialProvider:
        supports_i2i = True

        def __init__(self):
            self.calls = 0

        async def generate(
            self, prompt, ref_image_path, *, width=832, height=1216, ipadapter_weight=None, negative_suffix=None,
        ):
            self.calls += 1
            if self.calls == 1:  # first angle ("front") succeeds, the rest fail
                return TINY_PNG
            raise RuntimeError("provider unavailable")

    provider = _PartialProvider()
    monkeypatch.setattr(character_service.CharacterService, "_get_image_provider", lambda self: provider)

    await run_service._ensure_character_reference("SCP-096")  # must not raise (AC3)

    character = _get_character("SCP-096")
    assert character is not None  # at least one angle succeeded — keep the row
    assert character.angle_front_path
    assert character.selected_image_path == character.angle_front_path
    assert character.angle_back_path is None
    assert character.angle_side_path is None
    assert character.angle_three_quarter_path is None


async def test_concurrent_creation_race_is_non_fatal(monkeypatch, tmp_path):
    """AC4: a second run losing the create_character race (unique scp_id) must not
    look like a provisioning failure — it's another run already handling this SCP."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    with Session(db._engine) as session:
        character_service.CharacterService(session, settings=settings).create_character(
            "SCP-096", "SCP-096",
        )

    real_check = character_service.CharacterService.check_existing_character
    # Simulate the race: this run's own existence check still sees nothing (as if
    # it ran just before the other run's create_character committed).
    monkeypatch.setattr(character_service.CharacterService, "check_existing_character",
                         lambda self, scp_id: None)
    fake_search = _FakeImageSearch([])
    monkeypatch.setattr(character_service, "DuckDuckGoImageSearch", lambda: fake_search)

    await run_service._ensure_character_reference("SCP-096")  # must not raise

    assert fake_search.calls == []  # lost the race at create_character — never reached search
    monkeypatch.setattr(character_service.CharacterService, "check_existing_character", real_check)
    assert _get_character("SCP-096") is not None  # the winner's row is untouched


async def test_enrichment_success_persists_descriptor_before_generation(monkeypatch, tmp_path):
    """AC1: enrich_descriptor_from_references is called after search, before generation,
    and its result is persisted to Character.visual_descriptor."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    fake_search = _FakeImageSearch([
        {"url": "https://example.com/a.png", "thumbnail_url": "", "title": "a"},
    ])
    monkeypatch.setattr(character_service, "DuckDuckGoImageSearch", lambda: fake_search)
    monkeypatch.setattr(character_service.CharacterService, "_download_reference_image", _fake_download)

    class _CapturingProvider:
        supports_i2i = True

        def __init__(self):
            self.prompts: list[str] = []

        async def generate(
            self, prompt, ref_image_path, *, width=832, height=1216, ipadapter_weight=None, negative_suffix=None,
        ):
            self.prompts.append(prompt)
            return TINY_PNG

    provider = _CapturingProvider()

    async def _fake_enrich(self, scp_id, ref_image_paths):
        return "a tall figure in a tattered lab coat"

    monkeypatch.setattr(character_service.CharacterService, "enrich_descriptor_from_references", _fake_enrich)
    monkeypatch.setattr(character_service.CharacterService, "_get_image_provider", lambda self: provider)

    await run_service._ensure_character_reference("SCP-096")

    character = _get_character("SCP-096")
    assert character is not None
    assert character.visual_descriptor == "a tall figure in a tattered lab coat"
    assert len(provider.prompts) == len(CANONICAL_ANGLES)
    # The descriptor was persisted before generation ran — it shows up in every compiled prompt.
    assert all("a tall figure in a tattered lab coat" in p for p in provider.prompts)


async def test_enrichment_failure_is_non_fatal_generation_still_proceeds(monkeypatch, tmp_path):
    """AC2: a Vision LLM enrichment failure must not raise past _ensure_character_reference
    and must not trigger the total-failure rollback — generation proceeds normally."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    fake_search = _FakeImageSearch([
        {"url": "https://example.com/a.png", "thumbnail_url": "", "title": "a"},
    ])
    monkeypatch.setattr(character_service, "DuckDuckGoImageSearch", lambda: fake_search)
    monkeypatch.setattr(character_service.CharacterService, "_download_reference_image", _fake_download)
    provider = _FakeProvider()
    monkeypatch.setattr(character_service.CharacterService, "_get_image_provider", lambda self: provider)

    async def _broken_enrich(self, scp_id, ref_image_paths):
        raise RuntimeError("DeepSeek API unreachable")

    monkeypatch.setattr(character_service.CharacterService, "enrich_descriptor_from_references", _broken_enrich)

    await run_service._ensure_character_reference("SCP-096")  # must not raise

    character = _get_character("SCP-096")
    assert character is not None  # enrichment failure alone must not trigger rollback
    assert character.visual_descriptor is None
    assert provider.calls == len(CANONICAL_ANGLES)  # generation still ran for every angle


async def test_start_run_invokes_character_provisioning(monkeypatch, tmp_path):
    """The one-line production wiring: start_run must actually call
    _ensure_character_reference, not just have it defined."""
    calls: list[str] = []

    async def fake_ensure(scp_id: str) -> None:
        calls.append(scp_id)

    monkeypatch.setattr(run_service, "_ensure_character_reference", fake_ensure)

    async def fake_run(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(run_service, "_run", fake_run)
    monkeypatch.setattr(run_service, "_initial_state", lambda *a, **k: {})
    monkeypatch.setattr(run_service, "_graph", SimpleNamespace(astream=lambda *a, **k: None))

    await run_service.start_run("run-1", "SCP-096", "scp text")

    assert calls == ["SCP-096"]


def _special_pose_scenes(*pairs):
    return [{
        "scene_num": 1,
        "shots": [{
            "shot_id": f"S001{i}",
            "cast": [
                {"card_key": card_key, "position": "center", "depth": "near", "pose": "standing", "pose_hint": hint}
            ],
        } for i, (card_key, hint) in enumerate(pairs, start=1)],
    }]


async def test_special_pose_provisioning_skips_mock_mode(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    settings.comfyui_mock = True
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    calls = []

    async def fake_generate(self, card_key, pose_hint, pose_guide_key=None):
        calls.append((card_key, pose_hint))
        return "/tmp/special.png"

    monkeypatch.setattr(CharacterService, "generate_special_pose_card", fake_generate)

    await run_service._ensure_special_pose_cards("SCP-049", _special_pose_scenes(("SCP-049", "kneeling over a corpse")))

    assert calls == []


async def test_special_pose_provisioning_no_cast_noop(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    calls = []

    async def fake_generate(self, card_key, pose_hint, pose_guide_key=None):
        calls.append((card_key, pose_hint))
        return "/tmp/special.png"

    monkeypatch.setattr(CharacterService, "generate_special_pose_card", fake_generate)

    await run_service._ensure_special_pose_cards("SCP-049", [{"scene_num": 1, "shots": [{"cast": []}]}])

    assert calls == []


async def test_special_pose_provisioning_cache_hit_skips_generation(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    with Session(db._engine) as session:
        CharacterService(session, settings=settings).save_card(
            "SCP-049", pose_hint_key("kneeling over a corpse"), "front", "/tmp/existing.png"
        )
    calls = []

    async def fake_generate(self, card_key, pose_hint, pose_guide_key=None):
        calls.append((card_key, pose_hint))
        return "/tmp/special.png"

    monkeypatch.setattr(CharacterService, "generate_special_pose_card", fake_generate)

    await run_service._ensure_special_pose_cards("SCP-049", _special_pose_scenes(("SCP-049", "kneeling over a corpse")))

    assert calls == []


async def test_special_pose_provisioning_cap_and_warning(monkeypatch, tmp_path, caplog):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    settings.special_pose_max_per_run = 2
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    calls = []

    async def fake_generate(self, card_key, pose_hint, pose_guide_key=None):
        calls.append((card_key, pose_hint))
        return "/tmp/special.png"

    monkeypatch.setattr(CharacterService, "generate_special_pose_card", fake_generate)

    with caplog.at_level("WARNING"):
        await run_service._ensure_special_pose_cards(
            "SCP-049",
            _special_pose_scenes(
                ("SCP-049", "kneeling over a corpse"),
                ("SCP-049", "lying on operating table"),
                ("SCP-049", "reaching toward camera"),
            ),
        )

    assert calls == [
        ("SCP-049", "kneeling over a corpse"),
        ("SCP-049", "lying on operating table"),
    ]
    assert "capped at 2" in caplog.text
    assert "reaching toward camera" in caplog.text


async def test_special_pose_provisioning_generation_failure_swallowed(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    async def fake_generate(self, card_key, pose_hint, pose_guide_key=None):
        raise RuntimeError("renderer down")

    monkeypatch.setattr(CharacterService, "generate_special_pose_card", fake_generate)

    await run_service._ensure_special_pose_cards("SCP-049", _special_pose_scenes(("SCP-049", "kneeling over a corpse")))


def _derived_entity_scenes(*card_keys):
    return [{
        "scene_num": 1,
        "shots": [{
            "shot_id": f"S{i:04d}",
            "cast": [{"card_key": card_key, "position": "center", "depth": "mid", "pose": "standing"}],
        } for i, card_key in enumerate(card_keys, start=1)],
    }]


async def test_derived_entity_provisioning_skips_mock_mode(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    settings.comfyui_mock = True
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    calls = []

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                            angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        calls.append(card_key)
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))

    assert calls == []


async def test_derived_entity_provisioning_no_derived_keys_noop(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    calls = []

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                            angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        calls.append(card_key)
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    # Only stock/base cast, no `<scp_id>-<n>` derived member anywhere.
    await run_service._ensure_derived_entity_cards(
        "SCP-049", _derived_entity_scenes("SCP-049", "STOCK-d-class"),
    )

    assert calls == []


async def test_derived_entity_provisioning_dedup_generates_once(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    with Session(db._engine) as session:
        CharacterService(session, settings=settings).create_character("SCP-049", "SCP-049")
    calls = []

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                            angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        calls.append(card_key)
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    # 5 shots reference the same derived key — generated exactly once (AC1/AC2 dedup).
    await run_service._ensure_derived_entity_cards(
        "SCP-049", _derived_entity_scenes(*(["SCP-049-2"] * 5)),
    )

    assert calls == ["SCP-049-2"]


async def test_derived_entity_provisioning_existing_row_skips(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    with Session(db._engine) as session:
        svc = CharacterService(session, settings=settings)
        svc.create_character("SCP-049", "SCP-049")
        svc.create_character("SCP-049-2", "SCP-049-2")
    calls = []

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                            angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        calls.append(card_key)
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))

    assert calls == []  # a Character row already exists for SCP-049-2 — nothing to do


async def test_derived_entity_provisioning_uses_authored_look_without_anchor(monkeypatch, tmp_path):
    """Story 10.6 (지적 15). This test previously asserted the *bug*: the derived card
    inherited the base's verbatim visual_descriptor and was IPAdapter-locked to the base's
    own front card, so SCP-049-2 rendered as a second hooded plague doctor in a white beak
    mask and read as the same person as SCP-049 in 13 of 66 shots. The contract is now the
    authored look, no anchor, STOCK_NEGATIVE suppression and the enrichment token ban."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    with Session(db._engine) as session:
        svc = CharacterService(session, settings=settings)
        base = svc.create_character("SCP-049", "SCP-049")
        svc.update_character(base.id, angle_front_path="SCP-049/epoch_1/front_candidate_1.png",
                              visual_descriptor="a plague doctor in tattered robes, white beaked mask, black hooded robe")
    captured = {}

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                            angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        captured.update(card_key=card_key, descriptor=descriptor, anchor_path=anchor_path,
                        pose=pose, negative_suffix=negative_suffix, enrich_ban=enrich_ban)
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))

    assert captured["card_key"] == "SCP-049-2"
    assert captured["pose"] == "standing"
    assert captured["anchor_path"] is None  # a family-resemblance lock is the bug, not a feature
    assert captured["descriptor"] == DERIVED_DESCRIPTORS["SCP-049-2"]
    assert captured["negative_suffix"] == STOCK_NEGATIVE
    assert captured["enrich_ban"] == BANNED_STOCK_TOKEN
    # Nothing of the base's wardrobe, and not the live-proven mask attractor either.
    for token in ("plague", "beak", "hooded", BANNED_STOCK_TOKEN.lower()):
        assert token not in captured["descriptor"].lower()


async def test_derived_entity_provisioning_unauthored_key_skips_with_warning(monkeypatch, tmp_path, caplog):
    """A derived key with no authored look generates nothing and does not fail the run
    (AD-10): cast resolution already skips an unprovisioned key, and cast_decision.md's
    rule is "a wrong card is far worse than no card" — guessing is what produced 지적 15."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    with Session(db._engine) as session:
        CharacterService(session, settings=settings).create_character("SCP-173", "SCP-173")
    calls = []

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                            angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        calls.append(card_key)
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    with caplog.at_level("WARNING"):
        await run_service._ensure_derived_entity_cards("SCP-173", _derived_entity_scenes("SCP-173-2"))

    assert calls == []
    assert "SCP-173-2" in caplog.text
    assert "no authored look" in caplog.text


async def test_derived_entity_provisioning_frontless_base_still_generates(monkeypatch, tmp_path):
    """The base entity supplied only the anchor, and there is no anchor any more — so a
    missing/frontless base row no longer degrades anything and no longer warns about a
    lost "family-resemblance anchor"."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    with Session(db._engine) as session:
        CharacterService(session, settings=settings).create_character("SCP-049", "SCP-049")  # no front card
    captured = {}

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                            angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        captured.update(anchor_path=anchor_path, descriptor=descriptor)
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))

    assert captured["anchor_path"] is None
    assert captured["descriptor"] == DERIVED_DESCRIPTORS["SCP-049-2"]


async def test_derived_entity_provisioning_cap_and_warning(monkeypatch, tmp_path, caplog):
    """The cap applies among *authored* keys — unauthored ones are dropped earlier and
    must not consume the budget (see the authored-first test below)."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    settings.derived_entity_max_per_run = 1
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    monkeypatch.setitem(run_service.DERIVED_DESCRIPTORS, "SCP-049-3", "solo, 1boy, a second authored look")
    calls = []

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                            angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        calls.append(card_key)
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    with caplog.at_level("WARNING"):
        await run_service._ensure_derived_entity_cards(
            "SCP-049", _derived_entity_scenes("SCP-049-2", "SCP-049-3"),
        )

    assert calls == ["SCP-049-2"]
    assert "capped at 1" in caplog.text
    assert "SCP-049-3" in caplog.text


async def test_derived_entity_provisioning_unauthored_keys_do_not_consume_the_cap(
    monkeypatch, tmp_path, caplog,
):
    """Regression: the authored filter used to run *inside* the generation loop, after
    the cap slice, so unauthored keys ahead of an authored one burned the budget and
    then skipped — the authored key was never generated at all."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    settings.derived_entity_max_per_run = 2
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    calls = []

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                            angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        calls.append(card_key)
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    with caplog.at_level("WARNING"):
        await run_service._ensure_derived_entity_cards(
            # Two unauthored keys first, filling the cap of 2 under the old ordering.
            "SCP-049", _derived_entity_scenes("SCP-049-8", "SCP-049-9", "SCP-049-2"),
        )

    assert calls == ["SCP-049-2"]
    assert "SCP-049-8" in caplog.text and "SCP-049-9" in caplog.text
    assert "capped at" not in caplog.text  # only one authored key, so the cap never fires


async def test_derived_entity_provisioning_generation_failure_swallowed(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                            angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))  # must not raise


async def test_derived_entity_provisioning_swallowed_failure_rolls_back_stub_row(monkeypatch, tmp_path):
    """Regression for the review finding: a generation call that returns normally
    but produces no front card (e.g. every angle failed inside ComfyUI) must not
    leave a permanent stub `Character` row behind — the next call should still
    treat this derived key as ungenerated and retry it."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    calls = []

    async def fake_generate_no_front(self, card_key, descriptor, *, pose="standing", anchor_path=None,
                                     angles=None, negative_suffix=None, enrich_ban=None, stage=False):
        calls.append(card_key)
        self._ensure_character(card_key)  # mimics the real generator creating the row up front
        return []  # every angle failed — no front card ever gets set

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate_no_front)

    await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))
    with Session(db._engine) as session:
        assert CharacterService(session, settings=settings).check_existing_character("SCP-049-2") is None

    # Retried on the next call — the stub was rolled back, not treated as done.
    await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))
    assert calls == ["SCP-049-2", "SCP-049-2"]


async def test_resume_run_invokes_derived_entity_provisioning(monkeypatch):
    """One-line production wiring: resume_run's scenario-approve path must call
    _ensure_derived_entity_cards alongside _ensure_special_pose_cards."""
    calls = []

    async def fake_ensure(scp_id, scenes):
        calls.append(scp_id)
        return []  # Story 13.1: both provisioning helpers return their warnings

    monkeypatch.setattr(run_service, "_ensure_derived_entity_cards", fake_ensure)
    monkeypatch.setattr(run_service, "_ensure_special_pose_cards", AsyncMock(return_value=[]))

    class _FakeSnapshot:
        values = {"scp_id": "SCP-049", "scenes": []}

    async def fake_aget_state(config):
        return _FakeSnapshot()

    monkeypatch.setattr(run_service, "_graph", SimpleNamespace(
        aget_state=fake_aget_state, astream=lambda *a, **k: iter(()),
    ))
    monkeypatch.setattr(run_service, "_write_run", lambda *a, **k: None)

    async def fake_run(*args, **kwargs):
        return None

    monkeypatch.setattr(run_service, "_run", fake_run)

    await run_service.resume_run("run-1", "scenario", "approve")

    assert calls == ["SCP-049"]


# ── Story 10.5: the pose guide key must survive the harvest ──────────────────
# `_ensure_special_pose_cards` used to collect `(card_key, pose_hint)` and drop
# `pose_guide_key` on the floor, which is the whole reason 8.20's guide apparatus had
# no consumer at generation time. Without these two tests, reverting the triple to a
# pair leaves the suite green.


def _guided_scenes(*triples):
    """One shot per triple; `guide` may be None to model a hint with no guide key."""
    return [{
        "scene_num": 1,
        "shots": [{
            "shot_id": f"S001{i}",
            "cast": [{
                "card_key": card_key, "position": "center", "depth": "near",
                "pose": "standing", "pose_hint": hint,
                **({"pose_guide_key": guide} if guide is not None else {}),
            }],
        } for i, (card_key, hint, guide) in enumerate(triples, start=1)],
    }]


async def test_special_pose_provisioning_forwards_the_guide_key(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    calls = []

    async def fake_generate(self, card_key, pose_hint, pose_guide_key=None):
        calls.append((card_key, pose_hint, pose_guide_key))
        return "/tmp/special.png"

    monkeypatch.setattr(CharacterService, "generate_special_pose_card", fake_generate)

    await run_service._ensure_special_pose_cards("SCP-049", _guided_scenes(
        ("STOCK-d-class", "lying supine on table", "humanoid_lying_supine"),
        ("SCP-049", "extending hand", None),
    ))

    assert calls == [
        ("STOCK-d-class", "lying supine on table", "humanoid_lying_supine"),
        ("SCP-049", "extending hand", None),
    ]


async def test_dedup_keeps_the_first_non_empty_guide_not_the_first_shot(monkeypatch, tmp_path):
    """The common shape: an earlier shot spells the hint with no guide key and a later
    one supplies it. Taking the first occurrence outright would silently render that
    card unconditioned — the defect being fixed is invisible without this case."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    calls = []

    async def fake_generate(self, card_key, pose_hint, pose_guide_key=None):
        calls.append((card_key, pose_hint, pose_guide_key))
        return "/tmp/special.png"

    monkeypatch.setattr(CharacterService, "generate_special_pose_card", fake_generate)

    await run_service._ensure_special_pose_cards("SCP-049", _guided_scenes(
        ("STOCK-d-class", "lying supine on table", None),
        ("STOCK-d-class", "lying supine on table", "humanoid_lying_supine"),
    ))

    # One card (dedup on the pair that names the file), and it keeps the guide.
    assert calls == [("STOCK-d-class", "lying supine on table", "humanoid_lying_supine")]


# ── Story 13.1: provisioning degradations are returned, not just logged ───────


async def test_special_pose_cap_names_every_skipped_key(monkeypatch, tmp_path):
    """Stories 8.4/8.13 both produced empty-room output from this skip. A count would
    not have said which pose went missing, so every skipped key gets its own record."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    settings.special_pose_max_per_run = 1
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    async def fake_generate(self, card_key, pose_hint, pose_guide_key=None):
        return "/tmp/special.png"

    monkeypatch.setattr(CharacterService, "generate_special_pose_card", fake_generate)

    warnings = await run_service._ensure_special_pose_cards(
        "SCP-049",
        _special_pose_scenes(
            ("SCP-049", "kneeling over a corpse"),
            ("SCP-049", "lying on operating table"),
            ("STOCK-security", "aiming a rifle"),
        ),
    )

    assert [w["code"] for w in warnings] == ["special_pose_cap_exceeded"] * 2
    assert all(w["stage"] == "scenario" for w in warnings)
    assert [w["context"]["card_key"] for w in warnings] == ["SCP-049", "STOCK-security"]
    assert [w["context"]["pose_hint"] for w in warnings] == [
        pose_hint_key("lying on operating table"), pose_hint_key("aiming a rifle"),
    ]
    assert warnings[0]["context"]["cap"] == 1


async def test_special_pose_generation_failure_warns_with_the_card_named(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    async def fake_generate(self, card_key, pose_hint, pose_guide_key=None):
        raise RuntimeError("renderer down")

    monkeypatch.setattr(CharacterService, "generate_special_pose_card", fake_generate)

    warnings = await run_service._ensure_special_pose_cards(
        "SCP-049", _special_pose_scenes(("SCP-049", "kneeling over a corpse")))

    assert [w["code"] for w in warnings] == ["special_pose_generation_failed"]
    assert warnings[0]["context"]["card_key"] == "SCP-049"
    assert warnings[0]["context"]["detail"] == "RuntimeError: renderer down"


async def test_mock_mode_provisioning_is_warning_free(monkeypatch, tmp_path):
    """AC2: a bypass that exists only because comfyui_mock=True is not a degradation."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    settings.comfyui_mock = True
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    assert await run_service._ensure_special_pose_cards(
        "SCP-049", _special_pose_scenes(("SCP-049", "kneeling over a corpse"))) == []
    assert await run_service._ensure_derived_entity_cards(
        "SCP-049", _derived_entity_scenes("SCP-049-2")) == []


async def test_unauthored_derived_key_warns_instead_of_vanishing(monkeypatch, tmp_path):
    """Story 10.6 skips a derived key with no authored look — correct, and until now
    invisible: the cast member simply never appears on screen."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    async def fake_generate(self, *args, **kwargs):
        raise AssertionError("an unauthored key must not be generated")

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    warnings = await run_service._ensure_derived_entity_cards(
        "SCP-096", _derived_entity_scenes("SCP-096-2", "SCP-096-3"))

    assert [w["code"] for w in warnings] == ["derived_entity_look_unauthored"] * 2
    assert [w["context"]["card_key"] for w in warnings] == ["SCP-096-2", "SCP-096-3"]


async def test_derived_entity_generation_failure_warns(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    async def fake_generate(self, *args, **kwargs):
        raise RuntimeError("comfy down")

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    warnings = await run_service._ensure_derived_entity_cards(
        "SCP-049", _derived_entity_scenes("SCP-049-2"))

    assert [w["code"] for w in warnings] == ["derived_entity_generation_failed"]
    assert warnings[0]["context"]["card_key"] == "SCP-049-2"


async def test_pre_graph_provisioning_failure_is_seeded_into_the_initial_state(monkeypatch, tmp_path):
    """The warning has to survive the only boundary it can be lost at: there is no
    state yet when pre-graph provisioning runs."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    async def boom(self, scp_id, workspace_path=None):
        raise RuntimeError("search down")

    monkeypatch.setattr(CharacterService, "search_references", boom)

    warnings = await run_service._ensure_character_reference("SCP-096")
    assert [w["code"] for w in warnings] == ["character_provisioning_failed"]

    state = run_service._initial_state("run-1", "SCP-096", "text", None, warnings)
    assert state["run_warnings"] == warnings
    # A restart passes none, so the new attempt starts clean (AC6).
    assert run_service._initial_state("run-1", "SCP-096", "text")["run_warnings"] == []


async def test_swallowed_enrichment_failure_survives_successful_card_generation(monkeypatch, tmp_path):
    """The case a caller cannot detect: enrichment fails, an OLD descriptor comes back,
    generation succeeds, and nothing downstream knows the cards were never described by
    the references they were supposed to come from."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    settings.character_vision_api_key = ""  # capability unavailable at runtime
    collected: list = []
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings, warnings=collected)
        assert await service.enrich_descriptor_from_references("SCP-049", ["/tmp/ref.png"]) is None

    assert [w["code"] for w in collected] == ["vision_enrichment_failed"]
    assert collected[0]["context"] == {"card_key": "SCP-049", "reason": "vision_api_key_missing"}


async def test_a_collectorless_service_keeps_its_old_behaviour(monkeypatch, tmp_path):
    """Every non-run caller (the Character UI, scripts, most tests) passes no collector."""
    db.init("sqlite://")
    settings = _settings(tmp_path)
    settings.character_vision_api_key = ""
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        assert await service.enrich_descriptor_from_references("SCP-049", ["/tmp/ref.png"]) is None
