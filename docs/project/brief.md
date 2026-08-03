# Product Brief

## Problem
Students and researchers spend disproportionate effort on the mechanical parts of academic
writing: sourcing recent literature, formatting to a specific university's rules, verifying
citations, and passing plagiarism/AI-detection checks — on top of the actual writing.

## Solution
A web SaaS where users draft papers through an interactive chat + Git-like diff workspace. The
system searches/ingests literature, drafts text via DeepSeek LLM routing, verifies every citation
against a retrieved or uploaded source (zero-hallucination), "humanizes" the academic tone to
defeat AI detectors, and exports a fully formatted `.docx` against a university-specific or
user-supplied style config.

## Target Users
- Students and researchers writing theses, dissertations, or term papers.

## Success Metrics (see `Academic_Platform_PRD.md` §2)
- ≥80% originality on standard institutional plagiarism checkers.
- ≤5% AI-detection probability.
- Aggressive token-cost efficiency via model routing and context caching.

## Source of Truth
Full requirements live in `Academic_Platform_PRD.md` at the repo root. This brief is a summary —
do not duplicate detail here; update the PRD and link to it instead.
