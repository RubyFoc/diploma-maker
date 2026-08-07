"""Tests for TASK-E16-1's `Operation` op-log model (ADR-0012).

Pure model tests, no DB access — persisting `Operation` rows (TASK-E16-2) and the undo/redo
replay logic that consumes them (TASK-E16-2/3) are separate follow-up tasks with their own tests.
"""

from diploma_backend.history.models import Operation
from diploma_backend.locks.models import CharRange


def build_operation(**overrides: object) -> Operation:
    fields = {
        "chapter_id": "chapter-1",
        "base_version_id": "version-1",
        "block_id": "block-1",
        "before_text": "Original sentence.",
        "after_text": "Revised sentence.",
        "applied_by": "user-1",
    }
    fields.update(overrides)
    return Operation(**fields)


def test_operation_constructs_with_required_fields_and_autogenerates_id_and_created_at() -> None:
    operation = build_operation()

    assert operation.chapter_id == "chapter-1"
    assert operation.base_version_id == "version-1"
    assert operation.block_id == "block-1"
    assert operation.before_text == "Original sentence."
    assert operation.after_text == "Revised sentence."
    assert operation.applied_by == "user-1"
    assert operation.id
    assert operation.created_at is not None


def test_operation_assigns_a_unique_id_per_call() -> None:
    first = build_operation()
    second = build_operation()

    assert first.id != second.id


def test_operation_char_range_defaults_to_none() -> None:
    operation = build_operation()

    assert operation.char_range is None


def test_operation_char_range_can_be_set() -> None:
    operation = build_operation(char_range=CharRange(start=0, end=8))

    assert operation.char_range == CharRange(start=0, end=8)


def test_operation_round_trips_through_model_dump_and_validate() -> None:
    operation = build_operation(char_range=CharRange(start=2, end=5))

    rehydrated = Operation.model_validate(operation.model_dump())

    assert rehydrated == operation


def test_operation_round_trips_with_no_char_range() -> None:
    operation = build_operation()

    rehydrated = Operation.model_validate(operation.model_dump())

    assert rehydrated == operation
