"""MongoDB storage, write-path recording, and undo/redo replay for the edit op-log (ADR-0012,
TASK-E16-2, TASK-E16-3).

Three collections, all keyed by an explicit `id` field (matching this codebase's convention,
see `versions.service`'s module docstring): `chapter_operations` (`history.models.Operation`
rows), `chapter_operation_placements` (`history.models.OperationPlacement`, one per insertion
`Operation`, recorded alongside it), and `chapter_history_cursors` (`history.models.HistoryCursor`,
one upserted doc per chapter, keyed by `chapter_id` rather than `id`).

Two responsibilities live here:

- `record_anchor_insertion_operations`: called by
  `versions.service.create_draft_version_at_anchor` (TASK-E15-1's anchor-insertion generation
  path) once per newly spliced block. This is the ONLY write path that records `Operation`s in
  this codebase (see that function's docstring for why full-chapter generation and uploaded-draft
  ingestion are out of scope). Recording a new operation first deletes the chapter's stale
  "undone but not yet overwritten" tail — TASK-E16-3's entire redo-stack-wipe behavior, no
  separate flag needed, since this is a linear op-log rather than a branching history (ADR-0012).
- `undo_operations`/`redo_operations`: replay/revert recorded operations against a chapter's
  current pending draft `ChapterVersion`, mutating it in place (no new version row, no
  `version_number` bump — accept semantics, ADR-0004, are completely unaffected). Both reject
  with `HistoryReplayError` rather than guess a new anchor if an operation's anchor block can no
  longer be found in the current draft (ADR-0012's explicit consequence).

This module imports `versions.service` (for `get_latest_draft_version`/`update_draft_manifest`)
at module level; `versions.service` only ever reaches back into this module via a lazy,
inside-function import (see `create_draft_version_at_anchor`'s docstring) specifically to avoid
an import cycle between the two modules.
"""

from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from diploma_backend.history.models import HistoryCursor, Operation, OperationPlacement
from diploma_backend.locks.models import Block, insert_blocks_after
from diploma_backend.versions.models import ChapterVersion
from diploma_backend.versions.service import get_latest_draft_version, update_draft_manifest

_OPERATIONS_COLLECTION = "chapter_operations"
_PLACEMENTS_COLLECTION = "chapter_operation_placements"
_CURSORS_COLLECTION = "chapter_history_cursors"


class HistoryReplayError(ValueError):
    """Raised by `undo_operations`/`redo_operations` for any fail-closed reason they check (see
    their docstrings): no pending draft to mutate, nothing left to undo/redo, `count` exceeds
    what's available, or an operation's anchor block/insertion-point can no longer be found in
    the current draft.

    `history.router`'s endpoints distinguish the specific reason by substring, matching
    `locks.service.LockTargetError`'s convention, and translate each to the matching 4xx status.
    """


async def get_history_cursor(db: AsyncIOMotorDatabase, chapter_id: str) -> HistoryCursor | None:
    """Fetch `chapter_id`'s `HistoryCursor`, or `None` if no operation has ever been recorded
    for it yet (an unwritten cursor implicitly means `applied_count=0`)."""
    document = await db[_CURSORS_COLLECTION].find_one({"chapter_id": chapter_id})
    if document is None:
        return None
    return HistoryCursor.model_validate(document)


async def list_operations_for_chapter(db: AsyncIOMotorDatabase, chapter_id: str) -> list[Operation]:
    """Return every `Operation` recorded for `chapter_id`, ordered oldest-first by `created_at`
    — this order is the op-log's index space that `HistoryCursor.applied_count` counts into."""
    cursor = db[_OPERATIONS_COLLECTION].find({"chapter_id": chapter_id}).sort("created_at", 1)
    documents = await cursor.to_list(length=None)
    return [Operation.model_validate(document) for document in documents]


async def get_placement(db: AsyncIOMotorDatabase, operation_id: str) -> OperationPlacement | None:
    """Fetch the `OperationPlacement` recorded alongside `operation_id`, or `None` if it has
    none (only insertion `Operation`s recorded via `record_anchor_insertion_operations` have
    one)."""
    document = await db[_PLACEMENTS_COLLECTION].find_one({"operation_id": operation_id})
    if document is None:
        return None
    return OperationPlacement.model_validate(document)


async def _set_applied_count(db: AsyncIOMotorDatabase, chapter_id: str, applied_count: int) -> None:
    cursor = HistoryCursor(
        chapter_id=chapter_id, applied_count=applied_count, updated_at=datetime.now(UTC)
    )
    await db[_CURSORS_COLLECTION].replace_one(
        {"chapter_id": chapter_id}, cursor.model_dump(), upsert=True
    )


