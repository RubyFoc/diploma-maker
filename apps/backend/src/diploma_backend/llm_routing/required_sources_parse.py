"""Bulk-text required-sources parsing (user request).

Turns a block of pasted bibliography text (e.g. a full GOST-style reference list, many entries
long) into structured `(author, title, url)` triples via one or more fast-tier DeepSeek calls, so
a user with many must-cite sources doesn't have to add each one through `sources.router`'s
one-at-a-time Author/Work-title form.

Deliberately stateless: this module only builds the prompt, batches the input, and parses the
model's response, the same "thin, single-purpose function that composes with `DeepSeekClient`"
shape as `llm_routing.title`. Persisting parsed entries as `RequiredSource` rows is the caller's
job (`sources.router`'s existing create endpoint), not this module's.

Batching (`split_into_batches`, user report — a real ~20-entry GOST-style reference list came
back as `502 Model response was not valid JSON` every time): `deepseek-v4-flash` is a reasoning
model that spends part of its completion-token budget on an internal chain-of-thought before
emitting the actual answer. Measured directly against DeepSeek's API: a 20-entry bulk paste
consumed the *entire* budget on reasoning and produced zero answer content even at
`max_tokens=16000`, while the same prompt shape with 8 entries succeeded comfortably within 8000.
Reasoning-token cost does not scale linearly with entry count for this model on this task — no
single fixed `max_tokens` ceiling reliably covers "one call for the whole paste," so the input is
instead split into fixed-size batches of entries, each parsed with its own call.
"""

import json
import re

from diploma_backend.llm_routing.client import Message

_PARSE_SYSTEM_PROMPT = (
    "You extract a list of cited authors and their works from a block of pasted bibliography "
    "text (often GOST-style academic references, one entry per line or paragraph). For each "
    "distinct work, output one entry with the author's name, the work's title, and its URL if "
    "the entry includes one (GOST-style references often have a 'URL: https://...' segment). "
    'Respond with ONLY a JSON array of objects shaped like [{"author": "...", "title": "...", '
    '"url": "..."}, ...] — omit "title"/"url" (or set them to null) when absent. Copy the URL '
    "character-for-character exactly as it appears in the input, never invent or modify one. "
    "No commentary, no markdown code fences, just the JSON array itself."
)

PARSE_MAX_TOKENS = 8000
"""Completion-token cap per batch (see module docstring) — empirically covers `_PARSE_BATCH_SIZE`
entries' worth of reasoning + answer with headroom (8 entries measured at ~4300 completion
tokens), without leaving a runaway response uncapped."""

_PARSE_BATCH_SIZE = 8
"""Entries per model call (see module docstring's reasoning-token measurements). A smaller value
would mean more, slower round trips for a large paste; a larger one risks the exact
all-budget-spent-on-reasoning failure this batching exists to avoid — 8 is the largest size
measured to reliably finish within `PARSE_MAX_TOKENS`."""


class RequiredSourcesParseError(Exception):
    """Raised when the model's response isn't parseable as the expected JSON array shape."""


def split_into_batches(text: str, batch_size: int = _PARSE_BATCH_SIZE) -> list[str]:
    """Splits `text` into blank-line-separated bibliography entries, then regroups them into
    chunks of at most `batch_size` entries each (rejoined with blank lines) for
    `sources.router.parse_required_sources_bulk_endpoint` to parse with one model call per chunk
    (see module docstring).

    Falls back to a single batch containing the whole input if it has no blank-line separators
    at all (e.g. a short, single-entry paste) — nothing to split, and guessing at some other
    boundary (a lone newline) would risk cutting a wrapped multi-line entry in half.
    """
    entries = [entry.strip() for entry in re.split(r"\n\s*\n", text) if entry.strip()]
    if len(entries) <= 1:
        return [text] if text.strip() else []
    return ["\n\n".join(entries[i : i + batch_size]) for i in range(0, len(entries), batch_size)]


def build_parse_messages(text: str) -> list[Message]:
    """Build the chat messages for parsing `text` into required-source candidates."""
    return [
        {"role": "system", "content": _PARSE_SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]


def parse_response(content: str) -> list[dict[str, str]]:
    """Parse a model's raw completion `content` into a list of `{"author": ..., "title"?: ...}`.

    Strips a wrapping markdown code fence if the model added one despite the prompt's
    instruction not to (the same defensive shape `llm_routing.title.generate_project_title` uses
    for stray quote characters). Raises `RequiredSourcesParseError` if the content isn't a JSON
    array, so the caller can surface a clear failure rather than silently returning nothing.
    Entries missing a non-empty `author` are dropped rather than raising, since one malformed
    entry in a long pasted list shouldn't discard every other correctly-parsed one.

    `url` is returned as-is, verbatim from the model — the caller (`sources.router
    .parse_required_sources_bulk_endpoint`) is responsible for cross-checking it against the
    original pasted text before trusting it, since a model can still transcribe a long URL
    incorrectly despite being told to copy it exactly.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            first_line, rest = text.split("\n", 1)
            text = rest if first_line.strip().lower() in ("json", "") else text

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RequiredSourcesParseError("Model response was not valid JSON") from exc
    if not isinstance(parsed, list):
        raise RequiredSourcesParseError("Model response was not a JSON array")

    entries: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        if not isinstance(author, str) or not author.strip():
            continue
        entry = {"author": author.strip()}
        title = item.get("title")
        if isinstance(title, str) and title.strip():
            entry["title"] = title.strip()
        url = item.get("url")
        if isinstance(url, str) and url.strip():
            entry["url"] = url.strip()
        entries.append(entry)
    return entries
