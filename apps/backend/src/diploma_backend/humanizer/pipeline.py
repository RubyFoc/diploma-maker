"""Humanizer pipeline: pattern-breaking post-processing (TASK-E07-1, PRD §3.3, ADR-0003).

Per the PRD's pipeline order, this stage runs after a chapter is drafted and its citations are
verified (ADR-0001, `citations.verification`) and before the anti-plagiarism/AI-detection
pre-check (TASK-E07-2, not implemented here). It rewrites text to break up repetitive
LLM-sounding stylistic patterns (sentence structure, phrasing) while preserving meaning and
facts. Per ADR-0003, humanization is a fast-tier DeepSeek task, so this module calls
`llm_routing.retry.generate_with_retry(client, "fast", messages)`.

Citation-preservation constraint (the load-bearing safety property of this module): ADR-0001's
whole citation-verification pipeline exists to guarantee a citation is verbatim-supported by a
source. If this humanizer let the LLM freely rewrite citation markers, it could silently mangle
an already-verified citation's exact wording/formatting, undoing that guarantee. To prevent
this, `guard_citations` replaces every recognized citation marker (as produced by
`citations.verification.format_citation`: `(Author, Year)`-shaped APA markers or `[N]`-shaped
GOST markers) with a stable placeholder token before the text ever reaches the LLM, and
`restore_citations` substitutes the placeholders back afterward — the LLM never sees or touches
the actual citation text. `restore_citations` also validates that every placeholder token it
expects is present, unchanged, in the LLM's response; if the model dropped or mangled one
despite the system prompt's instructions, this is a distinct failure mode (the LLM call itself
succeeded, but its output violates the citation-preservation contract) and raises
`HumanizationError` rather than silently returning corrupted text.

Out of scope here (later/separate tasks): TASK-E07-2's anti-plagiarism/AI-detection check, any
FastAPI router, and wiring this into the generation endpoint
(`diploma_backend.projects.router`) — this is a pure, self-contained service module other tasks
compose on top of.
"""

import re
from dataclasses import dataclass

from diploma_backend.llm_routing.client import DeepSeekClient, Message
from diploma_backend.llm_routing.retry import generate_with_retry

# Mirrors the two shapes `citations.verification.format_citation` actually produces: an
# APA-style author-year parenthetical (e.g. "(Author, 2020)") or a GOST-style numbered bracket
# (e.g. "[3]"). Deliberately pragmatic, not a full citation parser — same spirit as
# `formatting/upload.py`'s citation-style guesser regexes.
_APA_CITATION_RE = re.compile(r"\([A-Za-zА-Яа-яЁё .,'-]+,\s*\d{4}\)")
_GOST_CITATION_RE = re.compile(r"\[\d+\]")
_CITATION_RE = re.compile(f"{_APA_CITATION_RE.pattern}|{_GOST_CITATION_RE.pattern}")

_PLACEHOLDER_TEMPLATE = "__CITATION_{index}__"
_PLACEHOLDER_RE = re.compile(r"__CITATION_\d+__")

_SYSTEM_PROMPT = (
    "You are an academic writing editor. Rewrite the user's text to vary sentence structure "
    "and reduce repetitive, formulaic AI-sounding patterns, while preserving all meaning and "
    "facts exactly. Prefer plain, direct, moderately simple language over dense, inflated, or "
    "bureaucratic-sounding phrasing — write sentences a student would actually write, not ones "
    "stuffed with unnecessary qualifiers or padding. "
    "Specifically remove or rephrase stock AI-generated-text tells wherever they appear, in "
    "both Russian and English, including but not limited to: \"не только ... но и\", "
    "\"таким образом\", \"важно отметить\", \"стоит подчеркнуть\", \"следует отметить\", "
    "\"в заключение\", \"не будет преувеличением сказать\", \"not only ... but also\", "
    "\"moreover\", \"furthermore\", \"it is important to note\", \"in conclusion\", and "
    "\"delve into\". If the input already contains one of these, replace it with a plainer, "
    "more direct construction instead of leaving it as-is. "
    "The text contains placeholder tokens of the exact form __CITATION_<N>__. "
    "You must preserve every such token character-for-character: never alter, remove, "
    "translate, reformat, reorder relative to its sentence's meaning, or merge/split them. "
    "Copy each token exactly as it appears in the input. Return only the rewritten text, with "
    "no additional commentary."
)


