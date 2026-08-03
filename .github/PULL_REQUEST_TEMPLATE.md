# Pull Request

## Summary
- What changed and why.

## Linked Tasks
- TASK-*

## Verification
- [ ] Backend lint passed (`uv run --project apps/backend ruff check .`)
- [ ] Backend tests passed (`uv run --project apps/backend pytest -q`)
- [ ] Frontend lint passed (`npm --prefix apps/frontend run lint`)
- [ ] Frontend tests passed (`npm --prefix apps/frontend run test`)
- [ ] Docs check passed (`./scripts/check-docs-structure.sh`)

## Definition of Done
- [ ] Acceptance criteria for linked TASK-* are met.
- [ ] Tests updated for new/changed behavior (happy path + failure path).
- [ ] Public APIs/modules/classes/functions include detailed docstrings.
- [ ] Only essential non-obvious comments are added (no AI-style comments).
- [ ] Architecture/flow changes reflected in `docs/architecture/diagrams.md`.
- [ ] Documentation updated in the same PR (project/architecture/operations/testing as needed).
- [ ] No LLM API keys, DB connection strings, or user document content leaked into code/logs/docs.
- [ ] Best practices from `docs/engineering/best-practices.md` followed.

## Risks and Follow-ups
- Risk:
- Follow-up:
