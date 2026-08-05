# Anti-Plagiarism Pre-Check + Registration/University Onboarding

## Date
2026-08-05

## PRD Section
§3.3 (plagiarism/AI-detection pre-check), §6 (onboarding: registration + university selection)

## Summary
Two more independent tasks (backend + frontend), built concurrently in the same working tree.

**`plagiarism/precheck.py` (TASK-E07-2):** The final pipeline gate per PRD §6's order (generate
→ verify citations → humanize → scan). Like `citations.verification`'s text-overlap heuristic,
this is an explicitly documented placeholder, not a real Turnitin/GPTZero integration:
- `score_plagiarism_risk(text, source_excerpts)` — 5-word shingle overlap ratio between the text
  and its cited sources. Documented nuance: some overlap is healthy for a well-cited chapter
  (verified quotes are *supposed* to match their source verbatim per ADR-0001) — this score is a
  signal, not a verdict.
- `score_ai_fingerprint(text)` — averages sentence-length uniformity (low variance = a common
  AI-text tell) and repeated-sentence-starter ratio.
- `run_precheck(text, source_excerpts, *, plagiarism_threshold=0.6, ai_fingerprint_threshold=0.6)`
  → `PlagiarismCheckResult(plagiarism_score, ai_fingerprint_score, flagged, reasons)`. Scoring
  only — no auto-regeneration/blocking, matching the citations module's separation of concerns.

**Onboarding (TASK-E10-1):** New `AuthContext` (mirrors `DocumentContext`'s exact Context+hooks
shape per ADR-0008), persisting the JWT to `localStorage`. `Onboarding.tsx` is a two-step gate:
register-or-login, then select-or-upload a university formatting config (`institution_id` stored
on `DocumentContext`, alongside the existing `projectId`). `App.tsx` renders `<Onboarding />`
until both a token and an institution are present, `<Workspace />` after. `useNewProject`/the
diff-accept flow now thread the previously-chosen `institutionId` through so it survives a new
project or an accepted draft, rather than being wiped by a state refresh.

## Files Changed
- `apps/backend/src/diploma_backend/plagiarism/{__init__,precheck}.py` (new)
- `apps/backend/tests/test_plagiarism.py` (new, 8 cases)
- `apps/frontend/src/context/AuthContext.tsx` (new)
- `apps/frontend/src/services/{authService,institutionService}.ts` + `.test.ts` (new)
- `apps/frontend/src/types/{auth,institution}.ts` (new)
- `apps/frontend/src/components/Onboarding.tsx` + `.test.tsx` (new)
- `apps/frontend/src/context/DocumentContext.tsx` (`institutionId` added)
- `apps/frontend/src/utils/mapProject.ts`, `hooks/useNewProject.ts`, `App.tsx` (thread
  `institutionId` through state updates; gate rendering on auth+institution)
- `apps/frontend/src/strings/index.ts` (onboarding strings)

## Verification
- Backend: `cd apps/backend && uv run pytest -q` — 131 passed, 1 skipped. `uv run ruff check .` —
  clean.
- Frontend: `npx vitest run` — 51/51 passed (10 files). `npx eslint .` — 0 errors (6 pre-existing
  unrelated warnings). `npx tsc -b` — clean.
- `docker compose up -d --build` — both services rebuilt and healthy.
- CI checked on GitHub after push (see below).

## Residual Risks
- `run_precheck` is not yet wired into the generation endpoint — like the humanizer, it's a
  standalone module a later integration task must call.
- The AI-fingerprint heuristic needs ≥2 sentences to produce a nonzero signal; single-sentence
  chapters (unlikely in practice) would always score 0 on that sub-signal.
- Onboarding's step-1 form uses `type="button"` (not `type="submit"`) on both Register/Log-in
  actions to avoid native HTML5 validation conflicting with two custom submit handlers on one
  form — `required`/`minLength` attributes are present but not enforced client-side; the backend
  still validates (min 8-char password, 409 on duplicate email) so no invalid state reaches
  storage, but the UX lacks inline validation feedback before submission.
- TOC-upload UI was intentionally left out of onboarding (existing `POST /projects/{id}/toc/upload`
  remains a separate, not-yet-wired follow-on).

## Docs Updated
- `docs/project/tasks.md` — TASK-E07-2 and TASK-E10-1 marked `done`.
