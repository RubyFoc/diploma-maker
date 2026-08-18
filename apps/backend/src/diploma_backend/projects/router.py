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

`assemble_prompt`'s `chapter_summaries` prefix (`_accumulated_chapter_summaries`, ADR-0003
addendum) is populated from every chapter in the project that has been accepted and summarized at
least once — `accept_draft_version_endpoint` dispatches `llm_routing.tasks.summarize_chapter_task`
right after each accept and persists the result onto that chapter via
`projects.service.update_chapter_summary` (TASK-E03-2's `summarize_chapter`, now wired into a
session).

Full citation verification (ADR-0001,
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
import base64
import json
import os
import re
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

import redis.asyncio as redis_asyncio
from celery.exceptions import TimeoutError as CeleryTimeoutError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from diploma_backend.auth.dependencies import get_current_user_id
from diploma_backend.db import get_database
from diploma_backend.export.docx import apply_institution_config, markdown_to_docx
from diploma_backend.formatting.service import get_institution_config
from diploma_backend.humanizer.pipeline import HumanizationError
from diploma_backend.humanizer.tasks import humanize_text_task
from diploma_backend.llm_routing import (
    DeepSeekClient,
    LLMRequestError,
    generate_project_title,
)
from diploma_backend.llm_routing.summary import assemble_prompt
from diploma_backend.llm_routing.tasks import (
    generate_with_retry_task,
    stream_generation_task,
    summarize_chapter_task,
)
from diploma_backend.locks.models import Block
from diploma_backend.locks.service import (
    AnchorResolution,
    AnchorResolutionError,
    find_valid_anchor,
    list_locks_for_chapter,
    reverify_anchor_resolution,
)
from diploma_backend.plagiarism.precheck import PlagiarismCheckResult, SentenceFlag
from diploma_backend.plagiarism.tasks import run_precheck_task
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
    update_chapter_summary,
    update_project_title,
)
from diploma_backend.sources.client import delete_project_vectors
from diploma_backend.sources.required import list_required_sources_for_project
from diploma_backend.sources.search import SourceSearchError, search_sources
from diploma_backend.toc.parser import TocParseError
from diploma_backend.toc.tasks import (
    parse_document_sections_with_subchapters_task,
    parse_toc_with_subchapters_task,
)
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

# Matches `llm_routing.client._DEFAULT_TIMEOUT_SECONDS`'s precedent of a generous fixed timeout
# for an external/out-of-process call this handler must still `await` before responding
# (ADR-0013 addendum point 1). `parse_toc` itself is fast in-memory `.docx` parsing; this mostly
# bounds how long a request waits on a busy/unreachable Celery worker, not the parse itself.
_TOC_PARSE_TASK_TIMEOUT_SECONDS = 60.0

# Same heuristic as `projects.service._LEADING_NUMBER_RE` (duplicated locally rather than
# imported, matching `locks.router`'s precedent of duplicating a small private helper across a
# module boundary rather than reaching into another module's private name): pulls a leading
# chapter number out of a title regardless of the surrounding words. Used by
# `upload_document_endpoint` to match a whole-document upload's `Heading 1` sections against
# chapters a prior `upload_toc_endpoint` call already created, since a real thesis's actual
# chapter heading and its TOC entry frequently word the rest of the title differently even when
# they share the same chapter number (e.g. TOC: "ГЛАВА 1 ТЕОРЕТИЧЕСКИЕ ОСНОВЫ ...", the
# document's real heading: "ГЛАВА 1 ТЕОРЕТИКО-МЕТОДОЛОГИЧЕСКИЕ ПРЕДПОСЫЛКИ ...") — an exact-text
# match alone would treat these as unrelated and create a duplicate chapter.
_LEADING_CHAPTER_NUMBER_RE = re.compile(r"^\D*(\d+)")


def _index_existing_chapters(
    chapters: list[Chapter],
) -> tuple[dict[str, Chapter], dict[str, list[Chapter]]]:
    """Builds the two lookup indexes `_match_existing_chapter` needs from a flat chapter list:
    by exact (trimmed, case-insensitive) title, and by leading chapter number. Callers pass an
    already-scoped list (e.g. just one chapter's subchapters, or just a project's top-level
    chapters) — this function does no scoping of its own.
    """
    by_title: dict[str, Chapter] = {}
    by_number: dict[str, list[Chapter]] = {}
    for chapter in chapters:
        by_title[chapter.title.strip().casefold()] = chapter
        number_match = _LEADING_CHAPTER_NUMBER_RE.match(chapter.title)
        if number_match is not None:
            by_number.setdefault(number_match.group(1), []).append(chapter)
    return by_title, by_number


def _match_existing_chapter(
    title: str, by_title: dict[str, Chapter], by_number: dict[str, list[Chapter]]
) -> Chapter | None:
    """Finds `title`'s existing counterpart, if any: an exact (trimmed, case-insensitive) title
    match first, else a leading-chapter-number match — but only when exactly one existing
    chapter shares that number, since matching against an ambiguous number would risk merging
    two genuinely different chapters that happen to both start with e.g. "1".
    """
    exact = by_title.get(title.strip().casefold())
    if exact is not None:
        return exact
    number_match = _LEADING_CHAPTER_NUMBER_RE.match(title)
    if number_match is None:
        return None
    candidates = by_number.get(number_match.group(1), [])
    return candidates[0] if len(candidates) == 1 else None


# Same rationale/precedent as `_TOC_PARSE_TASK_TIMEOUT_SECONDS`, applied to the humanize/precheck
# tasks the generation pipeline now awaits (ADR-0013, TASK-E17-4). Matches
# `plagiarism.router._PRECHECK_TASK_TIMEOUT_SECONDS`'s value.
#
# `_HUMANIZE_TASK_TIMEOUT_SECONDS` is NOT 60.0 like precheck (a single fast-tier call, so 60s —
# `DeepSeekClient._DEFAULT_TIMEOUT_SECONDS` — is the real worst case): `humanize_text` retries its
# DeepSeek call up to 3 times internally via `generate_with_retry` (see that function's own
# docstring), the same shape `_GENERATE_TASK_TIMEOUT_SECONDS` already budgets for. A 60s ceiling
# here fires `celery.exceptions.TimeoutError` (not `LLMRequestError`) well before a real multi-
# attempt humanize call can finish — observed in production taking 90-100s for a single retry
# even without hitting a second attempt — which used to crash the whole SSE response instead of
# falling open to the pre-humanization draft (see `_run_humanize`'s `except` clause below).
_HUMANIZE_TASK_TIMEOUT_SECONDS = 200.0
_PRECHECK_TASK_TIMEOUT_SECONDS = 60.0

