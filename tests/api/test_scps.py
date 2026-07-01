"""Tests for GET /scps (Story 2.5 AC: 1, 6)."""
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from yt_flow import db
from yt_flow.api.main import ScpEntry, app

_SAMPLE_SCPS = [
    ScpEntry(id="SCP-096", nickname="The Shy Guy", object_class="Euclid", rating=4.8),
    ScpEntry(id="SCP-173", nickname="The Sculpture", object_class="Euclid", rating=4.9),
]


@asynccontextmanager
async def _noop_lifespan(application):
    yield


@pytest.fixture
def client(monkeypatch):
    db.init("sqlite://")
    app.state.scps = _SAMPLE_SCPS
    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    with TestClient(app) as c:
        yield c
    db._engine = None


# ── AC 1: returns list from app.state.scps with correct fields ──────────────

def test_get_scps_returns_list(client):
    resp = client.get("/scps")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0] == {
        "id": "SCP-096",
        "nickname": "The Shy Guy",
        "object_class": "Euclid",
        "rating": 4.8,
    }


# ── AC 6: a started app always returns a valid list ─────────────────────────

def test_get_scps_all_entries_valid(client):
    for entry in client.get("/scps").json():
        assert set(entry) == {"id", "nickname", "object_class", "rating"}
