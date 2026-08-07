"""Celery task wrapping `llm_routing.retry.generate_with_retry` (ADR-0013, TASK-E17-2).

The task body is a plain sync `def` that drives the wrapped async call via `asyncio.run(...)`
(ADR-0013 addendum point 3) — safe because a Celery worker process runs one task at a time, so
there is no risk of `asyncio.run` colliding with another already-running event loop in that
process.

Task arguments are plain JSON-serializable values (`tier`, `messages`, plus the DeepSeek client's
constructor knobs), not a `DeepSeekClient` instance, since Celery task arguments must survive
broker serialization; the task constructs its own `DeepSeekClient` per call. `api_key`/
`fast_model`/`heavy_model` default to `None`, in which case `DeepSeekClient` falls back to the
`DEEPSEEK_API_KEY`/`DEEPSEEK_FAST_MODEL`/`DEEPSEEK_HEAVY_MODEL` environment variables, same as
every other caller of `DeepSeekClient` in this codebase.

No Celery-level `autoretry_for` is set here (ADR-0013 addendum point 5) — `generate_with_retry`
already owns retry/backoff for `LLMRequestError`; a failure that survives its retries propagates
out of this task unchanged (`task_eager_propagates=True` in tests, per `worker.celery_app`).
"""

import asyncio

from diploma_backend.llm_routing.client import DeepSeekClient, Message, Tier
from diploma_backend.llm_routing.retry import generate_with_retry
from diploma_backend.worker.celery_app import celery_app


@celery_app.task(name="llm_routing.generate_with_retry")
def generate_with_retry_task(
    tier: Tier,
    messages: list[Message],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    temperature: float | None = None,
    max_tokens: int | None = None,
    api_key: str | None = None,
    fast_model: str | None = None,
    heavy_model: str | None = None,
) -> str:
    """Run `generate_with_retry` in a worker process and return the assistant's reply text.

    Builds a fresh `DeepSeekClient(api_key, fast_model, heavy_model)` per call (see module
    docstring for why a client instance isn't passed as a task argument), then runs
    `generate_with_retry` via `asyncio.run`. Returns the same `str` `generate_with_retry` returns
    — already a plain, result-backend-serializable value, no conversion needed. Raises
    `LLMRequestError` unchanged if every retry attempt fails.
    """
    client = DeepSeekClient(api_key=api_key, fast_model=fast_model, heavy_model=heavy_model)
    return asyncio.run(
        generate_with_retry(
            client,
            tier,
            messages,
            max_attempts=max_attempts,
            base_delay_seconds=base_delay_seconds,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    )
