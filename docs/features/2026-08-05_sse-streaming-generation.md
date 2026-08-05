# SSE Streaming Generation

## Date
2026-08-05

## PRD Section
§3.6 (chat + diff workflow), ADR-0009 (real-time mechanism)

## Summary
TASK-E08-3, closing out Epic E08 (except live document preview during accepted-content edits,
which was never in scope). Per ADR-0009, chapter generation now streams token-by-token to the
user instead of the existing POST endpoint's blocking full-response wait.

**Backend:** `DeepSeekClient.generate_stream(tier, messages)` (new method, `generate` untouched)
uses `httpx.AsyncClient.stream` with `"stream": true`, parses DeepSeek's OpenAI-compatible SSE
protocol (`data: {"choices":[{"delta":{"content":...}}]}`, terminated by `data: [DONE]`), yields
content chunks. Deliberately has NO retry wrapper — retrying after a partial stream already sent
to the user doesn't make sense the way `llm_routing.retry`'s pre-response retry does for the
non-streaming path; a mid-stream failure surfaces as a real, visible `error` event instead.

New `GET /projects/{id}/chapters/{id}/generate/stream?instruction=<url-encoded text>` (GET with a
query param, not the existing endpoint's POST body — native browser `EventSource` can only issue
GET with no custom body). Streams `event: token` per chunk (multi-line chunks split into multiple
`data:` lines per the SSE spec, never a raw newline inside one line), then — once the full text
is assembled — runs the SAME post-processing the non-streaming endpoint does (humanize → precheck
→ persist) and emits one final `event: done` with the identical `{version, precheck}` JSON shape.
A failure emits `event: error` with `{"detail": ...}` and nothing is persisted.

**Frontend:** `generateStream.ts` wraps `EventSource` construction/listener wiring behind a
`streamChapterDraft(...)` callback API. `ChatPanel.handleSend` now calls this instead of the
awaited-fetch `generateChapterDraft`. Live-streaming text is held in a new `streamingContent`
field on `Chapter` (mirroring how `pendingDraft` was added earlier) — `DocumentPanel` renders it
through the existing `DocumentPreview` component while it's arriving, then swaps to the real
`DiffViewer` once `done` sets `pendingDraft` and clears `streamingContent`. Native `EventSource`
dispatches BOTH a custom backend `error` event and browser-level connection failures under the
same `"error"` type — distinguished by whether `event.data` is present.

## Files Changed
- `apps/backend/src/diploma_backend/llm_routing/client.py` (`generate_stream` added)
- `apps/backend/src/diploma_backend/projects/router.py` (new streaming endpoint)
- `apps/backend/tests/{test_streaming,test_projects_stream}.py` (new, 10 cases)
- `apps/frontend/src/services/generateStream.ts` + `.test.ts` (new)
- `apps/frontend/src/context/DocumentContext.tsx` (`streamingContent` added)
- `apps/frontend/src/utils/mapProject.ts`, `App.tsx` + `App.test.tsx` (wired to the stream)
- `apps/frontend/src/strings/index.ts` (`chapterStreamingLabel` added)

## Verification
- Backend: `cd apps/backend && uv run pytest -q` — 195 passed, 1 skipped. `uv run ruff check .` —
  clean.
- Frontend: `npx vitest run` — 75/75 passed (14 files). `npx eslint .` — 0 errors. `npx tsc -b` —
  clean.
- `docker compose up -d --build` — both services rebuilt and healthy.
- **Real end-to-end live verification, not mocked**: `curl -N` against the live stack's stream
  endpoint with a real DeepSeek call — confirmed ~35 individual `event: token` frames arriving in
  order (real word-by-word streaming), followed by exactly one `event: done` whose `version.content`
  is visibly humanized/paraphrased prose (not the raw streamed tokens concatenated verbatim),
  proving the post-stream humanize→precheck→persist pipeline ran correctly on the fully-assembled
  text.
- CI checked on GitHub after push.

## Residual Risks
- The streaming endpoint has no retry — a transient mid-stream network blip surfaces as a full
  generation failure the user must retry manually, unlike the non-streaming endpoint's
  automatic backoff retry.
- `generateChapterDraft` (the original non-streaming service function) is left in place, unused
  by `ChatPanel` now — harmless dead-ish code for now, but a future cleanup could remove it if
  nothing else ends up needing a non-streaming generation call.
- Citation verification and real RAG excerpts are still not wired into either the streaming or
  non-streaming generation path (`chapter_summaries=[]`/`rag_excerpts=[]` remains a standing
  simplification noted in `projects/router.py`'s module docstring since TASK-INT-1).

## Docs Updated
- `docs/project/tasks.md` — TASK-E08-3 marked `done`.
