"""Unit tests for src/yt_flow/services/vision_check.py (Story 10.2).

The detector's whole contract is "answer bool, or answer None, but never raise":
image_node treats it as an oracle it can safely ignore, so every failure mode
below must come back as ``None`` rather than as an exception or a coerced
verdict. No live DashScope — ``httpx.AsyncClient.post`` is patched.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from yt_flow.services import vision_check

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeSettings:
    def __init__(self, key="vision-key"):
        self.character_vision_api_key = key
        self.character_vision_model = "qwen-vl-plus"
        self.character_vision_max_tokens = 2000


def _reply(content: str):
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
        request=httpx.Request("POST", "http://vision.test"),
    )


async def _check(content: str, settings=None, image=PNG):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _reply(content)
        return await vision_check.background_has_person(image, settings or FakeSettings())


@pytest.mark.asyncio
@pytest.mark.parametrize("content,expected", [
    ('{"has_person": true, "notes": "a face fills the frame"}', True),
    ('{"has_person": false, "notes": "empty corridor"}', False),
])
async def test_happy_path_returns_the_boolean(content, expected):
    assert await _check(content) is expected


@pytest.mark.asyncio
async def test_missing_key_is_undecidable_and_makes_no_call():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        result = await vision_check.background_has_person(PNG, FakeSettings(key=""))
    assert result is None
    post.assert_not_called()


@pytest.mark.asyncio
async def test_http_error_is_undecidable_not_raised():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.side_effect = httpx.ConnectError("dashscope down")
        assert await vision_check.background_has_person(PNG, FakeSettings()) is None


@pytest.mark.asyncio
async def test_non_2xx_is_undecidable_not_raised():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = httpx.Response(429, request=httpx.Request("POST", "http://vision.test"))
        assert await vision_check.background_has_person(PNG, FakeSettings()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    '```json\n{"has_person": true}\n```',
    'Sure! Here is the verdict:\n{"has_person": true}\nHope that helps.',
])
async def test_fenced_and_prose_wrapped_json_is_parsed(content):
    """Qwen-VL fences or prefaces its JSON; the brace slice is why that is fine."""
    assert await _check(content) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    "there is definitely a person in this image",  # no JSON at all
    '{"has_person": "yes"}',                        # string, must not be coerced
    '{"has_person": 1}',                            # int, must not be coerced
    '{"has_person": null}',
    '{"notes": "forgot the field"}',
    '{"has_person": true',                          # truncated → JSONDecodeError
    '["has_person"]',                               # JSON, but not an object
])
async def test_undecidable_replies_return_none(content):
    assert await _check(content) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("image", ["not bytes", None, 42])
async def test_non_bytes_input_is_undecidable_not_raised(image):
    """The base64 encode sits inside the try precisely so this cannot escape."""
    assert await _check('{"has_person": false}', image=image) is None


@pytest.mark.asyncio
async def test_broken_settings_object_is_undecidable_not_raised():
    """Even the API-key read is inside the try — nothing about this call may raise."""
    class Exploding:
        @property
        def character_vision_api_key(self):
            raise RuntimeError("settings blew up")

    assert await vision_check.background_has_person(PNG, Exploding()) is None


@pytest.mark.asyncio
async def test_request_mirrors_the_dashscope_call_shape():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _reply('{"has_person": false}')
        await vision_check.background_has_person(PNG, FakeSettings())
    (url,), kwargs = post.call_args
    assert url == vision_check._DASHSCOPE_VISION_ENDPOINT
    assert kwargs["headers"]["Authorization"] == "Bearer vision-key"
    assert kwargs["json"]["model"] == "qwen-vl-plus"
    content = kwargs["json"]["messages"][0]["content"]
    assert content[0]["text"] == vision_check.CHECK_PROMPT
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_prompt_excludes_depicted_humans():
    """The runtime question is collision with a body, not "is a human depicted" —
    SCP set dressing is full of diagrams, posters and skulls."""
    prompt = vision_check.CHECK_PROMPT.lower()
    for excluded in ("diagram", "poster", "statue", "mannequin", "skull", "painting"):
        assert excluded in prompt


def test_prompt_states_one_rule_not_two_competing_ones():
    """The first draft called a "silhouette" a person AND called "a shadow with no
    body casting it" not a person, with no way to tell them apart. One rule now:
    is a real body occupying space in the frame."""
    prompt = vision_check.CHECK_PROMPT.lower()
    assert "silhouette" not in prompt
    assert "body occupying space" in prompt
    assert "outside the frame" in prompt  # the shadow/reflection case, decidable now


@pytest.mark.asyncio
async def test_request_pins_temperature_zero():
    """Story 11.1 keeps renders seed-deterministic; a sampled judge would make
    *which* rung is accepted a coin flip on replay."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _reply('{"has_person": false}')
        await vision_check.background_has_person(PNG, FakeSettings())
    assert post.call_args.kwargs["json"]["temperature"] == 0


