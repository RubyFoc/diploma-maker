"""Tests for the SSE streaming generation endpoint (ADR-0009, TASK-E08-3):
`GET /projects/{project_id}/chapters/{chapter_id}/generate/stream`.

Mirrors `test_projects.py`'s dual-mock pattern (heavy-tier generation + fast-tier humanization,
distinguished by respx's `json__model` matcher) but drives the DeepSeek "generation" call as an
SSE-streamed response instead of a single JSON body, since the endpoint under test calls
`DeepSeekClient.generate_stream` rather than `generate_with_retry`.
"""

import json

import httpx
import respx
from fastapi.testclient import TestClient

_CHAT_URL = "https://api.deepseek.com/chat/completions"
_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    """Register a user and return an `Authorization` header, since project endpoints require
    auth as of TASK-E11-1 (see `test_auth.py`'s `_register`)."""
    response = client.post("/auth/register", json={"email": email, "password": "hunter22"})
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _mock_empty_rag_search() -> None:
    """Mock the RAG-grounding search call every generation call now makes, with an empty
    result — these tests don't exercise RAG grounding itself."""
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(200, json={"data": []}))


def _stream_body(deltas: list[str]) -> bytes:
    lines = [f'data: {{"choices":[{{"delta":{{"content":{json.dumps(d)}}}}}]}}\n\n' for d in deltas]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


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


def _fail_response() -> httpx.Response:
    return httpx.Response(500, json={"error": "boom"})


def _mock_stream_and_humanize(
    *, deltas: list[str] = ("Draft ", "chapter ", "body."), humanized: str = "Humanized body."
) -> None:
    _mock_empty_rag_search()
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=_stream_body(list(deltas))
        )
    )
    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(
        return_value=_success_response(humanized)
    )


_TITLE_PROMPT_MARKER = "thesis title"
"""Substring unique to `llm_routing.title`'s system prompt, mirroring `test_projects.py`'s
constant of the same name — used to tell the fast-tier title-generation call apart from the
fast-tier humanization call in respx mocks."""


def _is_title_request(request: httpx.Request) -> bool:
    body = json.loads(request.content)
    return _TITLE_PROMPT_MARKER in body["messages"][0]["content"]


def _mock_stream_humanize_and_title(
    *,
    deltas: list[str] = ("Draft ", "chapter ", "body."),
    humanized: str = "Humanized body.",
    title_response: httpx.Response | None = None,
) -> None:
    """Like `_mock_stream_and_humanize`, plus a mock for the fast-tier project-title
    auto-generation call (Phase 5.9), distinguished from humanization by request content via
    `side_effect` (see `test_projects.py`'s `_mock_generate_humanize_and_title`)."""
    _mock_empty_rag_search()
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=_stream_body(list(deltas))
        )
    )
    resolved_title_response = (
        title_response if title_response is not None else _success_response("Generated Title")
    )

    def side_effect(request: httpx.Request) -> httpx.Response:
        return resolved_title_response if _is_title_request(request) else _success_response(
            humanized
        )

    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(side_effect=side_effect)


def _parse_sse(text: str) -> list[tuple[str, str]]:
    """Parse raw SSE text into `(event, data)` pairs, joining multi-line `data:` blocks."""
    events: list[tuple[str, str]] = []
    event_name = None
    data_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.rstrip("\r")
        if line.startswith("event: "):
            event_name = line[len("event: ") :]
        elif line.startswith("data: "):
            data_lines.append(line[len("data: ") :])
        elif line == "" and event_name is not None:
            events.append((event_name, "\n".join(data_lines)))
            event_name = None
            data_lines = []
    return events


def _setup_default_titled_project_and_chapter(client: TestClient) -> tuple[str, str, dict]:
    """Like `_setup_project_and_chapter`, but leaves the project at its default title (rather
    than "Thesis") so title auto-generation (Phase 5.9) is actually exercised."""
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    return project_id, chapter_id, headers


