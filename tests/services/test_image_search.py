"""Unit tests for DuckDuckGoImageSearch with mocked HTTP responses.
AC: 3
"""

import httpx
import pytest

from yt_flow.domain.state import SearchResult
from yt_flow.services import image_search as image_search_module
from yt_flow.services.image_search import DuckDuckGoImageSearch, ScpWikiImageFetch, _VQD_MAX_RETRIES, _VQD_RE


def _make_injecting_client(transport: httpx.MockTransport) -> type[httpx.AsyncClient]:
    """AsyncClient subclass that forces the given transport — the monkeypatch target
    used to drive DuckDuckGoImageSearch's real code path through a MockTransport
    without adding a transport seam to the production class."""

    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    return _Client


# ── Fake responses ───────────────────────────────────────────────────────────

def _fake_vqd_html():
    # DuckDuckGo response: vqd token appears as vqd=3-314-abc123... (no quotes)
    return '<html><head>vqd=3-314-abc123-def456</head></html>'


def _recording_sleep(recorded: list[float]):
    """Stand-in for asyncio.sleep in retry tests — records the requested delay
    instead of skipping it, so tests can assert on the backoff sequence."""

    async def _sleep(seconds: float) -> None:
        recorded.append(seconds)

    return _sleep


class TestDuckDuckGoImageSearch:
    """AC3: DuckDuckGo image search returns SearchResult objects."""

    def test_vqd_regex_extracts_token(self):
        """VQD token regex correctly extracts from HTML."""
        html = _fake_vqd_html()
        match = _VQD_RE.search(html)
        assert match is not None
        assert match.group(1) == "3-314-abc123-def456"

    def test_search_result_typeddict(self):
        """SearchResult has the correct fields."""
        sr = SearchResult(url="http://x.com/a.jpg", thumbnail_url="http://x.com/t.jpg", title="Test")
        assert sr["url"] == "http://x.com/a.jpg"
        assert sr["thumbnail_url"] == "http://x.com/t.jpg"
        assert sr["title"] == "Test"

    @pytest.mark.asyncio
    async def test_acquire_vqd_sends_get_to_query_page(self, monkeypatch):
        """AC1: vqd is acquired via GET to the query results page, not the homepage POST."""
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/"
            assert request.url.params["q"] == "SCP-096"
            assert request.url.params["iax"] == "images"
            assert request.url.params["ia"] == "images"
            return httpx.Response(200, text=_fake_vqd_html(), request=request)

        transport = httpx.MockTransport(handler)
        search = DuckDuckGoImageSearch()
        async with httpx.AsyncClient(transport=transport) as client:
            vqd = await search._acquire_vqd(client, "SCP-096")

        assert vqd == "3-314-abc123-def456"

    @pytest.mark.asyncio
    async def test_vqd_retry_on_failure(self, monkeypatch):
        """AC1/AC5: retry loop with exponential backoff, preserved across the new GET path."""
        sleeps: list[float] = []
        monkeypatch.setattr(image_search_module.asyncio, "sleep", _recording_sleep(sleeps))
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(500, request=request)
            return httpx.Response(200, text=_fake_vqd_html(), request=request)

        transport = httpx.MockTransport(handler)
        search = DuckDuckGoImageSearch()
        async with httpx.AsyncClient(transport=transport) as client:
            vqd = await search._acquire_vqd(client, "SCP-096")

        assert vqd == "3-314-abc123-def456"
        assert calls["n"] == 3
        assert sleeps == [1, 2]  # exponential backoff: 2**0, 2**1

    @pytest.mark.asyncio
    async def test_vqd_retry_exhausted_raises(self, monkeypatch):
        """AC5: exhausting all retries raises the same RuntimeError as before."""
        monkeypatch.setattr(image_search_module.asyncio, "sleep", _recording_sleep([]))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, request=request)

        transport = httpx.MockTransport(handler)
        search = DuckDuckGoImageSearch()
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(RuntimeError, match=f"VQD acquisition failed after {_VQD_MAX_RETRIES} attempts"):
                await search._acquire_vqd(client, "SCP-096")

    @pytest.mark.asyncio
    async def test_search_with_mock_transport(self, monkeypatch):
        """AC2/AC3/AC6: full search() flow through the real code path — query-page vqd
        acquisition + Referer header on i.js — returns real SearchResult objects."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/i.js":
                assert request.headers.get("referer") == "https://duckduckgo.com/"
                return httpx.Response(200, json={
                    "results": [
                        {"image": "http://x.com/1.jpg", "thumbnail": "http://x.com/t1.jpg", "title": "One"},
                        {"image": "http://x.com/2.jpg", "thumbnail": "http://x.com/t2.jpg", "title": "Two"},
                    ]
                }, request=request)
            assert request.url.params["q"] == "SCP-096"
            return httpx.Response(200, text=_fake_vqd_html(), request=request)

        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(image_search_module.httpx, "AsyncClient", _make_injecting_client(transport))

        results = await DuckDuckGoImageSearch().search("SCP-096", max_results=5)

        assert len(results) == 2
        assert results[0]["url"] == "http://x.com/1.jpg"
        assert results[0]["title"] == "One"

    @pytest.mark.asyncio
    async def test_max_results_limit(self, monkeypatch):
        """max_results limits the returned count, through the real search() path."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/i.js":
                return httpx.Response(200, json={
                    "results": [
                        {"image": f"http://x.com/{i}.jpg", "thumbnail": "", "title": ""}
                        for i in range(1, 6)
                    ]
                }, request=request)
            return httpx.Response(200, text=_fake_vqd_html(), request=request)

        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(image_search_module.httpx, "AsyncClient", _make_injecting_client(transport))

        results = await DuckDuckGoImageSearch().search("test", max_results=2)

        assert len(results) == 2


