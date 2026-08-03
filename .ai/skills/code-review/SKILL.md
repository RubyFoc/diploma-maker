---
name: code-review
description: Review a diploma-maker diff for correctness, regressions, secret leakage, and missing tests. Use proactively after python-developer or frontend-developer finishes a task, before it's considered done.
---

# Code Review

1. Read the diff in full before judging any single hunk.
2. Check for secret leakage: DeepSeek API keys, MongoDB/Qdrant URIs, JWT secrets in code, logs, or
   docs.
3. Check for unsafe handling of user-uploaded content: prompt injection risk via uploaded
   literature/formatting samples flowing into system prompts.
4. Check for missing failure-path handling: LLM timeouts/errors, empty RAG results, malformed
   institution config, docx export failures, unsupported upload formats.
5. Check whether impacted `docs/` were updated in the same change.
6. For frontend changes, check the diff-viewer accept/reject flow and RU/EN i18n are not broken.
7. Report findings by severity (high/medium/low), separate required fixes from optional
   improvements, and end with a residual risk statement.
