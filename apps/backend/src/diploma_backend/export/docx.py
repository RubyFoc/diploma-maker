"""Markdown → `.docx` mapping engine (TASK-E06-1).

Converts LLM-generated thesis-chapter Markdown into a `docx.Document`. This is the base engine
`TASK-E06-2` (institution config styles) and `TASK-E06-3` (media placeholders) build on later;
neither extension is implemented here.

Supported Markdown subset (the platform's LLM content generation is expected to only ever
produce this subset, not arbitrary web Markdown):
- Headings `#`, `##`, `###` → Word's built-in "Heading 1"/"Heading 2"/"Heading 3" paragraph
  styles.
- Blank-line-separated blocks of text → plain paragraphs.
- Inline `**bold**` and `*italic*` within any paragraph/heading/list-item text → `run.bold` /
  `run.italic` on the corresponding runs (formatting is preserved, not stripped).
- Unordered lists (`- item` / `* item`) → Word's built-in "List Bullet" style, one paragraph per
  item.
- Ordered lists (`1. item`, `2. item`, ...) → Word's built-in "List Number" style, one paragraph
  per item. The actual number text is not read; Word's own list numbering is used.

Explicitly NOT supported: tables, images/media (media placeholders are TASK-E06-3), nested
lists, links, blockquotes, code blocks, and headings beyond level 3 (`####`+). Any line matching
none of the rules above (including all of the above) is not dropped: it is emitted as a plain
paragraph containing the literal source text (markers and all), so worst case a document renders
literal Markdown syntax visibly rather than silently losing content.
"""

import re
from io import BytesIO

from docx import Document
from docx.text.paragraph import Paragraph

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_UNORDERED_LIST_RE = re.compile(r"^[-*]\s+(.*)$")
_ORDERED_LIST_RE = re.compile(r"^\d+\.\s+(.*)$")
_INLINE_RE = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*")


def markdown_to_docx(markdown_text: str) -> Document:
    """Convert `markdown_text` into a `docx.Document` per the module docstring's supported subset.

    Parses `markdown_text` line by line (no Markdown AST library — see module docstring for the
    exact rules) and builds the document by appending one paragraph per heading, list item, or
    blank-line-separated paragraph block. Never raises for unsupported Markdown constructs: they
    fall through to being rendered as a plain paragraph containing the literal source text.
    """
    document = Document()
    paragraph_buffer: list[str] = []

    def flush_paragraph_buffer() -> None:
        if not paragraph_buffer:
            return
        paragraph = document.add_paragraph()
        _add_inline_runs(paragraph, " ".join(paragraph_buffer))
        paragraph_buffer.clear()

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()

        if line == "":
            flush_paragraph_buffer()
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            flush_paragraph_buffer()
            level = len(heading_match.group(1))
            paragraph = document.add_paragraph(style=f"Heading {level}")
            _add_inline_runs(paragraph, heading_match.group(2))
            continue

        unordered_match = _UNORDERED_LIST_RE.match(line)
        if unordered_match:
            flush_paragraph_buffer()
            paragraph = document.add_paragraph(style="List Bullet")
            _add_inline_runs(paragraph, unordered_match.group(1))
            continue

        ordered_match = _ORDERED_LIST_RE.match(line)
        if ordered_match:
            flush_paragraph_buffer()
            paragraph = document.add_paragraph(style="List Number")
            _add_inline_runs(paragraph, ordered_match.group(1))
            continue

        # Anything else (plain text, and unsupported constructs like tables/blockquotes/code
        # fences) accumulates as part of the current paragraph block, per the module docstring's
        # fail-safe rule of rendering unsupported input as literal plain-paragraph text.
        paragraph_buffer.append(line)

    flush_paragraph_buffer()
    return document


def markdown_to_docx_bytes(markdown_text: str) -> bytes:
    """Convert `markdown_text` to `.docx` bytes, via `markdown_to_docx` and an in-memory buffer."""
    document = markdown_to_docx(markdown_text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _add_inline_runs(paragraph: Paragraph, text: str) -> None:
    """Append `text` to `paragraph` as one or more runs, applying `**bold**`/`*italic*` markup.

    Splits `text` on the first of either marker (non-overlapping, left to right) and adds a run
    per segment, setting `run.bold`/`run.italic` only for matched segments — unmarked segments
    get a plain run with no formatting flags touched.
    """
    position = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > position:
            paragraph.add_run(text[position : match.start()])

        bold_text, italic_text = match.group(1), match.group(2)
        if bold_text is not None:
            run = paragraph.add_run(bold_text)
            run.bold = True
        else:
            run = paragraph.add_run(italic_text)
            run.italic = True

        position = match.end()

    if position < len(text):
        paragraph.add_run(text[position:])
