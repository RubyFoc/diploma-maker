"""Tests for TASK-E15-1's "insert at anchor" generation mode
(`GenerateDraftRequest.target_block_id`) on `POST /projects/{project_id}/chapters/{chapter_id}
/generate`.

Only covers TASK-E15-1's scope: the anchor lookup / 404 cases and the happy-path splice.
Lock-freshness enforcement over the anchor (TASK-E15-2) and the frontend (TASK-E15-3) are
separate, later tasks with their own tests.
"""

import asyncio

import httpx
import respx
from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.main import app
from diploma_backend.versions.service import accept_draft_version, create_draft_version

_CHAT_URL = "https://api.deepseek.com/chat/completions"
_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    response = client.post("/auth/register", json={"email": email, "password": "hunter22"})
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _setup_project_and_chapter(client: TestClient, headers: dict) -> tuple[str, str]:
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    return project_id, chapter_id


def _accept_chapter_content(client: TestClient, chapter_id: str, content: str) -> dict:
    """Bypasses the LLM-backed `/generate` endpoint to seed an accepted version + manifest
    directly, matching `test_locks_router.py`'s pattern. Returns the accepted version's manifest
    (as plain dicts) so a test can pick an anchor block id."""
    db = app.dependency_overrides[get_database]()

    async def _create_and_accept() -> dict:
        draft = await create_draft_version(db, chapter_id, content=content)
        accepted = await accept_draft_version(db, draft.id)
        return accepted.model_dump()

    return asyncio.run(_create_and_accept())


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


def _mock_generate_and_humanize(generated: str = "Inserted paragraph.") -> None:
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=_success_response(generated)
    )
    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(
        return_value=_success_response("Humanized inserted paragraph.")
    )


@respx.mock
def test_anchor_generation_no_accepted_version_returns_404(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Add a sentence.", "target_block_id": "does-not-exist"},
        headers=headers,
    )

    assert response.status_code == 404


@respx.mock
def test_anchor_generation_missing_block_returns_404(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    _accept_chapter_content(client, chapter_id, "First paragraph.\nSecond paragraph.")

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Add a sentence.", "target_block_id": "does-not-exist"},
        headers=headers,
    )

    assert response.status_code == 404


@respx.mock
def test_anchor_generation_happy_path_splices_new_draft(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.\nSecond paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]

    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    _mock_generate_and_humanize()

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Add a transitional sentence.", "target_block_id": anchor_block_id},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    version = body["version"]
    assert version["manifest"] is not None
    assert [block["content"] for block in version["manifest"]] == [
        "First paragraph.",
        "Humanized inserted paragraph.",
        "Second paragraph.",
    ]
    # The unrelated pre-existing block keeps its original id (ADR-0011 stability contract).
    assert version["manifest"][0]["id"] == anchor_block_id
    assert version["manifest"][2]["id"] == accepted["manifest"][1]["id"]

    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    sent_body = generation_call.request.content.decode()
    # The anchor is the chapter's first block, so only the "after" neighbor is available as
    # context (see `_anchor_context_excerpts`).
    assert "Second paragraph." in sent_body


@respx.mock
def test_full_chapter_generation_unaffected_when_target_block_id_omitted(
    client: TestClient,
) -> None:
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    _mock_generate_and_humanize(generated="Full chapter draft.")

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write the introduction."},
        headers=headers,
    )

    assert response.status_code == 201
    version = response.json()["version"]
    assert version["content"] == "Humanized inserted paragraph."
