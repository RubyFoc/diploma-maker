# Architecture Overview

## Shape
Organize backend code by **pipeline stage**, not generic layers. Each stage is a module under
`apps/backend/src/diploma_backend/`:

| Stage | Module | Responsibility |
| --- | --- | --- |
| LLM routing & caching | `llm_routing` | Route requests to fast/heavy DeepSeek models; manage compressed-summary + RAG context to avoid full re-reads (PRD §3.1). |
| Source management | `sources` | Search/ingest literature (recency + geo filters), user-uploaded PDFs, citation verification against retrieved text (PRD §3.2). |
| Anti-plagiarism & humanization | `humanizer` | Internal plagiarism/AI-fingerprint pre-check; post-processing to break LLM text patterns (PRD §3.3). |
| Formatting & export | `formatting` | Parse formatting-by-example uploads; map Markdown output to institution JSON config; assemble `.docx` (PRD §3.4). |
| Feedback loop | `feedback` | Approve/reject/edit signals; per-institution formatting-accuracy weight adjustments (PRD §3.5). |
| Billing | `billing` | `User`/`Wallet`/`Transaction` entities; usage-based token accounting (PRD §5). |

Frontend is a single React + TypeScript app (`apps/frontend/`) consuming the backend's HTTP API;
no separate BFF layer for the MVP.

## Data Stores
- **MongoDB**: user profiles, institution formatting configs, wallet/transaction ledger.
- **Vector DB (Qdrant)**: draft chapter embeddings and literature embeddings for RAG retrieval and
  citation verification.

## Non-Functional Concerns (apply project-wide)
- Never leak DeepSeek API keys, MongoDB/Qdrant URIs, or raw user document content into logs.
- Every LLM call site must have an explicit failure path (timeout/error -> retry or user-facing
  error, never silent data loss).
- Citation verification must fail closed: if a quote can't be verified verbatim against a source,
  it is flagged, not silently accepted.

## MVP Boundary
Image generation is deferred; the LLM inserts semantic placeholders instead (PRD §3.1). Do not
build an image-generation pipeline without an explicit ADR and user confirmation.
