"""Block manifest model for lock-anchor tracking (ADR-0011, TASK-E13-1).

A chapter version's content is represented not just as an opaque string (ADR-0004) but also as
an ordered manifest of `Block`s, each carrying a persisted `block_id` (stable across edits — never
re-derived from position or content on subsequent reads) and a `content_hash` captured at the
time the block's content was last written. A later E13 task recomputes a block's hash immediately
before letting an AI edit touch it: a mismatch means the block's content changed since a lock was
set on it, so the edit is rejected — fail-closed, same posture as ADR-0001.

This module only defines the manifest shape and the hashing/building helpers. Persisting a
manifest per `ChapterVersion` (TASK-E13-2), parsing one from an uploaded draft (TASK-E13-3), and
the lock/unlock endpoints themselves (TASK-E13-4) are separate follow-up tasks.
"""

import hashlib
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field


def hash_block_content(content: str) -> str:
    """Deterministic content hash for a block, per ADR-0011's lock-freshness check.

    Plain SHA-256 over the UTF-8 bytes of `content` — no salt/nonce, since this hash is only ever
    compared against a fresh recomputation of the same block's current content (a freshness
    check), not used for any security purpose like authentication or storage integrity.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class Block(BaseModel):
    """One block within a chapter version's manifest, keyed by `id` (`block_id` in ADR-0011's
    terms).

    `id` is assigned once, at block creation, and never re-derived from the block's position or
    content on subsequent reads/edits — that stability is exactly what makes it usable as a lock
    anchor that survives edits to *other* blocks in the same chapter. `content_hash` is
    `hash_block_content(content)`, captured whenever this block's content is (re)written; the
    lock-freshness check (TASK-E13-4) recomputes it against the block's current content and
    compares the two.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    content_hash: str
    order: int


def build_block(content: str, order: int) -> Block:
    """Construct a new `Block` for `content` at manifest position `order`, computing its
    `content_hash` from `content` so callers never have to remember to keep the two in sync.
    """
    return Block(content=content, content_hash=hash_block_content(content), order=order)


def build_manifest(block_contents: list[str]) -> list[Block]:
    """Build an ordered manifest of `Block`s from `block_contents`, one block per list entry, in
    list order.

    Pure, no DB access: persisting the result per `ChapterVersion` is TASK-E13-2's job, and
    splitting a raw markdown/docx draft into `block_contents` in the first place is TASK-E13-3's
    job — this function only needs that split already done.
    """
    return [build_block(content, order) for order, content in enumerate(block_contents)]


def split_into_blocks(text: str) -> list[str]:
    """Split `text` into one block per non-blank line, matching how content already flows
    through this codebase: `humanizer`/`llm_routing` produce one paragraph per line, and
    `plagiarism.extract.extract_text_from_docx` extracts one `.docx` paragraph per line (joined
    with `"\\n"`, blank paragraphs already dropped) — splitting on `"\\n"` here exactly recovers
    that paragraph structure rather than re-guessing block boundaries from scratch. Blank lines
    (including ones that are pure whitespace) are dropped; a completely blank/whitespace-only
    `text` returns `[]`.
    """
    return [line.strip() for line in text.split("\n") if line.strip()]


def build_manifest_from_text(text: str) -> list[Block]:
    """Convenience composition of `split_into_blocks` + `build_manifest`: the one call
    `versions.service.create_draft_version` (TASK-E13-2) and the draft-upload endpoint
    (TASK-E13-3) both need to turn a chapter's raw `content` string into a persisted manifest.
    """
    return build_manifest(split_into_blocks(text))


class CharRange(BaseModel):
    """An intra-block character offset range, for sub-block lock precision (ADR-0011).

    `start`/`end` are character offsets into the anchored `Block.content`, `start` inclusive and
    `end` exclusive (Python slice convention: `block.content[start:end]`). Optional on `Lock` —
    omitting it locks the entire block.
    """

    start: int
    end: int


class Lock(BaseModel):
    """A user-placed protected range, anchored to a block in `chapter_id`'s current accepted
    content (TASK-E13-4, ADR-0011).

    `block_content_hash` is captured at lock time from the anchored block's `Block.content_hash`
    (in the chapter's current accepted `ChapterVersion.manifest`) — not recomputed here; freshness
    enforcement (comparing this stored hash against the block's hash at the moment an AI edit
    would touch it) is `locks.service.lock_block`'s and a later E15 task's job, not this model's.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    chapter_id: str
    block_id: str
    block_content_hash: str
    char_range: CharRange | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
