"""Vertical-slice endpoints: create a project, add a chapter, generate a draft via chat, and
accept it.

Composes `projects.service` (project/chapter storage), `versions.service` (draft/accepted
version storage, ADR-0004), `llm_routing` (DeepSeek client + retry + prompt assembly, ADR-0003),
`humanizer.pipeline` (TASK-E07-1) and `plagiarism.precheck` (TASK-E07-2) without modifying any of
their internals.

Known simplification (MVP scope for this task): the generation endpoint calls `assemble_prompt`
with `chapter_summaries=[]` and `rag_excerpts=[]`, and `run_precheck` with `source_excerpts=[]`.
Persisted chapter-summary accumulation (TASK-E03-2's `summarize_chapter`, wired into a session)
and RAG excerpt retrieval (E04/Qdrant) both exist elsewhere in this codebase but are not yet
threaded into this endpoint — that integration is explicitly out of scope here and belongs to a
later task. Citation verification (ADR-0001, `citations.verification`) is likewise not yet wired
into this endpoint: it needs those same RAG source excerpts to verify against, so it is deferred
to the same follow-up. As of this task, the pipeline order actually wired here is
generate -> humanize -> plagiarism/AI-detection scan (per PRD §6), skipping the
not-yet-integrated citation-verification step.
"""

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

from diploma_backend.db import get_database
from diploma_backend.export.docx import apply_institution_config, markdown_to_docx
from diploma_backend.formatting.service import get_institution_config
from diploma_backend.humanizer.pipeline import HumanizationError, humanize_text
from diploma_backend.llm_routing import DeepSeekClient, LLMRequestError, generate_with_retry
from diploma_backend.llm_routing.summary import assemble_prompt
from diploma_backend.plagiarism.precheck import PlagiarismCheckResult, run_precheck
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
) -> Response:
    """Export `project_id`'s full accepted content as a single `.docx` file (TASK-E06 closing the
    loop: the export engine existed with no reachable endpoint until this task).

    Raises `HTTPException(404)` if `project_id` doesn't exist. Otherwise assembles one Markdown
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
    project = await get_project(db, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found"
        )

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
    Builds messages via `assemble_prompt` with `chapter_summaries=[]` and `rag_excerpts=[]` (see
    module docstring: persisted summaries and RAG retrieval are out of scope for this task), then
    calls the DeepSeek "heavy" tier (ADR-0003: chapter drafting) through `generate_with_retry`.
    Raises `HTTPException(502)` if every retry attempt fails (`LLMRequestError`).

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
    `plagiarism.precheck.run_precheck` with `source_excerpts=[]` (RAG excerpts aren't threaded
    into this endpoint yet either — same simplification as `assemble_prompt`'s empty lists above).
    That text is what gets persisted via `versions.service.create_draft_version` — the draft a
    user reviews is the humanized version, not the raw LLM output. Returns a
    `GenerateDraftResponse` bundling the persisted `ChapterVersion` and the precheck result.
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

    try:
        humanized_content = await humanize_text(client, content)
    except LLMRequestError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except HumanizationError:
        # Fail-open: a mangled citation placeholder shouldn't block the user from seeing their
        # draft at all, since humanization is cosmetic, not correctness-critical (see docstring).
        humanized_content = content

    precheck = run_precheck(humanized_content, source_excerpts=[])

    version = await create_draft_version(db, chapter_id, content=humanized_content)
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
      endpoint) -> `run_precheck` (with `source_excerpts=[]`) -> `create_draft_version` pipeline
      as `generate_chapter_draft_endpoint`, then a single `event: done` whose `data:` is the JSON
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

    messages = assemble_prompt(
        system_prompt=_GENERATION_SYSTEM_PROMPT,
        chapter_summaries=[],
        rag_excerpts=[],
        user_message=instruction,
    )
    client = DeepSeekClient()

    async def event_stream() -> AsyncIterator[str]:
        chunks: list[str] = []
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

        precheck = run_precheck(humanized_content, source_excerpts=[])
        version = await create_draft_version(db, chapter_id, content=humanized_content)
        response_payload = GenerateDraftResponse(
            version=version, precheck=PlagiarismCheckResultResponse.from_result(precheck)
        )
        yield _sse_event("done", json.dumps(response_payload.model_dump(mode="json")))

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
