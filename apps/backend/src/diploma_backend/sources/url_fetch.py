"""Fetches a user-supplied required-source URL directly and extracts its plain text (user
request: a citation's own `URL: ...` link should be used as grounding, instead of the app only
ever re-searching external academic APIs by author/title — see `projects.router
._fetch_required_source_excerpts`'s module-level fallback chain for where this fits).

Security note: `url` here is arbitrary, user-supplied input that this module's caller fetches
server-side — a classic SSRF surface (a malicious `url` could otherwise target this server's own
internal network, a cloud metadata endpoint, etc.). `_ensure_safe_url` resolves the hostname and
rejects anything that isn't a public, routable address before any request is made.

PDF page markers (user request — "(Автор, год + статья + страницы (если возможно))" in-text
citations): a PDF is the one format this module handles where the source document's own page
boundaries are directly readable (`pypdf` extracts text per page; `.docx`'s page breaks are a
Word rendering-time concept with no reliable equivalent, and an HTML page has no pages at all).
`_extract_pdf_text_with_page_markers` prefixes each page's text with a `"[стр. N]"` marker so
`_GENERATION_SYSTEM_PROMPT`/`_ANCHOR_GENERATION_SYSTEM_PROMPT` can tell the model to cite a real
page number when one is available, instead of ever fabricating one.
"""

import ipaddress
import socket
from io import BytesIO
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from diploma_backend.plagiarism.extract import PlagiarismFileParseError, extract_text_from_docx

_ALLOWED_SCHEMES = {"http", "https"}
# User report: some real citation URLs (Belarusian university repositories, e.g. elib.bsu.by)
# were measured taking 10-22s just to establish a TCP connection, on top of whatever the actual
# transfer takes — comfortably exceeding the previous 20s ceiling and reporting the source as
# unmet even though the link was genuinely reachable, just slow. 45s trades slower generation for
# a source with an as-yet-uncached URL (this result is cached after the first successful fetch,
# see `projects.router._fetch_required_source_excerpts`) for a real chance of it succeeding
# instead of always failing outright.
_TIMEOUT_SECONDS = 45.0
# Caps how much of a response body is read — generous enough for any real journal-article PDF/
# HTML page, small enough to bound memory/time spent on an unexpectedly huge or malicious file.
_MAX_BYTES = 20 * 1024 * 1024

_PDF_CONTENT_TYPES = ("application/pdf",)
_DOCX_CONTENT_TYPES = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)
# Tags whose text is never part of a page's actual readable content (navigation, scripts,
# stylesheets, etc.) — stripped before extracting text, same reasoning a reader-mode/text
# extractor always applies.
_HTML_NOISE_TAGS = ("script", "style", "nav", "header", "footer", "noscript")


class UrlFetchError(Exception):
    """Raised when `fetch_url_text` cannot retrieve or extract usable text from a URL — an unsafe
    URL, a network/HTTP failure, an unsupported content type, or a document with no extractable
    text. Callers should treat this the same as any other failed grounding attempt (fail open,
    try the next fallback) rather than surfacing it to the end user directly.
    """


def _ensure_safe_url(url: str) -> None:
    """Raises `UrlFetchError` unless `url` is `http(s)` and resolves to a public, routable
    address — never a loopback/private/link-local/reserved one (SSRF guard, see module
    docstring). Resolves the hostname itself (not just string-matching it), so a DNS name that
    merely *points at* an internal address is still caught.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise UrlFetchError(f"Unsupported or malformed URL: {url}")

    try:
        addr_infos = socket.getaddrinfo(parsed.hostname, None)
    except OSError as exc:
        raise UrlFetchError(f"Could not resolve host for URL: {url}") from exc

    for family, _type, _proto, _canonname, sockaddr in addr_infos:
        host = sockaddr[0]
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise UrlFetchError(f"URL resolves to a non-public address, refusing to fetch: {url}")


def _extract_pdf_text_with_page_markers(content: bytes) -> str:
    """Extracts text from PDF bytes, one `"[стр. N]"`-prefixed block per page with any real
    extracted text (blank pages are dropped, not just emptied, so an all-blank PDF still comes
    out as `""` for `fetch_url_text`'s "no extractable text" check below).

    Deliberately not `plagiarism.extract.extract_text_from_pdf` — that function joins every
    page's text with no boundary markers at all, which is correct for its own purpose (a single
    plagiarism-similarity blob has no use for page numbers) but would give the generation prompt
    nothing to cite a real page number from.
    """
    try:
        reader = PdfReader(BytesIO(content))
    except PdfReadError as exc:
        raise UrlFetchError("Uploaded content is not a valid .pdf document") from exc

    pages = []
    for index, page in enumerate(reader.pages):
        page_text = (page.extract_text() or "").strip()
        if page_text:
            pages.append(f"[стр. {index + 1}]\n{page_text}")
    return "\n\n".join(pages)


def _extract_html_text(content: bytes) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(_HTML_NOISE_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


async def fetch_url_text(url: str) -> str:
    """Fetches `url` and extracts its plain text, routed by `Content-Type`/file extension:
    `.pdf` via `_extract_pdf_text_with_page_markers` (see module docstring — carries real
    `"[стр. N]"` page markers the generation prompt can cite from), `.docx` via
    `plagiarism.extract.extract_text_from_docx`, anything else treated as HTML.

    Raises `UrlFetchError` for an unsafe URL, any network/HTTP failure, an invalid PDF/DOCX, or a
    document with no extractable text — never returns an empty string.
    """
    _ensure_safe_url(url)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content[:_MAX_BYTES]
    except httpx.HTTPError as exc:
        raise UrlFetchError(f"Failed to fetch URL: {url}") from exc

    content_type = response.headers.get("content-type", "").lower()
    lower_url = url.lower()

    if any(t in content_type for t in _PDF_CONTENT_TYPES) or lower_url.endswith(".pdf"):
        text = _extract_pdf_text_with_page_markers(content)
    else:
        try:
            if any(t in content_type for t in _DOCX_CONTENT_TYPES) or lower_url.endswith(".docx"):
                text = extract_text_from_docx(content)
            else:
                text = _extract_html_text(content)
        except PlagiarismFileParseError as exc:
            raise UrlFetchError(f"Could not extract text from URL: {url}") from exc

    if not text.strip():
        raise UrlFetchError(f"No extractable text found at URL: {url}")
    return text
