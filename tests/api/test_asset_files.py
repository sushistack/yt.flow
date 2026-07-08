"""Tests for the /asset-files static mount serving library assets (Story 8.6)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yt_flow.api.main import mount_asset_files


def test_serves_asset_files_at_asset_files(tmp_path):
    assets = tmp_path / "assets"
    (assets / "characters" / "SCP-049" / "epoch_1").mkdir(parents=True)
    (assets / "characters" / "SCP-049" / "epoch_1" / "front.png").write_bytes(b"\x89PNG-bytes")

    app = FastAPI()

    @app.get("/runs")
    def runs():
        return ["ok"]

    mount_asset_files(app, assets)
    client = TestClient(app)

    resp = client.get("/asset-files/characters/SCP-049/epoch_1/front.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG-bytes"
    # API routes must not be shadowed by the static mount.
    assert client.get("/runs").json() == ["ok"]


def test_missing_asset_is_404(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    app = FastAPI()
    mount_asset_files(app, assets)
    assert TestClient(app).get("/asset-files/characters/nope.png").status_code == 404


def test_creates_assets_dir_when_absent(tmp_path):
    assets = tmp_path / "assets"
    app = FastAPI()
    mount_asset_files(app, assets)
    assert assets.is_dir()


def test_dotdot_traversal_outside_assets_is_404(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")

    app = FastAPI()
    mount_asset_files(app, assets)
    resp = TestClient(app).get("/asset-files/characters/../../secret.txt")
    assert resp.status_code == 404
