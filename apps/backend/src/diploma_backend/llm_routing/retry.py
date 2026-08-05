"""Retry/backoff policy for `DeepSeekClient` calls (ADR-0003, TASK-E03-3).

Wraps `DeepSeekClient.generate` (TASK-E03-1) without modifying it — the client itself stays
single-attempt and deterministic, since other callers/tests rely on that. This module adds a
retry layer on top, the same way `summary.py` (TASK-E03-2) composes with the client.

Retry scope decision: every `LLMRequestError` is retried uniformly, regardless of cause (network
error, timeout, non-2xx status, or malformed response body). `DeepSeekClient.generate` collapses
all of those into the same exception type and does not currently attach the underlying HTTP
status code, so there is no reliable signal here to distinguish a transient failure (e.g. a 503)
from a permanent one (e.g. a 401). Retrying a permanent failure wastes `max_attempts - 1` calls,
but treating everything as transient is the simplest correct MVP behavior given the information
available. A future improvement could have `DeepSeekClient` attach the status code to
`LLMRequestError` so this layer can skip retrying non-retryable statuses (e.g. 4xx other than
429) — out of scope here, and changing the client's exception shape could break other callers.
"""

import asyncio

from diploma_backend.llm_routing.client import DeepSeekClient, LLMRequestError, Message, Tier


async def generate_with_retry(
    client: DeepSeekClient,
    tier: Tier,
    messages: list[Message],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Call `client.generate`, retrying on `LLMRequestError` with exponential backoff.

    Inputs: same as `DeepSeekClient.generate` (`tier`, `messages`, `temperature`, `max_tokens`),
    plus `max_attempts` (total attempts, including the first — so `max_attempts=3` allows up to 2
    retries after an initial failure) and `base_delay_seconds` (backoff base).
    Backoff: before retry attempt `n` (1-indexed, i.e. the delay before the 2nd, 3rd, ... call),
    sleeps `base_delay_seconds * 2 ** (n - 1)` seconds via `asyncio.sleep` — standard exponential
    backoff, so with defaults the delays are 1.0s, then 2.0s.
    Output: the assistant's reply text, as returned by the first successful attempt.
    Raises the last `LLMRequestError` encountered if every attempt fails. See module docstring
    for why all `LLMRequestError`s are retried uniformly.
    """
    last_error: LLMRequestError | None = None

    for attempt in range(max_attempts):
        try:
            return await client.generate(
                tier, messages, temperature=temperature, max_tokens=max_tokens
            )
        except LLMRequestError as exc:
            last_error = exc
            if attempt < max_attempts - 1:
                await asyncio.sleep(base_delay_seconds * 2**attempt)

    assert last_error is not None
    raise last_error
