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

from diploma_backend.llm_routing.tasks import stream_generation_task
from diploma_backend.projects import router as projects_router

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
def test_generate_stream_flagged_content_does_not_crash_precheck_reconstruction(
    client: TestClient,
) -> None:
    """Regression test mirroring `test_projects.py`'s test of the same name: the streaming
    endpoint's inline copy of `_humanize_and_precheck`'s precheck-dict reconstruction had the same
    bug (plain `PlagiarismCheckResult(**precheck_dict)` construction leaving `sentence_flags` as
    a `list[dict]` instead of `list[SentenceFlag]`), duplicated separately from the shared
    helper. The humanized text below reliably earns a non-empty, `is_ai_like`-flagged
    `sentence_flags` via `plagiarism.precheck.flag_sentences`'s repeated-starter heuristic (see
    `test_plagiarism.py`'s `test_flag_sentences_repeated_starter_is_flagged_ai_like`)."""
    humanized = (
        "Furthermore, the results were significant. Furthermore, the data was consistent. "
        "Furthermore, the trend was clear. Furthermore, the outcome was expected."
    )
    _mock_stream_and_humanize(deltas=["Draft ", "chapter ", "body."], humanized=humanized)
    project_id, chapter_id, _headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write an introduction."},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    done_events = [data for event, data in events if event == "done"]
    assert len(done_events) == 1
    payload = json.loads(done_events[0])
    assert payload["version"]["content"] == humanized
    assert set(payload["precheck"].keys()) == {
        "plagiarism_score",
        "ai_fingerprint_score",
        "flagged",
        "reasons",
    }


@respx.mock
def test_generate_stream_done_payload_reports_unmet_required_sources(client: TestClient) -> None:
    """TASK-E14-3: the streaming endpoint's `done` payload carries `unmet_required_sources` the
    same way the non-streaming endpoint's response body does."""
    _mock_stream_and_humanize(deltas=["Draft body."], humanized="Humanized body.")
    project_id, chapter_id, headers = _setup_project_and_chapter(client)
    client.post(
        f"/projects/{project_id}/required-sources", json={"author": "Jane Doe"}, headers=headers
    )

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write an introduction."},
    )

    events = _parse_sse(response.text)
    done_events = [data for event, data in events if event == "done"]
    payload = json.loads(done_events[0])
    assert payload["unmet_required_sources"] == ["Jane Doe"]


@respx.mock
def test_generate_stream_humanize_dropped_citation_falls_back_to_raw_content(
    client: TestClient,
) -> None:
    """`HumanizationError` (a dropped/mangled `__CITATION_N__` placeholder) must fail open through
    the Celery task boundary (ADR-0013, TASK-E17-4) the same way the non-streaming endpoint's
    `_humanize_and_precheck` does, falling back to the raw streamed content instead of emitting an
    `error` event."""
    _mock_empty_rag_search()
    generated = "This baseline was established by prior work (Smith, 2020)."
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_stream_body([generated]),
        )
    )
    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(
        return_value=_success_response("This baseline is well known.")
    )
    project_id, chapter_id, _headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    events = _parse_sse(response.text)
    done_events = [data for event, data in events if event == "done"]
    assert len(done_events) == 1
    payload = json.loads(done_events[0])
    assert payload["version"]["content"] == generated


@respx.mock
def test_generate_stream_humanize_llm_failure_falls_back_to_raw_content(
    client: TestClient,
) -> None:
    """Mirrors `test_projects.py`'s
    `test_generate_draft_humanize_llm_failure_falls_back_to_raw_content`: a genuine
    `LLMRequestError` from the humanize call (every internal retry exhausted) must fail open to
    the raw streamed content, yielding a normal `done` event, not an `error` event that would
    discard the already-streamed generation."""
    generated = "Draft chapter body."
    _mock_empty_rag_search()
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_stream_body([generated]),
        )
    )
    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(return_value=_fail_response())
    project_id, chapter_id, _headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    done_events = [data for event, data in events if event == "done"]
    error_events = [data for event, data in events if event == "error"]
    assert error_events == []
    assert len(done_events) == 1
    assert json.loads(done_events[0])["version"]["content"] == generated


@respx.mock
def test_generate_stream_humanize_timeout_falls_back_to_raw_content(
    client: TestClient, monkeypatch
) -> None:
    """Mirrors `test_projects.py`'s `test_generate_draft_humanize_timeout_falls_back_to_raw_
    content` for the streaming endpoint: a `celery.exceptions.TimeoutError` from this handler's
    own `.get(timeout=...)` wait (not a failure of the humanize call itself) must fail open to
    the raw streamed content, not emit an `error` event."""
    from celery.exceptions import TimeoutError as CeleryTimeoutError

    generated = "Draft chapter body."
    _mock_empty_rag_search()
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_stream_body([generated]),
        )
    )
    project_id, chapter_id, _headers = _setup_project_and_chapter(client)

    class _SlowAsyncResult:
        def get(self, timeout=None):
            raise CeleryTimeoutError("The operation timed out.")

    monkeypatch.setattr(
        projects_router.humanize_text_task, "delay", lambda *args, **kwargs: _SlowAsyncResult()
    )

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    done_events = [data for event, data in events if event == "done"]
    error_events = [data for event, data in events if event == "error"]
    assert error_events == []
    assert len(done_events) == 1
    assert json.loads(done_events[0])["version"]["content"] == generated


