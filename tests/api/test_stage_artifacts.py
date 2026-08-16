"""Tests for GET /runs/{id}/stages/{stage}/artifacts (Story 2.5 AC: 2-5).

The graph is mocked — no real LangGraph DB. We inject a run_service._graph whose
aget_state() returns a canned PipelineState.
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


def _scene(
    n, *, image=None, audio=None, subtitle=None, mood="escalation", include_mood=True,
    title="첫 면담", kicker="개체가 입을 열다", include_title_kicker=True,
    display_narration=None, include_display_narration=True,
    cast=None, include_cast=True,
    location_key=None, include_location_key=True,
):
    shot = {
        "shot_id": f"S00{n}",
        "sentence_indices": [0, 1],
        "image_prompt": "a dark corridor",
        "negative_prompt": "bright, daylight",
        "camera_angle": "medium",
        "camera_movement": "static",
        "image_path": image,
    }
    if include_cast:
        shot["cast"] = cast if cast is not None else []
    if include_location_key:
        shot["location_key"] = location_key
    scene = {
        "scene_num": n,
        "narration": f"narration {n}",
        "shots": [shot],
        "audio_path": audio,
        "audio_duration": 12.5 if audio else None,
        "word_timings": [],
        "subtitle_path": subtitle,
    }
    if include_mood:
        scene["mood"] = mood
    if include_title_kicker:
        scene["title"] = title
        scene["kicker"] = kicker
    if include_display_narration:
        scene["display_narration"] = display_narration or f"display {n}"
    return scene


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
    monkeypatch.setattr(run_service, "_graph", graph)


# ── AC 2: per-stage artifact data read from checkpoint ──────────────────────

def test_scenario_artifacts(client, monkeypatch):
    _mock_graph(monkeypatch, _COMPLETE)
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["stage"] == "scenario"
    assert body["scenes"][0]["narration"] == "narration 1"
    assert body["scenes"][0]["shots"][0]["shot_id"] == "S001"
    assert body["scenes"][0]["mood"] == "escalation"


def test_scenario_artifacts_pre_7_1_checkpoint_mood_is_null(client, monkeypatch):
    _mock_graph(monkeypatch, _state([_scene(1, include_mood=False)]))
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenes"][0]["mood"] is None


def test_scenario_artifacts_includes_title_and_kicker(client, monkeypatch):
    """[Story 5.17 AC:9] title/kicker are exposed so the reviewer vets card text
    at the scenario gate."""
    _mock_graph(monkeypatch, _COMPLETE)
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenes"][0]["title"] == "첫 면담"
    assert body["scenes"][0]["kicker"] == "개체가 입을 열다"


def test_scenario_artifacts_pre_5_17_checkpoint_title_and_kicker_default_empty(client, monkeypatch):
    """[Story 5.17 AC:9] Old checkpoints without title/kicker keys are safe — "",
    matching the checkpoint-tolerant artifact precedent, not a KeyError."""
    _mock_graph(monkeypatch, _state([_scene(1, include_title_kicker=False)]))
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenes"][0]["title"] == ""
    assert body["scenes"][0]["kicker"] == ""


def test_scenario_artifacts_includes_display_narration(client, monkeypatch):
    """[Story 5.18 AC:8] display_narration exposed so the reviewer can diff
    spoken vs display text at the gate."""
    _mock_graph(monkeypatch, _state([_scene(1, display_narration="원문 1")]))
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenes"][0]["display_narration"] == "원문 1"
    assert body["scenes"][0]["narration"] == "narration 1"


def test_scenario_artifacts_pre_5_18_checkpoint_display_narration_falls_back_to_narration(client, monkeypatch):
    """Old checkpoints without display_narration: falls back to narration, not a KeyError."""
    _mock_graph(monkeypatch, _state([_scene(1, include_display_narration=False)]))
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenes"][0]["display_narration"] == "narration 1"


def test_scenario_artifacts_includes_cast(client, monkeypatch):
    """[Story 8.1 AC:7] cast is exposed at the scenario gate so a human reviewer
    can see per-shot cast placement, not just image_prompt — the D2 mistake
    (mood silently dropped by the serializer) must not repeat here."""
    cast = [{
        "card_key": "SCP-049",
        "position": "left",
        "depth": "near",
        "pose": "standing",
        "pose_hint": "kneeling over a corpse",
    }]
    _mock_graph(monkeypatch, _state([_scene(1, cast=cast)]))
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenes"][0]["shots"][0]["cast"] == cast


def test_scenario_artifacts_pre_8_1_checkpoint_cast_defaults_empty(client, monkeypatch):
    """Old checkpoints without a cast key: defaults to [], not a KeyError (AC:6)."""
    _mock_graph(monkeypatch, _state([_scene(1, include_cast=False)]))
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenes"][0]["shots"][0]["cast"] == []


def test_scenario_artifacts_includes_location_key(client, monkeypatch):
    """[Story 8.5 AC:8] location_key is exposed at the scenario gate so a human
    reviewer can see which shots use a STOCK plate before approving."""
    _mock_graph(monkeypatch, _state([_scene(1, location_key="corridor")]))
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenes"][0]["shots"][0]["location_key"] == "corridor"


def test_scenario_artifacts_pre_8_5_checkpoint_location_key_defaults_null(client, monkeypatch):
    """Old checkpoints without a location_key key: defaults to null, not a KeyError."""
    _mock_graph(monkeypatch, _state([_scene(1, include_location_key=False)]))
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenes"][0]["shots"][0]["location_key"] is None


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
    # Story 13.1: `warnings` is on every stage DTO, `[]` for a legacy/clean checkpoint.
    assert body == {"stage": "video", "video_path": "workspace/x/output.mp4", "warnings": []}


def test_video_artifacts_ending_credit_success(client, monkeypatch):
    """[Story 5.20 AC:6] cc_attribution was on and the card succeeded — the checkpoint's
    ending_credit_error=None surfaces as ending_credit=True + the expected description
    path (even though get_stage_artifacts never touches the filesystem for it)."""
    state = {**_COMPLETE, "ending_credit_error": None}
    _mock_graph(monkeypatch, state)
    body = client.get(f"/runs/{RUN_ID}/stages/video/artifacts").json()
    assert body["ending_credit"] is True
    assert body["ending_credit_error"] is None
    assert body["description_txt_path"] == f"workspace/{RUN_ID}/description.txt"


def test_video_artifacts_ending_credit_failure(client, monkeypatch):
    """A non-fatal card failure surfaces ending_credit=False + the error message,
    while video_path/status stay unaffected (AC:5)."""
    state = {**_COMPLETE, "ending_credit_error": "FFmpeg chapter card 0 failed (rc=1): boom"}
    _mock_graph(monkeypatch, state)
    body = client.get(f"/runs/{RUN_ID}/stages/video/artifacts").json()
    assert body["ending_credit"] is False
    assert body["ending_credit_error"] == "FFmpeg chapter card 0 failed (rc=1): boom"


def test_video_artifacts_no_ending_credit_fields_when_not_attempted(client, monkeypatch):
    """cc_attribution was off for this run — no ending_credit_error key in the
    checkpoint at all, so none of the attribution fields appear."""
    _mock_graph(monkeypatch, _COMPLETE)
    body = client.get(f"/runs/{RUN_ID}/stages/video/artifacts").json()
    assert "ending_credit" not in body
    assert "description_txt_path" not in body


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


# ── Story 12.3: scenario_quality on the artifact endpoint (AC6) ───────────────

_QUALITY = {
    "final_pass_index": 2,
    "retry_scope": "scene",
    "review_overall_pass": False,
    "critic_verdict": "retry",
    "critic_feedback": "장면 2가 늘어집니다",
    "rule_metrics": {
        "aggregate": {"character_count": 120, "sentence_count": 8,
                      "duplicate_sentence_count": 1, "repeated_4gram_count": 0},
        "scenes": [{"scene_num": 1, "character_count": 120, "sentence_count": 8,
                    "duplicate_sentence_count": 1, "repeated_4gram_count": 0}],
        "repeated_ngrams": [{"phrase": "가 나 다 라", "count": 3}],
        "slop_phrase_hits": [{"scene_num": 1, "phrase": "충격적인 사실", "count": 2}],
        "slop_vocabulary_version": 1,
    },
    "grounded_contradictions": [{
        "scene_num": 1, "narration_quote": "파란 눈", "grounding_source": "entity_sheet",
        "grounding_quote": "눈은 검은색이다", "explanation": "반대다", "correction": "검은 눈",
        # Story 12.8: stamped in code, not by a judge — the UI renders it beside the scene.
        "origin": "outline",
    }],
    "review_issues": [],
    "outline_grounding": [{"scene_num": 4, "code": "hedge_dropped", "detail": "appears fused"}],
    "warning": {
        "code": "unresolved_pass2", "message": "확인 후 승인하세요",
        "outline_originated": {"scenes": [1, 4], "note": "씬 리페어로는 고칠 수 없습니다"},
    },
}


def test_scenario_artifacts_carry_quality_warning(client, monkeypatch):
    _mock_graph(monkeypatch, {**_SCENARIO_ONLY, "scenario_quality": _QUALITY})
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenario_quality"]["warning"]["code"] == "unresolved_pass2"
    assert body["scenario_quality"]["grounded_contradictions"][0]["grounding_quote"] == "눈은 검은색이다"
    assert body["scenario_quality"]["rule_metrics"]["slop_phrase_hits"][0]["count"] == 2
    assert body["scenes"][0]["narration"] == "narration 1"  # existing payload intact


def test_scenario_artifacts_carry_the_outline_attribution(client, monkeypatch):
    """Story 12.8: `origin`, `outline_grounding` and `warning.outline_originated` are
    what tell the operator the scene repair could not have fixed this. If the
    serializer drops them the gate is back to a single undifferentiated warning."""
    _mock_graph(monkeypatch, {**_SCENARIO_ONLY, "scenario_quality": _QUALITY})
    quality = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()["scenario_quality"]
    assert quality["grounded_contradictions"][0]["origin"] == "outline"
    assert quality["outline_grounding"] == [
        {"scene_num": 4, "code": "hedge_dropped", "detail": "appears fused"}
    ]
    assert quality["warning"]["outline_originated"]["scenes"] == [1, 4]


def test_scenario_artifacts_pre_12_3_checkpoint_quality_is_null(client, monkeypatch):
    _mock_graph(monkeypatch, _SCENARIO_ONLY)  # no such key at all
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenario_quality"] is None


def test_scenario_artifacts_cleared_quality_is_null(client, monkeypatch):
    _mock_graph(monkeypatch, {**_SCENARIO_ONLY, "scenario_quality": None})
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert body["scenario_quality"] is None


def test_clean_run_scenario_artifacts_have_no_warning(client, monkeypatch):
    clean = {k: v for k, v in _QUALITY.items() if k != "warning"}
    clean.update(final_pass_index=1, retry_scope="none", review_overall_pass=True,
                 critic_verdict="pass", grounded_contradictions=[])
    _mock_graph(monkeypatch, {**_SCENARIO_ONLY, "scenario_quality": clean})
    body = client.get(f"/runs/{RUN_ID}/stages/scenario/artifacts").json()
    assert "warning" not in body["scenario_quality"]


def test_other_stage_artifacts_do_not_gain_quality(client, monkeypatch):
    _mock_graph(monkeypatch, {**_COMPLETE, "scenario_quality": _QUALITY})
    for stage in ("image", "tts", "subtitle", "video"):
        body = client.get(f"/runs/{RUN_ID}/stages/{stage}/artifacts").json()
        assert "scenario_quality" not in body
