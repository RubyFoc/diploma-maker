# Agent Team Workflow

Solo-maintainer mode: one human owner, no external stakeholders reviewing each role's output.
Roles below still separate concerns explicitly so an agent orchestrating sub-agents (or a single
agent working through the roles sequentially) keeps a clean paper trail per
`.ai/team/contracts/`.

## 1. Intake
- Coordinator reads the task and fills `contracts/task-input.yaml`.
- Business analyst clarifies which PRD section/user-journey step (`Academic_Platform_PRD.md`) is
  affected and what "done" means for it.
- Coordinator consolidates scope, risks, and acceptance criteria.

## 2. Analysis & Architecture
- Architect confirms the change fits the pipeline-stage module shape in
  `docs/architecture/overview.md` (LLM routing, source management, humanization, formatting,
  feedback loop, billing) rather than generic layering.
- Architect records non-functional concerns (secret handling, LLM-call failure modes, RAG store
  integrity, formatting-engine correctness).
- Architect updates `docs/architecture/diagrams.md` if the pipeline or data flow changes.
- Solo-maintainer mode: architect review is a documented self-review in the task handoff, not a
  wait for an external approver.

## 3. Planning
- Coordinator splits work into small, testable subtasks.
- Coordinator assigns subtasks to `architect`, `python-developer` (backend/LLM pipeline),
  `frontend-developer` (chat UI, diff viewer, live preview), `reviewer`, and `tester`.

## 4. Execution
- Python-developer and frontend-developer produce code and note design decisions in their own
  layer (backend pipeline vs. UI/state).
- Business analyst validates the change against the PRD requirement it maps to.
- Reviewer checks correctness, regressions, secret leakage, and maintainability across both
  layers.
- Tester validates behavior with automated checks (backend pytest, frontend vitest) and manual
  smoke tests when the change is user-facing.

## 5. Handoff
- Each role returns `contracts/handoff-output.yaml`.
- Documentation updates follow `docs/llm/docs-update-checklist.md`.
- Architect confirms diagram/decision-log consistency.
- Coordinator merges outputs into one final delivery using the `AGENTS.md` Task Output Contract
  format.
- Coordinator writes a feature note in `docs/features/` and syncs `docs/project/tasks.md`.
- Coordinator deletes branches that are no longer needed, if any were used.

## 6. Done Criteria
- Acceptance criteria explicitly satisfied.
- Architecture decisions and tradeoffs documented (`decisions.md`) when relevant.
- Test evidence attached (backend + frontend, as applicable).
- Impacted documentation updated in the same task.
- Diagrams updated for pipeline/data-flow changes.
- Feature note added under `docs/features/`.
- Final handoff includes a concise operator note: what changed and how to verify it.
