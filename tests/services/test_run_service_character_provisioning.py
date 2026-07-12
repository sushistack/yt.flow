"""Story 5.8 — automatic entity reference generation, pre-graph trigger in start_run.

Unit-tests ``run_service._ensure_character_reference`` directly rather than
driving the full graph: the interesting behavior (search/generation trigger,
dedup, non-fatal failure) all happens inside that one function before
``_graph.astream()`` is ever invoked. Search/generation/download are faked
exactly like ``tests/services/test_character_service*.py`` fake them — no
network, no ComfyUI.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlmodel import Session, select

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Character as CharacterModel
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

    async def generate(self, prompt, ref_image_path, *, width=832, height=1216, ipadapter_weight=None):
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

        async def generate(self, prompt, ref_image_path, *, width=832, height=1216, ipadapter_weight=None):
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

        async def generate(self, prompt, ref_image_path, *, width=832, height=1216, ipadapter_weight=None):
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

    async def fake_generate(self, card_key, pose_hint):
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

    async def fake_generate(self, card_key, pose_hint):
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

    async def fake_generate(self, card_key, pose_hint):
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

    async def fake_generate(self, card_key, pose_hint):
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

    async def fake_generate(self, card_key, pose_hint):
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

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None, angles=None):
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

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None, angles=None):
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

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None, angles=None):
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

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None, angles=None):
        calls.append(card_key)
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))

    assert calls == []  # a Character row already exists for SCP-049-2 — nothing to do


async def test_derived_entity_provisioning_uses_base_front_card_as_anchor(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    with Session(db._engine) as session:
        svc = CharacterService(session, settings=settings)
        base = svc.create_character("SCP-049", "SCP-049")
        svc.update_character(base.id, angle_front_path="SCP-049/epoch_1/front_candidate_1.png",
                              visual_descriptor="a plague doctor in tattered robes")
    captured = {}

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None, angles=None):
        captured["card_key"] = card_key
        captured["descriptor"] = descriptor
        captured["anchor_path"] = anchor_path
        captured["pose"] = pose
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))

    assert captured["card_key"] == "SCP-049-2"
    assert captured["pose"] == "standing"
    assert captured["anchor_path"] == str(Path(settings.assets_path) / "SCP-049/epoch_1/front_candidate_1.png")
    assert "a plague doctor in tattered robes" in captured["descriptor"]
    assert "SCP-049" in captured["descriptor"]


async def test_derived_entity_provisioning_missing_base_front_card_degrades(monkeypatch, tmp_path, caplog):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    with Session(db._engine) as session:
        CharacterService(session, settings=settings).create_character("SCP-049", "SCP-049")  # no front card
    captured = {}

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None, angles=None):
        captured["anchor_path"] = anchor_path
        return ["/tmp/derived.png"]

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    with caplog.at_level("WARNING"):
        await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))

    assert captured["anchor_path"] is None  # degrade path — no anchor, generation still proceeds
    assert "no front card" in caplog.text


async def test_derived_entity_provisioning_cap_and_warning(monkeypatch, tmp_path, caplog):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    settings.derived_entity_max_per_run = 1
    monkeypatch.setattr(run_service, "_settings", lambda: settings)
    calls = []

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None, angles=None):
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


async def test_derived_entity_provisioning_generation_failure_swallowed(monkeypatch, tmp_path):
    db.init("sqlite://")
    settings = _settings(tmp_path)
    monkeypatch.setattr(run_service, "_settings", lambda: settings)

    async def fake_generate(self, card_key, descriptor, *, pose="standing", anchor_path=None, angles=None):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(CharacterService, "generate_cards_from_descriptor", fake_generate)

    await run_service._ensure_derived_entity_cards("SCP-049", _derived_entity_scenes("SCP-049-2"))  # must not raise



async def test_resume_run_invokes_derived_entity_provisioning(monkeypatch):
    """One-line production wiring: resume_run's scenario-approve path must call
    _ensure_derived_entity_cards alongside _ensure_special_pose_cards."""
    calls = []

    async def fake_ensure(scp_id, scenes):
        calls.append(scp_id)

    monkeypatch.setattr(run_service, "_ensure_derived_entity_cards", fake_ensure)
    monkeypatch.setattr(run_service, "_ensure_special_pose_cards", AsyncMock())

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
