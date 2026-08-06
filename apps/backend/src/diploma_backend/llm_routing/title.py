"""Project-title auto-generation from a user's first chat instruction (user request, Phase 5.9).

A brand-new project starts with the generic `_DEFAULT_PROJECT_TITLE` ("Untitled Thesis",
`projects.router`). Once the user gives their first real generation instruction, that instruction
already names their actual topic, so a short, distinguishing title can be derived from it via a
single fast-tier DeepSeek call — mirroring `summary.py`'s `summarize_chapter`: a thin,
single-purpose function that composes with `DeepSeekClient` without modifying it, propagating
`LLMRequestError` on failure rather than swallowing it (the caller in `projects.router` is the one
that decides to fail open, per the PRD's tier routing, ADR-0003, since it's the module aware of
this being a non-critical side effect of generation).
"""

from diploma_backend.llm_routing.client import DeepSeekClient, Message

_TITLE_SYSTEM_PROMPT = (
    "You generate a short, distinguishing thesis title from a student's writing instruction. "
    "Output only the title itself: a concise academic-style title of a few words, capturing the "
    "specific topic. Do not wrap it in quotes, do not add a trailing period, and do not add any "
    "other commentary."
)

_TITLE_MAX_TOKENS = 40
"""Completion-token cap keeping the title short; enforced the same way as `_SUMMARY_MAX_TOKENS`
(no local tokenizer, see `summary.py`'s module docstring) — a small cap plus an explicit
conciseness instruction in the prompt."""


async def generate_project_title(client: DeepSeekClient, instruction: str) -> str:
    """Derive a short project title from `instruction` via the DeepSeek "fast" tier.

    Inputs: `client` is a configured `DeepSeekClient`; `instruction` is the user's chat
    instruction (typically their first generation instruction for a project).
    Output: the generated title (`str`), stripped of surrounding whitespace and any wrapping
    quote characters the model added despite the prompt's instruction not to.
    Raises `LLMRequestError` (propagated from `DeepSeekClient.generate_fast`) on any call failure.
    """
    messages: list[Message] = [
        {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    title = await client.generate_fast(messages, max_tokens=_TITLE_MAX_TOKENS)
    return title.strip().strip("\"'")
