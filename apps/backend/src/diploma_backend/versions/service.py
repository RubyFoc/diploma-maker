"""MongoDB storage for chapter versions (ADR-0004, TASK-E08-1).

Storage-layer only: no HTTP routes, no text-diff computation (ADR-0004 says the draft-vs-
accepted diff is computed on read by a later E08 task, not persisted here), and no `Chapter`
parent collection (none exists yet in this codebase). Documents live in the `chapter_versions`
collection, keyed by `id` (see `versions.models.ChapterVersion`).

Version numbering convention: a chapter's first version (whether created as a draft or directly
as accepted) is `version_number=0`; each subsequent version is one past the current accepted
version's number.

Write resilience: `docker-compose.yml`'s `mongo` service is a standalone single-node `mongo:7`
container, not a replica set or sharded cluster, so MongoDB's own automatic retryable-writes
feature (which requires one of those topologies) never kicks in here — a transient connection
blip during a write is not itself retried by the driver. `create_version`/`update_draft_manifest`
persist the result of a generation call that may already have been retried (and, for the "heavy"
tier draft call, expensively paid for) before ever reaching this module, so losing that work to a
transient Mongo write failure would be a needless waste. `_retry_mongo_write` wraps just the
actual `insert_one`/`update_one` calls with a short, bounded retry-with-backoff for exactly this
case — see that helper's docstring for why it's short and why it never swallows a persistent
failure.
"""

import asyncio
from collections.abc import Awaitable, Callable

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from diploma_backend.locks.models import (
    Block,
    build_manifest_from_text,
    insert_blocks_after,
    split_into_blocks,
)
from diploma_backend.versions.models import ChapterVersion

_COLLECTION = "chapter_versions"

# Short and bounded on purpose: this guards against a transient blip on a single non-replica-set
# Mongo instance (see module docstring), not a real outage. `max_attempts=3` with these delays
# adds at most ~1.5s of latency on top of an already-completed, already-expensive generation call
# before giving up and propagating the original error.
_MONGO_WRITE_MAX_ATTEMPTS = 3
_MONGO_WRITE_BASE_DELAY_SECONDS = 0.5


async def _retry_mongo_write[T](write: Callable[[], Awaitable[T]]) -> T:
    """Call `write()`, retrying on `PyMongoError` with exponential backoff.

    Mirrors `llm_routing.retry.generate_with_retry`'s shape (same "uniformly retry the broad
    exception type, no signal here to distinguish transient from permanent" reasoning, since
    `PyMongoError` covers `AutoReconnect`/`NetworkTimeout`/`ConnectionFailure` and similar
    transient-write failures without this module needing to enumerate each one individually).
    Sleeps `_MONGO_WRITE_BASE_DELAY_SECONDS * 2 ** attempt` between attempts (0.5s, then 1.0s with
    defaults). If every attempt fails, re-raises the last `PyMongoError` unchanged — this helper
    is for surviving a transient blip, not masking a persistent outage, so a real, ongoing failure
    must still surface to the caller exactly as it would without this wrapper.
    """
    last_error: PyMongoError | None = None
    for attempt in range(_MONGO_WRITE_MAX_ATTEMPTS):
        try:
            return await write()
        except PyMongoError as exc:
            last_error = exc
            if attempt < _MONGO_WRITE_MAX_ATTEMPTS - 1:
                await asyncio.sleep(_MONGO_WRITE_BASE_DELAY_SECONDS * 2**attempt)

    assert last_error is not None
    raise last_error


async def create_version(db: AsyncIOMotorDatabase, version: ChapterVersion) -> ChapterVersion:
    """Insert `version` into the `chapter_versions` collection and return it unchanged.

    The insert itself is retried up to `_MONGO_WRITE_MAX_ATTEMPTS` times on `PyMongoError` (see
    module docstring/`_retry_mongo_write`) before propagating a persistent failure.
    """
    await _retry_mongo_write(lambda: db[_COLLECTION].insert_one(version.model_dump()))
    return version


async def get_version(db: AsyncIOMotorDatabase, version_id: str) -> ChapterVersion | None:
    """Fetch the version with `version_id`, or `None` if it doesn't exist."""
    document = await db[_COLLECTION].find_one({"id": version_id})
    if document is None:
        return None
    return ChapterVersion.model_validate(document)


