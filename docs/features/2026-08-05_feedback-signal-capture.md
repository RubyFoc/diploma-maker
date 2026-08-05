# Feedback Signal Capture (Approve/Reject)

## Date
2026-08-05

## PRD Section
§3.5 (feedback loop & crowdsourced template weights)

## Summary
TASK-E09-1, the first half of Epic E09: capturing accept/reject events as an auditable log so a
later task (TASK-E09-2, now unblocked) can compute per-institution `accuracy_weight` adjustments
from real user corrections. Per the architect's non-functional note for E09 ("template weight
adjustments must be auditable — which user correction changed which weight"), the signal record
is a flat, immutable log row, not a running counter — the raw history stays inspectable.

**Backend:** New `feedback/` package — `FeedbackSignal` (`institution_id`, `chapter_id`,
`version_id`, `signal_type: "approve"|"reject"|"edit"`, `created_at`), `record_signal` /
`list_signals_for_institution`, and `POST /feedback/signals`. No existence-checking against
`projects`/`versions`/`formatting` collections — this is an audit log of what the user did, and
cross-referencing would add coupling for no benefit (nothing in this codebase deletes chapters or
institutions anyway). `"edit"` is defined but not yet emitted by any caller — reserved for a
future edit-then-resubmit UI flow that doesn't exist yet.

**Frontend:** `App.tsx`'s existing `handleAccept`/`handleReject` (in `DocumentPanel`) each now
also fire `recordSignal(institutionId, chapterId, versionId, "approve"|"reject")` — fire-and-forget
(`.catch(() => {})`), so a feedback-logging failure never blocks or fails the user-facing
accept/reject flow they're actually waiting on. `handleReject`'s signature grew a `draftId`
parameter to have the `version_id` to record.

## Files Changed
- `apps/backend/src/diploma_backend/feedback/{__init__,models,service,router}.py` (new)
- `apps/backend/src/diploma_backend/main.py` (router wired in)
- `apps/backend/tests/test_feedback.py` (new, 6 cases)
- `apps/frontend/src/types/feedback.ts`, `services/feedbackService.ts` + `.test.ts` (new)
- `apps/frontend/src/App.tsx` + `App.test.tsx` (signal calls wired into accept/reject, incl. a
  test verifying a 500 on `/feedback/signals` doesn't block the accept flow)

## Verification
- Backend: `cd apps/backend && uv run pytest -q` — 149 passed, 1 skipped. `uv run ruff check .` —
  clean.
- Frontend: `npx vitest run` — 64/64 passed (13 files). `npx eslint .` — 0 errors. `npx tsc -b` —
  clean.
- `docker compose up -d --build` — both services rebuilt and healthy.
- Manual smoke test against the live stack: `POST /feedback/signals` with a real request returns
  201 with the expected shape.
- CI checked on GitHub after push.

## Residual Risks
- No weight-adjustment consumer reads these signals yet (TASK-E09-2, now unblocked) — signals
  accumulate but don't affect anything yet.
- No FK validation means a typo'd `institution_id`/`chapter_id` from a buggy future caller would
  silently log a signal against a non-existent entity — acceptable for now since the only caller
  (this task's own frontend wiring) always passes real, live ids from `DocumentContext`.

## Docs Updated
- `docs/project/tasks.md` — TASK-E09-1 marked `done`; TASK-E09-2 unblocked to `ready`.
