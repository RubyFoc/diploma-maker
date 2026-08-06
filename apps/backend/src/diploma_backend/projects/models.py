"""Project and chapter document shapes for the vertical-slice generation flow.

These are the first persisted parent records for chapters (`versions.models.ChapterVersion`
already exists but had no owning `Chapter`/`Project` collection until this task). Kept minimal:
no ordering/reordering API beyond `order`, no per-project settings — those belong to later tasks.
"""

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class Project(BaseModel):
    """One thesis/dissertation project, keyed by `id` (matching this codebase's convention of an
    explicit `id` field rather than Mongo's own `_id`, see `versions.models.ChapterVersion`).

    `owner_id` is the `sub` claim (user id) of the authenticated user who created the project
    (TASK-E11-1, `auth.dependencies.get_current_user_id`); every project-scoped route in
    `projects.router` requires a valid caller and treats a project owned by someone else as
    nonexistent (404), not a 403, to avoid leaking other users' project ids.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str
    title: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Chapter(BaseModel):
    """One chapter belonging to a `Project`, keyed by `id`.

    `order` is a zero-based position among the project's chapters, assigned by
    `projects.service.create_chapter` (one past the current highest `order` for the project).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    title: str
    order: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
