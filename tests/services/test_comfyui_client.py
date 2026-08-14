"""Unit tests for src/yt_flow/services/comfyui_client.py (Story 1.6).

No live server: httpx.MockTransport drives the internal helpers, which take the
client as a parameter precisely so the submit/poll/download logic is testable
without a running ComfyUI. Covers the AC2 validation/failure paths.
"""

import httpx
import pytest

from yt_flow.config import Settings
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


# ── dropped prompts: accepted with 200 + prompt_id, then never queued ───────
# MEASURED over many live runs: the prompt exists in neither /queue nor
# /history and the poller burned all 900s before killing the image stage.
# interval=0.0 makes elapsed 0, so DROP_GRACE_SEC is patched to 0.0 to put the
# liveness check on poll 1 instead of waiting the real few seconds.


def _drop_server(*, queue=None, image_after=None):
    """A ComfyUI that answers /prompt + /queue + /history, counting submissions.

    ``queue`` is the ``GET /queue`` body; ``image_after`` (1-based) is the
    submission number whose prompt actually executes — earlier ones are dropped.
    """
    state = {"submits": 0, "prompts": [], "queue_polls": 0}

    async def handler(req):
        if req.url.path == "/prompt":
            import json
            state["submits"] += 1
            state["prompts"].append(json.loads(req.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": f"pid{state['submits']}", "node_errors": {}})
        if req.url.path == "/queue":
            state["queue_polls"] += 1
            return httpx.Response(200, json=queue or {"queue_running": [], "queue_pending": []})
        pid = req.url.path.rsplit("/", 1)[-1]
        if image_after is not None and pid == f"pid{image_after}":
            return httpx.Response(200, json={pid: {"outputs": {"9": {"images": [{"filename": "f.png"}]}}}})
        return httpx.Response(200, json={})  # not in history at all

    return handler, state


async def test_dropped_prompt_is_resubmitted_instead_of_burning_the_budget(monkeypatch):
    monkeypatch.setattr(cc, "DROP_GRACE_SEC", 0.0)
    handler, state = _drop_server(image_after=2)  # first submission silently dropped

    async with _client(handler) as c:
        ref = await cc._submit_and_await(c, {"9": {"inputs": {"filename_prefix": "p"}}},
                                         cc._await_image, 0.0, 900)
    assert ref["filename"] == "f.png"
    assert state["submits"] == 2
    assert state["queue_polls"] == 1  # detected on the first liveness check, not poll 900


async def test_prompt_sitting_in_queue_pending_is_not_treated_as_dropped(monkeypatch):
    """The false-positive guard: a busy queue must never trigger a resubmit."""
    monkeypatch.setattr(cc, "DROP_GRACE_SEC", 0.0)
    polls = {"n": 0}

    async def handler(req):
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "pid1"})
        if req.url.path == "/queue":
            return httpx.Response(200, json={
                "queue_running": [[7, "someone-else", {}]],
                "queue_pending": [[8, "another"], [9, "pid1", {"3": {}}, {}, {}]],
            })
        polls["n"] += 1
        if polls["n"] < 4:  # parked in the queue behind other work
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"pid1": {"outputs": {"9": {"images": [{"filename": "f.png"}]}}}})

    async with _client(handler) as c:
        ref = await cc._submit_and_await(c, {}, cc._await_image, 0.0, 10)
    assert ref["filename"] == "f.png"


async def test_unreadable_queue_is_not_treated_as_dropped(monkeypatch):
    """ComfyUI stalls HTTP while the GPU runs — a failing /queue means "unknown"."""
    monkeypatch.setattr(cc, "DROP_GRACE_SEC", 0.0)

    async def handler(req):
        if req.url.path == "/queue":
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={})

    async with _client(handler) as c:
        assert await cc._is_live(c, "pid1") is True
        with pytest.raises(cc.ComfyUIError, match="never appeared in history"):
            await cc._await_image(c, "pid1", interval=0.0, max_polls=2)


async def test_resubmission_is_bounded_and_error_reports_the_drop_count(monkeypatch):
    monkeypatch.setattr(cc, "DROP_GRACE_SEC", 0.0)
    monkeypatch.setattr(cc, "DROP_RESUBMITS", 2)
    handler, state = _drop_server()  # every submission is dropped

    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError) as exc_info:
            await cc._submit_and_await(c, {"9": {"inputs": {"filename_prefix": "p"}}},
                                       cc._await_image, 0.0, 900)
    assert state["submits"] == 3  # original + DROP_RESUBMITS, then it gives up
    msg = str(exc_info.value)
    assert "dropped the prompt 3 time(s)" in msg
    assert "never queued or executed" in msg


