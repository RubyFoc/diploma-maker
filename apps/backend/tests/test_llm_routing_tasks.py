"""Tests for `llm_routing.tasks.generate_with_retry_task` (ADR-0013, TASK-E17-2).

HTTP calls are mocked with `respx`, matching `test_retry.py`'s pattern. Per ADR-0013 addendum
point 4, these tests call `.delay()` from plain sync test functions (never from `async def` test
code) so the task body's own internal `asyncio.run()` never collides with a pytest-asyncio event
loop already running the test.
"""

import httpx
import pytest
import respx

from diploma_backend.llm_routing.client import LLMRequestError
from diploma_backend.llm_routing.tasks import generate_with_retry_task
from diploma_backend.worker.celery_app import celery_app

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