async def get_current_accepted_version(
    db: AsyncIOMotorDatabase, chapter_id: str
) -> ChapterVersion | None:
    """Return the accepted version with the highest `version_number` for `chapter_id`.

    This is the "current" version that drafts link/diff against. Returns `None` if the chapter
    has no accepted version yet.
    """
    document = await db[_COLLECTION].find_one(
        {"chapter_id": chapter_id, "status": "accepted"}, sort=[("version_number", -1)]
    )
    if document is None:
        return None
    return ChapterVersion.model_validate(document)


async def get_latest_draft_version(
    db: AsyncIOMotorDatabase, chapter_id: str
) -> ChapterVersion | None:
    """Return the draft version with the highest `version_number` for `chapter_id`.

    Mirrors `get_current_accepted_version` exactly but filters `status="draft"` instead of
    `status="accepted"`. Returns `None` if the chapter has no pending draft.
    """
    document = await db[_COLLECTION].find_one(
        {"chapter_id": chapter_id, "status": "draft"}, sort=[("version_number", -1)]
    )
    if document is None:
        return None
    return ChapterVersion.model_validate(document)


async def list_versions_for_chapter(
    db: AsyncIOMotorDatabase, chapter_id: str
) -> list[ChapterVersion]:
    """Return all versions (accepted and draft) for `chapter_id`, ordered by `version_number`."""
    cursor = db[_COLLECTION].find({"chapter_id": chapter_id}).sort("version_number", 1)
    documents = await cursor.to_list(length=None)
    return [ChapterVersion.model_validate(document) for document in documents]


async def create_draft_version(
    db: AsyncIOMotorDatabase, chapter_id: str, content: str
) -> ChapterVersion:
    """Build and insert a draft version proposed against the chapter's current accepted version.

    `parent_version_id` is set to the current accepted version's `id`, or `None` if the chapter
    has no accepted version yet. `version_number` is one past the current accepted version's
    number, or `0` if the chapter has no version at all yet (see module docstring for the
    numbering convention). `manifest` (ADR-0011, TASK-E13-2) is built fresh from `content` via
    `locks.models.build_manifest_from_text` — every new version gets one, regardless of caller.
    """
    current = await get_current_accepted_version(db, chapter_id)
    draft = ChapterVersion(
        chapter_id=chapter_id,
        version_number=current.version_number + 1 if current is not None else 0,
        content=content,
        manifest=build_manifest_from_text(content),
        status="draft",
        parent_version_id=current.id if current is not None else None,
    )
    return await create_version(db, draft)


async def create_draft_version_at_anchor(
    db: AsyncIOMotorDatabase,
    chapter_id: str,
    anchor_block_id: str,
    generated_content: str,
    applied_by: str,
) -> ChapterVersion:
    """Build and insert a draft version that splices freshly generated content into the
    chapter's current accepted manifest at `anchor_block_id`, instead of replacing the whole
    chapter (TASK-E15-1, ADR-0011).

    `generated_content` is split into one block per non-blank line via
    `locks.models.split_into_blocks` (same convention `build_manifest_from_text` uses for a
    full-chapter draft) and spliced in immediately after the anchor block via
    `locks.models.insert_blocks_after`, which preserves every pre-existing block's `id`/
    `content_hash`/`content` — only `order` may shift. The new version's `content` is the
    resulting manifest's block contents joined with `"\\n"`, matching how block-per-line content
    is joined elsewhere in this codebase. `version_number`/`parent_version_id` follow the same
    convention as `create_draft_version`.

    `applied_by` (the caller's user id) is recorded on each newly spliced block's `Operation`
    row (TASK-E16-2, ADR-0012) via `history.service.record_anchor_insertion_operations` — one op
    per new block, anchored to that block's own id, with `before_text=""` and `after_text` equal
    to the block's content. Recording first wipes any stale redo tail for this chapter
    (TASK-E16-3): a fresh edit after an undo discards whatever was undone, since this is a
    linear op-log, not a branching history. This is the ONLY generation path that records
    `Operation`s — full-chapter generation (`create_draft_version`) and uploaded-draft ingestion
    (`locks.router.upload_draft_endpoint`) have no clean block-level before/after decomposition
    and are deliberately left out of scope (ADR-0012).

    Imports `history.service` lazily (inside this function, not at module import time) because
    `history.service` itself imports from this module (`get_latest_draft_version`,
    `update_draft_manifest`) for undo/redo replay — a module-level import here would create an
    import cycle.

    Raises `ValueError` if the chapter has no accepted version yet ("no accepted version"), if
    that version has no block manifest ("no block manifest"), or if `anchor_block_id` isn't found
    in it (propagated from `insert_blocks_after`, message contains "not found").
    """
    accepted = await get_current_accepted_version(db, chapter_id)
    if accepted is None:
        raise ValueError(f"chapter {chapter_id!r} has no accepted version to insert into")
    if accepted.manifest is None:
        raise ValueError(f"chapter {chapter_id!r}'s current accepted version has no block manifest")

    anchor_index = next(
        (index for index, block in enumerate(accepted.manifest) if block.id == anchor_block_id),
        None,
    )
    if anchor_index is None:
        raise ValueError(f"block {anchor_block_id!r} not found in manifest")

    new_block_contents = split_into_blocks(generated_content)
    spliced_manifest = insert_blocks_after(accepted.manifest, anchor_block_id, new_block_contents)
    content = "\n".join(block.content for block in spliced_manifest)
    new_blocks = spliced_manifest[anchor_index + 1 : anchor_index + 1 + len(new_block_contents)]

    draft = ChapterVersion(
        chapter_id=chapter_id,
        version_number=accepted.version_number + 1,
        content=content,
        manifest=spliced_manifest,
        status="draft",
        parent_version_id=accepted.id,
    )
    created = await create_version(db, draft)

    from diploma_backend.history.service import record_anchor_insertion_operations

    await record_anchor_insertion_operations(
        db,
        chapter_id=chapter_id,
        base_version_id=accepted.id,
        anchor_block_id=anchor_block_id,
        new_blocks=new_blocks,
        applied_by=applied_by,
    )

    return created


