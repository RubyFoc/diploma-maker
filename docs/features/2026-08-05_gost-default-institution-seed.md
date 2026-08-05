# Default GOST 7.32-2017 Institution Seed

## Date
2026-08-05

## PRD Section
§3.4 (institution formatting configs), §6 (onboarding university selection)

## Summary
The user asked me to independently research real university formatting requirements ("на всякий
случай сам поищи"), as a sanity check on the platform's formatting-config schema and defaults.

**Research (web search, multiple independent sources: GOST 7.32-2017's own published text and
several university methodology guides):**
- Margins: left 30mm, right 15mm, top/bottom 20mm.
- Font: Times New Roman, 14pt.
- Line spacing: 1.5.
- Citation style: numbered bracketed references (e.g. `[3]`) — matches this codebase's existing
  `"GOST"` `CitationStyle` value and `formatting.upload.guess_citation_style`'s heuristic.

These values also happen to already match the sample fixture (`_build_config` in
`test_formatting.py`, written back in TASK-E05-1) that an earlier agent used as a plausible
example "Belarusian State University" config — independent confirmation the codebase's existing
assumptions were realistic, not just internally consistent.

**Real gap found while verifying this:** ADR-0005 defines `source: Literal["upload", "seed"]`,
but no code anywhere ever produced a `"seed"` config — the only way to get an `InstitutionConfig`
into the database was uploading a `.docx` sample first (TASK-E05-2). That means a fresh
deployment's university-selection dropdown (`GET /formatting/institution-configs`, TASK-E05-3,
used by `Onboarding.tsx`) was empty on first run, forcing every new user to upload their own
sample before they could even select a formatting profile — even though this platform's stated
target audience (per ADR-0001's GOST handling and `sources.geo_filter`'s RU/BY focus) has a
well-known published standard that doesn't require an upload at all.

**Fix (TASK-INT-6):** New `formatting/seed.py` — `build_default_gost_config()` builds an
`InstitutionConfig` with the researched GOST 7.32-2017 values (`institution_id: "seed-gost-7-32-2017"`,
`source: "seed"`, `accuracy_weight: 1.0` — a published standard starts as a trusted baseline,
distinct from an unvalidated upload's `0.0`). `ensure_default_gost_config(db)` inserts it only if
missing (idempotent — a restart never resets an `accuracy_weight` that TASK-E09-2's future
adjustment logic, or a manual edit, has since changed). Wired into `main.py` via a FastAPI
`lifespan` context manager, so it runs once per real app startup.

## Files Changed
- `apps/backend/src/diploma_backend/formatting/seed.py` (new)
- `apps/backend/tests/test_formatting_seed.py` (new, 4 cases)
- `apps/backend/src/diploma_backend/main.py` (`lifespan` added, calls `ensure_default_gost_config`)

## Verification
- `cd apps/backend && uv run pytest -q` — 153 passed, 1 skipped. `uv run ruff check .` — clean.
- Confirmed the seed does NOT fire during the test suite (`TestClient(app)` is used without
  entering it as a context manager in `conftest.py`'s `client` fixture, so lifespan startup never
  runs — no test accidentally reaches a real MongoDB).
- **Manual verification against the live stack**: rebuilt the container, confirmed
  `GET /formatting/institution-configs` returns the seeded GOST config with exactly the
  researched values (margins, font, line spacing, citation style) on a real startup.

## Residual Risks
- This is one national standard (GOST 7.32-2017), not every possible institution's house style —
  it's a sensible default/starting point, not a substitute for uploading an actual institution
  sample when one differs from the bare standard.
- `accuracy_weight: 1.0` as a "trusted baseline" is a judgment call with no real usage data behind
  it yet (same caveat as every other threshold/weight decision in this codebase pre-launch) —
  revisit once TASK-E09-2's adjustment logic and real feedback signals exist.

## Docs Updated
- `docs/project/tasks.md` — new "Phase 5.5" section, TASK-INT-6 `done`.
