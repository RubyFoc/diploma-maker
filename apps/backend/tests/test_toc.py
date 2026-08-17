"""Tests for TASK-E10-2 (TOC upload + parser).

Builds tiny `.docx` fixtures on the fly with `python-docx`, matching
`test_formatting_upload.py`'s pattern, and exercises both `toc.parser.parse_toc` directly and the
`POST /projects/{project_id}/toc/upload` endpoint via `client` (see `conftest.py`).
"""

from io import BytesIO

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from fastapi.testclient import TestClient

from diploma_backend.toc.parser import TocParseError, parse_document_sections, parse_toc


def _auth_headers(client: TestClient, email: str = "student@example.com") -> dict:
    """Register a user and return an `Authorization` header, since project endpoints require
    auth as of TASK-E11-1 (see `test_auth.py`'s `_register`)."""
    response = client.post("/auth/register", json={"email": email, "password": "hunter22"})
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


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


def _build_word_toc_field_docx() -> bytes:
    """Mimics a `.docx` containing just Word's auto-generated "Table of Contents" field, copied
    out on its own — the style Word actually gives each entry (`"TOC 1"`) rather than
    `"Heading 1"` or a manually-typed number, with a tab-separated page number the way Word's
    field renders it (not literal dot-leader text)."""
    document = Document()
    document.styles.add_style("TOC 1", WD_STYLE_TYPE.PARAGRAPH)
    document.styles.add_style("TOC 2", WD_STYLE_TYPE.PARAGRAPH)
    for title, page in [("Введение", 3), ("Обзор литературы", 5), ("Заключение", 20)]:
        paragraph = document.add_paragraph(title, style="TOC 1")
        paragraph.add_run(f"\t{page}")
    subsection = document.add_paragraph("Подраздел 1.1", style="TOC 2")
    subsection.add_run("\t6")
    return _docx_bytes(document)


def _build_list_numbered_docx() -> bytes:
    """Mimics a TOC where the numbering came from clicking Word's numbered-list button (style
    `"List Number"`) rather than typing "1. " by hand — the rendered number lives in the list
    definition (`w:numPr`), not in the paragraph's own text."""
    document = Document()
    document.add_paragraph("Введение", style="List Number")
    document.add_paragraph("Обзор литературы", style="List Number")
    document.add_paragraph("Заключение", style="List Number")
    return _docx_bytes(document)


def _build_mixed_numbered_and_unnumbered_docx() -> bytes:
    """Mimics a real Russian thesis TOC: numbered chapters plus conventionally-unnumbered
    front/back matter (introduction/conclusion/references), each with a dot-leader or
    tab-separated page number but no leading digit on the unnumbered entries."""
    document = Document()
    document.add_paragraph("ВВЕДЕНИЕ .......... 3")
    document.add_paragraph("1 Теоретические основы .......... 5")
    document.add_paragraph("2 Практическая часть .......... 15")
    document.add_paragraph("ЗАКЛЮЧЕНИЕ .......... 25")
    section = document.add_paragraph("СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ")
    section.add_run("\t27")
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


def test_parse_toc_includes_unnumbered_entries_alongside_numbered_ones() -> None:
    titles = parse_toc(_build_mixed_numbered_and_unnumbered_docx())

    assert titles == [
        "ВВЕДЕНИЕ",
        "Теоретические основы",
        "Практическая часть",
        "ЗАКЛЮЧЕНИЕ",
        "СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ",
    ]


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


def test_parse_toc_uses_word_toc_field_level_1_entries() -> None:
    titles = parse_toc(_build_word_toc_field_docx())

    assert titles == ["Введение", "Обзор литературы", "Заключение"]


def test_parse_toc_uses_top_level_list_numbered_paragraphs() -> None:
    titles = parse_toc(_build_list_numbered_docx())

    assert titles == ["Введение", "Обзор литературы", "Заключение"]


