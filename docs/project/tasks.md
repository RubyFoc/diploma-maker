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
| TASK-E08-3 | SSE streaming client for chat/generation per ADR-0009 | E08 | frontend-developer | done |
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
| TASK-E10-3 | Chapter-boundary-aware insertion logic | E10 | python-developer | done |

## Phase 6 — Feedback Loop

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E09-1 | Approve/reject/edit signal capture (UI + API) | E09 | frontend-developer, python-developer | done |
| TASK-E09-2 | Template `accuracy_weight` adjustment logic | E09 | python-developer | done |

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
| TASK-E10-3 | Chapter-boundary-aware insertion logic (storage layer; HTTP wiring still pending) | E10 | python-developer | done |

## Phase 2.5 — Vertical Slice Integration (added 2026-08-05, not in original epic breakdown)

Closes the gap between the backend services built in Phases 0-3 and an actually-usable
end-to-end flow: create a project, chat, get a chapter draft, accept/reject it. Added
opportunistically once Phases 0-3 were complete and it became clear no task covered wiring the
pieces together — see `docs/features/2026-08-05_vertical-slice-integration.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-1 | Project/chapter backend model + generation + accept endpoints | — | python-developer | done |
| TASK-INT-2 | Wire frontend (chat input, project creation, real diff viewer) to TASK-INT-1's API | — | frontend-developer | done |

## Phase 5.5 — Default GOST Institution Seed (added 2026-08-05, user-requested research, not in original epic breakdown)

The user asked for independent research into real university formatting requirements. Web
research confirmed GOST 7.32-2017's published margins/font/spacing values, and surfaced a real
gap: ADR-0005's `source: "upload" | "seed"` had no actual `"seed"` producer anywhere in the
codebase, so a fresh deployment's university dropdown (TASK-E05-3) was empty until someone
uploaded a sample. See `docs/features/2026-08-05_gost-default-institution-seed.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-6 | Seed a default GOST 7.32-2017 `InstitutionConfig` on startup | E05 | python-developer | done |

## Phase 5.6 — University Formatting Auto-Discovery (added 2026-08-05, user-requested, not in original epic breakdown)

The user asked that entering a university name should make the system TRY to automatically find
that university's formatting requirements via web search, instead of always requiring a manual
upload. See `docs/features/2026-08-05_auto-discovered-institution-formatting.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-7 | Web-search-based formatting auto-discovery (`POST .../auto-detect`) | E05 | python-developer | done |
| TASK-INT-8 | Onboarding UI: "try to auto-detect" option alongside select/upload | E05 | frontend-developer | done |

## Phase 5.7 — Logout (added 2026-08-06, user request, not in original epic breakdown)

The user asked for a way to log out. See `docs/features/2026-08-06_logout-button.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-12 | Logout button (clears session state, no server-side session to invalidate) | E10 | frontend-developer | done |

## Phase 2.7 — Live RAG Grounding for Generation (added 2026-08-06, not in original epic breakdown)

Closes part of the standing "citation verification/RAG not wired into generation" gap flagged
after every earlier integration task. See
`docs/features/2026-08-06_rag-grounding-for-generation.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-11 | Wire live external-search RAG excerpts into generation + precheck | E04 | python-developer | done |

## Phase 3.5 — Project docx Export (added 2026-08-05, not in original epic breakdown)

The docx export engine (E06) existed fully built and tested since Phase 3 with no endpoint
anywhere that reached it. See `docs/features/2026-08-05_project-docx-export.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-9 | `GET /projects/{id}/export` — assemble all chapters into one styled `.docx` | E06 | python-developer | done |
| TASK-INT-10 | "Export" button in the workspace header, triggers a browser download | E06 | frontend-developer | done |

## Deferred (no task yet — waiting on ADR-0007 or user input)
- Wallet-deduction / insufficient-balance enforcement (blocked on ADR-0007 resolution).
- Paid-tier pricing display in the frontend (blocked on ADR-0007 resolution).

## Phase 5.8 — Anti-Plagiarism Upgrades: Sentence Flags, File Upload, Dash Normalization (added 2026-08-06, user request, not in original epic breakdown)

