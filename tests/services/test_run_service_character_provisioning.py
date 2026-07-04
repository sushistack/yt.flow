"""Story 5.8 — automatic entity reference generation, pre-graph trigger in start_run.

Unit-tests ``run_service._ensure_character_reference`` directly rather than
driving the full graph: the interesting behavior (search/generation trigger,
dedup, non-fatal failure) all happens inside that one function before
``_graph.astream()`` is ever invoked. Search/generation/download are faked
exactly like ``tests/services/test_character_service*.py`` fake them — no
network, no ComfyUI.
"""

from sqlmodel import Session, select

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Character as CharacterModel
from yt_flow.services import character_service, run_service
from yt_flow.services.character_service import CANONICAL_ANGLES


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

    async def generate(self, prompt, ref_image_path, *, width=1664, height=928):
        self.calls += 1
        if not self._ok:
            raise RuntimeError("provider unavailable")
        return b"fake-png-bytes"


def _settings(tmp_path) -> Settings:
    return Settings(
        langfuse_host="http://localhost",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        workspace_path=str(tmp_path / "ws"),
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

    # AD-10 fallback: select_character_angles sees no CharacterModel at all and
    # returns None, same as the pre-Story-5.8 no-character case. The row this
    # function created is rolled back (not left permanently empty) so a future
    # run — after e.g. a transient rate limit clears — can retry the search.
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

        async def generate(self, prompt, ref_image_path, *, width=1664, height=928):
            self.calls += 1
            if self.calls == 1:  # first angle ("front") succeeds, the rest fail
                return b"fake-png-bytes"
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
