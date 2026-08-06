"""Anti-plagiarism / AI-detection pre-check (TASK-E07-2, PRD §3.3 / §6, Epic E07).

Per the PRD's pipeline order (generate -> verify citations -> humanize -> scan), this is the
final gate before a drafted chapter is considered ready to show the user: after citations are
verified against source excerpts (ADR-0001, `citations.verification`) and the text is run
through the humanizer (TASK-E07-1, `humanizer.pipeline`), it is scored here for (a) how much of
it is lifted near-verbatim from the sources it was generated against, and (b) how strongly it
reads as flatly AI-generated prose. Both scores are heuristic signals, not verdicts — `flagged`
on `run_precheck`'s result means "a human (or a future automated regeneration step) should take
a second look," never "this text is definitively plagiarized/AI-written."

Out of scope here (explicitly deferred, not implemented), matching `citations.verification`'s
scope boundary:
- Any real third-party plagiarism or AI-detection vendor integration (no PRD-specified vendor,
  no API key configured for this MVP). `score_plagiarism_risk` and `score_ai_fingerprint` are
  local text heuristics only — see each function's docstring for its named future extension
  point.
- Any auto-regeneration, blocking, or retry logic in response to `flagged=True`. This module
  only scores and flags; deciding what a caller does about a flagged result (surface a warning,
  trigger humanizer/generation retry, etc.) is deliberately left to the caller, mirroring how
  `citations.verification` separates "verify" from "what happens on rejection."
- Any FastAPI router or wiring into the generation endpoint (`diploma_backend.projects.router`)
  — this is a pure, self-contained service module other tasks compose on top of.
"""

import re
import statistics
from dataclasses import dataclass, field

# Shingle size for the n-gram overlap heuristic in `score_plagiarism_risk`. Five words is a
# common choice for plagiarism-style shingling: short enough to catch lifted phrases/sentences,
# long enough that overlap isn't dominated by common short word sequences.
_SHINGLE_SIZE = 5

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+(?:\s+|$)")
_WORD_RE = re.compile(r"[a-z0-9']+")


def _normalize_words(text: str) -> list[str]:
    """Lowercase `text` and split it into alphanumeric words (apostrophes kept)."""
    return _WORD_RE.findall(text.lower())


def _shingles(words: list[str], size: int = _SHINGLE_SIZE) -> set[str]:
    """Return the set of `size`-word shingles (contiguous word n-grams) from `words`.

    Returns an empty set if `words` has fewer than `size` words — there is no meaningful
    shingle overlap to compute for text shorter than one shingle.
    """
    if len(words) < size:
        return set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def _shingle_overlap_ratio(text: str, source_shingles: set[str]) -> float:
    """Fraction of `text`'s `_SHINGLE_SIZE`-word shingles that also appear in `source_shingles`.

    Shared core of the overlap-ratio computation used both whole-text (`score_plagiarism_risk`)
    and per-sentence (`flag_sentences`), so both scopes agree on exactly what "overlap" means.
    Returns 0.0 if either `text` or `source_shingles` yields no shingles (text shorter than one
    shingle, or no source material to compare against).
    """
    text_shingles = _shingles(_normalize_words(text))
    if not text_shingles or not source_shingles:
        return 0.0
    overlap = text_shingles & source_shingles
    return len(overlap) / len(text_shingles)


def score_plagiarism_risk(text: str, source_excerpts: list[str]) -> float:
    """Score how much of `text` overlaps near-verbatim with `source_excerpts` (0.0-1.0).

    Heuristic: builds `_SHINGLE_SIZE`-word shingles (contiguous word n-grams) of `text` and of
    the concatenation of `source_excerpts` (the RAG-retrieved/uploaded source passages this
    chapter's citations were verified against, per ADR-0001 — see `citations.verification`,
    which this module deliberately does not import from; it only needs the excerpt strings).
    The score is the fraction of `text`'s shingles that also appear among the sources' shingles
    (see `_shingle_overlap_ratio`).

    A high score is not automatically bad: some direct overlap is normal and healthy for a
    well-cited academic chapter (a verified quote is *supposed* to match its source verbatim).
    This score alone is a signal of how much of the chapter is directly-lifted phrasing, not a
    verdict — a caller should weigh it alongside how much of the chapter is quotation versus
    original analysis, which this function has no visibility into.

    Returns 0.0 if `text` (or the concatenated excerpts) is shorter than one shingle
    (`_SHINGLE_SIZE` words), since no overlap ratio can be computed in that case.

    Future extension point (out of scope for this MVP task): replace this local n-gram heuristic
    with a call to an external plagiarism-detection API (no vendor is specified in the PRD for
    this task), keeping the same `(text, source_excerpts) -> float` signature so callers
    (including `run_precheck` below) don't need to change.
    """
    source_shingles = _shingles(_normalize_words(" ".join(source_excerpts)))
    return _shingle_overlap_ratio(text, source_shingles)


