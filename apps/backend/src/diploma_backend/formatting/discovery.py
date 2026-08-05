"""Auto-discovery of institution formatting requirements via web search (ADR-0005 addendum).

Implements the `source="auto"` path added to ADR-0005 on 2026-08-05: instead of always requiring
a manual `.docx` upload (`formatting.upload`, TASK-E05-2), this module tries to find a named
university's official thesis/VKR formatting requirements on the open web and extract page
margins and body font from whatever page it finds — a strictly weaker, best-effort substitute for
a verified upload, hence the low `accuracy_weight=0.3` baked into the config this module builds.

Pipeline: `search_formatting_pages` (DuckDuckGo HTML search, no API key) finds candidate page
URLs; `fetch_page_text` fetches and strips each one to plain text; `extract_margins_mm` and
`extract_font` run pragmatic regex heuristics over that text, in the same fail-closed spirit as
`formatting.upload`'s heuristics (return `None` rather than guess at data that wasn't clearly
present). `discover_institution_config` orchestrates all of the above and stops at the first
candidate page that yields both margins and font.

Known, intentional MVP limitation: PDF results (common for these methodological guides) are
skipped entirely rather than parsed — this module deliberately does not add a PDF-parsing
dependency. A single non-HTML or unreachable result is not a failure; discovery just moves on to
the next search result.
"""

import html
import re
import uuid
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from diploma_backend.formatting.models import (
    FontConfig,
    Headings,
    InstitutionConfig,
    MarginsMm,
    PageConfig,
)

_DDG_SEARCH_URL = "https://html.duckduckgo.com/html/"
_DEFAULT_TIMEOUT_SECONDS = 15.0
_DEFAULT_SEARCH_LIMIT = 5
_ACCURACY_WEIGHT = 0.3

# DuckDuckGo's keyless HTML search endpoint 403s a client with no User-Agent at all; this mimics
# a real browser, matching the coordinator's verified working `curl` test.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# DDG wraps each organic result as `//duckduckgo.com/l/?uddg=<url-encoded-target>&rut=...` inside
# `<a class="result__a" href="...">`. This is a narrow, well-defined pattern over raw HTML; the
# codebase has no HTML-parsing dependency (`beautifulsoup4`/`lxml`) and adding one for this one
# extraction isn't warranted.
_RESULT_LINK_RE = re.compile(r'class="result__a"[^>]*href="([^"]+)"')

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# "лев\w*"/"прав\w*" already match inside the adverb forms "слева"/"справа" (both contain "лев"/
# "прав" as a literal substring), but "верхн\w*"/"нижн\w*" do NOT match their adverb counterparts
# "сверху"/"снизу" — those use an entirely different root ("верх"/"низ", not "верхн"/"нижн"), so
# both the adjective root and the adverb form are matched explicitly for top/bottom.
_MARGIN_PATTERNS = {
    "left": re.compile(r"лев\w*\s*[-–:]\s*(\d+)\s*мм", re.IGNORECASE),
    "right": re.compile(r"прав\w*\s*[-–:]\s*(\d+)\s*мм", re.IGNORECASE),
    "top": re.compile(r"(?:верхн\w*|сверху)\s*[-–:]\s*(\d+)\s*мм", re.IGNORECASE),
    "bottom": re.compile(r"(?:нижн\w*|снизу)\s*[-–:]\s*(\d+)\s*мм", re.IGNORECASE),
}

# Real guides very commonly state top and bottom together with one shared value ("сверху и
# снизу – 20 мм" / "верхнее и нижнее – 20 мм") rather than repeating the number for each side —
# checked as a fallback for whichever of top/bottom the per-side patterns above didn't find.
_SHARED_TOP_BOTTOM_RE = re.compile(
    r"(?:сверху|верхн\w*)\s*(?:и|,)\s*(?:снизу|нижн\w*)\s*[-–:]\s*(\d+)\s*мм", re.IGNORECASE
)

_FONT_FAMILIES = ("Times New Roman", "Arial")

# "кег\w*" (not "кегл\w*") deliberately covers both the standard spelling "кегль" and the
# "кегель" variant seen in real methodological-guide text (e.g. "кегель: - 14 пт").
_FONT_SIZE_RE = re.compile(
    r"(?:кег\w*|размер\s+шрифта)[^\d]{0,20}(\d{1,2})\s*(?:пт|pt|п\.)", re.IGNORECASE
)