# Applied to `summarize_chapter_task`, dispatched from `accept_draft_version_endpoint` (ADR-0003
# addendum, follow-up to TASK-E03-2/E17). Same 60.0 as `_HUMANIZE_TASK_TIMEOUT_SECONDS`:
# `summarize_chapter` makes a single fast-tier call with no internal retry of its own, unlike the
# heavy-tier generation call, so there's no multi-attempt worst case to budget extra headroom for.
_SUMMARIZE_TASK_TIMEOUT_SECONDS = 60.0

# Applied to the non-streaming heavy-tier draft generation call, now dispatched to
# `llm_routing.tasks.generate_with_retry_task` (ADR-0013, TASK-E17-4). Deliberately NOT the same
# 60.0 as `_HUMANIZE_TASK_TIMEOUT_SECONDS`/`_PRECHECK_TASK_TIMEOUT_SECONDS`: `generate_with_retry`
# (llm_routing/retry.py) can make up to `max_attempts=3` DeepSeek calls, each with its own
# `DeepSeekClient._DEFAULT_TIMEOUT_SECONDS=60.0` ceiling, plus exponential backoff between them
# (`base_delay_seconds * 2**attempt` for each of the 2 retries = 1s + 2s = 3s) — worst case
# 3*60 + 3 = 183s before `generate_with_retry` itself would give up and raise `LLMRequestError`.
# This timeout must stay comfortably above that worst case, or `.get()` fires first with
# `celery.exceptions.TimeoutError` (NOT `LLMRequestError`, so NOT caught by this endpoint's
# `except LLMRequestError` block) while the underlying task keeps running detached from the
# already-abandoned HTTP request.
_GENERATE_TASK_TIMEOUT_SECONDS = 200.0

# Read the same way `worker.celery_app`/`llm_routing.tasks` read `REDIS_URL` (see the latter's
# matching comment for why this two-line duplication is preferred over a shared config module for
# one env var read in three places).
_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# How many stream entries `generate_chapter_draft_stream_endpoint`'s catch-up `XREAD` requests in
# one call (ADR-0013 addendum point 2). Does NOT need to cover every entry a
# `stream_generation_task` that had already finished (under `task_always_eager=True`, always true
# in tests) may have written before this endpoint's tail loop attached — any entries past this
# call's cap are picked up by the very next `while not done:` iteration below instead, since a
# blocking `XREAD` from a given id returns immediately (no waiting) when entries already exist
# past that id. `llm_routing.tasks._STREAM_MAXLEN` is deliberately NOT trimmed during the hot
# per-chunk write loop any more (see that constant's docstring), so this count and that cap no
# longer need any numeric relationship to each other for correctness.
_STREAM_CATCHUP_COUNT = 500

# How long each subsequent `XREAD BLOCK` waits for a new entry before looping again. Short enough
# that a client disconnect is noticed promptly, long enough to avoid a tight busy-poll loop.
_STREAM_READ_BLOCK_MS = 2000

# Overall wall-clock ceiling on `generate_chapter_draft_stream_endpoint`'s catch-up + tail-loop
# sequence (i.e. from dispatching `stream_generation_task` to seeing its terminal `"done"`/
# `"error"` marker) — without this, a worker crash mid-task, a transient Redis error while
# publishing, or the stream key's `_STREAM_TTL_SECONDS` expiring before a marker ever arrives would
# leave the tail loop re-polling every `_STREAM_READ_BLOCK_MS` forever: an unbounded, leaked-open
# SSE connection/coroutine. Mirrors `_GENERATE_TASK_TIMEOUT_SECONDS`'s "don't hang forever"
# precedent for the non-streaming migration: this streaming path drives the same underlying
# DeepSeek call (worst case ~183s inside `generate_with_retry`, per that constant's comment) plus
# streaming overhead, so this ceiling is set comfortably above it rather than reusing it outright.
_STREAM_TAIL_TIMEOUT_SECONDS = 280.0

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
    "instruction, in plain and direct language rather than dense or inflated phrasing. Do not "
    "include meta-commentary about being an AI. If reference sources are provided below, ground "
    "relevant claims in them and cite each one in-text as (Author, Year) — using the source's "
    "own title/year if no author name is given — when you draw on it directly. An excerpt marked "
    "\"[REQUIRED]\" is a source the student specifically asked to have cited in this project: "
    "work it into the chapter and cite it at least once if it is even plausibly relevant to the "
    "instruction, rather than skipping it the way you might skip an unmarked excerpt that "
    "doesn't fit — treat skipping a [REQUIRED] source as a last resort, not a default. Never "
    "invent a citation for a source that was not provided; if none of the provided sources are "
    "relevant to a claim, state it plainly without a citation rather than fabricating one."
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
    "follows the user's instruction, in plain and direct language rather than dense or inflated "
    "phrasing. Do not include meta-commentary about being an AI. If reference sources are "
    "provided below, ground relevant claims in them and cite each one in-text as (Author, Year) — "
    "using the source's own title/year if no author name is given — when you draw on it "
    "directly. An excerpt marked \"[REQUIRED]\" is a source the student specifically asked to "
    "have cited in this project: work it into this inserted text and cite it at least once if it "
    "is even plausibly relevant to the instruction, rather than skipping it the way you might "
    "skip an unmarked excerpt that doesn't fit — treat skipping a [REQUIRED] source as a last "
    "resort, not a default. Never invent a citation for a source that was not provided; if none "
    "of the provided sources are relevant to a claim, state it plainly without a citation rather "
    "than fabricating one."
)