async def test_resubmits_are_cache_busted_too(monkeypatch):
    """A resubmit that hits the execution cache produces no outputs at all (b36aaa0)."""
    monkeypatch.setattr(cc, "DROP_GRACE_SEC", 0.0)
    handler, state = _drop_server(image_after=3)

    async with _client(handler) as c:
        await cc._submit_and_await(c, {"9": {"class_type": "SaveImage",
                                             "inputs": {"filename_prefix": "ytflow_bg"}}},
                                   cc._await_image, 0.0, 900)
    prefixes = [p["9"]["inputs"]["filename_prefix"] for p in state["prompts"]]
    assert len(prefixes) == 3 and len(set(prefixes)) == 3
    assert all(p.startswith("ytflow_bg_") for p in prefixes)


async def test_dropped_prompt_recovery_also_covers_submit_and_fetch_outputs(monkeypatch):
    monkeypatch.setattr(cc, "DROP_GRACE_SEC", 0.0)
    handler, state = _drop_server(image_after=2)

    async with _client(handler) as c:
        refs = await cc._submit_and_await(
            c, {}, lambda cl, pid, i, m: cc._await_outputs(cl, pid, ["9"], i, m), 0.0, 900)
    assert refs["9"]["filename"] == "f.png"
    assert state["submits"] == 2


async def test_normal_first_execution_returns_the_image_without_touching_the_queue(monkeypatch):
    """No drop, one submission, no liveness traffic, image unchanged."""
    monkeypatch.setattr(cc, "DROP_GRACE_SEC", 0.0)
    handler, state = _drop_server(image_after=1)

    async with _client(handler) as c:
        ref = await cc._submit_and_await(c, {}, cc._await_image, 0.0, 900)
    assert ref["filename"] == "f.png"
    assert (state["submits"], state["queue_polls"]) == (1, 0)


async def test_grace_period_delays_the_first_liveness_check(monkeypatch):
    """A prompt missing for less than DROP_GRACE_SEC is not judged yet."""
    async def handler(req):
        if req.url.path == "/queue":
            raise AssertionError("liveness checked before the grace period elapsed")
        return httpx.Response(200, json={})

    monkeypatch.setattr(cc.asyncio, "sleep", lambda _d: _done(None))  # 1s of simulated elapsed
    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="never appeared in history"):
            await cc._await_image(c, "pid", interval=1.0, max_polls=4)  # 4s < DROP_GRACE_SEC


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


# ── Workflow node manifest (Story 13.3 AC1) ──────────────────────────────────

def _node(class_type: str, title: str | None = None) -> dict:
    node: dict = {"class_type": class_type, "inputs": {}}
    if title is not None:
        node["_meta"] = {"title": title}
    return node


WF = {
    "6": _node("CLIPTextEncode", "ytflow:positive_prompt"),
    "7": _node("CLIPTextEncode", "ytflow:negative_prompt"),
    "3": _node("KSampler"),
}


def test_resolve_nodes_maps_keys_to_ids():
    assert cc.resolve_nodes(WF, ("ytflow:positive_prompt", "ytflow:negative_prompt")) == {
        "ytflow:positive_prompt": "6", "ytflow:negative_prompt": "7",
    }


def test_resolve_nodes_is_indifferent_to_node_ids():
    """The whole point: a ComfyUI re-export renumbers, and nothing moves."""
    renumbered = {"901": WF["7"], "902": WF["6"], "903": WF["3"]}
    assert cc.resolve_nodes(renumbered, ("ytflow:positive_prompt",)) == {
        "ytflow:positive_prompt": "902",
    }


def test_resolve_nodes_missing_key_names_the_key_and_the_titles_present():
    """An operator who renamed a node in the UI must be able to fix it from the
    error alone, without reading code."""
    with pytest.raises(ValueError) as exc:
        cc.resolve_nodes(WF, ("ytflow:card_image",))
    message = str(exc.value)
    assert "ytflow:card_image" in message
    assert "ytflow:positive_prompt" in message and "ytflow:negative_prompt" in message


def test_resolve_nodes_duplicate_title_raises():
    """Ambiguity is a defect, not a coin flip — copy/paste in the UI does this."""
    duplicated = {**WF, "16": _node("CLIPTextEncode", "ytflow:positive_prompt")}
    with pytest.raises(ValueError, match="ambiguous"):
        cc.resolve_nodes(duplicated, ("ytflow:positive_prompt",))


