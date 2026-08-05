# Template Accuracy-Weight Adjustment

## Date
2026-08-05

## PRD Section
§3.5 (feedback loop & crowdsourced template weights)

## Summary
TASK-E09-2, closing out Epic E09: feedback signals (TASK-E09-1) now actually change something.
Per the epic's success criterion ("a user's formatting correction increases that university
template's accuracy weight, visible on the next generation for that template"):

`accuracy_weight = approvals / (approvals + rejections)`, recomputed from an institution's
**entire** signal history on every new signal (not an incremental step-bump, which would drift
unboundedly and forget older signals). `"edit"` signals are excluded from both numerator and
denominator — there's no edit-emitting UI flow yet, and an edit isn't cleanly positive or
negative the way approve/reject are; a future iteration could treat edits as a partial-negative
signal once a real edit-then-resubmit flow exists to observe. If an institution has zero
approve/reject signals (none at all, or edit-only so far), `recompute_accuracy_weight` returns
`None` and leaves the stored weight untouched — an institution with no real feedback yet keeps
its starting baseline (e.g. the seeded GOST default's `1.0`, an upload's `0.0`, or an
auto-detected config's `0.3`), rather than being reset by a division-by-zero non-answer.

Wired directly into `POST /feedback/signals`: after `record_signal` persists the new signal,
`recompute_accuracy_weight` runs synchronously in the same request (cheap Mongo read+write, no
LLM call, unlike the fire-and-forget treatment given to this same endpoint call from the
frontend's accept/reject handlers) and updates the institution config's `accuracy_weight` +
`updated_at`. The endpoint's response shape is unchanged — this is a side effect, not part of
what's returned.

## Files Changed
- `apps/backend/src/diploma_backend/formatting/service.py` (`update_accuracy_weight` added)
- `apps/backend/src/diploma_backend/feedback/weights.py` (new — `recompute_accuracy_weight`)
- `apps/backend/src/diploma_backend/feedback/router.py` (wired into `POST /feedback/signals`)
- `apps/backend/tests/test_weights.py` (new, 7 cases)

## Verification
- `cd apps/backend && uv run pytest -q` — 185 passed, 1 skipped. `uv run ruff check .` — clean.
- `docker compose up -d --build` — backend rebuilt and healthy.
- **Manual end-to-end verification against the live stack**: the seeded GOST institution started
  at `accuracy_weight: 1.0`. Recorded 2 real `POST /feedback/signals` approvals + 1 rejection
  against it, then re-fetched `GET /formatting/institution-configs/seed-gost-7-32-2017` and
  confirmed `accuracy_weight` is now `0.6666666666666666` — exactly `2/3`, matching the formula.
- CI checked on GitHub after push.

## Residual Risks
- No UI anywhere surfaces `accuracy_weight` yet — this closes the backend half of E09; a future
  task could show it (e.g. in the onboarding institution list, or an admin view) so the "weight
  adjustment" is actually visible to a user, not just computed silently.
- The formula gives equal weight to every historical signal regardless of age — an institution
  whose formatting sample was fixed after early bad feedback has no way to "forget" that early
  signal short of it being outweighed by enough later approvals. Acceptable for now given there's
  no real usage data yet to justify a more complex time-decay scheme.

## Docs Updated
- `docs/project/tasks.md` — TASK-E09-2 marked `done`. This closes out Epic E09 entirely.
