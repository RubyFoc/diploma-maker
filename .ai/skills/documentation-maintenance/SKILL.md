---
name: documentation-maintenance
description: Keep docs/ in sync with a behavior change. Use whenever a task changes architecture, pipeline behavior, testing policy, or delivery process, per docs/llm/docs-update-checklist.md.
---

# Documentation Maintenance

1. Identify which doc(s) the change affects using `docs/README.md`'s structure map.
2. Update architecture docs (`overview.md`, `diagrams.md`, `decisions.md`) for any pipeline-stage
   or data-flow change.
3. Update `docs/testing/strategy.md` when verification steps change.
4. Add a feature note under `docs/features/` for every completed feature (see
   `docs/features/README.md` for the template).
5. Sync `docs/project/tasks.md` status if the change closes or unblocks a task.
6. Run `./scripts/check-docs-structure.sh` before handing off.
