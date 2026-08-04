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

## Resolved Decisions
- State management: React Context + hooks only — see ADR-0008.
- Real-time chat/diff updates: Server-Sent Events (SSE) — see ADR-0009.
