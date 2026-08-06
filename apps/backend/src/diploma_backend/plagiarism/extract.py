"""Text extraction from uploaded `.docx`/`.pdf` files for the anti-plagiarism check.

Companion to `formatting.upload`'s `.docx`-parsing pattern, but simpler: this module only needs
plain text out of a document (to feed into `plagiarism.precheck.run_precheck`), not any
structural page/font/citation-style fields. `plagiarism.router`'s `/plagiarism/check-file`
endpoint is the only caller.
"""

import zipfile
from io import BytesIO

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PlagiarismFileParseError(ValueError):
    """Raised when an uploaded file cannot be parsed into extractable text.

    Callers (the file-upload router) must translate this into a 4xx response rather than letting
    it surface as a 500 — same fail-closed policy `formatting.upload.FormattingSampleParseError`
    documents for the analogous `.docx`-upload path.
    """


def extract_text_from_docx(content: bytes) -> str:
    """Extract plain text from `.docx` bytes: non-empty paragraph text, joined with `"\\n"`.

    Raises `PlagiarismFileParseError` if `content` is not a valid `.docx` file (mirrors
    `formatting.upload.parse_formatting_sample`'s exact exception set for the same failure mode).
    """
    try:
        document = Document(BytesIO(content))
    except (PackageNotFoundError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise PlagiarismFileParseError("Uploaded file is not a valid .docx document") from exc

    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def extract_text_from_pdf(content: bytes) -> str:
    """Extract plain text from `.pdf` bytes: each page's extracted text, joined with `"\\n"`.

    Known limitation: this uses `pypdf`'s built-in text extraction only, with no OCR fallback.
    A scanned-image PDF with no embedded text layer will extract to an empty string and be
    treated the same as an unreadable file — raises `PlagiarismFileParseError` in both cases,
    since neither yields text `run_precheck` can meaningfully score.
    """
    try:
        reader = PdfReader(BytesIO(content))
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise PlagiarismFileParseError("Uploaded file is not a valid .pdf document") from exc

    text = "\n".join(pages_text)
    if not text.strip():
        raise PlagiarismFileParseError(
            "Could not extract any text from the uploaded .pdf (it may be a scanned image with "
            "no text layer, or empty)"
        )
    return text


def extract_text(filename: str, content: bytes) -> str:
    """Dispatch `content` to the right extractor based on `filename`'s extension.

    Supports `.docx` and `.pdf` (case-insensitive). Raises `PlagiarismFileParseError` naming the
    unsupported extension for anything else, including a missing extension.
    """
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "docx":
        return extract_text_from_docx(content)
    if suffix == "pdf":
        return extract_text_from_pdf(content)
    raise PlagiarismFileParseError(f"Unsupported file extension: '.{suffix or filename}'")
