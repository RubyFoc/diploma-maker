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

Must-cite sources (`_fetch_required_source_excerpts`, TASK-E14-3): a project's declared
`RequiredSource`s (TASK-E14-1/E14-2, `sources.required`) each get their own targeted search
(author + title, not the general chat instruction) and are boosted into the prompt's
`rag_excerpts` in addition to (not competing with) the instruction-driven search's
`_RAG_EXCERPT_LIMIT` cap — a must-cite source should never lose its grounding slot to an
unrelated but more instruction-relevant result. A required source with no findable/abstract-
bearing result is reported back as `GenerateDraftResponse.unmet_required_sources` rather than
silently dropped or fabricated: per ADR-0001, one ungroundable citation must never block the rest
of generation, so this fails open for the document as a whole while still surfacing the gap to
the user. Like `_fetch_rag_excerpts`, this targets live external search, not a Qdrant payload
filter (ADR-0002) — the same live-substitute reasoning applies, since nothing in this codebase
ingests project-scoped literature into Qdrant yet (see the paragraph above).

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
from diploma_backend.locks.models import Block
from diploma_backend.locks.service import (
    AnchorResolution,
    AnchorResolutionError,
    find_valid_anchor,
    list_locks_for_chapter,
    reverify_anchor_resolution,
)
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
from diploma_backend.sources.required import list_required_sources_for_project
from diploma_backend.sources.search import SourceSearchError, search_sources
from diploma_backend.toc.parser import TocParseError, parse_toc
from diploma_backend.versions.models import ChapterVersion
from diploma_backend.versions.service import (
    accept_draft_version,
    create_draft_version,
    create_draft_version_at_anchor,
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

# TASK-E15-1: distinct system prompt for "insert at anchor" generation mode. Reuses everything
# `_GENERATION_SYSTEM_PROMPT` says about grounding/citation honesty, but replaces the "write the
# whole chapter" framing with "write only the new material to splice in" — the model must not
# repeat the surrounding context it's shown (it's read-only orientation, not something to
# reproduce) and must not attempt a full-chapter rewrite.
_ANCHOR_GENERATION_SYSTEM_PROMPT = (
    "You are an academic writing assistant helping a student insert new content into an existing "
    "thesis chapter, at a specific point the user has chosen. You will be shown the text "
    "immediately before and/or after the insertion point as read-only context, purely so your new "
    "material flows naturally with what surrounds it. Output ONLY the new text to insert — do not "
    "repeat, rephrase, or continue past the surrounding context, and do not rewrite or summarize "
    "the rest of the chapter. Write clear, well-structured, formal academic prose that directly "
    "follows the user's instruction. Do not include meta-commentary about being an AI. If "
    "reference sources are provided below, ground relevant claims in them and cite each one "
    "in-text as (Author, Year) — using the source's own title/year if no author name is given — "
    "when you draw on it directly. Never invent a citation for a source that was not provided; if "
    "none of the provided sources are relevant to a claim, state it plainly without a citation "
    "rather than fabricating one."
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


async def _fetch_required_source_excerpts(
    db: AsyncIOMotorDatabase, project_id: str
) -> tuple[list[str], list[str]]:
    """Boost `project_id`'s must-cite sources (TASK-E14-1/2/3) into the RAG excerpt set, each via
    its own targeted search rather than leaving it to compete with `_fetch_rag_excerpts`'s
    instruction-driven, `_RAG_EXCERPT_LIMIT`-capped results.

    For each `RequiredSource`, searches `f"{author} {title}"` (or just `author` if no `title`)
    and takes the first result with an abstract as that source's excerpt. Returns
    `(excerpts, unmet_labels)`: `unmet_labels` collects the `"{author} — {title}"` (or just
    `author`) label of every required source that couldn't be matched to an abstract-bearing
    result, or whose search failed outright (`SourceSearchError`) — surfaced to the caller as
    `GenerateDraftResponse.unmet_required_sources` (see module docstring for why this fails open
    per-source rather than fabricating a citation or blocking generation).
    """
    required_sources = await list_required_sources_for_project(db, project_id)
    excerpts: list[str] = []
    unmet: list[str] = []

    for required in required_sources:
        label = f"{required.author} — {required.title}" if required.title else required.author
        query = f"{required.author} {required.title}" if required.title else required.author
        try:
            results = await search_sources(query, limit=1)
        except SourceSearchError:
            unmet.append(label)
            continue

        matched = next((result for result in results if result.abstract), None)
        if matched is None:
            unmet.append(label)
            continue
        excerpts.append(f"{matched.title} ({matched.year}): {matched.abstract}")

    return excerpts, unmet


async def _humanize_and_precheck(
    client: DeepSeekClient, content: str, rag_excerpts: list[str]
) -> tuple[str, PlagiarismCheckResult]:
    """Shared humanize -> plagiarism/AI-detection precheck pipeline, used by both full-chapter and
    "insert at anchor" (TASK-E15-1) generation, so the two modes never duplicate this logic.

    Same contract as inlined in `generate_chapter_draft_endpoint` previously: `HumanizationError`
    fails open (falls back to the pre-humanization `content`, humanization being cosmetic, not
    correctness-critical); a genuine `LLMRequestError` from the humanize call surfaces as
    `HTTPException(502)`.
    """
    try:
        humanized_content = await humanize_text(client, content)
    except LLMRequestError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except HumanizationError:
        # Fail-open: a mangled citation placeholder shouldn't block the user from seeing
        # their draft at all, humanization being cosmetic, not correctness-critical (see
        # docstring).
        humanized_content = content

    precheck = run_precheck(humanized_content, source_excerpts=rag_excerpts)
    return humanized_content, precheck


def _anchor_context_excerpts(
    manifest: list[Block], anchor_block_id: str, locked_block_ids: frozenset[str] = frozenset()
) -> list[str]:
    """Build read-only "surrounding context" excerpts for "insert at anchor" generation
    (TASK-E15-1): the content of the block immediately before and immediately after the anchor
    block in `manifest`, if they exist, each labeled so the model can tell it's orientation, not
    something to reproduce.

    `locked_block_ids` (TASK-E15-2, ADR-0011) is the set of block ids currently covered by an
    active `Lock` (`locks.service.list_locks_for_chapter`) — when a neighbor block is one of
    these, its excerpt uses an explicit "protected, read-only, must not be modified" label
    instead of the generic before/after one, so the model is told in-prompt not to touch it. This
    is advisory context only: the actual enforcement that a generation never lands inside a
    locked block is `locks.service.find_valid_anchor`, run in code before this function is even
    called, never the model's own restraint.

    Raises `ValueError` (message containing "not found") if no block in `manifest` has
    `id == anchor_block_id`, matching `locks.models.insert_blocks_after`'s convention — callers
    translate that into `HTTPException(404)` before ever calling the LLM.
    """
    anchor_index = next(
        (index for index, block in enumerate(manifest) if block.id == anchor_block_id), None
    )
    if anchor_index is None:
        raise ValueError(f"block {anchor_block_id!r} not found in manifest")

    def _label(position: str, block: Block) -> str:
        if block.id in locked_block_ids:
            return (
                f"Protected, read-only text {position} the insertion point — this content is "
                f"locked and must NOT be modified, repeated, or overwritten: {block.content}"
            )
        return f"Text immediately {position} the insertion point: {block.content}"

    excerpts = []
    if anchor_index > 0:
        excerpts.append(_label("before", manifest[anchor_index - 1]))
    if anchor_index < len(manifest) - 1:
        excerpts.append(_label("after", manifest[anchor_index + 1]))
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
    empty.

    `institution_id` (TASK-INT-17) optionally names a stored `InstitutionConfig` to associate
    with the new project up front, so a later export applies that institution's styling from the
    project itself rather than needing it re-supplied as an export-time query parameter (see
    `export_project_endpoint`). Not validated against `formatting.service.get_institution_config`
    here — same fail-open posture as export itself.
    """

    title: str | None = None
    institution_id: str | None = None


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
    """Body for `POST /projects/{project_id}/chapters/{chapter_id}/generate`.

    `target_block_id` (TASK-E15-1, ADR-0011) is optional: when omitted (the default), generation
    behaves exactly as before — a full-chapter draft replacing the whole content. When set to a
    `Block.id` from the chapter's current accepted manifest, generation switches to "insert at
    anchor" mode: only new content to splice in immediately after that block is generated and
    persisted, leaving every other block's `id`/`content_hash`/`content` untouched (see
    `locks.models.insert_blocks_after`).
    """

    instruction: str
    target_block_id: str | None = None


class ChapterDetail(BaseModel):
    """A chapter plus its current accepted content and pending draft, if any. Response-only:
    not persisted anywhere as its own document.

    `accepted_manifest` is the accepted version's block manifest (ADR-0011, TASK-E13-2) —
    surfaced alongside `accepted_content` so the frontend's lock-selection UI (TASK-E13-5) has
    the block ids/hashes it needs to place a lock (`POST /chapters/{chapter_id}/locks`) without a
    second round trip. `None` both when there's no accepted version yet and when the accepted
    version predates TASK-E13-2 (no manifest ever built for it) — either way, nothing to lock.
    """

    id: str
    project_id: str
    parent_chapter_id: str | None
    title: str
    order: int
    created_at: datetime
    accepted_content: str | None
    accepted_manifest: list[Block] | None
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

    `institution_id` (TASK-INT-17) surfaces the project's stored institution association so the
    frontend can read back which institution (if any) a project is already configured with,
    e.g. to preselect it in an export/settings UI (TASK-INT-18) rather than asking the user to
    re-pick it every time.
    """

    id: str
    title: str
    institution_id: str | None
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

    `unmet_required_sources` (TASK-E14-3) lists the label (`"{author} — {title}"`, or just
    `author`) of every project-declared must-cite source (`sources.required.RequiredSource`) that
    `_fetch_required_source_excerpts` could not ground this generation call in — empty when the
    project has no required sources, or all of them were found. Never blocks generation itself;
    purely informational, per ADR-0001's "one bad citation must never block the document" posture.

    `used_block_id`/`rerouted_from_block_id` (TASK-E15-2, ADR-0011) describe "insert at anchor"
    mode's deterministic lock guard (`locks.service.find_valid_anchor`). Both are `None` in
    full-chapter mode (`target_block_id` omitted). In anchor mode, `used_block_id` is the anchor
    the new content was actually spliced after; `rerouted_from_block_id` is `None` unless the
    originally requested `target_block_id` was locked and this generation was rerouted to a
    different, nearby unlocked anchor instead — in which case it holds that originally requested
    id, so a caller can surface "we moved your insertion point because it was locked".
    """

    version: ChapterVersion
    precheck: PlagiarismCheckResultResponse
    unmet_required_sources: list[str] = []
    used_block_id: str | None = None
    rerouted_from_block_id: str | None = None


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
        accepted_manifest=accepted.manifest if accepted is not None else None,
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
        institution_id=project.institution_id,
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
    project = await create_project(db, title, owner_id, institution_id=body.institution_id)
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

    Styling source of truth (TASK-INT-17): the project's OWN stored `institution_id`
    (`Project.institution_id`, set at creation time via `CreateProjectRequest.institution_id`) is
    used when present, in preference to the `institution_id` query parameter — a project should
    export with the institution it was actually configured with, not whatever a caller happens to
    pass at export time. The query parameter is kept ONLY as a fallback for projects created
    before this field existed (`project.institution_id is None`), so an export for one of those
    pre-existing projects can still be styled by passing it explicitly; once every project has
    gone through `POST /projects` with this field, the parameter becomes dead weight and can be
    removed. Whichever id is used, if it resolves to a stored `InstitutionConfig`
    (`formatting.service.get_institution_config`), `export.docx.apply_institution_config` is
    applied to the document before serializing, giving it that institution's page/font/heading
    styling. If neither source yields an id, or the id doesn't resolve to any stored config, the
    export proceeds WITHOUT institution styling (plain `python-docx` defaults) rather than
    failing — a missing or stale `institution_id` shouldn't block a user from getting their
    document, only from getting it styled.

    Returns a `Response` with `media_type="application/vnd.openxmlformats-officedocument
    .wordprocessingml.document"` and a `Content-Disposition: attachment` header whose filename is
    `project.title` sanitized via `_sanitize_filename`.
    """
    project = await _get_owned_project(db, project_id, owner_id)

    markdown_text = await _build_export_markdown(db, project)
    document = markdown_to_docx(markdown_text)

    effective_institution_id = project.institution_id or institution_id
    if effective_institution_id is not None:
        config = await get_institution_config(db, effective_institution_id)
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

    If `body.target_block_id` is set (TASK-E15-1, ADR-0011), generation switches to "insert at
    anchor" mode instead. Before any LLM call, `locks.service.find_valid_anchor` (TASK-E15-2)
    deterministically resolves the requested anchor against the chapter's current accepted
    manifest and its active locks: if the requested block doesn't exist at all (no accepted
    version, no manifest, or the block id isn't found), this raises `HTTPException(404)`,
    mirroring this endpoint's chapter-not-found 404 check's placement so a bad anchor never
    wastes a generation call. If the requested block IS locked but a nearby unlocked block
    exists, generation proceeds against that alternative anchor instead — never trusting the
    model to respect a lock on its own — and the response's `rerouted_from_block_id` surfaces the
    reroute. If the requested block is locked and the ENTIRE chapter is locked (no valid anchor
    exists at all), this raises `HTTPException(409)`: the chapter/anchor exist, the request just
    cannot be fulfilled right now.

    The model is switched to `_ANCHOR_GENERATION_SYSTEM_PROMPT` and given the (possibly
    rerouted) anchor's immediate neighboring block content as read-only context
    (`_anchor_context_excerpts`) — any neighbor that is itself locked is explicitly labeled
    protected/read-only, purely as advisory orientation for the model, never the actual
    enforcement — told to output only the new material to splice in, not a full-chapter rewrite.
    The same humanize -> precheck pipeline runs either way (`_humanize_and_precheck`); only
    persistence differs, via `versions.service.create_draft_version_at_anchor` instead of
    `create_draft_version`. Immediately before that persistence call,
    `locks.service.reverify_anchor_resolution` re-runs the same deterministic check against the
    resolution captured before the LLM call — closing the TOCTOU gap where a lock gets placed, or
    the anchor block's content changes, during the LLM round-trip — and raises
    `HTTPException(409)` instead of persisting if the previously-resolved anchor is no longer
    valid.
    """
    chapter = await get_chapter(db, chapter_id)
    if chapter is None or chapter.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Chapter '{chapter_id}' not found"
        )
    project = await get_project(db, project_id)

    # TASK-E15-2: "insert at anchor" mode's deterministic lock guard, run before any LLM call so
    # a request that will definitely be rejected/rerouted doesn't burn context on the wrong
    # anchor. `anchor_resolution` (used again just before persistence, below) is the single
    # source of truth for which block the prompt/persistence are actually built around.
    anchor_context_excerpts: list[str] = []
    anchor_resolution: AnchorResolution | None = None
    if body.target_block_id is not None:
        try:
            anchor_resolution = await find_valid_anchor(db, chapter_id, body.target_block_id)
        except AnchorResolutionError as exc:
            message = str(exc)
            if "no unlocked block available" in message:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from exc
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc

        accepted = await get_current_accepted_version(db, chapter_id)
        locks = await list_locks_for_chapter(db, chapter_id)
        locked_block_ids = frozenset(lock.block_id for lock in locks)
        anchor_context_excerpts = _anchor_context_excerpts(
            accepted.manifest, anchor_resolution.used_block_id, locked_block_ids
        )

    required_excerpts, unmet_required_sources = await _fetch_required_source_excerpts(
        db, project_id
    )
    rag_excerpts = (
        required_excerpts + anchor_context_excerpts + await _fetch_rag_excerpts(body.instruction)
    )
    messages = assemble_prompt(
        system_prompt=(
            _ANCHOR_GENERATION_SYSTEM_PROMPT
            if body.target_block_id is not None
            else _GENERATION_SYSTEM_PROMPT
        ),
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

        humanized_content, precheck = await _humanize_and_precheck(client, content, rag_excerpts)

        if anchor_resolution is not None:
            # TASK-E15-2: re-verify right before persistence, closing the TOCTOU gap between
            # resolving the anchor above and persisting into it now — a lock could have been
            # placed, or the anchor block's content changed, during the LLM round-trip.
            try:
                await reverify_anchor_resolution(db, chapter_id, anchor_resolution)
            except AnchorResolutionError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

            try:
                version = await create_draft_version_at_anchor(
                    db,
                    chapter_id,
                    anchor_resolution.used_block_id,
                    generated_content=humanized_content,
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        else:
            version = await create_draft_version(db, chapter_id, content=humanized_content)
    finally:
        # Always awaited, even on an early failure above, so a slower title-generation call
        # never becomes an unretrieved/dangling task (see `_finish_title_generation`'s
        # fail-open contract).
        await _finish_title_generation(db, project_id, title_task)

    return GenerateDraftResponse(
        version=version,
        precheck=PlagiarismCheckResultResponse.from_result(precheck),
        unmet_required_sources=unmet_required_sources,
        used_block_id=anchor_resolution.used_block_id if anchor_resolution is not None else None,
        rerouted_from_block_id=(
            anchor_resolution.rerouted_from_block_id if anchor_resolution is not None else None
        ),
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

    Full-chapter generation only — does not support TASK-E15-1's "insert at anchor" mode
    (`target_block_id`). Left out deliberately: threading the anchor lookup/404 checks and the
    alternate system prompt/context through this generator-based streaming path is meaningfully
    more moving parts than the non-streaming endpoint, and E15's frontend consumer (TASK-E15-3,
    not part of this task) does not require it yet.

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

    required_excerpts, unmet_required_sources = await _fetch_required_source_excerpts(
        db, project_id
    )
    rag_excerpts = required_excerpts + await _fetch_rag_excerpts(instruction)
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
                version=version,
                precheck=PlagiarismCheckResultResponse.from_result(precheck),
                unmet_required_sources=unmet_required_sources,
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
