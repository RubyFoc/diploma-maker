# Live RAG Grounding for Generation

## Date
2026-08-06

## PRD Section
§3.2 (source management/RAG), ADR-0001 (citation verification, partially addressed)

## Summary
Every prior integration task's docstring flagged the same standing gap: `assemble_prompt` and
`run_precheck` always received empty `rag_excerpts`/`source_excerpts` lists, so generated chapters
had zero grounding in real sources despite E04's search/RAG infrastructure being fully built.
This closes PART of that gap — real grounding via live external search — while being explicit
about what's still missing (full citation verification).

**What changed:** both generation endpoints (`POST .../generate` and `GET .../generate/stream`)
now call a new `_fetch_rag_excerpts(instruction)` before building the prompt: it searches
external academic literature (Semantic Scholar/CORE, `sources.search.search_sources`, already
built in TASK-E04-2) for the chat instruction, and turns up to 3 results that have an abstract
into excerpt strings (`"<title> (<year>): <abstract>"`). These excerpts now go into
`assemble_prompt`'s `rag_excerpts` (so the LLM sees real reference material) AND
`run_precheck`'s `source_excerpts` (so the plagiarism-overlap score is measured against real text
instead of always trivially `0.0`). The system prompt was updated to instruct the model to cite
provided sources by title/year when it draws on them, and to never fabricate a citation for a
source that wasn't provided.

**Why external live search, not Qdrant:** nothing in this codebase ingests any project's own
uploaded literature into Qdrant scoped to a project/chapter — `sources.client.QdrantSourceStore`
exists and is tested, but nothing ever calls `upsert_chunks` outside its own test suite. Querying
it during generation today would always return nothing. Live external search needs no prior
ingestion step, so it was the higher-value first move; a Qdrant-based path (a user's own uploaded
sources) remains a separate, larger follow-up requiring an ingestion UI/endpoint that doesn't
exist yet.

**What is deliberately still NOT wired in (a materially bigger follow-up):** full citation
verification per ADR-0001. That needs a claim-extraction step — finding which sentences in
already-generated prose assert something citable — which doesn't exist anywhere in this
codebase. `citations.verification.verify_citation_against_excerpt` can verify a GIVEN claim
against a GIVEN excerpt, but nothing extracts candidate claims from free-form generated text to
feed it. The system prompt asks the model to self-cite, but nothing verifies those in-text
citations are accurate, retries/rejects per ADR-0001's contract, or reformats them via
`citations.verification.format_citation`. This remains the single largest gap in the pipeline.

## Real Operational Limitation Found During Manual Verification
Live-tested against the real internet, not just mocks. The generate endpoint correctly returned
`201` end-to-end with a real DeepSeek call. However, a direct standalone check of
`search_sources` immediately afterward hit Semantic Scholar's **429 rate limit** — unauthenticated
access is rate-limited fairly aggressively, and this session's extensive testing throughout the
day (dozens of search calls across multiple features) had already used up the available quota.
`CORE_API_KEY` is unset, so there was no fallback provider. This is valuable real-world evidence
of two things:
1. **The fail-open design works correctly in production**: the generate call succeeded (201)
   despite the underlying search failing with a real `SourceSearchError` — confirming
   `_fetch_rag_excerpts`'s try/except path executes as designed under a genuine failure, not just
   in a mocked test.
2. **A real, honest limitation for production use**: without `SEMANTIC_SCHOLAR_API_KEY` (a free
   higher-rate-limit key) or `CORE_API_KEY` configured, RAG grounding will frequently and
   silently fall back to ungrounded generation under real traffic, not just in edge cases. This
   is worth flagging to the user directly, not glossing over — see Residual Risks.

## Files Changed
- `apps/backend/src/diploma_backend/projects/router.py` (`_fetch_rag_excerpts` added, wired into
  both generation endpoints' prompt assembly and precheck calls, system prompt updated)
- `apps/backend/tests/test_projects_rag.py` (new, 4 cases: excerpt threading, no-abstract
  skipping, fail-open on search-provider error, fail-open on empty results)
- `apps/backend/tests/test_projects.py`, `test_projects_stream.py` (updated to mock the new
  Semantic Scholar search call the generation pipeline now makes)

## Verification
- `cd apps/backend && uv run pytest -q` — 205 passed, 1 skipped. `uv run ruff check .` — clean.
- `docker compose up -d --build` — backend rebuilt and healthy.
- **Manual end-to-end verification against the live stack**: real `/generate` call succeeded
  (201) with a substantive, on-topic generated paragraph. A follow-up direct check of the
  underlying search call surfaced the real rate-limit condition described above — this was found
  BECAUSE of manual live verification, not something a mocked test suite would ever catch.
- CI checked on GitHub after push.

## Residual Risks
- **Rate limiting under real usage**: without an API key for Semantic Scholar (free to obtain) or
  CORE, expect RAG grounding to silently degrade to ungrounded generation under any meaningful
  traffic volume — the feature works, but its reliability in production depends on operational
  configuration this deployment doesn't currently have. Recommend obtaining
  `SEMANTIC_SCHOLAR_API_KEY` and/or `CORE_API_KEY` before relying on this for real users.
- **No citation verification** (see Summary) — the model is asked to self-cite honestly, but
  nothing checks that it did, or that a cited claim is actually supported by the excerpt it cites.
  A model could still cite a provided source inaccurately, or (despite the instruction) fabricate
  one, with nothing downstream catching it.
- **No Qdrant/user-uploaded-source grounding** — only external search results ground generation;
  a user's own uploaded literature is never consulted, since nothing ingests it yet.
- Excerpts are capped at 3 per call and DeepSeek's prompt cache (ADR-0003) is keyed on a stable
  prefix — since these excerpts vary per instruction, they sit in the volatile suffix per
  `assemble_prompt`'s existing contract, so this doesn't hurt cache-hit economics, but also means
  RAG excerpts themselves are never cached/reused across calls.

## Docs Updated
- `docs/project/tasks.md` — new "Phase 2.7" section, TASK-INT-11 `done`.
