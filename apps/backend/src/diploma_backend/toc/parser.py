"""`.docx` table-of-contents parsing (TASK-E10-2).

Extracts an ordered list of chapter titles from an uploaded `.docx` file. A thesis TOC upload on
this platform is really "tell me your chapter structure," not necessarily Word's auto-generated
TOC field, so this module supports six shapes of input, tried in order, each requiring
progressively less structure in the source file:

1. A sequence of `Heading 1`-styled paragraphs (mirroring how a real thesis document's actual
   chapter headings look) — preferred when present, since it's the least ambiguous signal.
2. Top-level entries from Word's auto-generated Table of Contents *field* — when a user builds
   their TOC via Word's References -> Table of Contents feature (common for a Cyrillic
   "оглавление" page extracted on its own, separate from the full thesis), each entry paragraph
   carries a `"TOC 1"`/`"TOC1"`-style name (level 2+ entries get `"TOC 2"` etc., which this
   deliberately ignores — same "only top-level" posture as the `Heading 1` case), not `Heading 1`.
3. Top-level paragraphs using Word's *list numbering* (a numbered-list style/button, not typed
   digits) — the rendered "1.", "2.", ... never appears in `paragraph.text` at all, since Word
   generates it from the list definition (`w:numPr`) rather than storing it as text, so neither
   of the text-based checks above nor the numbered-line regex below can see it. Detected via the
   paragraph's raw `w:numPr`/`w:ilvl` XML instead (level 0 only, i.e. not an indented sub-item).
4. Plain numbered lines like `"1. Introduction"`, `"2) Literature Review"`, or `"3 Conclusion"`,
   combined with (5) unnumbered lines that have a page-number suffix instead (a dot-leader or tab
   before the trailing digits) — e.g. a thesis's unnumbered front/back matter ("ВВЕДЕНИЕ",
   "ЗАКЛЮЧЕНИЕ", "СПИСОК ЛИТЕРАТУРЫ") sitting alongside numbered chapters, scanned together in
   one pass so neither shape drops the other.
6. Absolute last resort: every remaining non-blank line, when a real TOC was typed by hand with
   no styling, numbering, or page numbers at all — the only signal left at that point is that the
   caller chose this specific "upload a table of contents" endpoint, which this module trusts
   (excluding lines recognizable as a subsection or the page's own heading — see
   `_is_toc_subsection_or_page_title`).

Raises `TocParseError` only if `content` isn't a valid `.docx` file, or the document has no
non-blank paragraphs at all — tier 6 means an uploaded document essentially always yields
*something*, by design (see that tier's inline comment in `parse_toc` for the trade-off).
"""

import re
import zipfile
from io import BytesIO

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

# A leading number, then an optional ".", ")", or ":", then whitespace, then the title text — the
# same pragmatic regex-heuristic approach as `formatting.upload`'s citation-style guess: good
# enough for the common "1. Introduction" / "2) Literature Review" / "3 Conclusion" shapes, not a
# real outline-format parser.
_NUMBERED_ENTRY_RE = re.compile(r"^\d+[.):]?\s+(.+)$")

# Best-effort cleanup for Word-generated TOC entries, which render as e.g.
# "Introduction .......... 5" (title, a dot-leader, then a page number) or, when the leader is a
# real tab character rather than literal dots, "Introduction\t5". Strips a trailing run of 1+
# dot/whitespace/tab characters followed by digits. This is a heuristic, not a guarantee: a title
# that legitimately ends in a number right after a short gap could be over-trimmed, but that's an
# acceptable trade-off for the common case this exists to handle.
_TRAILING_PAGE_NUMBER_RE = re.compile(r"[.\s]+\d+\s*$")

_HEADING_1_STYLE = "Heading 1"

