"""Tests for TASK-E12-2's create/list-subchapters-under-a-parent endpoints (ADR-0014).

Exercises the HTTP endpoints only (storage-layer `create_chapter`/`list_subchapters` scoping is
already covered directly by `test_chapter_insertion.py`).
"""

from fastapi.testclient import TestClient


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    response = client.post("/auth/register", json={"email": email, "password": "hunter22"})
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_project(client: TestClient, headers: dict) -> str:
    response = client.post("/projects", json={"title": "My Thesis"}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def _create_chapter(client: TestClient, project_id: str, headers: dict, title: str) -> str:
    response = client.post(
        f"/projects/{project_id}/chapters", json={"title": title}, headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_create_subchapter_returns_chapter_detail_with_parent_id(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id = _create_project(client, headers)
    chapter_id = _create_chapter(client, project_id, headers, "Chapter 1")

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/subchapters",
        json={"title": "Section 1.1"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Section 1.1"
    assert body["parent_chapter_id"] == chapter_id
    assert body["project_id"] == project_id
    assert body["order"] == 0


def test_list_subchapters_returns_only_that_parents_children_in_order(
    client: TestClient,
) -> None:
    headers = _auth_headers(client)
    project_id = _create_project(client, headers)
    chapter_1 = _create_chapter(client, project_id, headers, "Chapter 1")
    chapter_2 = _create_chapter(client, project_id, headers, "Chapter 2")

    client.post(
        f"/projects/{project_id}/chapters/{chapter_1}/subchapters",
        json={"title": "Section 1.1"},
        headers=headers,
    )
    client.post(
        f"/projects/{project_id}/chapters/{chapter_1}/subchapters",
        json={"title": "Section 1.2"},
        headers=headers,
    )
    client.post(
        f"/projects/{project_id}/chapters/{chapter_2}/subchapters",
        json={"title": "Section 2.1"},
        headers=headers,
    )

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_1}/subchapters", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert [entry["title"] for entry in body] == ["Section 1.1", "Section 1.2"]
    assert all(entry["parent_chapter_id"] == chapter_1 for entry in body)


def test_list_subchapters_of_chapter_with_none_returns_empty_list(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id = _create_project(client, headers)
    chapter_id = _create_chapter(client, project_id, headers, "Chapter 1")

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/subchapters", headers=headers
    )

    assert response.status_code == 200
    assert response.json() == []


def test_create_subchapter_of_a_subchapter_422s(client: TestClient) -> None:
    """Nesting is capped at two levels (chapter, subchapter) per ADR-0014."""
    headers = _auth_headers(client)
    project_id = _create_project(client, headers)
    chapter_id = _create_chapter(client, project_id, headers, "Chapter 1")

    sub_response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/subchapters",
        json={"title": "Section 1.1"},
        headers=headers,
    )
    subchapter_id = sub_response.json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{subchapter_id}/subchapters",
        json={"title": "Section 1.1.1"},
        headers=headers,
    )

    assert response.status_code == 422


def test_create_subchapter_nonexistent_chapter_404s(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id = _create_project(client, headers)

    response = client.post(
        f"/projects/{project_id}/chapters/does-not-exist/subchapters",
        json={"title": "Section 1.1"},
        headers=headers,
    )

    assert response.status_code == 404


def test_create_subchapter_chapter_from_different_project_404s(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id_a = _create_project(client, headers)
    project_id_b = _create_project(client, headers)
    chapter_in_a = _create_chapter(client, project_id_a, headers, "Chapter 1")

    response = client.post(
        f"/projects/{project_id_b}/chapters/{chapter_in_a}/subchapters",
        json={"title": "Section 1.1"},
        headers=headers,
    )

    assert response.status_code == 404


def test_create_subchapter_other_users_project_404s(client: TestClient) -> None:
    owner_headers = _auth_headers(client, email="owner@example.com")
    project_id = _create_project(client, owner_headers)
    chapter_id = _create_chapter(client, project_id, owner_headers, "Chapter 1")

    other_headers = _auth_headers(client, email="intruder@example.com")
    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/subchapters",
        json={"title": "Section 1.1"},
        headers=other_headers,
    )

    assert response.status_code == 404


def test_project_detail_top_level_chapters_exclude_subchapters(client: TestClient) -> None:
    """Subchapters are reached via the dedicated endpoint, not flattened into `ProjectDetail`."""
    headers = _auth_headers(client)
    project_id = _create_project(client, headers)
    chapter_id = _create_chapter(client, project_id, headers, "Chapter 1")
    client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/subchapters",
        json={"title": "Section 1.1"},
        headers=headers,
    )

    response = client.get(f"/projects/{project_id}", headers=headers)

    assert response.status_code == 200
    titles = [chapter["title"] for chapter in response.json()["chapters"]]
    assert titles == ["Chapter 1"]