# Caps how many external search results become RAG excerpts per generation call — enough to
# ground the model without bloating the prompt (and DeepSeek's cache-hit economics, ADR-0003,
# favor a small, stable-ish context over a large one).
_RAG_EXCERPT_LIMIT = 3


# Per-chapter cap on the raw-excerpt fallback in `_accumulated_chapter_summaries` (see that
# function's docstring for why the fallback exists at all). Short enough that a project with many
# still-pending chapters (a bulk TOC/whole-document import, user request) doesn't blow up the
# prompt into one huge, cache-hostile block; long enough to give the model real terminology/
# content awareness rather than just a title.
_CONTEXT_EXCERPT_MAX_CHARS = 600


async def _accumulated_chapter_summaries(
    db: AsyncIOMotorDatabase, project_id: str, *, exclude_chapter_id: str | None = None
) -> list[str]:
    """Fetch `project_id`'s accumulated per-chapter context for `assemble_prompt`'s
    `chapter_summaries` (ADR-0003 addendum, follow-up to TASK-E03-2/E17), so drafting a new
    chapter/subchapter has awareness of every other chapter/subchapter/appendix in the project —
    not just ones that happen to already be accepted.

    For each chapter `list_chapters_for_project` returns (top-level chapters, subchapters, and
    appendix entries alike — that function applies no `parent_chapter_id` filter), in `created_at`
    order (chronological creation order, unlike `Chapter.order`, which is only unique within a
    `(project_id, parent_chapter_id)` scope per ADR-0014 and so cannot order chapters with
    different parents against each other):

    - If it has a persisted `summary` (accepted at least once and summarized successfully by
      `_summarize_and_persist_chapter`), that compact summary is used, as before.
    - Otherwise (user report: a bulk TOC/whole-document import leaves most chapters as an
      unaccepted pending draft, so `chapter_summaries` was empty for an entire freshly-imported
      project — nothing was visible to the model until the user accepted every single chapter
      first), a truncated raw excerpt (`_CONTEXT_EXCERPT_MAX_CHARS`) of its latest known content
      — the pending draft if one exists, else the current accepted content — is used instead,
      labeled with the chapter's title so the model can tell which chapter an excerpt belongs to.
      Skipped entirely if the chapter has neither a summary nor any content yet (nothing to add).

    `exclude_chapter_id`, when given, skips the raw-excerpt fallback for that one chapter (the
    chapter currently being generated into) — feeding a model the full pending draft it's about
    to rewrite is redundant at best and confusing at worst. Its own persisted `summary`, if any,
    is still included, matching this function's original behavior of never excluding a chapter's
    summary regardless of which chapter is being generated.
    """
    chapters = await list_chapters_for_project(db, project_id)
    chapters.sort(key=lambda chapter: chapter.created_at)

    entries: list[str] = []
    for chapter in chapters:
        if chapter.summary is not None:
            entries.append(chapter.summary)
            continue
        if chapter.id == exclude_chapter_id:
            continue
        draft = await get_latest_draft_version(db, chapter.id)
        accepted = await get_current_accepted_version(db, chapter.id)
        content = draft.content if draft is not None else (accepted.content if accepted is not None else None)
        if not content:
            continue
        excerpt = content[:_CONTEXT_EXCERPT_MAX_CHARS]
        if len(content) > _CONTEXT_EXCERPT_MAX_CHARS:
            excerpt += "…"
        entries.append(f"{chapter.title}: {excerpt}")
    return entries


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
        # "[REQUIRED]" distinguishes this from an ordinary `_fetch_rag_excerpts` result once both
        # are concatenated into one `rag_excerpts` list for `assemble_prompt` — otherwise the
        # model has no way to tell a must-cite source apart from a generic search hit, and (per
        # `_GENERATION_SYSTEM_PROMPT`'s "cite it when you draw on it directly" wording) is free to
        # judge it irrelevant and skip it like any other excerpt. See the system prompts' own
        # `[REQUIRED]` handling for the citation obligation this marker carries.
        excerpts.append(f"[REQUIRED] {matched.title} ({matched.year}): {matched.abstract}")

    return excerpts, unmet


def _plagiarism_result_from_task_dict(precheck_dict: dict) -> PlagiarismCheckResult:
    """Reconstruct a `PlagiarismCheckResult` from `run_precheck_task`'s plain-dict return value.

    `run_precheck_task` returns `dataclasses.asdict(result)`, which recurses into the nested
    `sentence_flags: list[SentenceFlag]` and converts each entry to a plain `dict` too. Plain
    dataclass construction (`PlagiarismCheckResult(**precheck_dict)`) does NOT reverse that
    recursion, so doing so directly would leave `sentence_flags` as a `list[dict]` sitting inside
    a `PlagiarismCheckResult` that claims to hold `list[SentenceFlag]` — any caller that reads a
    flag's fields as attributes (e.g. `plagiarism.router.SentenceFlagResponse.from_flag`, via
    `flag.text`/`flag.plagiarism_score`) would raise `AttributeError` the first time a generation
    actually produces a flagged sentence. This helper re-wraps each entry in `SentenceFlag`
    explicitly before constructing the outer dataclass, so the result matches
    `PlagiarismCheckResult`'s real shape. Used by both `_humanize_and_precheck` and
    `generate_chapter_draft_stream_endpoint`, which otherwise duplicate this same reconstruction.
    """
    return PlagiarismCheckResult(
        **{
            **precheck_dict,
            "sentence_flags": [SentenceFlag(**flag) for flag in precheck_dict["sentence_flags"]],
        }
    )


