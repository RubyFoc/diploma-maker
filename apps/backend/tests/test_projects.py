"""Tests for the vertical-slice endpoints: create project -> add chapter -> generate a draft via
chat -> accept it.

HTTP calls to DeepSeek are mocked with `respx` — no real network access, matching
`test_llm_routing.py`/`test_retry.py`'s pattern.
"""

import json

import httpx
import respx
from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.main import app

_CHAT_URL = "https://api.deepseek.com/chat/completions"
_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


def _fake_db(client: TestClient):
    """The in-memory Mongo fake `client`'s `get_database` dependency is overridden to, per
    `conftest.py` — used here to assert cascade-deleted documents (TASK-E11-3) are actually gone,
    matching `test_versions.py`'s `_fake_db` helper."""
    return app.dependency_overrides[get_database]()


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    """Register a user (TASK-E02-1) and return an `Authorization` header for their access token,
    since project endpoints require auth as of TASK-E11-1 (see `test_auth.py`'s `_register`)."""
    response = client.post("/auth/register", json={"email": email, "password": "hunter22"})
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _mock_empty_rag_search() -> None:
    """Mock the RAG-grounding search call (`_fetch_rag_excerpts`) every generation call now
    makes, with an empty result — these tests don't exercise RAG grounding itself (see
    `test_projects_rag.py` for that), just the generate/humanize/precheck/persist pipeline."""
    respx.get(_SEMANTIC_SCHOLAR_URL).mock(return_value=httpx.Response(200, json={"data": []}))


def _success_response(content: str = "Generated chapter text.") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "deepseek-v4-pro",
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


def _mock_generate_and_humanize(
    *, generated: str = "Draft chapter body.", humanized: str = "Humanized chapter body."
) -> None:
    """Mock both DeepSeek calls a successful generation now makes: the heavy-tier draft
    generation and the fast-tier humanization, distinguished by the `model` field respx sees in
    each request body (matching `client._model_for`'s tier->model mapping)."""
    _mock_empty_rag_search()
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=_success_response(generated)
    )
    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(
        return_value=_success_response(humanized)
    )


_TITLE_PROMPT_MARKER = "thesis title"
"""Substring unique to `llm_routing.title`'s system prompt (not present in the humanizer's), used
below to tell the two fast-tier calls a generation now makes apart in respx mocks."""


def _is_title_request(request: httpx.Request) -> bool:
    body = json.loads(request.content)
    return _TITLE_PROMPT_MARKER in body["messages"][0]["content"]


def _mock_generate_humanize_and_title(
    *,
    generated: str = "Draft chapter body.",
    humanized: str = "Humanized chapter body.",
    title_response: httpx.Response | None = None,
) -> None:
    """Like `_mock_generate_and_humanize`, plus a mock for the fast-tier project-title
    auto-generation call (Phase 5.9). Both humanization and title-generation are fast-tier calls
    to the same model, so a single route on `json__model="deepseek-v4-flash"` distinguishes them
    by request content (`_is_title_request`) via `side_effect`, rather than two separately
    registered routes for the same match criteria.

    `title_response` defaults to a successful response with content `"Generated Title"`; pass a
    failure response (e.g. `_fail_response()`) to exercise the fail-open path.
    """
    _mock_empty_rag_search()
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=_success_response(generated)
    )
    resolved_title_response = (
        title_response if title_response is not None else _success_response("Generated Title")
    )

    def side_effect(request: httpx.Request) -> httpx.Response:
        return (
            resolved_title_response if _is_title_request(request) else _success_response(humanized)
        )

    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(side_effect=side_effect)


