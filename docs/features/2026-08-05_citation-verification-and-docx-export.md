# Citation Verification + Markdown-to-docx Export Engine

## Date
2026-08-05

## PRD Section
§3.2 (citation handling, ADR-0001), §3.5 (document export)

## Summary
Two more independent backend tasks, built concurrently in the same working tree:

**`citations/verification.py` (TASK-E04-4):** Implements ADR-0001's retry-then-reject contract.
`verify_citation_against_excerpt` is a heuristic key-term-overlap check (not semantic entailment —
explicitly documented as a placeholder; a future iteration could route this through the DeepSeek
fast tier per ADR-0003, but that's out of scope for this MVP task). `verify_and_resolve_citation`
checks the candidate excerpt first, then falls back to `QdrantSourceStore.search` for alternative
passages (up to `max_retries`); if nothing verifies, it returns a `"rejected"` resolution rather
than raising — rejection is a normal, expected outcome per ADR-0001, not an error. `format_citation`
renders an accepted citation in the destination style: APA → `(Author, Year)`, GOST → `[N]`;
MLA/custom fall back to the raw reference string as-is (no real formatting rules yet).

**`export/docx.py` (TASK-E06-1):** `markdown_to_docx`/`markdown_to_docx_bytes` convert LLM-generated
chapter Markdown into a `python-docx` `Document`. Supports the practical subset this platform's
prompts actually produce: `#`/`##`/`###` headings, paragraphs, `**bold**`/`*italic*` inline runs,
and `-`/`1.` lists. Anything outside that subset (tables, blockquotes, code fences, links, nested
lists) renders as visible plain-paragraph text rather than being silently dropped or crashing —
deliberately fail-safe, since this is the last step before a user sees their thesis chapter.

## Files Changed
- `apps/backend/src/diploma_backend/citations/{__init__,verification}.py` (new)
- `apps/backend/tests/test_citation_verification.py` (new)
- `apps/backend/src/diploma_backend/export/{__init__,docx}.py` (new)
- `apps/backend/tests/test_export_docx.py` (new)

## Verification
- `uv run pytest -q` — 62 passed, 1 skipped (opt-in live DeepSeek test).
- `uv run ruff check .` — all checks passed.
- `docker compose up -d --build` — backend rebuilt, `/health` returns `{"status":"ok"}`.

## Residual Risks
- Citation verification is substring/key-term-overlap, not semantic entailment — will
  false-reject a paraphrased claim that's actually supported, and false-verify a claim that
  happens to share key terms with an unrelated excerpt. Flagged in ADR-0001's consequences as
  something to revisit once there's real usage data.
- `format_citation` only has real rules for APA/GOST (the two styles `formatting/upload.py`'s
  heuristic can actually detect); MLA/custom pass through unformatted.
- The docx engine doesn't yet apply an `InstitutionConfig`'s page/font/heading styles
  (TASK-E06-2, now unblocked) or insert media placeholders (TASK-E06-3, now unblocked) — this is
  the base mapping engine only.

## Docs Updated
- `docs/project/tasks.md` — TASK-E04-4 and TASK-E06-1 marked `done`; TASK-E06-2/E06-3 unblocked
  to `ready`.
