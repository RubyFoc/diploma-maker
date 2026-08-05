"""Tests for TASK-E07-3 (`POST /plagiarism/check`, standalone plagiarism/AI-fingerprint endpoint).

Uses the `client` fixture from `conftest.py`; this endpoint makes no DB/LLM calls, so the
in-memory Mongo override is irrelevant here but harmless to share.
"""

from fastapi.testclient import TestClient

# Same fixture text `test_plagiarism.py` uses for the "identical text scores high" case, reused
# here to keep the source-overlap assertion deterministic rather than fuzzy.
_SOURCE_EXCERPT = (
    "The mitochondria is the powerhouse of the cell and generates most of the chemical "
    "energy needed to power biochemical reactions within the cell through respiration."
)

_ORIGINAL_TEXT = (
    "Yesterday I watched a documentary about deep sea fish and learned that some species "
    "produce their own light through a process called bioluminescence in total darkness."
)


def test_check_plagiarism_original_text_no_sources_returns_low_scores(client: TestClient) -> None:
    response = client.post("/plagiarism/check", json={"text": _ORIGINAL_TEXT})

    assert response.status_code == 200
    body = response.json()
    assert body["flagged"] is False
    assert body["plagiarism_score"] == 0.0
    assert body["reasons"] == []


def test_check_plagiarism_text_matching_source_scores_higher(client: TestClient) -> None:
    matching_response = client.post(
        "/plagiarism/check",
        json={"text": _SOURCE_EXCERPT, "source_excerpts": [_SOURCE_EXCERPT]},
    )
    original_response = client.post(
        "/plagiarism/check",
        json={"text": _ORIGINAL_TEXT, "source_excerpts": [_SOURCE_EXCERPT]},
    )

    assert matching_response.status_code == 200
    assert original_response.status_code == 200
    assert (
        matching_response.json()["plagiarism_score"]
        > original_response.json()["plagiarism_score"]
    )


def test_check_plagiarism_empty_text_is_rejected(client: TestClient) -> None:
    response = client.post("/plagiarism/check", json={"text": ""})

    assert response.status_code == 422
