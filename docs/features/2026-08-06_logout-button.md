# Logout Button

## Date
2026-08-06

## PRD Section
§6 (onboarding/session), user request

## Summary
Added a "Log out" button in the app header (top-right, next to the app title, visible once past
onboarding). Clicking it resets `AuthContext` (clears the JWT, which also clears it from
`localStorage` via that context's existing effect), `DocumentContext` (clears `projectId`,
`institutionId`, and all chapters back to `emptyDocumentState`), and `ChatContext` (clears chat
history via `resetChat`). `Gate` re-renders `Onboarding` on the next render since it already
checks `auth.accessToken === null`.

There is no server-side session to invalidate and no logout endpoint — this backend has no
auth-gated endpoints at all yet (every route works with or without a JWT), so logging out is
purely a client-side state reset. Documented explicitly in the component's docstring so this
isn't mistaken for an oversight later.

## Files Changed
- `apps/frontend/src/App.tsx` (`LogoutButton` component, wired into `AuthenticatedApp`'s header)
- `apps/frontend/src/App.css` (`.logout-button` styling)
- `apps/frontend/src/strings/index.ts` (`logoutButton` string)
- `apps/frontend/src/App.test.tsx` (new test: logout returns to onboarding and clears the stored
  token)

## Verification
- `npx vitest run` — 81/81 passed (15 files). `npx eslint .` — 0 errors. `npx tsc -b` — clean.
- `docker compose up -d --build` — frontend rebuilt and healthy.

## Residual Risks
- Since there's no backend session/auth-gating yet, "logout" only affects this browser's local
  state — the JWT itself remains valid until it expires; there's no server-side revocation. Not a
  practical concern today (no endpoint checks the token meaningfully anyway), but worth revisiting
  if/when real auth enforcement is added.

## Docs Updated
- `docs/project/tasks.md` — new "Phase 5.7" section, TASK-INT-12 `done`.
