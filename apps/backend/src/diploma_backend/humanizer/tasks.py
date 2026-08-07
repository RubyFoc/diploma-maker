"""Celery task wrapping `humanizer.pipeline.humanize_text` (ADR-0013, TASK-E17-2).

`humanize_text` is async (it calls `generate_with_retry`, which is itself async), so the task body
is a plain sync `def` that runs it via `asyncio.run(...)` (ADR-0013 addendum point 3). As with
`llm_routing.tasks`, the `DeepSeekClient` is constructed inside the task from plain, serializable
keyword arguments rather than passed in as an object.

No Celery-level `autoretry_for` is set here (ADR-0013 addendum point 5) — humanization's only
retryable failure mode (`LLMRequestError`) is already retried inside `generate_with_retry`, which
`humanize_text` calls.
"""

import asyncio

from diploma_backend.humanizer.pipeline import humanize_text
from diploma_backend.llm_routing.client import DeepSeekClient
from diploma_backend.worker.celery_app import celery_app


@celery_app.task(name="humanizer.humanize_text")
def humanize_text_task(
    text: str,
    *,
    max_attempts: int = 3,
    api_key: str | None = None,
    fast_model: str | None = None,
    heavy_model: str | None = None,
) -> str:
    """Run `humanize_text` in a worker process and return the humanized text.

    Builds a fresh `DeepSeekClient(api_key, fast_model, heavy_model)` per call (see
    `llm_routing.tasks` for why a client instance isn't passed as a task argument). Returns the
    same `str` `humanize_text` returns — already result-backend-serializable, no conversion
    needed. Raises `LLMRequestError` (retries exhausted) or `HumanizationError` (citation
    placeholder dropped/mangled) unchanged.
    """
    client = DeepSeekClient(api_key=api_key, fast_model=fast_model, heavy_model=heavy_model)
    return asyncio.run(humanize_text(client, text, max_attempts=max_attempts))
