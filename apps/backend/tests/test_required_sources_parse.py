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
        assert response.json() == [{"author": "Jane Doe", "title": "A Study of Things"}]

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
