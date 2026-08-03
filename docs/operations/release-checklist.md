# Release Checklist

- [ ] All required CI checks pass (`docs-check`, `backend`, `frontend`).
- [ ] `docs/architecture/decisions.md` has no unresolved "Open ADRs" blocking this release.
- [ ] `docs/project/tasks.md` reflects the true state of shipped work.
- [ ] `.env.example` matches the variables actually consumed by the app.
- [ ] `docs/operations/changelog.md` updated with the release summary.
- [ ] Smoke test passed: `docker compose up -d --build && ./scripts/smoke-compose.sh`.