def test_create_project_returns_empty_chapters(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post("/projects", json={"title": "My Thesis"}, headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "My Thesis"
    assert body["chapters"] == []
    assert "id" in body
    assert "created_at" in body


def test_create_project_persists_and_returns_institution_id(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/projects",
        json={"title": "My Thesis", "institution_id": "inst-1"},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["institution_id"] == "inst-1"


def test_create_project_defaults_institution_id_to_none(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post("/projects", json={"title": "My Thesis"}, headers=headers)

    assert response.status_code == 201
    assert response.json()["institution_id"] is None


def test_create_project_defaults_title_when_omitted(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post("/projects", json={}, headers=headers)

    assert response.status_code == 201
    assert response.json()["title"] == "Untitled Thesis"


def test_create_project_defaults_title_when_empty(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post("/projects", json={"title": ""}, headers=headers)

    assert response.status_code == 201
    assert response.json()["title"] == "Untitled Thesis"


def test_create_project_requires_auth(client: TestClient) -> None:
    response = client.post("/projects", json={"title": "My Thesis"})

    assert response.status_code == 401


def test_get_project_404s_for_unknown_id(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.get("/projects/does-not-exist", headers=headers)

    assert response.status_code == 404


def test_list_projects_requires_auth(client: TestClient) -> None:
    response = client.get("/projects")

    assert response.status_code == 401


def test_list_projects_empty_when_user_has_none(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.get("/projects", headers=headers)

    assert response.status_code == 200
    assert response.json() == []


def test_list_projects_only_shows_own_projects(client: TestClient) -> None:
    owner_headers = _auth_headers(client, email="owner@example.com")
    owned_project = client.post(
        "/projects", json={"title": "Owner's Thesis"}, headers=owner_headers
    ).json()

    other_headers = _auth_headers(client, email="other@example.com")
    client.post("/projects", json={"title": "Other's Thesis"}, headers=other_headers)

    response = client.get("/projects", headers=owner_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == owned_project["id"]
    assert body[0]["title"] == "Owner's Thesis"
    assert "chapters" not in body[0]


def test_get_project_404s_for_other_users_project(client: TestClient) -> None:
    owner_headers = _auth_headers(client, email="owner@example.com")
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=owner_headers).json()[
        "id"
    ]

    other_headers = _auth_headers(client, email="other@example.com")
    response = client.get(f"/projects/{project_id}", headers=other_headers)

    assert response.status_code == 404


async def test_delete_project_removes_it_and_its_chapters_and_versions(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    with respx.mock:
        _mock_generate_and_humanize()
        generate_response = client.post(
            f"/projects/{project_id}/chapters/{chapter_id}/generate",
            json={"instruction": "Write an introduction."},
            headers=headers,
        )
    assert generate_response.status_code == 201
    version_id = generate_response.json()["version"]["id"]

    delete_response = client.delete(f"/projects/{project_id}", headers=headers)
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    assert client.get(f"/projects/{project_id}", headers=headers).status_code == 404

    db = _fake_db(client)
    assert await db["projects"].find_one({"id": project_id}) is None
    assert await db["chapters"].find_one({"id": chapter_id}) is None
    assert await db["chapter_versions"].find_one({"id": version_id}) is None


def test_delete_project_404s_for_other_users_project(client: TestClient) -> None:
    owner_headers = _auth_headers(client, email="owner@example.com")
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=owner_headers).json()[
        "id"
    ]

    other_headers = _auth_headers(client, email="other@example.com")
    response = client.delete(f"/projects/{project_id}", headers=other_headers)

    assert response.status_code == 404
    # The project must still exist for its real owner.
    assert client.get(f"/projects/{project_id}", headers=owner_headers).status_code == 200


def test_delete_project_404s_for_unknown_id(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.delete("/projects/does-not-exist", headers=headers)

    assert response.status_code == 404


def test_delete_project_requires_auth(client: TestClient) -> None:
    response = client.delete("/projects/does-not-exist")

    assert response.status_code == 401


def test_full_project_chapter_flow(client: TestClient) -> None:
    headers = _auth_headers(client)
    create_response = client.post("/projects", json={"title": "Thesis"}, headers=headers)
    project_id = create_response.json()["id"]

    empty_get = client.get(f"/projects/{project_id}", headers=headers)
    assert empty_get.status_code == 200
    assert empty_get.json()["chapters"] == []

    chapter_response = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    )
    assert chapter_response.status_code == 201
    chapter_body = chapter_response.json()
    assert chapter_body["title"] == "Introduction"
    assert chapter_body["project_id"] == project_id
    assert chapter_body["order"] == 0
    assert chapter_body["accepted_content"] is None
    assert chapter_body["pending_draft"] is None
    chapter_id = chapter_body["id"]

    populated_get = client.get(f"/projects/{project_id}", headers=headers)
    assert populated_get.status_code == 200
    populated_body = populated_get.json()
    assert len(populated_body["chapters"]) == 1
    fetched_chapter = populated_body["chapters"][0]
    assert fetched_chapter["id"] == chapter_id
    assert fetched_chapter["accepted_content"] is None
    assert fetched_chapter["pending_draft"] is None


def test_create_chapter_404s_for_unknown_project(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/projects/does-not-exist/chapters", json={"title": "Introduction"}, headers=headers
    )

    assert response.status_code == 404


@respx.mock
def test_generate_draft_creates_and_returns_draft_version(client: TestClient) -> None:
    _mock_generate_and_humanize(
        generated="Draft chapter body.", humanized="Humanized chapter body."
    )

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write an introduction about renewable energy."},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    version = body["version"]
    assert version["chapter_id"] == chapter_id
    assert version["content"] == "Humanized chapter body."
    assert version["status"] == "draft"
    assert version["version_number"] == 0

    precheck = body["precheck"]
    assert set(precheck.keys()) == {
        "plagiarism_score",
        "ai_fingerprint_score",
        "flagged",
        "reasons",
    }

    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    pending_draft = project_after["chapters"][0]["pending_draft"]
    assert pending_draft is not None
    assert pending_draft["id"] == version["id"]
    assert pending_draft["content"] == "Humanized chapter body."
    assert project_after["chapters"][0]["accepted_content"] is None


@respx.mock
def test_generate_draft_system_prompt_forbids_appending_a_bibliography_section(
    client: TestClient,
) -> None:
    """User report: a chat generation call didn't leave the project's own "Список
    использованных источников" chapter alone — it appended a references list inside the
    freshly generated chapter's own body instead. The model is only ever told to cite in-text;
    nothing routes a references list anywhere, so it must be told not to add one at all."""
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write an introduction about renewable energy."},
        headers=headers,
    )

    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    system_content = json.loads(generation_call.request.content)["messages"][0]["content"]
    assert "Список использованных источников" in system_content
    assert "never append" in system_content.lower()


@respx.mock
def test_generate_draft_system_prompt_requests_title_and_page_in_citations(
    client: TestClient,
) -> None:
    """User request: in-text citations should include the work's title and, when the excerpt
    indicates one, a page number — not just "(Author, Year)"."""
    _mock_generate_and_humanize()
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write an introduction about renewable energy."},
        headers=headers,
    )

    generation_call = next(
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and b'"deepseek-v4-pro"' in call.request.content
    )
    system_content = json.loads(generation_call.request.content)["messages"][0]["content"]
    assert '(Author, Year, "Title")' in system_content
    assert "[стр. N]" in system_content
    assert "Never invent a citation or a page number" in system_content


@respx.mock
def test_generate_draft_flagged_content_does_not_crash_precheck_reconstruction(
    client: TestClient,
) -> None:
    """Regression test for a bug where `_humanize_and_precheck` reconstructed
    `PlagiarismCheckResult` from `run_precheck_task`'s dict return value via plain
    `PlagiarismCheckResult(**precheck_dict)` construction, which does not recursively rehydrate
    the nested `sentence_flags: list[SentenceFlag]` — leaving it as a `list[dict]` instead. That
    silently violated the dataclass's contract for any generation whose humanized content
    actually earns a flagged sentence (empty-`sentence_flags` content, as most of this module's
    other tests use, round-trips fine by accident and never exercised the bug).

    The humanized text below repeats the same sentence starter four times, which
    `plagiarism.precheck.flag_sentences`'s repeated-starter heuristic reliably flags as
    `is_ai_like=True` per sentence (see `test_plagiarism.py`'s
    `test_flag_sentences_repeated_starter_is_flagged_ai_like`), guaranteeing a non-empty
    `sentence_flags` on the reconstructed `PlagiarismCheckResult` this endpoint builds internally.
    """
    humanized = (
        "Furthermore, the results were significant. Furthermore, the data was consistent. "
        "Furthermore, the trend was clear. Furthermore, the outcome was expected."
    )
    _mock_generate_and_humanize(generated="Draft chapter body.", humanized=humanized)

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write an introduction."},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["version"]["content"] == humanized
    assert set(body["precheck"].keys()) == {
        "plagiarism_score",
        "ai_fingerprint_score",
        "flagged",
        "reasons",
    }


def test_plagiarism_result_from_task_dict_rehydrates_sentence_flags_as_dataclasses() -> None:
    """Direct unit test of the reconstruction helper itself (`_plagiarism_result_from_task_dict`,
    used by both `_humanize_and_precheck` and the streaming endpoint's copy of the same logic):
    given a dict shaped exactly like `run_precheck_task`'s real return value (nested
    `sentence_flags` as plain dicts, matching `dataclasses.asdict`'s recursive conversion), the
    reconstructed `PlagiarismCheckResult.sentence_flags` entries must be real `SentenceFlag`
    instances — attribute access (`flag.text`, as `plagiarism.router.SentenceFlagResponse.
    from_flag` does) must not raise `AttributeError`, which it would if `sentence_flags` were
    left as `list[dict]` (the exact bug this test guards against: the endpoint-level tests above
    only exercise the "does it crash" question end to end, but `GenerateDraftResponse` doesn't
    itself surface `sentence_flags`, so this is the only test that actually inspects the
    reconstructed types)."""
    import diploma_backend.projects.router as router_module
    from diploma_backend.plagiarism.precheck import SentenceFlag
    from diploma_backend.plagiarism.tasks import run_precheck_task

    humanized = (
        "Furthermore, the results were significant. Furthermore, the data was consistent."
    )
    precheck_dict = run_precheck_task.delay(humanized, []).get()

    result = router_module._plagiarism_result_from_task_dict(precheck_dict)

    assert len(result.sentence_flags) >= 1
    for flag in result.sentence_flags:
        assert isinstance(flag, SentenceFlag)
        assert isinstance(flag.text, str)
        assert isinstance(flag.plagiarism_score, float)


@respx.mock
def test_generate_draft_llm_failure_returns_502(client: TestClient) -> None:
    _mock_empty_rag_search()
    respx.post(_CHAT_URL).mock(return_value=_fail_response())

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=headers,
    )

    assert response.status_code == 502


@respx.mock
def test_generate_draft_humanize_dropped_citation_falls_back_to_raw_content(
    client: TestClient,
) -> None:
    """`HumanizationError` (a dropped/mangled `__CITATION_N__` placeholder, per
    `humanizer.pipeline.restore_citations`) must fail open through the Celery task boundary
    (ADR-0013, TASK-E17-4, `_humanize_and_precheck`), falling back to the pre-humanization draft
    content rather than surfacing an error to the caller."""
    _mock_empty_rag_search()
    generated = "This baseline was established by prior work (Smith, 2020)."
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=_success_response(generated)
    )
    # The humanizer's own system prompt asks the model to preserve the __CITATION_0__ placeholder
    # it inserts in place of "(Smith, 2020)"; this response drops it, matching
    # `test_humanizer_tasks.py::test_dropped_citation_placeholder_propagates_as_real_exception`.
    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(
        return_value=_success_response("This baseline is well known.")
    )

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["version"]["content"] == generated


@respx.mock
def test_generate_draft_humanize_llm_failure_falls_back_to_raw_content(client: TestClient) -> None:
    """A genuine `LLMRequestError` from the humanize call (every internal retry inside
    `humanize_text_task` exhausted) must fail open to the raw, pre-humanization draft content
    rather than discarding an already-generated (and already-paid-for, "heavy" tier) draft with a
    502 — humanization is cosmetic, not correctness-critical, so its own retries being exhausted
    must never lose already-completed generation work (see `_humanize_and_precheck`'s
    docstring)."""
    _mock_empty_rag_search()
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=_success_response("Draft chapter body.")
    )
    respx.post(_CHAT_URL, json__model="deepseek-v4-flash").mock(return_value=_fail_response())

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["version"]["content"] == "Draft chapter body."


@respx.mock
def test_generate_draft_humanize_timeout_falls_back_to_raw_content(
    client: TestClient, monkeypatch
) -> None:
    """A `celery.exceptions.TimeoutError` from `_run_humanize`'s `.get(timeout=...)` — this
    handler's own wait giving up, not a failure of the humanize call itself, e.g. because the
    task is still legitimately running past `_HUMANIZE_TASK_TIMEOUT_SECONDS` (observed in
    production: 90-100s for a single `generate_with_retry` attempt) — must fail open to the raw,
    pre-humanization draft content the same way `LLMRequestError`/`HumanizationError` do, not
    crash the request (this was previously uncaught and propagated as an unhandled exception)."""
    from celery.exceptions import TimeoutError as CeleryTimeoutError

    import diploma_backend.projects.router as router_module

    _mock_empty_rag_search()
    respx.post(_CHAT_URL, json__model="deepseek-v4-pro").mock(
        return_value=_success_response("Draft chapter body.")
    )

    class _SlowAsyncResult:
        def get(self, timeout=None):
            raise CeleryTimeoutError("The operation timed out.")

    monkeypatch.setattr(
        router_module.humanize_text_task, "delay", lambda *args, **kwargs: _SlowAsyncResult()
    )

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["version"]["content"] == "Draft chapter body."


@respx.mock
def test_generate_draft_precheck_failure_falls_back_to_all_clear_result(
    client: TestClient, monkeypatch
) -> None:
    """`run_precheck_task` failing outright (defensive: it is pure/synchronous/no I/O and
    essentially cannot fail in practice, but must still fail open per `_run_precheck_with_
    fallback`) must not discard the already-generated, already-humanized draft — the draft is
    still persisted and returned, with an all-clear `PlagiarismCheckResult` standing in for the
    unavailable precheck."""
    import diploma_backend.projects.router as router_module

    _mock_generate_and_humanize(generated="Draft chapter body.", humanized="Humanized body.")

    def _raise_delay(*args, **kwargs):
        raise RuntimeError("precheck worker unavailable")

    monkeypatch.setattr(router_module.run_precheck_task, "delay", _raise_delay)

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["version"]["content"] == "Humanized body."
    assert body["precheck"] == {
        "plagiarism_score": 0.0,
        "ai_fingerprint_score": 0.0,
        "flagged": False,
        "reasons": [],
    }


@respx.mock
def test_generate_draft_auto_titles_a_default_titled_project(client: TestClient) -> None:
    """First generation on a still-default-titled project (Phase 5.9): the project's title is
    replaced with the LLM-generated one."""
    _mock_generate_humanize_and_title(title_response=_success_response("Renewable Energy Policy"))

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={}, headers=headers).json()["id"]
    assert client.get(f"/projects/{project_id}", headers=headers).json()["title"] == (
        "Untitled Thesis"
    )
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write an introduction about renewable energy."},
        headers=headers,
    )

    assert response.status_code == 201
    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    assert project_after["title"] == "Renewable Energy Policy"

    title_calls = [
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and _is_title_request(call.request)
    ]
    assert len(title_calls) == 1


@respx.mock
def test_generate_draft_does_not_retitle_an_already_titled_project(client: TestClient) -> None:
    """Once a project's title has been auto-generated once, a second generation call must not
    trigger another title-generation call (idempotent via the title-equality check)."""
    _mock_generate_humanize_and_title(title_response=_success_response("Renewable Energy Policy"))

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    first = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write an introduction about renewable energy."},
        headers=headers,
    )
    assert first.status_code == 201
    assert client.get(f"/projects/{project_id}", headers=headers).json()["title"] == (
        "Renewable Energy Policy"
    )

    second = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write a second paragraph."},
        headers=headers,
    )
    assert second.status_code == 201
    assert client.get(f"/projects/{project_id}", headers=headers).json()["title"] == (
        "Renewable Energy Policy"
    )

    title_calls = [
        call
        for call in respx.calls
        if call.request.url == _CHAT_URL and _is_title_request(call.request)
    ]
    assert len(title_calls) == 1


