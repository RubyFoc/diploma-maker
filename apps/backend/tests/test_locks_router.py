"""Tests for TASK-E13-3's draft-upload endpoint and TASK-E13-4's lock/unlock endpoints
(`locks.router`), via the HTTP `client` fixture (see `conftest.py`).
"""

import asyncio
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.main import app


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    response = client.post("/auth/register", json={"email": email, "password": "hunter22"})
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_project_and_chapter(client: TestClient, headers: dict) -> tuple[str, str]:
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Chapter 1"}, headers=headers
    ).json()["id"]
    return project_id, chapter_id


def _accept_chapter_content(client: TestClient, chapter_id: str, content: str) -> None:
    """Bypasses the LLM-backed `/generate` endpoint by writing directly to the same in-memory
    fake DB the `client` fixture wires up, matching `test_export_endpoint.py`'s pattern."""
    from diploma_backend.versions.service import accept_draft_version, create_draft_version

    db = app.dependency_overrides[get_database]()

    async def _create_and_accept() -> None:
        draft = await create_draft_version(db, chapter_id, content=content)
        await accept_draft_version(db, draft.id)

    asyncio.run(_create_and_accept())


def _docx_bytes(paragraphs: list[str]) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class TestAcceptedManifestExposure:
    def test_chapter_detail_exposes_accepted_manifest(self, client: TestClient) -> None:
        """TASK-E13-5's lock-selection UI needs the accepted version's manifest to know which
        block ids/hashes it can lock — exposed on `ChapterDetail` alongside `accepted_content`."""
        headers = _auth_headers(client)
        project_id, chapter_id = _create_project_and_chapter(client, headers)
        _accept_chapter_content(client, chapter_id, "First paragraph.\nSecond paragraph.")

        detail = client.get(f"/projects/{project_id}", headers=headers).json()
        chapter_detail = next(c for c in detail["chapters"] if c["id"] == chapter_id)

        assert chapter_detail["accepted_manifest"] is not None
        assert [b["content"] for b in chapter_detail["accepted_manifest"]] == [
            "First paragraph.",
            "Second paragraph.",
        ]

    def test_chapter_detail_accepted_manifest_none_without_accepted_content(
        self, client: TestClient
    ) -> None:
        headers = _auth_headers(client)
        project_id, chapter_id = _create_project_and_chapter(client, headers)

        detail = client.get(f"/projects/{project_id}", headers=headers).json()
        chapter_detail = next(c for c in detail["chapters"] if c["id"] == chapter_id)

        assert chapter_detail["accepted_manifest"] is None


