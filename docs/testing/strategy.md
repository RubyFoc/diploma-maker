# Testing Strategy

## Backend
- Unit tests (`pytest`) per pipeline module (`llm_routing`, `sources`, `humanizer`,
  `formatting`, `feedback`, `billing`); mock DeepSeek/Qdrant/MongoDB calls.
- Integration tests for cross-module flows (e.g. source ingestion -> citation verification, or
  institution config -> `.docx` export).
- Run: `uv run --project apps/backend pytest -q`.

## Frontend
- Component/interaction tests (Vitest + React Testing Library) for chat, diff viewer, and upload
  flows; mock backend API calls.
- Run: `npm --prefix apps/frontend run test`.

## Manual Smoke Test
- `docker compose up -d --build` then `./scripts/smoke-compose.sh` — verifies backend `/health`
  and frontend dev server respond.

## Non-Negotiable Coverage
- Every LLM-pipeline change needs a failure-path test (timeout/error).
- Every citation-verification change needs a test proving an unverifiable quote is flagged, not
  silently accepted.
- Every formatting/export change needs a test against at least one institution config fixture.