async def update_draft_manifest(
    db: AsyncIOMotorDatabase, version_id: str, manifest: list[Block], content: str
) -> ChapterVersion:
    """Overwrite `manifest`/`content` on the existing draft version `version_id`, in place —
    no new row, no `version_number` bump (same in-place-`update_one` pattern as
    `accept_draft_version`'s status flip).

    Used by `history.service`'s undo/redo replay (TASK-E16-2) to mutate a chapter's current
    pending draft as operations are reverted/reapplied against it. Raises `ValueError` if no
    version with `version_id` exists, or if it exists but isn't currently a draft — undo/redo
    only ever mutate a pending draft, never an already-accepted, immutable version (ADR-0004).

    The update itself is retried on `PyMongoError` the same way `create_version`'s insert is —
    see module docstring/`_retry_mongo_write`.
    """
    version = await get_version(db, version_id)
    if version is None:
        raise ValueError(f"no version with id {version_id!r}")
    if version.status != "draft":
        raise ValueError(f"version {version_id!r} is not a draft (status={version.status!r})")

    await _retry_mongo_write(
        lambda: db[_COLLECTION].update_one(
            {"id": version_id},
            {"$set": {"manifest": [block.model_dump() for block in manifest], "content": content}},
        )
    )
    version.manifest = manifest
    version.content = content
    return version


async def accept_draft_version(db: AsyncIOMotorDatabase, version_id: str) -> ChapterVersion:
    """Flip the draft version `version_id` to `status="accepted"` and return it.

    This is an update to the existing draft row, not a new insert: ADR-0004 frames "each accepted
    edit creates a new version row" as describing the draft-to-accepted transition itself, not a
    second parallel row alongside the draft.

    Raises `ValueError` if no version with `version_id` exists, or if it exists but isn't
    currently a draft.
    """
    version = await get_version(db, version_id)
    if version is None:
        raise ValueError(f"no version with id {version_id!r}")
    if version.status != "draft":
        raise ValueError(f"version {version_id!r} is not a draft (status={version.status!r})")

    await db[_COLLECTION].update_one({"id": version_id}, {"$set": {"status": "accepted"}})
    version.status = "accepted"
    return version


async def reject_draft_version(db: AsyncIOMotorDatabase, version_id: str) -> ChapterVersion:
    """Flip the draft version `version_id` to `status="rejected"` and return it (user report:
    rejecting a draft used to be purely a frontend-local state change, so the very next full
    project refetch would resurrect it — see `versions.models.VersionStatus`'s docstring).

    Raises `ValueError` if no version with `version_id` exists, or if it exists but isn't
    currently a draft — same contract as `accept_draft_version`, since a version can only be
    resolved (accepted or rejected) once.
    """
    version = await get_version(db, version_id)
    if version is None:
        raise ValueError(f"no version with id {version_id!r}")
    if version.status != "draft":
        raise ValueError(f"version {version_id!r} is not a draft (status={version.status!r})")

    await db[_COLLECTION].update_one({"id": version_id}, {"$set": {"status": "rejected"}})
    version.status = "rejected"
    return version
