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

    `url` (user request) is a direct link to the source itself — e.g. a GOST-style citation's own
    `URL: ...` segment — used by `projects.router._fetch_required_source_excerpts` as its first,
    most reliable grounding attempt before falling back to external academic/web search, since a
    user-supplied direct link is far more likely to resolve than a keyword search for a
    regional-journal work those search providers don't index at all.

    `cached_excerpt` holds the text extracted from `url` (or found via search) the first time
    grounding succeeds for this source, via `update_required_source_cached_excerpt` — grounding
    doesn't re-fetch/re-search on every subsequent generation call once a source has one.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    author: str
    title: str | None = None
    year: int | None = None
    url: str | None = None
    cached_excerpt: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


async def create_required_source(
    db: AsyncIOMotorDatabase,
    project_id: str,
    author: str,
    title: str | None = None,
    year: int | None = None,
    url: str | None = None,
) -> RequiredSource:
    """Create and persist a new `RequiredSource` for `project_id`."""
    required_source = RequiredSource(
        project_id=project_id, author=author, title=title, year=year, url=url
    )
    await db[_COLLECTION].insert_one(required_source.model_dump())
    return required_source


async def list_required_sources_for_project(
    db: AsyncIOMotorDatabase, project_id: str
) -> list[RequiredSource]:
    """Return every must-cite source declared for `project_id`, in no particular order."""
    cursor = db[_COLLECTION].find({"project_id": project_id})
    documents = await cursor.to_list(length=None)
    return [RequiredSource.model_validate(document) for document in documents]


async def update_required_source_cached_excerpt(
    db: AsyncIOMotorDatabase, source_id: str, excerpt: str
) -> None:
    """Persists `excerpt` (grounding text from `url` or an external search hit) onto
    `source_id`, so future generation calls reuse it instead of re-fetching/re-searching.

    Does nothing (no error) if `source_id` doesn't exist, matching `projects.service`'s
    `update_chapter_summary`/`update_project_title` no-error-on-missing convention — the caller
    already fails open on any grounding problem, so a missing/deleted source here is likewise not
    treated as an error.
    """
    await db[_COLLECTION].update_one({"id": source_id}, {"$set": {"cached_excerpt": excerpt}})
