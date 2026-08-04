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
