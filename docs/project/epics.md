# Epics

Populated by the coordinator after the first business-analyst + architect planning pass (see
`.ai/team/workflow.md`). Each epic must have a goal, scope, dependencies, and acceptance
criteria, and must map to a section of `Academic_Platform_PRD.md`.

## Problem Statement
Students/researchers writing academic papers spend disproportionate effort on literature
sourcing, university-specific formatting, citation verification, and passing
plagiarism/AI-detection checks. diploma-maker automates that around an interactive chat + diff
workspace, with zero-hallucination citations and per-university formatting learned over time.

## Target Users
Students and researchers producing theses, dissertations, and term papers (PRD §1, §6).

## Scope (MVP = PRD §6 user journey)
| In scope | Out of scope (for now) |
| --- | --- |
| Text generation, formatting, citation verification, humanization, diff review, `.docx` export | Image/diagram generation (explicitly deferred, PRD §3.1 — placeholders only) |
| DeepSeek fast/heavy model routing, RAG-based context caching | Any non-DeepSeek LLM provider |
| MongoDB institution configs + Wallet/Transaction schema | Real payment processing / external billing gateway integration |
| Geo-fenced academic source search, user-uploaded literature | Building/licensing an actual academic search index (assume a third-party API) |

## Non-Goals (E11-E17, BA-confirmed 2026-08-06)
Real-time multi-user collaborative editing; arbitrary/deep chapter nesting beyond 2 levels
(chapter, subchapter); free-text/inline-marker lock instructions (locks are UI-selection only, no
inline markers); keystroke-level undo; building a new citation-verification engine (E14 only adds
a new input to the existing ADR-0001 engine); choosing new LLM providers/payment gateways.

## Candidate Epics

| ID | Epic | PRD Section | Success Criterion (one line) | Depends On |
| --- | --- | --- | --- | --- |
| E01 | Workspace shell (chat + document viewer split) | §3.6 | User can open a project and see chat + empty document panel side by side | — |
| E02 | Auth, user & wallet foundation | §5 | New user can register and receives an initial token allocation | — |
| E03 | LLM routing & context caching | §3.1 | A request is routed to fast or heavy DeepSeek tier per task type, without re-sending prior chapters token-by-token | E02 |
| E04 | Source management & fact-checking (RAG) | §3.2 | Given a claim, the system returns a citation verified verbatim against a retrieved/uploaded source, or flags it as unverifiable | E03 |
| E05 | Institution formatting configs & formatting-by-example | §3.4 | Uploading a sample document produces a stored JSON config with margins/fonts/citation style extracted | E02 |
| E06 | Markdown → `.docx` export engine | §3.4 | Given Markdown + a selected institution config, the system produces a styled `.docx` with image placeholders | E05 |
| E07 | Anti-plagiarism & academic humanization pipeline | §3.3 | Generated text is scored against a plagiarism/AI-fingerprint pre-check before being shown to the user | E03, E04 |
| E08 | Git-like diff viewer & live preview | §3.6 | A generated/edited passage is shown as accept/reject diff; accepted text updates the live WYSIWYG preview | E01, E03 |
| E09 | Feedback loop & crowdsourced template weights | §3.5 | A user's formatting correction increases that university template's accuracy weight, visible on the next generation for that template | E05, E08 |
| E10 | Onboarding & TOC-aware smart insertion | §6 | User selects/uploads a university profile and TOC; generating "Chapter 2" is inserted between existing Chapters 1 and 3 | E01, E05 |
| E11 | Multi-project management (list/switch/delete) | §3.6 | User can list their own projects, switch between them, and delete one with cascading cleanup of its chapters/versions/vectors/files | E01, E02 |
| E12 | Chapter/subchapter data model + sidebar navigation | §3.6 | User can open a subchapter under a chapter from a sidebar tree and work on it independently of its siblings | E11, E10 |
| E13 | Draft ingestion & UI-driven lock/protected-range selection | §3.6 | User uploads an existing draft, selects a block in the UI to lock, and that block is rejected by any later AI edit whose anchor overlaps it | E12, E06 |
| E14 | Required-authors/citation-grounding onboarding input | §3.2 | User supplies a required-author/work list at onboarding and generated citations for that project are boosted/required toward it, still subject to ADR-0001's verify/retry/reject contract | E04, E11 |
| E15 | In-place AI insertion into existing draft content, respecting locks | §3.6 | An AI-proposed insertion whose anchor lands inside a locked block is rejected and rerouted to an explicit alternative anchor, never silently applied | E13, E08 |
| E16 | Multi-granularity history & undo/redo | §3.6 | User can undo/redo at whole-document, page-range, or paragraph/line granularity, and a new edit after an undo discards the redo stack | E15, E08 |
| E17 | Celery-based async task offloading | §3.1, §3.2, §3.3 | Parsing, humanization, plagiarism precheck, and generation run as Celery tasks; a stuck task no longer blocks the API process for unrelated requests | — |

