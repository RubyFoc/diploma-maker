# Project docx Export

## Date
2026-08-05

## PRD Section
§3.4 (formatting/export), user-flagged gap ("no button reaches the export engine")

## Summary
The docx export engine (`export/docx.py`, TASK-E06-1/2/3) has been fully built and tested since
Phase 3, but nothing in the running app ever called it — no endpoint, no button. This closes that
gap: a real "download my thesis as .docx" feature.

**Backend (TASK-INT-9):** `GET /projects/{id}/export?institution_id=<optional>` assembles every
chapter's accepted content (via `versions.service.get_current_accepted_version`) into one
Markdown document — a chapter with no accepted version yet gets an explicit placeholder note
(matching the frontend's `chapterContentEmpty` string) rather than being silently omitted —
converts it via `markdown_to_docx`, optionally applies an institution's styling if a valid
`institution_id` is given (an unknown/stale id falls back to unstyled export rather than 404ing —
a missing style shouldn't block getting the document at all), and returns it as a binary
`Response` with the right `Content-Type` and a `Content-Disposition` download header.

**Frontend (TASK-INT-10):** `exportService.ts`'s `exportProject` fetches the endpoint, reads the
response as a `Blob`, and triggers a real browser download via a temporary anchor element — a new
DOM-side-effect pattern for this codebase's otherwise pure-JSON services, kept self-contained in
one function. A new "Export" button sits next to "New Project" in the workspace header.

## Bug Found and Fixed During Manual Verification
The initial filename-sanitization regex (`_SAFE_FILENAME_RE`) allowlisted ASCII characters only
— every Cyrillic character in a project title got replaced with `_`. For this platform's actual
target audience (RU/BY academic writing, per ADR-0001's GOST handling and `sources.geo_filter`),
a title like `"Экспорт: Тест/Проверка?"` produced a filename of literally `"________
______________.docx"` — technically valid but useless. Caught by manually downloading a real
export with a Cyrillic project title on the live stack and inspecting the actual
`Content-Disposition` header, not just running the mocked unit tests (which only used ASCII
titles).

Fixed in two steps:
1. Replaced the ASCII-only allowlist with an unsafe-character denylist (path separators, control
   characters, quotes) so non-ASCII letters survive sanitization.
2. Added a proper `Content-Disposition` with BOTH `filename=` (ASCII-only fallback, for older
   clients) and `filename*=UTF-8''<percent-encoded>` (RFC 5987/6266, for modern browsers, which
   prefer it) — a plain `filename=` parameter isn't reliably interpreted as UTF-8 across clients.
3. Found a SECOND edge case while testing the fix: a fully non-ASCII title's ASCII fallback
   stripped down to just a stray space character (`" "`), which is non-empty in Python's truthiness
   sense so the "use a generic fallback name" branch never triggered. Fixed by checking for at
   least one alphanumeric character rather than emptiness.

## Files Changed
- `apps/backend/src/diploma_backend/projects/router.py` (export endpoint,
  `_sanitize_filename`/`_content_disposition_header` helpers)
- `apps/backend/tests/test_export_endpoint.py` (new, 6 cases incl. 2 Cyrillic-filename
  regression tests)
- `apps/frontend/src/services/exportService.ts` + `.test.ts` (new)
- `apps/frontend/src/App.tsx` (`ExportButton` added to `Workspace`'s header)
- `apps/frontend/src/strings/index.ts` (export button/error strings)

## Verification
- Backend: `cd apps/backend && uv run pytest -q` — 201 passed, 1 skipped. `uv run ruff check .`
  — clean.
- Frontend: `npx vitest run` — 80/80 passed (15 files). `npx eslint .` — 0 errors. `npx tsc -b`
  — clean.
- `docker compose up -d --build` — both services rebuilt and healthy.
- **Manual end-to-end verification against the live stack**: created a real project (Cyrillic
  title, deliberately including `:`/`/`/`?`), generated and accepted a real chapter via the
  actual `/generate` + `/accept` endpoints, downloaded the export, confirmed via `file` that the
  bytes are a genuine "Microsoft Word 2007+" document, and inspected the real
  `Content-Disposition` header — this is where both filename bugs above were actually caught,
  not in the initial mocked test suite.
- CI checked on GitHub after push.

## Residual Risks
- Export always uses A4/portrait as its base document (from `markdown_to_docx`'s defaults) before
  any institution styling is applied — this is consistent with the rest of the codebase's
  defaults, not a new limitation introduced here.
- No table-of-contents or title-page generation — the export is exactly the concatenation of
  chapter headings + accepted content, nothing more, matching the export engine's existing
  documented scope (TASK-E06-1/2/3).

## Docs Updated
- `docs/project/tasks.md` — new "Phase 3.5" section, TASK-INT-9/TASK-INT-10 both `done`.
