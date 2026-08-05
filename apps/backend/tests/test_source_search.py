"""Tests for TASK-E04-2 (Semantic Scholar / CORE search integration, recency filter).

HTTP calls are mocked with `respx` — no real network access, per
`docs/engineering/best-practices.md`.
"""

import httpx
import pytest
import respx

from diploma_backend.sources.search import SourceSearchError, search_sources

_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_CORE_URL = "https://api.core.ac.uk/v3/search/works"


def _semantic_scholar_response(papers: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"total": len(papers), "offset": 0, "data": papers})


def _core_response(results: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"totalHits": len(results), "results": results})


_SAMPLE_PAPER = {
    "paperId": "abc123",
    "title": "A Study of Things",
    "authors": [{"authorId": "1", "name": "Jane Doe"}],
    "year": 2021,
    "abstract": "An abstract.",
    "url": "https://semanticscholar.org/paper/abc123",
}

_SAMPLE_WORK = {
    "id": "core-999",
    "title": "Another Study",
    "authors": [{"name": "John Smith"}],
    "yearPublished": 2019,
    "abstract": "Another abstract.",
    "downloadUrl": "https://core.ac.uk/download/core-999",
}


@respx.mock
async def test_semantic_scholar_success() -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(
        return_value=_semantic_scholar_response([_SAMPLE_PAPER])
    )

    results = await search_sources("machine learning")

    assert len(results) == 1
    result = results[0]
    assert result.title == "A Study of Things"
    assert result.authors == ["Jane Doe"]
    assert result.year == 2021
    assert result.abstract == "An abstract."
    assert result.url == "https://semanticscholar.org/paper/abc123"
    assert result.provider == "semantic_scholar"
    assert result.external_id == "abc123"


@respx.mock
async def test_recency_filter_passed_to_semantic_scholar_as_query_param() -> None:
    route = respx.get(_SEMANTIC_SCHOLAR_URL).mock(
        return_value=_semantic_scholar_response([_SAMPLE_PAPER])
    )

    await search_sources("machine learning", min_year=2015)

    sent_params = route.calls.last.request.url.params
    assert sent_params["year"] == "2015-"


@respx.mock
async def test_empty_results_from_both_providers_returns_empty_list(monkeypatch) -> None:
    monkeypatch.setenv("CORE_API_KEY", "core-test-key")
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=_semantic_scholar_response([]))
    respx.get(_CORE_URL).mock(return_value=_core_response([]))

    results = await search_sources("an extremely obscure query")

    assert results == []


@respx.mock
async def test_semantic_scholar_empty_falls_back_to_core_when_key_set(monkeypatch) -> None:
    monkeypatch.setenv("CORE_API_KEY", "core-test-key")
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=_semantic_scholar_response([]))
    respx.get(_CORE_URL).mock(return_value=_core_response([_SAMPLE_WORK]))

    results = await search_sources("machine learning")

    assert len(results) == 1
    result = results[0]
    assert result.title == "Another Study"
    assert result.authors == ["John Smith"]
    assert result.year == 2019
    assert result.provider == "core"
    assert result.external_id == "core-999"


@respx.mock
async def test_semantic_scholar_fails_falls_back_to_core_success(monkeypatch) -> None:
    monkeypatch.setenv("CORE_API_KEY", "core-test-key")
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(500))
    respx.get(_CORE_URL).mock(return_value=_core_response([_SAMPLE_WORK]))

    results = await search_sources("machine learning")

    assert len(results) == 1
    assert results[0].provider == "core"


@respx.mock
async def test_semantic_scholar_fails_no_core_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("CORE_API_KEY", raising=False)
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(SourceSearchError):
        await search_sources("machine learning")


@respx.mock
async def test_both_providers_fail_raises(monkeypatch) -> None:
    monkeypatch.setenv("CORE_API_KEY", "core-test-key")
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(500))
    respx.get(_CORE_URL).mock(return_value=httpx.Response(503))

    with pytest.raises(SourceSearchError):
        await search_sources("machine learning")


@respx.mock
async def test_core_not_attempted_when_key_unset_and_semantic_scholar_succeeds(
    monkeypatch,
) -> None:
    monkeypatch.delenv("CORE_API_KEY", raising=False)
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=_semantic_scholar_response([]))

    results = await search_sources("machine learning")

    assert results == []
    assert _CORE_URL not in [str(c.request.url) for c in respx.calls]


@respx.mock
async def test_semantic_scholar_uses_api_key_header_when_set(monkeypatch) -> None:
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "ss-test-key")
    route = respx.get(_SEMANTIC_SCHOLAR_URL).mock(
        return_value=_semantic_scholar_response([_SAMPLE_PAPER])
    )

    await search_sources("machine learning")

    assert route.calls.last.request.headers["x-api-key"] == "ss-test-key"


@respx.mock
async def test_core_recency_filter_appended_to_query(monkeypatch) -> None:
    monkeypatch.setenv("CORE_API_KEY", "core-test-key")
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=_semantic_scholar_response([]))
    route = respx.get(_CORE_URL).mock(return_value=_core_response([_SAMPLE_WORK]))

    await search_sources("machine learning", min_year=2018)

    sent_params = route.calls.last.request.url.params
    assert "yearPublished>=2018" in sent_params["q"]
