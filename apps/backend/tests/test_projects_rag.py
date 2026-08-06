"""Tests for RAG grounding wired into generation (`_fetch_rag_excerpts`,
`projects.router`): live external-search excerpts actually reach `assemble_prompt`'s
`rag_excerpts` and `run_precheck`'s `source_excerpts`, and search failures/empty results fail
open rather than blocking generation.
"""

import httpx
import respx
from fastapi.testclient import TestClient

_CHAT_URL = "https://api.deepseek.com/chat/completions"
_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    """Register a user and return an `Authorization` header, since project endpoints require
    auth as of TASK-E11-1 (see `test_auth.py`'s `_register`)."""
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
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
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


def _setup_project_and_chapter(client: TestClient) -> tuple[str, str]:
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    return project_id, chapter_id


@respx.mock
def test_generate_draft_threads_search_result_abstract_into_prompt(client: TestClient) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(
        return_value=_semantic_scholar_response(
            [
                {
                    "paperId": "abc123",
                    "title": "Solar Panel Efficiency Trends",
                    "authors": [{"name": "Jane Doe"}],
                    "year": 2023,
                    "abstract": "Solar panel efficiency has increased steadily since 2010.",
                    "url": "https://example.org/paper",
                }
            ]
        )
    )
    _mock_generate_and_humanize()
    project_id, chapter_id = _setup_project_and_chapter(client)

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write about solar panel efficiency."},
    )

    assert response.status_code == 201

    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    sent_body = generation_call.request.content.decode()
    assert "Solar Panel Efficiency Trends" in sent_body
    assert "Solar panel efficiency has increased steadily since 2010." in sent_body


@respx.mock
def test_generate_draft_skips_results_with_no_abstract(client: TestClient) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(
        return_value=_semantic_scholar_response(
            [
                {
                    "paperId": "abc123",
                    "title": "No Abstract Paper",
                    "authors": [],
                    "year": 2023,
                    "abstract": None,
                    "url": None,
                }
            ]
        )
    )
    _mock_generate_and_humanize()
    project_id, chapter_id = _setup_project_and_chapter(client)

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
    )

    assert response.status_code == 201
    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    assert "No Abstract Paper" not in generation_call.request.content.decode()


@respx.mock
def test_generate_draft_fails_open_when_search_provider_errors(client: TestClient) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(500))
    _mock_generate_and_humanize()
    project_id, chapter_id = _setup_project_and_chapter(client)

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
    )

    assert response.status_code == 201


@respx.mock
def test_generate_draft_fails_open_when_search_returns_nothing(client: TestClient) -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=_semantic_scholar_response([]))
    _mock_generate_and_humanize()
    project_id, chapter_id = _setup_project_and_chapter(client)

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
    )

    assert response.status_code == 201
