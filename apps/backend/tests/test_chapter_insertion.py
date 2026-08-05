"""Tests for TASK-E10-3's storage-layer half: chapter-boundary-aware insertion.

Exercises `projects.service.insert_chapter_at_order` and `infer_insertion_order` directly against
an in-memory `mongomock-motor` database (same fake backing `tests/conftest.py`'s `client`
fixture), since this task deliberately has no HTTP route yet (`projects.router` is owned by a
parallel task this round).
"""

from mongomock_motor import AsyncMongoMockClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.projects.models import Chapter
from diploma_backend.projects.service import (
    create_chapter,
    infer_insertion_order,
    insert_chapter_at_order,
    list_chapters_for_project,
)


def _db() -> AsyncIOMotorDatabase:
    return AsyncMongoMockClient()["diploma_maker_test"]


async def test_insert_chapter_at_order_at_end_behaves_like_append() -> None:
    db = _db()
    await create_chapter(db, "p1", "Chapter 1")
    await create_chapter(db, "p1", "Chapter 2")

    inserted = await insert_chapter_at_order(db, "p1", "Chapter 3", order=2)

    assert inserted.order == 2
    chapters = await list_chapters_for_project(db, "p1")
    assert [chapter.order for chapter in chapters] == [0, 1, 2]
    assert chapters[2].title == "Chapter 3"


async def test_insert_chapter_at_order_in_middle_shifts_subsequent_chapters() -> None:
    db = _db()
    chapter_1 = await create_chapter(db, "p1", "Chapter 1")
    chapter_3 = await create_chapter(db, "p1", "Chapter 3")

    inserted = await insert_chapter_at_order(db, "p1", "Chapter 2", order=1)

    assert inserted.order == 1
    chapters = await list_chapters_for_project(db, "p1")
    assert [chapter.order for chapter in chapters] == [0, 1, 2]
    by_id = {chapter.id: chapter for chapter in chapters}
    assert by_id[chapter_1.id].order == 0
    assert by_id[inserted.id].order == 1
    assert by_id[chapter_3.id].order == 2
    assert [chapter.title for chapter in chapters] == [
        "Chapter 1",
        "Chapter 2",
        "Chapter 3",
    ]


async def test_insert_chapter_at_order_zero_into_empty_project_creates_first_chapter() -> None:
    db = _db()

    inserted = await insert_chapter_at_order(db, "p1", "Chapter 1", order=0)

    assert inserted.order == 0
    chapters = await list_chapters_for_project(db, "p1")
    assert [chapter.order for chapter in chapters] == [0]


async def test_insert_chapter_at_order_only_shifts_the_target_project() -> None:
    db = _db()
    await create_chapter(db, "other", "Other Chapter 1")

    await insert_chapter_at_order(db, "p1", "Chapter 1", order=0)

    other_chapters = await list_chapters_for_project(db, "other")
    assert [chapter.order for chapter in other_chapters] == [0]


def test_infer_insertion_order_returns_order_of_first_higher_numbered_chapter() -> None:
    existing = [
        Chapter(project_id="p1", title="Chapter 1", order=0),
        Chapter(project_id="p1", title="Chapter 3", order=1),
    ]

    assert infer_insertion_order(existing, "Chapter 2") == 1


def test_infer_insertion_order_falls_back_to_append_when_title_has_no_number() -> None:
    existing = [
        Chapter(project_id="p1", title="Chapter 1", order=0),
        Chapter(project_id="p1", title="Chapter 3", order=1),
    ]

    assert infer_insertion_order(existing, "Conclusion") == 2


def test_infer_insertion_order_empty_existing_chapters_returns_zero() -> None:
    assert infer_insertion_order([], "Chapter 1") == 0


def test_infer_insertion_order_higher_number_than_everything_appends_at_end() -> None:
    existing = [
        Chapter(project_id="p1", title="Chapter 1", order=0),
        Chapter(project_id="p1", title="Chapter 2", order=1),
    ]

    assert infer_insertion_order(existing, "Chapter 5") == 2
