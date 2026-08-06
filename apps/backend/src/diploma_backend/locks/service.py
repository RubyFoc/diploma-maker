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
from pydantic import BaseModel

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


class AnchorResolutionError(ValueError):
    """Raised by `find_valid_anchor` when a `target_block_id` from `GenerateDraftRequest`
    (TASK-E15-1) cannot be used as-is AND no deterministic reroute is possible either, for any of
    the fail-closed reasons `find_valid_anchor` checks (see its docstring).

    `projects.router.generate_chapter_draft_endpoint` distinguishes the specific reason by
    substring, same convention as `LockTargetError`, and translates it to the matching 4xx status
    (404 for "doesn't exist" cases, 409 for "exists but every block is locked").
    """


class AnchorResolution(BaseModel):
    """The deterministic outcome of `find_valid_anchor` for one `requested_block_id` (TASK-E15-2,
    ADR-0011): either the requested anchor was already unlocked and is used as-is, or it was
    locked and got rerouted to the nearest unlocked block.

    `requested_block_id` is kept on the resolution (not just passed as a bare id) so
    `reverify_anchor_resolution` can re-run the exact same deterministic search against the
    *original* request rather than the (possibly already-rerouted) `used_block_id` — rerouting
    from a rerouted anchor a second time would silently drift from what the prompt shown to the
    model was actually built around.

    `used_block_content_hash` is the resolved anchor block's `Block.content_hash` at resolution
    time, captured so a caller can later detect (`reverify_anchor_resolution`) that the block's
    content changed underneath it — the same hash-freshness posture as ADR-0011's lock-freshness
    check, applied to anchor resolution instead of lock placement.
    """

    requested_block_id: str
    used_block_id: str
    used_block_content_hash: str
    rerouted_from_block_id: str | None = None


async def find_valid_anchor(
    db: AsyncIOMotorDatabase, chapter_id: str, requested_block_id: str
) -> AnchorResolution:
    """Deterministically resolve `requested_block_id` into a safe anchor for "insert at anchor"
    generation (TASK-E15-1), never trusting the model's promise to leave locked spans alone
    (TASK-E15-2, ADR-0011) — this is the actual enforcement, run in code before any LLM call and
    again right before persistence (`reverify_anchor_resolution`).

    Fetches the chapter's current accepted manifest and every active lock
    (`list_locks_for_chapter`). A lock protects its whole anchored block for the purposes of this
    check even when it also carries a `char_range`: insertion happens at block granularity (see
    `locks.models.insert_blocks_after`), so a sub-block lock still makes that entire block an
    unsafe insertion point.

    - If `requested_block_id` is NOT covered by any lock: returned as-is, `rerouted_from_block_id`
      is `None`.
    - If it IS locked: rerouted to the nearest unlocked block, searching forward from the
      requested block's position first (towards the end of the manifest), then backward from it
      if nothing unlocked is found forward. This tie-break (forward-first) is arbitrary but fixed
      deterministically: inserting a bit further down the chapter than the user pointed at is a
      strictly smaller surprise than inserting into an earlier section, so forward is preferred
      when both directions have a candidate equally near.
    - If every block in the manifest is locked (no unlocked block exists at all): raises
      `AnchorResolutionError` ("no unlocked block available") — a real "cannot fulfill this
      request" failure, never returned as a `None` mixed in with the no-reroute case.

    Raises `AnchorResolutionError` if the chapter has no accepted version yet
    ("no accepted version"), that version has no manifest ("no block manifest"), or
    `requested_block_id` isn't found in it ("not found").
    """
    accepted = await get_current_accepted_version(db, chapter_id)
    if accepted is None:
        raise AnchorResolutionError(f"chapter {chapter_id!r} has no accepted version to insert into")
    if accepted.manifest is None:
        raise AnchorResolutionError(
            f"chapter {chapter_id!r}'s current accepted version has no block manifest"
        )

    manifest = accepted.manifest
    requested_index = next(
        (index for index, block in enumerate(manifest) if block.id == requested_block_id), None
    )
    if requested_index is None:
        raise AnchorResolutionError(
            f"block {requested_block_id!r} not found in chapter {chapter_id!r}"
        )

    locks = await list_locks_for_chapter(db, chapter_id)
    locked_block_ids = {lock.block_id for lock in locks}

    if manifest[requested_index].id not in locked_block_ids:
        block = manifest[requested_index]
        return AnchorResolution(
            requested_block_id=requested_block_id,
            used_block_id=block.id,
            used_block_content_hash=block.content_hash,
        )

    for index in range(requested_index + 1, len(manifest)):
        if manifest[index].id not in locked_block_ids:
            return AnchorResolution(
                requested_block_id=requested_block_id,
                used_block_id=manifest[index].id,
                used_block_content_hash=manifest[index].content_hash,
                rerouted_from_block_id=requested_block_id,
            )

    for index in range(requested_index - 1, -1, -1):
        if manifest[index].id not in locked_block_ids:
            return AnchorResolution(
                requested_block_id=requested_block_id,
                used_block_id=manifest[index].id,
                used_block_content_hash=manifest[index].content_hash,
                rerouted_from_block_id=requested_block_id,
            )

    raise AnchorResolutionError(
        f"chapter {chapter_id!r} has no unlocked block available as an insertion anchor "
        "(every block is currently locked)"
    )


async def reverify_anchor_resolution(
    db: AsyncIOMotorDatabase, chapter_id: str, resolution: AnchorResolution
) -> None:
    """Re-run `find_valid_anchor` against `resolution.requested_block_id` immediately before
    persisting a generation that used `resolution` (TASK-E15-2), closing the TOCTOU gap between
    resolving an anchor and persisting into it: a lock can be placed, or the anchor block's
    content can change (a concurrently accepted new version), during the LLM round-trip in
    between.

    Raises `AnchorResolutionError` (same fail-closed posture as `find_valid_anchor` and
    `locks.service.lock_block`) if re-resolving no longer produces the exact same
    `used_block_id`/`used_block_content_hash` as `resolution` — either because the previously
    unlocked anchor is now locked (a lock placed concurrently, so a fresh resolution reroutes
    elsewhere or fails outright), because its content changed underneath it (a stale anchor, same
    hash-freshness posture as ADR-0011), or because the anchor block (or the whole chapter's
    accepted version) no longer exists at all (e.g. a concurrently accepted new version rebuilt
    the manifest from scratch, per `versions.service.create_draft_version`, discarding the old
    block ids entirely) — any `AnchorResolutionError` from the fresh `find_valid_anchor` call is
    treated the same way here, since every one of those cases means the previously observed
    anchor can no longer be trusted. Deliberately does not attempt a second reroute here: the
    prompt already shown to the model was built around `resolution.used_block_id`'s specific
    neighboring context, so silently rerouting a second time at persistence time would splice
    content generated for one insertion point into a different one.
    """
    try:
        fresh = await find_valid_anchor(db, chapter_id, resolution.requested_block_id)
    except AnchorResolutionError as exc:
        raise AnchorResolutionError(
            f"anchor {resolution.used_block_id!r} in chapter {chapter_id!r} is no longer valid: "
            f"{exc}"
        ) from exc

    if (
        fresh.used_block_id != resolution.used_block_id
        or fresh.used_block_content_hash != resolution.used_block_content_hash
    ):
        raise AnchorResolutionError(
            f"anchor {resolution.used_block_id!r} in chapter {chapter_id!r} is no longer valid "
            "(locked or its content changed since it was resolved); rejecting rather than "
            "persisting into a stale or now-locked anchor"
        )


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
