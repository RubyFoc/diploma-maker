# Source Search Integration + Chapter-Summary Compaction

## Date
2026-08-05

## PRD Section
§3.2 (source management/RAG), §3.1 (LLM routing/prompt strategy)

## Summary
Two more independent backend tasks, built concurrently in the same working tree:

**`sources/search.py` (TASK-E04-2):** `search_sources(query, *, min_year=None, limit=10)` queries
the Semantic Scholar Graph API (no key required, optional `SEMANTIC_SCHOLAR_API_KEY` for higher
rate limits) as the primary provider, falling back to CORE API (`CORE_API_KEY` required — skipped
entirely if unset) when Semantic Scholar fails or returns no results. Normalizes both providers'
shapes into `SourceSearchResult` (`title`, `authors`, `year`, `abstract`, `url`, `provider`,
`external_id`) so downstream tasks (E04-3 geo-fencing, E04-4 citation verification) don't need to
know which provider answered. Raises `SourceSearchError` only if every attempted provider fails —
a `[]` result would be indistinguishable from "no relevant sources exist," which is a real
outcome, not a failure.

**`llm_routing/summary.py` (TASK-E03-2):** `summarize_chapter(client, chapter_content)` compacts a
chapter into a ~150-300 token summary via the fast DeepSeek tier (ADR-0003). `assemble_prompt(...)`
builds the message list for a generation call with a strict ordering contract: system prompt,
then a second stable `system`-role message holding all chapter summaries, then a final `user`
message with RAG excerpts + the current turn appended last. This ordering exists specifically so
the stable prefix is byte-identical across calls within a session — DeepSeek's prompt cache keys
on prefix match, and cache-hit input tokens are roughly 50x cheaper than cache-miss (ADR-0003).
Reordering or interleaving volatile content earlier in the message list would silently blow the
cache-hit rate without any functional test catching it, so this contract is documented directly
in the module docstring, not just here.

## Files Changed
- `apps/backend/src/diploma_backend/sources/search.py` (new)
- `apps/backend/tests/test_source_search.py` (new, 11 cases incl. both-provider-fail and
  fallback paths)
- `apps/backend/src/diploma_backend/sources/__init__.py` (re-exports)
- `apps/backend/src/diploma_backend/llm_routing/summary.py` (new)
- `apps/backend/tests/test_summary.py` (new, incl. an explicit stable-prefix-identity check)
- `apps/backend/src/diploma_backend/llm_routing/__init__.py` (re-exports)

## Verification
- `uv run pytest -q` — 41 passed, 1 skipped (opt-in live DeepSeek test).
- `uv run ruff check .` — all checks passed.
- `docker compose up -d --build` — backend rebuilt, `/health` returns `{"status":"ok"}`.

## Residual Risks
- Semantic Scholar's and CORE's actual response shapes were assumed from general API knowledge,
  not verified against a live call (WebFetch on both providers' doc pages didn't return usable
  schema detail in this environment). Field-mapping is isolated to two small parsing functions in
  `search.py`, so a live-call correction later is a localized fix.
- `summarize_chapter`'s `max_tokens=400` cap is a proxy for "~150-300 tokens of prose" — no local
  tokenizer is used to measure the actual output length precisely.
- Chapter-summary persistence (attaching a summary to a chapter/version record) is not yet wired
  up — that lives with TASK-E08-1 (blocked on TASK-E01-3), still pending.

## Docs Updated
- `docs/project/tasks.md` — TASK-E04-2 and TASK-E03-2 marked `done`; TASK-E04-3 unblocked to
  `ready`.
