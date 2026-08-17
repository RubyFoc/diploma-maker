"""Celery task wrapping `toc.parser.parse_toc` (ADR-0013, TASK-E17-2/TASK-E17-4).

`parse_toc` is synchronous (bytes in, `list[str]` out) and does no I/O beyond parsing an
in-memory `.docx` byte string, so this task calls it directly — no `asyncio.run` needed (ADR-0013
addendum point 3).

ADR-0013's task-breakdown names this task module `formatting.tasks`, but the function it wraps
(`parse_toc`) actually lives in `toc.parser`, not `diploma_backend.formatting`. Per this
codebase's module-separation rule, the task is defined here, alongside the function it wraps;
`diploma_backend.formatting.tasks` re-exports it under the name the ADR uses.
"""

import base64

from diploma_backend.toc.parser import (
    parse_document_sections,
    parse_toc,
    parse_toc_with_subchapters,
)
from diploma_backend.worker.celery_app import celery_app


@celery_app.task(name="toc.parse_toc")
def parse_toc_task(content_b64: str) -> list[str]:
    """Run `parse_toc` in a worker process and return the parsed chapter title list.

    `content_b64` must be a base64-encoded ASCII string of the raw `.docx` bytes (TASK-E17-4):
    Celery's default JSON message serializer cannot carry raw `bytes` over a real broker/result
    backend, so the caller (`projects.router.upload_toc_endpoint`) base64-encodes the uploaded
    file before calling `.delay()`/`.apply_async()`, and this task decodes it back to bytes before
    handing it to `parse_toc`. `parse_toc`'s `list[str]` return value is already
    result-backend-serializable, no conversion needed. Raises `TocParseError` unchanged if the
    decoded content isn't a valid `.docx` file or no heading/numbered TOC entries are found.
    """
    content = base64.b64decode(content_b64)
    return parse_toc(content)


@celery_app.task(name="toc.parse_toc_with_subchapters")
def parse_toc_with_subchapters_task(content_b64: str) -> list[list]:
    """Run `parse_toc_with_subchapters` in a worker process (user request: dotted-numbered
    subsections like "3.1"/"3.2" under chapter "3" were silently dropped by `parse_toc_task`).

    Same base64-in/decode-first convention as `parse_toc_task`. Returns a list of
    `[title, [subchapter_title, ...]]` pairs rather than `list[tuple[str, list[str]]]` — tuples
    aren't a JSON-native type, matching `parse_document_sections_task`'s identical reasoning.
    Raises `TocParseError` unchanged if the decoded content isn't a valid `.docx` file or yields
    no chapter titles at all.
    """
    content = base64.b64decode(content_b64)
    return [
        [title, subchapters] for title, subchapters in parse_toc_with_subchapters(content)
    ]


@celery_app.task(name="toc.parse_document_sections")
def parse_document_sections_task(content_b64: str) -> list[list[str]]:
    """Run `parse_document_sections` in a worker process (user request: ingest a whole
    already-written document as multiple chapters in one upload, not just one chapter at a time).

    Same base64-in/decode-first convention as `parse_toc_task`. Returns a list of `[title,
    content]` pairs rather than `list[tuple[str, str]]` — tuples aren't a JSON-native type, and
    Celery's default serializer would silently coerce them to lists on the wire anyway, so the
    task's declared return type matches what callers actually receive. Raises `TocParseError`
    unchanged if the decoded content isn't a valid `.docx` file or has no `Heading 1` paragraphs.
    """
    content = base64.b64decode(content_b64)
    return [[title, section_content] for title, section_content in parse_document_sections(content)]
