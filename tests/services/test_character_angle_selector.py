"""Unit tests for CharacterService.resolve_cast_cards (Story 1.13, reworked
in Story 8.3).

AC 1: LLM angle selection per shot — now scoped to shots whose cast contains
      the run's own entity (scp_id); other cast members skip the LLM entirely.
AC 3: Fallback to "front" on LLM failure
AC 4: Scene-level batch call — single LLM call for all entity shots
AC 5: Shots with an empty cast are excluded from the LLM catalogue and from
      the result; stock/derived cast members resolve deterministically.
Story 8.3 pose resolution: standing reads Character.angle_*_path, non-standing
reads the pose-keyed character_cards table with standing fallback.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session

from yt_flow import db
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


def _cast_member(card_key="SCP-096", *, position="center", depth="near", pose="standing"):
    return {"card_key": card_key, "position": position, "depth": depth, "pose": pose}


def _shot(shot_id, scene_num=1, *, cast=None,
          camera_angle=None, camera_movement=None):
    return {
        "shot_id": shot_id,
        "sentence_indices": [0],
        "image_prompt": "prompt",
        "negative_prompt": "",
        "camera_angle": camera_angle,
        "camera_movement": camera_movement,
        "image_path": "/tmp/img.png",
        "cast": [_cast_member()] if cast is None else cast,
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


class TestResolveCastCardsNoCharacter:
    """No Character row for a cast member's card_key → that member is skipped."""

    @pytest.mark.asyncio
    async def test_no_character_returns_empty(self, service):
        scenes = [_scene(1)]
        result = await service.resolve_cast_cards("SCP-000", scenes)
        assert result == {}

    @pytest.mark.asyncio
    async def test_character_exists_no_angle_paths_returns_empty(self, service):
        service.create_character("SCP-096", "Shy Guy")  # all angle_*_path None
        scenes = [_scene(1)]
        result = await service.resolve_cast_cards("SCP-096", scenes)
        assert result == {}

    @pytest.mark.asyncio
    async def test_unseeded_card_key_skips_member_only(self, service):
        """A cast member whose card_key has no Character row is dropped; other
        members in the same shot still resolve (AD-10: degrade, don't fail)."""
        _seed_character(service, "SCP-096")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[
                _cast_member("SCP-096"),
                _cast_member("UNSEEDED-ENTITY", position="left"),
            ]),
        ])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "front"},
            ])
            result = await service.resolve_cast_cards("SCP-096", scenes)

        assert len(result["1:S001"]) == 1
        assert result["1:S001"][0]["card_key"] == "SCP-096"

    @pytest.mark.asyncio
    async def test_malformed_cast_member_skips_member_only(self, service):
        """Old/checkpoint-corrupt cast entries are dropped without losing valid overlays."""
        _seed_character(service, "STOCK-d-class")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[
                "not-a-dict",
                {"position": "left", "depth": "near", "pose": "standing"},
                _cast_member("STOCK-d-class"),
            ]),
        ])]

        result = await service.resolve_cast_cards("SCP-999", scenes)

        assert len(result["1:S001"]) == 1
        assert result["1:S001"][0]["card_key"] == "STOCK-d-class"


class TestResolveCastCardsHappyPath:
    """AC 1: LLM selects angles for entity shots, validated and returned."""

    @pytest.mark.asyncio
    async def test_selects_angle_for_single_shot(self, service):
        _seed_character(service, "SCP-096")
        scenes = [_scene(1, "The creature emerges from the shadows")]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "back"},
            ])
            result = await service.resolve_cast_cards("SCP-096", scenes)

        assert "1:S001" in result
        card = result["1:S001"][0]
        assert card["card_key"] == "SCP-096"
        assert card["angle"] == "back"
        assert card["path"] == "/tmp/back.png"
        assert card["pose"] == "standing"
        assert card["fallback"] is False
        assert mock_post.call_count == 1  # AC4: single LLM call

    @pytest.mark.asyncio
    async def test_scene_level_batch_single_call(self, service):
        """AC4: Multiple entity shots across scenes → single LLM call."""
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
            result = await service.resolve_cast_cards("SCP-096", scenes)

        assert mock_post.call_count == 1  # AC4: single LLM call
        assert result["1:S001"][0]["angle"] == "front"
        assert result["1:S001"][0]["fallback"] is False  # legit LLM pick, not a fallback
        assert result["1:S002"][0]["angle"] == "side"
        assert result["2:S001"][0]["angle"] == "three_quarter"
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_shots_with_empty_cast_are_excluded(self, service):
        """AC5: Shots with an empty cast never reach the LLM catalogue or the result."""
        _seed_character(service, "SCP-096")
        scenes = [
            _scene(1, "Scene one", [
                _shot("S001", 1),
                _shot("S002", 1, cast=[]),  # background-only shot
            ]),
        ]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "front"},
            ])
            result = await service.resolve_cast_cards("SCP-096", scenes)

        assert mock_post.call_count == 1
        assert "1:S001" in result
        assert "1:S002" not in result  # AC5: excluded

    @pytest.mark.asyncio
    async def test_all_shots_empty_cast_returns_empty_no_llm_call(self, service):
        """AC5: every shot's cast is empty → empty result, no LLM call."""
        _seed_character(service, "SCP-096")
        scenes = [
            _scene(1, "Scene one", [
                _shot("S001", 1, cast=[]),
                _shot("S002", 1, cast=[]),
            ]),
        ]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            result = await service.resolve_cast_cards("SCP-096", scenes)
            mock_post.assert_not_called()
        assert result == {}

    @pytest.mark.asyncio
    async def test_stock_member_resolves_to_front_without_llm_call(self, service):
        """AC5: stock/derived cast members never trigger an LLM call — deterministic front."""
        _seed_character(service, "STOCK-d-class")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member("STOCK-d-class", position="right", depth="mid")]),
        ])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            result = await service.resolve_cast_cards("SCP-999", scenes)  # not the run entity
            mock_post.assert_not_called()

        card = result["1:S001"][0]
        assert card["card_key"] == "STOCK-d-class"
        assert card["angle"] == "front"
        assert card["fallback"] is False
        assert card["position"] == "right"
        assert card["depth"] == "mid"

    @pytest.mark.asyncio
    async def test_stock_member_uses_available_angle_when_front_missing(self, service):
        """A partial stock row should still resolve instead of being skipped just
        because the deterministic front preference is unavailable."""
        _seed_character(
            service, "STOCK-d-class",
            angle_front_path=None,
            angle_three_quarter_path="/tmp/three_quarter.png",
            angle_side_path=None,
            angle_back_path=None,
        )
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member("STOCK-d-class")]),
        ])]

        result = await service.resolve_cast_cards("SCP-999", scenes)

        card = result["1:S001"][0]
        assert card["angle"] == "three_quarter"
        assert card["path"] == "/tmp/three_quarter.png"
        assert card["fallback"] is False