def test_upload_toc_creates_chapters_in_order(client: TestClient) -> None:
    headers = _auth_headers(client)
    create_response = client.post("/projects", json={"title": "My Thesis"}, headers=headers)
    project_id = create_response.json()["id"]

    response = client.post(
        f"/projects/{project_id}/toc/upload",
        files={"file": ("toc.docx", _build_numbered_docx(), "application/vnd.openxmlformats")},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == project_id
    titles = [chapter["title"] for chapter in body["chapters"]]
    assert titles == ["Introduction", "Literature Review", "Conclusion"]
    orders = [chapter["order"] for chapter in body["chapters"]]
    assert orders == sorted(orders)


def test_upload_toc_nonexistent_project_404s(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/projects/does-not-exist/toc/upload",
        files={"file": ("toc.docx", _build_numbered_docx(), "application/vnd.openxmlformats")},
        headers=headers,
    )

    assert response.status_code == 404


def test_upload_toc_invalid_file_422s(client: TestClient) -> None:
    headers = _auth_headers(client)
    create_response = client.post("/projects", json={"title": "My Thesis"}, headers=headers)
    project_id = create_response.json()["id"]

    response = client.post(
        f"/projects/{project_id}/toc/upload",
        files={"file": ("toc.docx", b"not a real docx file", "application/octet-stream")},
        headers=headers,
    )

    assert response.status_code == 422


# --- parse_document_sections / POST /{project_id}/document/upload (whole-document ingestion) ----


def test_parse_document_sections_splits_by_heading_1() -> None:
    sections = parse_document_sections(_build_heading_docx())

    assert sections == [
        ("Introduction", "Some body text under the introduction."),
        ("Literature Review", ""),
        ("Conclusion", ""),
    ]


def test_parse_document_sections_joins_multiple_paragraphs_per_section() -> None:
    document = Document()
    document.add_paragraph("Introduction", style="Heading 1")
    document.add_paragraph("First paragraph.")
    document.add_paragraph("Second paragraph.")

    sections = parse_document_sections(_docx_bytes(document))

    assert sections == [("Introduction", "First paragraph.\n\nSecond paragraph.")]


def test_parse_document_sections_drops_preamble_before_first_heading() -> None:
    document = Document()
    document.add_paragraph("Some cover-page text before any heading.")
    document.add_paragraph("Introduction", style="Heading 1")
    document.add_paragraph("Body text.")

    sections = parse_document_sections(_docx_bytes(document))

    assert sections == [("Introduction", "Body text.")]


def test_parse_document_sections_invalid_file_raises() -> None:
    try:
        parse_document_sections(b"not a real docx file")
        raise AssertionError("expected TocParseError")
    except TocParseError:
        pass


def test_parse_document_sections_no_headings_raises() -> None:
    try:
        parse_document_sections(_build_empty_docx())
        raise AssertionError("expected TocParseError")
    except TocParseError:
        pass


def test_upload_document_creates_chapters_with_content(client: TestClient) -> None:
    headers = _auth_headers(client)
    create_response = client.post("/projects", json={"title": "My Thesis"}, headers=headers)
    project_id = create_response.json()["id"]

    response = client.post(
        f"/projects/{project_id}/document/upload",
        files={"file": ("thesis.docx", _build_heading_docx(), "application/vnd.openxmlformats")},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    chapters = {chapter["title"]: chapter for chapter in body["chapters"]}
    assert set(chapters) == {"Introduction", "Literature Review", "Conclusion"}
    assert chapters["Introduction"]["pending_draft"]["content"] == (
        "Some body text under the introduction."
    )
    assert chapters["Literature Review"]["pending_draft"] is None


def test_upload_document_nonexistent_project_404s(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/projects/does-not-exist/document/upload",
        files={"file": ("thesis.docx", _build_heading_docx(), "application/vnd.openxmlformats")},
        headers=headers,
    )

    assert response.status_code == 404


def test_upload_document_no_headings_422s(client: TestClient) -> None:
    headers = _auth_headers(client)
    create_response = client.post("/projects", json={"title": "My Thesis"}, headers=headers)
    project_id = create_response.json()["id"]

    response = client.post(
        f"/projects/{project_id}/document/upload",
        files={"file": ("thesis.docx", _build_empty_docx(), "application/vnd.openxmlformats")},
        headers=headers,
    )

    assert response.status_code == 422