@respx.mock
def test_generate_draft_title_generation_failure_does_not_break_main_flow(
    client: TestClient,
) -> None:
    """A failing title-generation call (fail-open) must not break the main draft-generation
    response, and must leave the project's title at its default."""
    _mock_generate_humanize_and_title(title_response=_fail_response())

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write an introduction about renewable energy."},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["version"]["content"] == "Humanized chapter body."
    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    assert project_after["title"] == "Untitled Thesis"


def test_generate_draft_404s_for_unknown_chapter(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]

    response = client.post(
        f"/projects/{project_id}/chapters/does-not-exist/generate",
        json={"instruction": "Write something."},
        headers=headers,
    )

    assert response.status_code == 404


def test_generate_draft_404s_when_chapter_belongs_to_other_project(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_a = client.post("/projects", json={"title": "Thesis A"}, headers=headers).json()["id"]
    project_b = client.post("/projects", json={"title": "Thesis B"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_a}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]

    response = client.post(
        f"/projects/{project_b}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=headers,
    )

    assert response.status_code == 404


def test_generate_draft_404s_for_other_owners_project(client: TestClient) -> None:
    """Regression test for TASK-E16-2's ownership fix: adding `get_current_user_id` to this
    endpoint (needed for `applied_by`) must not stop at "some valid token" — it must also verify
    the caller actually owns `project_id`, the same as every other project-scoped endpoint."""
    owner_headers = _auth_headers(client, email="owner@example.com")
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=owner_headers).json()[
        "id"
    ]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=owner_headers
    ).json()["id"]

    other_headers = _auth_headers(client, email="other@example.com")
    response = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=other_headers,
    )

    assert response.status_code == 404


