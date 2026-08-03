# Frontend Requirements

## Stack (confirmed)
- React + TypeScript, built with Vite.
- Sentry for error monitoring.
- RU/EN language support for all user-facing strings.

## Core Views (PRD §3.6)
- **Workspace**: split between AI chat (left/bottom) and document viewer (main).
- **Diff viewer**: red for deletions, green for additions; user must explicitly accept or reject
  each change — no silent auto-apply.
- **Live preview**: WYSIWYG rendering of the final formatted document before download.
- **Upload flows**: draft upload, table-of-contents upload, formatting-sample upload, custom
  literature upload.

## Open Questions
- Exact state-management approach (plain context/hooks vs. a store library) — decide via ADR once
  the workspace state shape is known from the first implementation slice.
- Real-time update mechanism for chat + diff (polling vs. WebSocket) — architect to decide, record
  in `docs/architecture/decisions.md`.
