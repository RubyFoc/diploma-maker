"""Tests for TASK-E04-4 (citation verification + retry/reject flow per ADR-0001)."""

from unittest.mock import MagicMock

import pytest

from diploma_backend.citations.verification import (
    CitationFields,
    format_citation,
    verify_and_resolve_citation,
    verify_citation_against_excerpt,
)
from diploma_backend.sources.client import SourceStoreError


def test_verify_citation_against_excerpt_matches_verbatim() -> None:
    claim = "Qdrant is used as the vector database for RAG storage."
    excerpt = "In this system, Qdrant is used as the vector database for RAG storage."

    assert verify_citation_against_excerpt(claim, excerpt) is True


def test_verify_citation_against_excerpt_matches_with_minor_rewording() -> None:
    claim = "Qdrant provides vector storage for retrieval augmented generation."
    excerpt = (
        "This project relies on Qdrant to provide vector storage for retrieval "
        "augmented generation workloads."
    )

    assert verify_citation_against_excerpt(claim, excerpt) is True


def test_verify_citation_against_excerpt_does_not_match_unrelated_text() -> None:
    claim = "Citation verification retries against alternative sources per ADR-0001."
    excerpt = "The weather today is sunny with a light breeze from the west."

    assert verify_citation_against_excerpt(claim, excerpt) is False


def test_verify_citation_against_excerpt_empty_claim_never_matches() -> None:
    assert verify_citation_against_excerpt("", "some excerpt text") is False


@pytest.mark.asyncio
async def test_verify_and_resolve_citation_verifies_candidate_directly() -> None:
    claim = "Qdrant is the vector database used for RAG storage."
    candidate = "Qdrant is the vector database used for RAG storage in this platform."
    source_store = MagicMock()

    resolution = await verify_and_resolve_citation(claim, candidate, source_store=source_store)

    assert resolution.status == "verified"
    assert resolution.excerpt == candidate
    source_store.search.assert_not_called()


@pytest.mark.asyncio
async def test_verify_and_resolve_citation_falls_back_to_alternative() -> None:
    claim = "Qdrant supports payload filtering for scoped RAG queries."
    bad_candidate = "This sentence has nothing to do with the claim at all."
    source_store = MagicMock()
    source_store.search.return_value = [
        {
            "text": "Qdrant supports payload filtering for scoped RAG queries per user.",
            "document_id": "doc-42",
            "chunk_index": 3,
            "score": 0.91,
        }
    ]

    resolution = await verify_and_resolve_citation(
        claim, bad_candidate, source_store=source_store, max_retries=1
    )

    assert resolution.status == "verified"
    assert resolution.excerpt == (
        "Qdrant supports payload filtering for scoped RAG queries per user."
    )
    assert resolution.source_reference == "doc-42#chunk3"
    source_store.search.assert_called_once_with(claim, top_k=1)


@pytest.mark.asyncio
async def test_verify_and_resolve_citation_rejects_when_nothing_verifies() -> None:
    claim = "Some very specific unverifiable claim about a niche topic."
    bad_candidate = "Totally unrelated text about gardening."
    source_store = MagicMock()
    source_store.search.return_value = [
        {
            "text": "Also unrelated, this time about cooking.",
            "document_id": "doc-1",
            "chunk_index": 0,
        }
    ]

    resolution = await verify_and_resolve_citation(
        claim, bad_candidate, source_store=source_store, max_retries=1
    )

    assert resolution.status == "rejected"
    assert resolution.excerpt is None
    assert resolution.source_reference is None


@pytest.mark.asyncio
async def test_verify_and_resolve_citation_propagates_infrastructure_errors() -> None:
    claim = "Some claim that needs a retry."
    bad_candidate = "Unrelated candidate excerpt."
    source_store = MagicMock()
    source_store.search.side_effect = SourceStoreError("Qdrant unreachable")

    with pytest.raises(SourceStoreError):
        await verify_and_resolve_citation(claim, bad_candidate, source_store=source_store)


def test_format_citation_apa_with_structured_fields() -> None:
    result = format_citation("doc-1", "APA", fields=CitationFields(author="Smith", year=2020))

    assert result == "(Smith, 2020)"


def test_format_citation_apa_falls_back_without_structured_fields() -> None:
    result = format_citation("doc-1", "APA")

    assert result == "(doc-1)"


def test_format_citation_gost_with_reference_number() -> None:
    result = format_citation("doc-1", "GOST", fields=CitationFields(reference_number=3))

    assert result == "[3]"


def test_format_citation_gost_falls_back_without_reference_number() -> None:
    result = format_citation("doc-1", "GOST")

    assert result == "[doc-1]"


def test_format_citation_mla_and_custom_return_reference_as_is() -> None:
    assert format_citation("doc-1", "MLA") == "doc-1"
    assert format_citation("doc-1", "custom") == "doc-1"
