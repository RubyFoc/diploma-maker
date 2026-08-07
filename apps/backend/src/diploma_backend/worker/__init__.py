"""Celery worker package (ADR-0013, TASK-E17-1/E17-2).

Holds the single shared `Celery` app instance (`worker.celery_app.celery_app`) that every
pipeline-module task module (`llm_routing.tasks`, `sources.tasks`, `humanizer.tasks`,
`formatting.tasks`) imports and registers tasks against. This package intentionally contains no
task definitions itself — each task lives alongside the function it wraps, in that function's own
pipeline module, per `docs/engineering/best-practices.md`'s module-separation rule.
"""
