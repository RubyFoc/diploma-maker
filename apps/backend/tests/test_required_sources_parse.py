"""Tests for bulk-text required-sources parsing (user request):
`llm_routing.required_sources_parse` and `POST /projects/required-sources/parse-bulk`.
"""

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from diploma_backend.llm_routing.required_sources_parse import (
    RequiredSourcesParseError,
    parse_response,
    split_into_batches,
)

_CHAT_URL = "https://api.deepseek.com/chat/completions"


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    response = client.post("/auth/register", json={"email": email, "password": "hunter22"})
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _chat_response(content: str) -> httpx.Response:
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


class TestParseResponse:
    def test_parses_a_plain_json_array(self) -> None:
        content = json.dumps([{"author": "Jane Doe", "title": "A Study of Things"}])

        assert parse_response(content) == [{"author": "Jane Doe", "title": "A Study of Things"}]

    def test_parses_entries_with_no_title(self) -> None:
        content = json.dumps([{"author": "Jane Doe"}])

        assert parse_response(content) == [{"author": "Jane Doe"}]

    def test_strips_a_markdown_code_fence(self) -> None:
        content = '```json\n[{"author": "Jane Doe"}]\n```'

        assert parse_response(content) == [{"author": "Jane Doe"}]

    def test_drops_entries_missing_a_non_empty_author(self) -> None:
        content = json.dumps([{"author": "  "}, {"title": "No author"}, {"author": "Jane Doe"}])

        assert parse_response(content) == [{"author": "Jane Doe"}]

    def test_raises_on_non_json_content(self) -> None:
        with pytest.raises(RequiredSourcesParseError):
            parse_response("not json at all")

    def test_raises_when_response_is_not_a_json_array(self) -> None:
        with pytest.raises(RequiredSourcesParseError):
            parse_response(json.dumps({"author": "Jane Doe"}))

    def test_parses_entries_with_a_url(self) -> None:
        content = json.dumps([{"author": "Jane Doe", "url": "https://example.com/paper.pdf"}])

        assert parse_response(content) == [
            {"author": "Jane Doe", "url": "https://example.com/paper.pdf"}
        ]

    def test_omits_url_when_blank(self) -> None:
        content = json.dumps([{"author": "Jane Doe", "url": "   "}])

        assert parse_response(content) == [{"author": "Jane Doe"}]


class TestSplitIntoBatches:
    def test_returns_a_single_batch_for_input_at_or_below_batch_size(self) -> None:
        entries = [f"Entry {i}." for i in range(3)]
        text = "\n\n".join(entries)

        assert split_into_batches(text, batch_size=8) == [text]

    def test_splits_into_multiple_batches_above_batch_size(self) -> None:
        entries = [f"Entry {i}." for i in range(10)]
        text = "\n\n".join(entries)

        batches = split_into_batches(text, batch_size=4)

        assert len(batches) == 3
        assert batches[0] == "\n\n".join(entries[:4])
        assert batches[1] == "\n\n".join(entries[4:8])
        assert batches[2] == "\n\n".join(entries[8:10])

    def test_falls_back_to_one_batch_when_there_are_no_blank_line_separators(self) -> None:
        text = "Doe, J. A single entry with no blank lines anywhere in it."

        assert split_into_batches(text, batch_size=4) == [text]

    def test_empty_input_returns_no_batches(self) -> None:
        assert split_into_batches("", batch_size=4) == []

    def test_ignores_extra_blank_lines_between_entries(self) -> None:
        text = "Entry one.\n\n\n\nEntry two."

        batches = split_into_batches(text, batch_size=4)

        assert batches == ["Entry one.\n\nEntry two."]


