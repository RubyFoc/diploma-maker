# Decision Log (ADR-lite)

Use `adr-template.md` for each entry. Append new decisions below; never edit history, only
supersede.

## Open ADRs (block implementation until resolved)

| # | Decision needed | Blocks | Why irreversible |
| --- | --- | --- | --- |
| ADR-0007 | Token pricing/markup formula for paid usage beyond the free tier | E09 pricing logic only (not E02's ledger schema or the free-tier mechanic) | Money-adjacent; user wants to base it on real observed per-user cost data before committing to a number |

ADRs 0001–0006, 0008, and 0009 below are resolved with architect-recommended defaults, accepted
2026-08-04. All carry the same caveat: **revisit if real usage data contradicts the assumption
behind them** — they were not battle-tested against production traffic.

**ADR #7 status: deferred further by user decision, 2026-08-04.** Interim policy: **usage is
unmetered/free while the platform is being built** — no free-tier daily limit is enforced, no
wallet balance is deducted, no paid tier exists yet. `Transaction` rows (ADR-0006) are still
written on every LLM operation purely to **log `deepseek_cost_usd`**, so real cost data
accumulates for when ADR #7 is revisited. Do not build wallet-deduction/insufficient-balance
enforcement logic until the user asks for it — that would be speculative work against an
unresolved ADR.

## Decisions

### ADR-0001: Citation-verification failure contract
- **Date:** 2026-08-04
- **Status:** Accepted
- **Decision:** If a candidate citation cannot be verified verbatim against a retrieved/uploaded
  source, the system first retries with an alternative source/passage supporting the same claim.
  If no verifiable alternative is found, that specific citation is rejected (the claim/citation is
  dropped or the passage is regenerated without it) — the rest of the document generation is
  never blocked for one unverifiable quote. All accepted citations must additionally be
  re-formatted to match the destination university's citation style (extracted via E05) before
  insertion.
- **Consequences:** E04 needs a "find alternative source" retry path, not just a pass/fail check;
  E07's humanizer must not run before this retry/reject step resolves, since it must never touch
  a citation that is still pending verification.

### ADR-0002: Vector database choice
- **Date:** 2026-08-04
- **Status:** Accepted
- **Decision:** Qdrant, self-hosted (already wired into `docker-compose.yml`). Chosen over
  Pinecone (managed, recurring cost, adds an external vendor dependency for a solo-maintainer
  MVP) and Milvus (heavier ops footprint for the same feature set). Qdrant's payload filtering is
  used to scope RAG queries per user/document without separate collections per user.
- **Consequences:** Embeddings and RAG ingestion code (E04) target the Qdrant client API
  directly; migrating to a different store later means rewriting the ingestion/query layer and
  re-embedding all stored content.

### ADR-0003: LLM router policy
- **Date:** 2026-08-04
- **Status:** Accepted
- **Decision:** Static, task-type routing (not a learned complexity-scoring model) per PRD §3.1:
  - `deepseek-v4-flash`: TOC/document-structure parsing, citation verification, humanization pass,
    plagiarism/AI-detection scoring, Markdown formatting.
  - `deepseek-v4-pro`: chapter drafting requiring argument synthesis (literature review synthesis,
    discussion/conclusion sections), complex reasoning, math/table generation.
  - **Context strategy:** each chapter has a compressed summary (~150–300 tokens) stored instead
    of re-sending full prior chapters; RAG retrieval supplies only similarity-matched excerpts.
    System prompt + document summary are kept stable within a session to maximize DeepSeek's
    prompt-cache hit rate (the $0.0028/1M cache-hit tier vs. $0.14–0.435/1M cache-miss).
- **Consequences:** Prompt templates and the summary-compaction logic become a stable contract
  other epics (E04, E07, E08) build against; changing the split later invalidates cached context
  and requires re-tuning prompts.

### ADR-0004: Document diff/versioning data model
- **Date:** 2026-08-04
- **Status:** Accepted
- **Decision:** Immutable version snapshots per chapter/section — no CRDT/operational-transform
  (not needed: single user editing via chat, not concurrent multi-user editing). Each accepted
  edit creates a new version row: `{chapter_id, version_number, content, created_at, status}`.
  A pending LLM-proposed edit is stored as a draft version linked to the current accepted version;
  the diff shown in the UI (E08) is computed on read (text-diff over draft vs. current accepted
  content), not persisted as a separate structure.
- **Consequences:** Simple to implement and reason about; if real-time multi-user collaborative
  editing is ever added, this model needs to be revisited (out of scope for MVP per
  `docs/project/epics.md` scope table).

### ADR-0005: Institution config JSON schema
- **Date:** 2026-08-04
- **Status:** Accepted
- **Decision:**
  ```json
  {
    "institution_id": "string",
    "institution_name": "string",
    "source": "upload | seed",
    "created_at": "iso8601",
    "updated_at": "iso8601",
    "page": { "size": "A4 | Letter", "orientation": "portrait | landscape",
              "margins_mm": { "top": 0, "bottom": 0, "left": 0, "right": 0 } },
    "font": { "family": "string", "size_pt": 0, "line_spacing": 0 },
    "headings": { "h1": {}, "h2": {}, "h3": {} },
    "citation_style": "APA | GOST | MLA | custom",
    "citation_rules": {},
    "toc_rules": {},
    "accuracy_weight": 0.0,
    "raw_sample_reference": "file_id"
  }
  ```
- **Consequences:** E06 (export) and E09 (weight adjustments) consume this shape directly;
  changing field names/structure later requires a migration across every stored institution
  config.
- **Addendum, 2026-08-05:** `source` gains a third value, `"auto"`, alongside the original
  `"upload" | "seed"` — an additive change, not a structural one, per user request to have the
  system try to auto-discover a named university's formatting rules via web search
  (`formatting.discovery`) rather than requiring an upload every time. `"auto"` configs get
  `accuracy_weight=0.3` (unverified web-extracted heuristic, distinctly less trusted than a
  `"seed"` config's `1.0` or a user's own verified upload) — see
  `docs/features/2026-08-05_auto-discovered-institution-formatting.md`.

### ADR-0006: Billing ledger schema
- **Date:** 2026-08-04
- **Status:** Accepted
- **Decision:**
  - `User`: `{id, email, password_hash, created_at}`
  - `Wallet`: `{id, user_id, token_balance, free_pages_used_today, free_pages_reset_at}`
  - `Transaction`: `{id, wallet_id, type: credit|debit, amount_tokens, operation:
    generation|humanization|citation_verify|plagiarism_check|free_tier_grant|purchase,
    reference_id, deepseek_cost_usd (nullable), created_at}`
  - `deepseek_cost_usd` is captured on every operation from day one specifically so the user has
    real per-operation cost data to resolve ADR #7 with later.
  - **Interim policy (2026-08-04):** no enforcement logic yet — don't deduct `token_balance`,
    don't gate on `free_pages_used_today`, don't block on insufficient balance. Every
    `Transaction` is written for cost-logging only; usage is unmetered while ADR #7 is open.
- **Consequences:** Schema is stable regardless of the still-open pricing formula — ADR #7 only
  changes how `amount_tokens` is computed and whether enforcement is turned on, not this shape.

### ADR-0008: Frontend state management
- **Date:** 2026-08-04
- **Status:** Accepted
- **Decision:** React Context + hooks only for the MVP — no Redux/Zustand/Recoil. Workspace state
  is a small, well-bounded set (current chapters/versions, chat message list, pending diffs,
  upload status) manageable with a handful of contexts (e.g. `DocumentContext`, `ChatContext`)
  without store-library machinery.
- **Consequences:** If profiling later shows context-driven re-render problems at real usage
  scale, that becomes a new ADR superseding this one — don't pre-adopt a store library
  speculatively before that happens (per `docs/engineering/best-practices.md`).

### ADR-0009: Real-time chat/diff update mechanism
- **Date:** 2026-08-04
- **Status:** Accepted
- **Decision:** Server-Sent Events (SSE) — FastAPI `StreamingResponse` (`text/event-stream`) for
  streaming LLM chat/generation output token-by-token to the frontend (`EventSource` client).
  Rejected: plain polling (too laggy for a streaming-chat UX) and WebSocket (bidirectional
  push infra the MVP doesn't need — user input is regular request/response, only the model's
  output needs to stream one-way to the client).
- **Consequences:** Backend generation endpoints must be generator-based/streamable; diff/document
  updates can ride the same SSE stream or be fetched via a normal REST call once a generation
  finishes. Browser auto-reconnect on a dropped SSE connection loses in-flight stream state —
  the first implementation must treat a reconnect as "restart this generation's stream," not
  assume seamless resume.

### ADR-0010: Embedding model
- **Date:** 2026-08-04
- **Status:** Accepted
- **Decision:** Use a local, open-source embedding model via `fastembed` (Qdrant's own
  ONNX-based embedding library, model `BAAI/bge-small-en-v1.5`, 384-dim) for RAG chunk/query
  embeddings, rather than a DeepSeek API call. Verified against DeepSeek's public API docs before
  deciding: DeepSeek's API is chat-completions focused and does not advertise a dedicated
  embeddings endpoint, so ADR-0003's routing policy cannot cover this.
  **Revised 2026-08-05:** initially implemented with `sentence-transformers`, but that pulls a
  full CUDA-enabled `torch` (>1.5GB across `torch`/`triton`/`nvidia-*` packages) purely to run
  CPU-only inference — impractical to install and unrelated to this MVP's needs. Switched to
  `fastembed`: ONNX runtime only, no torch/GPU dependency, purpose-built to pair with Qdrant,
  same 384 embedding dimension.
- **Consequences:** Adds `fastembed` as a backend dependency (small ONNX model file downloaded
  on first use). Embedding quality is capped by a small general-purpose model rather than a
  larger or domain-tuned one — revisit (e.g. a larger local model, or a dedicated hosted
  embeddings API) if retrieval quality proves insufficient once there's real usage to evaluate
  against. Changing the embedding model later requires re-embedding all previously ingested
  chunks (same migration cost noted under ADR-0002).

### ADR-0011: Lock anchor representation for draft protected ranges
- **Date:** 2026-08-06
- **Status:** Accepted
- **Decision:** A lock anchors to a persisted `block_id` (UUID assigned once at block creation,
  never re-derived by position or content on subsequent reads) plus a `block_content_hash`
  captured at lock time, plus an optional intra-block `char_range` for sub-block precision.
  Enforcement recomputes the block's hash immediately before any AI edit touches it; a hash
  mismatch means the lock is stale (the underlying content changed since the lock was set) and the
  edit is rejected and surfaced to the user — fail-closed, same posture as ADR-0001. This requires
  the backend to persist a block manifest (ordered `block_id` + content + hash) per chapter
  version, rather than treating `ChapterVersion.content` (ADR-0004) as an opaque string.
- **Consequences:** E13 (locks module) and every consumer of a chapter's content (E12 sidebar
  nav, E08 diff viewer, E15 insertion, E16 history) must read/write through the block manifest
  instead of raw string content. Retrofitting existing `ChapterVersion` rows without a manifest
  means old versions have no lockable blocks until re-parsed.

