"""Tests for stage control endpoints — retry & artifact edit (Story 2.4 AC: 1-7).

The compiled graph is replaced with a FakeGraph via run_service.configure(), the
same injection seam Story 2.3 uses. [AD-9, AD-8]
"""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from yt_flow import db
from yt_flow.api.main import ScpEntry, app
from yt_flow.db.models import Run
from yt_flow.services import run_service


# ── Test doubles ─────────────────────────────────────────────────────────────


class _Snap:
    def __init__(self, values): self.values = values


class FakeGraph:
    """Records aupdate_state/astream; serves aget_state from an in-memory dict."""

    def __init__(self, state=None):
        self.state = state or {}
        self.updates = []       # list of (values, as_node)
        self.astream_calls = []

    async def aget_state(self, config):
        return _Snap(self.state)

    async def aupdate_state(self, config, values, as_node=None):
        self.updates.append((values, as_node))
        self.state = {**self.state, **values}
        return config

    def astream(self, inp, config, stream_mode=None):
        self.astream_calls.append((inp, config))
        return _empty()


async def _empty():
    return
    yield  # noqa: unreachable — makes this an async generator


class RecordingRegistry:
    def __init__(self): self.events = []
    async def publish(self, run_id, event): self.events.append((run_id, event))


@asynccontextmanager
async def _noop_lifespan(application):
    yield


def _scene(num=1, narration="old", image=True, audio=True, subtitle="/tmp/s.srt"):
    return {
        "scene_num": num,
        "narration": narration,
        "shots": [{
            "shot_id": f"{num}-1", "sentence_indices": [0],
            "image_prompt": "p", "negative_prompt": "n",
            "camera_angle": None, "camera_movement": None,
            "image_path": "/tmp/img.png" if image else None,
            "background_path": "/tmp/bg.png" if image else None,
            "character_path": "/tmp/ch.png" if image else None,
        }],
        "audio_path": "/tmp/a.wav" if audio else None,
        "audio_duration": 3.0 if audio else None,
        "word_timings": [{"word": "hi", "start_sec": 0.0, "end_sec": 1.0}] if audio else [],
        "subtitle_path": subtitle,
    }


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    db.init("sqlite://")
    app.state.scps = [ScpEntry(id="SCP-096", nickname="Shy Guy", object_class="Euclid", rating=4.8)]
    app.state.workspace_path = str(tmp_path)
    app.state.sse_registry = RecordingRegistry()
    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    monkeypatch.setattr(run_service, "_settings",
                        lambda: SimpleNamespace(workspace_path=str(tmp_path)))
    yield
    run_service.configure(None)
    run_service._configs.clear()
    db._engine = None


@pytest.fixture
def client(_setup):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _graph(state=None):
    g = FakeGraph(state)
    run_service.configure(g)
    return g


def _seed(run_id="r1", gate_states=None, status="awaiting_approval"):
    with Session(db._engine) as session:
        session.add(Run(
            id=run_id, scp_id="SCP-096", status=status,
            gate_states=json.dumps(gate_states) if gate_states else None,
        ))
        session.commit()
    return run_id


# ── AC 1: retry happy path → 202 + stage_entry SSE + gate reset ───────────────

def test_retry_scenario_approved_returns_202(client):
    _seed(gate_states={"scenario": "approved"})
    _graph({"scenes": [_scene()], "gate_states": {"scenario": "approved"}})
    resp = client.post("/runs/r1/stages/scenario/retry")
    assert resp.status_code == 202
    assert resp.json()["status"] == "retrying"


def test_retry_emits_stage_entry_sse(client):
    _seed(gate_states={"scenario": "approved"})
    _graph({"scenes": [_scene()]})
    client.post("/runs/r1/stages/scenario/retry")
    events = app.state.sse_registry.events
    assert any(ev["event"] == "stage_entry" and ev["data"]["stage"] == "scenario"
               for _, ev in events)


def test_retry_resets_gate_to_pending_in_db(client):
    _seed(gate_states={"scenario": "approved", "image": "approved"})
    _graph({"scenes": [_scene()]})
    client.post("/runs/r1/stages/scenario/retry")
    with Session(db._engine) as session:
        run = session.get(Run, "r1")
    gs = json.loads(run.gate_states)
    assert gs["scenario"] == "pending"
    assert gs["image"] == "pending"  # downstream also reset


# ── AC 2: retry conflict when gate pending / absent → 409 ─────────────────────

