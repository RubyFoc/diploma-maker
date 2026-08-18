"""MongoDB storage for projects and chapters.

Storage-layer only: no HTTP routes (that's `projects.router`) and no generation logic. Documents
live in two collections, `projects` and `chapters`, each keyed by `id` (see `projects.models`).
"""

import re

from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.projects.models import Chapter, Project

# A leading run of non-digit characters, then a number — the same pragmatic regex-heuristic
# approach as `toc.parser`'s numbered-entry regex and `formatting.upload`'s citation-style guess:
# good enough to pull "2" out of "Chapter 2", "2.", "2) Literature Review", "Section 2", not a
# real outline-format parser.
_LEADING_NUMBER_RE = re.compile(r"^\D*(\d+)")

_PROJECTS_COLLECTION = "projects"
_CHAPTERS_COLLECTION = "chapters"
# Owned by `versions.service` (its `_COLLECTION`), duplicated here only so `delete_project` can
# cascade into it without importing that module's storage internals across the module boundary.
_CHAPTER_VERSIONS_COLLECTION = "chapter_versions"
# Owned by `sources.required` (its `_COLLECTION`), duplicated for the same cascade reason.
_REQUIRED_SOURCES_COLLECTION = "required_sources"


async def create_project(
    db: AsyncIOMotorDatabase,
    title: str,
    owner_id: str,
    institution_id: str | None = None,
) -> Project:
    """Create and insert a new `Project` with the given `title`, owned by `owner_id` (TASK-E11-1;
    the `sub` claim of the authenticated caller, see `auth.dependencies.get_current_user_id`).

    `institution_id` (TASK-INT-17) is stored as-is, with no validation that it resolves to an
    existing `formatting.models.InstitutionConfig` — `projects.router.export_project_endpoint`
    already fails open on an unresolvable id, so rejecting it here would only add a stricter
    failure mode than export itself has.
    """
    project = Project(title=title, owner_id=owner_id, institution_id=institution_id)
    await db[_PROJECTS_COLLECTION].insert_one(project.model_dump())
    return project


async def get_project(db: AsyncIOMotorDatabase, project_id: str) -> Project | None:
    """Fetch the project with `project_id`, or `None` if it doesn't exist."""
    document = await db[_PROJECTS_COLLECTION].find_one({"id": project_id})
    if document is None:
        return None
    return Project.model_validate(document)


async def update_project_title(db: AsyncIOMotorDatabase, project_id: str, title: str) -> None:
    """Set `project_id`'s stored `title` to `title` (auto-title generation, Phase 5.9).

    Does nothing (no error) if `project_id` doesn't exist, matching `delete_project`'s
    no-error-on-missing convention — callers that need existence guarantees should check with
    `get_project` first.
    """
    await db[_PROJECTS_COLLECTION].update_one({"id": project_id}, {"$set": {"title": title}})


async def update_chapter_summary(db: AsyncIOMotorDatabase, chapter_id: str, summary: str) -> None:
    """Set `chapter_id`'s stored `summary` to `summary` (accept-time summarization,
    `projects.router.accept_draft_version_endpoint`, TASK-E03-2 wiring).

    Does nothing (no error) if `chapter_id` doesn't exist, matching `update_project_title`'s
    no-error-on-missing convention — the caller already fails open on any summarization problem,
    so a missing chapter here is likewise not treated as an error.
    """
    await db[_CHAPTERS_COLLECTION].update_one({"id": chapter_id}, {"$set": {"summary": summary}})


async def list_projects_for_user(db: AsyncIOMotorDatabase, owner_id: str) -> list[Project]:
    """Return every project owned by `owner_id` (TASK-E11-2), in no particular order.

    Backs `GET /projects`, scoping the listing to the authenticated caller the same way
    `router._get_owned_project` scopes single-project lookups — a user only ever sees their own
    projects, never another user's.
    """
    cursor = db[_PROJECTS_COLLECTION].find({"owner_id": owner_id})
    documents = await cursor.to_list(length=None)
    return [Project.model_validate(document) for document in documents]


