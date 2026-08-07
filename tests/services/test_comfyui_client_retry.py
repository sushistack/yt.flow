"""Unit tests for the Story 5.14 bounded connection retry in comfyui_client.py.

Fully offline: httpx.MockTransport drives the client directly, no live server.
A dedicated file (rather than extending test_comfyui_client.py) per the story's
contract — see that module's docstring re: project test-execution convention.
"""

import asyncio

import httpx
import pytest

from yt_flow.services import comfyui_client as cc


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    monkeypatch.setattr(cc, "CONNECT_RETRY_DELAY", 0.0)


def _client(handler):
    return httpx.AsyncClient(base_url="http://comfy.test", transport=httpx.MockTransport(handler))


def _patch_check_health_transport(monkeypatch, handler):
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        cc.httpx, "AsyncClient",
        lambda *a, **kw: real_async_client(*a, **{**kw, "transport": httpx.MockTransport(handler)}),
    )


# ── _submit connection retry (AC5) ──────────────────────────────────────────

async def test_submit_retries_transport_error_then_succeeds():
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"prompt_id": "abc"})

    async with _client(handler) as c:
        assert await cc._submit(c, {}) == "abc"
    assert calls["n"] == 3


async def test_submit_raises_after_persistent_transport_error():
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        raise httpx.ConnectError("connection refused")

    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="connection failed"):
            await cc._submit(c, {})
    assert calls["n"] == cc.CONNECT_ATTEMPTS


async def test_submit_validation_error_not_retried():
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        return httpx.Response(400, json={"error": "invalid prompt"})

    async with _client(handler) as c:
        with pytest.raises(cc.ComfyUIError, match="rejected prompt"):
            await cc._submit(c, {})
    assert calls["n"] == 1


async def test_submit_generation_timeout_path_unaffected():
    """_await_image's own poll-budget timeout is untouched by the connect retry."""
    async def handler(req):
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "pid"})
        return httpx.Response(200, json={"pid": {"outputs": {}}})

    async with _client(handler) as c:
        prompt_id = await cc._submit(c, {})
        with pytest.raises(cc.ComfyUIError, match="no image"):
            await cc._await_image(c, prompt_id, interval=0.0, max_polls=2)


# ── check_health (AC4) ───────────────────────────────────────────────────────

async def test_check_health_reachable_returns(monkeypatch):
    async def handler(req):
        assert req.url.path == "/system_stats"
        return httpx.Response(200, json={})

    _patch_check_health_transport(monkeypatch, handler)
    await cc.check_health("http://comfy.test")  # no raise


async def test_check_health_unreachable_raises_after_retries(monkeypatch):
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        raise httpx.ConnectError("refused")

    _patch_check_health_transport(monkeypatch, handler)
    with pytest.raises(cc.ComfyUIError, match="unreachable"):
        await cc.check_health("http://comfy.test")
    assert calls["n"] == cc.CONNECT_ATTEMPTS


# ── check_health busy-vs-dead (run fdd69699) ────────────────────────────────
# ComfyUI is single-threaded on the GPU and stops answering /system_stats while
# a prompt runs. A slow-but-answered probe must be HEALTHY; only a refused
# connection is a crash. Real sockets, not MockTransport — MockTransport never
# touches the network so it cannot exercise timeouts at all. Delays are kept
# sub-second (not >5s) so the suite stays fast; that the *configured* read
# timeout is what governs slowness is pinned by the two tests below plus
# test_check_health_timeout_split_is_applied.


async def _slow_server(delay: float):
    """Accept the connection, then answer /system_stats only after `delay`s."""
    async def handle(reader, writer):
        await reader.read(4096)
        await asyncio.sleep(delay)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_check_health_slow_but_answered_is_healthy(monkeypatch):
    monkeypatch.setenv("YTFLOW_COMFYUI_HEALTH_READ_TIMEOUT_SEC", "10")
    server, port = await _slow_server(0.3)
    async with server:
        await cc.check_health(f"http://127.0.0.1:{port}")  # busy != crashed


async def test_check_health_read_timeout_is_configurable(monkeypatch):
    """The configured read timeout is the one that actually bites."""
    monkeypatch.setenv("YTFLOW_COMFYUI_HEALTH_READ_TIMEOUT_SEC", "0.1")
    server, port = await _slow_server(2.0)
    async with server:
        with pytest.raises(cc.ComfyUIError, match="unreachable"):
            await cc.check_health(f"http://127.0.0.1:{port}")


async def test_check_health_connection_refused_is_unhealthy():
    """No listener on the port -> ComfyUIError, promptly (CONNECT_RETRY_DELAY=0)."""
    server, port = await _slow_server(0.0)
    server.close()
    await server.wait_closed()
    with pytest.raises(cc.ComfyUIError, match="unreachable"):
        await cc.check_health(f"http://127.0.0.1:{port}")


async def test_check_health_timeout_split_is_applied(monkeypatch):
    """Short connect timeout (crash detection) + long configured read timeout."""
    monkeypatch.setenv("YTFLOW_COMFYUI_HEALTH_READ_TIMEOUT_SEC", "77")
    seen = {}
    real_async_client = httpx.AsyncClient

    def capture(*a, **kw):
        seen["timeout"] = kw["timeout"]
        return real_async_client(*a, **{**kw, "transport": httpx.MockTransport(
            lambda req: httpx.Response(200, json={})
        )})

    monkeypatch.setattr(cc.httpx, "AsyncClient", capture)
    await cc.check_health("http://comfy.test")
    assert seen["timeout"].connect == cc.HEALTH_CONNECT_TIMEOUT == 5.0
    assert seen["timeout"].read == 77.0
