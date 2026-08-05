# Vertical Slice Integration: Project → Chat → Draft → Accept

## Date
2026-08-05

## PRD Section
§3.6 (chat + diff workflow), §6 (user journey)

## Summary
After Phase 0-3 shipped substantial backend infrastructure (LLM routing/retry, RAG, citation
verification, docx export, chapter-version model) and a diff-viewer component, the running app
still showed only an empty chat template and an inert "New Project" button — no task in the
original epic breakdown covered wiring these pieces into an actual usable flow. Added two tasks
(TASK-INT-1, TASK-INT-2) opportunistically to close that gap, built in parallel against a fixed
API contract defined upfront so both sides would integrate without rework.

**Backend (TASK-INT-1):** New `projects/` package — `Project`/`Chapter` models and Mongo storage
(mirroring `formatting/service.py`'s plain-async-function style), plus a router exposing:
- `POST /projects` — create (default title `"Untitled Thesis"`).
- `GET /projects/{id}` — full detail, each chapter annotated with `accepted_content` (from
  `versions.service.get_current_accepted_version`) and `pending_draft` (from a new
  `get_latest_draft_version`, added to `versions/service.py`).
- `POST /projects/{id}/chapters` — add a chapter.
- `POST /projects/{id}/chapters/{id}/generate` — builds a prompt via `assemble_prompt` (empty
  `chapter_summaries`/`rag_excerpts` for this MVP — persisted summaries and RAG retrieval aren't
  wired into generation yet, a known simplification), calls `generate_with_retry` on the heavy
  tier, stores the result as a draft via `create_draft_version`.
- `POST /versions/{id}/accept` — on a separate `versions_router`, since `/versions/...` isn't
  under the `/projects` prefix.

**Frontend (TASK-INT-2):** `projectService.ts` replaced its local stub with real `fetch` calls
matching the contract exactly. `DocumentContext` gained `projectId` and each `Chapter` gained a
`pendingDraft` field — extending the existing two-context architecture (ADR-0008) rather than
adding a new store. `ChatPanel` gained a real text input: sending a message creates a default
"Chapter 1" on first use, calls the generate endpoint, and reports success/failure in the chat
without dumping the generated text there (that's the document panel's job). `DocumentPanel` now
renders real `accepted_content` and, when a `pending_draft` exists, the existing `DiffViewer`
(TASK-E08-2) with real Accept (calls `acceptDraft` + refetches the project) / Reject (clears
local state only, per ADR-0004 — no backend call for a rejected draft).

## Files Changed
- `apps/backend/src/diploma_backend/projects/{__init__,models,service,router}.py` (new)
- `apps/backend/tests/test_projects.py` (new, 14 cases)
- `apps/backend/src/diploma_backend/versions/service.py` (`get_latest_draft_version` added)
- `apps/backend/src/diploma_backend/main.py` (two new routers wired in)
- `apps/frontend/src/types/project.ts` (new)
- `apps/frontend/src/utils/mapProject.ts` (new)
- `apps/frontend/src/services/{projectService,projectService.test}.ts` (rewritten/new)
- `apps/frontend/src/context/DocumentContext.tsx` (`projectId`, `Chapter.pendingDraft` added)
- `apps/frontend/src/hooks/useNewProject.ts` (calls the real endpoint)
- `apps/frontend/src/App.tsx` + `App.test.tsx` (chat input, real draft flow)
- `apps/frontend/src/strings/index.ts` (new chat/draft strings)

## Verification
- Backend: `uv run pytest -q` — 108 passed, 1 skipped. `uv run ruff check .` — clean.
- Frontend: `npx vitest run` — 26/26 passed (5 files). `npx eslint .` — 0 errors. `npx tsc -b` —
  clean.
- `docker compose up -d --build` — both services rebuilt and healthy.
- **Manual end-to-end smoke test against the live stack** (real DeepSeek call, not mocked):
  `POST /projects` → `POST .../chapters` → `POST .../generate` (received a real generated
  sentence from `deepseek-v4-pro`) → `POST /versions/{id}/accept` → `GET /projects/{id}` confirmed
  `accepted_content` now holds the generated text and `pending_draft` is `null`. Full request
  sequence visible in `docker compose logs backend`.
- Frontend UI was NOT visually clicked through in a browser (no browser-automation tool available
  in this environment) — verified instead via the backend E2E smoke test above plus the
  frontend's automated tests, which exercise the same flow (message send → chapter creation →
  generate → diff viewer → accept/reject) against a mocked `fetch`. Recommend the user try
  `http://localhost:5173` directly to confirm the visual/UX result.

## Residual Risks
- Generation doesn't yet use chapter summaries or RAG-retrieved excerpts (`assemble_prompt` gets
  empty lists) — output quality/citation-groundedness is not representative of the full pipeline
  yet; that wiring is a follow-up task.
- Only one default chapter ("Chapter 1") is ever auto-created; there's no chapter-selection UI or
  TOC-aware chapter creation yet (that's E10, still pending).
- No SSE streaming (ADR-0009, TASK-E08-3) — generation is a single blocking request/response, so
  the user waits for the full response with no incremental feedback.
- Humanization, plagiarism-check, and citation-verification are not yet part of the generation
  endpoint's pipeline — the draft is raw LLM output.

## Docs Updated
- `docs/project/tasks.md` — new "Phase 2.5" section added with TASK-INT-1/TASK-INT-2, both
  `done`.
