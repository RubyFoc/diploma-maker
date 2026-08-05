"""LLM routing pipeline stage: DeepSeek fast/heavy tier client (ADR-0003)."""

from diploma_backend.llm_routing.client import DeepSeekClient, LLMRequestError, Tier
from diploma_backend.llm_routing.summary import assemble_prompt, summarize_chapter

__all__ = ["DeepSeekClient", "LLMRequestError", "Tier", "assemble_prompt", "summarize_chapter"]
