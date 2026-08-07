"""Celery task wrapping `plagiarism.precheck.run_precheck` (ADR-0013, TASK-E17-4).

`run_precheck` is synchronous and does no I/O — both heuristics it composes
(`score_plagiarism_risk`, `score_ai_fingerprint`) are pure local text processing, no network/DB
calls — so this task calls it directly, no `asyncio.run` needed (ADR-0013 addendum point 3),
matching `toc.tasks.parse_toc_task`'s treatment of `toc.parser.parse_toc`.
"""

from dataclasses import asdict

from diploma_backend.plagiarism.precheck import run_precheck
from diploma_backend.worker.celery_app import celery_app


@celery_app.task(name="plagiarism.run_precheck")
def run_precheck_task(text: str, source_excerpts: list[str]) -> dict:
    """Run `run_precheck` in a worker process and return its result as a plain dict.

    `run_precheck` returns a `PlagiarismCheckResult` — a frozen dataclass (itself nesting a list
    of `SentenceFlag` dataclasses in `sentence_flags`) that Celery's default JSON result backend
    cannot serialize natively, so it is converted via `dataclasses.asdict` before returning
    (matches `sources.tasks.search_sources_task`'s treatment of its own dataclass return value;
    `asdict` recurses into the nested `sentence_flags` dataclasses too). The resulting dict's keys
    line up exactly with `plagiarism.router.PlagiarismCheckResultResponse`'s fields, so a caller
    can build that response model directly from it (e.g. via `model_validate`).

    `run_precheck` never raises today (no PRD-specified vendor/threshold input can be malformed at
    this call site — thresholds are keyword-only with fixed defaults, and `text`/`source_excerpts`
    are already-validated strings), so this task has no failure path to preserve.
    """
    result = run_precheck(text, source_excerpts)
    return asdict(result)