def _default_precheck_result() -> PlagiarismCheckResult:
    """All-clear fallback `PlagiarismCheckResult` for when `run_precheck_task` itself fails
    outright (see `_run_precheck_with_fallback`).

    `run_precheck.precheck.run_precheck` is pure/synchronous/no I/O and essentially cannot fail
    in practice, but a resilience gap here is otherwise cheap to close and consistent with this
    module's broader "already-generated content must never be discarded over a non-correctness-
    critical stage" posture (see `_humanize_and_precheck`'s docstring): the precheck score is a
    quality signal ("a human should take a second look," per `plagiarism.precheck`'s module
    docstring), not a correctness gate, so a scoring failure must never discard an already-
    generated, already-humanized draft. `flagged=False`/zero scores/empty `reasons` and
    `sentence_flags` describe "nothing was flagged" rather than "this was actively checked and
    found clean" — a caller/frontend surfacing this result should treat it as precheck being
    unavailable for this draft, not as a clean bill of health.
    """
    return PlagiarismCheckResult(
        plagiarism_score=0.0,
        ai_fingerprint_score=0.0,
        flagged=False,
        reasons=[],
    )


async def _run_precheck_with_fallback(
    humanized_content: str, rag_excerpts: list[str]
) -> PlagiarismCheckResult:
    """Run `run_precheck_task` against `humanized_content`, falling back to
    `_default_precheck_result()` if dispatching or awaiting it raises anything at all.

    Unlike `_run_humanize`'s `LLMRequestError`/`HumanizationError` handling, this catches a broad
    `Exception` rather than a specific type: `run_precheck_task` has no internal `asyncio.run()`
    (it calls the synchronous `run_precheck` directly), so only the blocking `.get()` needs
    `asyncio.to_thread`, matching `plagiarism.router`'s existing `.delay()`-then-
    `asyncio.to_thread(async_result.get, ...)` pattern for the same task — but both the dispatch
    and the wait sit inside this one `try` so a failure at either point fails open the same way.
    """
    try:
        async_result = run_precheck_task.delay(humanized_content, rag_excerpts)
        precheck_dict = await asyncio.to_thread(
            async_result.get, timeout=_PRECHECK_TASK_TIMEOUT_SECONDS
        )
        return _plagiarism_result_from_task_dict(precheck_dict)
    except Exception:  # noqa: BLE001 -- precheck is a quality signal, not correctness-critical;
        # see `_default_precheck_result`'s docstring for why a scoring failure must never
        # discard an already-generated, already-humanized draft.
        return _default_precheck_result()


async def _humanize_and_precheck(
    content: str, rag_excerpts: list[str]
) -> tuple[str, PlagiarismCheckResult]:
    """Shared humanize -> plagiarism/AI-detection precheck pipeline, used by both full-chapter and
    "insert at anchor" (TASK-E15-1) generation, so the two modes never duplicate this logic.

    Both stages now run on a Celery worker (ADR-0013, TASK-E17-4) via
    `humanizer.tasks.humanize_text_task` and `plagiarism.tasks.run_precheck_task` instead of
    inline on this process, but this handler still `await`s each task's result before returning,
    so callers see the exact same behavior/timing shape as before (ADR-0013 addendum point 1) —
    no `client` argument is needed here any more, since `humanize_text_task` builds its own
    `DeepSeekClient` from `DEEPSEEK_API_KEY`/`DEEPSEEK_FAST_MODEL`/`DEEPSEEK_HEAVY_MODEL`, the
    same environment fallback every caller of this function already relies on (both call this
    with a bare `DeepSeekClient()`).

    Both the `.delay()` call AND the blocking `.get()` are run together inside a single
    `asyncio.to_thread(...)` call, not just `.get()` (unlike `upload_toc_endpoint`'s
    `parse_toc_with_subchapters_task`/`plagiarism.router`'s `run_precheck_task` sites): under
    `task_always_eager=True` (tests), `.delay()` itself runs the task body synchronously, and
    `humanize_text_task`'s body drives its async work via `asyncio.run(...)` (ADR-0013 addendum
    point 3) — calling `.delay()` directly from this already-running coroutine would collide with
    the caller's own event loop ("asyncio.run() cannot be called from a running event loop").
    Running both calls in a worker thread sidesteps that regardless of eager/real-worker mode.

    Humanization is cosmetic, not correctness-critical (per `humanizer.pipeline`'s own framing),
    and `humanize_text` already retries the underlying DeepSeek call itself up to 3 times
    internally (`llm_routing.retry.generate_with_retry`) before ever raising — so BOTH failure
    modes it can still surface after that fail open here to the pre-humanization `content` rather
    than discarding an already-generated (and, for the "heavy" tier draft call, already
    expensively-paid-for) piece of content: `HumanizationError` (the model dropped/mangled a
    `__CITATION_N__` placeholder) and, as of this change, a genuine `LLMRequestError` too (every
    retry attempt inside `humanize_text` was exhausted). No humanize failure of any kind should
    ever discard already-generated content — only the raw generation call itself (still
    dispatched separately, before this function is ever called) surfaces as a hard failure to the
    caller. Per `task_eager_propagates=True` (tests) / a real worker (production), both exception
    types propagate through `asyncio.to_thread` unchanged (see `test_humanizer_tasks.py`).

    The precheck stage (`_run_precheck_with_fallback`) fails open the same way on ANY exception,
    not just a specific type — see that helper's docstring.

    `run_precheck_task` returns a plain `dict` (`dataclasses.asdict` of a `PlagiarismCheckResult`,
    since Celery's JSON result backend can't carry the dataclass natively); it is converted back
    into a `PlagiarismCheckResult` here (via `_plagiarism_result_from_task_dict`, which also
    rehydrates the nested `sentence_flags` entries) so this function's return type/contract is
    unchanged for its callers (both build a `PlagiarismCheckResultResponse` via `.from_result`).
    """

    def _run_humanize() -> str:
        return humanize_text_task.delay(content).get(timeout=_HUMANIZE_TASK_TIMEOUT_SECONDS)

    try:
        humanized_content = await asyncio.to_thread(_run_humanize)
    except (LLMRequestError, HumanizationError, CeleryTimeoutError):
        # Fail-open: neither a genuine infra failure (retries exhausted or, per
        # `_HUMANIZE_TASK_TIMEOUT_SECONDS`'s comment, this handler's own wait timing out before a
        # slow-but-still-running task finishes) nor a mangled citation placeholder should block
        # the user from seeing their already-generated draft — see docstring.
        humanized_content = content

    precheck = await _run_precheck_with_fallback(humanized_content, rag_excerpts)
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


