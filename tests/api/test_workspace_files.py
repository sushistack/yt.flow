"""Tests for the /files static mount serving workspace artifacts (Story 3.4).

The Run Detail UI loads scene images, per-scene audio, subtitle files and the
intermediate video by URL. The stage-artifacts API returns server filesystem
paths under workspace/{run_id}/...; this mount exposes those bytes to the
browser without the frontend ever reading workspace/ directly.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yt_flow.api.main import mount_workspace_files


def test_serves_workspace_artifacts_at_files(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "run-1" / "images").mkdir(parents=True)
    (ws / "run-1" / "images" / "scene_001.png").write_bytes(b"\x89PNG-bytes")

    app = FastAPI()

    @app.get("/runs")
    def runs():
        return ["ok"]

    mount_workspace_files(app, ws)
    client = TestClient(app)

    resp = client.get("/files/run-1/images/scene_001.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG-bytes"
    # API routes must not be shadowed by the static mount.
    assert client.get("/runs").json() == ["ok"]


def test_missing_artifact_is_404(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    app = FastAPI()
    mount_workspace_files(app, ws)
    assert TestClient(app).get("/files/run-1/nope.png").status_code == 404


def test_creates_workspace_dir_when_absent(tmp_path):
    # No runs yet: the mount must not crash when workspace/ does not exist.
    ws = tmp_path / "workspace"
    app = FastAPI()
    mount_workspace_files(app, ws)
    assert ws.is_dir()
