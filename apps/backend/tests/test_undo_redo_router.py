"""Tests for TASK-E16-2/3's `POST /chapters/{chapter_id}/undo` and `.../redo` endpoints
(`history.router`), layered on `history.service`'s already-unit-tested replay logic
(`test_history.py`).

Generation itself is bypassed in favor of directly seeding an accepted version and calling
`versions.service.create_draft_version_at_anchor` (matching `test_generate_anchor.py`'s
`_accept_chapter_content` pattern), since the anchor-insertion recording behavior under test
lives in `versions.service`/`history.service`, not in the LLM call itself.
"""

import asyncio

from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.main import app
from diploma_backend.versions.service import accept_draft_version, create_draft_version


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
    """Bypasses the LLM-backed `/generate` endpoint, calling
    `versions.service.create_draft_version_at_anchor` directly, so this module's tests only
    exercise the undo/redo endpoints themselves, not generation/humanization/precheck."""
    db = app.dependency_overrides[get_database]()

    from diploma_backend.versions.service import create_draft_version_at_anchor

    async def _create() -> dict:
        draft = await create_draft_version_at_anchor(
            db, chapter_id, anchor_block_id, generated_content, applied_by=applied_by
        )
        return draft.model_dump()

    return asyncio.run(_create())


def test_undo_removes_the_last_inserted_block(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.\nSecond paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    draft = _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Inserted paragraph.", applied_by="ignored"
    )
    inserted_block_id = draft["manifest"][1]["id"]

    response = client.post(f"/chapters/{chapter_id}/undo", json={}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["applied_count"] == 0
    assert body["total_operations"] == 1
    contents = [block["content"] for block in body["version"]["manifest"]]
    assert contents == ["First paragraph.", "Second paragraph."]
    assert all(block["id"] != inserted_block_id for block in body["version"]["manifest"])


def test_redo_reinserts_the_block_with_matching_id_and_content(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.\nSecond paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    draft = _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Inserted paragraph.", applied_by="ignored"
    )
    inserted_block_id = draft["manifest"][1]["id"]
    inserted_content = draft["manifest"][1]["content"]

    client.post(f"/chapters/{chapter_id}/undo", json={}, headers=headers)
    response = client.post(f"/chapters/{chapter_id}/redo", json={}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["applied_count"] == 1
    assert body["total_operations"] == 1
    redone = body["version"]["manifest"][1]
    assert redone["id"] == inserted_block_id
    assert redone["content"] == inserted_content


def test_undo_then_new_anchor_insertion_wipes_stale_redo_tail(client: TestClient) -> None:
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

    redo_response = client.post(f"/chapters/{chapter_id}/redo", json={}, headers=headers)
    assert redo_response.status_code == 409
    assert "nothing to redo" in redo_response.json()["detail"]


def test_undo_rejects_when_there_is_no_pending_draft(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    draft = _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Inserted paragraph.", applied_by="ignored"
    )
    accept_draft_response = asyncio.run(
        accept_draft_version(app.dependency_overrides[get_database](), draft["id"])
    )
    assert accept_draft_response.status == "accepted"

    response = client.post(f"/chapters/{chapter_id}/undo", json={}, headers=headers)

    assert response.status_code == 409
    assert "no pending draft" in response.json()["detail"]


def test_undo_rejects_when_nothing_to_undo(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Inserted paragraph.", applied_by="ignored"
    )
    client.post(f"/chapters/{chapter_id}/undo", json={}, headers=headers)

    response = client.post(f"/chapters/{chapter_id}/undo", json={}, headers=headers)

    assert response.status_code == 409
    assert "nothing to undo" in response.json()["detail"]


def test_redo_rejects_when_nothing_to_redo(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Inserted paragraph.", applied_by="ignored"
    )

    response = client.post(f"/chapters/{chapter_id}/redo", json={}, headers=headers)

    assert response.status_code == 409
    assert "nothing to redo" in response.json()["detail"]


def test_undo_rejects_when_count_exceeds_available(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Inserted paragraph.", applied_by="ignored"
    )

    response = client.post(f"/chapters/{chapter_id}/undo", json={"count": 2}, headers=headers)

    assert response.status_code == 409
    assert "only" in response.json()["detail"]


def test_undo_404s_for_unknown_chapter(client: TestClient) -> None:
    headers = _auth_headers(client)

    response = client.post("/chapters/does-not-exist/undo", json={}, headers=headers)

    assert response.status_code == 404


def test_undo_404s_when_chapter_belongs_to_another_owner(client: TestClient) -> None:
    owner_headers = _auth_headers(client, email="owner@example.com")
    _, chapter_id = _setup_project_and_chapter(client, owner_headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Inserted paragraph.", applied_by="ignored"
    )

    other_headers = _auth_headers(client, email="other@example.com")
    response = client.post(f"/chapters/{chapter_id}/undo", json={}, headers=other_headers)

    assert response.status_code == 404


def test_undo_requires_authentication(client: TestClient) -> None:
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)

    response = client.post(f"/chapters/{chapter_id}/undo", json={})

    assert response.status_code == 401


def test_redo_anchor_block_no_longer_exists_returns_409(client: TestClient) -> None:
    """Simulates the recorded insertion point disappearing from the current draft between undo
    and redo (e.g. some other mutation removed it), a realistic construction of ADR-0012's
    "replaying an op whose anchor block no longer exists must reject" case."""
    headers = _auth_headers(client)
    _, chapter_id = _setup_project_and_chapter(client, headers)
    accepted = _accept_chapter_content(client, chapter_id, "First paragraph.")
    anchor_block_id = accepted["manifest"][0]["id"]
    draft = _insert_at_anchor(
        client, chapter_id, anchor_block_id, "Inserted paragraph.", applied_by="ignored"
    )
    client.post(f"/chapters/{chapter_id}/undo", json={}, headers=headers)

    db = app.dependency_overrides[get_database]()

    async def _strip_anchor_block() -> None:
        current = await db["chapter_versions"].find_one({"id": draft["id"]})
        stripped = [block for block in current["manifest"] if block["id"] != anchor_block_id]
        await db["chapter_versions"].update_one(
            {"id": draft["id"]}, {"$set": {"manifest": stripped}}
        )

    asyncio.run(_strip_anchor_block())

    response = client.post(f"/chapters/{chapter_id}/redo", json={}, headers=headers)

    assert response.status_code == 409
    assert "no longer exists in the current draft" in response.json()["detail"]
