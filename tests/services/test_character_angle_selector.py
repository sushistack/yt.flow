"""Unit tests for CharacterService.select_character_angles (Story 1.13).

AC 1: LLM angle selection per shot
AC 3: Fallback to "front" on LLM failure
AC 4: Scene-level batch call — single LLM call for all shots
AC 5: Skip shots where character_path is None
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session

from yt_flow import db
from yt_flow.db.models import Character as CharacterModel
from yt_flow.services.character_service import CharacterService


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _init_db():
    db.init("sqlite://")


@pytest.fixture
def session():
    from yt_flow.db import _engine
    with Session(_engine) as s:
        yield s


@pytest.fixture
def service(session):
    return CharacterService(session)


def _seed_character(service, scp_id="SCP-096", **angles):
    """Create a character with specified angle paths. Defaults all 4 angles."""
    c = service.create_character(scp_id, f"Character {scp_id}")
    paths = {
        "angle_front_path": "/tmp/front.png",
        "angle_back_path": "/tmp/back.png",
        "angle_side_path": "/tmp/side.png",
        "angle_three_quarter_path": "/tmp/three_quarter.png",
        **angles,
    }
    # Update with angle paths — use setattr directly since update_character
    # whitelist includes angle_*_path fields
    for k, v in paths.items():
        setattr(c, k, v)
    from datetime import datetime, timezone
    c.updated_at = datetime.now(tz=timezone.utc).isoformat()
    session = service._session
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def _scene(num, narration="narration text", shots=None):
    return {
        "scene_num": num,
        "narration": narration,
        "shots": shots or [_shot("S001", num)],
        "audio_path": None,
        "audio_duration": 2.0,
        "word_timings": [],
        "subtitle_path": None,
    }


def _shot(shot_id, scene_num=1, *, character_path="/tmp/char.png",
          camera_angle=None, camera_movement=None):
    return {
        "shot_id": shot_id,
        "sentence_indices": [0],
        "image_prompt": "prompt",
        "negative_prompt": "",
        "camera_angle": camera_angle,
        "camera_movement": camera_movement,
        "image_path": "/tmp/img.png",
        "background_path": "/tmp/bg.png",
        "character_path": character_path,
    }


# ── Mock helpers ──────────────────────────────────────────────────────────────


def _mock_llm_response(angles: list[dict]) -> dict:
    """Return a mock httpx response that returns a JSON array of angle assignments."""
    class _FakeResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "choices": [{
                    "message": {"content": json.dumps(angles)},
                }],
            }
    return _FakeResponse()


def _mock_llm_error() -> dict:
    """Return a mock that raises on the HTTP call."""
    class _FakeResponse:
        def raise_for_status(self):
            from httpx import HTTPStatusError
            raise HTTPStatusError("server error", request=None, response=None)  # type: ignore[arg-type]
    return _FakeResponse()


# ── Tests ────────────────────────────────────────────────────────────────────


class TestAngleSelectionNoCharacter:
    """AC: Returns None when no Character exists for the SCP ID."""

    @pytest.mark.asyncio
    async def test_no_character_returns_none(self, service):
        scenes = [_scene(1)]
        result = await service.select_character_angles("SCP-000", scenes)
        assert result is None

    @pytest.mark.asyncio
    async def test_character_exists_no_angle_paths_returns_none(self, service):
        # Create character with no angle paths set
        c = service.create_character("SCP-096", "Shy Guy")
        # All angle_*_path are None by default
        scenes = [_scene(1)]
        result = await service.select_character_angles("SCP-096", scenes)
        assert result is None


class TestAngleSelectionHappyPath:
    """AC 1: LLM selects angles, validated and returned."""

    @pytest.mark.asyncio
    async def test_selects_angle_for_single_shot(self, service):
        _seed_character(service, "SCP-096")
        scenes = [_scene(1, "The creature emerges from the shadows")]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "back"},
            ])
            result = await service.select_character_angles("SCP-096", scenes)

        assert result is not None
        assert result["1:S001"]["angle"] == "back"
        assert result["1:S001"]["path"] == "/tmp/back.png"
        assert mock_post.call_count == 1  # AC4: single LLM call

    @pytest.mark.asyncio
    async def test_scene_level_batch_single_call(self, service):
        """AC4: Multiple shots across scenes → single LLM call."""
        _seed_character(service, "SCP-096")
        scenes = [
            _scene(1, "Scene one", [
                _shot("S001", 1),
                _shot("S002", 1),
            ]),
            _scene(2, "Scene two", [
                _shot("S001", 2),
            ]),
        ]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "front"},
                {"scene_num": 1, "shot_id": "S002", "angle": "side"},
                {"scene_num": 2, "shot_id": "S001", "angle": "three_quarter"},
            ])
            result = await service.select_character_angles("SCP-096", scenes)

        assert mock_post.call_count == 1  # AC4: single LLM call
        assert result is not None
        assert result["1:S001"]["angle"] == "front"
        assert result["1:S001"]["fallback"] is False  # legit LLM pick, not a fallback
        assert result["1:S002"]["angle"] == "side"
        assert result["2:S001"]["angle"] == "three_quarter"
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_skips_shots_without_character_path(self, service):
        """AC5: Shots with character_path=None are excluded from analysis."""
        _seed_character(service, "SCP-096")
        scenes = [
            _scene(1, "Scene one", [
                _shot("S001", 1, character_path="/tmp/char.png"),
                _shot("S002", 1, character_path=None),  # background-only shot
            ]),
        ]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "front"},
            ])
            result = await service.select_character_angles("SCP-096", scenes)

        assert mock_post.call_count == 1
        assert result is not None
        assert "1:S001" in result
        assert "1:S002" not in result  # AC5: skipped

    @pytest.mark.asyncio
    async def test_all_shots_character_path_none_returns_empty(self, service):
        """AC5: All shots skipped → empty result, no LLM call."""
        _seed_character(service, "SCP-096")
        scenes = [
            _scene(1, "Scene one", [
                _shot("S001", 1, character_path=None),
                _shot("S002", 1, character_path=None),
            ]),
        ]

        result = await service.select_character_angles("SCP-096", scenes)
        assert result == {}


class TestAngleSelectionFallback:
    """AC 3: Fallback to "front" on LLM failure, invalid angle, or parsing error."""

    @pytest.mark.asyncio
    async def test_llm_http_failure_fallback_to_front(self, service):
        _seed_character(service, "SCP-096")
        scenes = [_scene(1, "Scene text", [_shot("S001", 1)])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_error()
            result = await service.select_character_angles("SCP-096", scenes)

        assert result is not None
        assert result["1:S001"]["angle"] == "front"
        # AC3: the fallback must resolve to a usable front asset path, not empty
        assert result["1:S001"]["path"] == "/tmp/front.png"
        assert result["1:S001"]["fallback"] is True

    @pytest.mark.asyncio
    async def test_invalid_json_response_fallback_to_front(self, service):
        _seed_character(service, "SCP-096")
        scenes = [_scene(1, "Scene text", [_shot("S001", 1)])]

        class _FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return {"choices": [{"message": {"content": "not json at all!!"}}]}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _FakeResponse()
            result = await service.select_character_angles("SCP-096", scenes)

        assert result is not None
        assert result["1:S001"]["angle"] == "front"
        # AC3: the fallback must resolve to a usable front asset path, not empty
        assert result["1:S001"]["path"] == "/tmp/front.png"
        assert result["1:S001"]["fallback"] is True

    @pytest.mark.asyncio
    async def test_invalid_angle_name_fallback_to_front(self, service):
        _seed_character(service, "SCP-096")
        scenes = [_scene(1, "Scene text", [_shot("S001", 1)])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "DIAGONAL_WEIRD"},
            ])
            result = await service.select_character_angles("SCP-096", scenes)

        assert result is not None
        assert result["1:S001"]["angle"] == "front"
        # AC3: the fallback must resolve to a usable front asset path, not empty
        assert result["1:S001"]["path"] == "/tmp/front.png"
        assert result["1:S001"]["fallback"] is True

    @pytest.mark.asyncio
    async def test_non_array_response_fallback_to_front(self, service):
        _seed_character(service, "SCP-096")
        scenes = [_scene(1, "Scene text", [_shot("S001", 1)])]

        class _FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return {"choices": [{"message": {"content": '{"key": "value"}'}}]}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _FakeResponse()
            result = await service.select_character_angles("SCP-096", scenes)

        assert result is not None
        assert result["1:S001"]["angle"] == "front"
        # AC3: the fallback must resolve to a usable front asset path, not empty
        assert result["1:S001"]["path"] == "/tmp/front.png"
        assert result["1:S001"]["fallback"] is True

    @pytest.mark.asyncio
    async def test_missing_shots_filled_with_front_fallback(self, service):
        """Shots in catalogue but not in LLM response → filled with 'front'."""
        _seed_character(service, "SCP-096")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1),
            _shot("S002", 1),  # won't appear in LLM response
        ])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "back"},
            ])
            result = await service.select_character_angles("SCP-096", scenes)

        assert result is not None
        assert result["1:S001"]["angle"] == "back"
        assert result["1:S001"]["fallback"] is False  # clean LLM pick
        assert result["1:S002"]["angle"] == "front"  # filled with fallback
        assert result["1:S002"]["path"] == "/tmp/front.png"  # usable path, not empty
        assert result["1:S002"]["fallback"] is True


class TestAngleSelectionWithPartialAngles:
    """Character only has some angles populated — fallback to available."""

    @pytest.mark.asyncio
    async def test_llm_selects_unavailable_angle_uses_first_available(self, service):
        _seed_character(service, "SCP-096",
                        angle_back_path=None,       # back not available
                        angle_side_path=None,       # side not available
                        )
        scenes = [_scene(1, "Scene", [_shot("S001", 1)])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "back"},  # LLM picks unavailable
            ])
            result = await service.select_character_angles("SCP-096", scenes)

        # Should fall back to first available (front or three_quarter)
        assert result is not None
        assert result["1:S001"]["angle"] in ("front", "three_quarter")


class TestAngleSelectionPromptContext:
    """LLM prompt includes scene context: narration, camera metadata."""

    @pytest.mark.asyncio
    async def test_prompt_includes_narration_and_camera_metadata(self, service):
        _seed_character(service, "SCP-096")
        scenes = [
            _scene(1, "The creature screams in agony", [
                _shot("S001", 1, camera_angle="low", camera_movement="zoom in"),
            ]),
        ]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "front"},
            ])
            await service.select_character_angles("SCP-096", scenes)

        call_args = mock_post.call_args
        # The prompt should contain narration and camera metadata
        prompt_content = call_args[1]["json"]["messages"][0]["content"]
        assert "The creature screams in agony" in prompt_content
        assert "zoom in" in prompt_content
        assert "SCP-096" in prompt_content
