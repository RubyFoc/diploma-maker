"""Citation verification + retry/reject flow (TASK-E04-4, per ADR-0001).

ADR-0001's contract: a candidate citation must be verified verbatim against a
retrieved/uploaded source before it is inserted into the generated document. If the citation's
current excerpt doesn't verify, the system retries against alternative passages for the same
claim (via `QdrantSourceStore.search`, TASK-E04-1) rather than failing outright. If no
alternative verifies either, the citation is *rejected* — a normal, expected outcome, not an
error — so the caller can drop the claim or regenerate the passage without it; the rest of the
document generation is never blocked on one unverifiable quote. Accepted citations are then
re-formatted to the destination institution's citation style (`CitationStyle` from
`diploma_backend.formatting.models`, sourced from `InstitutionConfig.citation_style` via E05)
before insertion.

Out of scope here (explicitly deferred, not implemented):
- Semantic/LLM-based entailment checking. `verify_citation_against_excerpt` is a heuristic
  text-overlap check only — see its docstring for the DeepSeek-fast-tier (ADR-0003) extension
  point a future iteration could wire in.
- External academic search (`diploma_backend.sources.search.search_sources`) as a retry source.
  This module's retry path only queries the already-ingested Qdrant store
  (`QdrantSourceStore.search`); wiring external search in as a further fallback is a natural
  follow-up but is not part of this MVP task.
- E07's humanizer interaction and any FastAPI router — this is a pure service module other
  tasks build on.
"""

import re
from dataclasses import dataclass
from typing import Literal

from diploma_backend.formatting.models import CitationStyle
from diploma_backend.sources.client import QdrantSourceStore

CitationStatus = Literal["verified", "rejected"]

# Common English stopwords excluded from the key-term overlap check so verification isn't
# trivially satisfied by shared filler words ("the", "of", "and", ...) — only content-bearing
# terms count toward the overlap ratio.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "from",
        "by",
        "not",
        "no",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "than",
        "then",
        "so",
        "such",
        "which",
        "who",
        "whom",
        "whose",
        "what",
        "when",
        "where",
        "why",
        "how",
    ]
)

# Fraction of the claim's key terms that must appear in the excerpt for a match, when the claim
# is not found verbatim as a substring. Chosen to tolerate minor rewording/punctuation
# differences while still requiring most of the claim's substance to be present.
_OVERLAP_THRESHOLD = 0.8

_DEFAULT_MAX_RETRIES = 1


@dataclass(frozen=True)
class Citation:
    """A candidate citation to verify: a claim attributed to a source excerpt.

    `source_excerpt` is the passage the claim is currently attributed to (the candidate to
    verify first). `source_reference` is an opaque identifier for that source (e.g. a document
    id or external id) used later for formatting once the citation is accepted.
    """

    claim_text: str
    source_excerpt: str
    source_reference: str | None = None


@dataclass(frozen=True)
class CitationResolution:
    """Outcome of `verify_and_resolve_citation`.

    `status` is `"verified"` (the claim is backed by `excerpt`, which may be the original
    candidate or an alternative passage found during retry) or `"rejected"` (no verifiable
    excerpt was found — the caller should drop the claim/citation or regenerate the passage
    without it, per ADR-0001). `excerpt`/`source_reference` are `None` when rejected.
    """

    status: CitationStatus
    excerpt: str | None
    source_reference: str | None


