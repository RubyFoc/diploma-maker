# Project Agent Instructions

## Mission
Build and maintain an AI-powered academic paper generation platform (thesis/dissertation/term
paper assembly, formatting, anti-plagiarism, and humanization) with predictable quality and low
knowledge loss between sessions.

## Mandatory Read Order
1. `Academic_Platform_PRD.md` (product requirements source)
2. `docs/README.md`
3. `docs/project/brief.md`
4. `docs/architecture/overview.md`
5. `docs/architecture/diagrams.md`
6. `docs/engineering/best-practices.md`
7. `.ai/team/workflow.md`

## Non-Negotiable Rules
- Ask clarifying questions whenever requirements are ambiguous.
- Produce an implementation plan first; wait for explicit user approval before writing or
  modifying code for any non-trivial change.
- Keep changes minimal, reversible, and scoped to the task.
- Update impacted docs in the same task (see `docs/README.md` for the map).
- Record architecture-impacting decisions in `docs/architecture/decisions.md`.
- Update `docs/architecture/diagrams.md` when pipeline steps, data flow, or the RAG/LLM-routing
  flow changes.
- Solo-maintainer mode: architecture review is a documented self-review in the task handoff, not
  a blocking external approval, until a second maintainer is active.
- Add or update verification steps in `docs/testing/strategy.md` when behavior changes.
- Keep backend on Python + FastAPI, frontend on React + TypeScript; do not switch stack without
  an ADR.
- Never commit or print DeepSeek/LLM API keys, MongoDB connection strings, or user-uploaded
  document content beyond what is needed to answer the current question.
- Do not add AI-style comments to code; keep only essential comments required for non-obvious
  logic (hidden constraint, workaround, surprising behavior).
- Write detailed docstrings for public modules, classes, and functions (purpose, inputs, outputs,
  side effects/exceptions).
- Use git for development changes (commits, direct push to `main` — no PR required in solo mode,
  see `docs/operations/github-workflow.md`).
- Do not commit or push changes unless explicitly asked.

## Task Output Contract
Always provide:
- What was done
- Files changed
- Verification commands run (or "skipped, docs-only" with reason)
- Residual risks
- Docs updated
- Next steps

## If Context Is Missing
- State assumptions explicitly.
- Ask for missing product/business constraints (see `Academic_Platform_PRD.md` for known scope
  boundaries — anything not covered by the MVP journey in §6 needs explicit confirmation).
- Add TODO markers only with an owner and a concrete trigger to revisit.
