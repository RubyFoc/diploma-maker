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

from diploma_backend.toc.parser import parse_toc
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
