"""Tests for TASK-E13-1's block manifest model (ADR-0011).

Pure model/helper tests, no DB access — persisting a manifest (TASK-E13-2) and parsing one from
an uploaded draft (TASK-E13-3) are separate follow-up tasks with their own tests.
"""

import pytest

from diploma_backend.locks.models import (
    Block,
    build_block,
    build_manifest,
    build_manifest_from_text,
    hash_block_content,
    insert_blocks_after,
    split_into_blocks,
)


def test_hash_block_content_is_deterministic() -> None:
    assert hash_block_content("Same content") == hash_block_content("Same content")


def test_hash_block_content_differs_for_different_content() -> None:
    assert hash_block_content("Content A") != hash_block_content("Content B")


def test_build_block_sets_content_hash_matching_hash_block_content() -> None:
    block = build_block("Some paragraph text.", order=0)

    assert block.content == "Some paragraph text."
    assert block.order == 0
    assert block.content_hash == hash_block_content("Some paragraph text.")


def test_build_block_assigns_a_unique_id_per_call() -> None:
    first = build_block("Text", order=0)
    second = build_block("Text", order=0)

    assert first.id != second.id


def test_build_manifest_returns_one_block_per_content_entry_in_order() -> None:
    manifest = build_manifest(["First paragraph.", "Second paragraph.", "Third paragraph."])

    assert [block.content for block in manifest] == [
        "First paragraph.",
        "Second paragraph.",
        "Third paragraph.",
    ]
    assert [block.order for block in manifest] == [0, 1, 2]


def test_build_manifest_empty_input_returns_empty_manifest() -> None:
    assert build_manifest([]) == []


def test_build_manifest_assigns_distinct_ids_to_every_block() -> None:
    manifest = build_manifest(["A", "B", "C"])

    ids = [block.id for block in manifest]
    assert len(ids) == len(set(ids))


def test_split_into_blocks_one_block_per_nonblank_line() -> None:
    text = "First paragraph.\n\nSecond paragraph.\n   \nThird paragraph."

    assert split_into_blocks(text) == [
        "First paragraph.",
        "Second paragraph.",
        "Third paragraph.",
    ]


def test_split_into_blocks_blank_text_returns_empty_list() -> None:
    assert split_into_blocks("") == []
    assert split_into_blocks("\n\n   \n") == []


def test_build_manifest_from_text_composes_split_and_build() -> None:
    manifest = build_manifest_from_text("Para one.\nPara two.")

    assert [block.content for block in manifest] == ["Para one.", "Para two."]
    assert manifest[0].content_hash == hash_block_content("Para one.")
    assert manifest[1].order == 1


def test_recomputed_hash_mismatch_signals_stale_content() -> None:
    """Demonstrates the ADR-0011 freshness check a later lock-enforcement task will perform:
    a block whose content has since changed no longer matches the hash captured at lock time."""
    block: Block = build_block("Original text.", order=0)
    locked_hash = block.content_hash

    edited_content = "Original text, but edited."

    assert hash_block_content(edited_content) != locked_hash


def test_insert_blocks_after_splices_new_content_immediately_after_anchor() -> None:
    manifest = build_manifest(["First.", "Second.", "Third."])
    anchor = manifest[0]

    result = insert_blocks_after(manifest, anchor.id, ["Inserted A.", "Inserted B."])

    assert [block.content for block in result] == [
        "First.",
        "Inserted A.",
        "Inserted B.",
        "Second.",
        "Third.",
    ]
    assert [block.order for block in result] == [0, 1, 2, 3, 4]


def test_insert_blocks_after_preserves_unrelated_block_ids_and_hashes() -> None:
    manifest = build_manifest(["First.", "Second.", "Third."])
    anchor = manifest[0]
    original_by_content = {block.content: (block.id, block.content_hash) for block in manifest}

    result = insert_blocks_after(manifest, anchor.id, ["Inserted."])

    for block in result:
        if block.content in original_by_content:
            assert (block.id, block.content_hash) == original_by_content[block.content]


def test_insert_blocks_after_missing_anchor_raises_not_found() -> None:
    manifest = build_manifest(["First.", "Second."])

    with pytest.raises(ValueError, match="not found"):
        insert_blocks_after(manifest, "does-not-exist", ["New content."])


def test_insert_blocks_after_last_block_anchor_appends_at_end() -> None:
    manifest = build_manifest(["First.", "Second."])
    anchor = manifest[-1]

    result = insert_blocks_after(manifest, anchor.id, ["Appended."])

    assert [block.content for block in result] == ["First.", "Second.", "Appended."]
    assert [block.order for block in result] == [0, 1, 2]
