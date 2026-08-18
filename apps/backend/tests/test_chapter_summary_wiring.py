"""Tests for the accept-time chapter-summarization wiring (ADR-0003 addendum, follow-up to
TASK-E03-2/E17): `accept_draft_version_endpoint` dispatching `summarize_chapter_task` and
persisting its result via `update_chapter_summary`, and `assemble_prompt`'s `chapter_summaries`
prefix being populated with other chapters' persisted summaries on later generation calls.

HTTP calls are mocked with `respx`, matching `test_projects.py`'s pattern. All three fast-tier
calls a full generate-accept round trip can make (humanization, project-title auto-generation, and
now accept-time summarization) share the same `deepseek-v4-flash` model, so they're distinguished
by a marker substring unique to each call's system prompt, mirroring `test_projects.py`'s
`_is_title_request`/`_TITLE_PROMPT_MARKER` pattern.
"""

import asyncio
import json

import httpx
import respx
from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.main import app
from diploma_backend.projects.service import list_chapters_for_project

_CHAT_URL = "https://api.deepseek.com/chat/completions"
_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

_TITLE_PROMPT_MARKER = "thesis title"
_SUMMARY_PROMPT_MARKER = "compact academic chapter text"


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    response = client.post("/auth/register", json={"email": email, "password": "hunter22"})
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _mock_empty_rag_search() -> None:
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(200, json={"data": []}))


def _success_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "deepseek-v4-flash",
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


def _fail_response() -> httpx.Response:
    return httpx.Response(500, json={"error": "boom"})


def _mock_generation_pipeline(
    *,
    generated: str = "Draft chapter body.",
    humanized: str = "Humanized chapter body.",
    summary_response: httpx.Response | None = None,
) -> None:
    """Mocks the heavy-tier draft-generation call plus all three fast-tier calls a generate-then-
    accept round trip makes (humanization, title auto-generation, accept-time summarization),
    routing each fast-tier request by its system prompt's marker substring.

    `summary_response` defaults to a successful response with content `"Chapter summary text."`;
    pass a failure response (e.g. `_fail_response()`) to exercise the fail-open path.
    """
    _mock_empty_rag_search()
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=_success_response(generated)
    )
    resolved_summary_response = (
        summary_response if summary_response is not None else _success_response("Chapter summary text.")
    )

    def side_effect(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system_content = body["messages"][0]["content"]
        if _SUMMARY_PROMPT_MARKER in system_content:
            return resolved_summary_response
        if _TITLE_PROMPT_MARKER in system_content:
            return _success_response("Generated Title")
        return _success_response(humanized)

    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(side_effect=side_effect)


def _generate_and_accept(
    client: TestClient, project_id: str, chapter_id: str, headers: dict, instruction: str
) -> dict:
    draft = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": instruction},
        headers=headers,
    ).json()["version"]
    accept_response = client.post(f"/versions/{draft['id']}/accept")
    assert accept_response.status_code == 200
    return accept_response.json()


def _chapter_summary(chapter_id: str, project_id: str) -> str | None:
    db = app.dependency_overrides[get_database]()

    async def _fetch() -> str | None:
        chapters = await list_chapters_for_project(db, project_id)
        return next(chapter.summary for chapter in chapters if chapter.id == chapter_id)

    return asyncio.run(_fetch())


@respx.mock
def test_accept_triggers_summarization_and_persists_chapter_summary(client: TestClient) -> None:
    _mock_generation_pipeline(summary_response=_success_response("Chapter summary text."))

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    assert _chapter_summary(chapter_id, project_id) is None

    _generate_and_accept(client, project_id, chapter_id, headers, "Write something.")

    assert _chapter_summary(chapter_id, project_id) == "Chapter summary text."


@respx.mock
def test_summarization_failure_does_not_block_accept_endpoint(client: TestClient) -> None:
    _mock_generation_pipeline(summary_response=_fail_response())

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    accepted = _generate_and_accept(client, project_id, chapter_id, headers, "Write something.")

    assert accepted["status"] == "accepted"
    assert _chapter_summary(chapter_id, project_id) is None


