"""Must-cite authors/works model (TASK-E14-1), extending the `sources` module beyond
search/geo-fencing/vector storage.

A `RequiredSource` is a user-declared author/work the generated thesis must cite, captured during
onboarding (TASK-E14-4) or added later via `POST /projects/{project_id}/required-sources`
(TASK-E14-2, `sources.router`). This module is the model plus storage only — boosting/requiring
these sources in generation (TASK-E14-3, `projects.router._fetch_required_source_excerpts`) is a
separate call site into it, not part of it.
"""

import uuid
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

_COLLECTION = "required_sources"


class RequiredSource(BaseModel):
    """One must-cite author/work declared for a project, keyed by `id`.

    `title`/`year` are optional: a user may only care about an author's body of work in general
    ("must cite Smith") rather than one specific title/year. `author` is the only required field
    — an empty must-cite entry has nothing for `projects.router` to search for or verify against.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    author: str
    title: str | None = None
    year: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


async def create_required_source(
    db: AsyncIOMotorDatabase,
    project_id: str,
    author: str,
    title: str | None = None,
    year: int | None = None,
) -> RequiredSource:
    """Create and persist a new `RequiredSource` for `project_id`."""
    required_source = RequiredSource(project_id=project_id, author=author, title=title, year=year)
    await db[_COLLECTION].insert_one(required_source.model_dump())
    return required_source


async def list_required_sources_for_project(
    db: AsyncIOMotorDatabase, project_id: str
) -> list[RequiredSource]:
    """Return every must-cite source declared for `project_id`, in no particular order."""
    cursor = db[_COLLECTION].find({"project_id": project_id})
    documents = await cursor.to_list(length=None)
    return [RequiredSource.model_validate(document) for document in documents]
