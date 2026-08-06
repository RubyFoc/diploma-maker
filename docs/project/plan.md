# Phased Delivery Plan

Consolidated by the coordinator from `docs/project/epics.md` (BA scope + architect build
sequence) and `docs/architecture/decisions.md` (ADR-0001..0006, 0008, 0009, 0010 resolved;
ADR-0007 open/deferred, non-blocking). See `.ai/team/workflow.md` for the role process this plan
feeds into.

**2026-08-06 addition:** E11-E17 (multi-project management, chapter/subchapter model, draft
locks, required-authors onboarding input, in-place AI insertion, multi-granularity undo/redo,
Celery offloading) land ADR-0011..0014 (see `docs/architecture/decisions.md`) and are sequenced
in Phases 7-13 below.

## Phase 0 — Foundations (parallel tracks)
- **Track A:** E02 — Auth, user & wallet foundation (schema only per ADR-0006; no enforcement
  logic, per ADR-0007 interim policy)
- **Track B:** E01 — Workspace shell (chat + document viewer split)

No dependency between tracks; `python-developer` and `frontend-developer` can start
simultaneously.

## Phase 1 — Core services (parallel tracks)
- **Track A:** E05 — Institution formatting configs & formatting-by-example (needs only MongoDB,
  schema per ADR-0005)
- **Track B:** E03 — LLM routing & context caching (needs E02's client/auth plumbing to exist,
  not its billing enforcement; routing policy per ADR-0003)

## Phase 2
- E04 — Source management & fact-checking / RAG (needs E03's embedding-call path + Qdrant per
  ADR-0002; citation retry/reject contract per ADR-0001)

## Phase 3 (parallel tracks)
- **Track A:** E06 — Markdown → `.docx` export engine (hard dependency: E05's frozen config
  schema)
- **Track B:** E08 — Git-like diff viewer & live preview, UI-only slice against mocked generation
  output (soft dependency: E01 only; SSE wiring per ADR-0009 comes once E03 has real output)

## Phase 4
- E07 — Anti-plagiarism & academic humanization pipeline (hard dependency: E03 + E04, per PRD §6
  pipeline order: generate → verify → humanize → scan)

## Phase 5
- E10 — Onboarding & TOC-aware smart insertion (depends on E01, E05, E03)

## Phase 6
- E09 — Feedback loop & crowdsourced template weights (depends on E05, E08)

## Phase 7 — Multi-project management (sequential spine)
- E11 — Multi-project management (list/switch/delete), cascading delete across Mongo/Qdrant/files.
  First step of the E11 -> E12 -> E13 -> E15 -> E16 spine (architect-reviewed 2026-08-06,
  overrides the BA's looser dependency list — see `docs/project/epics.md`).

## Phase 8 — Chapter/subchapter model + sidebar nav (sequential spine)
- E12 — needs ADR-0014 (subchapter data model) resolved; depends on E11.

## Phase 9 — Draft ingestion & lock/protected-range selection (sequential spine)
- E13 — needs ADR-0011 (lock anchor representation) resolved; depends on E12.

## Phase 10 — Required-authors/citation-grounding onboarding input (parallel track)
- E14 — depends on E04 and E11's ownership model only; runs alongside Phase 8/9 (E12/E13), touches
  a different module (`sources`), not on the sequential spine.

## Phase 11 — Celery-based async task offloading (parallel track, land before Phase 12/13)
- E17 — needs ADR-0013 (Redis broker/result backend) resolved; orthogonal to the spine, but should
  land **before** E15/E16 begin real work since generation/insertion/plagiarism-precheck benefit
  most from async offloading once those epics start producing heavier work.

## Phase 12 — In-place AI insertion respecting locks (sequential spine)
- E15 — depends directly on E13's lock model; needs ADR-0011. Must **not** run in parallel with
  E13 or E16 — despite the BA listing E15/E16 as separate parallel dependents of E13, the
  architect's sequencing forces E13 -> E15 -> E16 strictly sequential because they share the same
  anchor primitives (block_id + hash).

## Phase 13 — Multi-granularity history & undo/redo (sequential spine)
- E16 — needs ADR-0012 (op-log layered on ADR-0004) resolved; depends on E15. Last step of the
  spine.

## Deferred / Not Scheduled
- ADR-0007 (token pricing/markup): revisit once the user supplies real observed
  `deepseek_cost_usd` data from Phase 0+ usage. No epic is blocked on this.
- DeepSeek API account/tier provisioning: user-side action item, needed before Phase 1 Track B
  (E03) can run against a real endpoint instead of a mock.

## Process Note
Per `docs/operations/github-workflow.md` (updated 2026-08-04): direct push to `main` is the
current delivery mode — no PR or branch-protection gate. CI (`docs-check`, `backend`, `frontend`)
still runs on every push and should stay green.