def test_insert_chapter_between_existing_chapters(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_1 = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Chapter 1"}, headers=headers
    ).json()
    chapter_3 = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Chapter 3"}, headers=headers
    ).json()
    assert chapter_1["order"] == 0
    assert chapter_3["order"] == 1

    response = client.post(
        f"/projects/{project_id}/chapters/insert", json={"title": "Chapter 2"}, headers=headers
    )

    assert response.status_code == 201
    inserted = response.json()
    assert inserted["title"] == "Chapter 2"
    assert inserted["project_id"] == project_id
    assert inserted["order"] == 1
    assert inserted["accepted_content"] is None
    assert inserted["pending_draft"] is None

    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    chapters_by_id = {chapter["id"]: chapter for chapter in project_after["chapters"]}
    assert chapters_by_id[chapter_1["id"]]["order"] == 0
    assert chapters_by_id[inserted["id"]]["order"] == 1
    assert chapters_by_id[chapter_3["id"]]["order"] == 2


def test_insert_chapter_without_numeric_title_appends_at_end(client: TestClient) -> None:
    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_1 = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Chapter 1"}, headers=headers
    ).json()
    chapter_2 = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Chapter 2"}, headers=headers
    ).json()

    response = client.post(
        f"/projects/{project_id}/chapters/insert", json={"title": "Conclusion"}, headers=headers
    )

    assert response.status_code == 201
    inserted = response.json()
    assert inserted["title"] == "Conclusion"
    assert inserted["order"] == 2

    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    chapters_by_id = {chapter["id"]: chapter for chapter in project_after["chapters"]}
    assert chapters_by_id[chapter_1["id"]]["order"] == 0
    assert chapters_by_id[chapter_2["id"]]["order"] == 1
    assert chapters_by_id[inserted["id"]]["order"] == 2


