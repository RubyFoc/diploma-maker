"""Tests for TASK-E14-3: boosting a project's must-cite sources (`sources.required`) into
generation's RAG excerpts, and reporting unmet ones via `GenerateDraftResponse.unmet_required_sources`.
"""

import httpx
import respx
from fastapi.testclient import TestClient

_CHAT_URL = "https://api.deepseek.com/chat/completions"
_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


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
