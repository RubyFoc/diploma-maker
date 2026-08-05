"""Tests for TASK-E03-2 (chapter-summary compaction + cache-friendly prompt assembly).

HTTP calls are mocked with `respx`, following the pattern in `test_llm_routing.py` — no real
network access, per `docs/engineering/best-practices.md`.
"""

import json

import httpx
import respx

from diploma_backend.llm_routing import DeepSeekClient, assemble_prompt, summarize_chapter

_CHAT_URL = "https://api.deepseek.com/chat/completions"


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


@respx.mock
async def test_summarize_chapter_uses_fast_tier_and_returns_content() -> None:
    respx.post(_CHAT_URL).mock(return_value=_success_response("a concise summary"))

    result = await summarize_chapter(_client(), "full chapter text " * 100)

    assert result == "a concise summary"
    sent_body = json.loads(respx.calls.last.request.content)
    assert sent_body["model"] == "deepseek-v4-flash"
    assert sent_body["max_tokens"] == 400
    assert sent_body["messages"][-1]["content"] == "full chapter text " * 100


def test_assemble_prompt_empty_summaries_and_excerpts() -> None:
    messages = assemble_prompt(
        system_prompt="You are a thesis-writing assistant.",
        chapter_summaries=[],
        rag_excerpts=[],
        user_message="Draft the introduction.",
    )

    assert messages == [
        {"role": "system", "content": "You are a thesis-writing assistant."},
        {"role": "user", "content": "Draft the introduction."},
    ]


def test_assemble_prompt_multiple_summaries_stay_before_user_message() -> None:
    messages = assemble_prompt(
        system_prompt="System instructions.",
        chapter_summaries=["Chapter 1 summary.", "Chapter 2 summary."],
        rag_excerpts=[],
        user_message="Continue with chapter 3.",
    )

    assert len(messages) == 3
    assert messages[0] == {"role": "system", "content": "System instructions."}
    assert messages[1]["role"] == "system"
    assert "Chapter 1 summary." in messages[1]["content"]
    assert "Chapter 2 summary." in messages[1]["content"]
    assert messages[1]["content"].index("Chapter 1 summary.") < messages[1]["content"].index(
        "Chapter 2 summary."
    )
    assert messages[2] == {"role": "user", "content": "Continue with chapter 3."}


def test_assemble_prompt_with_rag_excerpts_and_no_summaries() -> None:
    messages = assemble_prompt(
        system_prompt="System instructions.",
        chapter_summaries=[],
        rag_excerpts=["Excerpt A", "Excerpt B"],
        user_message="What does the literature say?",
    )

    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": "System instructions."}
    user_content = messages[1]["content"]
    assert messages[1]["role"] == "user"
    assert user_content.index("Excerpt A") < user_content.index("Excerpt B")
    assert user_content.index("Excerpt B") < user_content.index("What does the literature say?")


def test_assemble_prompt_stable_prefix_identical_across_calls_with_different_volatile_content() -> (
    None
):
    common_kwargs = {
        "system_prompt": "System instructions.",
        "chapter_summaries": ["Chapter 1 summary.", "Chapter 2 summary."],
    }

    first_call = assemble_prompt(**common_kwargs, rag_excerpts=["Excerpt A"], user_message="Turn 1")
    second_call = assemble_prompt(
        **common_kwargs, rag_excerpts=["Excerpt Z"], user_message="Turn 2"
    )

    assert first_call[:2] == second_call[:2]
    assert first_call[2] != second_call[2]
