"""Vertical-slice endpoints: create a project, add a chapter, generate a draft via chat, and
accept it.

Composes `projects.service` (project/chapter storage), `versions.service` (draft/accepted
version storage, ADR-0004), `llm_routing` (DeepSeek client + retry + prompt assembly, ADR-0003),
`humanizer.pipeline` (TASK-E07-1) and `plagiarism.precheck` (TASK-E07-2) without modifying any of
their internals.

RAG grounding (`_fetch_rag_excerpts`): before generating, both endpoints search external academic
literature (Semantic Scholar/CORE via `sources.search.search_sources`, TASK-E04-2) for the chat
instruction and feed up to `_RAG_EXCERPT_LIMIT` abstracts into `assemble_prompt`'s `rag_excerpts`
and `run_precheck`'s `source_excerpts` — real, live source grounding, not `[]` placeholders. This
is a live substitute for a Qdrant-ingested source store (TASK-E04-1): nothing in this codebase
yet ingests any project's own uploaded literature into Qdrant scoped to a project/chapter, so
querying it here would always return nothing; live external search needs no prior ingestion step
and gives real grounding today. `_fetch_rag_excerpts` fails open (`SourceSearchError` or zero
results → `[]`) since source grounding is a quality enhancement, not a hard requirement.

Known remaining simplification: `chapter_summaries=[]` is still passed to `assemble_prompt` —
persisted chapter-summary accumulation (TASK-E03-2's `summarize_chapter`, wired into a session)
is not yet threaded into this endpoint. Full citation verification (ADR-0001,
`citations.verification`) is ALSO still not wired in: that needs a claim-extraction step (finding
which sentences in the generated text assert something citable) which doesn't exist anywhere in
this codebase yet — a materially larger follow-up than RAG grounding, since grounding only
needed a search call, while verification needs to segment generated prose into individual claims
first. The system prompt instructs the model to cite the provided sources by title/year when it
draws on them, but nothing verifies those in-text citations are accurate or reformats them per
ADR-0001's retry/reject contract — that remains future work. As of this task, the pipeline order
wired here is generate (RAG-grounded) -> humanize -> plagiarism/AI-detection scan (per PRD §6),
skipping the not-yet-integrated citation-verification step.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from diploma_backend.auth.dependencies import get_current_user_id
from diploma_backend.db import get_database
from diploma_backend.export.docx import apply_institution_config, markdown_to_docx
from diploma_backend.formatting.service import get_institution_config
from diploma_backend.humanizer.pipeline import HumanizationError, humanize_text
from diploma_backend.llm_routing import (
    DeepSeekClient,
    LLMRequestError,
    generate_project_title,
    generate_with_retry,
)
from diploma_backend.llm_routing.summary import assemble_prompt
from diploma_backend.plagiarism.precheck import PlagiarismCheckResult, run_precheck
from diploma_backend.projects.models import Chapter, Project
from diploma_backend.projects.service import (
    create_chapter,
    create_project,
    delete_project,
    get_chapter,
    get_project,
    infer_insertion_order,
    insert_chapter_at_order,
    list_chapters_for_project,
    list_projects_for_user,
    list_subchapters,
    update_project_title,
)
from diploma_backend.sources.client import delete_project_vectors
from diploma_backend.sources.search import SourceSearchError, search_sources
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

# Matches the frontend's `chapterContentEmpty` string (apps/frontend/src/strings/index.ts)
# verbatim, so a user sees the same wording in the exported document as in the editor UI for a
# chapter with no accepted content yet. Wrapped in `*...*` so `markdown_to_docx` renders it
# italicized, visually distinguishing it from real chapter body text.
_EXPORT_EMPTY_CHAPTER_NOTE = "*No accepted content yet.*"

# Strips only genuinely filesystem/header-unsafe characters (path separators, control chars,
# quotes) rather than allowlisting ASCII only — this platform's target audience (ADR-0001's GOST
# handling, sources.geo_filter's RU/BY focus) overwhelmingly types Cyrillic project titles, and an
# ASCII-only allowlist previously turned every such title into a string of underscores.
_UNSAFE_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# ASCII-only fallback for the plain `filename=` Content-Disposition parameter, which older
# clients may not correctly interpret as UTF-8; kept alongside the RFC 5987 `filename*=` parameter
# (see `_content_disposition_header`) so both older and modern clients get a sensible name.
_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")
_FALLBACK_EXPORT_FILENAME = "thesis"

_GENERATION_SYSTEM_PROMPT = (
    "You are an academic writing assistant helping a student draft a chapter of their thesis. "
    "Write clear, well-structured, formal academic prose that directly follows the user's "
    "instruction. Do not include meta-commentary about being an AI. If reference sources are "
    "provided below, ground relevant claims in them and cite each one in-text as "
    "(Author, Year) — using the source's own title/year if no author name is given — when you "
    "draw on it directly. Never invent a citation for a source that was not provided; if none of "
    "the provided sources are relevant to a claim, state it plainly without a citation rather "
    "than fabricating one."
)

# Caps how many external search results become RAG excerpts per generation call — enough to
# ground the model without bloating the prompt (and DeepSeek's cache-hit economics, ADR-0003,
# favor a small, stable-ish context over a large one).
_RAG_EXCERPT_LIMIT = 3


async def _fetch_rag_excerpts(instruction: str) -> list[str]:
    """Best-effort live RAG grounding for a generation call.

    Searches external academic literature (Semantic Scholar/CORE, `sources.search`, TASK-E04-2)
    for `instruction` and turns up to `_RAG_EXCERPT_LIMIT` results with an abstract into excerpt
    strings (`"<title> (<year>): <abstract>"`) suitable for `assemble_prompt`'s `rag_excerpts` and
    `run_precheck`'s `source_excerpts`. Results with no abstract are skipped (nothing useful to
    ground on). Fails open: if every search provider is down (`SourceSearchError`) or nothing
    relevant is found, returns `[]` rather than blocking generation — source grounding is a
    quality enhancement for this MVP, not a hard requirement (see module docstring for why this
    is a live-search substitute for Qdrant-ingested sources, not a replacement for one).
    """
    try:
        results = await search_sources(instruction, limit=_RAG_EXCERPT_LIMIT)
    except SourceSearchError:
        return []

    excerpts = []
    for result in results:
        if not result.abstract:
            continue
        excerpts.append(f"{result.title} ({result.year}): {result.abstract}")
    return excerpts


def _maybe_start_title_generation(
    client: DeepSeekClient, project: Project | None, instruction: str
) -> "asyncio.Task[str] | None":
    """Kick off best-effort project-title auto-generation (user request, Phase 5.9) if `project`
    still has the generic default title, returning `None` otherwise.

    Only triggers once: once a project's title is anything other than `_DEFAULT_PROJECT_TITLE`
    (i.e. after this has already renamed it once), this check naturally skips every later call —
    no separate "has been titled" flag is needed.

    Started as an `asyncio.create_task` here (rather than awaited inline) so it runs concurrently
    with the endpoint's main heavy-tier draft generation instead of adding to the user's perceived
    latency; the caller must await the returned task via `_finish_title_generation` once the main
    generation work is done. Returns `None` immediately (no task created) if `project` is `None`
    or already has a non-default title.
    """
    if project is None or project.title != _DEFAULT_PROJECT_TITLE:
        return None
    return asyncio.create_task(generate_project_title(client, instruction))


async def _finish_title_generation(
    db: AsyncIOMotorDatabase, project_id: str, title_task: "asyncio.Task[str] | None"
) -> None:
    """Await `title_task` (from `_maybe_start_title_generation`) and persist its result.

    Fails open: title auto-generation is a cosmetic side effect of generation, not
    correctness-critical, so an `LLMRequestError` here is caught and swallowed, leaving the
    project's title at its current (default) value — it must never fail or delay the caller's
    main chapter-generation response. Does nothing if `title_task` is `None`.
    """
    if title_task is None:
        return
    try:
        title = await title_task
    except LLMRequestError:
        return
    await update_project_title(db, project_id, title)


class CreateProjectRequest(BaseModel):
    """Body for `POST /projects`. `title` defaults to `_DEFAULT_PROJECT_TITLE` when omitted or
    empty."""

    title: str | None = None


class CreateChapterRequest(BaseModel):
    """Body for `POST /projects/{project_id}/chapters`."""

    title: str


class InsertChapterRequest(BaseModel):
    """Body for `POST /projects/{project_id}/chapters/insert`."""

    title: str


class CreateSubchapterRequest(BaseModel):
    """Body for `POST /projects/{project_id}/chapters/{chapter_id}/subchapters`."""

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
    parent_chapter_id: str | None
    title: str
    order: int
    created_at: datetime
    accepted_content: str | None
    pending_draft: ChapterVersion | None


class ProjectSummary(BaseModel):
    """A lightweight, per-project listing entry: just `id`/`title`/`created_at`, no chapters.

    Backs `GET /projects` (TASK-E11-2). Deliberately lighter than `ProjectDetail`: building a
    full `ProjectDetail` per project fetches every chapter plus its accepted/draft versions
    (`_build_project_detail` -> `_build_chapter_detail`), an N+1 cost that's wasted work for a
    listing view where only the project-level fields are shown.
    """

    id: str
    title: str
    created_at: datetime


class ProjectDetail(BaseModel):
    """A project plus all of its chapters, each with accepted content / pending draft filled in.
    Response-only: not persisted anywhere as its own document.
    """

    id: str
    title: str
    created_at: datetime
    chapters: list[ChapterDetail]


class PlagiarismCheckResultResponse(BaseModel):
    """Pydantic mirror of `plagiarism.precheck.PlagiarismCheckResult` for use as a response
    field: FastAPI response models must be Pydantic models, and the frozen dataclass returned by
    `run_precheck` doesn't interoperate with that automatically. Field names/meaning match the
    dataclass exactly; see that module for what each score means and how `flagged` is derived.
    """

    plagiarism_score: float
    ai_fingerprint_score: float
    flagged: bool
    reasons: list[str]

    @classmethod
    def from_result(cls, result: PlagiarismCheckResult) -> "PlagiarismCheckResultResponse":
        return cls(
            plagiarism_score=result.plagiarism_score,
            ai_fingerprint_score=result.ai_fingerprint_score,
            flagged=result.flagged,
            reasons=result.reasons,
        )


class GenerateDraftResponse(BaseModel):
    """Response body for `POST /projects/{project_id}/chapters/{chapter_id}/generate`.

    Response-only: not persisted anywhere as its own document. `version` is the persisted draft
    `ChapterVersion` (its `content` is the humanized text, not the raw generation output — see
    `generate_chapter_draft_endpoint`). `precheck` is the anti-plagiarism/AI-detection scan
    result run against that same humanized text, so a caller/frontend can surface a "this draft
    was flagged, review carefully" signal alongside the draft.
    """

    version: ChapterVersion
    precheck: PlagiarismCheckResultResponse


async def _build_chapter_detail(db: AsyncIOMotorDatabase, chapter: Chapter) -> ChapterDetail:
    accepted = await get_current_accepted_version(db, chapter.id)
    draft = await get_latest_draft_version(db, chapter.id)
    return ChapterDetail(
        id=chapter.id,
        project_id=chapter.project_id,
        parent_chapter_id=chapter.parent_chapter_id,
        title=chapter.title,
        order=chapter.order,
        created_at=chapter.created_at,
        accepted_content=accepted.content if accepted is not None else None,
        pending_draft=draft,
    )


async def _get_owned_project(
    db: AsyncIOMotorDatabase, project_id: str, owner_id: str
) -> Project:
    """Fetch `project_id`, scoped to `owner_id` (TASK-E11-1).

    Raises `HTTPException(404)` both when `project_id` doesn't exist at all AND when it exists
    but belongs to a different owner — deliberately the same status/detail either way, so a
    caller can't distinguish "no such project" from "not yours" and enumerate other users'
    project ids.
    """
    project = await get_project(db, project_id)
    if project is None or project.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found"
        )
    return project


async def _build_project_detail(db: AsyncIOMotorDatabase, project: Project) -> ProjectDetail:
    chapters = await list_chapters_for_project(db, project.id)
    top_level_chapters = [chapter for chapter in chapters if chapter.parent_chapter_id is None]
    chapter_details = [await _build_chapter_detail(db, chapter) for chapter in top_level_chapters]
    return ProjectDetail(
        id=project.id,
        title=project.title,
        created_at=project.created_at,
        chapters=chapter_details,
    )


async def _get_owned_chapter(
    db: AsyncIOMotorDatabase, project_id: str, chapter_id: str, owner_id: str
) -> Chapter:
    """Fetch `chapter_id`, scoped to `project_id` and, transitively via `_get_owned_project`, to
    `owner_id` (TASK-E11-1). Raises `HTTPException(404)` if the chapter doesn't exist, belongs to
    a different project, or its project belongs to a different owner — the same "don't
    distinguish reasons" rationale as `_get_owned_project`.
    """
    await _get_owned_project(db, project_id, owner_id)
    chapter = await get_chapter(db, chapter_id)
    if chapter is None or chapter.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Chapter '{chapter_id}' not found"
        )
    return chapter


@router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
async def create_project_endpoint(
    body: CreateProjectRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> ProjectDetail:
    """Create a new project owned by the authenticated caller (TASK-E11-1), defaulting `title`
    to `_DEFAULT_PROJECT_TITLE` when omitted/empty.

    Returns a `ProjectDetail` with an empty `chapters` list (a brand-new project has none yet).
    Raises `HTTPException(401)` (via `get_current_user_id`) if no valid bearer token is given.
    """
    title = body.title if body.title else _DEFAULT_PROJECT_TITLE
    project = await create_project(db, title, owner_id)
    return await _build_project_detail(db, project)


@router.get("", response_model=list[ProjectSummary])
async def list_projects_endpoint(
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> list[ProjectSummary]:
    """List every project owned by the authenticated caller (TASK-E11-2).

    Raises `HTTPException(401)` (via `get_current_user_id`) if no valid bearer token is given.
    Returns `[]` if the caller has no projects. Each entry is a lightweight `ProjectSummary`
    (no chapters) rather than a full `ProjectDetail`, to avoid an N+1 chapter/version fetch per
    project in what's meant to be a cheap listing view.
    """
    projects = await list_projects_for_user(db, owner_id)
    return [
        ProjectSummary(id=project.id, title=project.title, created_at=project.created_at)
        for project in projects
    ]


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project_endpoint(
    project_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> ProjectDetail:
    """Fetch a project and all of its chapters (with accepted content / pending draft filled
    in), scoped to the authenticated caller (TASK-E11-1). Raises `HTTPException(404)` if
    `project_id` doesn't exist OR belongs to a different owner (see `_get_owned_project`).
    """
    project = await _get_owned_project(db, project_id, owner_id)
    return await _build_project_detail(db, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_endpoint(
    project_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> Response:
    """Delete a project and everything that hangs off it (TASK-E11-3).

    Scoped to the authenticated caller (TASK-E11-1): raises `HTTPException(404)` if `project_id`
    doesn't exist or belongs to a different owner (see `_get_owned_project`), the same
    ownership/404 check every other single-project endpoint here uses.

    Cascades via `projects.service.delete_project` across Mongo's `projects`/`chapters`/
    `chapter_versions` collections, then calls `sources.client.delete_project_vectors` — currently
    a documented no-op (see that function's docstring: nothing ingests project-scoped content into
    Qdrant yet, ADR-0002) kept wired in so the cascade already reaches it once that changes.
    Uploaded-file cleanup is deliberately not attempted: there is no project-scoped uploaded-file
    storage anywhere in this codebase today (`formatting.upload`'s `UPLOADS_DIR` is keyed by
    institution, not project), so there is nothing on disk to delete for a project.

    Returns `204 No Content` on success, with no response body.
    """
    await _get_owned_project(db, project_id, owner_id)
    await delete_project(db, project_id)
    delete_project_vectors(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _sanitize_filename(title: str) -> str:
    """Turn `title` into a filesystem-safe filename stem (no extension), preserving non-ASCII
    letters (e.g. Cyrillic) rather than collapsing them to underscores.

    Replaces only genuinely unsafe characters (path separators, control characters, quotes) with
    `_`. Falls back to `_FALLBACK_EXPORT_FILENAME` if that leaves nothing usable (e.g. a title
    made up entirely of unsafe characters).
    """
    sanitized = _UNSAFE_FILENAME_CHARS_RE.sub("_", title).strip()
    return sanitized if sanitized else _FALLBACK_EXPORT_FILENAME


def _content_disposition_header(filename: str) -> str:
    """Build a `Content-Disposition` header value safe for both ASCII-only and Unicode-aware
    clients.

    `filename=` carries an ASCII-only fallback (non-ASCII characters stripped) for older clients
    that don't correctly interpret raw UTF-8 in that parameter; `filename*=UTF-8''<percent-
    encoded>` (RFC 5987/6266) carries the real, full Unicode filename for modern browsers, which
    prefer `filename*` over `filename` when both are present.
    """
    ascii_fallback = _NON_ASCII_RE.sub("_", filename).strip("_ ")
    if not any(char.isalnum() for char in ascii_fallback):
        ascii_fallback = _FALLBACK_EXPORT_FILENAME
    encoded = quote(filename, safe="")
    return f'attachment; filename="{ascii_fallback}.docx"; filename*=UTF-8\'\'{encoded}.docx'


async def _build_export_markdown(db: AsyncIOMotorDatabase, project: Project) -> str:
    """Assemble one Markdown document for `project`: one `# <title>` heading per chapter (in
    `order`), followed by its accepted content, or `_EXPORT_EMPTY_CHAPTER_NOTE` if it has none.
    """
    chapters = await list_chapters_for_project(db, project.id)
    sections = []
    for chapter in chapters:
        accepted = await get_current_accepted_version(db, chapter.id)
        body = accepted.content if accepted is not None else _EXPORT_EMPTY_CHAPTER_NOTE
        sections.append(f"# {chapter.title}\n\n{body}\n")
    return "\n".join(sections)


@router.get("/{project_id}/export")
async def export_project_endpoint(
    project_id: str,
    institution_id: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> Response:
    """Export `project_id`'s full accepted content as a single `.docx` file (TASK-E06 closing the
    loop: the export engine existed with no reachable endpoint until this task).

    Scoped to the authenticated caller (TASK-E11-1): raises `HTTPException(404)` if `project_id`
    doesn't exist or belongs to a different owner. Otherwise assembles one Markdown
    document from all of the project's chapters, in `order` (see `_build_export_markdown`): each
    chapter becomes a `# <title>` heading followed by its current accepted content, or
    `_EXPORT_EMPTY_CHAPTER_NOTE` (matching the frontend's `chapterContentEmpty` string) if it has
    no accepted version yet — a chapter with no content is called out explicitly, not silently
    omitted. That Markdown is converted to a `docx.Document` via `export.docx.markdown_to_docx`.

    If `institution_id` is given AND resolves to a stored `InstitutionConfig`
    (`formatting.service.get_institution_config`), `export.docx.apply_institution_config` is
    applied to the document before serializing, giving it that institution's page/font/heading
    styling. If `institution_id` is omitted, or given but doesn't resolve to any stored config,
    the export proceeds WITHOUT institution styling (plain `python-docx` defaults) rather than
    failing — a missing or stale `institution_id` shouldn't block a user from getting their
    document, only from getting it styled.

    Returns a `Response` with `media_type="application/vnd.openxmlformats-officedocument
    .wordprocessingml.document"` and a `Content-Disposition: attachment` header whose filename is
    `project.title` sanitized via `_sanitize_filename`.
    """
    project = await _get_owned_project(db, project_id, owner_id)

    markdown_text = await _build_export_markdown(db, project)
    document = markdown_to_docx(markdown_text)

    if institution_id is not None:
        config = await get_institution_config(db, institution_id)
        if config is not None:
            apply_institution_config(document, config)

    buffer = BytesIO()
    document.save(buffer)

    filename = _sanitize_filename(project.title)
    return Response(
        content=buffer.getvalue(),
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={"Content-Disposition": _content_disposition_header(filename)},
    )


@router.post(
    "/{project_id}/chapters", response_model=ChapterDetail, status_code=status.HTTP_201_CREATED
)
async def create_chapter_endpoint(
    project_id: str,
    body: CreateChapterRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> ChapterDetail:
    """Create a new chapter under `project_id`, scoped to the authenticated caller (TASK-E11-1).
    Raises `HTTPException(404)` if the project doesn't exist or belongs to a different owner.
    Returns a freshly created `ChapterDetail` (`accepted_content=None`, `pending_draft=None`
    since nothing has been generated yet).
    """
    await _get_owned_project(db, project_id, owner_id)
    chapter = await create_chapter(db, project_id, body.title)
    return await _build_chapter_detail(db, chapter)


@router.post(
    "/{project_id}/chapters/insert",
    response_model=ChapterDetail,
    status_code=status.HTTP_201_CREATED,
)
async def insert_chapter_endpoint(
    project_id: str,
    body: InsertChapterRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> ChapterDetail:
    """Insert a new chapter under `project_id` at a chapter-boundary-aware position, per
    TASK-E10-3 (see `projects.service.infer_insertion_order` /
    `projects.service.insert_chapter_at_order`). Scoped to the authenticated caller
    (TASK-E11-1): raises `HTTPException(404)` if the project doesn't exist or belongs to a
    different owner.

    Unlike `create_chapter_endpoint` (always appends at the end), this infers `order` from
    `body.title`'s leading number relative to the project's existing top-level chapters, shifting
    any chapters at or past that position forward so the new chapter lands between the chapters
    its number implies it belongs between (e.g. "Chapter 2" between existing Chapters 1 and 3).
    Only inserts among top-level chapters (`parent_chapter_id=None`); inserting among a chapter's
    subchapters is TASK-E12-2's endpoint, not this one.
    """
    await _get_owned_project(db, project_id, owner_id)
    existing = await list_chapters_for_project(db, project_id)
    siblings = [chapter for chapter in existing if chapter.parent_chapter_id is None]
    order = infer_insertion_order(siblings, body.title)
    chapter = await insert_chapter_at_order(db, project_id, body.title, order)
    return await _build_chapter_detail(db, chapter)


@router.post(
    "/{project_id}/chapters/{chapter_id}/subchapters",
    response_model=ChapterDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_subchapter_endpoint(
    project_id: str,
    chapter_id: str,
    body: CreateSubchapterRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> ChapterDetail:
    """Create a new subchapter under `chapter_id` (TASK-E12-2, ADR-0014). Scoped to the
    authenticated caller via `_get_owned_chapter`: raises `HTTPException(404)` if `project_id`/
    `chapter_id` don't exist, don't belong to each other, or belong to a different owner.

    Raises `HTTPException(422)` if `chapter_id` is itself a subchapter (`parent_chapter_id is not
    None`) — nesting is capped at two levels (chapter, subchapter) per ADR-0014, so a subchapter
    can never have subchapters of its own.

    `order` is assigned by `projects.service.create_chapter` as one past the highest `order`
    among `chapter_id`'s existing subchapters (append-only; there is no subchapter equivalent of
    `insert_chapter_endpoint`'s numbered-boundary insertion yet).
    """
    parent = await _get_owned_chapter(db, project_id, chapter_id, owner_id)
    if parent.parent_chapter_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot add a subchapter to a subchapter (nesting is capped at two levels)",
        )

    chapter = await create_chapter(db, project_id, body.title, parent_chapter_id=chapter_id)
    return await _build_chapter_detail(db, chapter)


@router.get(
    "/{project_id}/chapters/{chapter_id}/subchapters",
    response_model=list[ChapterDetail],
)
async def list_subchapters_endpoint(
    project_id: str,
    chapter_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> list[ChapterDetail]:
    """List `chapter_id`'s subchapters, in `order` (TASK-E12-2). Scoped to the authenticated
    caller via `_get_owned_chapter`: raises `HTTPException(404)` if `project_id`/`chapter_id`
    don't exist, don't belong to each other, or belong to a different owner.

    Returns `[]` (not a 404) if `chapter_id` has no subchapters, or if `chapter_id` is itself a
    subchapter — the latter is a valid, empty answer rather than an error, since "does X have
    subchapters" is a sensible question to ask of any chapter row regardless of its own nesting
    level.
    """
    await _get_owned_chapter(db, project_id, chapter_id, owner_id)
    subchapters = await list_subchapters(db, project_id, chapter_id)
    return [await _build_chapter_detail(db, chapter) for chapter in subchapters]


@router.post(
    "/{project_id}/toc/upload", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED
)
async def upload_toc_endpoint(
    project_id: str,
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> ProjectDetail:
    """Parse an uploaded `.docx` table of contents and create one chapter per entry, in order.

    Scoped to the authenticated caller (TASK-E11-1): raises `HTTPException(404)` if `project_id`
    doesn't exist or belongs to a different owner. Parses `file` via `toc.parser.parse_toc`;
    raises `HTTPException(422)` if it isn't a parseable TOC (fail-closed, matching
    `formatting.router`'s upload-parse-error convention). On success, calls
    `projects.service.create_chapter` once per parsed title, in order (so `order` assignment
    stays centralized in that function), and returns the updated `ProjectDetail`.

    Note: this only creates chapters from the parsed TOC; inserting a later-generated
    chapter between existing ones is handled separately by `insert_chapter_endpoint`.
    """
    project = await _get_owned_project(db, project_id, owner_id)

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
    response_model=GenerateDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_chapter_draft_endpoint(
    project_id: str,
    chapter_id: str,
    body: GenerateDraftRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> GenerateDraftResponse:
    """Generate a chapter draft from a chat instruction, humanize it, scan it, and store the
    humanized text as a new draft version.

    Raises `HTTPException(404)` if `chapter_id` doesn't exist or doesn't belong to `project_id`.
    Fetches live RAG excerpts via `_fetch_rag_excerpts` (external academic search, see module
    docstring) and builds messages via `assemble_prompt` with `chapter_summaries=[]` and those
    excerpts, then calls the DeepSeek "heavy" tier (ADR-0003: chapter drafting) through
    `generate_with_retry`. Raises `HTTPException(502)` if every retry attempt fails
    (`LLMRequestError`).

    The raw generated content is then passed through `humanizer.pipeline.humanize_text` (reusing
    the same `DeepSeekClient`, fast tier per ADR-0003) to break up repetitive LLM-sounding
    patterns. Citation verification (ADR-0001) is not yet wired into this endpoint (see module
    docstring), so no citation markers are formatted into the raw text today, and
    `humanize_text`'s `guard_citations` step should find nothing to guard in practice. It is
    still handled defensively: a `LLMRequestError` from the humanize call (the DeepSeek call
    itself failing after retries) is a genuine infra failure and surfaces as `HTTPException(502)`,
    same as a failed generation. A `HumanizationError` (the model dropped/mangled a citation
    placeholder) is deliberately fail-open here: humanization is a cosmetic polishing stage, not a
    correctness-critical one (unlike citation verification itself, which fails closed per
    ADR-0001), so this endpoint catches it and falls back to the pre-humanization content rather
    than blocking the user from seeing their draft at all.

    The (possibly humanized, possibly raw-fallback) text is then run through
    `plagiarism.precheck.run_precheck` with the SAME RAG excerpts fetched above as
    `source_excerpts`, so the plagiarism-overlap score is measured against real source text
    rather than always trivially zero. That text is what gets persisted via
    `versions.service.create_draft_version` — the draft a user reviews is the humanized version,
    not the raw LLM output. Returns a `GenerateDraftResponse` bundling the persisted
    `ChapterVersion` and the precheck result.
    """
    chapter = await get_chapter(db, chapter_id)
    if chapter is None or chapter.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Chapter '{chapter_id}' not found"
        )
    project = await get_project(db, project_id)

    rag_excerpts = await _fetch_rag_excerpts(body.instruction)
    messages = assemble_prompt(
        system_prompt=_GENERATION_SYSTEM_PROMPT,
        chapter_summaries=[],
        rag_excerpts=rag_excerpts,
        user_message=body.instruction,
    )

    client = DeepSeekClient()
    title_task = _maybe_start_title_generation(client, project, body.instruction)
    try:
        try:
            content = await generate_with_retry(client, "heavy", messages)
        except LLMRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc

        try:
            humanized_content = await humanize_text(client, content)
        except LLMRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc
        except HumanizationError:
            # Fail-open: a mangled citation placeholder shouldn't block the user from seeing
            # their draft at all, humanization being cosmetic, not correctness-critical (see
            # docstring).
            humanized_content = content

        precheck = run_precheck(humanized_content, source_excerpts=rag_excerpts)
        version = await create_draft_version(db, chapter_id, content=humanized_content)
    finally:
        # Always awaited, even on an early failure above, so a slower title-generation call
        # never becomes an unretrieved/dangling task (see `_finish_title_generation`'s
        # fail-open contract).
        await _finish_title_generation(db, project_id, title_task)

    return GenerateDraftResponse(
        version=version, precheck=PlagiarismCheckResultResponse.from_result(precheck)
    )


def _sse_event(event: str, data: str) -> str:
    """Format a single SSE event per the spec's multi-line `data:` convention.

    Splits `data` on `\\n` so a chunk containing a raw newline doesn't break SSE framing: each
    line of `data` becomes its own `data: ` line, all under one `event:` line, terminated by the
    required blank line. A single-line `data` produces exactly the `event: ...\\ndata: ...\\n\\n`
    shape called for by ADR-0009/TASK-E08-3's contract.
    """
    data_lines = "\n".join(f"data: {line}" for line in data.split("\n"))
    return f"event: {event}\n{data_lines}\n\n"


@router.get("/{project_id}/chapters/{chapter_id}/generate/stream")
async def generate_chapter_draft_stream_endpoint(
    project_id: str,
    chapter_id: str,
    instruction: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> StreamingResponse:
    """SSE variant of `generate_chapter_draft_endpoint` (ADR-0009, TASK-E08-3).

    `GET` with `instruction` as a query parameter rather than `POST` with a JSON body: browsers'
    native `EventSource` API (the intended client, per ADR-0009) can only issue GET requests with
    no custom body, so this deliberately differs from the existing POST-based `/generate`
    endpoint's contract while reproducing the same generate -> humanize -> precheck -> persist
    pipeline shape underneath.

    Raises `HTTPException(404)` before the stream starts if `chapter_id` doesn't exist or doesn't
    belong to `project_id` (same check as `generate_chapter_draft_endpoint`) — this happens before
    `StreamingResponse` is constructed, so FastAPI renders it as a normal 404 response, not a
    stream.

    Once the stream starts, the response body is `text/event-stream` framed as a sequence of SSE
    events (see `_sse_event`):
    - `event: token` once per chunk yielded by `DeepSeekClient.generate_stream`, `data:` being the
      chunk text verbatim (multi-line chunks are split across multiple `data:` lines per the SSE
      spec, all within the same event).
    - On successful completion of the stream: the accumulated raw text is run through the same
      `humanize_text` (fail-open on `HumanizationError`, same reasoning as the non-streaming
      endpoint) -> `run_precheck` (with the same live-searched RAG excerpts as `source_excerpts`,
      see module docstring) -> `create_draft_version` pipeline as `generate_chapter_draft_endpoint`,
      then a single `event: done` whose `data:` is the JSON
      (via `.model_dump(mode="json")`) of a `GenerateDraftResponse`-shaped payload
      (`{"version": ..., "precheck": ...}`) — same response shape as that endpoint's body.
    - On `LLMRequestError` from `generate_stream` (a non-2xx status before the stream starts, or a
      connection drop mid-stream): a single `event: error` whose `data:` is
      `{"detail": str(exc)}`, and the generator stops — per TASK-E08-3's scope, streaming has no
      retry, so a failure here is a real, visible failure to the user, not silently retried, and
      humanize/precheck/persist are not attempted on a failed/incomplete generation.
    """
    chapter = await get_chapter(db, chapter_id)
    if chapter is None or chapter.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Chapter '{chapter_id}' not found"
        )
    project = await get_project(db, project_id)

    rag_excerpts = await _fetch_rag_excerpts(instruction)
    messages = assemble_prompt(
        system_prompt=_GENERATION_SYSTEM_PROMPT,
        chapter_summaries=[],
        rag_excerpts=rag_excerpts,
        user_message=instruction,
    )
    client = DeepSeekClient()
    title_task = _maybe_start_title_generation(client, project, instruction)

    async def event_stream() -> AsyncIterator[str]:
        chunks: list[str] = []
        try:
            try:
                async for chunk in client.generate_stream("heavy", messages):
                    chunks.append(chunk)
                    yield _sse_event("token", chunk)
            except LLMRequestError as exc:
                yield _sse_event("error", json.dumps({"detail": str(exc)}))
                return

            content = "".join(chunks)
            try:
                humanized_content = await humanize_text(client, content)
            except LLMRequestError as exc:
                yield _sse_event("error", json.dumps({"detail": str(exc)}))
                return
            except HumanizationError:
                humanized_content = content

            precheck = run_precheck(humanized_content, source_excerpts=rag_excerpts)
            version = await create_draft_version(db, chapter_id, content=humanized_content)
            response_payload = GenerateDraftResponse(
                version=version, precheck=PlagiarismCheckResultResponse.from_result(precheck)
            )
            yield _sse_event("done", json.dumps(response_payload.model_dump(mode="json")))
        finally:
            # Same fail-open, always-awaited contract as the non-streaming endpoint (see
            # `_finish_title_generation`) — never leaves the title-generation task dangling,
            # whether the stream succeeded or errored out early.
            await _finish_title_generation(db, project_id, title_task)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
