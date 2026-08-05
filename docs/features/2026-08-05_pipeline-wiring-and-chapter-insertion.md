# Pipeline Wiring (Humanize + Plagiarism Precheck) + Chapter-Boundary Insertion

## Date
2026-08-05

## PRD Section
§3.3 (humanization/plagiarism pipeline order), §6 (TOC-aware chapter insertion)

## Summary
Two independent tasks, deliberately split by file ownership to run in parallel safely (both would
otherwise touch `projects/`): one agent owned `projects/router.py` exclusively; the other worked
only in `projects/service.py` and its own test file.

**Pipeline wiring (TASK-INT-3):** `humanizer/pipeline.py` (TASK-E07-1) and
`plagiarism/precheck.py` (TASK-E07-2) existed as fully-tested but completely unwired standalone
modules — the generation endpoint returned raw, unhumanized, unchecked LLM output. Now
`generate_chapter_draft_endpoint` runs: generate (heavy tier, unchanged) → humanize (fast tier,
reusing the same `DeepSeekClient`) → plagiarism/AI-fingerprint precheck → persist. Humanization
failure handling is deliberately **fail-open**: a `HumanizationError` (citation placeholder
corrupted) falls back to the pre-humanization text rather than failing the whole request —
documented as a conscious tradeoff, since humanization is cosmetic, unlike citation verification
itself (ADR-0001), which stays fail-closed. Citation verification and real RAG excerpts are
still NOT wired into this endpoint (`source_excerpts=[]` passed to `run_precheck`) — a known,
explicitly documented simplification, same pattern as `chapter_summaries=[]`/`rag_excerpts=[]`
already noted in this endpoint's docstring.

**Response shape change:** `POST /projects/{id}/chapters/{id}/generate` now returns
`{"version": ChapterVersion, "precheck": PlagiarismCheckResult}` instead of a bare
`ChapterVersion`. This is a breaking contract change caught and fixed in the same pass — the
frontend's `projectService.generateChapterDraft`, its `GenerateDraftResult`/`PlagiarismCheckResult`
types, and `App.tsx`'s chat-send handler were all updated to destructure `{version, precheck}` and
show a distinct "flagged, review carefully" chat message when `precheck.flagged` is true.

**Chapter insertion (TASK-E10-3, storage layer only):** `insert_chapter_at_order` shifts every
chapter at or after a target order forward by one (single `update_many` with `$inc`, not a loop —
`mongomock-motor` handled it correctly) then inserts the new chapter, avoiding a transient
duplicate-order window. `infer_insertion_order` is a pure, synchronous heuristic: extracts a
leading number from a title (`"Chapter 2"` → `2`) and returns the order of the first existing
chapter numbered `>=` it, falling back to append-at-end when there's no clear numeric signal.
**No HTTP endpoint wires this yet** — deliberately scoped out to avoid a same-file conflict with
the parallel pipeline-wiring task; this follows the same storage-layer-first precedent as
TASK-E05-1 landing before TASK-E05-3's HTTP endpoint.

## Files Changed
- `apps/backend/src/diploma_backend/projects/router.py` (generate endpoint rewired, new
  `GenerateDraftResponse`/`PlagiarismCheckResultResponse` models)
- `apps/backend/tests/test_projects.py` (updated for the new response shape, +2 cases)
- `apps/backend/src/diploma_backend/projects/service.py` (`insert_chapter_at_order`,
  `infer_insertion_order` added)
- `apps/backend/tests/test_chapter_insertion.py` (new, 8 cases)
- `apps/frontend/src/types/project.ts` (`PlagiarismCheckResult`, `GenerateDraftResult` added)
- `apps/frontend/src/services/projectService.ts` (`generateChapterDraft` return type updated)
- `apps/frontend/src/App.tsx` + `App.test.tsx` (destructure `{version, precheck}`, flagged-draft
  message)
- `apps/frontend/src/strings/index.ts` (`chatDraftFlaggedMessage` added)

## Verification
- Backend: `cd apps/backend && uv run pytest -q` — 140 passed, 1 skipped. `uv run ruff check .` —
  clean.
- Frontend: `npx vitest run` — 51/51 passed (10 files, after fixing the contract-change fallout).
  `npx eslint .` — 0 errors. `npx tsc -b` — clean.
- `docker compose up -d --build` — both services rebuilt and healthy.
- **Manual end-to-end smoke test against the live stack** with a real DeepSeek call: created a
  fresh project/chapter, called `/generate`, and confirmed the response now has the
  `{version, precheck}` shape AND that `version.content` is visibly humanized/paraphrased prose
  (not the kind of flat, generic single-sentence output the raw heavy-tier call alone tends to
  produce) — direct evidence the humanize stage is actually running, not just wired and silently
  no-op'd.
- CI checked on GitHub after push.

## Residual Risks
- Citation verification (ADR-0001) is still not wired into generation — accepted citations aren't
  actually being verified/formatted/protected by the humanizer's citation guard in this endpoint
  today, since nothing produces a citation marker in the raw generated text yet. The humanizer's
  citation-preservation logic is correct but currently inert at this call site.
- `run_precheck` always receives `source_excerpts=[]`, so `plagiarism_score` is always `0.0` in
  practice today — the score only becomes meaningful once RAG excerpts are threaded through.
- `insert_chapter_at_order`/`infer_insertion_order` have no HTTP endpoint yet — a caller can't
  actually trigger a mid-sequence chapter insertion through the API today; this is the next
  logical follow-up for TASK-E10-3.
- The generate-endpoint response-shape change was a breaking contract change; it was caught and
  fixed within this same integration pass because the coordinator ran the full frontend test
  suite before pushing, but this highlights the risk of coordinating backend/frontend contract
  changes across two decoupled agent tasks that don't cross-check each other's output — future
  contract changes to this endpoint should be flagged explicitly to whoever owns the frontend
  call site, or verified with an end-to-end run before pushing.

## Docs Updated
- `docs/project/tasks.md` — new "Phase 2.6" section; TASK-E10-3's original Phase 5 row annotated
  as partially done (storage layer only).
