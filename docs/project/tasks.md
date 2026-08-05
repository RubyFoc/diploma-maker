# Task Backlog

Task-level breakdown of `docs/project/epics.md`, following the phased order in
`docs/project/plan.md`. Owner role names match `.ai/team/roles/` and `.claude/agents/`. Keep
status in sync with GitHub issues once tasks move to execution.

## Phase 0 — Foundations

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E01-1 | Scaffold split-pane workspace layout (chat panel + document viewer) | E01 | frontend-developer | done |
| TASK-E01-2 | Wire `DocumentContext`/`ChatContext` per ADR-0008 | E01 | frontend-developer | done |
| TASK-E01-3 | Empty project/session creation flow | E01 | frontend-developer | done |
| TASK-E02-1 | User model + registration/login endpoints | E02 | python-developer | done |
| TASK-E02-2 | Wallet/Transaction schema per ADR-0006 (cost-logging only, no enforcement per ADR-0007) | E02 | python-developer | done |
| TASK-E02-3 | JWT auth middleware | E02 | python-developer | done |

## Phase 1 — Core Services

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E05-1 | Institution config schema + MongoDB storage per ADR-0005 | E05 | python-developer | done |
| TASK-E05-2 | Formatting-sample upload + parser (margins/fonts/citation style extraction) | E05 | python-developer | done |
| TASK-E05-3 | University dropdown/selection endpoint | E05 | python-developer | done |
| TASK-E03-1 | DeepSeek client wrapper (fast/heavy tier per ADR-0003) | E03 | python-developer | done |
| TASK-E03-2 | Chapter-summary compaction + cache-friendly prompt assembly | E03 | python-developer | done |
| TASK-E03-3 | LLM call failure-path handling (timeout/error/retry) | E03 | python-developer | done |

## Phase 2 — Sources & Citations

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E04-1 | Qdrant client integration + embedding ingestion pipeline | E04 | python-developer | done |
| TASK-E04-2 | Semantic Scholar / CORE API search integration (recency filter) | E04 | python-developer | done |
| TASK-E04-3 | Geo-fencing filter layer (RU/BY) on search results | E04 | python-developer | done |
| TASK-E04-4 | Citation verification + retry/reject flow per ADR-0001 | E04 | python-developer | done |

## Phase 3 — Export & Diff Review

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E06-1 | Markdown → `.docx` mapping engine (`python-docx`) | E06 | python-developer | done |
| TASK-E06-2 | Apply institution config styles to `.docx` output | E06 | python-developer | done |
| TASK-E06-3 | Media placeholder insertion | E06 | python-developer | done |
| TASK-E08-1 | Version-snapshot data model per ADR-0004 (backend) | E08 | python-developer | done |
| TASK-E08-2 | Diff viewer UI (accept/reject) | E08 | frontend-developer | done |
| TASK-E08-3 | SSE streaming client for chat/generation per ADR-0009 | E08 | frontend-developer | ready |
| TASK-E08-4 | Live WYSIWYG document preview rendering | E08 | frontend-developer | done |

## Phase 4 — Humanization & Plagiarism

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E07-1 | Humanizer pipeline (pattern-breaking post-processing) | E07 | python-developer | done |
| TASK-E07-2 | Anti-plagiarism/AI-detection pre-check integration | E07 | python-developer | done |

## Phase 5 — Onboarding

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E10-1 | Registration + university selection/upload onboarding flow | E10 | frontend-developer | done |
| TASK-E10-2 | TOC upload/parsing | E10 | python-developer | done |
| TASK-E10-3 | Chapter-boundary-aware insertion logic | E10 | python-developer | done (partial — see Phase 2.6; HTTP endpoint still pending) |

## Phase 6 — Feedback Loop

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E09-1 | Approve/reject/edit signal capture (UI + API) | E09 | frontend-developer, python-developer | blocked on TASK-E08-2 |
| TASK-E09-2 | Template `accuracy_weight` adjustment logic | E09 | python-developer | blocked on TASK-E09-1, TASK-E05-1 |

## Phase 4.5 — Standalone Plagiarism/AI-Check Tab (added 2026-08-05, user request, not in original epic breakdown)

The user asked for the plagiarism/AI-fingerprint pre-check (TASK-E07-2) to also be usable
standalone, to check their own already-written work independent of any generated chapter. See
`docs/features/2026-08-05_standalone-plagiarism-check-tab.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-4 | `POST /plagiarism/check` standalone endpoint (reuses `run_precheck`) | E07 | python-developer | done |
| TASK-INT-5 | Plagiarism-check tab (separate from Workspace) | E07 | frontend-developer | done |

## Phase 2.6 — Pipeline Wiring & Chapter Insertion (added 2026-08-05, not in original epic breakdown)

Closes the tech debt flagged after Phase 2.5: `humanizer/pipeline.py` (TASK-E07-1) and
`plagiarism/precheck.py` (TASK-E07-2) existed as fully-tested but unwired standalone modules.
Also lands TASK-E10-3's storage-layer half. See
`docs/features/2026-08-05_pipeline-wiring-and-chapter-insertion.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-3 | Wire humanizer + plagiarism precheck into the generation endpoint | E07 | python-developer | done |
| TASK-E10-3 | Chapter-boundary-aware insertion logic (storage layer; HTTP wiring still pending) | E10 | python-developer | done (partial — no HTTP endpoint yet) |

## Phase 2.5 — Vertical Slice Integration (added 2026-08-05, not in original epic breakdown)

Closes the gap between the backend services built in Phases 0-3 and an actually-usable
end-to-end flow: create a project, chat, get a chapter draft, accept/reject it. Added
opportunistically once Phases 0-3 were complete and it became clear no task covered wiring the
pieces together — see `docs/features/2026-08-05_vertical-slice-integration.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-1 | Project/chapter backend model + generation + accept endpoints | — | python-developer | done |
| TASK-INT-2 | Wire frontend (chat input, project creation, real diff viewer) to TASK-INT-1's API | — | frontend-developer | done |

## Deferred (no task yet — waiting on ADR-0007 or user input)
- Wallet-deduction / insufficient-balance enforcement (blocked on ADR-0007 resolution).
- Paid-tier pricing display in the frontend (blocked on ADR-0007 resolution).
