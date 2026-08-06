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

    `institution_id` (TASK-INT-17) optionally names a stored `formatting.models.InstitutionConfig`
    to style this project's export with (`projects.router.export_project_endpoint`), set at
    creation time (`CreateProjectRequest.institution_id`) rather than re-supplied per export.
    `None` for projects created before this field existed, or for a project whose author never
    picked an institution — either way export still succeeds, just unstyled (see
    `export_project_endpoint`'s docstring).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str
    title: str
    institution_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Chapter(BaseModel):
    """One chapter (or subchapter) belonging to a `Project`, keyed by `id`.

    `order` is a zero-based sibling position, assigned by `projects.service.create_chapter` (one
    past the current highest `order` among siblings). `parent_chapter_id` is `None` for a
    top-level chapter, or another `Chapter.id` for a subchapter, per ADR-0014: subchapters are
    plain rows in this same collection (self-referential), not an embedded array on the parent,
    so each keeps its own independent version history (ADR-0004) and lock/manifest state
    (ADR-0011). Nesting is capped at two levels (chapter, subchapter) per `docs/project/epics.md`
    — a subchapter's own `parent_chapter_id` is never itself a subchapter, but that constraint is
    enforced by callers (TASK-E12-2), not this model. Sibling `order` is scoped to
    `(project_id, parent_chapter_id)`, not just `project_id` — see
    `projects.service.insert_chapter_at_order`/`infer_insertion_order`.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    parent_chapter_id: str | None = None
    title: str
    order: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