class TestParseBulkEndpoint:
    @respx.mock
    def test_returns_parsed_entries(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        respx.post(_CHAT_URL).mock(
            return_value=_chat_response(
                json.dumps([{"author": "Jane Doe", "title": "A Study of Things"}])
            )
        )

        response = client.post(
            "/projects/required-sources/parse-bulk",
            json={"text": "Doe, J. A Study of Things. 2020."},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json() == [{"author": "Jane Doe", "title": "A Study of Things", "url": None}]

    @respx.mock
    def test_splits_a_large_paste_into_multiple_batched_calls_and_merges_results_in_order(
        self, client: TestClient
    ) -> None:
        """User report: a real ~20-entry GOST-style reference list came back as a 502 every
        time, because a single model call over that many entries spent its whole completion-
        token budget on internal reasoning and never emitted an answer (see
        `required_sources_parse`'s module docstring). Splitting into batches of 8 fixes it."""
        headers = _auth_headers(client)
        # 9 entries — one more than the batch size (8) — so this must span two calls.
        entries = [f"Author{i}, A. Title {i}." for i in range(9)]
        pasted_text = "\n\n".join(entries)

        def side_effect(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            sent_text = body["messages"][1]["content"]
            if "Author0" in sent_text:
                authors = [f"Author{i}" for i in range(8)]
            else:
                authors = ["Author8"]
            return _chat_response(json.dumps([{"author": author} for author in authors]))

        respx.post(_CHAT_URL).mock(side_effect=side_effect)

        response = client.post(
            "/projects/required-sources/parse-bulk", json={"text": pasted_text}, headers=headers
        )

        assert response.status_code == 200
        assert [entry["author"] for entry in response.json()] == [f"Author{i}" for i in range(9)]
        assert len(respx.calls) == 2

    def test_blank_text_returns_empty_list_without_calling_the_model(
        self, client: TestClient
    ) -> None:
        headers = _auth_headers(client)

        response = client.post(
            "/projects/required-sources/parse-bulk", json={"text": "   "}, headers=headers
        )

        assert response.status_code == 200
        assert response.json() == []

    @respx.mock
    def test_returns_502_on_unparseable_model_response(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        respx.post(_CHAT_URL).mock(return_value=_chat_response("not json"))

        response = client.post(
            "/projects/required-sources/parse-bulk",
            json={"text": "Doe, J. A Study of Things. 2020."},
            headers=headers,
        )

        assert response.status_code == 502

    def test_requires_auth(self, client: TestClient) -> None:
        response = client.post("/projects/required-sources/parse-bulk", json={"text": "Doe, J."})

        assert response.status_code == 401

    @respx.mock
    def test_keeps_a_url_that_appears_verbatim_in_the_pasted_text(self, client: TestClient) -> None:
        headers = _auth_headers(client)
        pasted_text = (
            "Doe, J. A Study of Things. 2020. URL: https://example.com/paper.pdf "
            "(дата обращения: 05.08.2026)."
        )
        respx.post(_CHAT_URL).mock(
            return_value=_chat_response(
                json.dumps(
                    [
                        {
                            "author": "Jane Doe",
                            "title": "A Study of Things",
                            "url": "https://example.com/paper.pdf",
                        }
                    ]
                )
            )
        )

        response = client.post(
            "/projects/required-sources/parse-bulk", json={"text": pasted_text}, headers=headers
        )

        assert response.status_code == 200
        assert response.json()[0]["url"] == "https://example.com/paper.pdf"

    @respx.mock
    def test_drops_a_url_the_model_invented_or_mistranscribed(self, client: TestClient) -> None:
        """The model is told to copy a URL verbatim, but could still mangle a long one — a URL
        that doesn't appear character-for-character in the original pasted text is dropped rather
        than trusted and later fetched (`projects.router._fetch_required_source_excerpts`)."""
        headers = _auth_headers(client)
        respx.post(_CHAT_URL).mock(
            return_value=_chat_response(
                json.dumps(
                    [
                        {
                            "author": "Jane Doe",
                            "title": "A Study of Things",
                            "url": "https://example.com/hallucinated-url.pdf",
                        }
                    ]
                )
            )
        )

        response = client.post(
            "/projects/required-sources/parse-bulk",
            json={"text": "Doe, J. A Study of Things. 2020."},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()[0]["url"] is None
