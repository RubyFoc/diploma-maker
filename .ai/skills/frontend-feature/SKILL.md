---
name: frontend-feature
description: Implement or modify a part of the diploma-maker workspace UI (AI chat, Git-like diff viewer, live document preview, upload/config flows). Use when requests touch apps/frontend/.
---

# Frontend Feature

1. Read `docs/project/frontend-requirements.md` and the relevant PRD section
   (`Academic_Platform_PRD.md` §3.6) for the UX being touched.
2. Preserve the split-workspace layout (chat + document viewer) and the diff accept/reject
   contract — changes must not let text mutate without going through the diff review step.
3. Build the smallest end-to-end slice first (user action -> state update -> API call -> rendered
   result).
4. Add a component/interaction test (vitest + RTL) for the happy path and one failure path (API
   error, empty document, unsupported upload format).
5. Keep RU/EN i18n strings externalized; do not hardcode user-facing text in components.
6. Return a concise handoff with files changed and verification commands
   (`npm --prefix apps/frontend run test`).

## References
- Load `references/stack.md` for library-specific conventions (React, TypeScript, state
  management, Sentry).
