"""Unit tests for src/yt_flow/services/comfyui_client.py (Story 1.6).

No live server: httpx.MockTransport drives the internal helpers, which take the
client as a parameter precisely so the submit/poll/download logic is testable
without a running ComfyUI. Covers the AC2 validation/failure paths.
"""

import httpx
import pytest

from yt_flow.services import comfyui_client as cc


def _client(handler):
    return httpx.AsyncClient(base_url="http://comfy.test", transport=httpx.MockTransport(handler))


async def test_submit_returns_prompt_id():
    async def handler(req):
        assert req.url.path == "/prompt"
        return httpx.Response(200, json={"prompt_id": "abc"})
    async with _client(handler) as c:
        assert await cc._submit(c, {"6": {}}) == "abc"


async def test_submit_raises_on_node_errors_in_200_body():
    async def handler(req):
        return httpx.Response(200, json={"node_errors": {"6": "missing text"}})
    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="validation error"):
            await cc._submit(c, {})


async def test_submit_raises_on_http_400():
    async def handler(req):
        return httpx.Response(400, json={"error": "invalid prompt"})
    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="rejected prompt"):
            await cc._submit(c, {})


async def test_submit_raises_when_prompt_id_missing():
    async def handler(req):
        return httpx.Response(200, json={})
    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="missing prompt_id"):
            await cc._submit(c, {})


async def test_await_image_extracts_first_image_ref():
    async def handler(req):
        return httpx.Response(200, json={
            "pid": {"outputs": {"9": {"images": [
                {"filename": "f.png", "subfolder": "", "type": "output"}]}}}
        })
    async with _client(handler) as c:
        ref = await cc._await_image(c, "pid", interval=0.0, max_polls=3)
        assert ref["filename"] == "f.png"


async def test_await_image_times_out_without_images():
    async def handler(req):
        return httpx.Response(200, json={"pid": {"outputs": {}}})
    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="no image"):
            await cc._await_image(c, "pid", interval=0.0, max_polls=2)


async def test_await_image_retries_transient_http_error():
    # A brief 5xx on the first poll must not abort the submission; the poll
    # budget should absorb it and succeed once the image appears. [review]
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={
            "pid": {"outputs": {"9": {"images": [
                {"filename": "f.png", "subfolder": "", "type": "output"}]}}}
        })
    async with _client(handler) as c:
        ref = await cc._await_image(c, "pid", interval=0.0, max_polls=3)
        assert ref["filename"] == "f.png"
        assert calls["n"] == 2  # retried past the transient error


async def test_download_returns_bytes():
    async def handler(req):
        assert req.url.path == "/view"
        assert req.url.params["filename"] == "f.png"
        return httpx.Response(200, content=b"PNGBYTES")
    async with _client(handler) as c:
        assert await cc._download(c, {"filename": "f.png"}) == b"PNGBYTES"


async def test_download_raises_on_empty_body():
    async def handler(req):
        return httpx.Response(200, content=b"")
    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="empty body"):
            await cc._download(c, {"filename": "f.png"})
