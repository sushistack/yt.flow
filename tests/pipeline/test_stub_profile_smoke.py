"""B-2 smoke test: drive the pipeline through the offline stub profile.

Two assertions of the frozen I/O matrix's "stubbed graph" row:
1. The full compiled graph reaches a terminal state (``complete``) via run_service
   with the four seams faked — zero real network/subprocess.
2. The real ``video_node`` (the one real seam reachable today) produces a tiny
   deterministic ``video.mp4`` artifact through ``fake_run_ffmpeg`` with no
   subprocess call.

SYS-E2E-001's full 5×-approve content assertions are QA's downstream task; B-2
only proves the seam is reusable and offline.
"""
import uuid

import pytest_asyncio
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Run
from yt_flow.pipeline.nodes import video as video_node_mod
from yt_flow.services import run_service


@pytest_asyncio.fixture
async def graph_env(tmp_path, monkeypatch):
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "ws"))
    db.init("sqlite://")
    settings = Settings(
        langfuse_host="http://localhost",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        db_path=str(tmp_path / "cp.db"),
    )
    saver = await run_service.init(settings)
    yield tmp_path
    await saver.conn.close()
    run_service._graph = None
    run_service._configs.clear()
    db._engine = None


async def test_graph_reaches_terminal_state(graph_env, stub_profile):
    """Full approval cycle → run status 'complete', no real external calls."""
    run_id = str(uuid.uuid4())
    with Session(db._engine) as session:
        session.add(Run(id=run_id, scp_id="SCP-096", status="running"))
        session.commit()

    await run_service.start_run(run_id, "SCP-096", "scp text", None)
    for stage in ("scenario", "image", "tts", "subtitle", "video"):
        await run_service.resume_run(run_id, stage, "approve", None)

    with Session(db._engine) as session:
        run = session.get(Run, run_id)
    assert run.status == "complete"  # terminal state reached


async def test_video_node_emits_tiny_artifact(graph_env, stub_profile, monkeypatch):
    """The real video seam produces a tiny video.mp4 via fake_run_ffmpeg (no subprocess)."""
    run_id = str(uuid.uuid4())
    ws = graph_env / "ws" / run_id
    (ws / "scenario").mkdir(parents=True, exist_ok=True)
    img = ws / "img.png"
    aud = ws / "audio.wav"
    srt = ws / "sub.srt"
    img.write_bytes(stub_profile.TINY_PNG)
    # tiny WAV + srt as fixture assets (video_node validates these exist on disk)
    import wave
    with wave.open(str(aud), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")

    state = {
        "run_id": run_id,
        "scp_text": "x",
        "scenes": [{
            "scene_num": 1,
            "narration": "hi",
            "audio_path": str(aud),
            "audio_duration": 1.0,
            "subtitle_path": str(srt),
            "word_timings": [],
            "shots": [{
                "shot_id": "S001", "sentence_indices": [0],
                "image_prompt": "p", "negative_prompt": "n",
                "image_path": str(img), "background_path": None, "character_path": None,
                "camera_angle": None, "camera_movement": None,
            }],
        }],
        "video_path": None,
        "current_stage": "",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }
    out = await video_node_mod.video_node(state)
    assert out.get("error") is None, out.get("error")
    from pathlib import Path
    assert Path(out["video_path"]).exists()  # tiny deterministic artifact on disk
