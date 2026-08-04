# Phased Delivery Plan

Consolidated by the coordinator from `docs/project/epics.md` (BA scope + architect build
sequence) and `docs/architecture/decisions.md` (ADR-0001..0006, 0008, 0009 resolved; ADR-0007
open/deferred, non-blocking). See `.ai/team/workflow.md` for the role process this plan feeds
into.

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

## Deferred / Not Scheduled
- ADR-0007 (token pricing/markup): revisit once the user supplies real observed
  `deepseek_cost_usd` data from Phase 0+ usage. No epic is blocked on this.
- DeepSeek API account/tier provisioning: user-side action item, needed before Phase 1 Track B
  (E03) can run against a real endpoint instead of a mock.

## Process Note
Per `docs/operations/github-workflow.md` (updated 2026-08-04): direct push to `main` is the
current delivery mode — no PR or branch-protection gate. CI (`docs-check`, `backend`, `frontend`)
still runs on every push and should stay green.
