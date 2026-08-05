"""Geo-fencing filter layer (RU/BY) on top of `diploma_backend.sources.search` results.

Implements TASK-E04-3 per `docs/project/epics.md` §3.2 (open questions) and
`Academic_Platform_PRD.md` ("Geo-Fencing" — filtering academic databases by region, e.g. RU/BY).
This is relevant because ADR-0001 fixes GOST as the citation style, and GOST is the RU/BY
academic convention — so RU/BY-only source search is a real, targeted platform feature, not a
generic country filter.

Neither Semantic Scholar nor CORE expose a structured country/region field on search results
(confirmed against both APIs' response shapes in `search.py`), so there is no native filter
param to pass through. This module is therefore a **heuristic** layered entirely on top of
already-fetched `SourceSearchResult` objects:

- Cyrillic script anywhere in `title`, `abstract`, or `venue` is treated as a strong signal the
  source is a Russian-language publication (the overwhelming majority of which are RU/BY, since
  Russian-language academic publishing outside RU/BY/other CIS states is rare).
- A short curated allowlist of venue-name substrings known to be RU/BY academic
  journals/publishers/repositories (e.g. "Вестник", "Известия", "elibrary", "cyberleninka"),
  matched against `venue` case-insensitively.

This is necessarily an approximation, not an authoritative database of RU/BY academic venues:
- False negatives: RU/BY papers published in English-language international venues (common for
  STEM fields) will not match either heuristic and are silently excluded by `filter_ru_by_sources`.
- False positives: Cyrillic-script text can also indicate Ukrainian, Bulgarian, Serbian, or other
  Cyrillic-using-language publications that are not RU/BY.
- The venue allowlist is a small, manually maintained list and will miss venues not in it.

Geo-fencing is strictly opt-in: `search_sources` in `search.py` is untouched and still returns
unfiltered results by default. A caller who wants RU/BY-only results applies
`filter_ru_by_sources` themselves after calling `search_sources`.
"""

import re

from diploma_backend.sources.search import SourceSearchResult

_CYRILLIC_PATTERN = re.compile(r"[Ѐ-ӿ]")

_RU_BY_VENUE_SUBSTRINGS = (
    "вестник",
    "известия",
    "elibrary",
    "cyberleninka",
    "издательство",
    "университета",
    "belsu",
    "bsu.by",
)


def is_likely_ru_by_source(result: SourceSearchResult) -> bool:
    """Return whether `result` is heuristically likely to be a RU/BY academic source.

    Checks, in order:
    1. Cyrillic script anywhere in `title`, `abstract`, or `venue`.
    2. A curated RU/BY venue-name substring match (case-insensitive) against `venue`.

    This is a best-effort heuristic (see module docstring for known false positive/negative
    modes), not an authoritative classification. Returns `False` if neither signal is present,
    including when `venue`/`abstract` are `None` and `title` has no Cyrillic characters.
    """
    text_fields = (result.title, result.abstract, result.venue)
    if any(field and _CYRILLIC_PATTERN.search(field) for field in text_fields):
        return True

    if result.venue:
        venue_lower = result.venue.lower()
        if any(substring in venue_lower for substring in _RU_BY_VENUE_SUBSTRINGS):
            return True

    return False


def filter_ru_by_sources(results: list[SourceSearchResult]) -> list[SourceSearchResult]:
    """Return only the results from `results` that pass `is_likely_ru_by_source`.

    Opt-in geo-fencing layer: callers who want RU/BY-restricted search results call this after
    `search_sources`, e.g. `filter_ru_by_sources(await search_sources(query))`. Preserves the
    original ordering of `results`. Returns an empty list if none match — this is not treated as
    an error condition by this module.
    """
    return [result for result in results if is_likely_ru_by_source(result)]
