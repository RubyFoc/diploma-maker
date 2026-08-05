"""Tests for TASK-E04-3 (RU/BY geo-fencing heuristic filter layer).

Pure logic over already-constructed `SourceSearchResult` instances — no network calls, no mocking
needed.
"""

from diploma_backend.sources.geo_filter import filter_ru_by_sources, is_likely_ru_by_source
from diploma_backend.sources.search import SourceSearchResult


def _make_result(**overrides) -> SourceSearchResult:
    defaults: dict = {
        "title": "A Study of Things",
        "authors": ["Jane Doe"],
        "year": 2021,
        "abstract": "An abstract.",
        "url": "https://example.com/paper",
        "provider": "semantic_scholar",
        "external_id": "abc123",
        "venue": None,
    }
    defaults.update(overrides)
    return SourceSearchResult(**defaults)


def test_cyrillic_title_is_likely_ru_by() -> None:
    result = _make_result(title="Исследование применения нейронных сетей")

    assert is_likely_ru_by_source(result) is True


def test_cyrillic_abstract_is_likely_ru_by() -> None:
    result = _make_result(abstract="В данной статье рассматривается вопрос...")

    assert is_likely_ru_by_source(result) is True


def test_known_ru_by_venue_substring_is_likely_ru_by() -> None:
    result = _make_result(venue="Вестник Московского университета")

    assert is_likely_ru_by_source(result) is True


def test_venue_substring_case_insensitive() -> None:
    result = _make_result(venue="CYBERLENINKA")

    assert is_likely_ru_by_source(result) is True


def test_plain_english_result_is_not_ru_by() -> None:
    result = _make_result(
        title="A Study of Neural Networks",
        abstract="This paper studies neural networks.",
        venue="Journal of Machine Learning Research",
    )

    assert is_likely_ru_by_source(result) is False


def test_no_venue_no_abstract_no_cyrillic_is_not_ru_by() -> None:
    result = _make_result(abstract=None, venue=None)

    assert is_likely_ru_by_source(result) is False


def test_non_ru_cyrillic_language_is_edge_case_false_positive() -> None:
    # Ukrainian text also uses Cyrillic script; the heuristic documents this as a known
    # false-positive mode rather than trying to distinguish languages within Cyrillic script.
    result = _make_result(title="Дослідження застосування нейронних мереж")

    assert is_likely_ru_by_source(result) is True


def test_filter_ru_by_sources_returns_only_matches_preserving_order() -> None:
    ru_result = _make_result(external_id="ru-1", title="Исследование вопроса")
    en_result = _make_result(external_id="en-1", title="An English Study")
    by_result = _make_result(external_id="by-1", venue="Известия НАН Беларуси")

    results = [en_result, ru_result, by_result]

    filtered = filter_ru_by_sources(results)

    assert filtered == [ru_result, by_result]


def test_filter_ru_by_sources_empty_input_returns_empty_list() -> None:
    assert filter_ru_by_sources([]) == []


def test_filter_ru_by_sources_no_matches_returns_empty_list() -> None:
    en_result = _make_result(title="An English Study", venue="Nature")

    assert filter_ru_by_sources([en_result]) == []
