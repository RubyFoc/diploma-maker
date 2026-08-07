"""Tests for TASK-E16-1's `Operation` op-log model (ADR-0012), plus TASK-E16-2/3's
storage/write-path service layer (`history.service`): recording operations for a batch of newly
spliced blocks, the redo-stack wipe on a fresh recording, and the undo/redo replay logic's
cursor bookkeeping and fail-closed error cases.

HTTP-level coverage of the undo/redo endpoints lives in `test_undo_redo_router.py`; this module
exercises `history.service` directly against the in-memory Mongo fake from `conftest.py`.
"""

import pytest
from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.history.models import Operation
from diploma_backend.history.service import (
    HistoryReplayError,
    get_history_cursor,
    get_placement,
    list_operations_for_chapter,
    redo_operations,
    undo_operations,
)
from diploma_backend.locks.models import CharRange
from diploma_backend.main import app
from diploma_backend.versions.service import (
    accept_draft_version,
    create_draft_version,
    create_draft_version_at_anchor,
)


def build_operation(**overrides: object) -> Operation:
    fields = {
        "chapter_id": "chapter-1",
        "base_version_id": "version-1",
        "block_id": "block-1",
        "before_text": "Original sentence.",
        "after_text": "Revised sentence.",
        "applied_by": "user-1",
    }
    fields.update(overrides)
    return Operation(**fields)


def test_operation_constructs_with_required_fields_and_autogenerates_id_and_created_at() -> None:
    operation = build_operation()

    assert operation.chapter_id == "chapter-1"
    assert operation.base_version_id == "version-1"
    assert operation.block_id == "block-1"
    assert operation.before_text == "Original sentence."
    assert operation.after_text == "Revised sentence."
    assert operation.applied_by == "user-1"
    assert operation.id
    assert operation.created_at is not None


def test_operation_assigns_a_unique_id_per_call() -> None:
    first = build_operation()
    second = build_operation()

    assert first.id != second.id


def test_operation_char_range_defaults_to_none() -> None:
    operation = build_operation()

    assert operation.char_range is None


def test_operation_char_range_can_be_set() -> None:
    operation = build_operation(char_range=CharRange(start=0, end=8))

    assert operation.char_range == CharRange(start=0, end=8)


def test_operation_round_trips_through_model_dump_and_validate() -> None:
    operation = build_operation(char_range=CharRange(start=2, end=5))

    rehydrated = Operation.model_validate(operation.model_dump())

    assert rehydrated == operation


def test_operation_round_trips_with_no_char_range() -> None:
    operation = build_operation()

    rehydrated = Operation.model_validate(operation.model_dump())

    assert rehydrated == operation


def _fake_db(client: TestClient):
    return app.dependency_overrides[get_database]()


async def _seed_accepted_chapter(db, content: str, chapter_id: str = "chapter-1"):
    """Bypasses generation entirely: builds and accepts a version directly, matching
    `test_versions.py`'s pattern, and returns the accepted `ChapterVersion`."""
    draft = await create_draft_version(db, chapter_id, content=content)
    return await accept_draft_version(db, draft.id)


async def test_record_anchor_insertion_operations_creates_ops_and_placements_and_advances_cursor(
    client: TestClient,
) -> None:
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.\nSecond paragraph.")
    anchor_block = accepted.manifest[0]

    draft = await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted one.\nInserted two.", applied_by="user-1"
    )

    operations = await list_operations_for_chapter(db, "chapter-1")
    assert len(operations) == 2
    assert operations[0].applied_by == "user-1"
    assert operations[0].before_text == ""
    assert operations[0].after_text == "Inserted one."
    assert operations[1].after_text == "Inserted two."

    new_block_ids = [block.id for block in draft.manifest[1:3]]
    assert [operation.block_id for operation in operations] == new_block_ids

    first_placement = await get_placement(db, operations[0].id)
    second_placement = await get_placement(db, operations[1].id)
    assert first_placement.insert_after_block_id == anchor_block.id
    assert second_placement.insert_after_block_id == operations[0].block_id

    cursor = await get_history_cursor(db, "chapter-1")
    assert cursor.applied_count == 2


async def test_recording_a_new_op_after_undo_wipes_the_stale_redo_tail(
    client: TestClient,
) -> None:
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.")
    anchor_block = accepted.manifest[0]

    await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Original insertion.", applied_by="user-1"
    )
    operations_before_undo = await list_operations_for_chapter(db, "chapter-1")
    undone_operation_id = operations_before_undo[0].id

    await undo_operations(db, "chapter-1", 1)
    cursor = await get_history_cursor(db, "chapter-1")
    assert cursor.applied_count == 0

    await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Replacement insertion.", applied_by="user-1"
    )

    operations_after = await list_operations_for_chapter(db, "chapter-1")
    assert len(operations_after) == 1
    assert operations_after[0].after_text == "Replacement insertion."
    assert all(operation.id != undone_operation_id for operation in operations_after)
    assert await get_placement(db, undone_operation_id) is None

    cursor_after = await get_history_cursor(db, "chapter-1")
    assert cursor_after.applied_count == 1


