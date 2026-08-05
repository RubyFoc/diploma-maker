"""Vertical-slice endpoints: create a project, add a chapter, generate a draft via chat, and
accept it.

Composes `projects.service` (project/chapter storage), `versions.service` (draft/accepted
version storage, ADR-0004) and `llm_routing` (DeepSeek client + retry + prompt assembly,
ADR-0003) without modifying any of their internals.

Known simplification (MVP scope for this task): the generation endpoint calls
`assemble_prompt` with `chapter_summaries=[]` and `rag_excerpts=[]`. Persisted chapter-summary
accumulation (TASK-E03-2's `summarize_chapter`, wired into a session) and RAG excerpt retrieval
(E04/Qdrant) both exist elsewhere in this codebase but are not yet threaded into this endpoint —
that integration is explicitly out of scope here and belongs to a later task.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from diploma_backend.db import get_database
from diploma_backend.llm_routing import DeepSeekClient, LLMRequestError, generate_with_retry
from diploma_backend.llm_routing.summary import assemble_prompt
from diploma_backend.projects.models import Chapter, Project
from diploma_backend.projects.service import (
    create_chapter,
    create_project,
    get_chapter,
    get_project,
    list_chapters_for_project,
)
from diploma_backend.toc.parser import TocParseError, parse_toc
from diploma_backend.versions.models import ChapterVersion
from diploma_backend.versions.service import (
    accept_draft_version,
    create_draft_version,
    get_current_accepted_version,
    get_latest_draft_version,
)

router = APIRouter(prefix="/projects", tags=["projects"])

# Separate, prefix-less router for the accept-draft endpoint: the contract requires
# `POST /versions/{version_id}/accept` (not nested under `/projects`), and there is no other
# `versions` router yet to attach it to. Both routers are included in `main.py`.
versions_router = APIRouter(prefix="/versions", tags=["projects"])

_DEFAULT_PROJECT_TITLE = "Untitled Thesis"

_GENERATION_SYSTEM_PROMPT = (
    "You are an academic writing assistant helping a student draft a chapter of their thesis. "
    "Write clear, well-structured, formal academic prose that directly follows the user's "
    "instruction. Do not include meta-commentary about being an AI."
)


class CreateProjectRequest(BaseModel):
    """Body for `POST /projects`. `title` defaults to `_DEFAULT_PROJECT_TITLE` when omitted or
    empty."""

    title: str | None = None


class CreateChapterRequest(BaseModel):
    """Body for `POST /projects/{project_id}/chapters`."""

    title: str


class GenerateDraftRequest(BaseModel):
    """Body for `POST /projects/{project_id}/chapters/{chapter_id}/generate`."""

    instruction: str


class ChapterDetail(BaseModel):
    """A chapter plus its current accepted content and pending draft, if any. Response-only:
    not persisted anywhere as its own document.
    """

    id: str
    project_id: str
    title: str
    order: int
    created_at: datetime
    accepted_content: str | None
    pending_draft: ChapterVersion | None


class ProjectDetail(BaseModel):
    """A project plus all of its chapters, each with accepted content / pending draft filled in.
    Response-only: not persisted anywhere as its own document.
    """

    id: str
    title: str
    created_at: datetime
    chapters: list[ChapterDetail]


async def _build_chapter_detail(db: AsyncIOMotorDatabase, chapter: Chapter) -> ChapterDetail:
    accepted = await get_current_accepted_version(db, chapter.id)
    draft = await get_latest_draft_version(db, chapter.id)
    return ChapterDetail(
        id=chapter.id,
        project_id=chapter.project_id,
        title=chapter.title,
        order=chapter.order,
        created_at=chapter.created_at,
        accepted_content=accepted.content if accepted is not None else None,
        pending_draft=draft,
    )


async def _build_project_detail(db: AsyncIOMotorDatabase, project: Project) -> ProjectDetail:
    chapters = await list_chapters_for_project(db, project.id)
    chapter_details = [await _build_chapter_detail(db, chapter) for chapter in chapters]
    return ProjectDetail(
        id=project.id,
        title=project.title,
        created_at=project.created_at,
        chapters=chapter_details,
    )


@router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
async def create_project_endpoint(
    body: CreateProjectRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ProjectDetail:
    """Create a new project, defaulting `title` to `_DEFAULT_PROJECT_TITLE` when omitted/empty.

    Returns a `ProjectDetail` with an empty `chapters` list (a brand-new project has none yet).
    """
    title = body.title if body.title else _DEFAULT_PROJECT_TITLE
    project = await create_project(db, title)
    return await _build_project_detail(db, project)


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project_endpoint(
    project_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ProjectDetail:
    """Fetch a project and all of its chapters (with accepted content / pending draft filled
    in). Raises `HTTPException(404)` if `project_id` doesn't exist.
    """
    project = await get_project(db, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found"
        )
    return await _build_project_detail(db, project)


@router.post(
    "/{project_id}/chapters", response_model=ChapterDetail, status_code=status.HTTP_201_CREATED
)
async def create_chapter_endpoint(
    project_id: str,
    body: CreateChapterRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ChapterDetail:
    """Create a new chapter under `project_id`. Raises `HTTPException(404)` if the project
    doesn't exist. Returns a freshly created `ChapterDetail` (`accepted_content=None`,
    `pending_draft=None` since nothing has been generated yet).
    """
    project = await get_project(db, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found"
        )
    chapter = await create_chapter(db, project_id, body.title)
    return await _build_chapter_detail(db, chapter)


@router.post(
    "/{project_id}/toc/upload", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED
)
async def upload_toc_endpoint(
    project_id: str,
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ProjectDetail:
    """Parse an uploaded `.docx` table of contents and create one chapter per entry, in order.

    Raises `HTTPException(404)` if `project_id` doesn't exist. Parses `file` via
    `toc.parser.parse_toc`; raises `HTTPException(422)` if it isn't a parseable TOC (fail-closed,
    matching `formatting.router`'s upload-parse-error convention). On success, calls
    `projects.service.create_chapter` once per parsed title, in order (so `order` assignment
    stays centralized in that function), and returns the updated `ProjectDetail`.

    Note: this only creates chapters from the parsed TOC; it does not yet insert a
    later-generated chapter between existing ones — that's TASK-E10-3, not implemented here.
    """
    project = await get_project(db, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found"
        )

    content = await file.read()
    try:
        titles = parse_toc(content)
    except TocParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    for title in titles:
        await create_chapter(db, project_id, title)
    return await _build_project_detail(db, project)


@router.post(
    "/{project_id}/chapters/{chapter_id}/generate",
    response_model=ChapterVersion,
    status_code=status.HTTP_201_CREATED,
)
async def generate_chapter_draft_endpoint(
    project_id: str,
    chapter_id: str,
    body: GenerateDraftRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ChapterVersion:
    """Generate a chapter draft from a chat instruction and store it as a new draft version.

    Raises `HTTPException(404)` if `chapter_id` doesn't exist or doesn't belong to `project_id`.
    Builds messages via `assemble_prompt` with `chapter_summaries=[]` and `rag_excerpts=[]` (see
    module docstring: persisted summaries and RAG retrieval are out of scope for this task), then
    calls the DeepSeek "heavy" tier (ADR-0003: chapter drafting) through `generate_with_retry`.
    Raises `HTTPException(502)` if every retry attempt fails (`LLMRequestError`). On success,
    persists and returns the new draft `ChapterVersion` (see `versions.service.create_draft_version`
    for version-numbering/parent-linking behavior).
    """
    chapter = await get_chapter(db, chapter_id)
    if chapter is None or chapter.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Chapter '{chapter_id}' not found"
        )

    messages = assemble_prompt(
        system_prompt=_GENERATION_SYSTEM_PROMPT,
        chapter_summaries=[],
        rag_excerpts=[],
        user_message=body.instruction,
    )

    client = DeepSeekClient()
    try:
        content = await generate_with_retry(client, "heavy", messages)
    except LLMRequestError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return await create_draft_version(db, chapter_id, content=content)


@versions_router.post("/{version_id}/accept", response_model=ChapterVersion)
async def accept_draft_version_endpoint(
    version_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ChapterVersion:
    """Accept a pending draft version, flipping it to `status="accepted"`.

    Raises `HTTPException(404)` if `version_id` doesn't exist, or `HTTPException(409)` if it
    exists but isn't currently a draft (see `versions.service.accept_draft_version`'s `ValueError`
    messages, which this distinguishes by substring).
    """
    try:
        return await accept_draft_version(db, version_id)
    except ValueError as exc:
        message = str(exc)
        if "no version" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from exc