async def record_anchor_insertion_operations(
    db: AsyncIOMotorDatabase,
    chapter_id: str,
    base_version_id: str,
    anchor_block_id: str,
    new_blocks: list[Block],
    applied_by: str,
) -> list[Operation]:
    """Record one insertion `Operation` per entry of `new_blocks` (TASK-E16-2), in the order they
    were spliced in, then advance `chapter_id`'s `HistoryCursor.applied_count` by that many.

    Before inserting anything, deletes every existing `Operation` (and its `OperationPlacement`)
    for `chapter_id` whose index (by `created_at` order) is `>= ` the cursor's current
    `applied_count` — the undone/redo-able tail (TASK-E16-3). If the caller never undid anything,
    `applied_count` already equals the total recorded so far and this deletes nothing.

    Each new `Operation`'s `block_id` is the new block's own `id`; `before_text=""` (nothing was
    there before an insertion); `after_text` is the block's `content`. Each one's
    `OperationPlacement.insert_after_block_id` is `anchor_block_id` for the first block in
    `new_blocks`, and the previous new block's own `id` for every subsequent one — reconstructing
    the exact splice order `versions.service.create_draft_version_at_anchor` inserted them in via
    `locks.models.insert_blocks_after`.
    """
    cursor = await get_history_cursor(db, chapter_id)
    applied_count = cursor.applied_count if cursor is not None else 0

    existing_operations = await list_operations_for_chapter(db, chapter_id)
    stale_operations = existing_operations[applied_count:]
    if stale_operations:
        stale_ids = [operation.id for operation in stale_operations]
        await db[_OPERATIONS_COLLECTION].delete_many({"id": {"$in": stale_ids}})
        await db[_PLACEMENTS_COLLECTION].delete_many({"operation_id": {"$in": stale_ids}})

    new_operations: list[Operation] = []
    insert_after_block_id = anchor_block_id
    for block in new_blocks:
        operation = Operation(
            chapter_id=chapter_id,
            base_version_id=base_version_id,
            block_id=block.id,
            before_text="",
            after_text=block.content,
            applied_by=applied_by,
        )
        await db[_OPERATIONS_COLLECTION].insert_one(operation.model_dump())

        placement = OperationPlacement(
            operation_id=operation.id, insert_after_block_id=insert_after_block_id
        )
        await db[_PLACEMENTS_COLLECTION].insert_one(placement.model_dump())

        new_operations.append(operation)
        insert_after_block_id = block.id

    await _set_applied_count(db, chapter_id, applied_count + len(new_operations))
    return new_operations


class UndoRedoResult(BaseModel):
    """Result of one `undo_operations`/`redo_operations` call: the chapter's updated draft
    `ChapterVersion` plus the resulting cursor position, so a caller (`history.router`) can
    report both without a second round-trip."""

    version: ChapterVersion
    applied_count: int
    total_operations: int


def _reassign_order(manifest: list[Block]) -> list[Block]:
    """Reassign `order` sequentially (0-based) over `manifest`, matching
    `locks.models.insert_blocks_after`'s own convention — every block keeps its `id`/
    `content_hash`/`content`, only `order` may shift."""
    return [block.model_copy(update={"order": order}) for order, block in enumerate(manifest)]


