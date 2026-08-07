"""Celery task wrapping `toc.parser.parse_toc` (ADR-0013, TASK-E17-2).

`parse_toc` is synchronous (bytes in, `list[str]` out) and does no I/O beyond parsing an
in-memory `.docx` byte string, so this task calls it directly — no `asyncio.run` needed (ADR-0013
addendum point 3).

ADR-0013's task-breakdown names this task module `formatting.tasks`, but the function it wraps
(`parse_toc`) actually lives in `toc.parser`, not `diploma_backend.formatting`. Per this
codebase's module-separation rule, the task is defined here, alongside the function it wraps;
`diploma_backend.formatting.tasks` re-exports it under the name the ADR uses.
"""

from diploma_backend.toc.parser import parse_toc
from diploma_backend.worker.celery_app import celery_app


@celery_app.task(name="toc.parse_toc")
def parse_toc_task(content: bytes) -> list[str]:
    """Run `parse_toc` in a worker process and return the parsed chapter title list.

    `content` must be raw `.docx` bytes. `parse_toc`'s `list[str]` return value is already
    result-backend-serializable, no conversion needed. Raises `TocParseError` unchanged if
    `content` isn't a valid `.docx` file or no heading/numbered TOC entries are found.

    Note: Celery's default JSON message serializer cannot carry raw `bytes` over a real
    broker/result backend without an explicit encoding step (e.g. base64) on the caller's side;
    that wiring is out of scope here (TASK-E17-4) and does not affect `task_always_eager` tests,
    which call this task in-process without serializing arguments.
    """
    return parse_toc(content)
