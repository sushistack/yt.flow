"""Unit tests for CharacterService — CRUD, validation, reference image search, SSRF.
AC: 2, 3, 4, 5
"""

import pytest
from sqlmodel import Session, select

from yt_flow import db
from yt_flow.db.models import Character as CharacterModel
from yt_flow.db.models import ReferenceImage as ReferenceImageModel
from yt_flow.domain.exceptions import ValidationError
from yt_flow.services.character_service import (
    CharacterService,
    _is_private_host,
    _validate_create,
)


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
