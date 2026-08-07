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

`stream_generation_task` (ADR-0013 addendum point 2, TASK-E17-3) is the progress-buffering
counterpart used by `generate_chapter_draft_stream_endpoint`'s SSE path: rather than returning its
result through Celery's result backend, it publishes each token (plus a terminal `done`/`error`
marker) to a Redis Stream keyed `generation:{task_id}`, which the endpoint tails via `XREAD`
instead of `.get()`-ing this task's return value. It lives alongside `generate_with_retry_task`
rather than in a separate module because both wrap the same `DeepSeekClient`/`llm_routing`
concern; `sources`/`humanizer`/`formatting`/`feedback`/`billing` stay untouched by this change.

`summarize_chapter_task` (ADR-0003 addendum, follow-up to TASK-E03-2/E17) wraps
`llm_routing.summary.summarize_chapter` the same way, for the same "same `DeepSeek`/`llm_routing`
concern" reasoning — dispatched from `projects.router.accept_draft_version_endpoint` right after
a draft is accepted, so `assemble_prompt`'s `chapter_summaries` prefix has real content to work
with on later generation calls.
"""

import asyncio
import os

import redis

from diploma_backend.llm_routing.client import DeepSeekClient, LLMRequestError, Message, Tier
from diploma_backend.llm_routing.retry import generate_with_retry
from diploma_backend.llm_routing.summary import summarize_chapter
from diploma_backend.worker.celery_app import celery_app

# Read the same way `worker.celery_app` reads `REDIS_URL`: a plain `os.environ.get` with the same
# localhost-friendly default, so this task works against a local dev/test Redis with no `.env`.
# Deliberately duplicated here rather than importing `worker.celery_app`'s private constant: two
# lines is cheaper than introducing a shared config module for one env var read in two places.
_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Matches ADR-0013 addendum point 2's "last N events" framing: caps each `generation:{task_id}`
# stream at (approximately, via `MAXLEN ~`) this many entries so a pathologically long generation
# can't grow its stream key unboundedly.
#
# Deliberately NOT applied on every `XADD` in `_stream_generation`'s hot per-chunk loop (that was
# the original, buggy shape): `DeepSeekClient.generate_stream` yields one small delta per SSE
# line DeepSeek sends, so a full chapter draft realistically produces well over a thousand chunks
# — trimming continuously during the hot loop would evict the EARLIEST tokens (Redis's `MAXLEN ~`
# trims oldest-first) before `generate_chapter_draft_stream_endpoint`'s tail loop ever reads them,
# silently truncating the opening of the chapter with no error surfaced anywhere. Instead, `_xadd`
# only passes `maxlen=`/`approximate=True` on the terminal (`"done"`/`"error"`) entry — a single,
# one-time trim applied only once every token has already been written, purely as a self-cleaning
# cap on the key's eventual size (on top of `_STREAM_TTL_SECONDS`'s own expiry), never as a
# mid-generation truncation risk. 20000 is comfortably above any realistic single-chapter chunk
# count (with real headroom, not equal to `projects.router._STREAM_CATCHUP_COUNT` or any other
# read-side constant), so this guarantees no token loss for a real generation.
_STREAM_MAXLEN = 20000

# Self-cleaning safety net (ADR-0013 addendum point 2): a stream key expires 300s after its first
# entry regardless of whether the SSE endpoint ever attaches/finishes reading it.
_STREAM_TTL_SECONDS = 300


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


@celery_app.task(name="llm_routing.summarize_chapter")
def summarize_chapter_task(
    chapter_content: str,
    *,
    api_key: str | None = None,
    fast_model: str | None = None,
    heavy_model: str | None = None,
) -> str:
    """Run `summarize_chapter` in a worker process and return the compacted summary text
    (accept-time summarization, `projects.router.accept_draft_version_endpoint`, TASK-E03-2
    wiring).

    Builds a fresh `DeepSeekClient(api_key, fast_model, heavy_model)` per call (see module
    docstring for why a client instance isn't passed as a task argument), then runs
    `summarize_chapter` via `asyncio.run` — `summarize_chapter` is itself `async def` but, unlike
    `generate_with_retry`/`humanize_text`, has no internal retry of its own (it calls
    `client.generate_fast` directly), so no Celery-level `autoretry_for` is warranted here either
    (ADR-0013 addendum point 5's reasoning applies the same way: this is a best-effort cost
    optimization, not a correctness-critical path — the caller is expected to fail open on any
    exception this task raises, never block on it). Raises `LLMRequestError` unchanged on any
    call failure, matching `generate_with_retry_task`'s propagation contract.
    """
    client = DeepSeekClient(api_key=api_key, fast_model=fast_model, heavy_model=heavy_model)
    return asyncio.run(summarize_chapter(client, chapter_content))


async def _stream_generation(
    client: DeepSeekClient, redis_client: redis.Redis, stream_key: str, tier: Tier,
    messages: list[Message],
) -> str:
    """Drive `client.generate_stream`, publishing each chunk plus a terminal marker to `stream_key`.

    Sets `stream_key`'s TTL right after the first `XADD` (whichever event that turns out to be —
    the first token, or an immediate `done`/`error` for a zero-chunk/failed generation), so the
    key self-expires (ADR-0013 addendum point 2) even if the SSE endpoint never attaches. Returns
    the concatenated chunk text on success (result-backend introspection only — the endpoint reads
    the Stream, not this return value) or `""` if an exception was caught and published as an
    `error` event instead of propagating, so the Celery task itself never fails: an unhandled
    exception here would skip the terminal `XADD`, leaving a late SSE subscriber's tail loop
    blocked until its own read timeout instead of seeing a clean `error` event.

    Catches broad `Exception`, not just `LLMRequestError`: a Redis I/O error raised by `_xadd`/
    `redis_client.expire` itself, or any other unexpected error, must still result in a terminal
    `error` marker being published — see `_STREAM_MAXLEN`'s docstring and this function's module
    for why a stranded stream (no terminal marker ever written) compounds into an unboundedly
    hanging SSE tail loop on the endpoint side. `LLMRequestError`'s `str(exc)` is generally a safe,
    user-facing message (see `llm_routing.client`); other exception types' `str(exc)` may be more
    opaque, but publishing SOME detail is still preferable to no terminal marker at all.
    """
    chunks: list[str] = []
    ttl_set = False

    def _xadd(fields: dict[str, str], *, is_terminal: bool = False) -> None:
        nonlocal ttl_set
        if is_terminal:
            redis_client.xadd(stream_key, fields, maxlen=_STREAM_MAXLEN, approximate=True)
        else:
            redis_client.xadd(stream_key, fields)
        if not ttl_set:
            redis_client.expire(stream_key, _STREAM_TTL_SECONDS)
            ttl_set = True

    try:
        async for chunk in client.generate_stream(tier, messages):
            chunks.append(chunk)
            _xadd({"type": "token", "data": chunk})
    except LLMRequestError as exc:
        _xadd({"type": "error", "detail": str(exc)}, is_terminal=True)
        return ""
    except Exception as exc:  # noqa: BLE001 -- must still publish a terminal marker, see docstring
        _xadd({"type": "error", "detail": str(exc)}, is_terminal=True)
        return ""

    _xadd({"type": "done"}, is_terminal=True)
    return "".join(chunks)


@celery_app.task(name="llm_routing.stream_generation")
def stream_generation_task(task_id: str, tier: Tier, messages: list[Message]) -> str:
    """Stream a heavy-tier generation, publishing progress to Redis Stream `generation:{task_id}`
    (ADR-0013 addendum point 2, TASK-E17-3).

    Used by `generate_chapter_draft_stream_endpoint`'s SSE path in place of the previously-inline
    `client.generate_stream("heavy", messages)` call: moving the DeepSeek call itself off the API
    process's event loop and into a worker means a stuck/slow generation call no longer ties up an
    API worker thread/coroutine for the call's full duration, matching ADR-0013's stated goal for
    every other task in this epic.

    Builds a fresh `DeepSeekClient()` per call (same reconstruction pattern as
    `generate_with_retry_task` — see that task's docstring) and a fresh sync `redis.Redis` client
    per call (a Celery worker process runs one task at a time, so there is no benefit to pooling a
    connection across tasks here). Publishes, in order: one `{"type": "token", "data": chunk}`
    entry per chunk yielded by `generate_stream`, then either `{"type": "done"}` on success or
    `{"type": "error", "detail": str(exc)}` if `LLMRequestError` — or any other unexpected
    exception — is raised — caught here (via `_stream_generation`'s broad `except Exception`)
    rather than left to propagate, precisely so that terminal marker still gets published (see
    `_stream_generation`'s docstring for why an unhandled exception would strand a late
    subscriber).

    Returns the concatenated generated text (or `""` on any caught exception) for result-
    backend introspection/debugging only; `generate_chapter_draft_stream_endpoint` never `.get()`s
    this task's result — it tails the Stream instead, which is why this task's caller wraps only
    `.delay()` (not `.delay()` + `.get()`) in `asyncio.to_thread` (ADR-0013 addendum's caller-side
    corollary).
    """
    client = DeepSeekClient()
    redis_client = redis.Redis.from_url(_REDIS_URL, decode_responses=True)
    stream_key = f"generation:{task_id}"
    try:
        return asyncio.run(_stream_generation(client, redis_client, stream_key, tier, messages))
    finally:
        redis_client.close()