class HumanizationError(Exception):
    """Raised when the LLM's humanized output violates the citation-preservation contract.

    This is a distinct failure category from `LLMRequestError`: the DeepSeek call itself
    succeeded, but the response dropped or mangled one or more `__CITATION_N__` placeholder
    tokens that `guard_citations` inserted, despite the system prompt's explicit instruction to
    preserve them verbatim. Restoring citations onto such a response would risk silently losing
    or corrupting an already-verified citation (ADR-0001), so this is raised instead.
    """


@dataclass(frozen=True)
class GuardedText:
    """Result of `guard_citations`: text with citation markers replaced by placeholder tokens.

    `text` is safe to send to an LLM. `citations` maps each placeholder's index to the exact
    original citation marker text it replaced, in the order needed by `restore_citations`.
    """

    text: str
    citations: list[str]


def normalize_dashes(text: str) -> str:
    """Replace every em-dash ("—") in `text` with an en-dash ("–").

    Em-dash overuse is a commonly-cited surface tell of AI-generated prose; this is a cheap,
    deterministic pass applied after humanization to reduce that tell without another LLM call.
    """
    return text.replace("—", "–")


def guard_citations(text: str) -> GuardedText:
    """Replace recognized citation markers in `text` with stable `__CITATION_N__` placeholders.

    Recognizes APA-style `(Author, Year)` and GOST-style `[N]` markers (the two shapes
    `citations.verification.format_citation` produces). Markers are replaced left-to-right with
    `__CITATION_0__`, `__CITATION_1__`, ... in order of appearance; the original marker text for
    each index is kept in the returned `GuardedText.citations` so `restore_citations` can put it
    back later.
    """
    citations: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        index = len(citations)
        citations.append(match.group(0))
        return _PLACEHOLDER_TEMPLATE.format(index=index)

    guarded = _CITATION_RE.sub(_replace, text)
    return GuardedText(text=guarded, citations=citations)


def restore_citations(text: str, citations: list[str]) -> str:
    """Substitute `__CITATION_N__` placeholders in `text` back with their original marker text.

    This is the enforcement point for this module's citation-preservation contract: every
    placeholder index in `citations` must appear in `text` exactly once, unchanged, or a
    citation marker inserted by `guard_citations` would be lost. Raises `HumanizationError`
    listing the missing indices if any placeholder is absent from `text` (e.g. the LLM dropped
    or mangled it) rather than silently returning text with a hole where a verified citation
    should be.
    """
    present_indices = {int(m.group(0)[len("__CITATION_") : -2]) for m in _PLACEHOLDER_RE.finditer(text)}
    expected_indices = set(range(len(citations)))
    missing = sorted(expected_indices - present_indices)
    if missing:
        missing_tokens = ", ".join(_PLACEHOLDER_TEMPLATE.format(index=i) for i in missing)
        raise HumanizationError(
            f"Humanized output is missing citation placeholder(s): {missing_tokens}. "
            "Refusing to restore citations onto output that may have mangled a verified "
            "citation marker."
        )

    def _replace(match: re.Match[str]) -> str:
        index = int(match.group(0)[len("__CITATION_") : -2])
        return citations[index]

    return _PLACEHOLDER_RE.sub(_replace, text)


async def humanize_text(client: DeepSeekClient, text: str, *, max_attempts: int = 3) -> str:
    """Rewrite `text` to break up repetitive LLM stylistic patterns, preserving citations.

    Steps: (1) `guard_citations` replaces recognized citation markers with placeholder tokens;
    (2) a fast-tier prompt (ADR-0003) instructs the model to vary sentence structure and reduce
    repetitive AI-sounding patterns while preserving meaning, facts, and the placeholder tokens
    verbatim; (3) `generate_with_retry(client, "fast", messages, max_attempts=max_attempts)`
    makes the call; (4) `restore_citations` substitutes the placeholders back with their
    original citation text, validating every one survived; (5) `normalize_dashes` replaces any
    em-dash left in the response with an en-dash.

    Raises `LLMRequestError` if `generate_with_retry` exhausts all attempts (propagated
    unchanged). Raises `HumanizationError` if the LLM's response is missing a placeholder token
    — see `restore_citations` for why this is a distinct, non-retryable failure category rather
    than being folded into `LLMRequestError`.
    """
    guarded = guard_citations(text)

    messages: list[Message] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": guarded.text},
    ]

    response = await generate_with_retry(client, "fast", messages, max_attempts=max_attempts)

    return normalize_dashes(restore_citations(response, guarded.citations))
