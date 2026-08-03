# Frontend Stack Conventions

- Framework: React + TypeScript, built with Vite.
- State management: keep it minimal (React context/hooks) until a concrete case justifies a
  store library — no premature Redux/Zustand adoption without an ADR.
- Monitoring: Sentry for error tracking (see `AGENTS.md`).
- i18n: RU/EN support required for user-facing strings.
- Diff viewer: red for deletions, green for additions, explicit accept/reject per change — do not
  auto-apply LLM edits.
- Lint/format: ESLint + Prettier.
- Tests: Vitest + React Testing Library; mock backend API calls.
