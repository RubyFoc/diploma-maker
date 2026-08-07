"""Shared pytest fixtures: a TestClient wired to an in-memory MongoDB fake.

Overrides `diploma_backend.db.get_database` with `mongomock-motor` so auth/billing tests never
need a live MongoDB instance. Also forces the Celery app into eager mode (ADR-0013 addendum point
4) so `worker`-package tasks run synchronously in-process, with no real Redis/worker required.
"""

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from diploma_backend.db import get_database
from diploma_backend.main import app
from diploma_backend.worker.celery_app import celery_app


@pytest.fixture(autouse=True, scope="session")
def celery_eager() -> None:
    """Run every Celery task synchronously in-process for the whole test session.

    Sets `task_always_eager`/`task_eager_propagates` (ADR-0013 addendum point 4): `.delay()`/
    `.apply_async()` executes the task body directly, and an exception raised inside a task
    propagates to the caller instead of being swallowed into a failed `AsyncResult`.
    """
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True


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
