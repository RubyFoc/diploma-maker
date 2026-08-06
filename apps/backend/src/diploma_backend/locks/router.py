"""HTTP endpoints for draft ingestion (TASK-E13-3) and lock/unlock (TASK-E13-4, ADR-0011).

Both groups of endpoints are scoped by `chapter_id` alone (no `project_id` segment in the path,
unlike most of `projects.router`) — ownership is still enforced, by walking `chapter_id ->
Chapter.project_id -> Project.owner_id` via `_get_owned_chapter` below, the same "don't
distinguish reasons" 404 posture as `projects.router._get_owned_project`/`_get_owned_chapter`.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from diploma_backend.auth.dependencies import get_current_user_id
from diploma_backend.db import get_database
from diploma_backend.locks.models import CharRange, Lock
from diploma_backend.locks.service import (
    LockTargetError,
    list_locks_for_chapter,
    lock_block,
    unlock,
)
from diploma_backend.plagiarism.extract import PlagiarismFileParseError, extract_text
from diploma_backend.projects.models import Chapter
from diploma_backend.projects.service import get_chapter, get_project
from diploma_backend.versions.models import ChapterVersion
from diploma_backend.versions.service import create_draft_version

router = APIRouter(tags=["locks"])


async def _get_owned_chapter(
    db: AsyncIOMotorDatabase, chapter_id: str, owner_id: str
) -> Chapter:
    """Fetch `chapter_id`, scoped to `owner_id` by walking up to its project. Raises
    `HTTPException(404)` if the chapter doesn't exist or its project belongs to a different
    owner — deliberately the same status/detail either way (see
    `projects.router._get_owned_project`'s identical rationale).
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


@router.post(
    "/chapters/{chapter_id}/draft/upload",
    response_model=ChapterVersion,
    status_code=status.HTTP_201_CREATED,
)
async def upload_draft_endpoint(
    chapter_id: str,
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> ChapterVersion:
    """Ingest an already-written `.docx`/`.pdf` draft as a new pending draft version for
    `chapter_id` (TASK-E13-3), so a user can bring their own writing into the workspace and get
    it split into lockable blocks (ADR-0011) without having the AI generate it first.

    Reuses `plagiarism.extract.extract_text` for `.docx`/`.pdf` text extraction (same supported
    formats, same `PlagiarismFileParseError` -> `HTTPException(400)` translation as
    `plagiarism.router`'s `/plagiarism/check-file`). Unlike AI-generated drafts, this content is
    NOT run through `humanizer.pipeline`/`plagiarism.precheck` — it's the user's own already-
    written work, not model output that needs pattern-breaking or a plagiarism/AI-fingerprint
    scan. `versions.service.create_draft_version` builds the block manifest (TASK-E13-2)
    automatically from the extracted text.
    """
    await _get_owned_chapter(db, chapter_id, owner_id)

    content = await file.read()
    try:
        text = extract_text(file.filename or "", content)
    except PlagiarismFileParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return await create_draft_version(db, chapter_id, text)


class CreateLockRequest(BaseModel):
    """Body for `POST /chapters/{chapter_id}/locks`.

    `block_content_hash` is the block's `content_hash` as the caller last observed it (from the
    chapter's current accepted `ChapterVersion.manifest`) — `locks.service.lock_block` rejects the
    request if it no longer matches the block's actual current hash (ADR-0011 freshness check).
    """

    block_id: str
    block_content_hash: str
    char_range: CharRange | None = None


def _lock_error_status(message: str) -> int:
    """Maps a `LockTargetError` message (see `locks.service.lock_block`'s docstring for the
    exact substrings) to the matching 4xx status: 404 for "the target doesn't exist at all",
    409 for "it exists but is in the wrong state to lock right now"."""
    if "no accepted version" in message or "not found" in message:
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_409_CONFLICT


@router.post("/chapters/{chapter_id}/locks", response_model=Lock, status_code=status.HTTP_201_CREATED)
async def create_lock_endpoint(
    chapter_id: str,
    body: CreateLockRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> Lock:
    """Place a lock on a block (or sub-range of one) in `chapter_id`'s current accepted content
    (TASK-E13-4, ADR-0011). Raises `HTTPException(404)` if `chapter_id` doesn't exist/isn't
    owned by the caller, or if the chapter/block/manifest the lock would anchor to doesn't exist;
    `HTTPException(409)` if `body.block_content_hash` is stale (see `_lock_error_status`).
    """
    await _get_owned_chapter(db, chapter_id, owner_id)
    try:
        return await lock_block(
            db, chapter_id, body.block_id, body.block_content_hash, body.char_range
        )
    except LockTargetError as exc:
        message = str(exc)
        raise HTTPException(status_code=_lock_error_status(message), detail=message) from exc


@router.get("/chapters/{chapter_id}/locks", response_model=list[Lock])
async def list_locks_endpoint(
    chapter_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> list[Lock]:
    """List every lock currently placed on `chapter_id` (TASK-E13-4), for the UI (TASK-E13-5) to
    render which blocks are protected. Raises `HTTPException(404)` if `chapter_id` doesn't exist
    or isn't owned by the caller.
    """
    await _get_owned_chapter(db, chapter_id, owner_id)
    return await list_locks_for_chapter(db, chapter_id)


@router.delete(
    "/chapters/{chapter_id}/locks/{lock_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_lock_endpoint(
    chapter_id: str,
    lock_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> None:
    """Remove a lock (TASK-E13-4). Raises `HTTPException(404)` if `chapter_id` doesn't exist or
    isn't owned by the caller; otherwise deletes `lock_id` unconditionally and idempotently (no
    error if it's already gone, or never belonged to `chapter_id` — matching
    `projects.service.delete_project`'s no-error-on-missing convention). No freshness check here:
    unlike placing a lock, removing one carries no risk of anchoring to stale content.
    """
    await _get_owned_chapter(db, chapter_id, owner_id)
    await unlock(db, chapter_id, lock_id)
