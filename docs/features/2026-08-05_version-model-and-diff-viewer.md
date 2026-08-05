# Version-Snapshot Data Model + Diff Viewer UI

## Date
2026-08-05

## PRD Section
§3.6 (diff/versioning workflow)

## Summary
First backend+frontend pair since Phase 0/1, both built to the same ADR-0004 contract
independently and in parallel:

**`versions/{models,service}.py` (TASK-E08-1, backend):** `ChapterVersion` per ADR-0004
(`chapter_id`, `version_number`, `content`, `created_at`, `status: "accepted"|"draft"`), plus
`id` (own UUID, matching the rest of the codebase's document-id style) and `parent_version_id`
(links a draft to the accepted version it's proposed against). Version numbers start at `0`;
`accept_draft_version` flips a draft's status in place rather than inserting a new row — ADR-0004
says an *accepted edit* creates a new version row, and a draft becoming accepted is exactly that
transition, not a second parallel row.

**`utils/diff.ts` + `components/DiffViewer.tsx` (TASK-E08-2, frontend):** A self-contained,
presentational diff viewer — no backend wiring yet, since there's no draft-fetching endpoint on
top of TASK-E08-1 yet. `diffLines` is a from-scratch line-based LCS diff (no new npm dependency —
tractable for prose-level chapter diffing). `DiffViewer` takes `before`/`after`/`onAccept`/
`onReject` as props and knows nothing about API calls, matching this codebase's existing
component/service separation. `App.tsx`'s `DocumentPanel` got a "Simulate pending draft" button
as a placeholder integration point, explicitly commented as a stand-in for a later task that
wires E08-1's real backend + an actual generation flow.

## Files Changed
- `apps/backend/src/diploma_backend/versions/{__init__,models,service}.py` (new)
- `apps/backend/tests/test_versions.py` (new, 9 cases)
- `apps/frontend/src/utils/{diff,diff.test}.ts` (new)
- `apps/frontend/src/components/{DiffViewer.tsx,DiffViewer.css,DiffViewer.test.tsx}` (new)
- `apps/frontend/src/strings/index.ts` (diff-viewer strings added)
- `apps/frontend/src/App.tsx` (placeholder draft-simulation wiring in `DocumentPanel`)

## Verification
- Backend: `uv run pytest -q` — 96 passed, 1 skipped. `uv run ruff check .` — clean.
- Frontend: `npx vitest run` — 16/16 passed (4 files). `npx eslint .` — 0 errors (4 pre-existing
  unrelated warnings in the Context files). `npx tsc -b` — clean.
- `docker compose up -d --build` — backend and frontend both rebuilt and healthy.

## Residual Risks
- No FastAPI router yet exposes the version model over HTTP — a later task needs to wire
  `create_draft_version`/`accept_draft_version` to real endpoints before the frontend's
  placeholder can talk to real data.
- The diff viewer is currently driven by a local `useState` simulation in `App.tsx`, not a real
  draft-generation flow — flagged clearly in-code as a placeholder for later integration.
- `diffLines` is line-based, not word/character-level — a one-word change in a long paragraph will
  show as "whole line replaced" rather than a tighter inline diff. Acceptable for prose-level
  review; revisit if user feedback wants finer-grained highlighting.

## Docs Updated
- `docs/project/tasks.md` — TASK-E08-1 and TASK-E08-2 marked `done`; TASK-E08-4 (WYSIWYG preview)
  unblocked to `ready`.
