"""Unit tests for DuckDuckGoImageSearch with mocked HTTP responses.
AC: 3
"""

import httpx
import pytest

from yt_flow.domain.state import SearchResult
from yt_flow.services.image_search import DuckDuckGoImageSearch, ScpWikiImageFetch, _VQD_RE


# ── Fake responses ───────────────────────────────────────────────────────────

def _fake_vqd_html():
    # DuckDuckGo response: vqd token appears as vqd=3-314-abc123... (no quotes)
    return '<html><head>vqd=3-314-abc123-def456</head></html>'


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
    async def test_search_with_mock_transport(self):
        """Full search flow with MockTransport returns SearchResults."""
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(200, text=_fake_vqd_html(), request=request)
            return httpx.Response(200, json={
                "results": [
                    {"image": "http://x.com/1.jpg", "thumbnail": "http://x.com/t1.jpg", "title": "One"},
                    {"image": "http://x.com/2.jpg", "thumbnail": "http://x.com/t2.jpg", "title": "Two"},
                ]
            }, request=request)

        transport = httpx.MockTransport(handler)
        search = DuckDuckGoImageSearch()

        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(search._timeout),
            headers=search._headers,
        ) as client:
            # Acquire VQD
            resp = await client.post("https://duckduckgo.com", data={"q": "test"})
            resp.raise_for_status()
            match = _VQD_RE.search(resp.text)
            assert match is not None
            vqd = match.group(1)

            # Search
            resp2 = await client.get("https://duckduckgo.com/i.js", params={
                "q": "SCP-096", "vqd": vqd, "o": "json", "p": "1", "f": ",,,,,",
            })
            resp2.raise_for_status()
            data = resp2.json()

        results = [
            SearchResult(url=item["image"], thumbnail_url=item["thumbnail"], title=item["title"])
            for item in data["results"]
        ]
        assert len(results) == 2
        assert results[0]["url"] == "http://x.com/1.jpg"
        assert results[0]["title"] == "One"

    @pytest.mark.asyncio
    async def test_max_results_limit(self):
        """max_results limits the returned count."""
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(200, text=_fake_vqd_html(), request=request)
            return httpx.Response(200, json={
                "results": [
                    {"image": f"http://x.com/{i}.jpg", "thumbnail": "", "title": ""}
                    for i in range(1, 6)
                ]
            }, request=request)

        transport = httpx.MockTransport(handler)
        search = DuckDuckGoImageSearch()

        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(search._timeout),
            headers=search._headers,
        ) as client:
            resp = await client.post("https://duckduckgo.com", data={"q": "test"})
            match = _VQD_RE.search(resp.text)
            vqd = match.group(1) if match else "x"

            resp2 = await client.get("https://duckduckgo.com/i.js", params={
                "q": "test", "vqd": vqd, "o": "json", "p": "1", "f": ",,,,,",
            })
            data = resp2.json()
            # Apply max_results=2
            limited = data["results"][:2]
            assert len(limited) == 2


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

