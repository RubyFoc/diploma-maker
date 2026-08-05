# Institution-Config docx Styling + RU/BY Source Geo-Fencing

## Date
2026-08-05

## PRD Section
§3.4 (formatting-by-example export), §3.2 (geo-fenced academic source search)

## Summary
Two more independent backend tasks, built concurrently in the same working tree:

**`export/docx.py` (TASK-E06-2):** New `apply_institution_config(document, config)` mutates a
`docx.Document` in place per an `InstitutionConfig` (ADR-0005): page size/orientation/margins on
`document.sections[0]`, font family/size/line-spacing on the `"Normal"` style (inherited by all
body text rather than set per-paragraph), and `font_size_pt`/`bold` on `"Heading 1/2/3"` styles
where those keys are present in a heading level's open-ended style dict. Kept separate from
`markdown_to_docx` (TASK-E06-1) rather than folded into it — existing unstyled callers/tests are
untouched.

**`sources/geo_filter.py` (TASK-E04-3):** Layers RU/BY relevance filtering on top of
`search_sources` (TASK-E04-2) results, since neither Semantic Scholar nor CORE expose a native
region filter. `SourceSearchResult` gained an optional `venue: str | None` field (backward
compatible — existing construction call sites and tests were unaffected), populated from Semantic
Scholar's `venue` field and CORE's `publisher` field. `is_likely_ru_by_source`/
`filter_ru_by_sources` combine Cyrillic-script detection (title/abstract/venue) with a curated
substring allowlist of known RU/BY venue names (e.g. "вестник", "известия", "cyberleninka").
Explicitly opt-in — `search_sources`'s default behavior/signature is unchanged; a caller applies
the filter separately when RU/BY-only results are wanted.

## Files Changed
- `apps/backend/src/diploma_backend/export/docx.py` (`apply_institution_config` added)
- `apps/backend/tests/test_export_docx.py` (+5 tests: page/margins, landscape swap, Normal font,
  heading style application, unknown-extra-key tolerance)
- `apps/backend/src/diploma_backend/sources/search.py` (`venue` field added to
  `SourceSearchResult`, populated from both providers)
- `apps/backend/src/diploma_backend/sources/geo_filter.py` (new)
- `apps/backend/tests/test_geo_filter.py` (new, 10 cases incl. a documented Cyrillic
  false-positive edge case for non-RU/BY Slavic languages)

## Verification
- `uv run pytest -q` — 77 passed, 1 skipped (opt-in live DeepSeek test).
- `uv run ruff check .` — all checks passed.
- `docker compose up -d --build` — backend rebuilt, `/health` returns `{"status":"ok"}`.

## Residual Risks
- Heading-style application only interprets two open-ended-dict keys (`font_size_pt`, `bold`);
  any other key an institution config might carry is silently ignored — documented in the module
  docstring, not a silent data-loss bug so much as an intentionally narrow MVP scope.
- The RU/BY geo-fencing heuristic is approximate by design: it will miss RU/BY papers published
  in English-language international venues, and will flag non-RU/BY Cyrillic-script languages
  (Ukrainian, Bulgarian, Serbian, etc.) as false positives. Called out explicitly in the module
  docstring and covered by a dedicated test documenting the known false-positive case.

## Docs Updated
- `docs/project/tasks.md` — TASK-E06-2 and TASK-E04-3 marked `done`.
