"""Tests for `sources.tasks.search_sources_task` (ADR-0013, TASK-E17-2).

HTTP calls are mocked with `respx`, matching `test_source_search.py`'s pattern. Per ADR-0013
addendum point 4, `.delay()` is called from plain sync test functions, never `async def` test
code.
"""

import httpx
import pytest
import respx

from diploma_backend.sources.search import SourceSearchError
from diploma_backend.sources.tasks import search_sources_task

_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

_SAMPLE_PAPER = {
    "paperId": "abc123",
    "title": "A Study of Things",
    "authors": [{"authorId": "1", "name": "Jane Doe"}],
    "year": 2021,
    "abstract": "An abstract.",
    "url": "https://semanticscholar.org/paper/abc123",
}


@respx.mock
def test_delay_runs_task_and_returns_dicts() -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(
        return_value=httpx.Response(200, json={"total": 1, "offset": 0, "data": [_SAMPLE_PAPER]})
    )

    async_result = search_sources_task.delay("machine learning")
    results = async_result.get()

    assert results == [
        {
            "title": "A Study of Things",
            "authors": ["Jane Doe"],
            "year": 2021,
            "abstract": "An abstract.",
            "url": "https://semanticscholar.org/paper/abc123",
            "provider": "semantic_scholar",
            "external_id": "abc123",
            "venue": None,
        }
    ]


@respx.mock
def test_all_providers_failing_propagates_as_real_exception(monkeypatch) -> None:
    monkeypatch.delenv("CORE_API_KEY", raising=False)
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(SourceSearchError):
        search_sources_task.delay("machine learning")
