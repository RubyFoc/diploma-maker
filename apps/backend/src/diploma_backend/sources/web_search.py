"""General web search via Google's Custom Search JSON API (user request): a last-resort
grounding fallback for a required source that has no direct `url`, and that neither
`sources.search` (Semantic Scholar/CORE — academic-literature-only APIs) nor a direct-URL fetch
could ground — many real citations (regional-journal articles, student conference proceedings)
simply aren't indexed by either, but do turn up in an ordinary web search.

Requires `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_CX` (a Custom Search Engine id configured at
https://programmablesearchengine.google.com/ to search the whole web) to be set — same
skip-entirely-if-unconfigured posture as `sources.search`'s `CORE_API_KEY`, since scraping
Google's own results page directly would violate its terms of service and break without notice.
"""

import os
from dataclasses import dataclass

import httpx

_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
_DEFAULT_TIMEOUT_SECONDS = 20.0
_DEFAULT_LIMIT = 3


class WebSearchError(Exception):
    """Raised when a web search couldn't be performed: the API isn't configured
    (`GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_CX` unset) or the request itself failed.
    """


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    link: str
    snippet: str


async def web_search(query: str, limit: int = _DEFAULT_LIMIT) -> list[WebSearchResult]:
    """Searches the general web for `query` via Google Custom Search, returning up to `limit`
    results. Raises `WebSearchError` if `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_CX` aren't both set, or
    if the request fails — callers should treat this as "no result", not a hard error.
    """
    api_key = os.environ.get("GOOGLE_CSE_API_KEY")
    cx = os.environ.get("GOOGLE_CSE_CX")
    if not api_key or not cx:
        raise WebSearchError("Google Custom Search is not configured")

    params = {"key": api_key, "cx": cx, "q": query, "num": min(limit, 10)}
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.get(_SEARCH_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise WebSearchError(f"Google Custom Search request failed: {exc}") from exc

    results = []
    for item in payload.get("items", [])[:limit]:
        title = item.get("title")
        link = item.get("link")
        snippet = item.get("snippet")
        if title and link and snippet:
            results.append(WebSearchResult(title=title, link=link, snippet=snippet))
    return results
