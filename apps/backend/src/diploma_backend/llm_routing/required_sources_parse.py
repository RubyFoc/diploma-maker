"""Bulk-text required-sources parsing (user request).

Turns a block of pasted bibliography text (e.g. a full GOST-style reference list, many entries
long) into structured `(author, title)` pairs via a single fast-tier DeepSeek call, so a user
with many must-cite sources doesn't have to add each one through `sources.router`'s
one-at-a-time Author/Work-title form.

Deliberately stateless: this module only builds the prompt and parses the model's response, the
same "thin, single-purpose function that composes with `DeepSeekClient`" shape as
`llm_routing.title`. Persisting parsed entries as `RequiredSource` rows is the caller's job
(`sources.router`'s existing create endpoint), not this module's.
"""

import json

from diploma_backend.llm_routing.client import Message

_PARSE_SYSTEM_PROMPT = (
    "You extract a list of cited authors and their works from a block of pasted bibliography "
    "text (often GOST-style academic references, one entry per line or paragraph). For each "
    "distinct work, output one entry with the author's name and the work's title. Respond with "
    'ONLY a JSON array of objects shaped like [{"author": "...", "title": "..."}, ...] — omit '
    '"title" (or set it to null) if an entry only names an author with no clear specific work. '
    "No commentary, no markdown code fences, just the JSON array itself."
)

PARSE_MAX_TOKENS = 4000
"""Completion-token cap: generous enough for a few dozen parsed entries (a realistic bulk-paste
upper bound) without leaving a runaway response uncapped."""


class RequiredSourcesParseError(Exception):
    """Raised when the model's response isn't parseable as the expected JSON array shape."""


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
        entries.append(entry)
    return entries