def test_retry_pending_returns_409(client):
    _seed(gate_states={"scenario": "pending"})
    _graph({"scenes": [_scene()]})
    resp = client.post("/runs/r1/stages/scenario/retry")
    assert resp.status_code == 409


def test_retry_absent_gate_returns_409(client):
    _seed(gate_states={})
    _graph({"scenes": [_scene()]})
    resp = client.post("/runs/r1/stages/scenario/retry")
    assert resp.status_code == 409


def test_retry_image_failed_returns_202(client):
    _seed(gate_states={"image": "failed"})
    _graph({"scenes": [_scene()]})
    resp = client.post("/runs/r1/stages/image/retry")
    assert resp.status_code == 202


# ── AC 3: retry not found ─────────────────────────────────────────────────────

def test_retry_unknown_stage_404(client):
    _seed(gate_states={"scenario": "approved"})
    _graph()
    resp = client.post("/runs/r1/stages/nonexistent/retry")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Unknown stage"


def test_retry_unknown_run_404(client):
    _graph()
    resp = client.post("/runs/does-not-exist/stages/scenario/retry")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Run not found"


# ── AC 4: artifact edit happy path → 200 + checkpoint + file ──────────────────

def test_edit_scenario_returns_200_and_updates(client, tmp_path):
    _seed()
    g = _graph({"scenes": [_scene(narration="old")]})
    resp = client.patch("/runs/r1/stages/scenario/artifact", json={"body": "new text"})
    assert resp.status_code == 200
    assert resp.json()["updated"] is True
    values, as_node = g.updates[-1]
    assert as_node == "scenario"
    assert values["scenes"][0]["narration"] == "new text"
    written = (tmp_path / "r1" / "scenario" / "scene_001.txt").read_text()
    assert written == "new text"


def test_edit_subtitle_rewrites_srt_file(client, tmp_path):
    srt = tmp_path / "sub.srt"
    srt.write_text("old srt")
    _seed()
    _graph({"scenes": [_scene(subtitle=str(srt))]})
    resp = client.patch("/runs/r1/stages/subtitle/artifact",
                        json={"body": "1\n00:00:00,000 --> 00:00:01,000\nhi\n"})
    assert resp.status_code == 200
    assert srt.read_text().startswith("1\n")


# ── AC 5: artifact edit invalid stage → 422 ───────────────────────────────────

@pytest.mark.parametrize("stage", ["image", "tts", "video"])
def test_edit_invalid_stage_422(client, stage):
    _seed()
    _graph({"scenes": [_scene()]})
    resp = client.patch(f"/runs/r1/stages/{stage}/artifact", json={"body": "x"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Artifact editing is only supported for scenario and subtitle stages"


# ── AC 6: artifact edit not found ─────────────────────────────────────────────

def test_edit_unknown_run_404(client):
    _graph({"scenes": [_scene()]})
    resp = client.patch("/runs/nope/stages/scenario/artifact", json={"body": "x"})
    assert resp.status_code == 404


def test_edit_stage_not_yet_run_404(client):
    _seed()
    _graph({"scenes": []})  # scenario has not run
    resp = client.patch("/runs/r1/stages/scenario/artifact", json={"body": "x"})
    assert resp.status_code == 404


# ── AC 7: retry cascade nullification ─────────────────────────────────────────

def test_retry_scenario_cascade_clears_downstream(client):
    _seed(gate_states={"scenario": "approved"})
    g = _graph({
        "scenes": [_scene()], "video_path": "/tmp/out.mp4",
        "gate_states": {"scenario": "approved", "video": "approved"},
    })
    client.post("/runs/r1/stages/scenario/retry")
    values, as_node = g.updates[-1]
    # retry re-enters via the stage's predecessor so the stage node actually re-runs (AD-9)
    assert as_node == run_service._RETRY_ENTRY["scenario"]
    assert values["scenes"] == []
    assert values["video_path"] is None
    assert all(v == "pending" for v in values["gate_states"].values())


def test_retry_image_cascade_clears_paths(client):
    _seed(gate_states={"image": "approved"})
    g = _graph({"scenes": [_scene()], "video_path": "/tmp/out.mp4"})
    client.post("/runs/r1/stages/image/retry")
    values, _ = g.updates[-1]
    shot = values["scenes"][0]["shots"][0]
    assert shot["image_path"] is None
    assert shot["background_path"] is None
    assert shot["character_path"] is None
    assert values["scenes"][0]["audio_path"] is None
    assert values["scenes"][0]["subtitle_path"] is None
    assert values["video_path"] is None
