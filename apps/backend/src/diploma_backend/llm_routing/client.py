"""DeepSeek chat-completions client with fast/heavy tier routing (ADR-0003, TASK-E03-1).

Wraps DeepSeek's OpenAI-compatible chat-completions HTTP API via `httpx`. Callers pick the tier
per ADR-0003's static task-type policy: `"fast"` (`DEEPSEEK_FAST_MODEL`) for TOC/structure
parsing, citation verification, humanization, plagiarism/AI-detection scoring, and Markdown
formatting; `"heavy"` (`DEEPSEEK_HEAVY_MODEL`) for chapter drafting, argument synthesis, and
complex reasoning/math/table generation.

Out of scope here (later tasks): chapter-summary compaction / prompt-cache assembly
(TASK-E03-2) and retry/backoff policy (TASK-E03-3) — any failure surfaces once as a single
`LLMRequestError`, never retried.
"""

import json
import os
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

_BASE_URL = "https://api.deepseek.com"
_CHAT_COMPLETIONS_PATH = "/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 60.0

Tier = Literal["fast", "heavy"]
Message = dict[str, str]


class LLMRequestError(Exception):
    """Raised when a DeepSeek chat-completions call fails.

    Covers network errors, timeouts, non-2xx responses, and unexpected response shapes so
    callers never need to catch raw `httpx` exceptions directly.
    """


class DeepSeekClient:
    """Async client for DeepSeek's chat-completions API, routed by task-type tier."""

    def __init__(
        self,
        api_key: str | None = None,
        fast_model: str | None = None,
        heavy_model: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Build a client, reading unset arguments from the environment.

        `api_key`, `fast_model`, `heavy_model` fall back to `DEEPSEEK_API_KEY`,
        `DEEPSEEK_FAST_MODEL`, `DEEPSEEK_HEAVY_MODEL` respectively. The API key is kept only in
        memory for request headers — never logged, printed, or included in error messages.
        """
        self._api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")
        self._fast_model = fast_model or os.environ.get("DEEPSEEK_FAST_MODEL", "deepseek-v4-flash")
        self._heavy_model = heavy_model or os.environ.get("DEEPSEEK_HEAVY_MODEL", "deepseek-v4-pro")
        self._timeout = timeout

    def _model_for(self, tier: Tier) -> str:
        return self._fast_model if tier == "fast" else self._heavy_model

    async def generate(
        self,
        tier: Tier,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send a chat-completions request to the model routed for `tier`.

        Inputs: `tier` selects `"fast"` or `"heavy"` per ADR-0003; `messages` is the
        OpenAI-compatible chat history (`[{"role": ..., "content": ...}]`); `temperature` and
        `max_tokens` are passed through to DeepSeek when given.
        Output: the assistant's reply text (first choice's `message.content`).
        Raises `LLMRequestError` on any network failure, timeout, non-2xx response, or a
        response missing the expected `choices[0].message.content` shape.
        """
        payload: dict[str, Any] = {"model": self._model_for(tier), "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with httpx.AsyncClient(base_url=_BASE_URL, timeout=self._timeout) as client:
                response = await client.post(_CHAT_COMPLETIONS_PATH, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMRequestError(
                f"DeepSeek request failed with status {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMRequestError(f"DeepSeek request failed: {type(exc).__name__}") from exc

        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMRequestError("DeepSeek response missing expected content") from exc

    async def generate_stream(
        self,
        tier: Tier,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream a chat-completions response token-by-token (ADR-0009, TASK-E08-3).

        Same request shape as `generate` (`tier`/`messages`/`temperature`/`max_tokens`), but sets
        `"stream": true` and issues the request via `httpx.AsyncClient.stream` instead of `.post`,
        so the response body is consumed incrementally as DeepSeek's OpenAI-compatible SSE stream
        arrives, rather than waiting for the full response.

        Yields each non-empty `choices[0].delta.content` chunk, in order, as soon as it is
        received. Lines that aren't `data: ...` (e.g. blank keep-alive lines) are skipped, as are
        chunks whose `delta` has no `content` (e.g. the first chunk, which only carries `role`).
        Stops cleanly on the literal `data: [DONE]` sentinel line.

        Deliberately has NO retry wrapper, unlike `generate`: retrying a stream that has already
        emitted partial output to the caller would mean either silently duplicating/discarding
        already-yielded tokens or re-streaming from scratch after the caller may have already
        surfaced partial text — neither composes cleanly with a token-by-token consumer. See
        `llm_routing.retry`'s module docstring: that module's retry-with-backoff policy is for the
        non-streaming `generate` path only. Callers of this method should treat any failure
        (including one raised after some chunks were already yielded) as a real, visible failure
        to the user rather than retrying transparently.

        Raises `LLMRequestError` if the initial response status is non-2xx, or if the connection
        drops/errors at any point while iterating the stream (including mid-stream, after some
        chunks have already been yielded) — never silently truncates the stream on error.
        """
        payload: dict[str, Any] = {
            "model": self._model_for(tier),
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with (
                httpx.AsyncClient(base_url=_BASE_URL, timeout=self._timeout) as client,
                client.stream(
                    "POST", _CHAT_COMPLETIONS_PATH, json=payload, headers=headers
                ) as response,
            ):
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise LLMRequestError(
                        f"DeepSeek request failed with status {exc.response.status_code}"
                    ) from exc

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[len("data: ") :]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        content = chunk["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError, TypeError, ValueError) as exc:
                        raise LLMRequestError(
                            "DeepSeek stream chunk missing expected content"
                        ) from exc
                    if content:
                        yield content
        except LLMRequestError:
            raise
        except httpx.HTTPError as exc:
            raise LLMRequestError(f"DeepSeek request failed: {type(exc).__name__}") from exc

    async def generate_fast(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Call `DEEPSEEK_FAST_MODEL`. See `generate` for the parameter/exception contract."""
        return await self.generate("fast", messages, temperature=temperature, max_tokens=max_tokens)

    async def generate_heavy(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Call `DEEPSEEK_HEAVY_MODEL`. See `generate` for the parameter/exception contract."""
        return await self.generate(
            "heavy", messages, temperature=temperature, max_tokens=max_tokens
        )
