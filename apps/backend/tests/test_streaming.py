"""Tests for `DeepSeekClient.generate_stream` (ADR-0009, TASK-E08-3).

HTTP calls are mocked with `respx` — no real network access, matching
`test_llm_routing.py`'s pattern. `respx` mocks a streamed request the same way as a normal one:
a plain `httpx.Response` with the full SSE body as `content` is enough to drive
`AsyncClient.stream(...).aiter_lines()`, verified empirically here.
"""

import httpx
import pytest
import respx

from diploma_backend.llm_routing import DeepSeekClient, LLMRequestError

_CHAT_URL = "https://api.deepseek.com/chat/completions"


def _client() -> DeepSeekClient:
    return DeepSeekClient(
        api_key="test-key", fast_model="deepseek-v4-flash", heavy_model="deepseek-v4-pro"
    )


def _sse_body(deltas: list[str]) -> bytes:
    lines = []
    for delta in deltas:
        lines.append(f'data: {{"choices":[{{"delta":{{"content":"{delta}"}}}}]}}\n\n')
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


@respx.mock
async def test_generate_stream_yields_chunks_in_order() -> None:
    respx.post(_CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(["Hello", ", ", "world", "."]),
        )
    )

    chunks = [
        chunk
        async for chunk in _client().generate_stream("heavy", [{"role": "user", "content": "hi"}])
    ]

    assert chunks == ["Hello", ", ", "world", "."]


@respx.mock
async def test_generate_stream_stops_at_done_sentinel() -> None:
    body = (
        b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
        b"data: [DONE]\n\n"
        b'data: {"choices":[{"delta":{"content":"b"}}]}\n\n'
    )
    respx.post(_CHAT_URL).mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)
    )

    chunks = [
        chunk
        async for chunk in _client().generate_stream("heavy", [{"role": "user", "content": "hi"}])
    ]

    assert chunks == ["a"]


@respx.mock
async def test_generate_stream_skips_empty_and_keepalive_lines() -> None:
    body = b'\ndata: {"choices":[{"delta":{"role":"assistant"}}]}\n\ndata: {"choices":[{"delta":{"content":"x"}}]}\n\ndata: [DONE]\n\n'
    respx.post(_CHAT_URL).mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)
    )

    chunks = [
        chunk
        async for chunk in _client().generate_stream("heavy", [{"role": "user", "content": "hi"}])
    ]

    assert chunks == ["x"]


@respx.mock
async def test_generate_stream_non_2xx_raises_llm_request_error() -> None:
    respx.post(_CHAT_URL).mock(return_value=httpx.Response(500, json={"error": "boom"}))

    with pytest.raises(LLMRequestError):
        async for _ in _client().generate_stream("heavy", [{"role": "user", "content": "hi"}]):
            pass


@respx.mock
async def test_generate_stream_connection_failure_raises_llm_request_error() -> None:
    respx.post(_CHAT_URL).mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(LLMRequestError):
        async for _ in _client().generate_stream("heavy", [{"role": "user", "content": "hi"}]):
            pass
