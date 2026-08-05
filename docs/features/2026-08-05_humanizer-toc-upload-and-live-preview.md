# Humanizer Pipeline + TOC Upload + Live WYSIWYG Preview

## Date
2026-08-05

## PRD Section
§3.3 (humanization), §6 (TOC onboarding), §3.6 (live preview)

## Summary
Three more independent tasks (backend x2, frontend x1), built concurrently in the same working
tree:

**`humanizer/pipeline.py` (TASK-E07-1):** `humanize_text` rewrites drafted text via the DeepSeek
fast tier (ADR-0003) to break up repetitive LLM stylistic patterns. The load-bearing safety
property: citations already formatted by `citations.verification.format_citation` (APA
`(Author, Year)` / GOST `[N]` markers) are swapped for stable placeholder tokens before the LLM
call and restored afterward — `restore_citations` validates every placeholder that went in comes
back out, raising `HumanizationError` (not an `LLMRequestError` subclass — a distinct failure
category) if the model dropped or mangled one. Without this guard, a humanization pass could
silently corrupt an already-verified citation (ADR-0001) with no downstream signal.

**`toc/parser.py` (TASK-E10-2):** `parse_toc` extracts an ordered chapter-title list from an
uploaded `.docx`, preferring `Heading 1`-styled paragraphs and falling back to numbered lines
(`"1. Introduction"`), stripping Word-generated dot-leader page numbers as best-effort cleanup.
Fails closed (`TocParseError` → HTTP 422) if neither pattern is found, matching
`formatting/upload.py`'s established philosophy. Wired into a new
`POST /projects/{id}/toc/upload` endpoint on the existing `projects` router: parses the TOC and
creates one chapter per entry via the existing `create_chapter` (order-assignment logic stays
centralized there), returning the updated `ProjectDetail`.

**`utils/renderMarkdownPreview.tsx` + `components/DocumentPreview.tsx` (TASK-E08-4):** Renders a
chapter's accepted content as formatted HTML instead of a raw text blob, using a hand-written
parser (no new npm dependency, matching `diff.ts`'s precedent) for the EXACT same Markdown subset
the backend's `export/docx.py` supports — headings, bold/italic, lists, and the
`[[figure: ...]]` placeholder syntax — so what a user sees in the live preview matches what
they'd get in the exported `.docx`. Wired into `DocumentPanel`, replacing the raw-text rendering
added by the previous integration task; "live" comes for free since React re-renders whenever
`DocumentContext` changes (e.g. after an Accept).

## Files Changed
- `apps/backend/src/diploma_backend/humanizer/{__init__,pipeline}.py` (new)
- `apps/backend/tests/test_humanizer.py` (new, 7 cases)
- `apps/backend/src/diploma_backend/toc/{__init__,parser}.py` (new)
- `apps/backend/src/diploma_backend/projects/router.py` (`POST .../toc/upload` added)
- `apps/backend/tests/test_toc.py` (new)
- `apps/frontend/src/utils/renderMarkdownPreview.tsx` (new)
- `apps/frontend/src/components/{DocumentPreview.tsx,DocumentPreview.css}` (new)
- `apps/frontend/src/App.tsx` (`DocumentPreview` wired into `DocumentPanel`)
- `apps/frontend/src/utils/renderMarkdownPreview.test.tsx`,
  `apps/frontend/src/components/DocumentPreview.test.tsx` (new)

## Verification
- Backend: `cd apps/backend && uv run pytest -q` — 123 passed, 1 skipped. `uv run ruff check .` —
  clean. **Both run from inside `apps/backend`**, matching the now-fixed CI invocation
  (`--directory apps/backend`) exactly.
- Frontend: `npx vitest run` — 36/36 passed (7 files). `npx eslint .` — 0 errors (4 pre-existing
  unrelated warnings). `npx tsc -b` — clean.
- `docker compose up -d --build` — both services rebuilt and healthy.
- **CI checked directly on GitHub after push** (not just locally) — see below.

## Residual Risks
- The humanizer's citation guard only reliably covers APA/GOST markers (the two styles
  `format_citation` actually formats); MLA/custom citations pass through `format_citation`
  unformatted and aren't specifically guarded, though they're also less likely to be mistaken for
  ordinary prose the humanizer would rewrite.
- `humanize_text` is not yet wired into the generation endpoint
  (`projects/router.py`'s `/generate`) — it's a standalone module a later integration task must
  call.
- TOC parsing's dot-leader-stripping and numbered-line regex are pragmatic heuristics, not a full
  TOC-format parser — unusual TOC layouts may need a follow-up.
- TASK-E10-3 (chapter-boundary-aware insertion — inserting a new "Chapter 2" between existing
  1 and 3) is now unblocked but not implemented; today `create_chapter` always appends at the end.

## Docs Updated
- `docs/project/tasks.md` — TASK-E07-1, TASK-E10-2, TASK-E08-4 marked `done`. Unblocked:
  TASK-E07-2 (anti-plagiarism check) and TASK-E10-3 (chapter-boundary insertion).