class TestUploadDraft:
    def test_upload_docx_creates_a_draft_version_with_a_manifest(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        _, chapter_id = _create_project_and_chapter(client, headers)

        response = client.post(
            f"/chapters/{chapter_id}/draft/upload",
            files={
                "file": (
                    "draft.docx",
                    _docx_bytes(["First paragraph.", "Second paragraph."]),
                    "application/vnd.openxmlformats",
                )
            },
            headers=headers,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "draft"
        assert body["chapter_id"] == chapter_id
        assert [block["content"] for block in body["manifest"]] == [
            "First paragraph.",
            "Second paragraph.",
        ]

    def test_upload_invalid_file_400s(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        _, chapter_id = _create_project_and_chapter(client, headers)

        response = client.post(
            f"/chapters/{chapter_id}/draft/upload",
            files={"file": ("draft.docx", b"not a real docx file", "application/octet-stream")},
            headers=headers,
        )

        assert response.status_code == 400

    def test_upload_nonexistent_chapter_404s(self, client: TestClient) -> None:
        headers = _auth_headers(client)

        response = client.post(
            "/chapters/does-not-exist/draft/upload",
            files={"file": ("draft.docx", _docx_bytes(["Text."]), "application/vnd.openxmlformats")},
            headers=headers,
        )

        assert response.status_code == 404

    def test_upload_other_users_chapter_404s(self, client: TestClient) -> None:
        owner_headers = _auth_headers(client, email="owner@example.com")
        _, chapter_id = _create_project_and_chapter(client, owner_headers)

        intruder_headers = _auth_headers(client, email="intruder@example.com")
        response = client.post(
            f"/chapters/{chapter_id}/draft/upload",
            files={"file": ("draft.docx", _docx_bytes(["Text."]), "application/vnd.openxmlformats")},
            headers=intruder_headers,
        )

        assert response.status_code == 404


class TestLocks:
    def _lock_first_block(self, client: TestClient, chapter_id: str, headers: dict) -> dict:
        chapter_response = client.get(f"/chapters/{chapter_id}/locks", headers=headers)
        assert chapter_response.status_code == 200
        # Fetch the block id/hash straight from the accepted version's manifest via the chapter
        # detail's generate-adjacent data isn't exposed on ChapterDetail; read it from the DB
        # fixture instead (mirrors `_accept_chapter_content`'s direct-DB approach).
        from diploma_backend.versions.service import get_current_accepted_version

        db = app.dependency_overrides[get_database]()

        async def _get_block():
            version = await get_current_accepted_version(db, chapter_id)
            return version.manifest[0]

        block = asyncio.run(_get_block())
        response = client.post(
            f"/chapters/{chapter_id}/locks",
            json={"block_id": block.id, "block_content_hash": block.content_hash},
            headers=headers,
        )
        return {"response": response, "block": block}

    def test_create_lock_succeeds_with_current_hash(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        _, chapter_id = _create_project_and_chapter(client, headers)
        _accept_chapter_content(client, chapter_id, "First paragraph.")

        result = self._lock_first_block(client, chapter_id, headers)

        assert result["response"].status_code == 201
        body = result["response"].json()
        assert body["chapter_id"] == chapter_id
        assert body["block_id"] == result["block"].id

    def test_create_lock_stale_hash_409s(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        _, chapter_id = _create_project_and_chapter(client, headers)
        _accept_chapter_content(client, chapter_id, "First paragraph.")

        from diploma_backend.versions.service import get_current_accepted_version

        db = app.dependency_overrides[get_database]()
        block = asyncio.run(get_current_accepted_version(db, chapter_id)).manifest[0]

        response = client.post(
            f"/chapters/{chapter_id}/locks",
            json={"block_id": block.id, "block_content_hash": "stale-hash"},
            headers=headers,
        )

        assert response.status_code == 409

    def test_create_lock_unknown_block_404s(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        _, chapter_id = _create_project_and_chapter(client, headers)
        _accept_chapter_content(client, chapter_id, "First paragraph.")

        response = client.post(
            f"/chapters/{chapter_id}/locks",
            json={"block_id": "does-not-exist", "block_content_hash": "any-hash"},
            headers=headers,
        )

        assert response.status_code == 404

    def test_create_lock_chapter_with_no_accepted_content_404s(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        _, chapter_id = _create_project_and_chapter(client, headers)

        response = client.post(
            f"/chapters/{chapter_id}/locks",
            json={"block_id": "any-block", "block_content_hash": "any-hash"},
            headers=headers,
        )

        assert response.status_code == 404

    def test_list_locks_returns_created_locks(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        _, chapter_id = _create_project_and_chapter(client, headers)
        _accept_chapter_content(client, chapter_id, "First paragraph.")
        self._lock_first_block(client, chapter_id, headers)

        response = client.get(f"/chapters/{chapter_id}/locks", headers=headers)

        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_delete_lock_removes_it(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        _, chapter_id = _create_project_and_chapter(client, headers)
        _accept_chapter_content(client, chapter_id, "First paragraph.")
        lock_id = self._lock_first_block(client, chapter_id, headers)["response"].json()["id"]

        delete_response = client.delete(f"/chapters/{chapter_id}/locks/{lock_id}", headers=headers)
        assert delete_response.status_code == 204

        list_response = client.get(f"/chapters/{chapter_id}/locks", headers=headers)
        assert list_response.json() == []

    def test_delete_missing_lock_is_a_no_op_204(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        _, chapter_id = _create_project_and_chapter(client, headers)

        response = client.delete(f"/chapters/{chapter_id}/locks/does-not-exist", headers=headers)

        assert response.status_code == 204

    def test_locks_endpoints_404_for_other_users_chapter(self, client: TestClient) -> None:
        owner_headers = _auth_headers(client, email="owner@example.com")
        _, chapter_id = _create_project_and_chapter(client, owner_headers)
        _accept_chapter_content(client, chapter_id, "First paragraph.")

        intruder_headers = _auth_headers(client, email="intruder@example.com")
        assert client.get(f"/chapters/{chapter_id}/locks", headers=intruder_headers).status_code == 404
        assert (
            client.post(
                f"/chapters/{chapter_id}/locks",
                json={"block_id": "x", "block_content_hash": "y"},
                headers=intruder_headers,
            ).status_code
            == 404
        )
        assert (
            client.delete(f"/chapters/{chapter_id}/locks/x", headers=intruder_headers).status_code
            == 404
        )