# Matches Word's built-in top-level TOC-field paragraph style, however it's spelled/spaced —
# `"TOC 1"`, `"TOC1"`, `"toc 1"`, etc. (Word's own naming varies by locale/version). Only level 1
# is matched, mirroring `_HEADING_1_STYLE`'s "top-level chapters only" scope: level 2+ entries
# (`"TOC 2"`, ...) are a document's subsections, not its chapters.
_TOC_FIELD_LEVEL_1_STYLE_RE = re.compile(r"^toc\s*1$", re.IGNORECASE)

# Detects a page-number suffix on its own, independent of a leading chapter number — a thesis's
# front/back matter entries (e.g. Russian "ВВЕДЕНИЕ"/"ЗАКЛЮЧЕНИЕ"/"СПИСОК ЛИТЕРАТУРЫ") are
# conventionally unnumbered even when the numbered chapters between them (e.g. "1 ...", "2 ...")
# are, so `_NUMBERED_ENTRY_RE` alone would silently drop them. Requires either a real tab
# character or a 2+-character dot-leader run before the trailing digits — deliberately stricter
# than `_TRAILING_PAGE_NUMBER_RE`'s cleanup regex, so a single space before an incidental trailing
# number in unrelated prose (e.g. "...took only 5") doesn't get mistaken for a TOC line.
_PAGE_NUMBER_SUFFIX_RE = re.compile(r"(\t+\d+|[.\s]{2,}\d+)\s*$")


def _has_page_number_suffix(text: str) -> bool:
    return _PAGE_NUMBER_SUFFIX_RE.search(text) is not None


# Matches a multi-level dotted subsection number ("1.1 ...", "2.3.1 ...") — always a subsection
# in this platform's chapter model (`Chapter`/subchapter, ADR-0014), never a top-level chapter,
# regardless of how the rest of the TOC is (un)structured.
_DOTTED_SUBSECTION_RE = re.compile(r"^\d+(\.\d+)+[.):]?\s")

# Matches a lettered appendix sub-item ("Приложение А. ...", "Appendix A ...") — a sub-item of
# the single top-level "ПРИЛОЖЕНИЯ"/"Appendices" entry, not a chapter of its own.
_APPENDIX_SUBITEM_RE = re.compile(r"^(приложение|appendix)\s+[a-zа-яё0-9]+\b", re.IGNORECASE)

# Matches a per-chapter conclusion line ("Выводы по главе 1") — always a subsection of the
# chapter it summarizes, never a chapter of its own.
_CHAPTER_CONCLUSION_RE = re.compile(r"^выводы\s+по\s+глав", re.IGNORECASE)

# A TOC page's own heading ("ОГЛАВЛЕНИЕ"/"СОДЕРЖАНИЕ"/"Table of Contents"/"Contents") — never a
# chapter title itself, just the label of the page listing them.
_TOC_PAGE_TITLE_WORDS = frozenset({"оглавление", "содержание", "table of contents", "contents"})


def _is_toc_subsection_or_page_title(text: str) -> bool:
    """`True` if `text` is a recognizable subsection/noise line that should never be treated as
    a top-level chapter title, even under `parse_toc`'s last-resort "every remaining line is a
    title" pass (see that pass's docstring for why it exists and why this filter matters)."""
    stripped = text.strip()
    if stripped.casefold() in _TOC_PAGE_TITLE_WORDS:
        return True
    return bool(
        _DOTTED_SUBSECTION_RE.match(stripped)
        or _APPENDIX_SUBITEM_RE.match(stripped)
        or _CHAPTER_CONCLUSION_RE.match(stripped)
    )


def _clean_toc_entry_title(text: str) -> str:
    """Strip a trailing tab-separated or dot-leader-separated page number from one TOC entry's
    raw paragraph text (see `_TRAILING_PAGE_NUMBER_RE`'s docstring), then strip whitespace.
    """
    if "\t" in text:
        text = text.split("\t", 1)[0]
    return _TRAILING_PAGE_NUMBER_RE.sub("", text).strip()


