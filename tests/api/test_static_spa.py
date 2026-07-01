"""Tests for the /app static SPA mount (Story 3.1 AC: 1)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yt_flow.api.main import mount_static_spa


def _make_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>yt.flow</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    return dist


def test_serves_spa_and_assets_at_app(tmp_path):
    app = FastAPI()

    @app.get("/scps")
    def scps():
        return ["ok"]

    mount_static_spa(app, _make_dist(tmp_path))
    client = TestClient(app)

    index = client.get("/app/")
    assert index.status_code == 200
    assert "yt.flow" in index.text
    assert client.get("/app/assets/app.js").status_code == 200
    # AC1: API routes must not be shadowed by the static mount.
    assert client.get("/scps").json() == ["ok"]


def test_skips_mount_when_build_absent(tmp_path):
    app = FastAPI()
    mount_static_spa(app, tmp_path / "missing")
    assert client_404(app)


def client_404(app):
    return TestClient(app).get("/app/").status_code == 404
