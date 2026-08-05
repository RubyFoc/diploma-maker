"""Chapter-summary compaction + cache-friendly prompt assembly (ADR-0003, TASK-E03-2).

Builds on `DeepSeekClient` (TASK-E03-1) without modifying it. Two independent pieces:

1. `summarize_chapter`: compacts a chapter's full content into a short (~150-300 token) summary
   via a single "fast"-tier DeepSeek call, per ADR-0003's routing policy (summarization is not
   complex reasoning, so it does not need the "heavy" tier). There is no local tokenizer in this
   project (see ADR-0002's rejection of a heavy embedding stack for the same reasoning), so
   "~150-300 tokens" is approximated via `max_tokens` on the DeepSeek call plus an explicit
   conciseness instruction in the prompt — `max_tokens` caps completion tokens as billed by
   DeepSeek directly, which is a closer proxy than any local word/char heuristic.

2. `assemble_prompt`: orders a generation call's message list so that DeepSeek's prompt cache
   stays warm across turns in the same session. DeepSeek (like other OpenAI-compatible caching
   backends) caches a *prefix* of the message list: as long as the leading messages are
   byte-identical to a previous call, that prefix is served from cache at roughly 1/50th the
   cost of a cache miss. Anything appended after the first point of divergence is billed at the
   full cache-miss rate, and any *reordering* of earlier messages (not just editing them)
   counts as divergence too.

   Consequently:
   - Stable content (system prompt, accumulated chapter summaries) must always come first, in a
     fixed order, and must not be reshuffled between calls within a session.
   - Volatile content (this turn's freshly retrieved RAG excerpts, the user's message) must come
     last, so it never pushes stable content out of the cached prefix.

   Persistence of summaries (attaching them to a chapter/version record) is out of scope here —
   that lives with TASK-E08-1. This module is pure/stateless: callers pass in whatever summaries
   they already have and get back a message list.
"""

from diploma_backend.llm_routing.client import DeepSeekClient, Message

_SUMMARY_SYSTEM_PROMPT = (
    "You compact academic chapter text into a short, dense summary for later reuse as context. "
    "Preserve only the key claims, findings, and structure needed to keep writing consistent "
    "with this chapter. Be extremely concise: target roughly 150-300 tokens of output. Do not "
    "pad with filler, restate the instructions, or add headings."
)

_SUMMARY_MAX_TOKENS = 400
"""Completion-token cap approximating the ~150-300 token target (see module docstring)."""


async def summarize_chapter(client: DeepSeekClient, chapter_content: str) -> str:
    """Compact a chapter's full content into a short summary via the DeepSeek "fast" tier.

    Inputs: `client` is a configured `DeepSeekClient`; `chapter_content` is the chapter's full
    text to compact.
    Output: the summary text (`str`), targeting ~150-300 tokens per ADR-0003, enforced via
    `max_tokens` on the underlying call (see `_SUMMARY_MAX_TOKENS`) rather than a local tokenizer.
    Raises `LLMRequestError` (propagated from `DeepSeekClient.generate_fast`) on any call failure.
    """
    messages: list[Message] = [
        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": chapter_content},
    ]
    return await client.generate_fast(messages, max_tokens=_SUMMARY_MAX_TOKENS)


def assemble_prompt(
    system_prompt: str,
    chapter_summaries: list[str],
    rag_excerpts: list[str],
    user_message: str,
) -> list[Message]:
    """Assemble a cache-friendly message list for a DeepSeek generation call.

    Ordering contract (see module docstring for why this matters for DeepSeek's prompt-cache
    economics — do not reorder these blocks between calls in the same session):
    1. `system_prompt` as a single `system` message — always first.
    2. `chapter_summaries` joined into one contiguous `system` message directly after it (a
       second `system`-role message, not a separate role) — kept as one block so the entire
       stable prefix is contiguous. Omitted if `chapter_summaries` is empty.
    3. A single trailing `user` message containing `rag_excerpts` (this turn's freshly retrieved,
       session-specific excerpts) followed by `user_message` (the actual user turn). This is the
       only volatile part of the list and must stay last.

    Inputs: `system_prompt` (stable instructions), `chapter_summaries` (stable, ordered list of
    per-chapter compacted summaries — e.g. from `summarize_chapter`, accumulated across the
    session), `rag_excerpts` (volatile, similarity-matched excerpts for this turn only — supplied
    by E04/Qdrant retrieval, out of scope here), `user_message` (the current user turn).
    Output: an OpenAI-compatible `list[Message]` ready to pass to `DeepSeekClient.generate`.
    """
    messages: list[Message] = [{"role": "system", "content": system_prompt}]

    if chapter_summaries:
        summaries_block = "\n\n".join(chapter_summaries)
        messages.append(
            {"role": "system", "content": f"Chapter summaries so far:\n\n{summaries_block}"}
        )

    if rag_excerpts:
        excerpts_block = "\n\n".join(rag_excerpts)
        user_content = f"Relevant excerpts:\n\n{excerpts_block}\n\n{user_message}"
    else:
        user_content = user_message

    messages.append({"role": "user", "content": user_content})
    return messages
