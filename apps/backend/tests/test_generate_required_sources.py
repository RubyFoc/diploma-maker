"""Tests for TASK-E14-3: boosting a project's must-cite sources (`sources.required`) into
generation's RAG excerpts, and reporting unmet ones via `GenerateDraftResponse.unmet_required_sources`.

Also covers the user-requested grounding fallback chain (`_fetch_required_source_excerpts`):
direct-URL fetch -> academic search -> general web search -> unmet, each cached on success.
"""

import socket
from unittest.mock import patch

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

_CHAT_URL = "https://api.deepseek.com/chat/completions"
_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"


def _mock_public_dns():
    return patch(
        "socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    response = client.post("/auth/register", json={"email": email, "password": "hunter22"})
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _success_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "deepseek-v4-pro",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def _mock_generate_and_humanize() -> None:
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=_success_response("Draft chapter body.")
    )
    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(
        return_value=_success_response("Humanized chapter body.")
    )


def _semantic_scholar_response(papers: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"data": papers})


def _setup_project_and_chapter(client: TestClient, headers: dict) -> tuple[str, str]:
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    return project_id, chapter_id


@respx.mock
def test_required_source_is_boosted_into_the_prompt(client: TestClient) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(
        return_value=_semantic_scholar_response(
            [
                {
                    "paperId": "abc123",
                    "title": "Foundations of Widget Theory",
                    "authors": [{"name": "Jane Doe"}],
                    "year": 2019,
                    "abstract": "This foundational work establishes widget theory.",
                    "url": None,
                }
            ]
        )
    )
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    client.post(
        f"/projects/{project_id}/required-sources",
        json={"author": "Jane Doe", "title": "Foundations of Widget Theory"},
        headers=headers,
    )

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write about widgets."},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["unmet_required_sources"] == []
    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    sent_body = generation_call.request.content.decode()
    assert "Foundations of Widget Theory" in sent_body
    assert "This foundational work establishes widget theory." in sent_body
    # Marked distinctly from an ordinary RAG excerpt (user report: required sources were being
    # silently skipped even when found, since the model had no signal that citing them wasn't
    # optional) — see `_fetch_required_source_excerpts`'s `"[REQUIRED]"` prefix. Prefixed with the
    # source's own author/title label (consistent across every grounding path — direct-URL fetch
    # and web search have no natural "title (year): abstract" shape of their own to fall back on).
    assert "[REQUIRED] Jane Doe — Foundations of Widget Theory: Foundations of Widget Theory" in sent_body


@respx.mock
def test_unmet_required_source_is_reported_not_fabricated(client: TestClient) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=_semantic_scholar_response([]))
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    client.post(
        f"/projects/{project_id}/required-sources",
        json={"author": "Jane Doe", "title": "Foundations of Widget Theory"},
        headers=headers,
    )

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write about widgets."},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["unmet_required_sources"] == ["Jane Doe — Foundations of Widget Theory"]


@respx.mock
def test_unmet_required_source_label_omits_title_when_absent(client: TestClient) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=_semantic_scholar_response([]))
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    client.post(
        f"/projects/{project_id}/required-sources", json={"author": "Jane Doe"}, headers=headers
    )

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write about widgets."},
        headers=headers,
    )

    assert response.json()["unmet_required_sources"] == ["Jane Doe"]


@respx.mock
def test_no_required_sources_means_no_unmet_and_generation_unaffected(client: TestClient) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=_semantic_scholar_response([]))
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write about widgets."},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["unmet_required_sources"] == []


@respx.mock
def test_required_source_search_failure_reports_unmet_and_fails_open(client: TestClient) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(500))
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    client.post(
        f"/projects/{project_id}/required-sources", json={"author": "Jane Doe"}, headers=headers
    )

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write about widgets."},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["unmet_required_sources"] == ["Jane Doe"]


