"""Tests for the read-only `GET /chapters/{chapter_id}/operations` addendum (`history.router`),
added as a small prerequisite for TASK-E16-4 (client-side page-range-to-count resolution). Setup
mirrors `test_undo_redo_router.py`'s pattern of bypassing the LLM-backed `/generate` endpoint via
`versions.service.create_draft_version_at_anchor` directly.
"""

import asyncio

from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.main import app
from diploma_backend.versions.service import (
    accept_draft_version,
    create_draft_version,
    create_draft_version_at_anchor,
)


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
    db = app.dependency_overrides[get_database]()

    async def _create_and_accept() -> dict:
        draft = await create_draft_version(db, chapter_id, content=content)
        accepted = await accept_draft_version(db, draft.id)
        return accepted.model_dump()

    return asyncio.run(_create_and_accept())


def _insert_at_anchor(
    client: TestClient,
    chapter_id: str,
    anchor_block_id: str,
    generated_content: str,
    applied_by: str,
) -> dict:
    db = app.dependency_overrides[get_database]()

    async def _create() -> dict:
        draft = await create_draft_version_at_anchor(
            db, chapter_id, anchor_block_id, generated_content, applied_by=applied_by
        )
        return draft.model_dump()

    return asyncio.run(_create())


def test_list_operations_returns_zeroed_shape_for_chapter_with_no_history(
    client: TestClient,
) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)

    response = client.get(f"/chapters/{chapter_id}/operations", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"operations": [], "applied_count": 0, "total_operations": 0}


def test_list_operations_returns_recorded_operations_in_order(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]

    first_draft = _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Second paragraph.", applied_by="ignored"
    )
    first_block_id = first_draft["manifest"][1]["id"]
    accepted_after_first = asyncio.run(
        accept_draft_version(app.dependency_overrides[get_database](), first_draft["id"])
    ).model_dump()
    second_anchor_block_id = accepted_after_first["manifest"][1]["id"]
    assert second_anchor_block_id == first_block_id
    second_draft = _insert_at_anchor(
        client, chapter_id, second_anchor_block_id, "Third paragraph.", applied_by="ignored"
    )
    second_block_id = second_draft["manifest"][2]["id"]

    response = client.get(f"/chapters/{chapter_id}/operations", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["applied_count"] == 2
    assert body["total_operations"] == 2
    assert [op["block_id"] for op in body["operations"]] == [first_block_id, second_block_id]
    for op in body["operations"]:
        assert set(op.keys()) == {"id", "block_id", "created_at"}


def test_list_operations_after_undo_keeps_undone_operation_listed(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Inserted paragraph.", applied_by="ignored"
    )

    client.post(f"/chapters/{chapter_id}/undo", json={}, headers=headers)
    response = client.get(f"/chapters/{chapter_id}/operations", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["applied_count"] == 0
    assert body["total_operations"] == 1
    assert len(body["operations"]) == 1


def test_list_operations_after_new_edit_drops_the_wiped_redo_tail(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]

    _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Original insertion.", applied_by="ignored"
    )
    client.post(f"/chapters/{chapter_id}/undo", json={}, headers=headers)
    _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Replacement insertion.", applied_by="ignored"
    )

    response = client.get(f"/chapters/{chapter_id}/operations", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["applied_count"] == 1
    assert body["total_operations"] == 1


def test_list_operations_404s_for_unknown_chapter(client: TestClient) -> None:
    headers = _auth_headers(client)

    response = client.get("/chapters/does-not-exist/operations", headers=headers)

    assert response.status_code == 404


def test_list_operations_404s_when_chapter_belongs_to_another_owner(client: TestClient) -> None:
    owner_headers = _auth_headers(client, email="owner@example.com")
    _, chapter_id = _setup_project_and_chapter(client, owner_headers)

    other_headers = _auth_headers(client, email="other@example.com")
    response = client.get(f"/chapters/{chapter_id}/operations", headers=other_headers)

    assert response.status_code == 404


def test_list_operations_requires_authentication(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)

    response = client.get(f"/chapters/{chapter_id}/operations")

    assert response.status_code == 401