def test_resolve_nodes_matches_exactly_never_by_substring():
    """The shipped layered_inspyrenet graph is the live trap: it carries both
    "Negative Prompt" and "Background Inpaint Negative Prompt (entity exclusion)",
    so a substring rule resolves two nodes and picks one arbitrarily."""
    import json
    from pathlib import Path

    # Anchored on this file, not the CWD — pytest is run from worktrees too, and
    # tests/test_workflow_definitions.py already anchors its glob the same way.
    path = (Path(__file__).resolve().parents[2] / "data" / "workflows"
            / "comfyui_sdxl_anime_lora_layered_inspyrenet_api.json")
    workflow = json.loads(path.read_text(encoding="utf-8"))
    titles = [
        node["_meta"]["title"] for node in workflow.values()
        if isinstance(node, dict) and isinstance(node.get("_meta"), dict)
    ]
    assert "Negative Prompt" in titles
    assert "Background Inpaint Negative Prompt (entity exclusion)" in titles
    # Exact match resolves the one node; a substring rule would raise "ambiguous".
    assert cc.resolve_nodes(workflow, ("Negative Prompt",)) == {"Negative Prompt": "7"}


def test_resolve_nodes_skips_non_node_scalars():
    """API-format graphs carry provenance scalars beside the nodes; a scan that
    assumes every value is a node crashes on `ytflow_verified_iclight: true`."""
    with_scalars = {**WF, "ytflow_verified_iclight": True, "_ytflow_note": "prose"}
    assert cc.resolve_nodes(with_scalars, ("ytflow:positive_prompt",)) == {
        "ytflow:positive_prompt": "6",
    }


def test_resolve_nodes_empty_keys_is_a_no_op():
    assert cc.resolve_nodes(WF, ()) == {}


# ── get_system_stats (Story 13.3 AC7) ────────────────────────────────────────

def _mock_client(monkeypatch, handler):
    """Route get_system_stats' own AsyncClient through a MockTransport.

    The real class is captured first — patching ``cc.httpx.AsyncClient`` patches
    httpx itself, so a factory that calls it again recurses.
    """
    real = httpx.AsyncClient
    monkeypatch.setattr(
        cc.httpx, "AsyncClient",
        lambda **kw: real(base_url=kw.get("base_url", ""), transport=httpx.MockTransport(handler)),
    )


async def test_get_system_stats_returns_the_payload(monkeypatch):
    payload = {"system": {"comfyui_version": "0.12.3"}, "devices": [{"name": "cuda:0"}]}
    _mock_client(monkeypatch, lambda req: httpx.Response(200, json=payload))
    assert await cc.get_system_stats("http://comfy.test") == payload


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="boom"),
    httpx.Response(200, text="not json"),
])
async def test_get_system_stats_swallows_failures(monkeypatch, response):
    """[AD-10] provenance is observability — it records null, it never raises."""
    _mock_client(monkeypatch, lambda req: response)
    assert await cc.get_system_stats("http://comfy.test") is None


async def test_get_system_stats_swallows_transport_errors(monkeypatch):
    def _raise(req):
        raise httpx.ConnectError("connection refused")

    _mock_client(monkeypatch, _raise)
    assert await cc.get_system_stats("http://comfy.test") is None


async def test_check_health_returns_nothing_on_success(monkeypatch):
    """~15 test fakes and seed_location_plates.py replace this with an
    ``async def ok(url) -> None``; the day it starts *returning* the stats payload
    every one of them silently becomes a lie. The behaviour, not the annotation —
    a pinned annotation is self-verification (see the ffmpeg-arg-string gotcha).
    """
    payload = {"system": {"comfyui_version": "0.12.3"}}
    _mock_client(monkeypatch, lambda req: httpx.Response(200, json=payload))
    assert await cc.check_health("http://comfy.test") is None


async def test_get_system_stats_uses_the_short_timeout_not_the_health_budget(monkeypatch):
    """Story 13.3 review: image_node awaits this before any resume decision, so a
    fully-resumed run behind a busy GPU would block on the 120s health budget just
    to record a version string. Provenance is best-effort [AD-10] — it gets its own
    short timeout and records null."""
    seen: list[httpx.Timeout] = []
    real = httpx.AsyncClient

    def factory(**kw):
        seen.append(kw["timeout"])
        return real(base_url=kw.get("base_url", ""),
                    transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})))

    monkeypatch.setattr(cc.httpx, "AsyncClient", factory)
    await cc.get_system_stats("http://comfy.test")

    assert seen[0].read == cc.STATS_READ_TIMEOUT
    assert cc.STATS_READ_TIMEOUT < Settings().comfyui_health_read_timeout_sec
