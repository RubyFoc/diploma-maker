"""Tests for `projects.service.update_chapter_summary` (ADR-0003 addendum, follow-up to
TASK-E03-2/E17), exercised directly against an in-memory `mongomock-motor` database, matching
`test_chapter_insertion.py`'s pattern for `projects.service` storage-layer functions.
"""

from mongomock_motor import AsyncMongoMockClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.projects.service import (
    create_chapter,
    list_chapters_for_project,
    update_chapter_summary,
)


def _db() -> AsyncIOMotorDatabase:
    return AsyncMongoMockClient()["diploma_maker_test"]


async def test_update_chapter_summary_persists_summary_text() -> None:
    db = _db()
    chapter = await create_chapter(db, "p1", "Introduction")
    assert chapter.summary is None

    await update_chapter_summary(db, chapter.id, "A compacted summary of the introduction.")

    chapters = await list_chapters_for_project(db, "p1")
    assert chapters[0].summary == "A compacted summary of the introduction."


async def test_update_chapter_summary_does_nothing_for_unknown_chapter() -> None:
    """No error on a missing chapter id, matching `update_project_title`'s no-error-on-missing
    convention — the caller already fails open on any summarization problem."""
    db = _db()

    await update_chapter_summary(db, "does-not-exist", "orphaned summary")
