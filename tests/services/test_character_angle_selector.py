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
from yt_flow.services.character_service import CharacterService, pose_hint_key


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


def _cast_member(
    card_key="SCP-096", *, position="center", depth="near", pose="standing",
    motion_style=None, motion_energy=None, pose_hint=None,
    movement_mode=None, movement_direction=None, movement_pace=None,
):
    member = {"card_key": card_key, "position": position, "depth": depth, "pose": pose}
    if pose_hint is not None:
        member["pose_hint"] = pose_hint
    if motion_style is not None:
        member["motion_style"] = motion_style
    if motion_energy is not None:
        member["motion_energy"] = motion_energy
    if movement_mode is not None:
        member["movement_mode"] = movement_mode
    if movement_direction is not None:
        member["movement_direction"] = movement_direction
    if movement_pace is not None:
        member["movement_pace"] = movement_pace
    return member


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
    async def test_derived_entity_key_resolves_once_character_row_exists(self, service):
        """Story 8.13 AC6: `check_existing_character`/card resolution are data-driven
        on card_key — a `<scp_id>-<n>` derived key needs no special-casing here,
        it resolves exactly like any other non-entity card_key once a Character
        row exists for it (e.g. via on-demand generation)."""
        _seed_character(service, "SCP-049-2")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member("SCP-049-2", position="left", depth="far")]),
        ])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            result = await service.resolve_cast_cards("SCP-049", scenes)  # not the run entity itself
            mock_post.assert_not_called()

        card = result["1:S001"][0]
        assert card["card_key"] == "SCP-049-2"
        assert card["angle"] == "front"
        assert card["fallback"] is False

    @pytest.mark.asyncio
    async def test_card_defaults_motion_fields_when_member_omits_them(self, service):
        """Story 8.8: same default-on-missing convention as position/depth."""
        _seed_character(service, "STOCK-d-class")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member("STOCK-d-class")]),
        ])]

        result = await service.resolve_cast_cards("SCP-999", scenes)

        card = result["1:S001"][0]
        assert card["motion_style"] == "breath"
        assert card["motion_energy"] == "medium"

    @pytest.mark.asyncio
    async def test_card_carries_explicit_motion_fields(self, service):
        """Story 8.8: a parser-normalized motion_style/motion_energy passes through."""
        _seed_character(service, "STOCK-d-class")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member(
                "STOCK-d-class", motion_style="tremble", motion_energy="high",
            )]),
        ])]

        result = await service.resolve_cast_cards("SCP-999", scenes)

        card = result["1:S001"][0]
        assert card["motion_style"] == "tremble"
        assert card["motion_energy"] == "high"

    @pytest.mark.asyncio
    async def test_card_defaults_movement_fields_when_member_omits_them(self, service):
        """Story 8.9: same default-on-missing convention as motion_style/motion_energy."""
        _seed_character(service, "STOCK-d-class")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member("STOCK-d-class")]),
        ])]

        result = await service.resolve_cast_cards("SCP-999", scenes)

        card = result["1:S001"][0]
        assert card["movement_mode"] == "anchored"
        assert card["movement_direction"] == "none"
        assert card["movement_pace"] == "slow"

    @pytest.mark.asyncio
    async def test_card_carries_explicit_movement_fields(self, service):
        """Story 8.9: a parser-normalized movement_mode/direction/pace passes
        through resolve_cast_cards to reach video_node's filtergraph — this
        was previously dropped (movement fields weren't copied at all), so
        every real run silently rendered as movement_mode="anchored"."""
        _seed_character(service, "STOCK-d-class")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member(
                "STOCK-d-class", movement_mode="enter",
                movement_direction="left", movement_pace="medium",
            )]),
        ])]

        result = await service.resolve_cast_cards("SCP-999", scenes)

        card = result["1:S001"][0]
        assert card["movement_mode"] == "enter"
        assert card["movement_direction"] == "left"
        assert card["movement_pace"] == "medium"

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


class TestResolveCastCardsSpecialPose:
    """Story 8.4: pose_hint cards resolve before base-pose angle selection."""

    @pytest.mark.asyncio
    async def test_pose_hint_hit_uses_hint_card_and_skips_llm(self, service):
        _seed_character(service, "SCP-096")
        hint = "kneeling over a corpse"
        service.save_card("SCP-096", pose_hint_key(hint), "front", "/tmp/hint_front.png")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member("SCP-096", pose_hint=hint)]),
        ])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            result = await service.resolve_cast_cards("SCP-096", scenes)

        assert mock_post.call_count == 0
        card = result["1:S001"][0]
        assert card["pose"] == pose_hint_key(hint)
        assert card["angle"] == "front"
        assert card["path"] == "/tmp/hint_front.png"
        assert card["fallback"] is False

    @pytest.mark.asyncio
    async def test_pose_hint_hit_still_carries_movement_fields(self, service):
        """Story 8.9: the pose_hint branch is a separate code path from the
        base-pose branch and must copy movement_* the same way (both branches
        previously dropped movement_* entirely)."""
        _seed_character(service, "SCP-096")
        hint = "kneeling over a corpse"
        service.save_card("SCP-096", pose_hint_key(hint), "front", "/tmp/hint_front.png")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member(
                "SCP-096", pose_hint=hint,
                movement_mode="approach", movement_direction="in", movement_pace="fast",
            )]),
        ])]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock):
            result = await service.resolve_cast_cards("SCP-096", scenes)

        card = result["1:S001"][0]
        assert card["movement_mode"] == "approach"
        assert card["movement_direction"] == "in"
        assert card["movement_pace"] == "fast"

    @pytest.mark.asyncio
    async def test_pose_hint_miss_falls_back_to_base_pose_with_warning(self, service, caplog):
        _seed_character(service, "STOCK-d-class")
        scenes = [_scene(1, "Scene", [
            _shot("S001", 1, cast=[_cast_member("STOCK-d-class", pose_hint="reaching toward camera")]),
        ])]

        with caplog.at_level("WARNING"):
            result = await service.resolve_cast_cards("SCP-999", scenes)

        card = result["1:S001"][0]
        assert card["pose"] == "standing"
        assert card["path"] == "/tmp/front.png"
        assert "special-pose card" in caplog.text
