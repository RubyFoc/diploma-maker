"""Tests for `llm_routing.tasks.generate_with_retry_task`/`stream_generation_task` (ADR-0013,
TASK-E17-2/E17-3).

HTTP calls are mocked with `respx`, matching `test_retry.py`'s pattern. Per ADR-0013 addendum
point 4, these tests call `.delay()` from plain sync test functions (never from `async def` test
code) so the task body's own internal `asyncio.run()` never collides with a pytest-asyncio event
loop already running the test.

`stream_generation_task`'s tests exercise its Redis Stream side effects directly against a real
local Redis (`REDIS_URL`, default `redis://localhost:6379/0` — the same instance the dev
`docker-compose.yml` provides and this repo's CI now provisions for the backend test job) rather
than through the SSE endpoint, since asserting the exact `XADD` fields/ordering here is more
direct than parsing SSE frames for the same assertions (`test_projects_stream.py` covers the
endpoint-level, end-to-end contract).
"""

import asyncio
import json
import uuid

import httpx
import pytest
import redis as redis_sync
import respx

from diploma_backend.llm_routing.client import LLMRequestError
from diploma_backend.llm_routing.tasks import (
    _REDIS_URL,
    _stream_generation,
    generate_with_retry_task,
    stream_generation_task,
)
from diploma_backend.worker.celery_app import celery_app


def _redis_reachable() -> bool:
    """Whether `_REDIS_URL` answers a `PING` — guards `stream_generation_task`'s tests (there is
    no in-memory Redis fake in this codebase's dependencies, unlike Mongo's `mongomock-motor`; see
    module docstring) so a developer/CI environment without Redis skips these specific tests
    instead of erroring on every one of them with an unhelpful connection-refused traceback."""
    try:
        redis_sync.Redis.from_url(_REDIS_URL, socket_connect_timeout=1).ping()
    except redis_sync.exceptions.RedisError:
        return False
    return True


requires_redis = pytest.mark.skipif(
    not _redis_reachable(), reason="stream_generation_task tests require a real Redis at REDIS_URL"
)

_CHAT_URL = "https://api.deepseek.com/chat/completions"


def _success_response(content: str = "hello") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def test_task_always_eager_is_active() -> None:
    assert celery_app.conf.task_always_eager is True
    assert celery_app.conf.task_eager_propagates is True


@respx.mock
def test_delay_runs_task_and_returns_reply() -> None:
    respx.post(_CHAT_URL).mock(return_value=_success_response("humanized reply"))

    async_result = generate_with_retry_task.delay(
        "fast",
        [{"role": "user", "content": "hi"}],
        api_key="test-key",
        fast_model="deepseek-v4-flash",
        heavy_model="deepseek-v4-pro",
    )

    assert async_result.get() == "humanized reply"


@respx.mock
def test_exhausted_retries_propagate_as_real_exception() -> None:
    respx.post(_CHAT_URL).mock(return_value=httpx.Response(500, json={"error": "boom"}))

    with pytest.raises(LLMRequestError):
        generate_with_retry_task.delay(
            "fast",
            [{"role": "user", "content": "hi"}],
            max_attempts=1,
            api_key="test-key",
        )


def _stream_body(deltas: list[str]) -> bytes:
    """Same OpenAI-compatible SSE stream body shape as `test_projects_stream.py`'s helper of the
    same name."""
    lines = [
        f'data: {{"choices":[{{"delta":{{"content":{json.dumps(d)}}}}}]}}\n\n' for d in deltas
    ]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


@pytest.fixture
def redis_client():
    """A real `redis.Redis` connection, cleaned up after the test — skipped module-wide via
    `requires_redis` if `_REDIS_URL` isn't reachable (see module docstring)."""
    conn = redis_sync.Redis.from_url(_REDIS_URL, decode_responses=True)
    try:
        yield conn
    finally:
        conn.close()


@requires_redis
@respx.mock
def test_stream_generation_task_publishes_tokens_and_done(redis_client) -> None:
    respx.post(_CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_stream_body(["Draft ", "body."]),
        )
    )
    task_id = uuid.uuid4().hex
    stream_key = f"generation:{task_id}"

    result = stream_generation_task.delay(task_id, "heavy", [{"role": "user", "content": "hi"}])

    assert result.get() == "Draft body."
    entries = redis_client.xrange(stream_key)
    assert [fields["type"] for _id, fields in entries] == ["token", "token", "done"]
    assert [fields.get("data") for _id, fields in entries[:2]] == ["Draft ", "body."]
    ttl = redis_client.ttl(stream_key)
    assert 0 < ttl <= 300

    redis_client.delete(stream_key)


@requires_redis
@respx.mock
def test_stream_generation_task_publishes_error_on_llm_failure(redis_client) -> None:
    respx.post(_CHAT_URL).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    task_id = uuid.uuid4().hex
    stream_key = f"generation:{task_id}"

    result = stream_generation_task.delay(task_id, "heavy", [{"role": "user", "content": "hi"}])

    assert result.get() == ""
    entries = redis_client.xrange(stream_key)
    assert len(entries) == 1
    _entry_id, fields = entries[0]
    assert fields["type"] == "error"
    assert fields["detail"]
    ttl = redis_client.ttl(stream_key)
    assert 0 < ttl <= 300

    redis_client.delete(stream_key)


@requires_redis
@respx.mock
def test_stream_generation_task_survives_thousands_of_chunks_without_truncation(
    redis_client,
) -> None:
    """Regression test for the `_STREAM_MAXLEN` truncation bug: a full-chapter generation can
    realistically produce well over a thousand small SSE deltas (one per DeepSeek stream line),
    and every one of them must survive the round trip through the Redis Stream — the earliest
    chunks must never be silently evicted by `MAXLEN` trimming before this task's own `.get()`,
    let alone before a real SSE subscriber's tail loop reads them."""
    deltas = [f"tok{i} " for i in range(1500)]
    respx.post(_CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_stream_body(deltas),
        )
    )
    task_id = uuid.uuid4().hex
    stream_key = f"generation:{task_id}"
    expected = "".join(deltas)

    result = stream_generation_task.delay(task_id, "heavy", [{"role": "user", "content": "hi"}])

    assert result.get() == expected
    entries = redis_client.xrange(stream_key)
    assert len(entries) == len(deltas) + 1
    token_entries = entries[:-1]
    assert "".join(fields["data"] for _id, fields in token_entries) == expected
    assert entries[-1][1]["type"] == "done"

    redis_client.delete(stream_key)


@requires_redis
def test_stream_generation_publishes_error_marker_for_non_llm_request_error(redis_client) -> None:
    """`_stream_generation`'s exception handling must not be limited to `LLMRequestError`: any
    other unexpected exception raised while streaming (e.g. a Redis I/O error, or here a stand-in
    `RuntimeError` from a misbehaving client) must still result in a terminal `"error"` marker
    being published, so a subscriber's tail loop never strands waiting for a marker that will
    never arrive."""

    class _RaisingClient:
        async def generate_stream(self, tier, messages, *, temperature=None, max_tokens=None):
            yield "partial "
            raise RuntimeError("unexpected boom")

    task_id = uuid.uuid4().hex
    stream_key = f"generation:{task_id}"

    result = asyncio.run(
        _stream_generation(
            _RaisingClient(),
            redis_client,
            stream_key,
            "heavy",
            [{"role": "user", "content": "hi"}],
        )
    )

    assert result == ""
    entries = redis_client.xrange(stream_key)
    assert [fields["type"] for _id, fields in entries] == ["token", "error"]
    assert "unexpected boom" in entries[-1][1]["detail"]

    redis_client.delete(stream_key)
