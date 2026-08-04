# Phase 0: Auth/Wallet Foundation + Workspace Shell

## Date
2026-08-04

## PRD Section
§3.6 (workspace UX), §5 (billing entities)

## Summary
First parallel backend + frontend slice of the build plan (`docs/project/plan.md` Phase 0).

**Backend** (`apps/backend`): `auth/` module (User model, register/login, JWT Bearer dependency)
and `billing/` module (Wallet/Transaction schema per ADR-0006, auto-created on registration).
Per ADR-0007's interim policy, no balance-deduction or gating logic exists yet — Wallets start
zeroed and are not enforced against.

**Frontend** (`apps/frontend`): split-pane workspace (chat panel + document panel) replacing the
Vite placeholder; `DocumentContext`/`ChatContext` per ADR-0008 (React Context + hooks, no store
library); a "New Project" action resetting both contexts to empty state (local-only for now, no
backend call — TASK-E02/E03 wiring is a follow-up).

## Files Changed
- `apps/backend/src/diploma_backend/auth/*`, `billing/*`, `db.py`, `main.py`
- `apps/backend/tests/conftest.py`, `test_auth.py`
- `apps/backend/pyproject.toml` (added `motor`, `pyjwt`, `bcrypt`, dev dep `mongomock-motor`)
- `apps/frontend/src/App.tsx`, `App.css`, `App.test.tsx`
- `apps/frontend/src/context/{DocumentContext,ChatContext}.tsx` (+ `ChatContext.test.tsx`)
- `apps/frontend/src/services/projectService.ts`, `hooks/useNewProject.ts`, `strings/index.ts`

## Verification
- Backend: `uv run pytest -q` — 8 passed; `uv run ruff check .` — all checks passed.
- Frontend: `npm run lint` — 0 errors (4 pre-existing-pattern fast-refresh warnings from
  co-located context+hook exports, non-blocking); `npm run test -- --run` — 5/5 passed;
  `npx tsc -b` — clean.

## Residual Risks
- No unique index on `users.email` yet — a race condition under concurrent registration could
  create duplicate emails; add an index before real multi-user traffic.
- `JWT_SECRET_KEY` still defaults to the `.env.example` placeholder in dev; must be a real 32+
  byte secret before any non-local deployment.
- `DocumentContext`/`ChatContext` shapes are intentionally placeholder pending TASK-E08-1
  (version-snapshot model) and TASK-E03 (real generation output).

## Docs Updated
- `docs/project/tasks.md` — TASK-E01-1..3 and TASK-E02-1..3 marked `done`.
