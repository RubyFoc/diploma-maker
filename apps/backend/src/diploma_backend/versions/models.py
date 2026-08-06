"""Chapter version document shape (ADR-0004, TASK-E08-1).

ADR-0004 locks in immutable version snapshots per chapter/section instead of CRDT/operational-
transform (not needed: single user editing via chat, not concurrent multi-user editing). Each
accepted edit is a new version row; a pending LLM-proposed edit is stored as a draft version
linked to the current accepted version it was proposed against. The diff shown in the UI (E08)
is computed on read (text-diff over draft vs. current accepted content) and is not persisted
here — that belongs to a later E08 task, not this one.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from diploma_backend.locks.models import Block

VersionStatus = Literal["accepted", "draft"]


class ChapterVersion(BaseModel):
    """One immutable version row for a chapter, matching ADR-0004's schema exactly.

    `id` is a generated version-row id (this codebase's storage functions key documents by an
    explicit `id` field rather than Mongo's own `_id`, matching `auth.models`/`billing.models`'s
    style) used by `versions.service.get_version`/`accept_draft_version`.

    `parent_version_id` points at the `id` of "the current accepted version [this draft] is
    proposed against" (ADR-0004): set for draft versions once a chapter already has an accepted
    version, and `None` for a chapter's very first version (nothing accepted yet to link against)
    or for accepted versions themselves, which don't carry a parent.

    `manifest` is `content` split into lockable `Block`s (ADR-0011, TASK-E13-2) — `content`
    remains the source of truth for text-diff/export/humanization, all of which only need a plain
    string; `manifest` exists purely so `locks.service` has stable per-block ids/hashes to anchor
    a `Lock` to. `versions.service.create_draft_version` populates it from `content` for every new
    row; it defaults to `None` (not `[]`) so it's easy to tell "never parsed into blocks" (a
    version persisted before TASK-E13-2, per ADR-0011's retrofit consequence) apart from
    "parsed into zero blocks" (empty content).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    chapter_id: str
    version_number: int
    content: str
    manifest: list[Block] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: VersionStatus
    parent_version_id: str | None = None
