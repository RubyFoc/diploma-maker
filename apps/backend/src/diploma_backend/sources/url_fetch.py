"""Fetches a user-supplied required-source URL directly and extracts its plain text (user
request: a citation's own `URL: ...` link should be used as grounding, instead of the app only
ever re-searching external academic APIs by author/title — see `projects.router
._fetch_required_source_excerpts`'s module-level fallback chain for where this fits).

Security note: `url` here is arbitrary, user-supplied input that this module's caller fetches
server-side — a classic SSRF surface (a malicious `url` could otherwise target this server's own
internal network, a cloud metadata endpoint, etc.). `_ensure_safe_url` resolves the hostname and
rejects anything that isn't a public, routable address before any request is made.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from diploma_backend.plagiarism.extract import (
    PlagiarismFileParseError,
    extract_text_from_docx,
    extract_text_from_pdf,
)

_ALLOWED_SCHEMES = {"http", "https"}
_TIMEOUT_SECONDS = 20.0
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


def _extract_html_text(content: bytes) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(_HTML_NOISE_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


async def fetch_url_text(url: str) -> str:
    """Fetches `url` and extracts its plain text: `.pdf`/`.docx` (by `Content-Type` or file
    extension) via the same extractors `plagiarism.extract` uses for uploaded files, anything
    else treated as HTML.

    Raises `UrlFetchError` for an unsafe URL, any network/HTTP failure, or a document with no
    extractable text — never returns an empty string.
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

    try:
        if any(t in content_type for t in _PDF_CONTENT_TYPES) or lower_url.endswith(".pdf"):
            text = extract_text_from_pdf(content)
        elif any(t in content_type for t in _DOCX_CONTENT_TYPES) or lower_url.endswith(".docx"):
            text = extract_text_from_docx(content)
        else:
            text = _extract_html_text(content)
    except PlagiarismFileParseError as exc:
        raise UrlFetchError(f"Could not extract text from URL: {url}") from exc

    if not text.strip():
        raise UrlFetchError(f"No extractable text found at URL: {url}")
    return text
