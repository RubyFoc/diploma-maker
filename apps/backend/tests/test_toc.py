"""Tests for TASK-E10-2 (TOC upload + parser).

Builds tiny `.docx` fixtures on the fly with `python-docx`, matching
`test_formatting_upload.py`'s pattern, and exercises both `toc.parser.parse_toc` directly and the
`POST /projects/{project_id}/toc/upload` endpoint via `client` (see `conftest.py`).
"""

from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from diploma_backend.toc.parser import TocParseError, parse_toc


def _docx_bytes(document: Document) -> bytes:
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _build_heading_docx() -> bytes:
    document = Document()
    document.add_paragraph("Introduction", style="Heading 1")
    document.add_paragraph("Some body text under the introduction.")
    document.add_paragraph("Literature Review", style="Heading 1")
    document.add_paragraph("Conclusion", style="Heading 1")
    return _docx_bytes(document)


def _build_numbered_docx() -> bytes:
    document = Document()
    document.add_paragraph("Table of Contents")
    document.add_paragraph("1. Introduction")
    document.add_paragraph("2. Literature Review")
    document.add_paragraph("3) Conclusion")
    return _docx_bytes(document)


def _build_numbered_with_page_numbers_docx() -> bytes:
    document = Document()
    document.add_paragraph("1. Introduction .......... 5")
    document.add_paragraph("2. Literature Review .......... 12")
    return _docx_bytes(document)


def _build_empty_docx() -> bytes:
    document = Document()
    document.add_paragraph("Just some unrelated prose.")
    document.add_paragraph("Nothing here looks like a TOC entry at all.")
    return _docx_bytes(document)


def test_parse_toc_uses_heading_1_paragraphs() -> None:
    titles = parse_toc(_build_heading_docx())

    assert titles == ["Introduction", "Literature Review", "Conclusion"]


def test_parse_toc_falls_back_to_numbered_lines() -> None:
    titles = parse_toc(_build_numbered_docx())

    assert titles == ["Introduction", "Literature Review", "Conclusion"]


def test_parse_toc_strips_trailing_page_numbers() -> None:
    titles = parse_toc(_build_numbered_with_page_numbers_docx())

    assert titles == ["Introduction", "Literature Review"]


def test_parse_toc_invalid_file_raises() -> None:
    try:
        parse_toc(b"not a real docx file")
        raise AssertionError("expected TocParseError")
    except TocParseError:
        pass


def test_parse_toc_no_headings_or_numbered_lines_raises() -> None:
    try:
        parse_toc(_build_empty_docx())
        raise AssertionError("expected TocParseError")
    except TocParseError:
        pass


def test_upload_toc_creates_chapters_in_order(client: TestClient) -> None:
    create_response = client.post("/projects", json={"title": "My Thesis"})
    project_id = create_response.json()["id"]

    response = client.post(
        f"/projects/{project_id}/toc/upload",
        files={"file": ("toc.docx", _build_numbered_docx(), "application/vnd.openxmlformats")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == project_id
    titles = [chapter["title"] for chapter in body["chapters"]]
    assert titles == ["Introduction", "Literature Review", "Conclusion"]
    orders = [chapter["order"] for chapter in body["chapters"]]
    assert orders == sorted(orders)


def test_upload_toc_nonexistent_project_404s(client: TestClient) -> None:
    response = client.post(
        "/projects/does-not-exist/toc/upload",
        files={"file": ("toc.docx", _build_numbered_docx(), "application/vnd.openxmlformats")},
    )

    assert response.status_code == 404


def test_upload_toc_invalid_file_422s(client: TestClient) -> None:
    create_response = client.post("/projects", json={"title": "My Thesis"})
    project_id = create_response.json()["id"]

    response = client.post(
        f"/projects/{project_id}/toc/upload",
        files={"file": ("toc.docx", b"not a real docx file", "application/octet-stream")},
    )

    assert response.status_code == 422
