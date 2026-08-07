"""Celery task wrapping `sources.search.search_sources` (ADR-0013, TASK-E17-2).

`search_sources` is async (it drives `httpx.AsyncClient` calls), so the task body is a plain sync
`def` that runs it via `asyncio.run(...)` (ADR-0013 addendum point 3).
"""

import asyncio
from dataclasses import asdict

from diploma_backend.sources.search import search_sources
from diploma_backend.worker.celery_app import celery_app


@celery_app.task(name="sources.search_sources")
def search_sources_task(
    query: str, *, min_year: int | None = None, limit: int = 10
) -> list[dict]:
    """Run `search_sources` in a worker process and return its results as plain dicts.

    `search_sources` returns a `list[SourceSearchResult]` — a frozen dataclass, not natively
    JSON-serializable by Celery's result backend, so each result is converted via
    `dataclasses.asdict` before returning. Raises `SourceSearchError` unchanged if every attempted
    provider fails.
    """
    results = asyncio.run(search_sources(query, min_year=min_year, limit=limit))
    return [asdict(result) for result in results]
