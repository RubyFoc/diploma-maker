"""Tests for TASK-E06-1 (Markdown → `.docx` mapping engine).

Builds Markdown input strings, converts them with `markdown_to_docx`/`markdown_to_docx_bytes`,
and reads the result back with `python-docx`'s `Document(BytesIO(...))` to assert on structure
and content, following the fixture style in `test_formatting_upload.py`.
"""

from io import BytesIO

from docx import Document

from diploma_backend.export.docx import markdown_to_docx, markdown_to_docx_bytes


def test_headings_all_three_levels() -> None:
    document = markdown_to_docx("# Title\n\n## Section\n\n### Subsection\n")

    styles = [paragraph.style.name for paragraph in document.paragraphs]
    texts = [paragraph.text for paragraph in document.paragraphs]

    assert styles == ["Heading 1", "Heading 2", "Heading 3"]
    assert texts == ["Title", "Section", "Subsection"]


def test_plain_paragraph() -> None:
    document = markdown_to_docx("This is a plain paragraph of thesis text.")

    assert len(document.paragraphs) == 1
    paragraph = document.paragraphs[0]
    assert paragraph.text == "This is a plain paragraph of thesis text."
    assert paragraph.style.name in ("Normal", "Default Paragraph Font")


def test_multiline_paragraph_block_joins_with_space() -> None:
    document = markdown_to_docx("Line one\nLine two continues.\n\nSecond paragraph.")

    assert len(document.paragraphs) == 2
    assert document.paragraphs[0].text == "Line one Line two continues."
    assert document.paragraphs[1].text == "Second paragraph."


def test_bold_and_italic_inline_formatting() -> None:
    document = markdown_to_docx("This has **bold text** and *italic text* inside it.")

    paragraph = document.paragraphs[0]
    runs = paragraph.runs

    assert [run.text for run in runs] == [
        "This has ",
        "bold text",
        " and ",
        "italic text",
        " inside it.",
    ]
    assert runs[0].bold is not True
    assert runs[1].bold is True
    assert runs[1].italic is not True
    assert runs[2].bold is not True
    assert runs[3].italic is True
    assert runs[3].bold is not True
    assert runs[4].bold is not True


def test_unordered_list() -> None:
    document = markdown_to_docx("- First item\n* Second item\n- Third item")

    assert [p.style.name for p in document.paragraphs] == ["List Bullet"] * 3
    assert [p.text for p in document.paragraphs] == [
        "First item",
        "Second item",
        "Third item",
    ]


def test_ordered_list() -> None:
    document = markdown_to_docx("1. First step\n2. Second step\n3. Third step")

    assert [p.style.name for p in document.paragraphs] == ["List Number"] * 3
    assert [p.text for p in document.paragraphs] == [
        "First step",
        "Second step",
        "Third step",
    ]


def test_unsupported_construct_renders_as_plain_text_not_dropped() -> None:
    markdown_text = (
        "> This is a blockquote.\n\n| col1 | col2 |\n| --- | --- |\n| a | b |"
    )

    document = markdown_to_docx(markdown_text)
    all_text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert "This is a blockquote." in all_text
    assert "col1" in all_text
    assert "col2" in all_text
    # Neither construct should be turned into a heading or list style; it stays plain text.
    assert all(
        paragraph.style.name in ("Normal", "Default Paragraph Font")
        for paragraph in document.paragraphs
    )


def test_markdown_to_docx_bytes_round_trips_via_python_docx() -> None:
    docx_bytes = markdown_to_docx_bytes("# Heading\n\nSome **bold** text.")

    assert isinstance(docx_bytes, bytes)
    document = Document(BytesIO(docx_bytes))

    assert document.paragraphs[0].style.name == "Heading 1"
    assert document.paragraphs[0].text == "Heading"
    assert document.paragraphs[1].text == "Some bold text."
