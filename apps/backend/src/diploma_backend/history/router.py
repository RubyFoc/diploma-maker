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

`GET /chapters/{chapter_id}/operations` is a small read-only addendum added for TASK-E16-4: the
frontend resolves a page's block-id range into an undo/redo `count` client-side, which requires
seeing every recorded operation's `block_id` in op-log order — this endpoint exposes exactly that
(and nothing more; content is never sent twice over the wire since the draft's own manifest
already carries it).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from diploma_backend.auth.dependencies import get_current_user_id
from diploma_backend.db import get_database
from diploma_backend.history.models import Operation
from diploma_backend.history.service import (
    HistoryReplayError,
    UndoRedoResult,
    get_history_cursor,
    list_operations_for_chapter,
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


class OperationSummary(BaseModel):
    """Minimal, non-content projection of one `history.models.Operation` for
    `GET /chapters/{chapter_id}/operations`. Deliberately omits `before_text`/`after_text`/
    `applied_by` — the frontend only needs `block_id` (to map blocks on a page to their op-log
    position) and `created_at` (for ordering/display), and there is no reason to send a chapter's
    generated content over the wire twice when the draft's own manifest already carries it."""

    id: str
    block_id: str
    created_at: datetime

    @classmethod
    def from_operation(cls, operation: Operation) -> "OperationSummary":
        return cls(id=operation.id, block_id=operation.block_id, created_at=operation.created_at)


class OperationsListResponse(BaseModel):
    """Response for `GET /chapters/{chapter_id}/operations`: every recorded operation for the
    chapter (both currently-applied and any still-undone redo tail), oldest-first, plus the same
    `applied_count`/`total_operations` the undo/redo endpoints report — enough for a caller to
    tell which of `operations` are currently applied (the first `applied_count` of them) without
    a second request."""

    operations: list[OperationSummary]
    applied_count: int
    total_operations: int


@router.get("/chapters/{chapter_id}/operations", response_model=OperationsListResponse)
async def list_operations_endpoint(
    chapter_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> OperationsListResponse:
    """List every recorded operation for `chapter_id`, oldest-first (TASK-E16-4's addendum): the
    frontend needs each operation's `block_id` in op-log order to resolve a page's block-id range
    into an undo/redo `count` client-side ("revert this page").

    A chapter that exists but has never had an anchor-insertion generation run against it has no
    recorded operations and no `HistoryCursor` yet — that is a valid, common state, distinct from
    "chapter doesn't exist", so it returns the zeroed shape (`operations=[]`, `applied_count=0`,
    `total_operations=0`) rather than a 404.

    Raises `HTTPException(404)` if `chapter_id` doesn't exist or isn't owned by the caller.
    """
    await _get_owned_chapter(db, chapter_id, owner_id)

    operations = await list_operations_for_chapter(db, chapter_id)
    cursor = await get_history_cursor(db, chapter_id)
    applied_count = cursor.applied_count if cursor is not None else 0

    return OperationsListResponse(
        operations=[OperationSummary.from_operation(operation) for operation in operations],
        applied_count=applied_count,
        total_operations=len(operations),
    )
