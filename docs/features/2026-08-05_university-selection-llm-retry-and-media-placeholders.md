# University Selection Endpoints + LLM Retry Policy + Media Placeholders

## Date
2026-08-05

## PRD Section
§3.4 (institution selection), §3.1 (LLM routing resilience), §3.4 (export placeholders)

## Summary
Three more independent backend tasks, built concurrently in the same working tree — this batch
completes **Phase 0 through Phase 3** of `docs/project/plan.md` entirely.

**`formatting/router.py` (TASK-E05-3):** `GET /formatting/institution-configs` (list, for a
frontend dropdown) and `GET /formatting/institution-configs/{institution_id}` (404 if unknown).
Returns full `InstitutionConfig` objects rather than a slimmer summary shape — the config list is
small and not a hot path, so a second schema to keep in sync with ADR-0005 wasn't worth it.

**`llm_routing/retry.py` (TASK-E03-3):** `generate_with_retry` wraps `DeepSeekClient.generate`
with exponential backoff (`base_delay_seconds * 2**attempt`), up to `max_attempts` total tries.
Retries every `LLMRequestError` uniformly — the base client currently collapses network errors,
timeouts, non-2xx statuses, and malformed responses into the same exception type without
exposing a status code, so there's no signal yet to distinguish transient from permanent
failures. Raises the same `LLMRequestError` type on final failure so existing `except
LLMRequestError` call sites are unaffected.

**`export/docx.py` (TASK-E06-3):** New `[[figure: <description>]]` placeholder line syntax
renders as an italicized `[FIGURE PLACEHOLDER: <description>]` paragraph. This is deliberately a
placeholder, not real image embedding — DeepSeek is text-only, so generation prompts are expected
to emit this marker wherever a figure belongs, and a human author fills it in later. Standard
Markdown image syntax (`![alt](url)`) is intentionally NOT recognized, since it implies a real
image the LLM can't produce.

## Files Changed
- `apps/backend/src/diploma_backend/formatting/router.py` (list/get endpoints added)
- `apps/backend/tests/test_formatting_list.py` (new)
- `apps/backend/src/diploma_backend/llm_routing/retry.py` (new)
- `apps/backend/tests/test_retry.py` (new)
- `apps/backend/src/diploma_backend/llm_routing/__init__.py` (re-export)
- `apps/backend/src/diploma_backend/export/docx.py` (`[[figure: ...]]` placeholder support)
- `apps/backend/tests/test_export_docx.py` (+2 tests)

## Verification
- `uv run pytest -q` — 87 passed, 1 skipped (opt-in live DeepSeek test).
- `uv run ruff check .` — all checks passed.
- `docker compose up -d --build` — backend rebuilt, `/health` returns `{"status":"ok"}`.

## Residual Risks
- Retry-all-uniformly means a permanent failure (e.g. bad API key) gets retried `max_attempts`
  times before surfacing, wasting time/cost on calls that can never succeed. Documented as a
  known limitation — fixing it requires `DeepSeekClient` to expose the HTTP status code on
  `LLMRequestError`, deferred to avoid destabilizing existing callers/tests.
- The figure-placeholder contract (`[[figure: ...]]`) is now a hard dependency for E03's chapter
  generation prompts — if prompt templates don't emit exactly this syntax, figures silently fall
  through to plain literal text instead of a visible placeholder.

## Docs Updated
- `docs/project/tasks.md` — TASK-E05-3, TASK-E03-3, TASK-E06-3 marked `done`. This closes out
  **Phase 0-3** entirely. Unblocked: TASK-E08-1/E08-2/E08-3 (diff/versioning/SSE), TASK-E07-1
  (humanizer), TASK-E10-1/E10-2 (onboarding, TOC upload).
