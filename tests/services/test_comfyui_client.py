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


async def test_poll_budget_comes_from_settings(monkeypatch):
    """The generation budget is config-driven, not the old hardcoded 180 polls.

    A 20s timeout at a 4s interval must yield 5 polls, and submit_and_fetch must
    hand exactly that to the poller; explicit caller values still win.
    """
    monkeypatch.setenv("YTFLOW_COMFYUI_GENERATION_TIMEOUT_SEC", "20")
    monkeypatch.setenv("YTFLOW_COMFYUI_POLL_INTERVAL_SEC", "4")

    assert cc._poll_budget(None, None) == (4.0, 5)
    assert cc._poll_budget(0.0, 2) == (0.0, 2)  # caller override untouched

    seen = {}

    async def fake_await_image(client, prompt_id, interval, max_polls):
        seen["budget"] = (interval, max_polls)
        return {"filename": "f.png"}

    monkeypatch.setattr(cc, "_submit", lambda c, w: _done("pid"))
    monkeypatch.setattr(cc, "_await_image", fake_await_image)
    monkeypatch.setattr(cc, "_download", lambda c, ref: _done(b"PNG"))

    assert await cc.submit_and_fetch("http://comfy.test", {}) == b"PNG"
    assert seen["budget"] == (4.0, 5)


async def _done(value):
    return value


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


# ── upload_image (Story 5.10 — LoadImage needs a real uploaded filename, not base64) ─

async def test_upload_returns_bare_name_without_subfolder():
    async def handler(req):
        assert req.url.path == "/upload/image"
        return httpx.Response(200, json={"name": "ref.png", "subfolder": "", "type": "input"})
    async with _client(handler) as c:
        assert await cc._upload(c, b"PNGBYTES", "ref.png") == "ref.png"


async def test_upload_returns_bracketed_name_with_subfolder():
    async def handler(req):
        return httpx.Response(200, json={"name": "ref.png", "subfolder": "sub", "type": "input"})
    async with _client(handler) as c:
        assert await cc._upload(c, b"PNGBYTES", "ref.png") == "ref.png [sub]"


async def test_upload_raises_on_http_error():
    async def handler(req):
        return httpx.Response(400, text="bad request")
    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="upload failed"):
            await cc._upload(c, b"PNGBYTES", "ref.png")


async def test_upload_raises_when_name_missing():
    async def handler(req):
        return httpx.Response(200, json={})
    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="missing name"):
            await cc._upload(c, b"PNGBYTES", "ref.png")


async def test_upload_declares_content_type_from_filename():
    captured = {}

    async def handler(req):
        content_type = req.headers["content-type"]
        assert content_type.startswith("multipart/form-data")
        captured["body"] = req.content
        return httpx.Response(200, json={"name": "ref.jpg", "subfolder": ""})

    async with _client(handler) as c:
        await cc._upload(c, b"JPEGBYTES", "ref.jpg")
    assert b"Content-Type: image/jpeg" in captured["body"]