def test_endpoint_matches_character_services_definition():
    """The URL is duplicated on purpose (importing it drags the DB layer into
    pipeline/), so a test — not an import — keeps the two copies equal."""
    from yt_flow.services.character_service import _DASHSCOPE_VISION_ENDPOINT as ANCHOR
    assert vision_check._DASHSCOPE_VISION_ENDPOINT == ANCHOR


@pytest.mark.asyncio
async def test_the_models_note_is_logged_beside_the_verdict(caplog):
    """Story 14.4. `notes` was already in every reply and thrown away at the parse, so
    the one description of what is actually IN the frame never reached a log line — run
    4b35c0ed's `S00201` framed anime portrait was in the detector's own note and we had
    n=1 as a result. The verdict and the signature are unchanged; only the log grew.
    """
    with caplog.at_level("INFO", logger=vision_check.__name__):
        assert await _check('{"has_person": false, "notes": "a framed anime portrait"}') is False
    assert "a framed anime portrait" in caplog.text
    assert "has_person=False" in caplog.text


@pytest.mark.asyncio
async def test_a_reply_without_notes_still_returns_its_verdict():
    """The note is a log line, never a required field: a reply that omits it must not
    become undecidable (`None` means "not checked" and costs the caller a warning)."""
    assert await _check('{"has_person": true}') is True


# ── Story 14.2: the affordance question ─────────────────────────────────────

async def _standing(content, settings=None, image=PNG):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _reply(content)
        return await vision_check.plate_has_standing_room(image, settings or FakeSettings())


@pytest.mark.asyncio
@pytest.mark.parametrize("content,expected", [
    ('{"standing_room": true, "floor_fraction": 0.8, "reason": "wide flat floor"}', True),
    ('{"standing_room": false, "floor_fraction": 0.0, "reason": "macro of a tray"}', False),
    # The four other fields of the shared schema are for the offline report; the runtime
    # reads `standing_room` and nothing else, so a reply carrying only it still decides.
    ('{"standing_room": false}', False),
])
async def test_standing_room_verdicts_are_returned(content, expected):
    assert await _standing(content) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    "there is nowhere to stand in this shot",   # no JSON at all
    '{"standing_room": "no"}',                  # string, must not be coerced
    '{"standing_room": 0}',                     # int, must not be coerced
    '{"standing_room": null}',
    '{"floor_fraction": 0.0}',                  # the field this caller reads is absent
    '{"standing_room": false',                  # truncated → JSONDecodeError
    '["standing_room"]',                        # JSON, but not an object
])
async def test_undecidable_affordance_replies_return_none(content):
    """Undecidable is never "no standing room": the caller keeps the cast on `None` and
    drops it only on a real `False`, so a coerced verdict here deletes cards."""
    assert await _standing(content) is None