### ADR-0012: Fine-grained edit history data model (cross-references ADR-0004)
- **Date:** 2026-08-06
- **Status:** Accepted
- **Decision:** Layer a new `Operation` op-log on top of the existing immutable `ChapterVersion`
  snapshot chain from ADR-0004 — the snapshot chain is not extended or replaced.
  `Operation{id, chapter_id, base_version_id, anchor(block_id + optional char_range), before_text,
  after_text, applied_by, created_at}`. Undo/redo at paragraph/line granularity replays or reverts
  `Operation` rows against the current draft. "Accept" still collapses all accumulated operations
  since the last accepted version into one new `ChapterVersion`, exactly as today. "Page" is never
  a stored backend concept — a page-level revert is resolved client-side (`PaginatedDocument`
  already knows which block indices fall on which page) into a block-id range, then sent to the
  backend as a batch-undo over that range.
- **Consequences:** E16 (history module) owns the `Operation` collection; replaying an op whose
  anchor block no longer exists must reject with a clear error rather than guess a new anchor. A
  new edit after an undo wipes the redo stack (ADR-0012 addendum, see below) — this is a linear
  op-log, not a branching/tree history, so no redo-stack merge logic is needed.
- **Addendum (redo-stack semantics):** A new edit applied after an undo discards the redo stack
  (standard editor behavior), consistent with the linear op-log above.

