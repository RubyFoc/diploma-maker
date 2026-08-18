"""Tests for TASK-E15-1's "insert at anchor" generation mode
(`GenerateDraftRequest.target_block_id`) on `POST /projects/{project_id}/chapters/{chapter_id}
/generate`, plus TASK-E15-2's deterministic lock guard (reject-and-reroute, full-lock 409, and
the pre-persistence TOCTOU re-check) layered on top of it.

The frontend (TASK-E15-3) is a separate, later task with its own tests.
"""

import asyncio
import json

import httpx
import respx
from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.locks.service import lock_block
from diploma_backend.main import app
from diploma_backend.versions.service import (
    accept_draft_version,
    create_draft_version,
    list_versions_for_chapter,
)

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
def test_anchor_generation_system_prompt_forbids_appending_a_bibliography_section(
    client: TestClient,
) -> None:
    """Same user report as `test_projects.py`'s equivalent test, for the anchor-mode prompt:
    an inserted snippet must never carry its own references list — the model is only told to
    cite in-text, and nothing routes a references list anywhere in the document."""
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.\nSecond paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]

    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    _mock_generate_and_humanize()

    client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Add a transitional sentence.", "target_block_id": anchor_block_id},
        headers=headers,
    )

    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    system_content = json.loads(generation_call.request.content)["messages"][0]["content"]
    assert "Список использованных источников" in system_content
    assert "never append" in system_content.lower()


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
    assert response.json()["used_block_id"] is None
    assert response.json()["rerouted_from_block_id"] is None


def _lock_block(chapter_id: str, block_id: str, block_content_hash: str) -> None:
    """Places a lock directly against the in-memory fake DB, bypassing the HTTP lock endpoint —
    matches `_accept_chapter_content`'s bypass pattern above."""
    db = app.dependency_overrides[get_database]()
    asyncio.run(lock_block(db, chapter_id, block_id, block_content_hash))


@respx.mock
def test_anchor_generation_unlocked_anchor_is_unaffected_by_locks_elsewhere(
    client: TestClient,
) -> None:
    """Confirms the non-locked-anchor path's response shape is untouched: `used_block_id`/
    `rerouted_from_block_id` behave exactly as the no-locks-at-all case even when an unrelated
    lock exists elsewhere in the chapter."""
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.\nSecond paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    other_block = accepted["manifest"][1]
    _lock_block(chapter_id, other_block["id"], other_block["content_hash"])

    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    _mock_generate_and_humanize()

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Add a transitional sentence.", "target_block_id": anchor_block_id},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["used_block_id"] == anchor_block_id
    assert body["rerouted_from_block_id"] is None


@respx.mock
def test_anchor_generation_prompt_labels_locked_neighbor_as_read_only(
    client: TestClient,
) -> None:
    """A neighboring block that is itself locked must appear in the prompt sent to the model as
    explicitly-labeled protected/read-only context (TASK-E15-2) — advisory only, not the actual
    enforcement."""
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.\nSecond paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    locked_neighbor = accepted["manifest"][1]
    _lock_block(chapter_id, locked_neighbor["id"], locked_neighbor["content_hash"])

    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    _mock_generate_and_humanize()

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Add a transitional sentence.", "target_block_id": anchor_block_id},
        headers=headers,
    )

    assert response.status_code == 201
    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    sent_body = generation_call.request.content.decode()
    assert "protected" in sent_body.lower()
    assert "Second paragraph." in sent_body


@respx.mock
def test_anchor_generation_reroutes_when_requested_anchor_is_locked(
    client: TestClient,
) -> None:
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(
        client, chapter_id, "First paragraph.\nSecond paragraph.\nThird paragraph."
    )
    requested_block = accepted["manifest"][1]
    forward_neighbor = accepted["manifest"][2]
    _lock_block(chapter_id, requested_block["id"], requested_block["content_hash"])

    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    _mock_generate_and_humanize()

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={
            "instruction": "Add a transitional sentence.",
            "target_block_id": requested_block["id"],
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["used_block_id"] == forward_neighbor["id"]
    assert body["used_block_id"] != requested_block["id"]
    assert body["rerouted_from_block_id"] == requested_block["id"]

    version = body["version"]
    assert [block["content"] for block in version["manifest"]] == [
        "First paragraph.",
        "Second paragraph.",
        "Third paragraph.",
        "Humanized inserted paragraph.",
    ]


@respx.mock
def test_anchor_generation_fully_locked_chapter_returns_409_without_calling_the_llm(
    client: TestClient,
) -> None:
    headers = _auth_headers(client)
    project_id, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.\nSecond paragraph.")
    for block in accepted["manifest"]:
        _lock_block(chapter_id, block["id"], block["content_hash"])

    generation_mock = respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=_success_response("Should never be generated.")
    )

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={
            "instruction": "Add a transitional sentence.",
            "target_block_id": accepted["manifest"][0]["id"],
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert generation_mock.call_count == 0


@respx.mock
def test_anchor_generation_race_condition_before_persistence_returns_409(
    client: TestClient, monkeypatch
) -> None:
    """Simulates TASK-E15-2's TOCTOU race — a lock lands on the resolved anchor during the LLM
    round-trip, after the pre-LLM guard passed but before persistence — by making the
    pre-persistence re-check (`reverify_anchor_resolution`) fail, mirroring what a real
    concurrently-placed lock would produce (see `test_locks_service.py`'s direct-race coverage of
    `reverify_anchor_resolution` itself)."""
    import diploma_backend.projects.router as router_module
    from diploma_backend.locks.service import AnchorResolutionError

    async def _always_stale(db, chapter_id, resolution):
        raise AnchorResolutionError("anchor is no longer valid: simulated concurrent lock")

    monkeypatch.setattr(router_module, "reverify_anchor_resolution", _always_stale)

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

    assert response.status_code == 409

    db = app.dependency_overrides[get_database]()
    versions = asyncio.run(list_versions_for_chapter(db, chapter_id))
    assert len(versions) == 1  # only the original accepted version — no draft was persisted
