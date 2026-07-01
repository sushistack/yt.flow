"""Image search service — provider-agnostic protocol + DuckDuckGo implementation.

No API key required. DuckDuckGo image search uses VQD token acquisition
followed by a JSON image search request. This is scraped, not an official API.

Architecture: services/ imports domain/ and db/. Must NOT import api/ or pipeline/. [AD-1]
"""

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from typing import override

import httpx

from yt_flow.domain.state import SearchResult

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_VQD_RE = re.compile(r"vqd=([0-9a-f-]+)")
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
_TIMEOUT = 30.0
_VQD_MAX_RETRIES = 3


# ── Protocol ──────────────────────────────────────────────────────────────────


class ImageSearch(ABC):
    """Provider-agnostic image search protocol. Implementations are swap-in
    search backends (DuckDuckGo, Google, etc.)."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Return up to max_results SearchResult objects for the given query."""
        ...


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