async def undo_operations(db: AsyncIOMotorDatabase, chapter_id: str, count: int) -> UndoRedoResult:
    """Revert the last `count` applied `Operation`(s) for `chapter_id` against its current
    pending draft (TASK-E16-2), decrementing `HistoryCursor.applied_count` by `count`.

    Every operation this codebase records is an insertion with `before_text=""`
    (`record_anchor_insertion_operations`), so reverting one always means removing the block
    `operation.block_id` from the current draft's manifest — there is no partial/char-range
    revert to perform.

    Raises `HistoryReplayError` if: `chapter_id` has no pending draft ("no pending draft"); there
    is nothing to undo, i.e. `applied_count == 0` ("nothing to undo"); `count` exceeds
    `applied_count` ("only ... available"); or, while reverting, some operation's `block_id` can
    no longer be found in the manifest as it stands at that point in the undo sequence ("no
    longer exists in the current draft") — rejected outright, never guessing a new anchor
    (ADR-0012).
    """
    if count < 1:
        raise HistoryReplayError("count must be at least 1")

    draft = await get_latest_draft_version(db, chapter_id)
    if draft is None:
        raise HistoryReplayError(f"chapter {chapter_id!r} has no pending draft to undo against")

    cursor = await get_history_cursor(db, chapter_id)
    applied_count = cursor.applied_count if cursor is not None else 0
    if applied_count == 0:
        raise HistoryReplayError(f"chapter {chapter_id!r} has nothing to undo")
    if count > applied_count:
        raise HistoryReplayError(
            f"cannot undo {count} operation(s) for chapter {chapter_id!r}; only "
            f"{applied_count} available"
        )

    operations = await list_operations_for_chapter(db, chapter_id)
    manifest = list(draft.manifest or [])

    for _ in range(count):
        applied_count -= 1
        operation = operations[applied_count]
        index = next(
            (i for i, block in enumerate(manifest) if block.id == operation.block_id), None
        )
        if index is None:
            raise HistoryReplayError(
                f"operation {operation.id!r}'s anchor block {operation.block_id!r} no longer "
                "exists in the current draft"
            )
        manifest = manifest[:index] + manifest[index + 1 :]

    manifest = _reassign_order(manifest)
    content = "\n".join(block.content for block in manifest)
    updated = await update_draft_manifest(db, draft.id, manifest, content)
    await _set_applied_count(db, chapter_id, applied_count)

    return UndoRedoResult(
        version=updated, applied_count=applied_count, total_operations=len(operations)
    )


async def redo_operations(db: AsyncIOMotorDatabase, chapter_id: str, count: int) -> UndoRedoResult:
    """Re-apply the next `count` undone `Operation`(s) for `chapter_id` against its current
    pending draft (TASK-E16-2), incrementing `HistoryCursor.applied_count` by `count`.

    Each re-applied operation is spliced back in via `locks.models.insert_blocks_after`, targeting
    its recorded `OperationPlacement.insert_after_block_id` — reusing the exact same splicing
    logic the original generation used, rather than reimplementing it. `insert_blocks_after`
    assigns the newly spliced block a fresh `id`; it is immediately overwritten back to
    `operation.block_id` so the re-applied block has the exact same identity (and thus content)
    as when it was first generated, and so a later undo of the same operation can find it again
    by that id.

    Raises `HistoryReplayError` if: `chapter_id` has no pending draft ("no pending draft"); there
    is nothing to redo, i.e. `applied_count == total_operations` ("nothing to redo"); `count`
    exceeds what's available ("only ... available"); or, while redoing, some operation's
    recorded insertion point can no longer be found in the manifest as it stands at that point in
    the redo sequence ("no longer exists in the current draft") — rejected outright, never
    guessing a new anchor (ADR-0012).
    """
    if count < 1:
        raise HistoryReplayError("count must be at least 1")

    draft = await get_latest_draft_version(db, chapter_id)
    if draft is None:
        raise HistoryReplayError(f"chapter {chapter_id!r} has no pending draft to redo against")

    operations = await list_operations_for_chapter(db, chapter_id)
    total = len(operations)
    cursor = await get_history_cursor(db, chapter_id)
    applied_count = cursor.applied_count if cursor is not None else 0
    if applied_count >= total:
        raise HistoryReplayError(f"chapter {chapter_id!r} has nothing to redo")
    if count > total - applied_count:
        raise HistoryReplayError(
            f"cannot redo {count} operation(s) for chapter {chapter_id!r}; only "
            f"{total - applied_count} available"
        )

    manifest = list(draft.manifest or [])

    for _ in range(count):
        operation = operations[applied_count]
        placement = await get_placement(db, operation.id)
        if placement is None:
            raise HistoryReplayError(
                f"operation {operation.id!r} has no recorded insertion point to redo against"
            )

        anchor_index = next(
            (i for i, block in enumerate(manifest) if block.id == placement.insert_after_block_id),
            None,
        )
        if anchor_index is None:
            raise HistoryReplayError(
                f"operation {operation.id!r}'s anchor block "
                f"{placement.insert_after_block_id!r} no longer exists in the current draft"
            )

        spliced = insert_blocks_after(
            manifest, placement.insert_after_block_id, [operation.after_text]
        )
        spliced[anchor_index + 1] = spliced[anchor_index + 1].model_copy(
            update={"id": operation.block_id}
        )
        manifest = spliced
        applied_count += 1

    manifest = _reassign_order(manifest)
    content = "\n".join(block.content for block in manifest)
    updated = await update_draft_manifest(db, draft.id, manifest, content)
    await _set_applied_count(db, chapter_id, applied_count)

    return UndoRedoResult(version=updated, applied_count=applied_count, total_operations=total)
