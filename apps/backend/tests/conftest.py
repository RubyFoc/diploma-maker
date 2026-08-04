"""Shared pytest fixtures: a TestClient wired to an in-memory MongoDB fake.

Overrides `diploma_backend.db.get_database` with `mongomock-motor` so auth/billing tests never
need a live MongoDB instance.
"""

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from diploma_backend.db import get_database
from diploma_backend.main import app


@pytest.fixture
def client() -> TestClient:
    """A TestClient for `app` with `get_database` overridden to an isolated in-memory fake."""
    fake_db = AsyncMongoMockClient()["diploma_maker_test"]

    def _override_get_database():
        return fake_db

    app.dependency_overrides[get_database] = _override_get_database
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_database, None)