async def create_chapter(
    db: AsyncIOMotorDatabase,
    project_id: str,
    title: str,
    parent_chapter_id: str | None = None,
) -> Chapter:
    """Create and insert a new `Chapter` for `project_id` (or subchapter under
    `parent_chapter_id`, per ADR-0014).

    `order` is one past the current highest `order` among its siblings — other chapters/
    subchapters sharing the same `(project_id, parent_chapter_id)` — or `0` if it has none yet.
    """
    existing = await db[_CHAPTERS_COLLECTION].find_one(
        {"project_id": project_id, "parent_chapter_id": parent_chapter_id}, sort=[("order", -1)]
    )
    next_order = existing["order"] + 1 if existing is not None else 0

    chapter = Chapter(
        project_id=project_id, parent_chapter_id=parent_chapter_id, title=title, order=next_order
    )
    await db[_CHAPTERS_COLLECTION].insert_one(chapter.model_dump())
    return chapter


async def insert_chapter_at_order(
    db: AsyncIOMotorDatabase,
    project_id: str,
    title: str,
    order: int,
    parent_chapter_id: str | None = None,
) -> Chapter:
    """Create and insert a new `Chapter` for `project_id` (or subchapter under
    `parent_chapter_id`, per ADR-0014) at the given sibling `order`, displacing any existing
    siblings that are at or past it.

    Every existing sibling — sharing `(project_id, parent_chapter_id)` — with `order >= order` is
    shifted up by one (via a single `update_many` using `$inc`) BEFORE the new chapter is
    inserted, so there's never a moment where two siblings share an `order` value. Exposed via
    `POST /projects/{project_id}/chapters/insert` in `projects.router`.
    """
    await db[_CHAPTERS_COLLECTION].update_many(
        {
            "project_id": project_id,
            "parent_chapter_id": parent_chapter_id,
            "order": {"$gte": order},
        },
        {"$inc": {"order": 1}},
    )

    chapter = Chapter(
        project_id=project_id, parent_chapter_id=parent_chapter_id, title=title, order=order
    )
    await db[_CHAPTERS_COLLECTION].insert_one(chapter.model_dump())
    return chapter


def infer_insertion_order(existing_chapters: list[Chapter], title: str) -> int:
    """Decide where a new chapter titled `title` belongs among `existing_chapters`, purely from
    each title's leading number (e.g. "Chapter 2" -> `2`), per TASK-E10-3 / the E10 success
    criterion's "generating 'Chapter 2' is inserted between existing Chapters 1 and 3" example.

    `existing_chapters` must already be scoped to the target's siblings — same
    `(project_id, parent_chapter_id)`, per ADR-0014 — since this function has no DB access of its
    own to do that filtering itself; passing a mixed set of chapters and subchapters will infer a
    nonsensical position. `projects.router.insert_chapter_endpoint` does this filtering before
    calling in.

    Returns the `order` the new chapter should be inserted at (displacing the chapter currently
    there and everything after it forward — see `insert_chapter_at_order`). This is a pure
    decision function: it does not touch the database or call `insert_chapter_at_order` itself;
    composing the two (and exposing them over HTTP) is later, `projects.router`-owning work.

    The heuristic: extract the new title's leading number, then walk `existing_chapters` in
    `order` sequence and return the `order` of the first one whose own leading number is `>=` the
    new title's number (so the new chapter is inserted just before it). Falls back to
    append-at-end — `max(order) + 1`, or `0` if `existing_chapters` is empty — whenever there's no
    clear numeric signal: the new title has no extractable number, or no existing chapter has a
    number `>=` it. "No clear signal" should default to safe append, never a guess.
    """
    if not existing_chapters:
        return 0

    append_order = max(chapter.order for chapter in existing_chapters) + 1

    new_match = _LEADING_NUMBER_RE.match(title)
    if new_match is None:
        return append_order
    new_number = int(new_match.group(1))

    for chapter in sorted(existing_chapters, key=lambda chapter: chapter.order):
        existing_match = _LEADING_NUMBER_RE.match(chapter.title)
        if existing_match is None:
            continue
        if int(existing_match.group(1)) >= new_number:
            return chapter.order

    return append_order


