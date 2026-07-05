"""Image search service — provider-agnostic protocol + DuckDuckGo implementation.

No API key required. DuckDuckGo image search uses VQD token acquisition
followed by a JSON image search request. This is scraped, not an official API.

Architecture: services/ imports domain/ and db/. Must NOT import api/ or pipeline/. [AD-1]
"""

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from typing import NamedTuple, override
from urllib.parse import quote

import httpx

from yt_flow.domain.state import SearchResult

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_VQD_RE = re.compile(r"vqd=([0-9a-f-]+)")
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
_TIMEOUT = 30.0
_VQD_MAX_RETRIES = 3

# SCP Wiki page image extraction (Story 5.10 — official-source-first reference lookup)
_WIKI_BASE_URL = "https://scp-wiki.wikidot.com"
_WIKI_CONTENT_START = '<div id="page-content">'
_WIKI_CONTENT_END = '<div class="footer-wikiwalk-nav">'
_WIKI_IMG_RE = re.compile(
    r'<img[^>]+src="(https?://[^"]+/local--files/[^"]+\.(?:png|jpe?g|gif|webp))"',
    re.IGNORECASE,
)


# ── Protocol ──────────────────────────────────────────────────────────────────


class ImageSearch(ABC):
    """Provider-agnostic image search protocol. Implementations are swap-in
    search backends (DuckDuckGo, Google, etc.)."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Return up to max_results SearchResult objects for the given query."""
        ...


class WikiImage(NamedTuple):
    """A wiki-sourced reference image: the downloadable asset plus its source page for attribution."""

    image_url: str
    page_url: str


# ── SCP Wiki Implementation (Story 5.10) ─────────────────────────────────────


class ScpWikiImageFetch:
    """Fetches the SCP Wiki's official page image for a given scp_id — the primary,
    attributable source ahead of the DuckDuckGo image-search fallback.

    Wikidot slug convention (confirmed against the live site): lowercase, hyphenated,
    no zero-padding, e.g. "SCP-096" -> "scp-096", "SCP-3007" -> "scp-3007".
    """

    def __init__(
        self,
        timeout: float = _TIMEOUT,
        user_agent: str = _USER_AGENT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._headers = {"User-Agent": user_agent}
        self._transport = transport  # test seam — MockTransport, unused in production

    async def fetch(self, scp_id: str) -> WikiImage | None:
        """Return the page's main article image + page URL, or None if unavailable.

        Returns None (never raises) on any 404/HTTP error/missing-image/unparseable
        page — callers fall back to DuckDuckGo image search in that case.
        """
        slug = quote(scp_id.strip().lower())
        page_url = f"{_WIKI_BASE_URL}/{slug}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers=self._headers,
                follow_redirects=True,
                transport=self._transport,
            ) as client:
                resp = await client.get(page_url)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("SCP Wiki page fetch failed for %s: %s", scp_id, exc)
            return None

        html = resp.text
        start = html.find(_WIKI_CONTENT_START)
        if start == -1:
            logger.info("SCP Wiki page for %s has no #page-content — unrecognized structure", scp_id)
            return None
        end = html.find(_WIKI_CONTENT_END, start)
        body = html[start:end] if end != -1 else html[start:start + 50_000]

        match = _WIKI_IMG_RE.search(body)
        if not match:
            logger.info("SCP Wiki page for %s has no article image", scp_id)
            return None

        logger.info("SCP Wiki image found for %s: %s", scp_id, match.group(1))
        return WikiImage(image_url=match.group(1), page_url=page_url)


# ── DuckDuckGo Implementation ────────────────────────────────────────────────


class DuckDuckGoImageSearch(ImageSearch):
    """DuckDuckGo image search via VQD token + i.js endpoint.

    Flow:
      1. POST to duckduckgo.com → extract vqd token from response
      2. GET duckduckgo.com/i.js?q=<query>&vqd=<token> → parse JSON results
    """

    def __init__(self, timeout: float = _TIMEOUT, user_agent: str = _USER_AGENT) -> None:
        self._timeout = timeout
        self._headers = {"User-Agent": user_agent}

    async def _acquire_vqd(self, client: httpx.AsyncClient) -> str:
        """POST to duckduckgo.com and extract the VQD token from the response.

        Retries up to _VQD_MAX_RETRIES times with exponential backoff on failure.
        """
        last_error: Exception | None = None
        for attempt in range(_VQD_MAX_RETRIES):
            try:
                resp = await client.post(
                    "https://duckduckgo.com",
                    headers=self._headers,
                    data={"q": "test"},
                    follow_redirects=True,
                )
                resp.raise_for_status()
                match = _VQD_RE.search(resp.text)
                if match:
                    return match.group(1)
                raise RuntimeError("Failed to extract VQD token from DuckDuckGo response")
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                if attempt < _VQD_MAX_RETRIES - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning("VQD acquisition attempt %d failed: %s. Retrying in %ds...", attempt + 1, exc, wait)
                    await asyncio.sleep(wait)
        raise RuntimeError(f"VQD acquisition failed after {_VQD_MAX_RETRIES} attempts") from last_error

    @override
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search DuckDuckGo images for the given query."""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            headers=self._headers,
        ) as client:
            vqd = await self._acquire_vqd(client)

            params = {
                "q": query,
                "vqd": vqd,
                "o": "json",
                "p": "1",
                "f": ",,,,,",
            }
            resp = await client.get("https://duckduckgo.com/i.js", params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        for item in data.get("results", [])[:max_results]:
            results.append(SearchResult(
                url=item.get("image", ""),
                thumbnail_url=item.get("thumbnail", ""),
                title=item.get("title", ""),
            ))

        logger.info("DuckDuckGo image search: query=%r → %d results", query, len(results))
        return results
