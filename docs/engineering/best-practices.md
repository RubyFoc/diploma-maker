# Engineering Best Practices

Apply these in every task (per `AGENTS.md`).

## Backend: Typing & Style
- Python 3.12+, type hints on public functions; builtin generics (`dict`, `list`) and PEP604
  unions (`X | None`) — no `typing.Dict`/`Optional`/`Union`.
- Match existing annotation density in a file rather than fully annotating everything mypy would
  accept.
- Docstrings on public modules/classes/functions: purpose, inputs, outputs, side
  effects/exceptions. No comments unless the WHY is non-obvious.

## Frontend: Typing & Style
- TypeScript strict mode; no implicit `any`.
- Functional components + hooks; no class components.
- Externalize user-facing strings for RU/EN i18n — never hardcode UI copy in a component.

## Simplicity
- Minimum code needed to satisfy the request; no speculative abstractions, no config knobs nobody
  asked for.
- Three similar lines beat a premature abstraction.
- Touch only files/lines required by the task; do not opportunistically refactor unrelated code.

## Secrets & Data Safety
- Never commit or print DeepSeek API keys, MongoDB/Qdrant URIs, or JWT secrets.
- Never print raw user-uploaded document content or vector-store dumps into chat/logs beyond what
  is needed to answer the current question.

## Dependencies
- Backend: prefer standard library first; reach for `fastapi`, `motor`, `qdrant-client`,
  `python-docx` — the stack already decided in `Academic_Platform_PRD.md` §4 — before adding
  anything new.
- Frontend: prefer React built-ins (context/hooks) before adding a state-management library.
- Any new dependency needs an ADR entry in `../architecture/decisions.md`.

## Testing
- Add/update unit tests for each behavior change.
- Add integration tests when behavior crosses module boundaries (e.g. pipeline stage -> RAG
  store, API -> MongoDB).
- Run targeted tests first, then the broader suite relevant to the change.
