"""MongoDB storage for chapter versions (ADR-0004, TASK-E08-1).

Storage-layer only: no HTTP routes, no text-diff computation (ADR-0004 says the draft-vs-
accepted diff is computed on read by a later E08 task, not persisted here), and no `Chapter`
parent collection (none exists yet in this codebase). Documents live in the `chapter_versions`
collection, keyed by `id` (see `versions.models.ChapterVersion`).

Version numbering convention: a chapter's first version (whether created as a draft or directly
as accepted) is `version_number=0`; each subsequent version is one past the current accepted
version's number.
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.locks.models import (
    build_manifest_from_text,
    insert_blocks_after,
    split_into_blocks,
)
from diploma_backend.versions.models import ChapterVersion

_COLLECTION = "chapter_versions"


async def create_version(db: AsyncIOMotorDatabase, version: ChapterVersion) -> ChapterVersion:
    """Insert `version` into the `chapter_versions` collection and return it unchanged."""
    await db[_COLLECTION].insert_one(version.model_dump())
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
    db: AsyncIOMotorDatabase, chapter_id: str, anchor_block_id: str, generated_content: str
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

    Raises `ValueError` if the chapter has no accepted version yet ("no accepted version"), if
    that version has no block manifest ("no block manifest"), or if `anchor_block_id` isn't found
    in it (propagated from `insert_blocks_after`, message contains "not found").
    """
    accepted = await get_current_accepted_version(db, chapter_id)
    if accepted is None:
        raise ValueError(f"chapter {chapter_id!r} has no accepted version to insert into")
    if accepted.manifest is None:
        raise ValueError(f"chapter {chapter_id!r}'s current accepted version has no block manifest")

    new_block_contents = split_into_blocks(generated_content)
    spliced_manifest = insert_blocks_after(accepted.manifest, anchor_block_id, new_block_contents)
    content = "\n".join(block.content for block in spliced_manifest)

    draft = ChapterVersion(
        chapter_id=chapter_id,
        version_number=accepted.version_number + 1,
        content=content,
        manifest=spliced_manifest,
        status="draft",
        parent_version_id=accepted.id,
    )
    return await create_version(db, draft)


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
