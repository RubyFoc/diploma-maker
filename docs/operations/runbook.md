# Operations Runbook

## Local Bootstrap
- `cp .env.example .env`
- `docker compose up -d --build`
- Backend health: `http://localhost:8000/health`
- Frontend: `http://localhost:5173`

## Common Issues
| Symptom | Likely Cause | Action |
| --- | --- | --- |
| Backend fails to start | Missing `DEEPSEEK_API_KEY` or MongoDB not reachable | Check `.env`, `docker compose logs backend` |
| Citation verification always fails | Qdrant collection not created / empty | Check `QDRANT_URL`, run ingestion for at least one source |
| `.docx` export empty/broken | Missing or malformed institution config | Validate config JSON against the formatting-engine schema |

## Rollback
- Revert the offending PR via `git revert` on `main`; do not force-push.