async def _summarize_and_persist_chapter(
    db: AsyncIOMotorDatabase, chapter_id: str, content: str
) -> None:
    """Best-effort accept-time chapter summarization (ADR-0003 addendum, follow-up to
    TASK-E03-2/E17), dispatched from `accept_draft_version_endpoint` right after a draft version
    is flipped to `accepted`.

    Fails open exactly like `_finish_title_generation`'s title-generation call: this is a
    nice-to-have background enrichment (feeding `assemble_prompt`'s `chapter_summaries` prefix on
    later generation calls), never a correctness-critical step, so ANY failure here — an
    `LLMRequestError` (the underlying DeepSeek call failed) or a `celery.exceptions.TimeoutError`
    (the worker didn't respond within `_SUMMARIZE_TASK_TIMEOUT_SECONDS`) — is caught and swallowed,
    leaving the chapter's stored `summary` at whatever it was before (`None` on a chapter's first
    accept, or stale from a previous accept). Accepting a draft must never fail or be delayed by a
    summarization problem.

    `summarize_chapter_task`'s body drives its async work via `asyncio.run(...)` (ADR-0013
    addendum point 3), so both the `.delay()` call and the blocking `.get()` are run together
    inside one `asyncio.to_thread(...)` call, not just `.get()` alone — same caller-side pattern
    as `_run_generate`/`_run_humanize` elsewhere in this module (ADR-0013 addendum point 3's
    caller-side corollary).
    """

    def _run_summarize() -> str:
        return summarize_chapter_task.delay(content).get(
            timeout=_SUMMARIZE_TASK_TIMEOUT_SECONDS
        )

    try:
        summary = await asyncio.to_thread(_run_summarize)
    except Exception:  # noqa: BLE001 -- fail open on any summarization problem, see docstring
        return
    await update_chapter_summary(db, chapter_id, summary)


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


async def _get_owned_project(db: AsyncIOMotorDatabase, project_id: str, owner_id: str) -> Project:
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
    return f"attachment; filename=\"{ascii_fallback}.docx\"; filename*=UTF-8''{encoded}.docx"


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
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
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
    """Parse an uploaded `.docx` table of contents and create one chapter per entry, in order,
    plus a subchapter per dotted-numbered subsection line (e.g. `"3.1 ..."` under `"3 ..."`,
    user request) under its nearest preceding chapter.

    Matches each parsed chapter/subchapter title against the project's existing chapters (see
    `_match_existing_chapter`) and reuses a match instead of creating a duplicate — e.g. running
    this after `upload_document_endpoint` already created chapters from the same thesis's actual
    headings.

    Scoped to the authenticated caller (TASK-E11-1): raises `HTTPException(404)` if `project_id`
    doesn't exist or belongs to a different owner. Parsing itself now runs on a Celery worker via
    `toc.tasks.parse_toc_with_subchapters_task` (ADR-0013, TASK-E17-4) instead of inline on this
    process; the uploaded bytes are base64-encoded before `.delay()` since Celery's default JSON
    serializer cannot carry raw `bytes`, and the task decodes them back before calling
    `parse_toc_with_subchapters`. Per ADR-0013's addendum point 1, the HTTP contract is
    unchanged: this handler still `await`s the task's result (via `asyncio.to_thread`, since
    `AsyncResult.get()` blocks) before responding, with the same response shape/status as before.
    Raises `HTTPException(422)` if the task surfaces a `TocParseError` (fail-closed, matching
    `formatting.router`'s upload-parse-error convention) — Celery re-raises the original
    exception type from `.get()` when it's importable in this process, which it is here since the
    API and worker share this codebase, so the `except TocParseError` below still fires whether
    the task ran eagerly (tests) or on a real worker.

    Note: this only creates chapters from the parsed TOC; inserting a later-generated
    chapter between existing ones is handled separately by `insert_chapter_endpoint`.
    """
    project = await _get_owned_project(db, project_id, owner_id)

    content = await file.read()
    content_b64 = base64.b64encode(content).decode("ascii")
    try:
        # `task_eager_propagates` (tests) raises directly from `.delay()` rather than deferring
        # the exception to `.get()`, so both calls must sit inside this `try` block to catch a
        # `TocParseError` regardless of whether the task ran eagerly or on a real worker.
        async_result = parse_toc_with_subchapters_task.delay(content_b64)
        chapters = await asyncio.to_thread(
            async_result.get, timeout=_TOC_PARSE_TASK_TIMEOUT_SECONDS
        )
    except TocParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    existing_chapters = await list_chapters_for_project(db, project_id)
    by_title, by_number = _index_existing_chapters(
        [chapter for chapter in existing_chapters if chapter.parent_chapter_id is None]
    )

    for title, subchapter_titles in chapters:
        chapter = _match_existing_chapter(title, by_title, by_number) or await create_chapter(
            db, project_id, title
        )
        existing_subchapters = [
            existing for existing in existing_chapters if existing.parent_chapter_id == chapter.id
        ]
        sub_by_title, sub_by_number = _index_existing_chapters(existing_subchapters)
        for subchapter_title in subchapter_titles:
            if _match_existing_chapter(subchapter_title, sub_by_title, sub_by_number) is None:
                await create_chapter(
                    db, project_id, subchapter_title, parent_chapter_id=chapter.id
                )
    return await _build_project_detail(db, project)


