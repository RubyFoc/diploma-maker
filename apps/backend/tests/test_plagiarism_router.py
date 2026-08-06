"""Tests for TASK-E07-3 (`POST /plagiarism/check`, standalone plagiarism/AI-fingerprint endpoint).

Uses the `client` fixture from `conftest.py`; this endpoint makes no DB/LLM calls, so the
in-memory Mongo override is irrelevant here but harmless to share.
"""

from io import BytesIO

from docx import Document
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


def _build_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_check_plagiarism_file_docx_returns_scores(client: TestClient) -> None:
    docx_bytes = _build_docx_bytes(_ORIGINAL_TEXT)

    response = client.post(
        "/plagiarism/check-file",
        files={"file": ("sample.docx", docx_bytes, "application/vnd.openxmlformats")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["flagged"] is False
    assert "originality_score" in body
    assert "sentence_flags" in body


def test_check_plagiarism_file_invalid_docx_returns_4xx_not_500(client: TestClient) -> None:
    response = client.post(
        "/plagiarism/check-file",
        files={"file": ("sample.docx", b"not a real docx file", "application/octet-stream")},
    )

    assert 400 <= response.status_code < 500


def test_check_plagiarism_file_unsupported_extension_returns_4xx(client: TestClient) -> None:
    response = client.post(
        "/plagiarism/check-file",
        files={"file": ("sample.txt", b"some plain text", "text/plain")},
    )

    assert 400 <= response.status_code < 500
