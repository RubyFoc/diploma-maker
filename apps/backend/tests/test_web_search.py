"""Tests for `sources.web_search` (user request): a last-resort general-web grounding fallback
via Google Custom Search, for required sources no academic API indexes at all.
"""

import httpx
import pytest
import respx

from diploma_backend.sources.web_search import WebSearchError, web_search

_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"


class TestWebSearch:
    async def test_raises_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_CSE_CX", raising=False)

        with pytest.raises(WebSearchError):
            await web_search("some query")

    async def test_raises_when_only_api_key_is_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_CSE_API_KEY", "key")
        monkeypatch.delenv("GOOGLE_CSE_CX", raising=False)

        with pytest.raises(WebSearchError):
            await web_search("some query")

    @respx.mock
    async def test_returns_parsed_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_CSE_API_KEY", "key")
        monkeypatch.setenv("GOOGLE_CSE_CX", "cx-id")
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "title": "Some Journal Article",
                            "link": "https://example.com/article",
                            "snippet": "A short excerpt of the article.",
                        }
                    ]
                },
            )
        )

        results = await web_search("some query")

        assert len(results) == 1
        assert results[0].title == "Some Journal Article"
        assert results[0].link == "https://example.com/article"
        assert results[0].snippet == "A short excerpt of the article."

    @respx.mock
    async def test_skips_items_missing_a_snippet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_CSE_API_KEY", "key")
        monkeypatch.setenv("GOOGLE_CSE_CX", "cx-id")
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": [{"title": "No snippet here", "link": "https://example.com/x"}]},
            )
        )

        results = await web_search("some query")

        assert results == []

    @respx.mock
    async def test_returns_empty_list_when_no_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_CSE_API_KEY", "key")
        monkeypatch.setenv("GOOGLE_CSE_CX", "cx-id")
        respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json={}))

        assert await web_search("some query") == []

    @respx.mock
    async def test_raises_on_http_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_CSE_API_KEY", "key")
        monkeypatch.setenv("GOOGLE_CSE_CX", "cx-id")
        respx.get(_SEARCH_URL).mock(return_value=httpx.Response(500))

        with pytest.raises(WebSearchError):
            await web_search("some query")

    @respx.mock
    async def test_respects_the_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_CSE_API_KEY", "key")
        monkeypatch.setenv("GOOGLE_CSE_CX", "cx-id")
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"title": f"Result {i}", "link": f"https://example.com/{i}", "snippet": "s"}
                        for i in range(5)
                    ]
                },
            )
        )

        results = await web_search("some query", limit=2)

        assert len(results) == 2
