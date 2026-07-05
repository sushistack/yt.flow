"""Unit tests for CharacterService — CRUD, validation, reference image search, SSRF.
AC: 2, 3, 4, 5
"""

import httpx
import pytest
from sqlmodel import Session, select

from yt_flow import db
from yt_flow.db.models import ReferenceImage as ReferenceImageModel
from yt_flow.domain.exceptions import ValidationError
from yt_flow.services.character_service import (
    CharacterService,
    _is_private_host,
    _validate_create,
)
from yt_flow.services.image_search import WikiImage


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _init_db():
    """Fresh file-based SQLite for each test."""
    db.init("sqlite://")


@pytest.fixture
def session():
    from yt_flow.db import _engine
    with Session(_engine) as s:
        yield s


@pytest.fixture
def service(session):
    return CharacterService(session)


# ── Validation (AC5) ─────────────────────────────────────────────────────────


class TestValidation:
    """AC5: ValidationError raised on invalid input."""

    def test_empty_scp_id(self):
        with pytest.raises(ValidationError, match="scp_id"):
            _validate_create("", "Name", None)

    def test_whitespace_scp_id(self):
        with pytest.raises(ValidationError, match="scp_id"):
            _validate_create("   ", "Name", None)

    def test_empty_canonical_name(self):
        with pytest.raises(ValidationError, match="canonical_name"):
            _validate_create("SCP-096", "", None)

    def test_whitespace_canonical_name(self):
        with pytest.raises(ValidationError, match="canonical_name"):
            _validate_create("SCP-096", "  ", None)

    def test_empty_alias(self):
        with pytest.raises(ValidationError, match="aliases"):
            _validate_create("SCP-096", "Shy Guy", ["valid", ""])

    def test_whitespace_only_alias(self):
        with pytest.raises(ValidationError, match="aliases"):
            _validate_create("SCP-096", "Shy Guy", ["  "])

    def test_validation_error_has_field_and_message(self):
        try:
            raise ValidationError("test_field", "test message")
        except ValidationError as e:
            assert e.field == "test_field"
            assert e.message == "test message"
            assert "test_field" in str(e)

    def test_valid_input_does_not_raise(self):
        _validate_create("SCP-096", "Shy Guy", ["The Shy Guy", "096"])
        _validate_create("SCP-173", "The Sculpture", None)
        _validate_create("SCP-049", "Plague Doctor", [])


# ── CRUD (AC2) ───────────────────────────────────────────────────────────────