# Numeric line-spacing values (e.g. "интервал: 1.5" or "1,5 интервал") or their Russian word forms
# ("полуторный" = 1.5, "одинарный" = 1.0, "двойной" = 2.0), matched within ~30 characters of the
# word "интервал" in either direction.
_LINE_SPACING_NUMERIC_RE = re.compile(
    r"интервал.{0,30}?\b(1[.,]5|2|1)\b|\b(1[.,]5|2|1)\b.{0,30}?интервал", re.IGNORECASE
)
_LINE_SPACING_WORDS = {
    "полуторный": 1.5,
    "одинарный": 1.0,
    "двойной": 2.0,
}
_LINE_SPACING_WORD_RE = re.compile(
    r"интервал.{0,30}?\b(полуторный|одинарный|двойной)\b|\b(полуторный|одинарный|двойной)\b.{0,30}?интервал",
    re.IGNORECASE,
)

# GOST's own commonly-published default, used only as a fallback for line spacing specifically.
# Unlike margins/font-family/size, this codebase's `export/docx.py`'s `apply_institution_config`
# only feeds this into `Normal` style spacing (a soft, non-layout-critical value), not a
# dimension a mis-detected value would visibly break — so this is the one field allowed to
# default rather than fail closed.
_DEFAULT_LINE_SPACING = 1.5


class FormattingDiscoveryError(Exception):
    """Raised when the search step itself fails (network/parsing failure), so callers never
    need to catch raw `httpx` exceptions directly.

    Not raised for "nothing found" outcomes (per-page fetch/extraction misses) — those are a
    normal `DiscoveryResult(status="not_found", ...)`, not an error.
    """


@dataclass(frozen=True)
class DiscoveryResult:
    """Outcome of `discover_institution_config`.

    `source_url` records which candidate page a successful extraction came from, so a user or a
    future admin view can see where an auto-detected config's numbers were pulled from — `None`
    when `status="not_found"`.
    """

    status: Literal["found", "not_found"]
    config: InstitutionConfig | None
    source_url: str | None


