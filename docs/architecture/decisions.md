# Decision Log (ADR-lite)

Use `adr-template.md` for each entry. Append new decisions below; never edit history, only
supersede.

## Open ADRs (block implementation until resolved)

| # | Decision needed | Blocks | Why irreversible |
| --- | --- | --- | --- |
| 7 | Token pricing/markup formula for paid usage beyond the free tier | E09 pricing logic only (not E02's ledger schema or the free-tier mechanic) | Money-adjacent; user wants to base it on real observed per-user cost data before committing to a number |

ADRs #1–#6 below are resolved with architect-recommended defaults, accepted 2026-08-04. All
carry the same caveat: **revisit if real usage data contradicts the assumption behind them** —
they were not battle-tested against production traffic.

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