async def test_undo_removes_spliced_block_and_decrements_cursor(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.\nSecond paragraph.")
    anchor_block = accepted.manifest[0]

    draft = await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph.", applied_by="user-1"
    )
    inserted_block_id = draft.manifest[1].id

    result = await undo_operations(db, "chapter-1", 1)

    assert result.applied_count == 0
    assert result.total_operations == 1
    assert [block.content for block in result.version.manifest] == [
        "First paragraph.",
        "Second paragraph.",
    ]
    assert all(block.id != inserted_block_id for block in result.version.manifest)


async def test_redo_resplices_block_with_matching_id_and_content(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.\nSecond paragraph.")
    anchor_block = accepted.manifest[0]

    draft = await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph.", applied_by="user-1"
    )
    inserted_block_id = draft.manifest[1].id
    inserted_content = draft.manifest[1].content

    await undo_operations(db, "chapter-1", 1)
    result = await redo_operations(db, "chapter-1", 1)

    assert result.applied_count == 1
    assert result.total_operations == 1
    redone_block = result.version.manifest[1]
    assert redone_block.id == inserted_block_id
    assert redone_block.content == inserted_content
    assert [block.content for block in result.version.manifest] == [
        "First paragraph.",
        "Inserted paragraph.",
        "Second paragraph.",
    ]


async def test_undo_rejects_when_there_is_no_pending_draft(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.")
    anchor_block = accepted.manifest[0]
    draft = await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph.", applied_by="user-1"
    )
    await accept_draft_version(db, draft.id)

    with pytest.raises(HistoryReplayError, match="no pending draft"):
        await undo_operations(db, "chapter-1", 1)


async def test_redo_rejects_when_there_is_no_pending_draft(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.")
    anchor_block = accepted.manifest[0]
    draft = await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph.", applied_by="user-1"
    )
    await undo_operations(db, "chapter-1", 1)
    await accept_draft_version(db, draft.id)

    with pytest.raises(HistoryReplayError, match="no pending draft"):
        await redo_operations(db, "chapter-1", 1)


async def test_undo_rejects_when_nothing_to_undo(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.")
    anchor_block = accepted.manifest[0]
    await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph.", applied_by="user-1"
    )
    await undo_operations(db, "chapter-1", 1)

    with pytest.raises(HistoryReplayError, match="nothing to undo"):
        await undo_operations(db, "chapter-1", 1)


async def test_redo_rejects_when_nothing_to_redo(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.")
    anchor_block = accepted.manifest[0]
    await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph.", applied_by="user-1"
    )

    with pytest.raises(HistoryReplayError, match="nothing to redo"):
        await redo_operations(db, "chapter-1", 1)


async def test_undo_rejects_when_count_exceeds_available(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.")
    anchor_block = accepted.manifest[0]
    await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph.", applied_by="user-1"
    )

    with pytest.raises(HistoryReplayError, match="only"):
        await undo_operations(db, "chapter-1", 2)


async def test_redo_rejects_when_count_exceeds_available(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.")
    anchor_block = accepted.manifest[0]
    await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph.", applied_by="user-1"
    )
    await undo_operations(db, "chapter-1", 1)

    with pytest.raises(HistoryReplayError, match="only"):
        await redo_operations(db, "chapter-1", 2)


async def test_undo_rejects_when_anchor_block_no_longer_exists(client: TestClient) -> None:
    """Simulates the operation's anchor block having disappeared from the current draft some
    other way (e.g. it was undone/removed through a different path) by manually stripping it out
    of the draft's manifest before calling undo directly against the still-recorded operation."""
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.")
    anchor_block = accepted.manifest[0]
    draft = await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph.", applied_by="user-1"
    )

    stripped_manifest = [
        block for block in draft.manifest if block.content != "Inserted paragraph."
    ]
    await db["chapter_versions"].update_one(
        {"id": draft.id},
        {"$set": {"manifest": [block.model_dump() for block in stripped_manifest]}},
    )

    with pytest.raises(HistoryReplayError, match="no longer exists in the current draft"):
        await undo_operations(db, "chapter-1", 1)


async def test_redo_rejects_when_insertion_point_no_longer_exists(client: TestClient) -> None:
    """Simulates the recorded insertion point having disappeared from the current draft (e.g.
    the anchor block was independently deleted) by stripping it out of the manifest between
    undo and redo."""
    db = _fake_db(client)
    accepted = await _seed_accepted_chapter(db, "First paragraph.")
    anchor_block = accepted.manifest[0]
    draft = await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph.", applied_by="user-1"
    )
    await undo_operations(db, "chapter-1", 1)

    current = await db["chapter_versions"].find_one({"id": draft.id})
    stripped_manifest = [block for block in current["manifest"] if block["id"] != anchor_block.id]
    await db["chapter_versions"].update_one(
        {"id": draft.id}, {"$set": {"manifest": stripped_manifest}}
    )

    with pytest.raises(HistoryReplayError, match="no longer exists in the current draft"):
        await redo_operations(db, "chapter-1", 1)
