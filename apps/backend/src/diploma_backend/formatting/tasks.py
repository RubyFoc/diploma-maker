"""`formatting.tasks` (ADR-0013/TASK-E17-2 naming) — re-exports the TOC-parsing Celery task.

ADR-0013's task breakdown names this module `formatting.tasks`, but the only parsing-shaped
function it currently covers, `parse_toc`, lives in `diploma_backend.toc.parser`, not in this
package. `diploma_backend.formatting.upload.parse_formatting_sample` (used by the separate
"upload an institution formatting sample" endpoint) is a distinct concern with no task defined
for it in this epic's scope (TASK-E17-2 lists only `llm_routing.tasks`, `sources.tasks`,
`humanizer.tasks`, `formatting.tasks` — one task module per pipeline concern, and TOC parsing is
that concern here). The actual task is defined in `diploma_backend.toc.tasks`, alongside
`parse_toc`, per this codebase's module-separation rule; this module re-exports it under the name
the ADR's task breakdown uses.
"""

from diploma_backend.toc.tasks import parse_toc_task

__all__ = ["parse_toc_task"]
