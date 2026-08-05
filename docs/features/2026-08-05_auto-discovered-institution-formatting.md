# University Formatting Auto-Discovery

## Date
2026-08-05

## PRD Section
§3.4 (institution formatting configs), §6 (onboarding), ADR-0005 addendum

## Summary
The user asked that, when a university name is entered, the system should also TRY to
automatically find that university's formatting requirements itself, rather than always
requiring a manual `.docx` upload. Scoped via two clarifying questions up front: (1) search
method — free, keyless DuckDuckGo HTML search (no API key/cost) over a paid search API; (2)
fallback when nothing confident is found — an honest "couldn't find it" message pointing at the
existing upload/select options, never a silent wrong guess. PDF results (common for these
methodological guides) are explicitly skipped in this pass rather than adding a new PDF-parsing
dependency, per the user's own "check what's already sufficient first" guidance.

**ADR-0005 addendum:** `source` gains a third value, `"auto"`, alongside `"upload"`/`"seed"`.
Auto-detected configs get `accuracy_weight=0.3` — less trusted than a seeded standard (`1.0`) or
presumably a verified upload, since it's unverified web-extracted text.

**Backend (TASK-INT-7):** New `formatting/discovery.py` — `search_formatting_pages` queries
`https://html.duckduckgo.com/html/` (no API key), decodes DDG's `uddg`-wrapped result links;
`fetch_page_text` fetches each candidate, skips non-`text/html` content-types (PDFs) entirely,
and — critically — decodes HTML entities (`html.unescape`) before stripping tags, since real
pages very commonly write margin dashes as `&ndash;` rather than a literal "–"; `extract_margins_mm`/
`extract_font` run pragmatic regexes over the result. `discover_institution_config` tries each
search result in order and stops at the first page yielding both margins and font. New
`POST /formatting/institution-configs/auto-detect` (on the existing `formatting` router) returns
201 on a confident hit, 404 (an expected outcome, not an error) when nothing was found, 502 on a
genuine search-infra failure.

**Frontend (TASK-INT-8):** `Onboarding.tsx`'s institution-selection step gained a third sibling
block — a university-name input + "Try to auto-detect" button — above the existing
dropdown/upload options, which remain completely unchanged and always usable regardless of
whether auto-detect was tried or failed. A 404 is represented as `null` (not a thrown error) at
the service layer, since it's a normal, expected outcome distinct from a real failure (502/network
error), which still throws and shows a separate message.

## Manual Verification Against the Live Stack (real web search, not mocked)
This was validated with real network calls throughout, not just mocked tests, since the whole
point of this feature is behavior against real, messy, unpredictable real-world pages:
1. Confirmed DuckDuckGo's HTML endpoint is reachable and parseable from this environment via a
   direct `curl`.
2. Found a real page (`dissergrad.com`) with exactly the kind of text this feature targets:
   `"поля: левое – 30 мм, верхнее – 20 мм, ... шрифт: Times New Roman; кегель: - 14 пт"`.
3. **First integration attempt failed for real queries** (`МГУ`, `Финансовый университет`,
   `МПГУ` all returned 404) despite the underlying mechanism working in isolation. Debugged with
   a standalone script hitting the real pipeline function-by-function and found TWO real bugs:
   - **HTML entities weren't decoded.** `&ndash;` (the literal escaped entity) doesn't match the
     `[-–:]` separator regex, which expects a real dash character — tag-stripping alone never
     converts `&ndash;` into `–`. Fixed by calling `html.unescape()` before stripping tags.
   - **Adverb margin phrasing wasn't recognized.** Real guides commonly write "слева"/"справа"/
     "сверху"/"снизу" (adverbs: "from the left/right/top/bottom") rather than "левое"/"правое"/
     "верхнее"/"нижнее" (adjectives). "лев"/"прав" happen to be literal substrings of "слева"/
     "справа" so those matched by accident, but "верхн"/"нижн" are NOT substrings of "сверху"/
     "снизу" (different root entirely — "верх"/"низ" vs "верхн"/"нижн") — top/bottom silently
     never matched. Fixed by adding the adverb form as an explicit alternative for top/bottom.
   - **A further real-world quirk found in the same page**: top and bottom margins are often
     stated together with ONE shared value ("сверху и снизу – 20 мм") rather than repeated per
     side. Added `_SHARED_TOP_BOTTOM_RE` as a fallback for whichever side isn't found
     individually.
4. After both fixes, re-ran the exact same live query (`POST .../auto-detect {"institution_name":
   "МГУ"}`) against the rebuilt container and got a real **201** with margins
   `{top:20, bottom:20, left:30, right:10}` and font `Times New Roman, 12pt` extracted from
   `dissergrad.com` — a genuine, confirmed live end-to-end success, not a mocked one.

## Files Changed
- `docs/architecture/decisions.md` (ADR-0005 addendum: `source: "auto"`)
- `apps/backend/src/diploma_backend/formatting/models.py` (`Source` literal extended)
- `apps/backend/src/diploma_backend/formatting/discovery.py` (new)
- `apps/backend/src/diploma_backend/formatting/router.py` (`POST .../auto-detect` added)
- `apps/backend/tests/test_formatting_discovery.py` (new, 23 cases incl. 2 regression tests for
  the entity-decoding and adverb/shared-value bugs found during manual verification)
- `apps/frontend/src/services/institutionService.ts` + `.test.ts` (`autoDetectInstitution` added)
- `apps/frontend/src/components/Onboarding.tsx` + `.test.tsx` (third option wired in)
- `apps/frontend/src/strings/index.ts` (auto-detect strings)

## Verification
- Backend: `cd apps/backend && uv run pytest -q` — 176 passed, 1 skipped. `uv run ruff check .` —
  clean.
- Frontend: `npx vitest run` — 69/69 passed (13 files, one isolated CPU-contention flake on a
  concurrent full-suite run, confirmed stable across 3 repeated full runs afterward). `npx eslint
  .` — 0 errors. `npx tsc -b` — clean.
- `docker compose up -d --build` — both services rebuilt and healthy.
- **Real end-to-end live verification** (not mocked): see the debugging narrative above — this
  feature was actually exercised against the live internet and a real bug-fix loop, not just
  unit-tested against fixtures.
- CI checked on GitHub after push.

## Residual Risks
- Coverage is inherently best-effort: PDF-only guides (roughly half of real search results in
  informal testing) are skipped entirely — a real limitation, not a bug, and clearly surfaced to
  the user as "couldn't find it, try uploading instead" rather than a silent wrong guess.
- The regex heuristics now handle several real phrasings found during manual testing, but Russian
  academic-guide prose has more variation than any fixed regex set can fully cover — expect
  further false-negatives ("not found" when a page actually did have the data) on unseen
  phrasings; false-positives (wrong data extracted) are less likely given the fail-closed,
  all-four-margins-required design, but not impossible.
- `citation_style` and page size/orientation are never auto-detected — always defaulted to
  `"GOST"`/A4/portrait for this MVP, regardless of what the source page might say.

## Docs Updated
- `docs/project/tasks.md` — new "Phase 5.6" section, TASK-INT-7/TASK-INT-8 both `done`.
