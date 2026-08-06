"""Tests for `locks.service` (TASK-E13-4, ADR-0011): lock-placement freshness checks and
storage, against the in-memory Mongo fake used elsewhere (`test_chapter_insertion.py`,
`test_versions.py`).
"""

import pytest
from mongomock_motor import AsyncMongoMockClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.locks.models import CharRange
from diploma_backend.locks.service import (
    AnchorResolutionError,
    LockTargetError,
    find_valid_anchor,
    get_lock,
    list_locks_for_chapter,
    lock_block,
    reverify_anchor_resolution,
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


async def test_find_valid_anchor_returns_requested_block_when_unlocked() -> None:
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First.\nSecond.\nThird.")
    requested = accepted.manifest[1]

    resolution = await find_valid_anchor(db, "c1", requested.id)

    assert resolution.used_block_id == requested.id
    assert resolution.used_block_content_hash == requested.content_hash
    assert resolution.rerouted_from_block_id is None


async def test_find_valid_anchor_reroutes_forward_to_nearest_unlocked_block() -> None:
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First.\nSecond.\nThird.")
    requested, forward_neighbor = accepted.manifest[1], accepted.manifest[2]
    await lock_block(db, "c1", requested.id, requested.content_hash)

    resolution = await find_valid_anchor(db, "c1", requested.id)

    assert resolution.requested_block_id == requested.id
    assert resolution.used_block_id == forward_neighbor.id
    assert resolution.rerouted_from_block_id == requested.id


async def test_find_valid_anchor_reroutes_backward_when_nothing_unlocked_forward() -> None:
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First.\nSecond.\nThird.")
    backward_neighbor, requested, forward_neighbor = accepted.manifest
    await lock_block(db, "c1", requested.id, requested.content_hash)
    await lock_block(db, "c1", forward_neighbor.id, forward_neighbor.content_hash)

    resolution = await find_valid_anchor(db, "c1", requested.id)

    assert resolution.used_block_id == backward_neighbor.id
    assert resolution.rerouted_from_block_id == requested.id


async def test_find_valid_anchor_raises_when_entire_manifest_is_locked() -> None:
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First.\nSecond.")
    for block in accepted.manifest:
        await lock_block(db, "c1", block.id, block.content_hash)

    with pytest.raises(AnchorResolutionError, match="no unlocked block"):
        await find_valid_anchor(db, "c1", accepted.manifest[0].id)


async def test_find_valid_anchor_unknown_block_raises() -> None:
    db = _db()
    await _accepted_version_with_manifest(db, "c1", "First.")

    with pytest.raises(AnchorResolutionError, match="not found"):
        await find_valid_anchor(db, "c1", "does-not-exist")


async def test_find_valid_anchor_no_accepted_version_raises() -> None:
    db = _db()

    with pytest.raises(AnchorResolutionError, match="no accepted version"):
        await find_valid_anchor(db, "c1", "some-block")


async def test_reverify_anchor_resolution_passes_when_nothing_changed() -> None:
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First.\nSecond.")
    resolution = await find_valid_anchor(db, "c1", accepted.manifest[0].id)

    await reverify_anchor_resolution(db, "c1", resolution)


async def test_reverify_anchor_resolution_rejects_a_lock_placed_after_resolution() -> None:
    """Simulates TASK-E15-2's TOCTOU race: a lock lands on the resolved anchor between the
    pre-LLM resolution and the pre-persistence reverification."""
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First.\nSecond.")
    resolution = await find_valid_anchor(db, "c1", accepted.manifest[0].id)

    await lock_block(db, "c1", accepted.manifest[0].id, accepted.manifest[0].content_hash)

    with pytest.raises(AnchorResolutionError, match="no longer valid"):
        await reverify_anchor_resolution(db, "c1", resolution)


async def test_reverify_anchor_resolution_rejects_stale_content_hash() -> None:
    """A concurrently accepted new version changes the anchor block's content underneath a
    resolution captured before it, even without any lock involved (ADR-0011's hash-freshness
    posture applied to anchor resolution)."""
    db = _db()
    accepted = await _accepted_version_with_manifest(db, "c1", "First.\nSecond.")
    anchor_block_id = accepted.manifest[0].id
    resolution = await find_valid_anchor(db, "c1", anchor_block_id)

    new_draft = await create_draft_version(db, "c1", "Edited first.\nSecond.")
    await accept_draft_version(db, new_draft.id)

    with pytest.raises(AnchorResolutionError, match="no longer valid"):
        await reverify_anchor_resolution(db, "c1", resolution)
