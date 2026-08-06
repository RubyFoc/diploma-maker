# Anti-Plagiarism Upgrades: Sentence Flags, File Upload, Dash Normalization

## Date
2026-08-06

## PRD Section
§3.3 (anti-plagiarism/AI-detection, "Killer Feature"), user request

## Summary
Extended the E07 heuristic anti-plagiarism/AI-fingerprint MVP (`plagiarism/precheck.py`,
`POST /plagiarism/check`) with four upgrades, all user-requested, keeping the existing
local-heuristic scope (no real vendor API):

1. **Per-sentence flags.** `flag_sentences` scores each sentence individually: its own
   shingle-overlap ratio against `source_excerpts` (`is_plagiarized`), and whether its first
   word is a repeated sentence-starter across the document (`is_ai_like`). Both are exposed on
   `PlagiarismCheckResult.sentence_flags` and rendered as highlighted spans in
   `PlagiarismResultView`. Sentence-length uniformity (the other AI-fingerprint sub-signal)
   stays a document-level-only statistic — it isn't meaningfully attributable to one sentence.
2. **Originality %.** `PlagiarismCheckResult.originality_score` (`1.0 - plagiarism_score`) is
   now returned and rendered as its own labeled score bar, alongside the existing plagiarism and
   AI-fingerprint bars.
3. **File upload tab.** New `POST /plagiarism/check-file` accepts a `.docx` or `.pdf` upload,
   extracts its text (`plagiarism/extract.py`, via `python-docx` / `pypdf`), and runs the same
   `run_precheck` as the paste-text endpoint. New "plagiarism-upload" tab
   (`PlagiarismUploadPanel.tsx`) in the frontend tab bar, sharing the same result view as the
   existing paste-text tab.
4. **Dash normalization.** `humanizer.pipeline.normalize_dashes` replaces every em-dash ("—")
   with an en-dash ("–") in humanized output, applied automatically inside `humanize_text` with
   no caller changes — every generated chapter gets this for free.

## Files Changed
- `apps/backend/src/diploma_backend/plagiarism/precheck.py` — `SentenceFlag`, `flag_sentences`,
  `originality_score`/`sentence_flags` fields, shared `_shingle_overlap_ratio` /
  `_sentence_starters` helpers.
- `apps/backend/src/diploma_backend/plagiarism/router.py` — `SentenceFlagResponse`, extended
  `PlagiarismCheckResultResponse`, new `POST /plagiarism/check-file` endpoint.
- `apps/backend/src/diploma_backend/plagiarism/extract.py` (new) — `PlagiarismFileParseError`,
  `extract_text_from_docx`, `extract_text_from_pdf`, `extract_text` dispatcher.
- `apps/backend/src/diploma_backend/humanizer/pipeline.py` — `normalize_dashes`, wired into
  `humanize_text`.
- `apps/backend/pyproject.toml` / `uv.lock` — added `pypdf`.
- `apps/backend/tests/test_plagiarism.py`, `test_plagiarism_extract.py` (new),
  `test_plagiarism_router.py`, `test_humanizer.py` — extended/added coverage.
- `apps/frontend/src/types/project.ts` — `PlagiarismSentenceFlag`, extended
  `PlagiarismCheckResult`.
- `apps/frontend/src/services/plagiarismService.ts` — `checkPlagiarismFile`.
- `apps/frontend/src/components/PlagiarismResultView.tsx` (new) — shared result rendering
  (banner, three score bars, reasons, sentence-flag highlighting).
- `apps/frontend/src/components/PlagiarismCheckPanel.tsx` — delegates result rendering to
  `PlagiarismResultView`.
- `apps/frontend/src/components/PlagiarismUploadPanel.tsx` (new) — file-upload tab panel.
- `apps/frontend/src/components/PlagiarismCheckPanel.css` — sentence-highlight and upload-panel
  styles.
- `apps/frontend/src/strings/index.ts` — new `plagiarismCheckOriginalityScoreLabel`,
  `plagiarismCheckSentenceFlagsTitle`, `tabPlagiarismUploadLabel`, `plagiarismUpload*` keys.
- `apps/frontend/src/App.tsx` — third `plagiarism-upload` tab.
- Matching `*.test.tsx`/`*.test.ts` updates for all of the above.

## Verification
- Backend: `uv run pytest -q` — 221 passed, 1 skipped. `uv run ruff check .` — clean.
- Frontend: `npm run build` (tsc + vite) — clean. `npm run lint` — 0 errors (pre-existing
  unrelated warnings only). `npx vitest run` — 87/87 passed across 16 files.
- No manual browser smoke test was performed in this pass — build/lint/test suites only.

## Residual Risks
- Still heuristic-only, same as the original E07 MVP: no real plagiarism/AI-detection vendor
  integration. `is_ai_like`/`is_plagiarized` are coarse local signals, not verdicts.
- PDF text extraction has no OCR fallback — a scanned/image-only PDF with no embedded text
  layer will fail to extract and return a 400, not a best-effort partial result.
- `POST /plagiarism/check-file` does not accept `source_excerpts` (unlike the paste-text
  endpoint) — a deliberate simplification since there's no natural way to pair a second set of
  source files with the multipart upload in this pass.
- Dash normalization only replaces em-dash → en-dash inside the humanizer pipeline; text that
  bypasses humanization (e.g. a user manually editing an accepted chapter) is not normalized.

## Docs Updated
- `docs/project/tasks.md` — new "Phase 5.8" section, TASK-INT-13/14/15 `done`.