@respx.mock
def test_generation_sends_other_chapters_persisted_summaries_in_prompt(client: TestClient) -> None:
    _mock_generation_pipeline(summary_response=_success_response("Summary of chapter one."))

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_one_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    chapter_two_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Literature Review"}, headers=headers
    ).json()["id"]

    _generate_and_accept(client, project_id, chapter_one_id, headers, "Write the introduction.")
    assert _chapter_summary(chapter_one_id, project_id) == "Summary of chapter one."

    client.post(
        f"/projects/{project_id}/chapters/{chapter_two_id}/generate",
        json={"instruction": "Write the literature review."},
        headers=headers,
    )

    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL
        and b'"deepseek-v4-pro"' in call.request.content
        and b"literature review" in call.request.content
    )
    sent_body = generation_call.request.content.decode()
    assert "Summary of chapter one." in sent_body


@respx.mock
def test_generation_includes_raw_excerpt_for_unaccepted_pending_chapter(client: TestClient) -> None:
    """User report: a bulk TOC/whole-document import leaves most chapters/subchapters/appendices
    as unaccepted pending drafts, so they had no persisted summary and were entirely invisible to
    later generation calls until each one was individually accepted first. A chapter with no
    summary but a pending draft should still contribute a raw excerpt."""
    _mock_generation_pipeline(humanized="Draft body about widgets and gadgets.")
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_one_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    chapter_two_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Literature Review"}, headers=headers
    ).json()["id"]

    # Generate but deliberately do NOT accept chapter one — it stays an unaccepted pending draft
    # with no summary.
    client.post(
        f"/projects/{project_id}/chapters/{chapter_one_id}/generate",
        json={"instruction": "Write the introduction."},
        headers=headers,
    )
    assert _chapter_summary(chapter_one_id, project_id) is None

    client.post(
        f"/projects/{project_id}/chapters/{chapter_two_id}/generate",
        json={"instruction": "Write the literature review."},
        headers=headers,
    )

    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL
        and b'"deepseek-v4-pro"' in call.request.content
        and b"literature review" in call.request.content
    )
    sent_body = generation_call.request.content.decode()
    assert "Introduction" in sent_body
    assert "Draft body about widgets and gadgets." in sent_body


@respx.mock
def test_generation_does_not_feed_a_chapter_its_own_pending_draft_as_context(
    client: TestClient,
) -> None:
    _mock_generation_pipeline(humanized="First draft text unique-marker-xyz.")
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write the introduction."},
        headers=headers,
    )
    # Regenerate the very same (still-unaccepted) chapter — its own pending draft from the call
    # above must not be fed back to itself as "other chapters' context".
    client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write the introduction again."},
        headers=headers,
    )

    generation_calls = [
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    ]
    assert len(generation_calls) == 2
    second_call_body = generation_calls[-1].request.content.decode()
    assert "unique-marker-xyz" not in second_call_body


@respx.mock
def test_generation_truncates_a_long_pending_excerpt(client: TestClient) -> None:
    _mock_generation_pipeline(humanized="X" * 2000)
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_one_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    chapter_two_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Literature Review"}, headers=headers
    ).json()["id"]

    client.post(
        f"/projects/{project_id}/chapters/{chapter_one_id}/generate",
        json={"instruction": "Write the introduction."},
        headers=headers,
    )
    client.post(
        f"/projects/{project_id}/chapters/{chapter_two_id}/generate",
        json={"instruction": "Write the literature review."},
        headers=headers,
    )

    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL
        and b'"deepseek-v4-pro"' in call.request.content
        and b"literature review" in call.request.content
    )
    sent_body = generation_call.request.content.decode()
    assert "X" * 601 not in sent_body
    assert "X" * 600 in sent_body
