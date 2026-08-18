"""Tests for TASK-E07-1 (humanizer pipeline, citation-preservation contract).

HTTP calls are mocked with `respx`, matching `test_retry.py`/`test_llm_routing.py`'s pattern —
no real network access.
"""

import json

import httpx
import pytest
import respx

from diploma_backend.humanizer.pipeline import (
    HumanizationError,
    guard_citations,
    humanize_text,
    normalize_dashes,
    restore_citations,
)
from diploma_backend.llm_routing import DeepSeekClient, LLMRequestError

_CHAT_URL = "https://api.deepseek.com/chat/completions"

_APA_TEXT = "Prior work established this baseline (Smith, 2020) among other findings."
_GOST_TEXT = "Prior work established this baseline [3] among other findings."


def _client() -> DeepSeekClient:
    return DeepSeekClient(
        api_key="test-key", fast_model="deepseek-v4-flash", heavy_model="deepseek-v4-pro"
    )


def _success_response(content: str) -> httpx.Response:
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


def test_normalize_dashes_replaces_em_dash_with_en_dash() -> None:
    text = "This is one point—and this is another."

    result = normalize_dashes(text)

    assert "—" not in result
    assert result == "This is one point–and this is another."


def test_normalize_dashes_leaves_text_without_em_dash_unchanged() -> None:
    text = "No em dashes here at all, only a hyphen-word."

    assert normalize_dashes(text) == text


def test_guard_citations_replaces_apa_and_gost_markers() -> None:
    text = f"{_APA_TEXT} Also see this. {_GOST_TEXT}"

    guarded = guard_citations(text)

    assert "(Smith, 2020)" not in guarded.text
    assert "[3]" not in guarded.text
    assert "__CITATION_0__" in guarded.text
    assert "__CITATION_1__" in guarded.text
    assert guarded.citations == ["(Smith, 2020)", "[3]"]


def test_guard_citations_recognizes_the_richer_title_and_page_citation_shape() -> None:
    """User request: in-text citations now include the work's title and, when available, a page
    number — e.g. '(Иванов, 2020, "Название статьи", с. 45)' — not just '(Author, Year)'. The
    citation-preservation guard must still recognize and protect this richer shape from being
    rewritten during humanization."""
    text = 'Prior work established this (Иванов, 2020, "Название статьи", с. 45) among findings.'

    guarded = guard_citations(text)

    assert '(Иванов, 2020, "Название статьи", с. 45)' not in guarded.text
    assert "__CITATION_0__" in guarded.text
    assert guarded.citations == ['(Иванов, 2020, "Название статьи", с. 45)']


def test_guard_citations_recognizes_title_without_a_page_number() -> None:
    text = 'See (Smith, 2020, "A Study of Things") for details.'

    guarded = guard_citations(text)

    assert guarded.citations == ['(Smith, 2020, "A Study of Things")']


def test_guard_then_restore_round_trip_is_identity() -> None:
    text = f"{_APA_TEXT} Also see this. {_GOST_TEXT}"

    guarded = guard_citations(text)
    restored = restore_citations(guarded.text, guarded.citations)

    assert restored == text


def test_restore_citations_raises_when_placeholder_missing() -> None:
    guarded = guard_citations(_APA_TEXT)
    mangled_response = guarded.text.replace("__CITATION_0__", "")

    with pytest.raises(HumanizationError):
        restore_citations(mangled_response, guarded.citations)


@respx.mock
async def test_humanize_text_happy_path_restores_citations() -> None:
    text = f"{_APA_TEXT} Also see this. {_GOST_TEXT}"
    guarded = guard_citations(text)
    rewritten = f"Rewritten version. {guarded.text} Some more rewritten prose."
    respx.post(_CHAT_URL).mock(return_value=_success_response(rewritten))

    result = await humanize_text(_client(), text)

    assert "(Smith, 2020)" in result
    assert "[3]" in result
    assert "__CITATION_" not in result


@respx.mock
async def test_humanize_text_normalizes_em_dashes_in_response() -> None:
    text = _APA_TEXT
    guarded = guard_citations(text)
    rewritten = f"Rewritten—with an em dash. {guarded.text}"
    respx.post(_CHAT_URL).mock(return_value=_success_response(rewritten))

    result = await humanize_text(_client(), text)

    assert "—" not in result
    assert "–" in result


@respx.mock
async def test_humanize_text_raises_humanization_error_on_dropped_placeholder() -> None:
    text = _APA_TEXT
    guarded = guard_citations(text)
    mangled = guarded.text.replace("__CITATION_0__", "")
    respx.post(_CHAT_URL).mock(return_value=_success_response(mangled))

    with pytest.raises(HumanizationError):
        await humanize_text(_client(), text)


@respx.mock
async def test_humanize_text_uses_fast_tier_model() -> None:
    text = _APA_TEXT
    guarded = guard_citations(text)
    respx.post(_CHAT_URL).mock(return_value=_success_response(guarded.text))

    await humanize_text(_client(), text)

    sent_body = json.loads(respx.calls.last.request.content)
    assert sent_body["model"] == "deepseek-v4-flash"


@respx.mock
async def test_humanize_text_propagates_llm_request_error_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("diploma_backend.llm_routing.retry.asyncio.sleep", _fake_sleep)
    respx.post(_CHAT_URL).mock(return_value=httpx.Response(500, json={"error": "boom"}))

    with pytest.raises(LLMRequestError):
        await humanize_text(_client(), _APA_TEXT, max_attempts=2)

    assert len(respx.calls) == 2
