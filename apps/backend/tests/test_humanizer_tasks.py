"""Tests for `humanizer.tasks.humanize_text_task` (ADR-0013, TASK-E17-2).

HTTP calls are mocked with `respx`, matching `test_humanizer.py`'s pattern. Per ADR-0013 addendum
point 4, `.delay()` is called from plain sync test functions, never `async def` test code.
"""

import httpx
import pytest
import respx

from diploma_backend.humanizer.pipeline import HumanizationError
from diploma_backend.humanizer.tasks import humanize_text_task

_CHAT_URL = "https://api.deepseek.com/chat/completions"


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


@respx.mock
def test_delay_runs_task_and_preserves_citation() -> None:
    respx.post(_CHAT_URL).mock(
        return_value=_success_response(
            "This baseline was established by prior work __CITATION_0__."
        )
    )

    async_result = humanize_text_task.delay(
        "Prior work established this baseline (Smith, 2020).", api_key="test-key"
    )

    assert async_result.get() == "This baseline was established by prior work (Smith, 2020)."


@respx.mock
def test_dropped_citation_placeholder_propagates_as_real_exception() -> None:
    respx.post(_CHAT_URL).mock(return_value=_success_response("This baseline is well known."))

    with pytest.raises(HumanizationError):
        humanize_text_task.delay(
            "Prior work established this baseline (Smith, 2020).", api_key="test-key"
        )