def _num_pr(paragraph_properties) -> object | None:
    return paragraph_properties.find(qn("w:numPr")) if paragraph_properties is not None else None


def _list_numbering_level(paragraph: Paragraph) -> int | None:
    """Returns `paragraph`'s list-numbering indent level (`0` = top level), or `None` if it isn't
    part of a numbered/bulleted list at all (no `w:numPr` anywhere in its own paragraph
    properties or its paragraph style's, walking the style-inheritance chain).

    Word's built-in list-style paragraph styles (e.g. "List Number") — which is what a real
    thesis TOC built by clicking a numbered-list button, rather than typing "1. " by hand, ends
    up using — put `w:numPr` on the *style definition* (`styles.xml`), not on each individual
    paragraph's own properties. A paragraph using such a style has no `w:numPr` of its own at
    all, so checking only the paragraph's own properties would silently miss this common case;
    `_TOC_FIELD_LEVEL_1_STYLE_RE`'s style-name check above only covers Word's specific `"TOC 1"`
    field style, not arbitrary list styles.

    A level-0 `w:ilvl` is often omitted entirely by Word (top level is the implicit default), so
    a present `w:numPr` with no `w:ilvl` child counts as level `0`, not `None`.
    """
    num_pr = _num_pr(paragraph._p.pPr)
    style = paragraph.style
    while num_pr is None and style is not None:
        style_element = getattr(style, "element", None)
        num_pr = _num_pr(style_element.find(qn("w:pPr")) if style_element is not None else None)
        style = getattr(style, "base_style", None)
    if num_pr is None:
        return None
    ilvl = num_pr.find(qn("w:ilvl"))
    if ilvl is None:
        return 0
    try:
        return int(ilvl.get(qn("w:val")))
    except (TypeError, ValueError):
        return 0


class TocParseError(ValueError):
    """Raised when an uploaded file cannot be parsed into a table of contents.

    Callers (the TOC upload router) must translate this into a 4xx response rather than letting
    it surface as a 500 — this module fails closed rather than guessing a chapter list from a
    file it couldn't make sense of.
    """


