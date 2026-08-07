"""Standalone anti-plagiarism / AI-fingerprint check endpoint (TASK-E07-3).

`POST /plagiarism/check` exposes `plagiarism.precheck.run_precheck` as its own ad-hoc,
stateless HTTP endpoint, independent of the project/chapter generation pipeline
(`projects.router`'s generate endpoint already calls `run_precheck` internally on
LLM-generated drafts). This endpoint lets a user paste arbitrary already-written text — their
own work, not something this platform generated — and get the same heuristic scoring, with no
project/chapter association and nothing persisted.
"""

import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from diploma_backend.plagiarism.extract import PlagiarismFileParseError, extract_text
from diploma_backend.plagiarism.precheck import PlagiarismCheckResult, SentenceFlag
from diploma_backend.plagiarism.tasks import run_precheck_task

router = APIRouter(prefix="/plagiarism", tags=["plagiarism"])

# Local heuristic scoring only (no network calls) — generous timeout purely as a worker-hang
# safety net, matching `projects.router._TOC_PARSE_TASK_TIMEOUT_SECONDS`'s rationale.
_PRECHECK_TASK_TIMEOUT_SECONDS = 60.0


class PlagiarismCheckRequest(BaseModel):
    """Body for `POST /plagiarism/check`.

    `source_excerpts` defaults to empty since most ad-hoc checks have no specific source
    material to compare against; `score_plagiarism_risk` already returns `0.0` in that case, so
    no special-casing is needed here.
    """

    text: str = Field(min_length=1)
    source_excerpts: list[str] = []


class SentenceFlagResponse(BaseModel):
    """Pydantic mirror of `plagiarism.precheck.SentenceFlag`; see that dataclass for field
    meaning."""

    text: str
    plagiarism_score: float
    is_plagiarized: bool
    is_ai_like: bool

    @classmethod
    def from_flag(cls, flag: SentenceFlag) -> "SentenceFlagResponse":
        return cls(
            text=flag.text,
            plagiarism_score=flag.plagiarism_score,
            is_plagiarized=flag.is_plagiarized,
            is_ai_like=flag.is_ai_like,
        )


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
    originality_score: float
    sentence_flags: list[SentenceFlagResponse]

    @classmethod
    def from_result(cls, result: PlagiarismCheckResult) -> "PlagiarismCheckResultResponse":
        return cls(
            plagiarism_score=result.plagiarism_score,
            ai_fingerprint_score=result.ai_fingerprint_score,
            flagged=result.flagged,
            reasons=result.reasons,
            originality_score=result.originality_score,
            sentence_flags=[
                SentenceFlagResponse.from_flag(flag) for flag in result.sentence_flags
            ],
        )

    @classmethod
    def from_task_result(cls, result: dict) -> "PlagiarismCheckResultResponse":
        """Build this response from `plagiarism.tasks.run_precheck_task`'s plain-dict return.

        `run_precheck_task`'s `dataclasses.asdict` conversion of `PlagiarismCheckResult` (see that
        task's docstring) yields a dict whose keys/shape already line up exactly with this
        model's fields, including the nested `sentence_flags` dicts matching
        `SentenceFlagResponse`'s fields — so `model_validate` needs no extra field mapping, unlike
        `from_result` above (which reads attributes off the dataclass directly).
        """
        return cls.model_validate(result)


@router.post("/check", response_model=PlagiarismCheckResultResponse)
async def check_plagiarism(request: PlagiarismCheckRequest) -> PlagiarismCheckResultResponse:
    """Run `run_precheck` on arbitrary user-supplied `text`, with no project/chapter context.

    Stateless and unauthenticated: nothing is persisted, and there is no LLM call here (only a
    couple of local heuristic function calls), so this carries none of the cost/abuse concerns
    that motivate auth/rate-limiting on the generation endpoint.

    Scoring now runs on a Celery worker via `plagiarism.tasks.run_precheck_task` (ADR-0013,
    TASK-E17-4) instead of inline on this process. Per ADR-0013's addendum point 1, the HTTP
    contract is unchanged: this handler still `await`s the task's result (via
    `asyncio.to_thread`, since `AsyncResult.get()` blocks) before responding, with the same
    response shape/status as before. `run_precheck` never raises (see that task's docstring), so
    there is no failure path to translate here, unlike `upload_toc_endpoint`'s `TocParseError`
    handling.
    """
    async_result = run_precheck_task.delay(request.text, request.source_excerpts)
    result = await asyncio.to_thread(async_result.get, timeout=_PRECHECK_TASK_TIMEOUT_SECONDS)
    return PlagiarismCheckResultResponse.from_task_result(result)


@router.post("/check-file", response_model=PlagiarismCheckResultResponse)
async def check_plagiarism_file(
    file: UploadFile = File(...),
) -> PlagiarismCheckResultResponse:
    """Run `run_precheck` on text extracted from an uploaded `.docx`/`.pdf` file.

    Multipart upload counterpart to `/check` for users who have a document rather than pasted
    text. Does not accept `source_excerpts` (unlike `/check`'s JSON body) — this endpoint is for
    a quick self-check of an already-written file with no source material to compare against;
    `run_precheck`/`score_plagiarism_risk` already handle an empty `source_excerpts` list
    correctly (score `0.0`), so this is a deliberate simplification, not a limitation that needs
    a `Form` field workaround. Raises `HTTPException(400)` if `file` isn't a parseable
    `.docx`/`.pdf` (matches `formatting.router`'s upload error-translation pattern).

    Text extraction stays inline on this process: `extract_text` is cheap, in-memory
    `.docx`/`.pdf` parsing comparable in cost/shape to `toc.parser.parse_toc` (which likewise
    stays inline, only its result is fed to a Celery task), so only the scoring step below moves
    to `plagiarism.tasks.run_precheck_task` (ADR-0013, TASK-E17-4) — the same
    `.delay()`-then-`asyncio.to_thread(async_result.get, ...)` pattern
    `upload_toc_endpoint` uses.
    """
    content = await file.read()

    try:
        text = extract_text(file.filename or "", content)
    except PlagiarismFileParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    async_result = run_precheck_task.delay(text, [])
    result = await asyncio.to_thread(async_result.get, timeout=_PRECHECK_TASK_TIMEOUT_SECONDS)
    return PlagiarismCheckResultResponse.from_task_result(result)
