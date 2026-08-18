"""Tests for TASK-E07-2 (plagiarism/AI-fingerprint pre-check heuristics).

Pure unit tests: `plagiarism.precheck` makes no network/DB calls, so there is nothing to mock.
"""

from diploma_backend.plagiarism.precheck import (
    flag_sentences,
    run_precheck,
    score_ai_fingerprint,
    score_plagiarism_risk,
)

_SOURCE_EXCERPT = (
    "The mitochondria is the powerhouse of the cell and generates most of the chemical "
    "energy needed to power biochemical reactions within the cell through respiration."
)

_ORIGINAL_TEXT = (
    "Yesterday I watched a documentary about deep sea fish and learned that some species "
    "produce their own light through a process called bioluminescence in total darkness."
)

_UNIFORM_AI_TEXT = (
    "Furthermore, the results were significant. Furthermore, the data was consistent. "
    "Furthermore, the trend was clear. Furthermore, the outcome was expected."
)

_VARIED_HUMAN_TEXT = (
    "The results, frankly, surprised everyone on the team. Nobody had predicted this. "
    "Over the following weeks, as more data came in from several independent labs across "
    "three continents, a much richer and more nuanced picture slowly began to emerge."
)


def test_score_plagiarism_risk_identical_text_scores_high() -> None:
    score = score_plagiarism_risk(_SOURCE_EXCERPT, [_SOURCE_EXCERPT])

    assert score == 1.0


def test_score_plagiarism_risk_unrelated_text_scores_zero() -> None:
    score = score_plagiarism_risk(_ORIGINAL_TEXT, [_SOURCE_EXCERPT])

    assert score == 0.0


def test_score_plagiarism_risk_partial_overlap_is_between_identical_and_unrelated() -> None:
    partial_text = (
        f"{_SOURCE_EXCERPT} However, I also want to add my own original commentary here "
        "that has nothing to do with the source material at all and rambles on for a while."
    )

    identical_score = score_plagiarism_risk(_SOURCE_EXCERPT, [_SOURCE_EXCERPT])
    partial_score = score_plagiarism_risk(partial_text, [_SOURCE_EXCERPT])
    zero_score = score_plagiarism_risk(_ORIGINAL_TEXT, [_SOURCE_EXCERPT])

    assert zero_score <= partial_score < identical_score


def test_score_ai_fingerprint_uniform_repetitive_text_scores_higher_than_varied_text() -> None:
    uniform_score = score_ai_fingerprint(_UNIFORM_AI_TEXT)
    varied_score = score_ai_fingerprint(_VARIED_HUMAN_TEXT)

    assert uniform_score > varied_score


def test_run_precheck_low_scores_not_flagged() -> None:
    result = run_precheck(_ORIGINAL_TEXT, [_SOURCE_EXCERPT])

    assert result.flagged is False
    assert result.reasons == []


def test_run_precheck_flags_high_plagiarism_score() -> None:
    result = run_precheck(_SOURCE_EXCERPT, [_SOURCE_EXCERPT], plagiarism_threshold=0.5)

    assert result.flagged is True
    assert any("plagiarism" in reason for reason in result.reasons)


def test_run_precheck_flags_high_ai_fingerprint_score() -> None:
    result = run_precheck(_UNIFORM_AI_TEXT, [], ai_fingerprint_threshold=0.3)

    assert result.flagged is True
    assert any("ai_fingerprint" in reason for reason in result.reasons)


def test_run_precheck_flags_both_when_both_exceed_thresholds() -> None:
    both_flagging_text = f"{_SOURCE_EXCERPT} {_SOURCE_EXCERPT}"

    result = run_precheck(
        both_flagging_text,
        [_SOURCE_EXCERPT],
        plagiarism_threshold=0.5,
        ai_fingerprint_threshold=0.3,
    )

    assert result.flagged is True
    assert any("plagiarism" in reason for reason in result.reasons)
    assert any("ai_fingerprint" in reason for reason in result.reasons)


def test_run_precheck_originality_score_is_inverse_of_plagiarism_score() -> None:
    result = run_precheck(_SOURCE_EXCERPT, [_SOURCE_EXCERPT])

    assert result.originality_score == 1.0 - result.plagiarism_score


def test_flag_sentences_lifted_sentence_is_flagged_plagiarized() -> None:
    text = f"{_SOURCE_EXCERPT} This next sentence is entirely my own original commentary."

    flags = flag_sentences(text, [_SOURCE_EXCERPT], plagiarism_threshold=0.5)

    assert len(flags) == 2
    lifted, original = flags
    assert lifted.text.startswith("The mitochondria")
    assert lifted.is_plagiarized is True
    assert lifted.plagiarism_score > 0.5
    assert original.is_plagiarized is False


def test_flag_sentences_repeated_starter_is_flagged_ai_like() -> None:
    flags = flag_sentences(_UNIFORM_AI_TEXT, [])

    assert all(flag.is_ai_like for flag in flags)


def test_flag_sentences_varied_starters_are_not_flagged_ai_like() -> None:
    flags = flag_sentences(_VARIED_HUMAN_TEXT, [])

    assert all(flag.is_ai_like is False for flag in flags)


def test_score_ai_fingerprint_detects_cliche_phrases_even_with_varied_sentence_structure() -> None:
    """`_sentence_length_uniformity`/`_repeated_starter_ratio` alone are blind to a single
    formulaic sentence with a unique opening word and ordinary length variation — user report:
    text using "не только ... но и" scored as clean despite reading as obviously AI-generated."""
    cliche_text = (
        "Названия гостиниц выполняют не только номинативную, но и рекламную функцию. "
        "Таким образом, они формируют образ страны для туристов."
    )
    clean_text = (
        "Названия гостиниц называют объект и одновременно продают его туристу. "
        "Поэтому выбор имени редко бывает случайным."
    )

    assert score_ai_fingerprint(cliche_text) > score_ai_fingerprint(clean_text)


def test_flag_sentences_marks_cliche_phrase_sentences_as_ai_like_even_with_a_unique_starter() -> None:
    text = "Названия гостиниц выполняют не только номинативную, но и рекламную функцию."

    flags = flag_sentences(text, [])

    assert len(flags) == 1
    assert flags[0].is_ai_like is True


def test_flag_sentences_detects_english_cliche_phrases_too() -> None:
    text = "Moreover, the hotel names reflect local identity."

    flags = flag_sentences(text, [])

    assert flags[0].is_ai_like is True