def test_insert_chapter_404s_for_unknown_project(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/projects/does-not-exist/chapters/insert", json={"title": "Chapter 2"}, headers=headers
    )

    assert response.status_code == 404


def test_accept_draft_404s_for_unknown_version(client: TestClient) -> None:
    response = client.post("/versions/does-not-exist/accept")

    assert response.status_code == 404


@respx.mock
def test_accept_already_accepted_draft_returns_409(client: TestClient) -> None:
    _mock_generate_and_humanize()

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    draft = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=headers,
    ).json()["version"]

    first_accept = client.post(f"/versions/{draft['id']}/accept")
    assert first_accept.status_code == 200
    assert first_accept.json()["status"] == "accepted"

    second_accept = client.post(f"/versions/{draft['id']}/accept")
    assert second_accept.status_code == 409


def test_reject_draft_404s_for_unknown_version(client: TestClient) -> None:
    response = client.post("/versions/does-not-exist/reject")

    assert response.status_code == 404


@respx.mock
def test_reject_draft_flips_status_and_clears_it_as_the_pending_draft(client: TestClient) -> None:
    """User report: rejecting a draft used to only clear it from the frontend's own in-memory
    state, with no backend call at all — so the very next full project refetch (e.g. accepting a
    draft in a different chapter, which re-fetches the whole project) would resurrect the
    "rejected" draft as if it had never been dismissed."""
    _mock_generate_and_humanize()

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    draft = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=headers,
    ).json()["version"]

    reject_response = client.post(f"/versions/{draft['id']}/reject")
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"

    project_after = client.get(f"/projects/{project_id}", headers=headers).json()
    assert project_after["chapters"][0]["pending_draft"] is None


@respx.mock
def test_reject_already_accepted_draft_returns_409(client: TestClient) -> None:
    _mock_generate_and_humanize()

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    draft = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=headers,
    ).json()["version"]
    client.post(f"/versions/{draft['id']}/accept")

    response = client.post(f"/versions/{draft['id']}/reject")
    assert response.status_code == 409


@respx.mock
def test_reject_already_rejected_draft_returns_409(client: TestClient) -> None:
    _mock_generate_and_humanize()

    headers = _auth_headers(client)
    project_id = client.post("/projects", json={"title": "Thesis"}, headers=headers).json()["id"]
    chapter_id = client.post(
        f"/projects/{project_id}/chapters", json={"title": "Introduction"}, headers=headers
    ).json()["id"]
    draft = client.post(
        f"/projects/{project_id}/chapters/{chapter_id}/generate",
        json={"instruction": "Write something."},
        headers=headers,
    ).json()["version"]
    client.post(f"/versions/{draft['id']}/reject")

    response = client.post(f"/versions/{draft['id']}/reject")
    assert response.status_code == 409
