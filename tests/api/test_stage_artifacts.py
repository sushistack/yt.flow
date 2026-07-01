"""Tests for GET /runs/{id}/stages/{stage}/artifacts (Story 2.5 AC: 2-5).

The graph is mocked — no real LangGraph DB. We patch run_service.build_graph to
hand back a graph whose aget_state() returns a canned PipelineState.
"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from yt_flow import db
from yt_flow.api.main import app
from yt_flow.services import run_service

RUN_ID = "11111111-1111-4111-8111-111111111111"


def _scene(n, *, image=None, audio=None, subtitle=None):
    return {
        "scene_num": n,
        "narration": f"narration {n}",
        "shots": [{
            "shot_id": f"S00{n}",
            "sentence_indices": [0, 1],
            "image_prompt": "a dark corridor",
            "negative_prompt": "bright, daylight",
            "camera_angle": "medium",
            "camera_movement": "static",
            "image_path": image,
            "background_path": None,
            "character_path": None,
        }],
        "audio_path": audio,
        "audio_duration": 12.5 if audio else None,
        "word_timings": [],
        "subtitle_path": subtitle,
    }


def _state(scenes, video_path=None):
    return {
        "run_id": RUN_ID,
        "scp_text": "text",
        "scenes": scenes,
        "video_path": video_path,
        "current_stage": "scenario",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }


# Fully-complete run: every stage reached.
_COMPLETE = _state(
    [_scene(1, image="workspace/x/images/S001.png",
            audio="workspace/x/audio/scene_01.mp3",
            subtitle="workspace/x/subtitles/scene_01.srt")],
    video_path="workspace/x/output.mp4",
)
# Scenario reached only: scenes exist but no downstream artifacts.
_SCENARIO_ONLY = _state([_scene(1)])


@pytest.fixture
def client(monkeypatch):
    db.init("sqlite://")
    app.state.scps = []

    @asynccontextmanager
    async def _noop(application):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", _noop)
    with TestClient(app) as c:
        yield c
    db._engine = None


def _mock_graph(monkeypatch, values):
    graph = MagicMock()
    graph.aget_state = AsyncMock(return_value=SimpleNamespace(values=values))
    saver = MagicMock()
    saver.conn.close = AsyncMock()
    monkeypatch.setattr(run_service, "build_graph", AsyncMock(return_value=(graph, saver)))


# ── AC 2: per-stage artifact data read from checkpoint ──────────────────────

def test_scenario_artifacts(client, monkeypatch):
    _mock_graph(monkeypatch, _COMPLETE)
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["stage"] == "scenario"
    assert body["scenes"][0]["narration"] == "narration 1"
    assert body["scenes"][0]["shots"][0]["shot_id"] == "S001"


def test_image_artifacts(client, monkeypatch):
    _mock_graph(monkeypatch, _COMPLETE)
    resp = client.get(f"/runs/{RUN_ID}/stages/image/artifacts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stage"] == "image"
    assert body["images"][0] == {
        "scene_num": 1, "shot_id": "S001", "image_path": "workspace/x/images/S001.png",
    }


def test_tts_artifacts(client, monkeypatch):
    _mock_graph(monkeypatch, _COMPLETE)
    body = client.get(f"/runs/{RUN_ID}/stages/tts/artifacts").json()
    assert body["stage"] == "tts"
    assert body["audio"][0] == {
        "scene_num": 1, "audio_path": "workspace/x/audio/scene_01.mp3", "duration_sec": 12.5,
    }


def test_subtitle_artifacts(client, monkeypatch):
    _mock_graph(monkeypatch, _COMPLETE)
    body = client.get(f"/runs/{RUN_ID}/stages/subtitle/artifacts").json()
    assert body["stage"] == "subtitle"
    assert body["subtitles"][0] == {
        "scene_num": 1, "subtitle_path": "workspace/x/subtitles/scene_01.srt",
    }


def test_video_artifacts(client, monkeypatch):
    _mock_graph(monkeypatch, _COMPLETE)
    body = client.get(f"/runs/{RUN_ID}/stages/video/artifacts").json()
    assert body == {"stage": "video", "video_path": "workspace/x/output.mp4"}


# ── AC 3 / AC 5: stage not yet reached → 404 ────────────────────────────────

def test_stage_not_reached_404(client, monkeypatch):
    _mock_graph(monkeypatch, _SCENARIO_ONLY)
    assert client.get(f"/runs/{RUN_ID}/stages/image/artifacts").status_code == 404


def test_scenario_not_reached_404(client, monkeypatch):
    _mock_graph(monkeypatch, _state([]))  # no scenes yet
    assert client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").status_code == 404


# ── AC 4: invalid run_id (no checkpoint) → 404 "Run not found" ──────────────

def test_invalid_run_id_404(client, monkeypatch):
    _mock_graph(monkeypatch, {})  # empty checkpoint values
    resp = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Run not found"}


# ── AC (route): invalid stage name → 422 ────────────────────────────────────

def test_invalid_stage_422(client, monkeypatch):
    _mock_graph(monkeypatch, _COMPLETE)
    assert client.get(f"/runs/{RUN_ID}/stages/render/artifacts").status_code == 422
