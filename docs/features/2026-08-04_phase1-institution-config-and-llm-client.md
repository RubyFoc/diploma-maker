# Phase 1: Institution Config Storage + DeepSeek Client

## Date
2026-08-04

## PRD Section
§3.1 (LLM routing), §3.4 (institution formatting configs)

## Summary
Second parallel backend slice (`docs/project/plan.md` Phase 1, both tracks backend this time,
different modules to avoid overlap).

**`formatting` module** (TASK-E05-1): `InstitutionConfig` Pydantic model matching ADR-0005
exactly, plus `create_institution_config`/`get_institution_config`/`list_institution_configs`
against MongoDB. Storage-layer only — no upload/parser (TASK-E05-2) or selection endpoint
(TASK-E05-3) yet.

**`llm_routing` module** (TASK-E03-1): `DeepSeekClient` wrapping DeepSeek's OpenAI-compatible
chat-completions API via `httpx`, with `generate_fast`/`generate_heavy` per ADR-0003's tier
split. Failures (network/timeout/non-2xx) are wrapped in `LLMRequestError`. An opt-in live
integration test exists, skipped unless `RUN_LIVE_DEEPSEEK_TEST=1` is set — not run as part of
normal CI/local test runs.

## Files Changed
- `apps/backend/src/diploma_backend/formatting/{__init__,models,service}.py`
- `apps/backend/tests/test_formatting.py`
- `apps/backend/src/diploma_backend/llm_routing/{__init__,client}.py`
- `apps/backend/tests/test_llm_routing.py`
- `apps/backend/pyproject.toml` (added `pytest-asyncio`, `respx` dev deps; `asyncio_mode = "auto"`)

## Verification
- `uv run pytest -q` — 16 passed, 1 skipped (the opt-in live DeepSeek test).
- `uv run ruff check .` — all checks passed.
- Live DeepSeek endpoint was not exercised against the real API during this task — only the
  documented request/response shape was verified. Run manually with
  `RUN_LIVE_DEEPSEEK_TEST=1 uv run pytest -q tests/test_llm_routing.py -k live` to confirm the
  real key/endpoint once desired.

## Residual Risks
- No uniqueness check on `institution_id` yet — left for whichever task defines real
  create/update semantics (not in scope for schema-only TASK-E05-1).
- `llm_routing` has no retry/backoff policy yet (reserved for TASK-E03-3) and no
  context/summary-compaction caching yet (TASK-E03-2) — a call today is a single request, not
  the full cost/caching-optimized pipeline described in ADR-0003.

## Docs Updated
- `docs/project/tasks.md` — TASK-E05-1 and TASK-E03-1 marked `done`; downstream tasks
  (TASK-E05-2/3, TASK-E04-1, TASK-E06-1) unblocked to `ready`.
