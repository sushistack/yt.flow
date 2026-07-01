"""Tests for /api/characters endpoints (Story 3.7 AC: 1-5)."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from yt_flow import db
from yt_flow.api.main import ScpEntry, app
from yt_flow.api.routes.characters import router
from yt_flow.db.models import Character, CharacterCandidate, ReferenceImage

_SAMPLE_SCPS = [ScpEntry(id="SCP-096", nickname="Shy Guy", object_class="Euclid", rating=4.8)]


@asynccontextmanager
async def _noop_lifespan(application):
    yield


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    """In-memory DB + test lifespan + app state for every test."""
    db.init("sqlite://")
    app.state.scps = _SAMPLE_SCPS
    app.state.workspace_path = "./workspace"
    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    yield
    db._engine = None


@pytest.fixture
def client(_setup):
    # Ensure characters router is included for tests
    # (main.py adds it at import time; tests need it explicitly)
    if router not in app.routes and not any(
        hasattr(r, "app") and getattr(r, "path", "").startswith("/api/characters")
        for r in app.routes
    ):
        app.include_router(router)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Helper ────────────────────────────────────────────────────────────────────

def _create_char(
    client,
    scp_id: str = "SCP-096",
    name: str = "Test Character",
    aliases: list[str] | None = None,
) -> dict:
    resp = client.post(
        "/api/characters",
        json={"scp_id": scp_id, "canonical_name": name, "aliases": aliases or []},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── AC 1: POST /api/characters — create ──────────────────────────────────────

def test_create_character_returns_201(client):
    resp = client.post(
        "/api/characters",
        json={"scp_id": "SCP-173", "canonical_name": "The Sculpture"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["scp_id"] == "SCP-173"
    assert body["canonical_name"] == "The Sculpture"
    assert body["aliases"] == []
    assert len(body["id"]) >= 32


def test_create_character_persists_row(client):
    resp = client.post(
        "/api/characters",
        json={"scp_id": "SCP-682", "canonical_name": "Hard-to-Destroy Reptile", "aliases": ["Lizard"]},
    )
    char_id = resp.json()["id"]
    with Session(db._engine) as session:
        char = session.get(Character, char_id)
    assert char is not None
    assert char.scp_id == "SCP-682"
    assert char.aliases == ["Lizard"]


def test_create_character_validates_empty_scp_id(client):
    resp = client.post("/api/characters", json={"scp_id": "", "canonical_name": "X"})
    assert resp.status_code >= 400


def test_create_character_validates_empty_name(client):
    resp = client.post("/api/characters", json={"scp_id": "SCP-999", "canonical_name": ""})
    assert resp.status_code >= 400


# ── AC 1: GET /api/characters — list ─────────────────────────────────────────

def test_list_characters_empty(client):
    resp = client.get("/api/characters")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_characters_returns_all(client):
    _create_char(client, "SCP-096", "Shy Guy")
    _create_char(client, "SCP-173", "The Sculpture")
    resp = client.get("/api/characters")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = {c["canonical_name"] for c in data}
    assert names == {"Shy Guy", "The Sculpture"}


def test_list_characters_filter_by_scp_id(client):
    _create_char(client, "SCP-096", "Shy Guy")
    _create_char(client, "SCP-173", "The Sculpture")
    resp = client.get("/api/characters?scp_id=SCP-096")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["canonical_name"] == "Shy Guy"


# ── AC 2: GET /api/characters/{id} — detail ──────────────────────────────────

def test_get_character_detail(client):
    char = _create_char(client)
    resp = client.get(f"/api/characters/{char['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == char["id"]
    assert body["canonical_name"] == "Test Character"
    assert "references" in body
    assert "candidates" in body


def test_get_character_not_found(client):
    resp = client.get("/api/characters/nonexistent-id")
    assert resp.status_code == 404


# ── AC 3: PATCH /api/characters/{id} — update ────────────────────────────────

def test_update_character(client):
    char = _create_char(client)
    resp = client.patch(
        f"/api/characters/{char['id']}",
        json={"canonical_name": "Updated Name", "aliases": ["Alias1", "Alias2"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["canonical_name"] == "Updated Name"
    assert body["aliases"] == ["Alias1", "Alias2"]


def test_update_character_not_found(client):
    resp = client.patch("/api/characters/nonexistent", json={"canonical_name": "X"})
    assert resp.status_code == 404


# ── AC 4: DELETE /api/characters/{id} — delete ───────────────────────────────

def test_delete_character(client):
    char = _create_char(client)
    resp = client.delete(f"/api/characters/{char['id']}")
    assert resp.status_code == 204
    with Session(db._engine) as session:
        assert session.get(Character, char["id"]) is None


def test_delete_character_not_found(client):
    resp = client.delete("/api/characters/nonexistent")
    assert resp.status_code == 404


# ── AC 3: POST /api/characters/{id}/search-refs — trigger search ─────────────

@patch("yt_flow.services.character_service.DuckDuckGoImageSearch.search")
def test_search_references_trigger(mock_search, client):
    """Search refs triggers DuckDuckGo search and returns references."""
    mock_search.return_value = []  # Return empty results (no real HTTP call)
    char = _create_char(client, "SCP-096", "Shy Guy")
    resp = client.post(f"/api/characters/{char['id']}/search-refs")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "references" in body
    assert body["count"] == 0


# ── AC 3: GET /api/characters/{id}/references — list references ──────────────

def test_list_references_empty(client):
    char = _create_char(client)
    resp = client.get(f"/api/characters/{char['id']}/references")
    assert resp.status_code == 200
    assert resp.json() == []


# ── AC 4: POST /api/characters/{id}/generate — trigger generation ────────────

def test_generate_candidates_trigger(client):
    """Generate triggers candidate creation (requires reference images)."""
    char = _create_char(client, "SCP-096", "Shy Guy")
    char_id = char["id"]
    # Insert a reference image so the generate endpoint doesn't reject
    with Session(db._engine) as session:
        ref = ReferenceImage(
            id="ref-test-1",
            character_id=char_id,
            url="https://example.com/img.png",
            local_path="/tmp/test/img.png",
        )
        session.add(ref)
        session.commit()
    resp = client.post(f"/api/characters/{char_id}/generate")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert "candidates" in body


# ── AC 4: GET /api/characters/{id}/candidates — list candidates ──────────────

def test_list_candidates_empty(client):
    char = _create_char(client)
    resp = client.get(f"/api/characters/{char['id']}/candidates")
    assert resp.status_code == 200
    assert resp.json() == []


# ── AC 4: POST /api/characters/{id}/finalize — finalize ──────────────────────

def test_finalize_not_ready(client):
    char = _create_char(client)
    resp = client.post(f"/api/characters/{char['id']}/finalize")
    # Should fail with 409 if not all angles ready
    assert resp.status_code == 409, resp.text
