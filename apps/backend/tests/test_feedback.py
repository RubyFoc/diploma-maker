"""Tests for feedback signal capture (TASK-E09-1): storage layer (`feedback.service`) and the
`POST /feedback/signals` endpoint. Does not test any weight-adjustment logic (TASK-E09-2, not
implemented here) — only that raw signals are recorded and queryable in the right shape.

Storage-layer tests exercise `feedback.service` directly against an in-memory `mongomock-motor`
database (same fake backing `tests/conftest.py`'s `client` fixture), matching
`test_chapter_insertion.py`'s pattern.
"""

from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.feedback.service import list_signals_for_institution, record_signal


def _db() -> AsyncIOMotorDatabase:
    return AsyncMongoMockClient()["diploma_maker_test"]


async def test_record_signal_persists_and_returns_expected_fields() -> None:
    db = _db()
    signal = await record_signal(db, "mit", "chapter-1", "version-1", "approve")

    assert signal.institution_id == "mit"
    assert signal.chapter_id == "chapter-1"
    assert signal.version_id == "version-1"
    assert signal.signal_type == "approve"
    assert signal.id
    assert signal.created_at is not None

    stored = await db["feedback_signals"].find_one({"id": signal.id})
    assert stored is not None
    assert stored["institution_id"] == "mit"


async def test_list_signals_for_institution_filters_and_orders() -> None:
    db = _db()
    first = await record_signal(db, "mit", "chapter-1", "version-1", "approve")
    await record_signal(db, "other-school", "chapter-2", "version-2", "reject")
    second = await record_signal(db, "mit", "chapter-3", "version-3", "reject")

    signals = await list_signals_for_institution(db, "mit")

    assert [signal.id for signal in signals] == [first.id, second.id]
    assert all(signal.institution_id == "mit" for signal in signals)


def test_record_signal_endpoint_returns_201_for_approve(client: TestClient) -> None:
    response = client.post(
        "/feedback/signals",
        json={
            "institution_id": "mit",
            "chapter_id": "chapter-1",
            "version_id": "version-1",
            "signal_type": "approve",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["institution_id"] == "mit"
    assert body["chapter_id"] == "chapter-1"
    assert body["version_id"] == "version-1"
    assert body["signal_type"] == "approve"
    assert "id" in body
    assert "created_at" in body


def test_record_signal_endpoint_returns_201_for_reject(client: TestClient) -> None:
    response = client.post(
        "/feedback/signals",
        json={
            "institution_id": "mit",
            "chapter_id": "chapter-1",
            "version_id": "version-1",
            "signal_type": "reject",
        },
    )

    assert response.status_code == 201
    assert response.json()["signal_type"] == "reject"


def test_record_signal_endpoint_returns_201_for_edit(client: TestClient) -> None:
    response = client.post(
        "/feedback/signals",
        json={
            "institution_id": "mit",
            "chapter_id": "chapter-1",
            "version_id": "version-1",
            "signal_type": "edit",
        },
    )

    assert response.status_code == 201
    assert response.json()["signal_type"] == "edit"


def test_record_signal_endpoint_rejects_invalid_signal_type(client: TestClient) -> None:
    response = client.post(
        "/feedback/signals",
        json={
            "institution_id": "mit",
            "chapter_id": "chapter-1",
            "version_id": "version-1",
            "signal_type": "not-a-real-type",
        },
    )

    assert response.status_code == 422