class TestCharacterCRUD:
    """AC2: CharacterService CRUD operations."""

    def test_create_character(self, service):
        c = service.create_character("SCP-096", "Shy Guy", ["The Shy Guy"])
        assert c.id is not None
        assert c.scp_id == "SCP-096"
        assert c.canonical_name == "Shy Guy"
        assert c.aliases == ["The Shy Guy"]

    def test_create_character_default_aliases(self, service):
        c = service.create_character("SCP-173", "The Sculpture")
        assert c.aliases == []

    def test_get_character(self, service):
        created = service.create_character("SCP-096", "Shy Guy")
        fetched = service.get_character(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.canonical_name == "Shy Guy"

    def test_get_character_not_found(self, service):
        assert service.get_character("nonexistent-id") is None

    def test_list_characters(self, service):
        service.create_character("SCP-096", "Shy Guy")
        service.create_character("SCP-173", "The Sculpture")
        service.create_character("SCP-682", "Hard-to-Destroy Reptile")

        results = service.list_characters("SCP-096")
        assert len(results) == 1
        assert results[0].scp_id == "SCP-096"

        results_173 = service.list_characters("SCP-173")
        assert len(results_173) == 1

    def test_list_all_characters(self, service):
        service.create_character("SCP-096", "A")
        service.create_character("SCP-173", "B")
        assert len(service.list_all_characters()) == 2

    def test_check_existing_character(self, service):
        assert service.check_existing_character("SCP-096") is None
        service.create_character("SCP-096", "Shy Guy")
        found = service.check_existing_character("SCP-096")
        assert found is not None
        assert found.canonical_name == "Shy Guy"

    def test_update_character(self, service):
        c = service.create_character("SCP-096", "Shy Guy")
        updated = service.update_character(c.id, canonical_name="The Shy Guy", aliases=["096", "Shy"])
        assert updated.canonical_name == "The Shy Guy"
        assert updated.aliases == ["096", "Shy"]

    def test_update_character_not_found(self, service):
        with pytest.raises(LookupError, match="not found"):
            service.update_character("no-such-id", canonical_name="x")

    def test_delete_character(self, service):
        c = service.create_character("SCP-096", "Shy Guy")
        service.delete_character(c.id)
        assert service.get_character(c.id) is None

    def test_delete_character_not_found(self, service):
        with pytest.raises(LookupError, match="not found"):
            service.delete_character("no-such-id")

    def test_delete_cascades_candidates_not_just_orphans_them(self, session):
        """Regression: a deleted character's candidates must not survive to be
        "adopted" by a future character created for the same scp_id.

        delete_character() used to only null a candidate's character_id FK
        instead of deleting the row. list_candidates() (used by both the
        detail GET and the polling GET) filters by scp_id alone, not
        character_id — so those orphaned rows, including a stale "ready"
        status, would resurface as soon as anyone created a new character for
        the same scp_id, making it look fully generated without any real
        generation happening.
        """
        from yt_flow.services.character_service import CANONICAL_ANGLES

        svc = CharacterService(session)
        c = svc.create_character("SCP-096", "Shy Guy")
        candidates = svc.create_candidate_batch("SCP-096")
        for cand in candidates:
            svc.update_candidate_status(cand.id, "ready", image_path="/tmp/x.png")

        svc.delete_character(c.id)

        assert svc.list_candidates("SCP-096") == []

        # A new character for the same scp_id must start with zero candidates.
        c2 = svc.create_character("SCP-096", "Shy Guy Returns")
        assert svc.list_candidates(c2.scp_id) == []
        assert len(CANONICAL_ANGLES) == 4  # sanity: the 4 angles this test relies on

    def test_delete_cascades_reference_images(self, service, session):
        c = service.create_character("SCP-096", "Shy Guy")
        ref = ReferenceImageModel(character_id=c.id, url="http://x.com/a.jpg", local_path="/tmp/a.jpg")
        session.add(ref)
        session.commit()

        service.delete_character(c.id)
        remaining = session.exec(
            select(ReferenceImageModel).where(ReferenceImageModel.character_id == c.id)
        ).all()
        assert len(remaining) == 0


# ── SSRF Protection (AC4) ────────────────────────────────────────────────────


class TestSSRFProtection:
    """AC4: Private/loopback IP addresses are blocked."""

    @staticmethod
    def _check(host: str) -> bool:
        import asyncio
        return asyncio.run(_is_private_host(host))

    def test_loopback_blocked(self):
        assert self._check("127.0.0.1") is True
        assert self._check("::1") is True

    def test_rfc1918_blocked(self):
        assert self._check("10.0.0.1") is True
        assert self._check("172.16.0.1") is True
        assert self._check("192.168.1.1") is True

    def test_public_ip_allowed(self):
        assert self._check("8.8.8.8") is False
        assert self._check("1.1.1.1") is False

    def test_non_ip_host_not_resolved_as_private(self):
        """Hostnames that don't resolve to IPs should not match private ranges."""
        assert self._check("example.com") is False


# ── Reference Image Search (AC2, AC4) ────────────────────────────────────────


class _FakeImageSearch:
    """Fake ImageSearch that returns canned results."""

    def __init__(self, results=None):
        self._results = results or []

    async def search(self, query, max_results=10):
        return self._results[:max_results]


class _FakeWikiFetch:
    """Fake ScpWikiImageFetch — returns a canned WikiImage, or None to force DDG fallback."""

    def __init__(self, wiki_image=None):
        self._wiki_image = wiki_image

    async def fetch(self, scp_id):
        return self._wiki_image


class _FakeWikiFetchRaises:
    """Fake ScpWikiImageFetch whose fetch() itself errors (network blip, not a clean miss)."""

    async def fetch(self, scp_id):
        raise httpx.ConnectError("boom")


class TestReferenceImageSearch:
    """AC4: search_references downloads with safety checks."""

    def test_search_references_no_character(self, service):
        import asyncio
        with pytest.raises(LookupError, match="No character found"):
            asyncio.run(service.search_references("SCP-096", "/tmp/workspace"))

    @pytest.mark.asyncio
    async def test_search_references_deduplication(self, service, session):
        """Existing references skip search (dedup)."""
        c = service.create_character("SCP-096", "Shy Guy")
        ref = ReferenceImageModel(character_id=c.id, url="http://x.com/a.jpg", local_path="/tmp/a.jpg")
        session.add(ref)
        session.commit()

        # Should skip search because refs already exist
        result = await service.search_references("SCP-096", "/tmp/workspace")
        assert len(result) == 1
        assert result[0].url == "http://x.com/a.jpg"

    @pytest.mark.asyncio
    async def test_search_references_http_timeout(self, monkeypatch):
        """Downloads respect 30-second timeout."""
        from yt_flow.services.character_service import _DOWNLOAD_TIMEOUT
        assert _DOWNLOAD_TIMEOUT == 30.0

    @pytest.mark.asyncio
    async def test_search_references_downloads_and_persists_results(self, session, monkeypatch, tmp_path):
        """Regression: non-empty search results must actually download and persist.

        ``SearchResult`` is a TypedDict (a plain dict at runtime); a prior bug
        accessed ``result.url`` instead of ``result["url"]``, raising
        AttributeError on every real result — silently swallowed by the
        surrounding except/continue, so 0 references were ever downloaded.
        The other tests in this class only cover the empty-results and
        dedup-existing-refs branches, neither of which reaches that line.
        """
        svc = CharacterService(
            session,
            image_search=_FakeImageSearch([
                {"url": "https://example.com/a.png", "thumbnail_url": "https://example.com/a_t.png", "title": "a"},
                {"url": "https://example.com/b.png", "thumbnail_url": "https://example.com/b_t.png", "title": "b"},
            ]),
            wiki_fetch=_FakeWikiFetch(),  # miss -> falls through to DDG fake below
        )
        svc.create_character("SCP-096", "Shy Guy")

        async def fake_download(self, url, refs_dir, num):
            refs_dir.mkdir(parents=True, exist_ok=True)
            (refs_dir / f"ref_{num}.png").write_bytes(b"\x89PNG")
            return "png"

        monkeypatch.setattr(CharacterService, "_download_reference_image", fake_download)

        result = await svc.search_references("SCP-096", tmp_path, max_results=10)
        assert [r.url for r in result] == ["https://example.com/a.png", "https://example.com/b.png"]


class TestWikiFirstReferenceSearch:
    """AC1-3 (Story 5.10): SCP Wiki is tried first; DuckDuckGo is the fallback."""

    @pytest.mark.asyncio
    async def test_wiki_hit_downloads_and_persists_page_url_for_attribution(self, session, monkeypatch, tmp_path):
        """AC1/AC3: a wiki hit downloads the image and stores the page URL (not the
        asset URL) on the ReferenceImage record, for CC BY-SA provenance."""
        svc = CharacterService(
            session,
            image_search=_FakeImageSearch([{"url": "https://ddg.example/should-not-be-used.png",
                                             "thumbnail_url": "", "title": ""}]),
            wiki_fetch=_FakeWikiFetch(WikiImage(
                image_url="https://scp-wiki.wdfiles.com/local--files/scp-096/shy-guy.jpg",
                page_url="https://scp-wiki.wikidot.com/scp-096",
            )),
        )
        svc.create_character("SCP-096", "Shy Guy")

        async def fake_download(self, url, refs_dir, num):
            assert url == "https://scp-wiki.wdfiles.com/local--files/scp-096/shy-guy.jpg"
            refs_dir.mkdir(parents=True, exist_ok=True)
            (refs_dir / f"ref_{num}.jpg").write_bytes(b"\xff\xd8")
            return "jpg"

        monkeypatch.setattr(CharacterService, "_download_reference_image", fake_download)

        result = await svc.search_references("SCP-096", tmp_path, max_results=10)
        assert len(result) == 1
        assert result[0].url == "https://scp-wiki.wikidot.com/scp-096"

    @pytest.mark.asyncio
    async def test_wiki_download_error_falls_back_to_ddg(self, session, monkeypatch, tmp_path):
        """AC2: if the wiki image itself fails to download, fall back to DuckDuckGo."""
        svc = CharacterService(
            session,
            image_search=_FakeImageSearch([{"url": "https://ddg.example/fallback.png",
                                             "thumbnail_url": "", "title": ""}]),
            wiki_fetch=_FakeWikiFetch(WikiImage(
                image_url="https://scp-wiki.wdfiles.com/local--files/scp-096/broken.jpg",
                page_url="https://scp-wiki.wikidot.com/scp-096",
            )),
        )
        svc.create_character("SCP-096", "Shy Guy")

        async def fake_download(self, url, refs_dir, num):
            if "wdfiles.com" in url:
                raise ValueError("simulated download failure")
            refs_dir.mkdir(parents=True, exist_ok=True)
            (refs_dir / f"ref_{num}.png").write_bytes(b"\x89PNG")
            return "png"

        monkeypatch.setattr(CharacterService, "_download_reference_image", fake_download)

        result = await svc.search_references("SCP-096", tmp_path, max_results=10)
        assert len(result) == 1
        assert result[0].url == "https://ddg.example/fallback.png"

    @pytest.mark.asyncio
    async def test_wiki_fetch_error_falls_back_to_ddg(self, session, monkeypatch, tmp_path):
        """AC2: if the wiki fetch itself raises, fall back to DuckDuckGo rather than
        propagating — a transient network blip must not break reference provisioning."""
        svc = CharacterService(
            session,
            image_search=_FakeImageSearch([{"url": "https://ddg.example/fallback.png",
                                             "thumbnail_url": "", "title": ""}]),
            wiki_fetch=_FakeWikiFetchRaises(),
        )
        svc.create_character("SCP-096", "Shy Guy")

        async def fake_download(self, url, refs_dir, num):
            refs_dir.mkdir(parents=True, exist_ok=True)
            (refs_dir / f"ref_{num}.png").write_bytes(b"\x89PNG")
            return "png"

        monkeypatch.setattr(CharacterService, "_download_reference_image", fake_download)

        with pytest.raises(httpx.ConnectError):
            await svc.search_references("SCP-096", tmp_path, max_results=10)


# ── Layer-boundary test ──────────────────────────────────────────────────────


def test_services_does_not_import_api_or_pipeline():
    """AD-1: services/ must not import api/ or pipeline/.
    Excludes run_service.py (the sole graph.astream() caller, per AD-3, AD-4)."""
    import ast
    from pathlib import Path

    svc_dir = Path(__file__).resolve().parents[2] / "src" / "yt_flow" / "services"
    for py in svc_dir.glob("*.py"):
        if py.name in ("__init__.py", "run_service.py"):
            continue  # run_service is the sole astream() caller (AD-3, AD-4)
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("yt_flow.api"), f"{py.name}: imports {module}"
                assert not module.startswith("yt_flow.pipeline"), f"{py.name}: imports {module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("yt_flow.api"), f"{py.name}: imports {alias.name}"
                    assert not alias.name.startswith("yt_flow.pipeline"), f"{py.name}: imports {alias.name}"