@router.post(
    "/{project_id}/document/upload",
    response_model=ProjectDetail,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_endpoint(
    project_id: str,
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> ProjectDetail:
    """Ingest a whole already-written `.docx` document as multiple chapters (and subchapters,
    user request) in one upload, instead of requiring `upload_toc_endpoint` (titles only)
    followed by a separate `locks.router.upload_draft_endpoint` call per chapter.

    Splits `file` into `(title, content, subchapters)` sections by `Heading 1` paragraph, each
    further split into subchapters at `Heading 2`/dotted-numbered subsection boundaries (see
    `toc.parser.parse_document_sections_with_subchapters`'s docstring for the exact rule), via
    the same base64-encode-then-Celery-task shape as `upload_toc_endpoint` (ADR-0013,
    TASK-E17-4). Matches each parsed chapter/subchapter title against the project's existing
    chapters (see `_match_existing_chapter`) — e.g. ones already created by a prior
    `upload_toc_endpoint` call, or by an earlier call to this same endpoint — and reuses a match
    instead of creating a duplicate (user request: this was always creating a fresh chapter per
    section, even when a TOC upload had already made one for the same chapter under a slightly
    differently-worded title). Falls back to creating a new chapter when no title matches, same
    as before. Either way, if the section/subchapter has any non-blank content, ingests it as
    that chapter's first pending draft version (`versions.service.create_draft_version`) — same
    as `locks.router.upload_draft_endpoint`, so the ingested content goes through the same
    accept/reject `DiffViewer` flow as any other draft rather than silently becoming "accepted"
    content with no review step. A section with only a heading and no body content still gets/
    creates its chapter, just with no pending draft to review.

    Scoped to the authenticated caller (TASK-E11-1): raises `HTTPException(404)` if `project_id`
    doesn't exist or belongs to a different owner. Raises `HTTPException(422)` if the task
    surfaces a `TocParseError` (no valid `.docx`, or no `Heading 1` paragraphs found) — fail
    closed, matching `upload_toc_endpoint`'s convention, rather than guessing chapter boundaries.
    """
    project = await _get_owned_project(db, project_id, owner_id)

    content = await file.read()
    content_b64 = base64.b64encode(content).decode("ascii")
    try:
        async_result = parse_document_sections_with_subchapters_task.delay(content_b64)
        sections = await asyncio.to_thread(
            async_result.get, timeout=_TOC_PARSE_TASK_TIMEOUT_SECONDS
        )
    except TocParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    existing_chapters = await list_chapters_for_project(db, project_id)
    by_title, by_number = _index_existing_chapters(
        [chapter for chapter in existing_chapters if chapter.parent_chapter_id is None]
    )

    for title, section_content, subchapters in sections:
        chapter = _match_existing_chapter(title, by_title, by_number) or await create_chapter(
            db, project_id, title
        )
        if section_content.strip():
            await create_draft_version(db, chapter.id, content=section_content)

        existing_subchapters = [
            existing for existing in existing_chapters if existing.parent_chapter_id == chapter.id
        ]
        sub_by_title, sub_by_number = _index_existing_chapters(existing_subchapters)
        for subtitle, subcontent in subchapters:
            subchapter = _match_existing_chapter(
                subtitle, sub_by_title, sub_by_number
            ) or await create_chapter(db, project_id, subtitle, parent_chapter_id=chapter.id)
            if subcontent.strip():
                await create_draft_version(db, subchapter.id, content=subcontent)
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
    owner_id: str = Depends(get_current_user_id),
) -> GenerateDraftResponse:
    """Generate a chapter draft from a chat instruction, humanize it, scan it, and store the
    humanized text as a new draft version.

    Scoped to the authenticated caller via `_get_owned_chapter`: raises `HTTPException(404)` if
    `chapter_id` doesn't exist, doesn't belong to `project_id`, or `project_id` belongs to a
    different owner (previously this endpoint had no ownership check at all — TASK-E16-2 added
    the `get_current_user_id` dependency it needed for `applied_by` and, since a real caller
    identity is now available, this closes what would otherwise be a same-diff IDOR: any
    authenticated user generating content into a project they don't own).
    Fetches live RAG excerpts via `_fetch_rag_excerpts` (external academic search, see module
    docstring) and builds messages via `assemble_prompt` with `chapter_summaries=[]` and those
    excerpts, then calls the DeepSeek "heavy" tier (ADR-0003: chapter drafting), now dispatched to
    a Celery worker via `llm_routing.tasks.generate_with_retry_task` (ADR-0013, TASK-E17-4) rather
    than calling `generate_with_retry` inline. Both the `.delay()` call and the blocking `.get()`
    are run together inside a single `asyncio.to_thread(...)` call, not just `.get()` alone
    (ADR-0013 addendum point 3's caller-side corollary), since `generate_with_retry_task`'s body
    drives its async work via `asyncio.run(...)` and would otherwise collide with this already-
    running coroutine's own event loop under `task_always_eager=True` (tests) — same pattern as
    `_humanize_and_precheck`'s `_run_humanize`. Raises `HTTPException(502)` if every retry attempt
    fails (`LLMRequestError`), propagated unchanged through the worker thread.

    The raw generated content is then passed through `humanizer.pipeline.humanize_text` (fast
    tier per ADR-0003), now dispatched to a Celery worker via `humanizer.tasks.humanize_text_task`
    (ADR-0013, TASK-E17-4) rather than running inline — see `_humanize_and_precheck` — to break up
    repetitive LLM-sounding patterns. Citation verification (ADR-0001) is not yet wired into this
    endpoint (see module docstring), so no citation markers are formatted into the raw text today,
    and `humanize_text`'s `guard_citations` step should find nothing to guard in practice. Any
    humanize-stage failure — a `HumanizationError` (the model dropped/mangled a citation
    placeholder) or a `LLMRequestError` (the humanize call's own internal retries, per
    `llm_routing.retry.generate_with_retry`, were exhausted) — is deliberately fail-open here (see
    `_humanize_and_precheck`'s docstring): humanization is a cosmetic polishing stage, not a
    correctness-critical one (unlike citation verification itself, or the raw draft generation
    call above, both of which still fail closed), so this endpoint falls back to the
    pre-humanization content rather than discarding an already-generated draft and blocking the
    user from seeing it at all. Precheck failures fail open the same way (`_run_precheck_with_
    fallback`), to an all-clear `PlagiarismCheckResult`.

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

    Requires authentication (`Depends(get_current_user_id)`, added for TASK-E16-2): in anchor
    mode, `owner_id` is threaded through to `create_draft_version_at_anchor` as `applied_by`, so
    each newly spliced block's recorded `Operation` (ADR-0012) attributes it to the caller.
    Raises `HTTPException(401)` (via `get_current_user_id`) if no valid bearer token is given.
    """
    await _get_owned_chapter(db, project_id, chapter_id, owner_id)
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
        chapter_summaries=await _accumulated_chapter_summaries(db, project_id, exclude_chapter_id=chapter_id),
        rag_excerpts=rag_excerpts,
        user_message=body.instruction,
    )

    client = DeepSeekClient()
    title_task = _maybe_start_title_generation(client, project, body.instruction)

    def _run_generate() -> str:
        return generate_with_retry_task.delay("heavy", messages).get(
            timeout=_GENERATE_TASK_TIMEOUT_SECONDS
        )

    try:
        try:
            content = await asyncio.to_thread(_run_generate)
        except LLMRequestError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        humanized_content, precheck = await _humanize_and_precheck(content, rag_excerpts)

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
                    applied_by=owner_id,
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