@respx.mock
def test_generate_stream_precheck_failure_falls_back_to_all_clear_result(
    client: TestClient, monkeypatch
) -> None:
    """Mirrors `test_projects.py`'s `test_generate_draft_precheck_failure_falls_back_to_all_clear_
    result` for the streaming endpoint's own precheck dispatch."""
    _mock_stream_and_humanize(deltas=["Draft ", "body."], humanized="Humanized body.")

    def _raise_delay(*args, **kwargs):
        raise RuntimeError("precheck worker unavailable")

    monkeypatch.setattr(projects_router.run_precheck_task, "delay", _raise_delay)
    project_id, chapter_id, _headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    done_events = [data for event, data in events if event == "done"]
    assert len(done_events) == 1
    payload = json.loads(done_events[0])
    assert payload["version"]["content"] == "Humanized body."
    assert payload["precheck"] == {
        "plagiarism_score": 0.0,
        "ai_fingerprint_score": 0.0,
        "flagged": False,
        "reasons": [],
    }


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
def test_generate_stream_mid_stream_failure_persists_partial_draft(client: TestClient) -> None:
    """If `stream_generation_task` fails partway through — after already publishing some
    `"token"` entries but before a terminal `"done"` marker — the already-streamed, already-
    generated tokens must not be discarded: the endpoint still yields an `error` SSE event (the
    generation itself did fail), but also persists the partial text as a draft version, raw and
    un-humanized/un-prechecked, so it isn't lost outright.

    The malformed final chunk below (missing the `choices` shape `generate_stream` expects)
    reproduces exactly the `LLMRequestError` `DeepSeekClient.generate_stream` raises mid-stream
    (see `test_streaming.py`), after two well-formed chunks have already been yielded/published.
    """
    _mock_empty_rag_search()
    body = (
        b'data: {"choices":[{"delta":{"content":"Draft "}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"chapter "}}]}\n\n'
        b'data: {"bad": "shape"}\n\n'
    )
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)
    )
    project_id, chapter_id, headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    token_events = [data for event, data in events if event == "token"]
    assert token_events == ["Draft ", "chapter "]
    error_events = [data for event, data in events if event == "error"]
    assert len(error_events) == 1

    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    pending_draft = project_after["chapters"][0]["pending_draft"]
    assert pending_draft is not None
    assert pending_draft["content"] == "Draft chapter "


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


def test_generate_stream_times_out_gracefully_when_no_terminal_marker_arrives(
    client: TestClient, monkeypatch
) -> None:
    """If `stream_generation_task` never publishes a terminal `"done"`/`"error"` marker (e.g. a
    crashed worker, or here a stubbed-out `.delay()` that never writes anything to the stream key
    at all), the tail loop must not hang forever — it must emit a graceful `error` SSE event once
    `_STREAM_TAIL_TIMEOUT_SECONDS` elapses, rather than an unbounded, leaked-open SSE connection.
    Uses a monkeypatched, test-only tiny timeout so this doesn't have to wait out the real
    production ceiling."""
    monkeypatch.setattr(projects_router, "_STREAM_TAIL_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(stream_generation_task, "delay", lambda *args, **kwargs: None)
    project_id, chapter_id, _headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert len(events) == 1
    event, data = events[0]
    assert event == "error"
    assert "timed out" in json.loads(data)["detail"].lower()


def test_generate_stream_dispatch_failure_emits_error_event(
    client: TestClient, monkeypatch
) -> None:
    """If enqueueing `stream_generation_task` itself fails (e.g. a Celery/broker connection error
    before the task even starts), the endpoint must yield a graceful `error` SSE event instead of
    letting the async generator die unhandled with a dropped connection."""

    def _raise_delay(*args, **kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(stream_generation_task, "delay", _raise_delay)
    project_id, chapter_id, _headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert len(events) == 1
    event, data = events[0]
    assert event == "error"
    assert "broker unavailable" in json.loads(data)["detail"]


def test_generate_stream_read_failure_emits_error_event(client: TestClient, monkeypatch) -> None:
    """If the ENDPOINT's own Redis read connection fails while tailing the stream (distinct from
    a failure inside the worker task, already covered by `stream_generation_task`'s own broad
    `except Exception`, and distinct from a dispatch-time failure, covered above), the endpoint
    must still yield a graceful `error` SSE event rather than letting the exception propagate
    unhandled and silently truncate/drop the SSE response mid-stream."""

    class _RaisingRedis:
        async def xread(self, *args, **kwargs):
            raise ConnectionError("redis connection lost")

        async def aclose(self):
            pass

    monkeypatch.setattr(stream_generation_task, "delay", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        projects_router.redis_asyncio.Redis, "from_url", lambda *args, **kwargs: _RaisingRedis()
    )
    project_id, chapter_id, _headers = _setup_project_and_chapter(client)

    response = client.get(
        f"/projects/{project_id}/chapters/{chapter_id}/generate/stream",
        params={"instruction": "Write something."},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert len(events) == 1
    event, data = events[0]
    assert event == "error"
    assert "redis connection lost" in json.loads(data)["detail"]


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
