"""External academic search integration: Semantic Scholar (primary) + CORE (fallback).

Implements TASK-E04-2 (source management pipeline stage per `docs/architecture/overview.md`).
This module only *finds* candidate sources by querying external academic search APIs — it does
not touch Qdrant (ADR-0002 covers that in `diploma_backend.sources.client`, TASK-E04-1) and does
not verify or cite anything (that is citation verification, TASK-E04-4, per ADR-0001). The
`external_id` returned here is what a later citation-verification step uses to fetch the full
source text from the same provider.

Providers:
- Semantic Scholar Graph API (`/graph/v1/paper/search`) is primary and needs no API key for
  basic use; setting `SEMANTIC_SCHOLAR_API_KEY` adds it as an `x-api-key` header for a higher
  rate limit.
- CORE API (`/v3/search/works`) is a secondary/fallback provider, used only if Semantic Scholar
  fails or returns no results, and only if `CORE_API_KEY` is set (CORE requires a key; if unset,
  it is skipped entirely rather than attempted and failed).

Recency filtering: `min_year` is passed to Semantic Scholar as `year=<min_year>-` (an open-ended
range, per its query syntax) and to CORE as a `yearPublished>=<min_year>` clause appended to the
query string (CORE's search query language supports field filters inline in `q`).

`SourceSearchResult.venue` (journal/publisher name, when the provider supplies one) is populated
here so that `diploma_backend.sources.geo_filter` (TASK-E04-3) can heuristically filter/annotate
results for RU/BY academic sources. This module does not itself do any geo-fencing.

Out of scope here (later, separate tasks): citation verification/retry (TASK-E04-4).
"""

import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx

_SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org"
_SEMANTIC_SCHOLAR_SEARCH_PATH = "/graph/v1/paper/search"
_SEMANTIC_SCHOLAR_FIELDS = "title,authors,year,abstract,url,externalIds,venue"

_CORE_BASE_URL = "https://api.core.ac.uk"
_CORE_SEARCH_PATH = "/v3/search/works"

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_LIMIT = 10

Provider = Literal["semantic_scholar", "core"]


class SourceSearchError(Exception):
    """Raised when every attempted provider fails.

    Wraps the underlying network/HTTP failures so callers never need to catch raw `httpx`
    exceptions directly. Not raised if at least one attempted provider returns successfully
    (even with zero results) — only raised when all attempted providers error out.
    """


@dataclass(frozen=True)
class SourceSearchResult:
    """A single normalized search hit, regardless of which provider produced it.

    `external_id` is the provider's own paper/work identifier (Semantic Scholar's `paperId` or
    CORE's `id`), kept around so a later citation-verification step (TASK-E04-4) can fetch the
    full text back from the same provider without re-searching.

    `venue` is the journal/conference/publisher name if the provider supplied one (Semantic
    Scholar's `venue` field, CORE's `publisher` field) — `None` if absent. It exists primarily so
    `diploma_backend.sources.geo_filter` (TASK-E04-3) can heuristically detect RU/BY academic
    sources; it is optional and defaults to `None` so existing construction call sites are
    unaffected.
    """

    title: str
    authors: list[str]
    year: int | None
    abstract: str | None
    url: str | None
    provider: Provider
    external_id: str
    venue: str | None = None


async def _search_semantic_scholar(
    client: httpx.AsyncClient, query: str, *, min_year: int | None, limit: int
) -> list[SourceSearchResult]:
    params: dict[str, Any] = {"query": query, "limit": limit, "fields": _SEMANTIC_SCHOLAR_FIELDS}
    if min_year is not None:
        params["year"] = f"{min_year}-"

    headers = {}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    if api_key:
        headers["x-api-key"] = api_key

    try:
        response = await client.get(
            _SEMANTIC_SCHOLAR_SEARCH_PATH, params=params, headers=headers
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SourceSearchError(
            f"Semantic Scholar request failed with status {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise SourceSearchError(
            f"Semantic Scholar request failed: {type(exc).__name__}"
        ) from exc

    try:
        papers = response.json().get("data", [])
    except ValueError as exc:
        raise SourceSearchError("Semantic Scholar response was not valid JSON") from exc

    results = []
    for paper in papers:
        results.append(
            SourceSearchResult(
                title=paper.get("title") or "",
                authors=[a.get("name", "") for a in paper.get("authors") or []],
                year=paper.get("year"),
                abstract=paper.get("abstract"),
                url=paper.get("url"),
                provider="semantic_scholar",
                external_id=str(paper.get("paperId", "")),
                venue=paper.get("venue") or None,
            )
        )
    return results


async def _search_core(
    client: httpx.AsyncClient, query: str, *, min_year: int | None, limit: int
) -> list[SourceSearchResult]:
    api_key = os.environ.get("CORE_API_KEY", "")
    search_query = query
    if min_year is not None:
        search_query = f"{query} AND yearPublished>={min_year}"

    try:
        response = await client.get(
            _CORE_SEARCH_PATH,
            params={"q": search_query, "limit": limit},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SourceSearchError(
            f"CORE request failed with status {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise SourceSearchError(f"CORE request failed: {type(exc).__name__}") from exc

    try:
        works = response.json().get("results", [])
    except ValueError as exc:
        raise SourceSearchError("CORE response was not valid JSON") from exc

    results = []
    for work in works:
        authors = work.get("authors") or []
        results.append(
            SourceSearchResult(
                title=work.get("title") or "",
                authors=[a.get("name", "") for a in authors],
                year=work.get("yearPublished"),
                abstract=work.get("abstract"),
                url=work.get("downloadUrl"),
                provider="core",
                external_id=str(work.get("id", "")),
                venue=work.get("publisher") or None,
            )
        )
    return results


async def search_sources(
    query: str, *, min_year: int | None = None, limit: int = _DEFAULT_LIMIT
) -> list[SourceSearchResult]:
    """Search academic literature for `query`, optionally restricted to `min_year` onward.

    Queries Semantic Scholar first. Falls back to CORE only if Semantic Scholar raises or
    returns an empty list, and only if `CORE_API_KEY` is set (CORE is skipped, not attempted,
    when unset). Returns whichever provider's results were obtained first (non-empty), or an
    empty list if both providers ran and both returned nothing.

    Raises `SourceSearchError` only if every attempted provider failed with an error — a
    provider returning zero results is not treated as failure and does not by itself trigger
    the error path (though it does trigger the CORE fallback).
    """
    errors: list[Exception] = []

    async with httpx.AsyncClient(
        base_url=_SEMANTIC_SCHOLAR_BASE_URL, timeout=_DEFAULT_TIMEOUT_SECONDS
    ) as client:
        try:
            results = await _search_semantic_scholar(
                client, query, min_year=min_year, limit=limit
            )
            if results:
                return results
        except SourceSearchError as exc:
            errors.append(exc)

    core_api_key = os.environ.get("CORE_API_KEY", "")
    if not core_api_key:
        if errors:
            raise SourceSearchError(
                "Semantic Scholar failed and CORE_API_KEY is not set for fallback"
            ) from errors[0]
        return []

    async with httpx.AsyncClient(
        base_url=_CORE_BASE_URL, timeout=_DEFAULT_TIMEOUT_SECONDS
    ) as client:
        try:
            return await _search_core(client, query, min_year=min_year, limit=limit)
        except SourceSearchError as exc:
            errors.append(exc)

    raise SourceSearchError(
        "All attempted providers failed: "
        + "; ".join(str(e) for e in errors)
    )
