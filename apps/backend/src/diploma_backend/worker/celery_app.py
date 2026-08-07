"""Shared Celery app instance (ADR-0013, TASK-E17-1).

Broker and result backend both point at the same Redis instance (`REDIS_URL`), read from the
environment the same way `diploma_backend.db.get_client` reads `MONGODB_URI` — a plain
`os.environ.get` with a localhost-friendly default so tests and local `uvicorn` runs work without
a `.env` file. Redis is used only as a broker/result-backend here; ADR-0013's addendum point 2
(progress-buffering Streams) belongs to TASK-E17-3, not this module.

`task_always_eager`/`task_eager_propagates` default to `False` for real worker processes and are
flipped on for the whole test session by the `celery_eager` fixture in `tests/conftest.py`
(ADR-0013 addendum point 4), so `.delay()`/`.apply_async()` runs synchronously in-process against
`respx`-mocked HTTP calls with no real Redis/worker required.

Deliberately no Celery-level `autoretry_for` is configured anywhere in this module or any task
module that imports it (ADR-0013 addendum point 5): `llm_routing.retry.generate_with_retry`
already owns retry/backoff for LLM calls, and stacking Celery-level retries on top would multiply
latency/cost on every transient failure.

`include` lists every module that defines a `@celery_app.task`: a real `celery worker` process
(unlike this test suite, which imports each `tasks.py` module directly) only registers tasks it
has actually imported, so without this list `celery -A diploma_backend.worker.celery_app worker`
starts with an empty task registry and every `.delay()` from the API process fails at the worker
with "Received unregistered task" even though the broker message itself was sent successfully.
`formatting.tasks` is deliberately omitted: it only re-exports `toc.tasks.parse_toc_task`, which
`toc.tasks` already registers under the same task name — importing both would just re-register
the identical task twice.
"""

import os

from celery import Celery

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "diploma_backend",
    broker=_REDIS_URL,
    backend=_REDIS_URL,
    include=[
        "diploma_backend.llm_routing.tasks",
        "diploma_backend.sources.tasks",
        "diploma_backend.humanizer.tasks",
        "diploma_backend.toc.tasks",
    ],
)

celery_app.conf.task_always_eager = False
celery_app.conf.task_eager_propagates = False
