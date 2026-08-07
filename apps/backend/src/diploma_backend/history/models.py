"""Fine-grained edit op-log model (ADR-0012, TASK-E16-1).

ADR-0012 layers a new `Operation` op-log on top of the existing immutable `ChapterVersion`
snapshot chain (ADR-0004) — the snapshot chain is not extended or replaced. Where a
`versions.models.ChapterVersion` is a full-content snapshot taken once per "accept" (or once per
pending draft), an `Operation` is one small edit (paragraph/line granularity) recorded as it
happens, so undo/redo can step through the individual edits made since the last accepted version
without needing a new snapshot per keystroke. "Accept" still collapses every `Operation` recorded
since the last accepted version into one new `ChapterVersion`, exactly as today — this module adds
a parallel, finer-grained log, it does not change what "accept" produces.

`anchor(block_id + optional char_range)` from ADR-0012's schema is flattened onto `Operation` as
plain `block_id`/`char_range` fields rather than a nested `Anchor` sub-model, matching how
`locks.models.Lock` already represents the identical ADR-0011 anchor shape (`block_id` +
`char_range: CharRange | None`) as flat fields rather than nesting — consistency with `Lock` here
means an anchor is represented exactly one way across this codebase, per the epics doc's note that
ADR-0011's anchor model "must be designed once and shared with E13/E16, not reinvented per epic."
`char_range` reuses `locks.models.CharRange` for that same reason.

`base_version_id` is the `id` of the chapter's current *accepted* `ChapterVersion` at the moment
this operation was recorded — the same "proposed/recorded against the current accepted version"
convention `ChapterVersion.parent_version_id` already uses (ADR-0004). It is not the id of any
other `Operation`: replaying a chapter's op-log always starts from a known accepted snapshot's
content, not from another in-flight edit.

Scope note: this module defines only the `Operation` shape. Persisting/querying it (a
`history/service.py` MongoDB layer), the undo/redo replay logic that applies/reverts `Operation`
rows against the current draft, and the "a new edit after an undo wipes the redo stack" rule from
ADR-0012's addendum are separate follow-up tasks (TASK-E16-2, TASK-E16-3) — deliberately not
implemented here.
"""

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from diploma_backend.locks.models import CharRange


class Operation(BaseModel):
    """One recorded edit against a chapter's draft, anchored to a block (ADR-0011, ADR-0012).

    `id` is a generated operation-row id, matching this codebase's convention of an explicit `id`
    field rather than Mongo's own `_id` (see `versions.models.ChapterVersion`).

    `block_id`/`char_range` are this operation's anchor, in ADR-0011's terms: `block_id` names the
    `locks.models.Block` this edit touched, and `char_range` optionally narrows the edit to an
    intra-block character range (`None` means the whole block's content changed). `before_text`/
    `after_text` are the anchored content (the full block, or just the `char_range` slice of it,
    matching whichever granularity `char_range` implies) immediately before and after this
    operation — undo replays `before_text` back over the anchor, redo replays `after_text`.

    `applied_by` is the user id (the `sub` claim from `auth.dependencies.get_current_user_id`) of
    the caller who made this edit, matching how `projects.models.Project.owner_id` references a
    user id elsewhere in this codebase.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    chapter_id: str
    base_version_id: str
    block_id: str
    char_range: CharRange | None = None
    before_text: str
    after_text: str
    applied_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
