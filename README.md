# diploma-maker

AI-powered academic paper generation platform: draft, format, and export theses/dissertations/term
papers with DeepSeek-backed LLM routing, RAG-verified citations, academic humanization, and
university-specific `.docx` formatting.

## Start Here
- Human/agent operating rules: `AGENTS.md`
- Product requirements: `Academic_Platform_PRD.md`
- Documentation index: `docs/README.md`
- Agent team workflow: `.ai/team/workflow.md`
- Reusable skills: `.ai/skills/*`

## Engineering Bootstrap
- Backend (`uv`): `cd apps/backend && uv sync && uv run uvicorn diploma_backend.main:app --reload`
- Frontend (React + TS): `cd apps/frontend && npm install && npm run dev`
- Docs check: `./scripts/check-docs-structure.sh`

## Docker Bootstrap
1. `cp .env.example .env`
2. `docker compose up -d --build`
3. `./scripts/smoke-compose.sh`
4. Frontend: `http://localhost:5173`, Backend health: `http://localhost:8000/health`

## Delivery Process
- Git/GitHub flow and protected branch policy: `docs/operations/github-workflow.md`
- PR Definition of Done: `.github/PULL_REQUEST_TEMPLATE.md`
- Task-level backlog: `docs/project/tasks.md`
