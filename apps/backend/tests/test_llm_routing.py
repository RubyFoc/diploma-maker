"""Tests for TASK-E03-1 (DeepSeek client wrapper, fast/heavy tier per ADR-0003).

HTTP calls are mocked with `respx` — no real network access, per
`docs/engineering/best-practices.md`. One additional live test is skipped by default and only
runs against the real DeepSeek API when `RUN_LIVE_DEEPSEEK_TEST=1` is set manually.
"""

import os

import httpx
import pytest
import respx

from diploma_backend.llm_routing import DeepSeekClient, LLMRequestError

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


@respx.mock
async def test_generate_fast_uses_fast_model() -> None:
    route = respx.post(_CHAT_URL).mock(return_value=_success_response("fast reply"))

    result = await _client().generate_fast([{"role": "user", "content": "hi"}])

    assert result == "fast reply"
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-key"
    sent_body = respx.calls.last.request.content
    import json

    assert json.loads(sent_body)["model"] == "deepseek-v4-flash"


@respx.mock
async def test_generate_heavy_uses_heavy_model() -> None:
    respx.post(_CHAT_URL).mock(return_value=_success_response("heavy reply"))

    result = await _client().generate_heavy([{"role": "user", "content": "hi"}])

    assert result == "heavy reply"
    import json

    assert json.loads(respx.calls.last.request.content)["model"] == "deepseek-v4-pro"


@respx.mock
async def test_non_2xx_response_raises_llm_request_error() -> None:
    respx.post(_CHAT_URL).mock(return_value=httpx.Response(500, json={"error": "boom"}))

    with pytest.raises(LLMRequestError):
        await _client().generate_fast([{"role": "user", "content": "hi"}])


@respx.mock
async def test_timeout_raises_llm_request_error() -> None:
    respx.post(_CHAT_URL).mock(side_effect=httpx.TimeoutException("timed out"))

    with pytest.raises(LLMRequestError):
        await _client().generate_fast([{"role": "user", "content": "hi"}])


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_DEEPSEEK_TEST") != "1",
    reason="Live DeepSeek API call; set RUN_LIVE_DEEPSEEK_TEST=1 to run manually",
)
async def test_live_deepseek_fast_call_smoke() -> None:
    client = DeepSeekClient()
    result = await client.generate_fast(
        [{"role": "user", "content": "Reply with exactly the word: ok"}], max_tokens=5
    )
    assert isinstance(result, str)
    assert len(result) > 0