@pytest.mark.asyncio
async def test_a_content_refusal_is_undecidable_not_a_failed_plate():
    """The measured case (report §5): `S00601`, a sheet-covered corpse on a gurney, gets
    HTTP 400 `data_inspection_failed` deterministically. Corpse/medical/mutilation plates
    are standing output of an SCP pipeline, so this MUST come back as "not judged" —
    reading it as "no standing room" would delete that class of shot's cast forever."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = httpx.Response(
            400, json={"error": {"code": "data_inspection_failed",
                                 "message": "Input data may contain inappropriate content."}},
            request=httpx.Request("POST", "http://vision.test"))
        assert await vision_check.plate_has_standing_room(PNG, FakeSettings()) is None


@pytest.mark.asyncio
async def test_missing_key_is_undecidable_and_makes_no_affordance_call():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        assert await vision_check.plate_has_standing_room(PNG, FakeSettings(key="")) is None
    post.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("image", ["not bytes", None, 42])
async def test_non_bytes_input_is_undecidable_for_the_affordance_call(image):
    assert await _standing('{"standing_room": true}', image=image) is None


@pytest.mark.asyncio
async def test_the_affordance_call_sends_the_calibrated_envelope():
    """The envelope, not just the prompt text. Review loop 1 re-measured all 33 plates:
    `[text, image]` recalls 3/7, `[image, text]` recalls 5/7, zero flips across repeated
    passes in either — a deterministic ordering effect, and 5/7 is the only number this
    gate is judged on. So the image part comes FIRST here, matching
    `scripts/assess_plate_affordance.py`, and `temperature: 0` is pinned on both sides.
    """
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _reply('{"standing_room": true}')
        await vision_check.plate_has_standing_room(PNG, FakeSettings())
    (url,), kwargs = post.call_args
    assert url == vision_check._DASHSCOPE_VISION_ENDPOINT
    assert kwargs["json"]["temperature"] == 0
    content = kwargs["json"]["messages"][0]["content"]
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["text"] == vision_check.STANDING_ROOM_PROMPT


@pytest.mark.asyncio
async def test_the_person_check_keeps_its_own_text_first_envelope():
    """The two questions do NOT share the order, and that is deliberate: 10.2/14.4's guard
    numbers were all measured `[text, image]`, the ordering effect has never been measured
    for THAT question, and flipping it would invalidate 14.4's confidence figures without
    replacing them. Deferred work, pinned here so it cannot drift silently."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _reply('{"has_person": false}')
        await vision_check.background_has_person(PNG, FakeSettings())
    content = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert content[0]["text"] == vision_check.CHECK_PROMPT
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_the_models_reason_is_logged_beside_the_verdict(caplog):
    """Story 14.4's lesson applied to the new question: `reason` is the only place the
    plate's actual content is described, and here it names WHY a shot just lost its card."""
    with caplog.at_level("INFO", logger=vision_check.__name__):
        assert await _standing(
            '{"standing_room": false, "reason": "close-up of an instrument tray"}') is False
    assert "close-up of an instrument tray" in caplog.text
    assert "standing_room=False" in caplog.text


def test_the_offline_curator_and_the_runtime_gate_share_one_prompt():
    """Jay's §4-2 decision: ONE prompt text, ONE output contract, two callers. The
    33-plate calibration (7/33 base rate, 1/25 false positives) is the only evidence
    this gate ships on, and a hand-copied second wording would silently invalidate it
    (`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`). An identity check, not a
    similarity check: `assess_plate_affordance.PROMPT` IS this object.
    """
    import importlib.util
    import sys
    from pathlib import Path
    path = Path(vision_check.__file__).resolve().parents[3] / "scripts/assess_plate_affordance.py"
    spec = importlib.util.spec_from_file_location("assess_plate_affordance", path)
    module = importlib.util.module_from_spec(spec)
    # The script prepends `src/` to `sys.path` at import time (it runs as a file, not as a
    # package). Executing it here leaks that entry into every test that follows, which can
    # shadow the installed package — so put the path back exactly as it was.
    before = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = before
    assert module.PROMPT is vision_check.STANDING_ROOM_PROMPT
    # The five fields the shared contract promises — dropping one changes the question.
    for field in ("standing_room", "floor_fraction", "camera_distance", "best_spot", "reason"):
        assert field in vision_check.STANDING_ROOM_PROMPT