def _sentences(text: str) -> list[str]:
    """Split `text` into non-empty sentences on `.`/`!`/`?` boundaries."""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _sentence_length_uniformity(sentences: list[str]) -> float:
    """Score (0.0-1.0) how uniform the sentences' word counts are; higher = more uniform.

    Uses the coefficient of variation (population stdev / mean word count) as the spread
    measure, since it is scale-independent (comparable across texts with different average
    sentence lengths). A coefficient of variation of 0 (every sentence the same length) maps to
    a uniformity score of 1.0; a coefficient of variation of 1.0 or higher (spread as large as
    the mean itself, i.e. clearly varied sentence lengths) maps to 0.0, linearly in between.
    Suspiciously uniform sentence lengths are a commonly-cited surface tell of flatly
    AI-generated prose.

    Returns 0.0 (no signal) if there are fewer than two sentences, since spread isn't meaningful
    for a single sentence.
    """
    if len(sentences) < 2:
        return 0.0
    lengths = [len(_normalize_words(s)) for s in sentences]
    mean_length = statistics.mean(lengths)
    if mean_length == 0:
        return 0.0
    coefficient_of_variation = statistics.pstdev(lengths) / mean_length
    return max(0.0, 1.0 - min(coefficient_of_variation, 1.0))


def _sentence_starters(sentences: list[str]) -> list[str | None]:
    """First normalized word of each sentence in `sentences`, `None` for a sentence with none.

    Preserves one entry per input sentence (unlike simply filtering), so callers can zip this
    positionally against `sentences` — needed by `flag_sentences` to attribute each starter back
    to its sentence.
    """
    return [words[0] if (words := _normalize_words(s)) else None for s in sentences]


def _repeated_starter_flags(sentences: list[str]) -> list[bool]:
    """Per-sentence flag: does this sentence's first word repeat as another sentence's first word?

    Shared starter-counting core of `_repeated_starter_ratio` (aggregate) and `flag_sentences`
    (per-sentence), so both agree on what "repeated starter" means. Returns one entry per
    sentence in `sentences`, positionally aligned (`False` for a sentence with no normalizable
    words, since it has no starter to compare).
    """
    starters = _sentence_starters(sentences)
    counts: dict[str, int] = {}
    for starter in starters:
        if starter is not None:
            counts[starter] = counts.get(starter, 0) + 1
    return [starter is not None and counts[starter] > 1 for starter in starters]


def _repeated_starter_ratio(sentences: list[str]) -> float:
    """Fraction of sentences whose first word is shared with at least one other sentence.

    Repeatedly opening sentences with the same word/transition ("Furthermore", "Additionally",
    ...) is a commonly-cited surface tell of flatly AI-generated prose. Returns 0.0 if there are
    fewer than two sentences.
    """
    if len(sentences) < 2:
        return 0.0
    starters = _sentence_starters(sentences)
    non_empty_count = sum(1 for starter in starters if starter is not None)
    if non_empty_count < 2:
        return 0.0
    flags = _repeated_starter_flags(sentences)
    return sum(flags) / non_empty_count


def score_ai_fingerprint(text: str) -> float:
    """Score how strongly `text` reads as flatly AI-generated prose (0.0-1.0).

    Heuristic proxy combining two surface signals, each documented in its own helper:
    - `_sentence_length_uniformity`: suspiciously uniform sentence lengths (low variance).
    - `_repeated_starter_ratio`: sentences repeatedly opening with the same starting word.

    The combined score is the simple average of the two sub-signals. There is no ground-truth
    AI-detection dataset available to calibrate against in this MVP, so this combination is
    chosen for being simple and clearly documented rather than tuned for precision; treat the
    result as a coarse signal, not a calibrated probability.

    Future extension point (out of scope for this MVP task): replace this surface-heuristic
    combination with a call to a dedicated AI-detection API/model (no vendor is specified in the
    PRD for this task), keeping the same `(text) -> float` signature so callers (including
    `run_precheck` below) don't need to change.
    """
    sentences = _sentences(text)
    uniformity = _sentence_length_uniformity(sentences)
    repeated_starters = _repeated_starter_ratio(sentences)
    return (uniformity + repeated_starters) / 2


@dataclass(frozen=True)
class SentenceFlag:
    """Per-sentence breakdown behind an overall `PlagiarismCheckResult`.

    Lets a caller (e.g. a frontend review UI) highlight exactly which sentences drove the
    aggregate scores, rather than only seeing a single chapter-wide number. `is_plagiarized` and
    `is_ai_like` are computed with the same thresholds/heuristics `run_precheck` uses for the
    aggregate result, pre-applied here so the frontend never needs to know the threshold values.
    """

    text: str
    plagiarism_score: float
    is_plagiarized: bool
    is_ai_like: bool


