"""MongoDB storage for projects and chapters.

Storage-layer only: no HTTP routes (that's `projects.router`) and no generation logic. Documents
live in two collections, `projects` and `chapters`, each keyed by `id` (see `projects.models`).
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.projects.models import Chapter, Project

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
