"""Tests for TASK-E03-3 (retry/backoff layer on top of `DeepSeekClient`).

HTTP calls are mocked with `respx`, matching `test_llm_routing.py`'s pattern. `asyncio.sleep` is
monkeypatched to a no-op recorder so backoff delays are asserted without real waiting.
"""

import httpx
import pytest
import respx

from diploma_backend.llm_routing import DeepSeekClient, LLMRequestError
from diploma_backend.llm_routing.retry import generate_with_retry

_CHAT_URL = "https://api.deepseek.com/chat/completions"


def _client() -> DeepSeekClient:
    return DeepSeekClient(
        api_key="test-key", fast_model="deepseek-v4-flash", heavy_model="deepseek-v4-pro"
    )


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


def _fail_response() -> httpx.Response:
    return httpx.Response(500, json={"error": "boom"})


@pytest.fixture
def fake_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("diploma_backend.llm_routing.retry.asyncio.sleep", _fake_sleep)
    return delays


@respx.mock
async def test_succeeds_on_first_attempt_no_retry(fake_sleep: list[float]) -> None:
    respx.post(_CHAT_URL).mock(return_value=_success_response("first try"))

    result = await generate_with_retry(_client(), "fast", [{"role": "user", "content": "hi"}])

    assert result == "first try"
    assert fake_sleep == []


@respx.mock
async def test_fails_once_then_succeeds(fake_sleep: list[float]) -> None:
    respx.post(_CHAT_URL).mock(
        side_effect=[_fail_response(), _success_response("second try")]
    )

    result = await generate_with_retry(_client(), "fast", [{"role": "user", "content": "hi"}])

    assert result == "second try"
    assert fake_sleep == [1.0]


@respx.mock
async def test_fails_all_attempts_raises_llm_request_error(fake_sleep: list[float]) -> None:
    respx.post(_CHAT_URL).mock(return_value=_fail_response())

    with pytest.raises(LLMRequestError):
        await generate_with_retry(
            _client(), "fast", [{"role": "user", "content": "hi"}], max_attempts=3
        )

    assert len(respx.calls) == 3
    assert fake_sleep == [1.0, 2.0]


@respx.mock
async def test_backoff_delay_grows_between_attempts(fake_sleep: list[float]) -> None:
    respx.post(_CHAT_URL).mock(return_value=_fail_response())

    with pytest.raises(LLMRequestError):
        await generate_with_retry(
            _client(),
            "fast",
            [{"role": "user", "content": "hi"}],
            max_attempts=4,
            base_delay_seconds=1.0,
        )

    assert fake_sleep == [1.0, 2.0, 4.0]