def flag_sentences(
    text: str,
    source_excerpts: list[str],
    *,
    plagiarism_threshold: float = 0.6,
) -> list[SentenceFlag]:
    """Break `text` into sentences and score/flag each one individually.

    `plagiarism_score` per sentence is that sentence's own shingle-overlap ratio against
    `source_excerpts`' shingles (`_shingle_overlap_ratio`, the same core `score_plagiarism_risk`
    uses for the whole chapter — computed per-sentence here for finer-grained review), and
    `is_plagiarized` is that score compared against `plagiarism_threshold`.

    `is_ai_like` flags a sentence whose first normalized word is a "repeated starter" — shared
    with at least one other sentence in `text` (`_repeated_starter_flags`, the same per-sentence
    signal `_repeated_starter_ratio` aggregates for the whole chapter's AI-fingerprint score).
    This is a narrower per-sentence signal than `score_ai_fingerprint`, which also folds in
    sentence-length uniformity — a whole-chapter-only signal with no single sentence to pin it
    on, so it's deliberately not reflected in `is_ai_like`.

    Returns one `SentenceFlag` per non-empty sentence `_sentences` finds; sentences with no
    normalizable words (rare edge case, e.g. a sentence of only punctuation) get
    `plagiarism_score=0.0` and `is_ai_like=False` since neither heuristic has anything to look at.
    """
    sentences = _sentences(text)
    source_shingles = _shingles(_normalize_words(" ".join(source_excerpts)))
    ai_like_flags = _repeated_starter_flags(sentences)

    flags: list[SentenceFlag] = []
    for sentence, is_ai_like in zip(sentences, ai_like_flags, strict=True):
        plagiarism_score = _shingle_overlap_ratio(sentence, source_shingles)
        flags.append(
            SentenceFlag(
                text=sentence,
                plagiarism_score=plagiarism_score,
                is_plagiarized=plagiarism_score > plagiarism_threshold,
                is_ai_like=is_ai_like,
            )
        )
    return flags


@dataclass(frozen=True)
class PlagiarismCheckResult:
    """Outcome of `run_precheck`: both heuristic scores plus a derived review flag.

    `flagged` is `True` if either score exceeds its configured threshold — a signal for a caller
    to review or regenerate the text, mirroring `citations.verification.CitationResolution`'s
    "outcome dataclass with a status-like flag" shape. This dataclass carries no opinion on what
    the caller should do about a flagged result; see this module's docstring for why that
    decision is deliberately left out of scope here. `reasons` holds one human-readable note per
    threshold that was exceeded (empty when `flagged` is `False`).
    """

    plagiarism_score: float
    ai_fingerprint_score: float
    flagged: bool
    reasons: list[str] = field(default_factory=list)
    originality_score: float = 0.0
    sentence_flags: list[SentenceFlag] = field(default_factory=list)


def run_precheck(
    text: str,
    source_excerpts: list[str],
    *,
    plagiarism_threshold: float = 0.6,
    ai_fingerprint_threshold: float = 0.6,
) -> PlagiarismCheckResult:
    """Run both heuristic pre-checks on `text` and flag it if either exceeds its threshold.

    Computes `score_plagiarism_risk(text, source_excerpts)` and `score_ai_fingerprint(text)`,
    then sets `flagged=True` if the plagiarism score exceeds `plagiarism_threshold` and/or the
    AI-fingerprint score exceeds `ai_fingerprint_threshold`, recording a human-readable reason
    per threshold exceeded (e.g. `"plagiarism_score 0.72 exceeds threshold 0.6"`). This function
    only scores and flags — it does not decide what happens next; see this module's docstring
    for why any auto-regeneration/blocking logic is deliberately out of scope here.

    Also populates `originality_score` (`1.0 - plagiarism_score`, a "how much of this reads as
    the author's own" framing of the same signal) and `sentence_flags`
    (`flag_sentences(text, source_excerpts, plagiarism_threshold=plagiarism_threshold)`) for
    callers that want a per-sentence breakdown alongside the aggregate scores. Both are purely
    additive: existing callers that only read `plagiarism_score`/`ai_fingerprint_score`/`flagged`/
    `reasons` are unaffected.
    """
    plagiarism_score = score_plagiarism_risk(text, source_excerpts)
    ai_fingerprint_score = score_ai_fingerprint(text)

    reasons: list[str] = []
    if plagiarism_score > plagiarism_threshold:
        reasons.append(
            f"plagiarism_score {plagiarism_score:.2f} exceeds threshold {plagiarism_threshold}"
        )
    if ai_fingerprint_score > ai_fingerprint_threshold:
        reasons.append(
            f"ai_fingerprint_score {ai_fingerprint_score:.2f} exceeds threshold "
            f"{ai_fingerprint_threshold}"
        )

    return PlagiarismCheckResult(
        plagiarism_score=plagiarism_score,
        ai_fingerprint_score=ai_fingerprint_score,
        flagged=bool(reasons),
        reasons=reasons,
        originality_score=1.0 - plagiarism_score,
        sentence_flags=flag_sentences(
            text, source_excerpts, plagiarism_threshold=plagiarism_threshold
        ),
    )
