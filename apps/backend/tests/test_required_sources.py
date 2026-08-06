"""Tests for TASK-E14-1 (`sources.required` model/storage) and TASK-E14-2
(`sources.router`'s `/projects/{project_id}/required-sources` endpoints).
"""

from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.db import get_database
from diploma_backend.main import app
from diploma_backend.sources.required import (
    create_required_source,
    list_required_sources_for_project,
)


def _db() -> AsyncIOMotorDatabase:
    return AsyncMongoMockClient()["diploma_maker_test"]


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    response = client.post("/auth/register", json={"email": email, "password": "hunter22"})
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestService:
    async def test_create_required_source_persists_all_fields(self) -> None:
        db = _db()

        created = await create_required_source(db, "p1", "Jane Doe", "A Study of Things", 2020)

        assert created.project_id == "p1"
        assert created.author == "Jane Doe"
        assert created.title == "A Study of Things"
        assert created.year == 2020

    async def test_create_required_source_defaults_title_and_year_to_none(self) -> None:
        db = _db()

        created = await create_required_source(db, "p1", "Jane Doe")

        assert created.title is None
        assert created.year is None

    async def test_list_required_sources_for_project_returns_only_that_projects_sources(
        self,
    ) -> None:
        db = _db()
        await create_required_source(db, "p1", "Jane Doe")
        await create_required_source(db, "p2", "John Smith")

        sources = await list_required_sources_for_project(db, "p1")

        assert len(sources) == 1
        assert sources[0].author == "Jane Doe"

    async def test_list_required_sources_for_project_with_none_returns_empty_list(self) -> None:
        db = _db()

        assert await list_required_sources_for_project(db, "p1") == []


class TestRouter:
    def _create_project(self, client: TestClient, headers: dict) -> str:
        return client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]

    def test_create_required_source_returns_the_created_record(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        project_id = self._create_project(client, headers)

        response = client.post(
            f"/projects/{project_id}/required-sources",
            json={"author": "Jane Doe", "title": "A Study of Things", "year": 2020},
            headers=headers,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["author"] == "Jane Doe"
        assert body["title"] == "A Study of Things"
        assert body["year"] == 2020
        assert body["project_id"] == project_id

    def test_create_required_source_only_requires_author(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        project_id = self._create_project(client, headers)

        response = client.post(
            f"/projects/{project_id}/required-sources",
            json={"author": "Jane Doe"},
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["title"] is None

    def test_list_required_sources_returns_created_sources(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        project_id = self._create_project(client, headers)
        client.post(
            f"/projects/{project_id}/required-sources",
            json={"author": "Jane Doe"},
            headers=headers,
        )
        client.post(
            f"/projects/{project_id}/required-sources",
            json={"author": "John Smith"},
            headers=headers,
        )

        response = client.get(f"/projects/{project_id}/required-sources", headers=headers)

        assert response.status_code == 200
        authors = {source["author"] for source in response.json()}
        assert authors == {"Jane Doe", "John Smith"}

    def test_list_required_sources_empty_for_new_project(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        project_id = self._create_project(client, headers)

        response = client.get(f"/projects/{project_id}/required-sources", headers=headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_create_required_source_404s_for_unknown_project(self, client: TestClient) -> None:
        headers = _auth_headers(client)

        response = client.post(
            "/projects/does-not-exist/required-sources",
            json={"author": "Jane Doe"},
            headers=headers,
        )

        assert response.status_code == 404

    def test_required_sources_404_for_other_users_project(self, client: TestClient) -> None:
        owner_headers = _auth_headers(client, email="owner@example.com")
        project_id = self._create_project(client, owner_headers)

        intruder_headers = _auth_headers(client, email="intruder@example.com")
        assert (
            client.post(
                f"/projects/{project_id}/required-sources",
                json={"author": "Jane Doe"},
                headers=intruder_headers,
            ).status_code
            == 404
        )
        assert (
            client.get(f"/projects/{project_id}/required-sources", headers=intruder_headers).status_code
            == 404
        )

    async def test_delete_project_cascades_required_sources(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        project_id = self._create_project(client, headers)
        client.post(
            f"/projects/{project_id}/required-sources",
            json={"author": "Jane Doe"},
            headers=headers,
        )

        db = app.dependency_overrides[get_database]()
        assert (await db["required_sources"].find_one({"project_id": project_id})) is not None

        delete_response = client.delete(f"/projects/{project_id}", headers=headers)
        assert delete_response.status_code == 204

        assert (await db["required_sources"].find_one({"project_id": project_id})) is None