class TestResolveCastCardsFallback:
    """AC 3: Fallback to "front" on LLM failure, invalid angle, or parsing error."""

    @pytest.mark.asyncio
    async def test_llm_http_failure_fallback_to_front(self, service):
        _seed_character(service, "SCP-096")
        scenes = [_scene(1, "Scene text", [_shot("S001", 1)])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_error()
            result = await service.resolve_cast_cards("SCP-096", scenes)

        card = result["1:S001"][0]
        assert card["angle"] == "front"
        assert card["path"] == "/tmp/front.png"
        assert card["fallback"] is True

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
            result = await service.resolve_cast_cards("SCP-096", scenes)

        card = result["1:S001"][0]
        assert card["angle"] == "front"
        assert card["path"] == "/tmp/front.png"
        assert card["fallback"] is True

    @pytest.mark.asyncio
    async def test_invalid_angle_name_fallback_to_front(self, service):
        _seed_character(service, "SCP-096")
        scenes = [_scene(1, "Scene text", [_shot("S001", 1)])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_llm_response([
                {"scene_num": 1, "shot_id": "S001", "angle": "DIAGONAL_WEIRD"},
            ])
            result = await service.resolve_cast_cards("SCP-096", scenes)

        card = result["1:S001"][0]
        assert card["angle"] == "front"
        assert card["path"] == "/tmp/front.png"
        assert card["fallback"] is True

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
            result = await service.resolve_cast_cards("SCP-096", scenes)

        card = result["1:S001"][0]
        assert card["angle"] == "front"
        assert card["path"] == "/tmp/front.png"
        assert card["fallback"] is True

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
            result = await service.resolve_cast_cards("SCP-096", scenes)

        assert result["1:S001"][0]["angle"] == "back"
        assert result["1:S001"][0]["fallback"] is False  # clean LLM pick
        assert result["1:S002"][0]["angle"] == "front"  # filled with fallback
        assert result["1:S002"][0]["path"] == "/tmp/front.png"
        assert result["1:S002"][0]["fallback"] is True


class TestResolveCastCardsWithPartialAngles:
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
            result = await service.resolve_cast_cards("SCP-096", scenes)

        assert result["1:S001"][0]["angle"] in ("front", "three_quarter")


class TestResolveCastCardsPromptContext:
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
            await service.resolve_cast_cards("SCP-096", scenes)

        call_args = mock_post.call_args
        prompt_content = call_args[1]["json"]["messages"][0]["content"]
        assert "The creature screams in agony" in prompt_content
        assert "zoom in" in prompt_content
        assert "SCP-096" in prompt_content


class TestResolveCastCardsPose:
    """Story 8.3: pose-aware card resolution — standing vs character_cards lookup."""

    @pytest.mark.asyncio
    async def test_sitting_pose_hit_via_character_cards(self, service):
        _seed_character(service, "STOCK-d-class")
        service.save_card("STOCK-d-class", "sitting", "front", "/tmp/sit_front.png")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member("STOCK-d-class", pose="sitting")]),
        ])]

        result = await service.resolve_cast_cards("SCP-999", scenes)  # not the entity

        card = result["1:S001"][0]
        assert card["pose"] == "sitting"
        assert card["path"] == "/tmp/sit_front.png"
        assert card["fallback"] is False
        assert card["asset_fallback"] is False
        assert card["fallback_reason"] is None

    @pytest.mark.asyncio
    async def test_sitting_pose_miss_falls_back_to_standing(self, service):
        """No `sitting` row saved — falls back to the standing card, fallback=True."""
        _seed_character(service, "STOCK-d-class")  # no save_card call
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member("STOCK-d-class", pose="sitting")]),
        ])]

        result = await service.resolve_cast_cards("SCP-999", scenes)

        card = result["1:S001"][0]
        assert card["pose"] == "standing"
        assert card["path"] == "/tmp/front.png"
        assert card["fallback"] is True
        assert card["asset_fallback"] is True
        assert card["fallback_reason"] == "asset"

    @pytest.mark.asyncio
    async def test_unknown_pose_value_defaults_to_standing(self, service):
        """Interfaces: an old-checkpoint/malformed pose value maps defensively to standing."""
        _seed_character(service, "STOCK-d-class")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member("STOCK-d-class", pose="crouching")]),
        ])]

        result = await service.resolve_cast_cards("SCP-999", scenes)

        card = result["1:S001"][0]
        assert card["pose"] == "standing"
        assert card["path"] == "/tmp/front.png"