## Build Sequence (architect-reviewed, 2026-08-04)
Confirmed order, with parallel tracks called out:

1. **E02 (auth/wallet) ‖ E01 (workspace shell)** — no dependency between them; backend and
   frontend can start simultaneously.
2. **E05 (institution configs) ‖ E03 (LLM client + routing)** — E05 only needs MongoDB; E03's
   *routing policy* doesn't hard-require E02, only token *accounting* does (soft dependency,
   deduction can be stubbed until E09).
3. **E04 (source management/RAG)** — depends on E03 only for the embedding-call path, not full
   chat routing logic; needs the vector-DB ADR resolved first (see below).
4. **E06 (docx export)** — hard dependency on E05's config schema; can start once E05's schema is
   frozen, in parallel with E04.
5. **E08 (diff viewer)** — UI can be built early against mocked generation output (soft dep on
   E01 only); becomes *end-to-end testable* only once E03 produces real output (hard dep for
   done-criteria, not for starting).
6. **E07 (humanization/plagiarism)** — hard dependency on E03 and E04: operates on generated,
   citation-verified text (PRD §6 step 4 pipeline order: generate → verify → humanize → scan).
7. **E10 (onboarding/TOC-aware insertion)** — depends on E01, E05, and E03 (chapter-boundary
   insertion is an LLM-driven decision, not pure UI logic).
8. **E09 (feedback loop/template weights)** — depends on E05 (templates exist) and E08 (accept/
   reject events are the feedback signal).

Net effect vs. the BA draft: E01/E02 and E05/E03 are parallelizable, not strictly sequential; E08
can start UI-only work much earlier than the BA draft implied — only its *done* criteria wait on
E03.

## Build Sequence — E11-E17 (architect-reviewed, 2026-08-06)
BA's dependency list (E11 -> E12 -> E13 -> E14/E15 in parallel -> E16, E17 orthogonal) is
overridden by the architect's tighter sequencing below, because E13/E15/E16 share the same anchor
primitives (block_id + hash per ADR-0011/ADR-0012) and must not be built in parallel against each
other:

1. **E11** (multi-project management) — no new-epic dependency, needs only E01/E02.
2. **E12** (chapter/subchapter model + sidebar) — needs ADR-0014 (subchapter model) resolved;
   depends on E11.
3. **E13** (lock/protected-range UI) — needs ADR-0011 (lock anchor) resolved; depends on E12.
4. **E15** (in-place AI insertion respecting locks) — depends on E13's lock model directly; must
   not run in parallel with E13 or E16.
5. **E16** (multi-granularity undo/redo) — needs ADR-0012 (op-log) resolved; depends on E15.
   E13 -> E15 -> E16 is a strict sequential spine, despite the BA listing E15/E16 as separate
   parallel dependents of E13 — they share the same anchor primitives and reusing the wrong one
   would force a rewrite.
6. **E14** (required-authors onboarding input) — parallel track, starts once E11's ownership model
   lands; runs alongside E12/E13 since it touches a different module (`sources`).
7. **E17** (Celery offloading) — parallel track, gated only on ADR-0013 (Redis broker) being
   resolved; should land **before** E15/E16 begin real work, since generation/insertion/
   plagiarism-precheck benefit most from async offloading once those epics start producing
   heavier work.

Sequential spine: **E11 -> E12 -> E13 -> E15 -> E16**. Parallel tracks: **E14** (alongside
E12/E13) and **E17** (land before E15/E16 start).