async def search_formatting_pages(university_name: str, limit: int = _DEFAULT_SEARCH_LIMIT) -> list[str]:
    """Search DuckDuckGo's keyless HTML endpoint for `university_name`'s VKR formatting guides.

    Queries `f"{university_name} оформление ВКР методические указания поля шрифт"` and returns up
    to `limit` target page URLs, in the order DuckDuckGo returned them, decoded from the
    `//duckduckgo.com/l/?uddg=<url-encoded target>&rut=...` redirect wrapper DDG uses for organic
    results.

    Raises `FormattingDiscoveryError` on any network failure, non-2xx response, or if the
    response HTML doesn't parse into any result links at all.
    """
    query = f"{university_name} оформление ВКР методические указания поля шрифт"
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.get(
                _DDG_SEARCH_URL,
                params={"q": query},
                headers={"User-Agent": _USER_AGENT},
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise FormattingDiscoveryError(
            f"DuckDuckGo search failed with status {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise FormattingDiscoveryError(
            f"DuckDuckGo search failed: {type(exc).__name__}"
        ) from exc

    urls: list[str] = []
    for match in _RESULT_LINK_RE.finditer(response.text):
        target = _decode_ddg_redirect(match.group(1))
        if target is not None:
            urls.append(target)
        if len(urls) >= limit:
            break
    return urls


def _decode_ddg_redirect(href: str) -> str | None:
    """Extract and URL-decode the `uddg` query param from a DDG `/l/?uddg=...` redirect href."""
    parsed = urlparse(href.replace("&amp;", "&"))
    params = parse_qs(parsed.query)
    targets = params.get("uddg")
    if not targets:
        return None
    return unquote(targets[0])


async def fetch_page_text(url: str) -> str | None:
    """Fetch `url` and return its plain text with HTML tags stripped, or `None` if unavailable.

    Returns `None` (never raises) on any network failure (timeout, non-2xx, connection error) —
    a single bad search result must not abort the whole discovery attempt. Also returns `None` if
    the response `Content-Type` isn't `text/html` (case-insensitive prefix match): PDFs and other
    formats are an explicit, intentional MVP limitation, not a bug — this module has no
    PDF-parsing dependency and skips straight to the next search result instead.
    """
    try:
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = await client.get(url, headers={"User-Agent": _USER_AGENT})
            response.raise_for_status()
    except httpx.HTTPError:
        return None

    content_type = response.headers.get("content-type", "")
    if not content_type.lower().startswith("text/html"):
        return None

    # Real pages very commonly use HTML entities instead of literal characters (e.g. "&ndash;"
    # rather than "–" for the dash between a margin label and its value) — stripping tags alone
    # leaves those entities as literal escaped text, which silently defeats the extraction
    # regexes' `[-–:]` separator class below. Decode entities BEFORE stripping tags, so `&lt;`/
    # `&gt;` sequences that were never real tags don't get mistaken for one after decoding.
    unescaped = html.unescape(response.text)
    text = _TAG_RE.sub(" ", unescaped)
    return _WHITESPACE_RE.sub(" ", text).strip()


def extract_margins_mm(text: str) -> MarginsMm | None:
    """Extract all four page margins (mm) from Russian-language formatting-guide text.

    Matches e.g. "левое – 30 мм" / "правое: 15 мм" / "верхнее - 20 мм" / "нижнее – 20 мм", and
    also the adverb phrasing real guides commonly use instead ("слева – 30 мм", "справа – 10 мм",
    "сверху – 20 мм", "снизу – 20 мм") — see `_MARGIN_PATTERNS`'s comment for why top/bottom need
    an explicit adverb alternative while left/right don't. If top and/or bottom aren't found
    individually, also tries `_SHARED_TOP_BOTTOM_RE` for the common "сверху и снизу – 20 мм"
    combined phrasing (real guides frequently state top=bottom this way rather than repeating the
    number). `[-–:]` handles a hyphen, en-dash, or colon between the label and the number. Returns
    `None` unless ALL FOUR margins are found — partial margin data isn't safe to guess the rest
    of, per this codebase's fail-closed philosophy (`formatting.upload`).
    """
    values: dict[str, float] = {}
    for side, pattern in _MARGIN_PATTERNS.items():
        match = pattern.search(text)
        if match is not None:
            values[side] = float(match.group(1))

    if "top" not in values or "bottom" not in values:
        shared = _SHARED_TOP_BOTTOM_RE.search(text)
        if shared is not None:
            values.setdefault("top", float(shared.group(1)))
            values.setdefault("bottom", float(shared.group(1)))

    if not {"left", "right", "top", "bottom"} <= values.keys():
        return None
    return MarginsMm(**values)


def extract_font(text: str) -> FontConfig | None:
    """Extract body font family, point size, and (best-effort) line spacing from guide text.

    Family is matched against a small known list (`Times New Roman` first, then `Arial` — the
    two overwhelmingly common choices for GOST-style documents). Size is matched near "кегль"/
    "размер шрифта" followed by a point-size number. Line spacing is matched near "интервал" as
    either a literal value (1, 1.5, 2) or a Russian word form ("полуторный" etc.); if no line
    spacing is found, it defaults to `1.5` (GOST's common default) rather than failing closed —
    the one field this function allows to default, since `export/docx.py`'s
    `apply_institution_config` only uses it for `Normal` style spacing, a soft/lower-stakes value
    compared to margins or font family/size.

    Returns `None` unless BOTH family and size are found.
    """
    family = next((f for f in _FONT_FAMILIES if f.lower() in text.lower()), None)
    size_match = _FONT_SIZE_RE.search(text)
    if family is None or size_match is None:
        return None

    line_spacing = _extract_line_spacing(text)
    return FontConfig(
        family=family, size_pt=float(size_match.group(1)), line_spacing=line_spacing
    )


def _extract_line_spacing(text: str) -> float:
    numeric_match = _LINE_SPACING_NUMERIC_RE.search(text)
    if numeric_match is not None:
        raw = next(g for g in numeric_match.groups() if g is not None)
        return float(raw.replace(",", "."))

    word_match = _LINE_SPACING_WORD_RE.search(text)
    if word_match is not None:
        word = next(g for g in word_match.groups() if g is not None)
        return _LINE_SPACING_WORDS[word.lower()]

    return _DEFAULT_LINE_SPACING


async def discover_institution_config(university_name: str) -> DiscoveryResult:
    """Try to auto-discover `university_name`'s formatting requirements from the web.

    Searches for candidate pages (`search_formatting_pages`), then tries each in order: fetches
    and extracts margins/font from its text, skipping any page that isn't fetchable HTML
    (`fetch_page_text` returning `None`) or that doesn't yield both margins and a font. Returns a
    `"found"` result as soon as one page yields both, with `source_url` set to that page's URL.

    Returns `DiscoveryResult(status="not_found", config=None, source_url=None)` if no candidate
    page yields both — never builds a config from partial data. Lets `FormattingDiscoveryError`
    from the search step propagate: that is a genuine infrastructure failure, not a "nothing
    found" outcome.
    """
    urls = await search_formatting_pages(university_name)

    for url in urls:
        text = await fetch_page_text(url)
        if text is None:
            continue

        margins = extract_margins_mm(text)
        font = extract_font(text)
        if margins is None or font is None:
            continue

        config = InstitutionConfig(
            institution_id=str(uuid.uuid4()),
            institution_name=university_name,
            source="auto",
            page=PageConfig(size="A4", orientation="portrait", margins_mm=margins),
            font=font,
            headings=Headings(),
            citation_style="GOST",
            citation_rules={},
            toc_rules={},
            accuracy_weight=_ACCURACY_WEIGHT,
            raw_sample_reference="",
        )
        return DiscoveryResult(status="found", config=config, source_url=url)

    return DiscoveryResult(status="not_found", config=None, source_url=None)
