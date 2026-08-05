"""`.docx` table-of-contents parsing (TASK-E10-2).

Extracts an ordered list of chapter titles from an uploaded `.docx` file. A thesis TOC upload on
this platform is really "tell me your chapter structure," not necessarily Word's auto-generated
TOC field, so this module supports two shapes of input:

1. A sequence of `Heading 1`-styled paragraphs (mirroring how a real thesis document's actual
   chapter headings look) — preferred when present, since it's the least ambiguous signal.
2. Plain numbered lines like `"1. Introduction"` or `"2) Literature Review"`, scanned across all
   paragraphs when no `Heading 1` paragraphs exist.

If neither shape is found, `parse_toc` raises `TocParseError` rather than guessing a chapter list
from unrelated prose (fail-closed, matching `formatting.upload`'s philosophy).
"""

import re
import zipfile
from io import BytesIO

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

# A leading number, then "." or ")", then whitespace, then the title text — the same pragmatic
# regex-heuristic approach as `formatting.upload`'s citation-style guess: good enough for the
# common "1. Introduction" / "2) Literature Review" shapes, not a real outline-format parser.
_NUMBERED_ENTRY_RE = re.compile(r"^\d+[.)]\s+(.+)$")

# Best-effort cleanup for Word-generated TOC fields, which render as e.g.
# "Introduction .......... 5" (title, a dot-leader, then a page number). Strips a trailing run of
# 2+ dot/whitespace characters followed by digits. This is a heuristic, not a guarantee: a title
# that legitimately ends in a number right after a short gap could be over-trimmed, but that's an
# acceptable trade-off for the common case this exists to handle.
_TRAILING_PAGE_NUMBER_RE = re.compile(r"[.\s]{2,}\d+\s*$")

_HEADING_1_STYLE = "Heading 1"


class TocParseError(ValueError):
    """Raised when an uploaded file cannot be parsed into a table of contents.

    Callers (the TOC upload router) must translate this into a 4xx response rather than letting
    it surface as a 500 — this module fails closed rather than guessing a chapter list from a
    file it couldn't make sense of.
    """


def parse_toc(content: bytes) -> list[str]:
    """Parse `content` (raw `.docx` bytes) into an ordered list of chapter titles.

    First checks the whole document for `Heading 1`-styled paragraphs; if any exist, their
    (stripped) text is used as the chapter titles, in document order. Otherwise, scans all
    paragraphs for lines matching a numbered-entry pattern (leading number, `.`/`)`, whitespace,
    then title text — e.g. `"1. Introduction"`), taking the captured title text in document
    order and skipping non-matching lines; a trailing dot-leader/page-number artifact (e.g.
    `"Introduction .......... 5"`) is stripped from each captured title as a best-effort cleanup
    (see `_TRAILING_PAGE_NUMBER_RE`).

    Raises `TocParseError` if `content` is not a valid `.docx` file, or if neither a heading nor a
    numbered-entry chapter list is found.
    """
    try:
        document = Document(BytesIO(content))
    except (PackageNotFoundError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise TocParseError("Uploaded file is not a valid .docx document") from exc

    headings = [
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.style is not None and paragraph.style.name == _HEADING_1_STYLE
    ]
    if headings:
        return headings

    titles = []
    for paragraph in document.paragraphs:
        match = _NUMBERED_ENTRY_RE.match(paragraph.text.strip())
        if match is None:
            continue
        title = _TRAILING_PAGE_NUMBER_RE.sub("", match.group(1)).strip()
        titles.append(title)
    if titles:
        return titles

    raise TocParseError(
        "Could not find any Heading 1 paragraphs or numbered TOC entries in the .docx document"
    )
