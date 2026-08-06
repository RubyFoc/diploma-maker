"""Tests for TASK-E08-1 (chapter version schema + MongoDB storage), using the in-memory Mongo
fake from `conftest.py`. `client` (a FastAPI `TestClient`) is only used here for its
dependency-override wiring of `get_database`, since this module has no HTTP routes yet.
"""

import pytest
from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.main import app
from diploma_backend.versions.models import ChapterVersion
from diploma_backend.versions.service import (
    accept_draft_version,
    create_draft_version,
    create_draft_version_at_anchor,
    create_version,
    get_current_accepted_version,
    get_version,
    list_versions_for_chapter,
)


def _fake_db(client: TestClient):
    return app.dependency_overrides[get_database]()


def _build_version(
    chapter_id: str = "chapter-1",
    version_number: int = 0,
    content: str = "Initial content.",
    status: str = "accepted",
    parent_version_id: str | None = None,
) -> ChapterVersion:
    return ChapterVersion(
        chapter_id=chapter_id,
        version_number=version_number,
        content=content,
        status=status,
        parent_version_id=parent_version_id,
    )


async def test_create_and_get_version_by_id(client: TestClient) -> None:
    db = _fake_db(client)
    version = _build_version()

    created = await create_version(db, version)
    assert created == version

    fetched = await get_version(db, version.id)
    assert fetched is not None
    assert fetched.model_dump(exclude={"created_at"}) == version.model_dump(
        exclude={"created_at"}
    )


async def test_get_version_by_missing_id_returns_none(client: TestClient) -> None:
    db = _fake_db(client)
    fetched = await get_version(db, "does-not-exist")
    assert fetched is None


async def test_get_current_accepted_version_none_then_present(client: TestClient) -> None:
    db = _fake_db(client)

    assert await get_current_accepted_version(db, "chapter-1") is None

    v0 = _build_version(version_number=0, content="v0")
    await create_version(db, v0)
    v1 = _build_version(version_number=1, content="v1")
    await create_version(db, v1)
    # A draft with a higher version_number must not be returned as "current accepted".
    draft = _build_version(version_number=2, content="draft", status="draft")
    await create_version(db, draft)

    current = await get_current_accepted_version(db, "chapter-1")
    assert current is not None
    assert current.id == v1.id
    assert current.version_number == 1


async def test_list_versions_for_chapter_ordered_by_version_number(client: TestClient) -> None:
    db = _fake_db(client)
    v1 = _build_version(version_number=1, content="second")
    v0 = _build_version(version_number=0, content="first")
    other_chapter = _build_version(chapter_id="chapter-2", version_number=0, content="other")

    await create_version(db, v1)
    await create_version(db, v0)
    await create_version(db, other_chapter)

    versions = await list_versions_for_chapter(db, "chapter-1")
    assert [v.version_number for v in versions] == [0, 1]
    assert [v.content for v in versions] == ["first", "second"]


async def test_create_draft_version_with_no_prior_accepted(client: TestClient) -> None:
    db = _fake_db(client)

    draft = await create_draft_version(db, "chapter-1", "first draft content")
    assert draft.chapter_id == "chapter-1"
    assert draft.status == "draft"
    assert draft.version_number == 0
    assert draft.parent_version_id is None