The user asked for four upgrades to the E07 anti-plagiarism/AI-fingerprint MVP: per-sentence
plagiarism/AI-like highlighting, a separate "originality %" alongside the AI-fingerprint %, a
new tab to upload `.pdf`/`.docx` files for checking (not just pasted text), and automatic
em-dash-to-en-dash normalization on generated text (em-dash overuse is a commonly-cited
AI-writing tell). See `docs/features/2026-08-06_plagiarism-sentence-flags-and-file-upload.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-13 | Per-sentence plagiarism/AI-like flags + `originality_score` in the precheck result | E07 | python-developer | done |
| TASK-INT-14 | `POST /plagiarism/check-file` (`.pdf`/`.docx` text extraction via `pypdf`/`python-docx`) + new upload tab | E07 | python-developer, frontend-developer | done |
| TASK-INT-15 | Auto-normalize em-dash to en-dash in the humanizer pipeline | E07 | python-developer | done |

## Phase 5.9 — Auto-Generated Project Title (added 2026-08-06, user request, not in original epic breakdown)

The user asked that a project's generic "Untitled Thesis" default title be automatically replaced
with a short, distinguishing title once the user gives their first real generation instruction,
rather than requiring a manual rename.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-16 | Auto-generate and persist a project title from the user's first chat instruction via a fast-tier DeepSeek call, wired into both the streaming and non-streaming generate-draft endpoints (fail-open, triggers once via a title-equality check) | E11 | python-developer | done |

## Phase 5.10 — Per-Project University Selection (added 2026-08-06, user request, not in original epic breakdown)

The user pointed out that "Select your university" currently gates the whole app once per account
(`Onboarding`, TASK-E10-1/TASK-INT-8, backed by a single global `DocumentContext.institutionId`),
so every project a user creates shares the same formatting styles. It should instead be asked at
new-project-creation time, scoped per project, since different theses/projects may need different
institution formatting. Requires adding an `institution_id` field to the `Project` model (currently
absent per its own docstring, "no per-project settings"; institution is only threaded through
export as an optional ad-hoc query param today) and moving the select/upload/auto-detect UI out of
the account-level `Onboarding` gate into the "create new project" flow (`useNewProject`/
`ProjectLanding`). `Onboarding` keeps only its email/password auth step.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-INT-17 | Add `institution_id: str \| None` to `Project`; accept it in `CreateProjectRequest` (`POST /projects`) and use it (not the export-time query param) when applying formatting on export | E05 | python-developer | todo |
| TASK-INT-18 | Move university select/upload/auto-detect UI from the account-level `Onboarding` gate into the "create new project" flow (`useNewProject`/`ProjectLanding`), scoped per project instead of per account | E05 | frontend-developer | todo |

## Phase 7 — Multi-Project Management (added 2026-08-06, BA/architect epic breakdown for large onboarding/history/async epic)

E11. See `docs/project/epics.md` build sequence and `docs/project/plan.md` for sequencing —
sequential spine, first of E11 -> E12 -> E13 -> E15 -> E16.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E11-1 | Add `owner_id` to `Project`; scope project creation/read to the authenticated user | E11 | python-developer | done |
| TASK-E11-2 | `GET /projects` — `list_projects_for_user` endpoint | E11 | python-developer | done |
| TASK-E11-3 | `DELETE /projects/{id}` — cascading delete across Mongo projects/chapters/versions, Qdrant vectors (ADR-0002), and uploaded files | E11 | python-developer | done |
| TASK-E11-4 | Project list/switch/delete UI | E11 | frontend-developer | done |

## Phase 8 — Chapter/Subchapter Model & Sidebar Navigation

E12, depends on E11 and ADR-0014 (subchapter data model).

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E12-1 | Add `parent_chapter_id: str \| None` to `Chapter`; rescope `insert_chapter_at_order`/`infer_insertion_order` from `(project_id)` to `(project_id, parent_chapter_id)` per ADR-0014 | E12 | python-developer | done |
| TASK-E12-2 | Create/list-subchapters-under-a-parent endpoints | E12 | python-developer | done |
| TASK-E12-3 | Regression check: confirm E10's chapter-insertion tests still pass under parent-scoped ordering (top-level chapters = `parent_chapter_id=None`) | E12 | python-developer | done |
| TASK-E12-4 | `ChapterTree` sidebar navigation component + hook | E12 | frontend-developer | done |

## Phase 9 — Draft Ingestion & Lock/Protected-Range Selection

E13, depends on E12 and E06; needs ADR-0011 (lock anchor).

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E13-1 | New `locks` module: block manifest model (`block_id` + `block_content_hash`) per ADR-0011 | E13 | python-developer | done |
| TASK-E13-2 | Persist a block manifest per `ChapterVersion` (replacing opaque string content as the sole representation) | E13 | python-developer | done |
| TASK-E13-3 | Draft upload/ingestion endpoint that parses an uploaded draft into manifest blocks | E13 | python-developer | done |
| TASK-E13-4 | Lock/unlock endpoints (`POST`/`DELETE /chapters/{id}/locks`) with hash-freshness check (fail-closed on stale lock) | E13 | python-developer | done |
| TASK-E13-5 | Lock/unlock selection UI in `DiffViewer`/`PaginatedDocument` (UI-selection only, no inline markers) | E13 | frontend-developer | done |

## Phase 10 — Required-Authors/Citation-Grounding Onboarding Input

E14, depends on E04 and E11 (parallel track alongside E12/E13, per `docs/project/plan.md`).

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E14-1 | Extend `sources` module with a must-cite authors/works model | E14 | python-developer | done |
| TASK-E14-2 | `POST /projects/{id}/required-sources` endpoint | E14 | python-developer | done |
| TASK-E14-3 | Boost/require must-cite sources in the RAG query via a Qdrant payload filter (ADR-0002); fail closed (flag unmet requirement) rather than fabricate a citation, per ADR-0001 | E14 | python-developer | done |
| TASK-E14-4 | Onboarding UI input for the required-authors/works list | E14 | frontend-developer | done |

## Phase 11 — In-Place AI Insertion Respecting Locks

E15, depends on E13 and E08; must run strictly after E13, before E16 (not in parallel with either).

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E15-1 | "Insert at anchor" generation mode targeting a `block_id` in the `llm_routing`/generation pipeline | E15 | python-developer | todo |
| TASK-E15-2 | Deterministic post-generation lock guard: locked spans stay in the prompt as read-only context; enforcement recomputes hash-freshness (ADR-0011) and rejects-and-reroutes with an explicit alternative anchor if the proposed anchor overlaps a lock — never trust the model's promise alone | E15 | python-developer | todo |
| TASK-E15-3 | Frontend surfacing of a reject-and-reroute outcome in the diff viewer | E15 | frontend-developer | todo |

## Phase 12 — Multi-Granularity History & Undo/Redo

E16, depends on E15 and E08; needs ADR-0012 (op-log). Must not run in parallel with E13/E15 —
shares the same anchor primitives.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E16-1 | `Operation` op-log model per ADR-0012 (layered on the existing `ChapterVersion` chain, not replacing it) | E16 | python-developer | todo |
| TASK-E16-2 | `POST /chapters/{id}/undo`, `/redo` endpoints: replay/revert `Operation` rows against the current draft; reject with a clear error if an op's anchor block no longer exists | E16 | python-developer | todo |
| TASK-E16-3 | Redo-stack wipe on a new edit applied after an undo (linear op-log, no branching history) | E16 | python-developer | todo |
| TASK-E16-4 | Client-side page-range revert resolution: `PaginatedDocument`'s per-page block indices resolved into a block-id range, sent to the backend as a batch-undo | E16 | frontend-developer | todo |
| TASK-E16-5 | Undo/redo UI controls at whole-document/page-range/paragraph-or-line granularity | E16 | frontend-developer | todo |

## Phase 13 — Celery-Based Async Task Offloading

E17, orthogonal/parallel track; needs ADR-0013 (Redis broker) resolved; should land before E15/E16
begin real work, per `docs/project/plan.md`.

| ID | Task | Epic | Owner Role | Status |
| --- | --- | --- | --- | --- |
| TASK-E17-1 | New `redis` service in `docker-compose.yml` + Celery app config (broker + result backend) per ADR-0013 | E17 | python-developer | todo |
| TASK-E17-2 | New `worker` package: task modules `llm_routing.tasks`, `sources.tasks`, `humanizer.tasks`, `formatting.tasks` | E17 | python-developer | todo |
| TASK-E17-3 | Redis Pub/Sub progress bridge into the existing SSE generators (ADR-0009), buffering the last N events per `task_id` for late subscribers | E17 | python-developer | todo |
| TASK-E17-4 | Migrate parsing/humanization/plagiarism-precheck/generation endpoints to enqueue Celery tasks instead of running inline | E17 | python-developer | todo |
