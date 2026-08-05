"""Standalone anti-plagiarism / AI-fingerprint check endpoint (TASK-E07-3).

`POST /plagiarism/check` exposes `plagiarism.precheck.run_precheck` as its own ad-hoc,
stateless HTTP endpoint, independent of the project/chapter generation pipeline
(`projects.router`'s generate endpoint already calls `run_precheck` internally on
LLM-generated drafts). This endpoint lets a user paste arbitrary already-written text — their
own work, not something this platform generated — and get the same heuristic scoring, with no
project/chapter association and nothing persisted.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from diploma_backend.plagiarism.precheck import PlagiarismCheckResult, run_precheck

router = APIRouter(prefix="/plagiarism", tags=["plagiarism"])


class PlagiarismCheckRequest(BaseModel):
    """Body for `POST /plagiarism/check`.

    `source_excerpts` defaults to empty since most ad-hoc checks have no specific source
    material to compare against; `score_plagiarism_risk` already returns `0.0` in that case, so
    no special-casing is needed here.
    """

    text: str = Field(min_length=1)
    source_excerpts: list[str] = []


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


@router.post("/check", response_model=PlagiarismCheckResultResponse)
async def check_plagiarism(request: PlagiarismCheckRequest) -> PlagiarismCheckResultResponse:
    """Run `run_precheck` on arbitrary user-supplied `text`, with no project/chapter context.

    Stateless and unauthenticated: nothing is persisted, and there is no LLM call here (only a
    couple of local heuristic function calls), so this carries none of the cost/abuse concerns
    that motivate auth/rate-limiting on the generation endpoint.
    """
    result = run_precheck(request.text, request.source_excerpts)
    return PlagiarismCheckResultResponse.from_result(result)
