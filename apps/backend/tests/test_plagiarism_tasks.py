"""Tests for `plagiarism.tasks.run_precheck_task` (ADR-0013, TASK-E17-4).

`run_precheck` is synchronous with no I/O, so the task calls it directly, with no `asyncio.run`
involved — `.delay()` still needs to be called from a plain sync test function to match every
other task module's convention (ADR-0013 addendum point 4).
"""

from diploma_backend.plagiarism.tasks import run_precheck_task

# Same fixture text `test_plagiarism.py`/`test_plagiarism_router.py` use for the
# "identical text scores high" case, reused here to keep the source-overlap assertion
# deterministic rather than fuzzy.
_SOURCE_EXCERPT = (
    "The mitochondria is the powerhouse of the cell and generates most of the chemical "
    "energy needed to power biochemical reactions within the cell through respiration."
)

_ORIGINAL_TEXT = (
    "Yesterday I watched a documentary about deep sea fish and learned that some species "
    "produce their own light through a process called bioluminescence in total darkness."
)


def test_delay_runs_task_and_returns_result_as_dict() -> None:
    async_result = run_precheck_task.delay(_ORIGINAL_TEXT, [])
    result = async_result.get()

    assert isinstance(result, dict)
    assert result["flagged"] is False
    assert result["plagiarism_score"] == 0.0
    assert result["reasons"] == []
    assert "sentence_flags" in result
    assert isinstance(result["sentence_flags"], list)


def test_matching_source_excerpt_scores_higher_than_original_text() -> None:
    matching_result = run_precheck_task.delay(
        _SOURCE_EXCERPT, [_SOURCE_EXCERPT]
    ).get()
    original_result = run_precheck_task.delay(
        _ORIGINAL_TEXT, [_SOURCE_EXCERPT]
    ).get()

    assert matching_result["plagiarism_score"] > original_result["plagiarism_score"]
