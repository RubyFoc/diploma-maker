# Docs Update Checklist

For every behavior change, check whether it touches:
- [ ] `docs/architecture/overview.md` / `diagrams.md` / `decisions.md` (pipeline/data-flow change)
- [ ] `docs/testing/strategy.md` (verification approach changed)
- [ ] `docs/project/epics.md` / `tasks.md` (scope/status changed)
- [ ] `docs/project/frontend-requirements.md` (UI/UX decision changed)
- [ ] `docs/operations/*` (delivery/process changed)
- [ ] `docs/features/` (new feature note)

Run `./scripts/check-docs-structure.sh` before handoff.