async def test_create_draft_version_links_to_current_accepted(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = _build_version(version_number=3, content="accepted content")
    await create_version(db, accepted)

    draft = await create_draft_version(db, "chapter-1", "proposed edit")
    assert draft.status == "draft"
    assert draft.parent_version_id == accepted.id
    assert draft.version_number == 4


async def test_create_draft_version_builds_a_block_manifest_from_content(
    client: TestClient,
) -> None:
    """Per ADR-0011/TASK-E13-2: every new version gets a manifest derived from `content`, not
    just an opaque string."""
    db = _fake_db(client)

    draft = await create_draft_version(db, "chapter-1", "First paragraph.\nSecond paragraph.")

    assert draft.manifest is not None
    assert [block.content for block in draft.manifest] == [
        "First paragraph.",
        "Second paragraph.",
    ]
    assert [block.order for block in draft.manifest] == [0, 1]


async def test_manifest_persists_and_round_trips_through_get_version(client: TestClient) -> None:
    db = _fake_db(client)
    draft = await create_draft_version(db, "chapter-1", "Only paragraph.")

    fetched = await get_version(db, draft.id)

    assert fetched is not None
    assert fetched.manifest is not None
    assert [block.content for block in fetched.manifest] == ["Only paragraph."]


async def test_version_built_directly_without_manifest_defaults_to_none(
    client: TestClient,
) -> None:
    """A version constructed via `_build_version` (mirroring a pre-TASK-E13-2 legacy row) has no
    manifest — `None`, distinguishable from "parsed into zero blocks"."""
    version = _build_version()

    assert version.manifest is None


async def test_accept_draft_version_flips_status(client: TestClient) -> None:
    db = _fake_db(client)
    draft = await create_draft_version(db, "chapter-1", "proposed edit")

    accepted = await accept_draft_version(db, draft.id)
    assert accepted.id == draft.id
    assert accepted.status == "accepted"

    stored = await get_version(db, draft.id)
    assert stored is not None
    assert stored.status == "accepted"


async def test_accept_draft_version_missing_id_raises(client: TestClient) -> None:
    db = _fake_db(client)
    with pytest.raises(ValueError):
        await accept_draft_version(db, "does-not-exist")


async def test_accept_draft_version_already_accepted_raises(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = _build_version(version_number=0, status="accepted")
    await create_version(db, accepted)

    with pytest.raises(ValueError):
        await accept_draft_version(db, accepted.id)


async def test_create_draft_version_at_anchor_no_accepted_version_raises(
    client: TestClient,
) -> None:
    db = _fake_db(client)

    with pytest.raises(ValueError, match="no accepted version"):
        await create_draft_version_at_anchor(db, "chapter-1", "block-1", "New content.")


async def test_create_draft_version_at_anchor_no_manifest_raises(client: TestClient) -> None:
    db = _fake_db(client)
    accepted = _build_version(version_number=0, content="Some content", status="accepted")
    await create_version(db, accepted)

    with pytest.raises(ValueError, match="no block manifest"):
        await create_draft_version_at_anchor(db, "chapter-1", "block-1", "New content.")


async def test_create_draft_version_at_anchor_missing_block_raises(client: TestClient) -> None:
    db = _fake_db(client)
    accepted_draft = await create_draft_version(db, "chapter-1", "First paragraph.")
    await accept_draft_version(db, accepted_draft.id)

    with pytest.raises(ValueError, match="not found"):
        await create_draft_version_at_anchor(db, "chapter-1", "does-not-exist", "New content.")


async def test_create_draft_version_at_anchor_success_splices_and_persists(
    client: TestClient,
) -> None:
    db = _fake_db(client)
    accepted_draft = await create_draft_version(
        db, "chapter-1", "First paragraph.\nSecond paragraph."
    )
    accepted = await accept_draft_version(db, accepted_draft.id)
    assert accepted.manifest is not None
    anchor_block = accepted.manifest[0]

    draft = await create_draft_version_at_anchor(
        db, "chapter-1", anchor_block.id, "Inserted paragraph."
    )

    assert draft.status == "draft"
    assert draft.version_number == accepted.version_number + 1
    assert draft.parent_version_id == accepted.id
    assert draft.manifest is not None
    assert [block.content for block in draft.manifest] == [
        "First paragraph.",
        "Inserted paragraph.",
        "Second paragraph.",
    ]
    assert draft.content == "First paragraph.\nInserted paragraph.\nSecond paragraph."
    # The unrelated existing blocks keep their original id/hash (ADR-0011 stability contract).
    assert draft.manifest[0].id == anchor_block.id
    assert draft.manifest[0].content_hash == anchor_block.content_hash
    assert draft.manifest[2].id == accepted.manifest[1].id
