---
name: backend-feature
description: Implement or modify a step of the academic-paper generation backend pipeline (LLM routing/caching, source management, anti-plagiarism/humanization, formatting/export, feedback loop, billing). Use when requests touch apps/backend/.
---

# Backend Feature

1. Read `docs/project/brief.md` and the relevant PRD section (`Academic_Platform_PRD.md` §3) for
   the pipeline stage being touched.
2. Identify which pipeline stage the change belongs to; keep stage boundaries intact per
   `docs/architecture/overview.md` — each stage consumes only its declared inputs (previous stage
   output, RAG context, or institution config).
3. Build the smallest end-to-end slice first (input -> stage logic -> output consumed by the next
   stage or by storage).
4. Add a unit test for the stage's transformation and one failure path (LLM timeout/error, missing
   input, empty RAG context, malformed institution config).
5. If the stage's output shape changes, note the contract impact in the feature note
   (`docs/features/`) and check whether the frontend needs a matching update.
6. Return a concise handoff with files changed and verification commands
   (`uv run --project apps/backend pytest -q ...`).

## References
- Load `references/stack.md` for library-specific conventions (FastAPI, Motor/PyMongo, Qdrant
  client, python-docx, LLM routing).