def _process_stream_entries(
    entries: list[tuple[str, dict[str, str]]], chunks: list[str]
) -> tuple[list[str], bool, str | None, str | None]:
    """Turn a batch of `generation:{task_id}` Redis Stream entries (ADR-0013 addendum point 2)
    into SSE-framed strings for `generate_chapter_draft_stream_endpoint`'s tail loop to yield.

    Appends each `"token"` entry's `data` field to `chunks` in place (mirroring the accumulation
    the old inline `client.generate_stream` loop performed, so the unchanged humanize/precheck
    block below still sees `"".join(chunks)` as the full generated text) and returns:
    - the list of `_sse_event("token", ...)` strings to yield, in order;
    - whether a terminal (`"done"`/`"error"`) entry was seen in this batch;
    - that entry's `"detail"` field if it was `"error"`, else `None`;
    - the last entry id processed in this batch (`None` if `entries` was empty), so the caller
      knows where to resume `XREAD`ing from.

    Stops processing (ignoring any further entries in this same batch) as soon as a terminal entry
    is seen, matching the old code's `except LLMRequestError: ... return` early-exit shape — a
    `done`/`error` marker is always the last entry `stream_generation_task` publishes.
    """
    sse_events: list[str] = []
    done = False
    error_detail: str | None = None
    last_id: str | None = None
    for entry_id, fields in entries:
        last_id = entry_id
        event_type = fields.get("type")
        if event_type == "token":
            data = fields.get("data", "")
            chunks.append(data)
            sse_events.append(_sse_event("token", data))
        elif event_type == "done":
            done = True
            break
        elif event_type == "error":
            done = True
            error_detail = fields.get("detail", "")
            break
    return sse_events, done, error_detail, last_id


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
      spec, all within the same event). The generation call itself now runs inside
      `llm_routing.tasks.stream_generation_task` (ADR-0013 addendum point 2, TASK-E17-3) rather
      than inline: this endpoint enqueues that task, then tails its `generation:{task_id}` Redis
      Stream via `XREAD` (catch-up from `0`, then `BLOCK`-ing reads) and re-emits each `"token"`
      entry as the same `event: token` SSE frame as before — the response contract is unchanged.
    - On successful completion of the stream: the accumulated raw text is run through the same
      `humanize_text_task` -> `run_precheck_task` (with the same live-searched RAG excerpts as
      `source_excerpts`, see module docstring) -> `create_draft_version` pipeline as
      `generate_chapter_draft_endpoint`'s `_humanize_and_precheck`, both now dispatched to a
      Celery worker (ADR-0013, TASK-E17-4) rather than running inline. Both `HumanizationError`
      and `LLMRequestError` from the humanize call fail open to the raw streamed text (see
      `_humanize_and_precheck`'s docstring for why: humanization is cosmetic, not correctness-
      critical, and already retries the underlying DeepSeek call internally, so its own retries
      being exhausted must not discard the already-streamed draft) — then a single `event: done`
      whose `data:` is the JSON (via `.model_dump(mode="json")`) of a `GenerateDraftResponse`-
      shaped payload (`{"version": ..., "precheck": ...}`) — same response shape as that
      endpoint's body.
    - On `LLMRequestError` from `generate_stream` (a non-2xx status before the stream starts, or a
      connection drop mid-stream) — now surfaced as an `"error"` entry on the Redis Stream by
      `stream_generation_task` rather than raised directly in this coroutine — a single
      `event: error` whose `data:` is `{"detail": str(exc)}`, and the generator stops. Per
      TASK-E08-3's scope, streaming has no retry of the generation call itself, so this remains a
      real, visible failure to the user, not silently retried — but if any tokens were already
      streamed before the failure (`chunks` non-empty), they are persisted as a draft via
      `create_draft_version` (raw, un-humanized/un-prechecked — the generation itself failed, so
      there is nothing more to do with the partial text than save it) BEFORE the `error` event is
      yielded, so already-generated partial content isn't discarded outright; it surfaces as the
      chapter's pending draft the next time the frontend fetches chapter details. If no tokens
      arrived before the failure, this is a no-op and only the `error` event is yielded, as before.
    - On any OTHER unexpected exception inside `stream_generation_task` (e.g. a Redis I/O error,
      not just `LLMRequestError`) — the task's own broad `except Exception` (see
      `llm_routing.tasks._stream_generation`) still publishes an `"error"` entry, which surfaces
      here the same way.
    - If dispatching `stream_generation_task.delay(...)` itself fails (e.g. a Celery/broker
      connection error before the task even starts) or if no terminal `"done"`/`"error"` marker
      ever arrives within `_STREAM_TAIL_TIMEOUT_SECONDS` (a crashed worker, a Redis publish error,
      or the stream key's TTL expiring first) — a single `event: error` is emitted and the
      generator stops, rather than an unhandled exception or an unboundedly hanging SSE
      connection/coroutine.
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
        chapter_summaries=await _accumulated_chapter_summaries(db, project_id, exclude_chapter_id=chapter_id),
        rag_excerpts=rag_excerpts,
        user_message=instruction,
    )
    client = DeepSeekClient()
    title_task = _maybe_start_title_generation(client, project, instruction)

    async def event_stream() -> AsyncIterator[str]:
        chunks: list[str] = []
        task_id = uuid.uuid4().hex
        stream_key = f"generation:{task_id}"
        try:
            try:
                # `stream_generation_task`'s body calls `asyncio.run(...)` internally (ADR-0013
                # addendum point 3); under `task_always_eager=True`, `.delay()` alone runs that
                # entire body synchronously in the calling thread, so `.delay()` — not just a
                # paired `.get()`, since this endpoint never calls `.get()` on this task at all —
                # must run in a separate thread via `asyncio.to_thread` to avoid colliding with
                # this coroutine's own already-running event loop (ADR-0013 addendum's caller-side
                # corollary).
                await asyncio.to_thread(stream_generation_task.delay, task_id, "heavy", messages)
            except Exception as exc:  # noqa: BLE001 -- a broker-level failure (e.g. Celery/Redis
                # connection error) before the task even starts must still surface as a graceful
                # `error` SSE event, not an unhandled exception killing the generator mid-stream
                # with a dropped connection.
                yield _sse_event("error", json.dumps({"detail": str(exc)}))
                return

            redis_client = redis_asyncio.Redis.from_url(_REDIS_URL, decode_responses=True)
            error_detail: str | None = None
            timed_out = False
            read_failed = False
            tail_deadline = time.monotonic() + _STREAM_TAIL_TIMEOUT_SECONDS
            try:
                last_id = "0"
                response = await redis_client.xread(
                    {stream_key: last_id}, count=_STREAM_CATCHUP_COUNT
                )
                entries = response[0][1] if response else []
                sse_events, done, error_detail, seen_id = _process_stream_entries(entries, chunks)
                for sse_event in sse_events:
                    yield sse_event
                if seen_id is not None:
                    last_id = seen_id

                while not done:
                    if time.monotonic() >= tail_deadline:
                        timed_out = True
                        break
                    response = await redis_client.xread(
                        {stream_key: last_id}, block=_STREAM_READ_BLOCK_MS
                    )
                    entries = response[0][1] if response else []
                    if not entries:
                        continue
                    sse_events, done, error_detail, seen_id = _process_stream_entries(
                        entries, chunks
                    )
                    for sse_event in sse_events:
                        yield sse_event
                    if seen_id is not None:
                        last_id = seen_id
            except Exception as exc:  # noqa: BLE001 -- a Redis I/O error on the ENDPOINT's own
                # read connection (distinct from a failure inside the worker task, already handled
                # by `stream_generation_task`'s own broad `except Exception`) must still surface as
                # a graceful `error` SSE event rather than propagating unhandled and silently
                # truncating/dropping the SSE response mid-stream.
                read_failed = True
                error_detail = str(exc)
            finally:
                await redis_client.aclose()

            if read_failed:
                yield _sse_event("error", json.dumps({"detail": error_detail}))
                return

            if timed_out:
                # No terminal marker arrived within `_STREAM_TAIL_TIMEOUT_SECONDS` — surface a
                # clear, graceful `error` event rather than hanging this SSE connection/coroutine
                # open forever (see that constant's docstring for the failure modes this guards
                # against: a crashed worker, a Redis publish error, or the stream key's TTL
                # expiring before its terminal marker ever arrived).
                yield _sse_event(
                    "error",
                    json.dumps({"detail": "Generation timed out waiting for a response."}),
                )
                return

            if error_detail is not None:
                if chunks:
                    # `stream_generation_task` failed partway through (an "error" entry, not a
                    # read/timeout failure on this endpoint's own side) after already streaming
                    # some real, already-generated tokens — persist them as a draft, raw and
                    # un-humanized/un-prechecked, rather than discarding them outright. See the
                    # docstring above for why: the generation itself failed, so there is nothing
                    # more to do with the partial text than save it as-is.
                    await create_draft_version(db, chapter_id, content="".join(chunks))
                yield _sse_event("error", json.dumps({"detail": error_detail}))
                return

            content = "".join(chunks)

            def _run_humanize() -> str:
                return humanize_text_task.delay(content).get(
                    timeout=_HUMANIZE_TASK_TIMEOUT_SECONDS
                )

            try:
                # Humanization now runs on a Celery worker (ADR-0013, TASK-E17-4) via
                # `humanizer.tasks.humanize_text_task`, matching `_humanize_and_precheck`'s
                # non-streaming treatment of the same call (see that function's docstring for why
                # `.delay()` and `.get()` both run inside one `asyncio.to_thread`). Both
                # `HumanizationError`, `LLMRequestError`, and `CeleryTimeoutError` (this
                # handler's own wait timing out — see `_HUMANIZE_TASK_TIMEOUT_SECONDS`'s comment)
                # all fail open to the raw streamed `content` here, exactly like
                # `_humanize_and_precheck` does for the non-streaming endpoint (see that
                # function's docstring): humanization is cosmetic, not correctness-critical, so a
                # failure of any of these kinds must never discard the already-streamed,
                # already-generated draft.
                humanized_content = await asyncio.to_thread(_run_humanize)
            except (LLMRequestError, HumanizationError, CeleryTimeoutError):
                humanized_content = content

            precheck = await _run_precheck_with_fallback(humanized_content, rag_excerpts)
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

    After a successful accept (ADR-0003 addendum, follow-up to TASK-E03-2/E17), dispatches
    accept-time chapter summarization (`_summarize_and_persist_chapter`) with the just-accepted
    version's content, so later generation calls' `assemble_prompt` has a real per-chapter summary
    to include in its cache-friendly prefix. This is a pure side effect: the response contract is
    unchanged (same `ChapterVersion`, same status code) whether summarization succeeds or fails.
    """
    try:
        version = await accept_draft_version(db, version_id)
    except ValueError as exc:
        message = str(exc)
        if "no version" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from exc

    await _summarize_and_persist_chapter(db, version.chapter_id, version.content)
    return version
