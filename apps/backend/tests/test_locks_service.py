"""Tests for `locks.service` (TASK-E13-4, ADR-0011): lock-placement freshness checks and
storage, against the in-memory Mongo fake used elsewhere (`test_chapter_insertion.py`,
`test_versions.py`).
"""

import pytest
from mongomock_motor import AsyncMongoMockClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.locks.models import CharRange
from diploma_backend.locks.service import (
    LockTargetError,
    get_lock,
    list_locks_for_chapter,
    lock_block,
    unlock,
)
from diploma_backend.versions.service import accept_draft_version, create_draft_version


def _db() -> AsyncIOMotorDatabase:
    return AsyncMongoMockClient()["diploma_maker_test"]


async def _accepted_version_with_manifest(db: AsyncIOMotorDatabase, chapter_id: str, content: str):
    draft = await create_draft_version(db, chapter_id, content)
    return await accept_draft_version(db, draft.id)


async def test_lock_block_succeeds_with_current_hash() -> None:
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First paragraph.")
    block = accepted.manifest[0]

    lock = await lock_block(db, "c1", block.id, block.content_hash)

    assert lock.chapter_id == "c1"
    assert lock.block_id == block.id
    assert lock.block_content_hash == block.content_hash
    assert lock.char_range is None


async def test_lock_block_persists_char_range() -> None:
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First paragraph.")
    block = accepted.manifest[0]

    lock = await lock_block(db, "c1", block.id, block.content_hash, CharRange(start=0, end=5))

    fetched = await get_lock(db, lock.id)
    assert fetched is not None
    assert fetched.char_range == CharRange(start=0, end=5)


async def test_lock_block_stale_hash_raises() -> None:
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First paragraph.")
    block = accepted.manifest[0]

    with pytest.raises(LockTargetError, match="stale lock"):
        await lock_block(db, "c1", block.id, "not-the-real-hash")


async def test_lock_block_unknown_block_id_raises() -> None:
    db = _db()
    await _accepted_version_with_manifest(db, "c1", "First paragraph.")

    with pytest.raises(LockTargetError, match="not found"):
        await lock_block(db, "c1", "does-not-exist", "any-hash")


async def test_lock_block_chapter_with_no_accepted_version_raises() -> None:
    db = _db()

    with pytest.raises(LockTargetError, match="no accepted version"):
        await lock_block(db, "c1", "some-block", "any-hash")


async def test_lock_block_accepted_version_without_manifest_raises() -> None:
    """Simulates a pre-TASK-E13-2 legacy version with no manifest (ADR-0011's retrofit
    consequence)."""
    db = _db()
    draft = await create_draft_version(db, "c1", "content")
    accepted = await accept_draft_version(db, draft.id)
    await db["chapter_versions"].update_one({"id": accepted.id}, {"$set": {"manifest": None}})

    with pytest.raises(LockTargetError, match="no block manifest"):
        await lock_block(db, "c1", "some-block", "any-hash")


async def test_list_locks_for_chapter_returns_only_that_chapters_locks() -> None:
    db = _db()
    accepted_1 = await _accepted_version_with_manifest(db, "c1", "Chapter one text.")
    accepted_2 = await _accepted_version_with_manifest(db, "c2", "Chapter two text.")
    block_1 = accepted_1.manifest[0]
    block_2 = accepted_2.manifest[0]

    await lock_block(db, "c1", block_1.id, block_1.content_hash)
    await lock_block(db, "c2", block_2.id, block_2.content_hash)

    locks = await list_locks_for_chapter(db, "c1")
    assert len(locks) == 1
    assert locks[0].chapter_id == "c1"


async def test_unlock_removes_a_lock() -> None:
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First paragraph.")
    block = accepted.manifest[0]
    lock = await lock_block(db, "c1", block.id, block.content_hash)

    await unlock(db, "c1", lock.id)

    assert await get_lock(db, lock.id) is None


async def test_unlock_does_not_remove_a_lock_from_a_different_chapter() -> None:
    """Guards the authorization-relevant scoping: `unlock` must not delete a lock whose
    `chapter_id` doesn't match the one passed in, even if the caller supplies a valid `lock_id`
    from a different chapter."""
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First paragraph.")
    block = accepted.manifest[0]
    lock = await lock_block(db, "c1", block.id, block.content_hash)

    await unlock(db, "some-other-chapter", lock.id)

    assert await get_lock(db, lock.id) is not None


async def test_unlock_missing_lock_id_does_nothing() -> None:
    db = _db()
    await unlock(db, "c1", "does-not-exist")