def _setup_project_and_chapter(client: TestClient) -> tuple[str, str, dict]:
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    return project_id, chapter_id, headers


@respx.mock
def test_generate_stream_emits_tokens_and_done(client: TestClient) -> None:
    _mock_stream_and_humanize(deltas=["Draft ", "chapter ", "body."], humanized="Humanized body.")
    project_id, chapter_id, headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write an introduction."},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    token_events = [data for event, data in events if event == "token"]
    assert token_events == ["Draft ", "chapter ", "body."]

    done_events = [data for event, data in events if event == "done"]
    assert len(done_events) == 1
    payload = json.loads(done_events[0])
    assert payload["version"]["content"] == "Humanized body."
    assert payload["version"]["chapter_id"] == chapter_id
    assert set(payload["precheck"].keys()) == {
        "plagiarism_score",
        "ai_fingerprint_score",
        "flagged",
        "reasons",
    }

    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    pending_draft = project_after["chapters"][0]["pending_draft"]
    assert pending_draft is not None
    assert pending_draft["content"] == "Humanized body."


@respx.mock
def test_generate_stream_multiline_chunk_is_framed_correctly(client: TestClient) -> None:
    _mock_stream_and_humanize(deltas=["line one\nline two"], humanized="Humanized body.")
    project_id, chapter_id, _headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    events = _parse_sse(response.text)
    token_events = [data for event, data in events if event == "token"]
    assert token_events == ["line one\nline two"]


@respx.mock
def test_generate_stream_llm_failure_emits_error_event(client: TestClient) -> None:
    _mock_empty_rag_search()
    respx.post(_CHAT_URL).mock(return_value=_fail_response())
    project_id, chapter_id, headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert len(events) == 1
    event, data = events[0]
    assert event == "error"
    assert "detail" in json.loads(data)

    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    assert project_after["chapters"][0]["pending_draft"] is None


@respx.mock
def test_generate_stream_auto_titles_a_default_titled_project(client: TestClient) -> None:
    """First streamed generation on a still-default-titled project (Phase 5.9) results in the
    project's title being replaced with the LLM-generated one, mirroring
    `test_projects.py`'s non-streaming equivalent."""
    _mock_stream_humanize_and_title(title_response=_success_response("Renewable Energy Policy"))
    project_id, chapter_id, headers = _setup_default_titled_project_and_chapter(client)
    assert client.get(f"/projects/{project_id}", headers=headers).json()["title"] == (
        "Untitled Thesis"
    )

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write an introduction about renewable energy."},
    )

    assert response.status_code == 200
    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    assert project_after["title"] == "Renewable Energy Policy"

    title_calls = [
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and _is_title_request(call.request)
    ]
    assert len(title_calls) == 1


@respx.mock
def test_generate_stream_title_generation_failure_does_not_break_main_flow(
    client: TestClient,
) -> None:
    """A failing title-generation call must not break the streamed draft response, and must leave
    the project's title at its default (fail-open)."""
    _mock_stream_humanize_and_title(title_response=_fail_response())
    project_id, chapter_id, headers = _setup_default_titled_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write an introduction about renewable energy."},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    done_events = [data for event, data in events if event == "done"]
    assert len(done_events) == 1
    assert json.loads(done_events[0])["version"]["content"] == "Humanized body."

    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    assert project_after["title"] == "Untitled Thesis"


def test_generate_stream_404s_for_unknown_chapter(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]

    response = client.get(
        f"/projects/{project_id}/chapters/does-not-exist/generate/stream",
        params={"instruction": "Write something."},
    )

    assert response.status_code == 404


def test_generate_stream_404s_when_chapter_belongs_to_other_project(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_a = client.post("/projects", json={"title": "Thesis A"}, headers=headers).json()["id"]
    project_b = client.post("/projects", json={"title": "Thesis B"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_a}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.get(
        f"/projects/{project_b}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    assert response.status_code == 404
