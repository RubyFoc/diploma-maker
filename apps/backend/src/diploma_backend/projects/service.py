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


async def create_project(db: AsyncIOMotorDatabase, title: str) -> Project:
    """Create and insert a new `Project` with the given `title`."""
    project = Project(title=title)
    await db[_PROJECTS_COLLECTION].insert_one(project.model_dump())
    return project


async def get_project(db: AsyncIOMotorDatabase, project_id: str) -> Project | None:
    """Fetch the project with `project_id`, or `None` if it doesn't exist."""
    document = await db[_PROJECTS_COLLECTION].find_one({"id": project_id})
    if document is None:
        return None
    return Project.model_validate(document)


async def create_chapter(db: AsyncIOMotorDatabase, project_id: str, title: str) -> Chapter:
    """Create and insert a new `Chapter` for `project_id`.

    `order` is one past the current highest `order` among the project's existing chapters, or `0`
    if it has none yet.
    """
    existing = await db[_CHAPTERS_COLLECTION].find_one(
        {"project_id": project_id}, sort=[("order", -1)]
    )
    next_order = existing["order"] + 1 if existing is not None else 0

    chapter = Chapter(project_id=project_id, title=title, order=next_order)
    await db[_CHAPTERS_COLLECTION].insert_one(chapter.model_dump())
    return chapter


async def insert_chapter_at_order(
    db: AsyncIOMotorDatabase, project_id: str, title: str, order: int
) -> Chapter:
    """Create and insert a new `Chapter` for `project_id` at the given `order`, displacing any
    existing chapters that are at or past it.

    Every existing chapter for `project_id` with `order >= order` is shifted up by one (via a
    single `update_many` using `$inc`) BEFORE the new chapter is inserted, so there's never a
    moment where two chapters share an `order` value. This is TASK-E10-3's storage-layer half of
    "chapter-boundary-aware insertion" (see docs/project/epics.md's E10 success criterion): it has
    no HTTP route yet — `projects.router` is owned by a parallel task this round — wiring an
    endpoint (likely calling `infer_insertion_order` then this function) is follow-up work.
    """
    await db[_CHAPTERS_COLLECTION].update_many(
        {"project_id": project_id, "order": {"$gte": order}},
        {"$inc": {"order": 1}},
    )

    chapter = Chapter(project_id=project_id, title=title, order=order)
    await db[_CHAPTERS_COLLECTION].insert_one(chapter.model_dump())
    return chapter


def infer_insertion_order(existing_chapters: list[Chapter], title: str) -> int:
    """Decide where a new chapter titled `title` belongs among `existing_chapters`, purely from
    each title's leading number (e.g. "Chapter 2" -> `2`), per TASK-E10-3 / the E10 success
    criterion's "generating 'Chapter 2' is inserted between existing Chapters 1 and 3" example.

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


async def list_chapters_for_project(
    db: AsyncIOMotorDatabase, project_id: str
) -> list[Chapter]:
    """Return all chapters for `project_id`, ordered by `order`."""
    cursor = db[_CHAPTERS_COLLECTION].find({"project_id": project_id}).sort("order", 1)
    documents = await cursor.to_list(length=None)
    return [Chapter.model_validate(document) for document in documents]


async def get_chapter(db: AsyncIOMotorDatabase, chapter_id: str) -> Chapter | None:
    """Fetch the chapter with `chapter_id`, or `None` if it doesn't exist."""
    document = await db[_CHAPTERS_COLLECTION].find_one({"id": chapter_id})
    if document is None:
        return None
    return Chapter.model_validate(document)
