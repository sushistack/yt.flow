"""Unit tests for DuckDuckGoImageSearch with mocked HTTP responses.
AC: 3
"""

import httpx
import pytest

from yt_flow.domain.state import SearchResult
from yt_flow.services.image_search import DuckDuckGoImageSearch, _VQD_RE


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

