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


async def test_await_image_timeout_reports_poll_and_error_counts():
    """Every poll erroring must not read as "ComfyUI produced nothing".

    The old silent `except httpx.HTTPError: entry = None` made a broken poll
    indistinguishable from a slow generation — the error names the counts and
    the last exception so the next incident is diagnosable from the journal.
    """
    async def handler(req):
        raise httpx.ReadTimeout("read timed out")

    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError) as exc_info:
            await cc._await_image(c, "pid", interval=0.0, max_polls=3)
    msg = str(exc_info.value)
    assert "3 polls" in msg and "3 errored" in msg
    assert "ReadTimeout" in msg and "read timed out" in msg
    assert "never appeared in history" in msg


async def test_await_image_timeout_distinguishes_present_but_imageless():
    """Prompt in history with no images is a different failure from a dead poll."""
    async def handler(req):
        return httpx.Response(200, json={"pid": {"outputs": {"9": {"gifs": []}}}})

    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError) as exc_info:
            await cc._await_image(c, "pid", interval=0.0, max_polls=2)
    msg = str(exc_info.value)
    assert "in history but it carried no image" in msg
    assert "['9']" in msg  # which output nodes were actually present
    assert "2 polls, 0 errored" in msg


# ── execution cache: finished-with-no-outputs is terminal, not slow ──────────
# ComfyUI serves an identical graph from its execution cache: SaveImage never
# re-executes, so the history entry is success/completed with outputs=[]. The old
# poller waited out the whole budget and then blamed a timeout.

_CACHED_ENTRY = {
    "outputs": {},
    "status": {
        "status_str": "success",
        "completed": True,
        "messages": [["execution_start", {}], ["execution_cached", {}], ["execution_success", {}]],
    },
}


async def test_await_image_cached_entry_fails_fast_without_burning_budget():
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        return httpx.Response(200, json={"pid": _CACHED_ENTRY})

    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError) as exc_info:
            await cc._await_image(c, "pid", interval=0.0, max_polls=900)
    assert calls["n"] == 1  # terminal on the first poll, not 900
    msg = str(exc_info.value)
    assert "finished prompt_id=pid without an image" in msg
    assert "execution_cached" in msg and "'success'" in msg
    assert "terminal after 1 poll(s)" in msg


async def test_await_outputs_cached_entry_fails_fast():
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        return httpx.Response(200, json={"pid": _CACHED_ENTRY})

    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="without an image for node\\(s\\) \\['9', '13'\\]"):
            await cc._await_outputs(c, "pid", ["9", "13"], interval=0.0, max_polls=900)
    assert calls["n"] == 1


async def test_await_image_errored_entry_fails_fast():
    """A prompt that ended in error is terminal too — don't wait out the budget."""
    async def handler(req):
        return httpx.Response(200, json={"pid": {"outputs": {}, "status": {
            "status_str": "error", "completed": False,
            "messages": [["execution_error", {"exception_message": "OOM"}]],
        }}})

    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="status_str='error'"):
            await cc._await_image(c, "pid", interval=0.0, max_polls=900)


async def test_await_image_unfinished_entry_still_polls():
    """No status yet = mid-flight: the entry must not be mistaken for terminal."""
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(200, json={"pid": {"outputs": {}}})
        return httpx.Response(200, json={
            "pid": {"outputs": {"9": {"images": [{"filename": "f.png"}]}}}
        })

    async with _client(handler) as c:
        ref = await cc._await_image(c, "pid", interval=0.0, max_polls=5)
    assert ref["filename"] == "f.png"
    assert calls["n"] == 3


# ── cache busting on submit (the fix: SaveImage must re-execute) ─────────────

async def test_submit_makes_save_prefix_unique_but_leaves_seed_alone():
    """Only filename_prefix changes — the Story 11.1 seed contract is untouched."""
    sent = []

    async def handler(req):
        import json
        sent.append(json.loads(req.content)["prompt"])
        return httpx.Response(200, json={"prompt_id": "abc"})

    wf = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1234567, "steps": 30}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ytflow_bg", "images": ["8", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ytflow_char", "images": ["12", 0]}},
    }
    async with _client(handler) as c:
        await cc._submit(c, wf)
        await cc._submit(c, wf)

    for body in sent:
        assert body["3"]["inputs"] == {"seed": 1234567, "steps": 30}  # sampler identical
        assert body["9"]["inputs"]["filename_prefix"].startswith("ytflow_bg_")
        assert body["13"]["inputs"]["filename_prefix"].startswith("ytflow_char_")
    # two submissions of the same graph -> different save keys -> no cache hit
    assert sent[0]["9"]["inputs"]["filename_prefix"] != sent[1]["9"]["inputs"]["filename_prefix"]
    assert wf["9"]["inputs"]["filename_prefix"] == "ytflow_bg"  # caller's dict untouched


async def test_submit_tolerates_workflow_without_save_node():
    async def handler(req):
        return httpx.Response(200, json={"prompt_id": "abc"})

    async with _client(handler) as c:
        assert await cc._submit(c, {"3": {"inputs": {"seed": 1}}, "x": "not-a-node"}) == "abc"


async def test_await_outputs_timeout_reports_counts_and_nodes():
    async def handler(req):
        return httpx.Response(200, json={"pid": {"outputs": {"9": {"images": [{"filename": "f.png"}]}}}})

    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError) as exc_info:
            await cc._await_outputs(c, "pid", ["42"], interval=0.0, max_polls=2)
    msg = str(exc_info.value)
    assert "node(s) ['42']" in msg and "output nodes seen: ['9']" in msg
    assert "2 polls, 0 errored" in msg


async def test_await_image_logs_transient_error_but_still_retries(caplog):
    """Logging the swallowed exception must not break the retry path."""
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={
            "pid": {"outputs": {"9": {"images": [{"filename": "f.png"}]}}}
        })

    with caplog.at_level("WARNING", logger=cc.logger.name):
        async with _client(handler) as c:
            ref = await cc._await_image(c, "pid", interval=0.0, max_polls=3)
    assert ref["filename"] == "f.png"
    assert calls["n"] == 2
    assert "HTTPStatusError" in caplog.text and "prompt_id=pid" in caplog.text


async def test_poll_error_logging_is_rate_limited(caplog):
    """First error at WARNING, the rest at DEBUG — 900 polls can't flood the log."""
    async def handler(req):
        raise httpx.ConnectError("refused")

    with caplog.at_level("DEBUG", logger=cc.logger.name):
        async with _client(handler) as c:
            with pytest.raises(cc.ComfyUIError):
                await cc._await_image(c, "pid", interval=0.0, max_polls=5)
    levels = [r.levelname for r in caplog.records]
    assert levels == ["WARNING", "DEBUG", "DEBUG", "DEBUG", "DEBUG"]


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
