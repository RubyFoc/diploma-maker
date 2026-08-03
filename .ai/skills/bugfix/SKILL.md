---
name: bugfix
description: Diagnose and fix defects quickly with low regression risk. Use when requests involve incorrect behavior, crashes, performance regressions, or flaky tests in the backend pipeline or frontend UI.
---

# Bugfix

1. Reproduce the issue with a deterministic input (sample draft/institution config fixture if the
   bug is pipeline-related).
2. Narrow root cause to one module (`llm_routing`, `sources`, `humanizer`, `formatting`,
   `feedback`, `billing` on the backend; or the specific React component/store on the frontend)
   before editing.
3. Apply the minimal fix, then add a regression test (pytest or vitest as applicable).
4. Verify both the affected behavior and adjacent pipeline steps/UI states still work.
5. Return root cause, fix summary, and evidence.
