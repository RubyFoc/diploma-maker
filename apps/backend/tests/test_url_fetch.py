"""Tests for `sources.url_fetch` (user request: ground a required source directly from its own
citation URL instead of only re-searching academic APIs by author/title).
"""

import socket
from io import BytesIO
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from docx import Document
from pypdf import PdfWriter
from pypdf.errors import PdfReadError

from diploma_backend.sources.url_fetch import (
    UrlFetchError,
    _extract_pdf_text_with_page_markers,
    fetch_url_text,
)

_PUBLIC_IP = "93.184.216.34"


def _mock_public_dns():
    return patch(
        "socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_IP, 0))],
    )


def _docx_bytes(paragraphs: list[str]) -> bytes:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf_bytes(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    # pypdf's PdfWriter has no simple "add text" helper — a blank page is enough to exercise the
    # extraction *path* (content-type/extension routing to `extract_text_from_pdf`); the actual
    # empty-text-raises-UrlFetchError case is covered by `test_pdf_with_no_extractable_text_raises`.
    del page
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestSsrfGuard:
    async def test_rejects_non_http_scheme(self) -> None:
        with pytest.raises(UrlFetchError):
            await fetch_url_text("file:///etc/passwd")

    async def test_rejects_url_with_no_hostname(self) -> None:
        with pytest.raises(UrlFetchError):
            await fetch_url_text("http://")

    async def test_rejects_loopback_address(self) -> None:
        with pytest.raises(UrlFetchError):
            await fetch_url_text("http://127.0.0.1/secret")

    async def test_rejects_link_local_address(self) -> None:
        # The classic cloud-metadata-endpoint SSRF target (AWS/GCP/Azure all serve instance
        # credentials from this address).
        with pytest.raises(UrlFetchError):
            await fetch_url_text("http://169.254.169.254/latest/meta-data/")

    async def test_rejects_private_network_address(self) -> None:
        with pytest.raises(UrlFetchError):
            await fetch_url_text("http://10.0.0.5/internal")

    async def test_rejects_unresolvable_host(self) -> None:
        with (
            patch("socket.getaddrinfo", side_effect=OSError("name resolution failed")),
            pytest.raises(UrlFetchError),
        ):
            await fetch_url_text("http://does-not-exist.invalid/paper.pdf")


def _fake_pdf_reader(page_texts: list[str]) -> MagicMock:
    """A `pypdf.PdfReader` stand-in whose `.pages[i].extract_text()` returns `page_texts[i]` —
    used because `pypdf.PdfWriter` has no simple "draw real text" API without reportlab (same
    constraint `test_plagiarism_extract.py` documents), so a real multi-page PDF with actual
    extractable text per page can't easily be constructed for these tests."""
    reader = MagicMock()
    pages = []
    for text in page_texts:
        page = MagicMock()
        page.extract_text.return_value = text
        pages.append(page)
    reader.pages = pages
    return reader


class TestExtractPdfTextWithPageMarkers:
    def test_prefixes_each_page_with_a_marker(self) -> None:
        reader = _fake_pdf_reader(["First page text.", "Second page text."])

        with patch("diploma_backend.sources.url_fetch.PdfReader", return_value=reader):
            text = _extract_pdf_text_with_page_markers(b"fake-pdf-bytes")

        assert text == "[стр. 1]\nFirst page text.\n\n[стр. 2]\nSecond page text."

    def test_drops_blank_pages_entirely(self) -> None:
        reader = _fake_pdf_reader(["   ", "Real content on page two."])

        with patch("diploma_backend.sources.url_fetch.PdfReader", return_value=reader):
            text = _extract_pdf_text_with_page_markers(b"fake-pdf-bytes")

        assert text == "[стр. 2]\nReal content on page two."
        assert "[стр. 1]" not in text

    def test_all_blank_pages_returns_empty_string(self) -> None:
        reader = _fake_pdf_reader(["", "   "])

        with patch("diploma_backend.sources.url_fetch.PdfReader", return_value=reader):
            text = _extract_pdf_text_with_page_markers(b"fake-pdf-bytes")

        assert text == ""

    def test_raises_on_invalid_pdf(self) -> None:
        with patch(
            "diploma_backend.sources.url_fetch.PdfReader", side_effect=PdfReadError("bad file")
        ), pytest.raises(UrlFetchError):
            _extract_pdf_text_with_page_markers(b"not a pdf")


class TestFetchAndExtract:
    @respx.mock
    async def test_pdf_link_carries_page_markers_the_generation_prompt_can_cite(self) -> None:
        """User request: an in-text citation should include a real page number when one is
        available — only possible for a PDF, since that's the one format with directly readable
        page boundaries (see module docstring)."""
        reader = _fake_pdf_reader(["Text from the first page.", "Text from the second page."])
        with _mock_public_dns(), patch(
            "diploma_backend.sources.url_fetch.PdfReader", return_value=reader
        ):
            respx.get("http://example.com/paper.pdf").mock(
                return_value=httpx.Response(
                    200, content=b"irrelevant-mocked-body", headers={"content-type": "application/pdf"}
                )
            )
            text = await fetch_url_text("http://example.com/paper.pdf")

        assert text == "[стр. 1]\nText from the first page.\n\n[стр. 2]\nText from the second page."

    @respx.mock
    async def test_pdf_link_with_no_text_layer_raises(self) -> None:
        # pypdf's writer has no simple "draw text" API without reportlab (same constraint
        # `test_plagiarism_extract.py` documents) — a blank page exercises PDF-branch routing (by
        # content-type) without asserting real extracted content.
        with _mock_public_dns():
            respx.get("http://example.com/paper.pdf").mock(
                return_value=httpx.Response(
                    200,
                    content=_pdf_bytes(""),
                    headers={"content-type": "application/pdf"},
                )
            )
            with pytest.raises(UrlFetchError):
                await fetch_url_text("http://example.com/paper.pdf")

    @respx.mock
    async def test_extracts_text_from_a_docx_link(self) -> None:
        with _mock_public_dns():
            respx.get("http://example.com/paper.docx").mock(
                return_value=httpx.Response(
                    200,
                    content=_docx_bytes(["First paragraph.", "Second paragraph."]),
                    headers={
                        "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    },
                )
            )
            text = await fetch_url_text("http://example.com/paper.docx")

        assert "First paragraph." in text
        assert "Second paragraph." in text

    @respx.mock
    async def test_extracts_docx_by_file_extension_even_without_a_matching_content_type(self) -> None:
        with _mock_public_dns():
            respx.get("http://example.com/paper.docx").mock(
                return_value=httpx.Response(
                    200,
                    content=_docx_bytes(["Content served with a generic content-type."]),
                    headers={"content-type": "application/octet-stream"},
                )
            )
            text = await fetch_url_text("http://example.com/paper.docx")

        assert "Content served with a generic content-type." in text

    @respx.mock
    async def test_extracts_visible_text_from_html_and_strips_scripts_and_nav(self) -> None:
        html = """
        <html>
          <head><style>body { color: red; }</style></head>
          <body>
            <nav>Site navigation</nav>
            <script>console.log('tracked')</script>
            <article><h1>Article Title</h1><p>The actual article body text.</p></article>
            <footer>Copyright notice</footer>
          </body>
        </html>
        """
        with _mock_public_dns():
            respx.get("http://example.com/article").mock(
                return_value=httpx.Response(200, content=html, headers={"content-type": "text/html"})
            )
            text = await fetch_url_text("http://example.com/article")

        assert "Article Title" in text
        assert "The actual article body text." in text
        assert "Site navigation" not in text
        assert "tracked" not in text
        assert "Copyright notice" not in text

    @respx.mock
    async def test_raises_on_http_error_status(self) -> None:
        with _mock_public_dns():
            respx.get("http://example.com/missing.pdf").mock(return_value=httpx.Response(404))
            with pytest.raises(UrlFetchError):
                await fetch_url_text("http://example.com/missing.pdf")

    @respx.mock
    async def test_raises_when_html_page_has_no_visible_text(self) -> None:
        with _mock_public_dns():
            respx.get("http://example.com/empty").mock(
                return_value=httpx.Response(
                    200, content="<html><head></head><body>   </body></html>",
                    headers={"content-type": "text/html"},
                )
            )
            with pytest.raises(UrlFetchError):
                await fetch_url_text("http://example.com/empty")