# ── ScpWikiImageFetch (Story 5.10, AC1-2) ────────────────────────────────────

_PAGE_WITH_IMAGE = """
<html><body>
<div id="page-content">
<div style="text-align: right;"><div class="page-rate-widget-box">rate</div></div>
<p>Item #: SCP-096</p>
<img src="https://scp-wiki.wdfiles.com/local--files/scp-096/shy-guy.jpg" alt="shy-guy.jpg" class="image" />
</div>
<div class="footer-wikiwalk-nav">nav</div>
</body></html>
"""

_PAGE_NO_IMAGE = """
<html><body>
<div id="page-content">
<p>Item #: SCP-173</p>
</div>
<div class="footer-wikiwalk-nav">nav</div>
</body></html>
"""


class TestScpWikiImageFetch:
    """AC1: SCP Wiki fetch is attempted before DuckDuckGo. AC2: falls back on any miss."""

    @pytest.mark.asyncio
    async def test_wiki_hit_extracts_image_url(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/scp-096"
            return httpx.Response(200, text=_PAGE_WITH_IMAGE, request=request)

        fetch = ScpWikiImageFetch(transport=httpx.MockTransport(handler))
        result = await fetch.fetch("SCP-096")

        assert result is not None
        assert result.image_url == "https://scp-wiki.wdfiles.com/local--files/scp-096/shy-guy.jpg"
        assert result.page_url == "https://scp-wiki.wikidot.com/scp-096"

    @pytest.mark.asyncio
    async def test_wiki_miss_no_image_element(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_PAGE_NO_IMAGE, request=request)

        fetch = ScpWikiImageFetch(transport=httpx.MockTransport(handler))
        result = await fetch.fetch("SCP-173")

        assert result is None

    @pytest.mark.asyncio
    async def test_wiki_miss_404(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found", request=request)

        fetch = ScpWikiImageFetch(transport=httpx.MockTransport(handler))
        result = await fetch.fetch("SCP-9999999")

        assert result is None

    @pytest.mark.asyncio
    async def test_wiki_miss_connection_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        fetch = ScpWikiImageFetch(transport=httpx.MockTransport(handler))
        result = await fetch.fetch("SCP-096")

        assert result is None

    @pytest.mark.asyncio
    async def test_wiki_miss_unrecognized_structure(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><body>no page-content div</body></html>", request=request)

        fetch = ScpWikiImageFetch(transport=httpx.MockTransport(handler))
        result = await fetch.fetch("SCP-096")

        assert result is None

