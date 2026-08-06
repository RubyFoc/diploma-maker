"""MongoDB storage and lock/unlock business logic for protected block ranges (ADR-0011,
TASK-E13-4).

Storage-layer plus the freshness-check logic: no HTTP routes (that's `locks.router`). Documents
live in the `chapter_locks` collection, keyed by `id` (see `locks.models.Lock`).

Locks anchor into a chapter's *current accepted* content, not an unreviewed pending draft: a
draft might still be rejected or regenerated, so protecting a range inside it would be protecting
content that may never become the chapter's real, stable text. This mirrors `PaginatedDocument`'s
own choice of what to render as "the document" — the accepted version, not the diff-in-progress.
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.locks.models import CharRange, Lock
from diploma_backend.versions.service import get_current_accepted_version

_COLLECTION = "chapter_locks"


class LockTargetError(ValueError):
    """Raised when a lock can't be placed on the requested block, for any of the fail-closed
    reasons `lock_block` checks (see its docstring) — the block/chapter doesn't exist, the
    chapter has no manifest yet to anchor into, or the caller's `block_content_hash` is stale.

    Callers (the `locks.router` endpoint) distinguish the specific reason by substring, matching
    `versions.service.accept_draft_version`'s `ValueError`-message-substring convention, and
    translate each to the appropriate 4xx status.
    """


async def lock_block(
    db: AsyncIOMotorDatabase,
    chapter_id: str,
    block_id: str,
    block_content_hash: str,
    char_range: CharRange | None = None,
) -> Lock:
    """Create and persist a `Lock` anchored to `block_id` in `chapter_id`'s current accepted
    content, after verifying `block_content_hash` (the hash the caller last observed) still
    matches that block's actual current hash — fail-closed on any mismatch (ADR-0011), same
    posture as ADR-0001's citation-verification retry/reject contract.

    Raises `LockTargetError` (translated by the router into the matching 4xx) if:
    - the chapter has no accepted version yet ("no accepted version"),
    - the chapter's current accepted version has no manifest yet, e.g. a version persisted before
      TASK-E13-2 ("no block manifest"),
    - `block_id` isn't in that manifest ("block ... not found"),
    - `block_content_hash` doesn't match the block's actual current hash ("stale lock").
    """
    accepted = await get_current_accepted_version(db, chapter_id)
    if accepted is None:
        raise LockTargetError(f"chapter {chapter_id!r} has no accepted version to lock")
    if accepted.manifest is None:
        raise LockTargetError(
            f"chapter {chapter_id!r}'s current accepted version has no block manifest"
        )

    block = next((block for block in accepted.manifest if block.id == block_id), None)
    if block is None:
        raise LockTargetError(f"block {block_id!r} not found in chapter {chapter_id!r}")
    if block.content_hash != block_content_hash:
        raise LockTargetError(
            f"stale lock: block {block_id!r}'s content has changed since it was last observed"
        )

    lock = Lock(
        chapter_id=chapter_id,
        block_id=block_id,
        block_content_hash=block.content_hash,
        char_range=char_range,
    )
    await db[_COLLECTION].insert_one(lock.model_dump())
    return lock


async def list_locks_for_chapter(db: AsyncIOMotorDatabase, chapter_id: str) -> list[Lock]:
    """Return every lock currently placed on `chapter_id`, in no particular order."""
    cursor = db[_COLLECTION].find({"chapter_id": chapter_id})
    documents = await cursor.to_list(length=None)
    return [Lock.model_validate(document) for document in documents]


async def get_lock(db: AsyncIOMotorDatabase, lock_id: str) -> Lock | None:
    """Fetch the lock with `lock_id`, or `None` if it doesn't exist."""
    document = await db[_COLLECTION].find_one({"id": lock_id})
    if document is None:
        return None
    return Lock.model_validate(document)


async def unlock(db: AsyncIOMotorDatabase, chapter_id: str, lock_id: str) -> None:
    """Delete the lock with `lock_id`, scoped to `chapter_id` — a lock belonging to a different
    chapter is left untouched, so a caller can't delete another chapter's lock by pairing its id
    with a `chapter_id` they do own (`locks.router` already checks caller-ownership of
    `chapter_id` itself; this is what stops the pairing trick). Does nothing (no error) either
    way if no matching lock exists, matching `projects.service.delete_project`'s
    no-error-on-missing convention — no freshness check is needed to remove a lock, only to place
    one.
    """
    await db[_COLLECTION].delete_one({"id": lock_id, "chapter_id": chapter_id})
