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
