"""Feedback signal document shape (E09, TASK-E09-1).

A `FeedbackSignal` is a flat, immutable log row recording that a user approved, rejected, or
edited a specific chapter draft (`versions.models.ChapterVersion`), tagged with which
institution's formatting template (`formatting.models.InstitutionConfig.institution_id`) was in
play. This is intentionally not a running counter: per the E09 architect non-functional note
("template weight adjustments must be auditable — which user correction changed which weight"),
keeping each signal as its own row is what makes that traceable later, when TASK-E09-2 reads
these rows to compute weight adjustments.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

SignalType = Literal["approve", "reject", "edit"]
"""The three signal kinds named in E09's "approve/reject/edit" language. Only `"approve"` and
`"reject"` are currently emitted by any caller (the diff viewer UI has no edit-then-resubmit
flow yet); `"edit"` is reserved for that future UI capability.
"""


class FeedbackSignal(BaseModel):
    """One immutable record of a user approving, rejecting, or editing a chapter draft.

    `id` is a generated row id (this codebase's storage functions key documents by an explicit
    `id` field rather than Mongo's own `_id`, matching `versions.models.ChapterVersion`'s style).
    `institution_id`/`chapter_id`/`version_id` are stored as plain strings with no foreign-key
    enforcement (see `feedback.service.record_signal` for why). There is no update path for this
    model: a mistaken signal is recorded as history, not corrected in place.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    institution_id: str
    chapter_id: str
    version_id: str
    signal_type: SignalType
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