@respx.mock
def test_required_source_grounds_directly_from_its_own_url_without_searching(
    client: TestClient,
) -> None:
    """User report: a required source's own citation URL was collected but never used, forcing a
    keyword search that regional-journal literature almost never turns up. A source with a `url`
    should ground from it directly — academic search should never even be attempted."""
    semantic_scholar = respx.get(_SEMANTIC_SCHOLAR_URL).mock(
        return_value=_semantic_scholar_response([])
    )
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    client.post(
        f"/projects/{project_id}/required-sources",
        json={"author": "Jane Doe", "url": "http://example.com/paper-view"},
        headers=headers,
    )

    with _mock_public_dns():
        respx.get("http://example.com/paper-view").mock(
            return_value=httpx.Response(
                200,
                content=b"Content fetched directly from the source's own URL.",
                headers={"content-type": "text/html"},
            )
        )
        response = client.post(
            f"/projects/{project_id}/chapters/{chapter_id}/generate",
            json={"instruction": "Write about widgets."},
            headers=headers,
        )

    assert response.status_code == 201
    assert response.json()["unmet_required_sources"] == []
    # `_fetch_rag_excerpts` (general, instruction-driven grounding) also calls Semantic Scholar,
    # so the endpoint is hit overall — what matters is that it's never queried for *this*
    # required source specifically, since its `url` should ground it directly instead.
    assert all(b"Jane+Doe" not in call.request.url.query for call in semantic_scholar.calls)
    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    assert "Content fetched directly from the source's own URL." in generation_call.request.content.decode()


@respx.mock
def test_required_source_falls_back_to_academic_search_when_url_fetch_fails(
    client: TestClient,
) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(
        return_value=_semantic_scholar_response(
            [
                {
                    "paperId": "abc123",
                    "title": "Foundations of Widget Theory",
                    "authors": [{"name": "Jane Doe"}],
                    "year": 2019,
                    "abstract": "This foundational work establishes widget theory.",
                    "url": None,
                }
            ]
        )
    )
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    client.post(
        f"/projects/{project_id}/required-sources",
        json={
            "author": "Jane Doe",
            "title": "Foundations of Widget Theory",
            "url": "http://example.com/missing.pdf",
        },
        headers=headers,
    )

    with _mock_public_dns():
        respx.get("http://example.com/missing.pdf").mock(return_value=httpx.Response(404))
        response = client.post(
            f"/projects/{project_id}/chapters/{chapter_id}/generate",
            json={"instruction": "Write about widgets."},
            headers=headers,
        )

    assert response.status_code == 201
    assert response.json()["unmet_required_sources"] == []
    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    assert "This foundational work establishes widget theory." in generation_call.request.content.decode()


@respx.mock
def test_required_source_falls_back_to_web_search_when_academic_search_finds_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User request: literature academic APIs don't index at all (common for regional-journal/
    student-conference citations) should still ground via a general web search, not go unmet."""
    monkeypatch.setenv("GOOGLE_CSE_API_KEY", "key")
    monkeypatch.setenv("GOOGLE_CSE_CX", "cx-id")
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=_semantic_scholar_response([]))
    respx.get(_GOOGLE_CSE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "A Regional Journal Article",
                        "link": "https://example.com/article",
                        "snippet": "An excerpt found via general web search.",
                    }
                ]
            },
        )
    )
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    client.post(
        f"/projects/{project_id}/required-sources", json={"author": "Jane Doe"}, headers=headers
    )

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write about widgets."},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["unmet_required_sources"] == []
    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    assert "An excerpt found via general web search." in generation_call.request.content.decode()


@respx.mock
def test_required_source_still_unmet_when_web_search_is_not_configured(
    client: TestClient,
) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=_semantic_scholar_response([]))
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    client.post(
        f"/projects/{project_id}/required-sources", json={"author": "Jane Doe"}, headers=headers
    )

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write about widgets."},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["unmet_required_sources"] == ["Jane Doe"]


@respx.mock
def test_required_source_grounding_is_cached_and_not_refetched_on_a_second_generation(
    client: TestClient,
) -> None:
    """A direct-URL fetch shouldn't repeat on every chapter's generation call — expensive and
    slow with many required sources across many chapters (user request)."""
    semantic_scholar = respx.get(_SEMANTIC_SCHOLAR_URL).mock(
        return_value=_semantic_scholar_response([])
    )
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    client.post(
        f"/projects/{project_id}/required-sources",
        json={"author": "Jane Doe", "url": "http://example.com/paper-view"},
        headers=headers,
    )

    with _mock_public_dns():
        url_fetch = respx.get("http://example.com/paper-view").mock(
            return_value=httpx.Response(
                200, content=b"Cached excerpt content.", headers={"content-type": "text/html"}
            )
        )
        first = client.post(
            f"/projects/{project_id}/chapters/{chapter_id}/generate",
            json={"instruction": "Write about widgets."},
            headers=headers,
        )
        second = client.post(
            f"/projects/{project_id}/chapters/{chapter_id}/generate",
            json={"instruction": "Write more about widgets."},
            headers=headers,
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert url_fetch.call_count == 1
    assert all(b"Jane+Doe" not in call.request.url.query for call in semantic_scholar.calls)
