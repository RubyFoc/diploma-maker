"""Tests for the vertical-slice endpoints: create project -> add chapter -> generate a draft via
chat -> accept it.

HTTP calls to DeepSeek are mocked with `respx` — no real network access, matching
`test_llm_routing.py`/`test_retry.py`'s pattern.
"""

import httpx
import respx
from fastapi.testclient import TestClient

_CHAT_URL = "https://api.deepseek.com/chat/completions"


def _success_response(content: str = "Generated chapter text.") -> httpx.Response:
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


def _fail_response() -> httpx.Response:
    return httpx.Response(500, json={"error": "boom"})


def test_create_project_returns_empty_chapters(client: TestClient) -> None:
    response = client.post("/projects", json={"title": "My Thesis"})

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "My Thesis"
    assert body["chapters"] == []
    assert "id" in body
    assert "created_at" in body


def test_create_project_defaults_title_when_omitted(client: TestClient) -> None:
    response = client.post("/projects", json={})

    assert response.status_code == 201
    assert response.json()["title"] == "Untitled Thesis"


def test_create_project_defaults_title_when_empty(client: TestClient) -> None:
    response = client.post("/projects", json={"title": ""})

    assert response.status_code == 201
    assert response.json()["title"] == "Untitled Thesis"


def test_get_project_404s_for_unknown_id(client: TestClient) -> None:
    response = client.get("/projects/does-not-exist")

    assert response.status_code == 404


def test_full_project_chapter_flow(client: TestClient) -> None:
    create_response = client.post("/projects", json={"title": "Thesis"})
    project_id = create_response.json()["id"]

    empty_get = client.get(f"/projects/{project_id}")
    assert empty_get.status_code == 200
    assert empty_get.json()["chapters"] == []

    chapter_response = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}
    )
    assert chapter_response.status_code == 201
    chapter_body = chapter_response.json()
    assert chapter_body["title"] == "Introduction"
    assert chapter_body["project_id"] == project_id
    assert chapter_body["order"] == 0
    assert chapter_body["accepted_content"] is None
    assert chapter_body["pending_draft"] is None
    chapter_id = chapter_body["id"]

    populated_get = client.get(f"/projects/{project_id}")
    assert populated_get.status_code == 200
    populated_body = populated_get.json()
    assert len(populated_body["chapters"]) == 1
    fetched_chapter = populated_body["chapters"][0]
    assert fetched_chapter["id"] == chapter_id
    assert fetched_chapter["accepted_content"] is None
    assert fetched_chapter["pending_draft"] is None


def test_create_chapter_404s_for_unknown_project(client: TestClient) -> None:
    response = client.post(
        "/projects/does-not-exist/chapters", json={"title": "Introduction"}
    )

    assert response.status_code == 404


@respx.mock
def test_generate_draft_creates_and_returns_draft_version(client: TestClient) -> None:
    respx.post(_CHAT_URL).mock(return_value=_success_response("Draft chapter body."))

    project_id = client.post("/projects", json={"title": "Thesis"}).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write an introduction about renewable energy."},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["chapter_id"] == chapter_id
    assert body["content"] == "Draft chapter body."
    assert body["status"] == "draft"
    assert body["version_number"] == 0

    project_after = client.get(f"/projects/{project_id}").json()
    pending_draft = project_after["chapters"][0]["pending_draft"]
    assert pending_draft is not None
    assert pending_draft["id"] == body["id"]
    assert project_after["chapters"][0]["accepted_content"] is None


@respx.mock
def test_generate_draft_llm_failure_returns_502(client: TestClient) -> None:
    respx.post(_CHAT_URL).mock(return_value=_fail_response())

    project_id = client.post("/projects", json={"title": "Thesis"}).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
    )

    assert response.status_code == 502


def test_generate_draft_404s_for_unknown_chapter(client: TestClient) -> None:
    project_id = client.post("/projects", json={"title": "Thesis"}).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/does-not-exist/generate",
        json={"instruction": "Write something."},
    )

    assert response.status_code == 404


def test_generate_draft_404s_when_chapter_belongs_to_other_project(client: TestClient) -> None:
    project_a = client.post("/projects", json={"title": "Thesis A"}).json()["id"]
    project_b = client.post("/projects", json={"title": "Thesis B"}).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_a}/chapters", json={"title": "Introduction"}
    ).json()["id"]

    response = client.post(
        f"/projects/{project_b}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
    )

    assert response.status_code == 404


def test_accept_draft_404s_for_unknown_version(client: TestClient) -> None:
    response = client.post("/versions/does-not-exist/accept")

    assert response.status_code == 404


@respx.mock
def test_accept_already_accepted_draft_returns_409(client: TestClient) -> None:
    respx.post(_CHAT_URL).mock(return_value=_success_response("Draft body."))

    project_id = client.post("/projects", json={"title": "Thesis"}).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}
    ).json()["id"]
    draft = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
    ).json()

    first_accept = client.post(f"/versions/{draft['id']}/accept")
    assert first_accept.status_code == 200
    assert first_accept.json()["status"] == "accepted"

    second_accept = client.post(f"/versions/{draft['id']}/accept")
    assert second_accept.status_code == 409
