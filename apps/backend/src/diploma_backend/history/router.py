"""HTTP endpoints for undo/redo over a chapter's edit op-log (ADR-0012, TASK-E16-2, TASK-E16-3).

Scoped by `chapter_id` alone (no `project_id` segment in the path), same convention as
`locks.router` — ownership is enforced by walking `chapter_id -> Chapter.project_id ->
Project.owner_id`, matching `locks.router._get_owned_chapter`'s exact 404-either-way semantics
(duplicated here rather than imported, to keep `history.router` from depending on `locks.router`
for something as small as one lookup helper; the check itself is intentionally identical).

Both endpoints mutate the chapter's current pending draft `ChapterVersion` in place — no new
version row, "accept" (`versions.service.accept_draft_version`) is unaffected. Batch-undo/redo
over `count` steps (ADR-0012's client-resolved-page-range note) is supported; resolving a page's
block-id range into a `count`/starting point is a separate frontend task (TASK-E16-4), not built
here.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from diploma_backend.auth.dependencies import get_current_user_id
from diploma_backend.db import get_database
from diploma_backend.history.service import (
    HistoryReplayError,
    UndoRedoResult,
    redo_operations,
    undo_operations,
)
from diploma_backend.projects.models import Chapter
from diploma_backend.projects.service import get_chapter, get_project
from diploma_backend.versions.models import ChapterVersion

router = APIRouter(tags=["history"])


async def _get_owned_chapter(db: AsyncIOMotorDatabase, chapter_id: str, owner_id: str) -> Chapter:
    """Fetch `chapter_id`, scoped to `owner_id` by walking up to its project. Raises
    `HTTPException(404)` if the chapter doesn't exist or its project belongs to a different
    owner — deliberately the same status/detail either way, matching
    `locks.router._get_owned_chapter`.
    """
    chapter = await get_chapter(db, chapter_id)
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Chapter '{chapter_id}' not found"
        )
    project = await get_project(db, chapter.project_id)
    if project is None or project.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Chapter '{chapter_id}' not found"
        )
    return chapter


class UndoRedoRequest(BaseModel):
    """Body for `POST /chapters/{chapter_id}/undo` and `.../redo`.

    `count` (default `1`) supports batch-undo/redo over a range of operations in one call, per
    ADR-0012's note that a page-level revert is resolved client-side into a block-id range and
    sent as a batch — this endpoint accepts the resulting step count, it does not resolve pages
    itself. Must be at least `1`.
    """

    count: int = Field(default=1, ge=1)


class UndoRedoResponse(BaseModel):
    """Response for both undo and redo: the chapter's updated pending draft `ChapterVersion`
    (content + manifest already reflect the requested steps), plus where the op-log cursor now
    sits (`applied_count` out of `total_operations`) so a caller can tell whether further
    undo/redo is still possible without an extra request."""

    version: ChapterVersion
    applied_count: int
    total_operations: int

    @classmethod
    def from_result(cls, result: UndoRedoResult) -> "UndoRedoResponse":
        return cls(
            version=result.version,
            applied_count=result.applied_count,
            total_operations=result.total_operations,
        )


def _replay_error_status(message: str) -> int:
    """Maps a `HistoryReplayError` message (see `history.service.undo_operations`/
    `redo_operations` docstrings for the exact substrings) to the matching 4xx status: every case
    this module raises is "the chapter/draft/operations exist, but the request can't be
    fulfilled right now" — 409, never 404 (unlike `locks.router._lock_error_status`, which does
    distinguish a 404 case; here the chapter's existence/ownership has already been checked by
    `_get_owned_chapter` before either service function is ever called).
    """
    return status.HTTP_409_CONFLICT


@router.post("/chapters/{chapter_id}/undo", response_model=UndoRedoResponse)
async def undo_endpoint(
    chapter_id: str,
    body: UndoRedoRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> UndoRedoResponse:
    """Revert the last `body.count` applied operation(s) for `chapter_id` (TASK-E16-2) against
    its current pending draft, in place.

    Raises `HTTPException(404)` if `chapter_id` doesn't exist or isn't owned by the caller.
    Raises `HTTPException(409)` if there's no pending draft, if `applied_count == 0` (nothing to
    undo), if `body.count` exceeds what's available, or if the operation being undone can't find
    its anchor block in the current draft (`_replay_error_status`).
    """
    await _get_owned_chapter(db, chapter_id, owner_id)
    try:
        result = await undo_operations(db, chapter_id, body.count)
    except HistoryReplayError as exc:
        message = str(exc)
        raise HTTPException(status_code=_replay_error_status(message), detail=message) from exc
    return UndoRedoResponse.from_result(result)


@router.post("/chapters/{chapter_id}/redo", response_model=UndoRedoResponse)
async def redo_endpoint(
    chapter_id: str,
    body: UndoRedoRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> UndoRedoResponse:
    """Re-apply the next `body.count` undone operation(s) for `chapter_id` (TASK-E16-2) against
    its current pending draft, in place.

    Raises `HTTPException(404)` if `chapter_id` doesn't exist or isn't owned by the caller.
    Raises `HTTPException(409)` if there's no pending draft, if `applied_count ==
    total_operations` (nothing to redo), if `body.count` exceeds what's available, or if the
    operation being redone can't find its recorded insertion point in the current draft
    (`_replay_error_status`).
    """
    await _get_owned_chapter(db, chapter_id, owner_id)
    try:
        result = await redo_operations(db, chapter_id, body.count)
    except HistoryReplayError as exc:
        message = str(exc)
        raise HTTPException(status_code=_replay_error_status(message), detail=message) from exc
    return UndoRedoResponse.from_result(result)
