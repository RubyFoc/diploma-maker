# Formatting-Sample Upload + Qdrant RAG Store

## Date
2026-08-05

## PRD Section
§3.2 (source management/RAG), §3.4 (formatting-by-example)

## Summary
Two more parallel backend tasks, both independent modules built concurrently in the same
working tree:

**`formatting/upload.py` + router (TASK-E05-2):** `POST /formatting/institution-configs/upload`
accepts a `.docx` sample, parses page size/margins/orientation, default font, and a best-effort
citation-style guess (simple bracket/author-year regex heuristic, not an NLP classifier), then
persists an `InstitutionConfig` (`source="upload"`) via TASK-E05-1's storage layer. Fails closed
(4xx) on an unparseable file rather than guessing.

**`sources/client.py` (TASK-E04-1):** `QdrantSourceStore` wraps Qdrant for chunk
ingestion/similarity search, with per-chunk deterministic point IDs (safe re-ingestion after a
partial failure) and a `SourceIngestionError` carrying which chunks succeeded before a mid-batch
failure.

## Embedding Model Change (ADR-0010 revised)
Initially implemented with `sentence-transformers`, which pulls a full CUDA-enabled `torch`
(>1.5GB across `torch`/`triton`/`nvidia-*` packages) purely for CPU-only inference — impractical
and, in this environment, failed to even download (network timeout on a 500MB+ package).
Swapped to `fastembed` (Qdrant's own ONNX-based embedding library, ~20MB install, no GPU deps,
same `BAAI/bge-small-en-v1.5` 384-dim output) — see the revised ADR-0010.

## Bugs Found and Fixed During Integration
Both tasks were implemented by parallel agents in the same working tree; integrating them
surfaced two real bugs, fixed directly:
1. **Unhandled `zipfile.BadZipFile`** in `parse_formatting_sample` — an invalid upload crashed
   with a 500 instead of the intended 4xx fail-closed response. Fixed by adding
   `zipfile.BadZipFile` to the caught exception types.
2. **EMU→mm rounding noise** — `python-docx` margin values round-tripped as e.g. `30.00375` mm
   instead of a clean `30`, since page-margin lengths are stored as EMUs internally. Fixed by
   rounding to the nearest mm in `_parse_page` (formatting rules are specified in whole mm
   anyway).
3. **`UPLOADS_DIR` broke in Docker** — computed via `Path(__file__).resolve().parents[5]`,
   assuming the local dev directory depth (`formatting/ -> ... -> repo root`); the Docker image
   copies `src` to `/app/src`, a shallower path, so the backend container crash-looped with
   `IndexError: 5` on startup. Caught immediately by rebuilding the container after this change
   (per the project's "always rebuild after a change" rule) rather than only trusting local
   `pytest`. Fixed by making `UPLOADS_DIR` an env var (`UPLOADS_DIR`, default `uploads` relative
   to cwd) instead of counting parent directories; `docker-compose.yml` now sets it to
   `/app/uploads` with a dedicated named volume for persistence.

## Files Changed
- `apps/backend/src/diploma_backend/formatting/{upload,router}.py` (new)
- `apps/backend/tests/test_formatting_upload.py` (new)
- `apps/backend/src/diploma_backend/sources/{__init__,client}.py` (new)
- `apps/backend/tests/test_sources.py` (new)
- `apps/backend/pyproject.toml` (added `fastembed`, `qdrant-client`, `python-docx`,
  `python-multipart`; extended ruff's `extend-immutable-calls` for `File`/`Form`)
- `docs/architecture/decisions.md` (ADR-0010 added, then revised same-day for the embedding
  model swap)

## Verification
- `uv run pytest -q` — 26 passed, 1 skipped (opt-in live DeepSeek test).
- `uv run ruff check .` — all checks passed.
- `docker compose up -d --build` — full stack rebuilt and healthy after this change.

## Residual Risks
- Citation-style detection is a simple regex heuristic (documented as such); will misclassify
  styles it has no rule for.
- `fastembed`'s model file is downloaded on first use — needs network access on first run in any
  new environment (dev, CI, prod).
- No uniqueness index on `institution_id` yet (same residual risk as TASK-E05-1).

## Docs Updated
- `docs/project/tasks.md` — TASK-E05-2 and TASK-E04-1 marked `done`; TASK-E04-2, TASK-E04-4
  unblocked to `ready`.
- `docs/architecture/decisions.md` — ADR-0010 revised (fastembed, not sentence-transformers).