def parse_toc(content: bytes) -> list[str]:
    """Parse `content` (raw `.docx` bytes) into an ordered list of chapter titles.

    Tried in order (see module docstring): `Heading 1` paragraphs, then Word TOC-field level-1
    paragraphs, then top-level Word-list-numbered paragraphs, then plain-numbered/page-numbered
    lines together, then (last resort) every remaining non-blank line. The first tier that
    yields any entries wins; a trailing dot-leader/tab/page-number artifact (e.g.
    `"Introduction .......... 5"` or `"Introduction\t5"`) is stripped from each entry as a
    best-effort cleanup (see `_TRAILING_PAGE_NUMBER_RE`).

    Raises `TocParseError` if `content` is not a valid `.docx` file, or if it has no non-blank
    paragraphs at all.
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

    toc_field_entries = [
        _clean_toc_entry_title(paragraph.text)
        for paragraph in document.paragraphs
        if paragraph.style is not None
        and _TOC_FIELD_LEVEL_1_STYLE_RE.match(paragraph.style.name or "")
    ]
    toc_field_entries = [title for title in toc_field_entries if title]
    if toc_field_entries:
        return toc_field_entries

    list_numbered_entries = [
        _clean_toc_entry_title(paragraph.text)
        for paragraph in document.paragraphs
        if _list_numbering_level(paragraph) == 0
    ]
    list_numbered_entries = [title for title in list_numbered_entries if title]
    if list_numbered_entries:
        return list_numbered_entries

    # Plain numbered lines (e.g. "1. Introduction") and unnumbered-but-page-numbered lines (e.g.
    # "ВВЕДЕНИЕ .......... 3") are scanned together, in one pass over document order, rather than
    # as two separate "first non-empty list wins" fallbacks: a real thesis TOC commonly mixes
    # both in the same document (numbered chapters alongside conventionally-unnumbered
    # introduction/conclusion/references entries), and if the numbered-only scan ran first and
    # found even one match, a strictly-sequential fallback would return early with just that
    # partial list, silently dropping every unnumbered entry instead of ever trying the
    # page-number-suffix check at all.
    entries = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        match = _NUMBERED_ENTRY_RE.match(text)
        if match is not None:
            title = _clean_toc_entry_title(match.group(1))
        elif _has_page_number_suffix(paragraph.text):
            # Requires the page-number-suffix signal specifically (see
            # `_PAGE_NUMBER_SUFFIX_RE`'s docstring) rather than treating every non-blank
            # paragraph as a title, so unrelated prose with no such structure still correctly
            # falls through to `TocParseError` below instead of being guessed at.
            title = _clean_toc_entry_title(paragraph.text)
        else:
            continue
        if title:
            entries.append(title)
    if entries:
        return entries

    # Absolute last resort: some real thesis TOCs (typed by hand, in "Normal" style throughout,
    # with no page numbers listed at all) carry no structural signal whatsoever beyond being a
    # short list of lines — every check above requires *some* marker (a style, a leading number,
    # a page-number suffix) and finds none. Since the caller specifically chose "upload a table
    # of contents" (a distinct, single-purpose upload from `parse_document_sections`'s "upload a
    # whole document", which never reaches this far — it requires `Heading 1` unconditionally),
    # that choice itself is the signal: trust every remaining non-blank line as a chapter title,
    # excluding only lines recognizable as a subsection/the page's own heading (see
    # `_is_toc_subsection_or_page_title`). This does mean a genuinely unrelated document dropped
    # into this upload gets misread as a one-line-per-chapter TOC rather than rejected — an
    # acceptable trade-off here specifically, since a wrong result just creates chapters the user
    # can immediately see and delete (`TASK-E11-3`), rather than silently corrupting anything.
    plain_entries = [
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.text.strip() and not _is_toc_subsection_or_page_title(paragraph.text)
    ]
    if plain_entries:
        return plain_entries

    raise TocParseError(
        "Could not find any chapter titles in the .docx document — it appears to be empty."
    )


def parse_document_sections(content: bytes) -> list[tuple[str, str]]:
    """Split a whole already-written `.docx` document into `(title, content)` sections, one per
    `Heading 1`-styled paragraph, so an entire pre-written thesis can be ingested as multiple
    chapters — each with its actual content, not just its title — in a single upload, instead of
    requiring the TOC (titles only, `parse_toc`) and then a separate per-chapter draft upload for
    each one.

    Every non-heading paragraph's text is appended to the section started by the most recent
    `Heading 1` paragraph above it; paragraphs before the first heading are dropped (there is no
    section yet to attach them to). Section content joins paragraphs with a blank line, mirroring
    a `.docx` document's paragraph-per-line structure. Blank paragraphs are skipped rather than
    preserved as empty lines.

    Raises `TocParseError` if `content` isn't a valid `.docx` file, or if no `Heading 1`
    paragraphs exist at all — unlike `parse_toc`, there is no numbered-list fallback here, since a
    numbered line has no notion of "everything until the next entry" to bound a section's content.
    """
    try:
        document = Document(BytesIO(content))
    except (PackageNotFoundError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise TocParseError("Uploaded file is not a valid .docx document") from exc

    sections: list[tuple[str, list[str]]] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        is_heading = paragraph.style is not None and paragraph.style.name == _HEADING_1_STYLE
        if is_heading:
            if text:
                sections.append((text, []))
            continue
        if not sections or not text:
            continue
        sections[-1][1].append(text)

    if not sections:
        raise TocParseError(
            "Could not find any Heading 1 paragraphs to split the document into chapters"
        )

    return [(title, "\n\n".join(paragraphs)) for title, paragraphs in sections]