## Architect Non-Functional Notes by Epic
| Epic | Key non-functional concern |
| --- | --- |
| E02 | Wallet/ledger integrity under concurrent requests (no double-spend on token deduction) |
| E03 | LLM timeout/error handling on every call site; cache invalidation when a chapter is edited |
| E04 | RAG store integrity if ingestion is interrupted mid-document; embedding-call failure path |
| E05 | Malformed/ambiguous uploaded formatting samples must fail closed (flag for user review, not guess) |
| E06 | `.docx` assembly failure must not silently drop content — surface a partial-export error |
| E07 | Humanizer must never alter citation text verified by E04 (ordering/immutability constraint) |
| E08 | Diff/version state must survive a page reload mid-review (no lost pending edits) |
| E09 | Template weight adjustments must be auditable (which user correction changed which weight) |
| E10 | Chapter-boundary insertion must not silently overwrite an existing chapter |
| E11 | Cascading delete correctness (Mongo projects/chapters/versions, Qdrant vectors per ADR-0002, uploaded files) must not orphan data |
| E12 | Parent-scoped ordering (ADR-0014) must not break E10's existing chapter-insertion tests |
| E13 | Block-ID persistence discipline: `block_id` must never be re-derived by position/hash on read, only assigned once at block creation |
| E14 | Must fail closed (flag unmet must-cite requirement) rather than fabricate a citation, consistent with ADR-0001 |
| E15 | Anchor representation (ADR-0011) must be designed once and shared with E13/E16, not reinvented per epic |
| E16 | Replay of an op whose anchor block no longer exists must reject with a clear error, not guess a new anchor |
| E17 | A fast Celery task can finish before an SSE subscriber attaches (ADR-0013's buffered-events fix) |

## Diagram Impact
Resolved 2026-08-04: `docs/architecture/diagrams.md` now reflects Qdrant (ADR-0002), the
citation retry/reject contract (ADR-0001), and the version-snapshot diff model (ADR-0004) as
concrete diagrams, not placeholders.

## Cost Estimate (2026-08-04, informs ADR #7 — see `docs/architecture/decisions.md`)
Rough per-stage DeepSeek API cost for a 100-page thesis (1800 chars/page, ~720 tokens/page for
Cyrillic text), using published `deepseek-v4-flash`/`deepseek-v4-pro` pricing:

| Stage | Cost (100 pages, single pass) |
| --- | --- |
| Generation (70% flash / 30% pro, cached context) | ~$0.040 |
| Citation verification (~300 citations + retry-on-failure per ADR-0001) | ~$0.011 |
| Humanization pass (full-text rewrite, flash tier) | ~$0.029 |
| Anti-plagiarism/AI-detection check | ~$0.011 |
| Formatting/`.docx` export | $0 (deterministic code, no LLM call) |
| **Total, single pass** | **~$0.09** |
| **Realistic (with ~1.5x revision overhead from chat edits)** | **~$0.12–0.13** |
| **Pessimistic (cold cache, more retries/pro-tier use)** | **~$0.40–0.60** |

**Known uncertainty:** tokens/page for Cyrillic text, citations/page, and revision-pass count are
estimates, not measurements — re-derive from real usage once the app has traffic, per ADR #7's
deferral below.

## Open Questions
- ~~Academic search provider~~ — resolved 2026-08-04: Semantic Scholar / CORE API for the
  recency+geo-fencing filter (§3.2); geo-filtering (RU/BY) will need to be layered on top since
  neither API has native support for it.
- ~~Institution config authoring~~ — resolved 2026-08-04: upload-and-parse only for MVP (E05); no
  admin UI in this phase.
- ~~Citation-verification failure contract~~ — resolved 2026-08-04: see ADR-0001 in
  `docs/architecture/decisions.md` (retry with alternative source, else reject; format per
  university style).
- **Token pricing/markup formula** — deferred by user decision, 2026-08-04 (see ADR #7 in
  `docs/architecture/decisions.md`); free tier (1 page/day) and wallet/ledger plumbing (ADR #5)
  proceed now, paid-tier price is set once the user supplies real observed cost data.
- DeepSeek API account/tier provisioning (actual API key, rate limits) — still needed before E03
  can be implemented against a real endpoint rather than a mock.

## Assumptions
- MVP scope is exactly the journey in PRD §6; anything else (team-shared configs, non-DeepSeek
  providers, real payment gateway) is out of scope until the user says otherwise.
- Auth is basic email/password unless the user specifies SSO/OAuth requirements.
- "University" and "institution" are used interchangeably with the PRD's terminology.
