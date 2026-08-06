"""Tests for `plagiarism.extract` (text extraction from uploaded `.docx`/`.pdf` files).

Builds tiny in-memory `.docx`/`.pdf` fixtures rather than committing binary files, matching
`test_formatting_upload.py`'s `.docx`-fixture pattern. `.pdf` fixtures are built with `pypdf`'s
writer since it's already a dependency of this module — no extra library needed for tests.
"""

from io import BytesIO

import pytest
from docx import Document
from pypdf import PdfWriter

from diploma_backend.plagiarism.extract import (
    PlagiarismFileParseError,
    extract_text,
    extract_text_from_docx,
    extract_text_from_pdf,
)


def _build_docx_bytes(paragraphs: list[str]) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _build_pdf_bytes_with_text(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    page.merge_page(page)
    # pypdf's writer has no simple "draw text" API without reportlab; a blank page with no text
    # layer is exactly the "no extractable text" case this module needs to fail closed on.
    del text
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_extract_text_from_docx_joins_non_empty_paragraphs() -> None:
    docx_bytes = _build_docx_bytes(["First paragraph.", "", "Second paragraph."])

    text = extract_text_from_docx(docx_bytes)

    assert text == "First paragraph.\nSecond paragraph."


def test_extract_text_from_docx_invalid_file_raises() -> None:
    with pytest.raises(PlagiarismFileParseError):
        extract_text_from_docx(b"not a real docx file")


def test_extract_text_from_pdf_blank_page_raises_no_extractable_text() -> None:
    pdf_bytes = _build_pdf_bytes_with_text("irrelevant, page is blank")

    with pytest.raises(PlagiarismFileParseError):
        extract_text_from_pdf(pdf_bytes)


def test_extract_text_from_pdf_invalid_file_raises() -> None:
    with pytest.raises(PlagiarismFileParseError):
        extract_text_from_pdf(b"not a real pdf file")


def test_extract_text_dispatches_on_extension() -> None:
    docx_bytes = _build_docx_bytes(["Some content."])

    assert extract_text("sample.docx", docx_bytes) == "Some content."


def test_extract_text_unsupported_extension_raises() -> None:
    with pytest.raises(PlagiarismFileParseError):
        extract_text("sample.txt", b"some content")