async def reorder_chapters(
    db: AsyncIOMotorDatabase,
    project_id: str,
    parent_chapter_id: str | None,
    chapter_ids: list[str],
) -> None:
    """Sets each id in `chapter_ids`'s `order` field to its position in the list (0, 1, 2, ...),
    scoped to `(project_id, parent_chapter_id)` per ADR-0014.

    Used by `projects.router`'s TOC/whole-document upload endpoints to make the final `order`
    match the just-parsed document sequence exactly, for every chapter/subchapter touched by that
    upload — overriding both `create_chapter`'s append-at-end default for newly created siblings
    and any stale `order` a *reused* (matched) chapter already carried from an earlier upload pass
    or manual creation. Without this, a chapter matched by `_match_existing_chapter` keeps
    whatever `order` it happened to get earlier while newly created siblings are appended at the
    end of the whole list, regardless of the position `title` actually has in the newly parsed
    TOC/document — silently producing an out-of-order chapter/subchapter list (user report).
    """
    for index, chapter_id in enumerate(chapter_ids):
        await db[_CHAPTERS_COLLECTION].update_one(
            {"id": chapter_id, "project_id": project_id, "parent_chapter_id": parent_chapter_id},
            {"$set": {"order": index}},
        )


async def list_chapters_for_project(db: AsyncIOMotorDatabase, project_id: str) -> list[Chapter]:
    """Return all chapters (and subchapters) for `project_id`, ordered by `order`.

    Note `order` is only unique within a `(project_id, parent_chapter_id)` scope (per ADR-0014),
    so a top-level chapter and one of its subchapters may share the same `order` value in this
    combined list — callers displaying a flat outline should group by `parent_chapter_id` first.
    `projects.router._build_project_detail` filters this down to top-level chapters
    (`parent_chapter_id is None`) rather than displaying the mixed list directly.
    """
    cursor = db[_CHAPTERS_COLLECTION].find({"project_id": project_id}).sort("order", 1)
    documents = await cursor.to_list(length=None)
    return [Chapter.model_validate(document) for document in documents]


async def list_subchapters(
    db: AsyncIOMotorDatabase, project_id: str, parent_chapter_id: str
) -> list[Chapter]:
    """Return the subchapters of `parent_chapter_id` within `project_id`, ordered by `order`
    (TASK-E12-2). Does not recurse: per ADR-0014's two-level nesting cap, a subchapter never has
    subchapters of its own, so there is no deeper level to return.
    """
    cursor = (
        db[_CHAPTERS_COLLECTION]
        .find({"project_id": project_id, "parent_chapter_id": parent_chapter_id})
        .sort("order", 1)
    )
    documents = await cursor.to_list(length=None)
    return [Chapter.model_validate(document) for document in documents]


async def get_chapter(db: AsyncIOMotorDatabase, chapter_id: str) -> Chapter | None:
    """Fetch the chapter with `chapter_id`, or `None` if it doesn't exist."""
    document = await db[_CHAPTERS_COLLECTION].find_one({"id": chapter_id})
    if document is None:
        return None
    return Chapter.model_validate(document)


async def delete_project(db: AsyncIOMotorDatabase, project_id: str) -> None:
    """Cascade-delete `project_id` and everything that hangs off it (TASK-E11-3).

    `ChapterVersion` has no direct `project_id` field (only `chapter_id`, see
    `versions.service`), so its versions must be reached via the project's chapter ids first.
    `required_sources` (TASK-E14-1, `sources.required`) does have a direct `project_id` field, so
    it's deleted alongside `chapters` directly. Order: `chapter_versions` for those chapter ids ->
    `chapters`/`required_sources` for `project_id` -> the `project` document itself. There are no
    FK constraints in Mongo, so this order isn't required for correctness, only for leaving the
    least orphaned data behind if the process is interrupted partway through.

    Does nothing (no error) if `project_id` doesn't exist — callers that need a 404 for an
    unknown/foreign project should check with `get_project`/`_get_owned_project` first, as
    `projects.router`'s delete endpoint does.
    """
    chapters = await list_chapters_for_project(db, project_id)
    chapter_ids = [chapter.id for chapter in chapters]

    if chapter_ids:
        await db[_CHAPTER_VERSIONS_COLLECTION].delete_many({"chapter_id": {"$in": chapter_ids}})
    await db[_CHAPTERS_COLLECTION].delete_many({"project_id": project_id})
    await db[_REQUIRED_SOURCES_COLLECTION].delete_many({"project_id": project_id})
    await db[_PROJECTS_COLLECTION].delete_one({"id": project_id})