def _normalize(text: str) -> str:
    """Lowercase and collapse `text` to alphanumeric words separated by single spaces."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _key_terms(normalized_claim: str) -> list[str]:
    return [w for w in normalized_claim.split() if w not in _STOPWORDS and len(w) > 2]


def verify_citation_against_excerpt(claim_text: str, source_excerpt: str) -> bool:
    """Check whether `claim_text` is verbatim-supported by `source_excerpt`.

    This is a heuristic placeholder for ADR-0001's "verified verbatim" requirement, *not*
    semantic entailment: it normalizes both strings (lowercase, alphanumeric words only) and
    passes if either (a) the whole normalized claim appears as a substring of the normalized
    excerpt, or (b) at least `_OVERLAP_THRESHOLD` of the claim's non-stopword key terms appear
    in the excerpt (tolerating minor rewording/punctuation differences). It does not understand
    meaning, paraphrase, or negation.

    Future iteration (explicitly out of scope for this MVP task): route this through the
    DeepSeek fast tier (`deepseek-v4-flash`, ADR-0003 names "citation verification" as one of
    its fast-tier tasks) for real entailment checking instead of a text-overlap heuristic. That
    would replace this function's body but should keep the same `(claim_text, source_excerpt)
    -> bool` signature so callers (including `verify_and_resolve_citation` below) don't need to
    change.
    """
    normalized_claim = _normalize(claim_text)
    normalized_excerpt = _normalize(source_excerpt)
    if not normalized_claim:
        return False
    if normalized_claim in normalized_excerpt:
        return True

    key_terms = _key_terms(normalized_claim)
    if not key_terms:
        return False
    excerpt_words = set(normalized_excerpt.split())
    matched = sum(1 for term in key_terms if term in excerpt_words)
    return (matched / len(key_terms)) >= _OVERLAP_THRESHOLD


async def verify_and_resolve_citation(
    claim_text: str,
    candidate_excerpt: str,
    *,
    source_store: QdrantSourceStore,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    candidate_reference: str | None = None,
) -> CitationResolution:
    """Verify a citation, retrying against alternative sources on failure, per ADR-0001.

    Checks `candidate_excerpt` first. If it doesn't verify, queries `source_store.search
    (claim_text)` for alternative passages already ingested into Qdrant and checks up to
    `max_retries` of them (highest-similarity first) against the claim. Returns a `"verified"`
    resolution as soon as any excerpt (candidate or alternative) verifies; returns a
    `"rejected"` resolution if none do.

    Rejection is a normal, expected outcome per ADR-0001 (dropping the citation or
    regenerating the passage without it) and is never raised as an exception. The only
    exception that propagates from here is `SourceStoreError` (from `source_store.search`),
    representing genuine infrastructure failure (e.g. Qdrant unreachable) rather than a
    citation simply failing to verify.
    """
    if verify_citation_against_excerpt(claim_text, candidate_excerpt):
        return CitationResolution(
            status="verified", excerpt=candidate_excerpt, source_reference=candidate_reference
        )

    alternatives = source_store.search(claim_text, top_k=max_retries)
    for alternative in alternatives[:max_retries]:
        excerpt = alternative.get("text")
        if not excerpt:
            continue
        if verify_citation_against_excerpt(claim_text, excerpt):
            document_id = alternative.get("document_id")
            chunk_index = alternative.get("chunk_index")
            reference = f"{document_id}#chunk{chunk_index}" if document_id is not None else None
            return CitationResolution(
                status="verified", excerpt=excerpt, source_reference=reference
            )

    return CitationResolution(status="rejected", excerpt=None, source_reference=None)


@dataclass(frozen=True)
class CitationFields:
    """Optional structured fields for formatting, when available beyond a loose reference string.

    All fields are optional since, at this stage of the pipeline, callers typically only have a
    `source_reference` string (a document id or external id) rather than parsed
    author/year/title metadata.
    """

    author: str | None = None
    year: int | None = None
    reference_number: int | None = None


def format_citation(
    source_reference: str, style: CitationStyle, fields: CitationFields | None = None
) -> str:
    """Format an accepted citation for in-text insertion, per the destination institution's style.

    Only `"APA"` and `"GOST"` have real formatting rules here — the two styles
    `formatting.upload.guess_citation_style` actually detects. This is a simple formatting
    utility, not a full citation-style engine:
    - `"APA"`: author-year parenthetical, e.g. `(Author, 2020)`, using `fields.author`/
      `fields.year` if given; falls back to `(source_reference)` if those aren't available.
    - `"GOST"`: numbered bracketed reference, e.g. `[3]`, using `fields.reference_number` if
      given; falls back to `[source_reference]` if not available.
    - `"MLA"` / `"custom"`: no formatting rules implemented yet; returns `source_reference`
      as-is.
    """
    if style == "APA":
        if fields and fields.author and fields.year:
            return f"({fields.author}, {fields.year})"
        return f"({source_reference})"
    if style == "GOST":
        if fields and fields.reference_number is not None:
            return f"[{fields.reference_number}]"
        return f"[{source_reference}]"
    return source_reference
