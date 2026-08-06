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