### ADR-0013: Async task queue for long-running pipeline stages (cross-references ADR-0002,
ADR-0009)
- **Date:** 2026-08-06
- **Status:** Accepted
- **Decision:** Celery, with Redis as both broker and result backend — not a Mongo-backed broker,
  to avoid adding extra load onto the version/ledger datastore that ADR-0002/ADR-0004/ADR-0006
  already depend on. A new `redis` service is added to `docker-compose.yml`. The Celery worker
  publishes progress updates to Redis Pub/Sub keyed by `task_id`; the existing SSE generators
  (ADR-0009) subscribe to that channel and forward events to the browser over the same one-way
  streaming connection — additive to ADR-0009, not a replacement for it. Because a fast task can
  finish before an SSE subscriber attaches, the worker also buffers the last N events per
  `task_id` in Redis so a late subscriber can catch up instead of hanging.
- **Consequences:** E17 (worker package) owns `llm_routing.tasks`, `sources.tasks`,
  `humanizer.tasks`, `formatting.tasks`. Parsing, humanization, plagiarism precheck, and
  generation move off the request/response cycle; the API process no longer blocks on them, so a
  stuck task can no longer take down request handling for unrelated requests.

### ADR-0014: Subchapter data model (first structural change to Chapter)
- **Date:** 2026-08-06
- **Status:** Accepted
- **Decision:** Subchapters are represented as a self-referential `parent_chapter_id: str | None`
  field on the existing `Chapter` collection — not as an embedded array on the parent chapter —
  so each subchapter keeps its own independent version history (ADR-0004) and lock/manifest state
  (ADR-0011). Nesting is capped at two levels (chapter, subchapter); deeper nesting is explicitly
  out of scope per `docs/project/epics.md`. `insert_chapter_at_order`/`infer_insertion_order`
  (from E10) are rescoped from sibling-ordering within `(project_id)` to sibling-ordering within
  `(project_id, parent_chapter_id)`.
- **Consequences:** E12 must not break E10's existing chapter-insertion tests when ordering
  becomes parent-scoped — existing top-level chapters are simply chapters with
  `parent_chapter_id=None`, and their relative ordering logic is unchanged, only newly scoped.
