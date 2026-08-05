"""Tests for TASK-E04-1 (Qdrant client integration + embedding ingestion pipeline).

Uses `QdrantClient(location=":memory:")` (an in-process Qdrant instance backed by no external
process) so these are real integration-style tests against the actual `qdrant-client` API
without needing a live Qdrant container. The embedding call is monkeypatched with a small
deterministic fake vector function instead of loading a real `sentence-transformers` model:
downloading `all-MiniLM-L6-v2` needs network access on first use, which this sandboxed test
environment cannot rely on. The fake preserves the property the tests care about — near-identical
text embeds to near-identical vectors, and unrelated text embeds far away — so `search` still
proves out real similarity behavior end to end against the in-memory Qdrant collection.
"""

import hashlib

import pytest
from qdrant_client import QdrantClient

from diploma_backend.sources.client import (
    _EMBEDDING_DIM,
    QdrantSourceStore,
    SourceIngestionError,
    SourceStoreError,
)


def _fake_vector(text: str) -> list[float]:
    """Deterministic pseudo-embedding: same text -> same vector, similar text -> nearby vector.

    Buckets the text into a handful of topic keywords so unrelated sentences land in different
    regions of the vector space, which is all `search`'s relevance test needs.
    """
    keywords = ["qdrant", "vector", "citation", "plagiarism", "unrelated"]
    vector = [0.0] * _EMBEDDING_DIM
    lowered = text.lower()
    for i, keyword in enumerate(keywords):
        if keyword in lowered:
            vector[i] = 1.0
    # Add a small per-text jitter so identical-topic-but-different-text chunks aren't exact ties.
    digest = hashlib.sha256(text.encode()).digest()
    for i in range(len(keywords), _EMBEDDING_DIM):
        vector[i] = (digest[i % len(digest)] / 255.0) * 0.01
    return vector


@pytest.fixture(autouse=True)
def _mock_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("diploma_backend.sources.client._embed", lambda text: _fake_vector(text))


def _store() -> QdrantSourceStore:
    return QdrantSourceStore(client=QdrantClient(location=":memory:"), collection_name="test_docs")


def test_collection_is_created_if_missing() -> None:
    client = QdrantClient(location=":memory:")
    assert client.collection_exists("test_docs") is False

    QdrantSourceStore(client=client, collection_name="test_docs")

    assert client.collection_exists("test_docs") is True


def test_ensure_collection_is_idempotent() -> None:
    client = QdrantClient(location=":memory:")

    QdrantSourceStore(client=client, collection_name="test_docs")
    QdrantSourceStore(client=client, collection_name="test_docs")  # must not raise

    assert client.collection_exists("test_docs") is True


def test_upsert_then_search_returns_relevant_chunk() -> None:
    store = _store()
    store.upsert_chunks(
        "doc-1",
        [
            "Qdrant is the vector database used for RAG storage.",
            "This sentence is completely unrelated filler text.",
        ],
    )

    results = store.search("Tell me about qdrant vector storage", top_k=1)

    assert results[0]["text"] == "Qdrant is the vector database used for RAG storage."
    assert results[0]["document_id"] == "doc-1"


def test_search_filters_by_document_id() -> None:
    store = _store()
    store.upsert_chunks("doc-1", ["Citation verification uses plagiarism checks."])
    store.upsert_chunks("doc-2", ["Citation verification uses plagiarism checks."])

    results = store.search("citation plagiarism", document_id="doc-2", top_k=5)

    assert results
    assert all(r["document_id"] == "doc-2" for r in results)


def test_upsert_chunks_mid_document_failure_raises_ingestion_error_with_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store()
    calls = {"n": 0}

    def _flaky_embed(text: str) -> list[float]:
        calls["n"] += 1
        if calls["n"] == 2:
            raise SourceStoreError("simulated embedding failure")
        return _fake_vector(text)

    monkeypatch.setattr("diploma_backend.sources.client._embed", _flaky_embed)

    with pytest.raises(SourceIngestionError) as exc_info:
        store.upsert_chunks("doc-3", ["chunk one", "chunk two", "chunk three"])

    error = exc_info.value
    assert error.document_id == "doc-3"
    assert error.succeeded_indices == [0]
    assert error.failed_index == 1


def test_upsert_chunks_can_resume_after_failure() -> None:
    store = _store()
    store.upsert_chunks("doc-4", ["chunk one"])  # succeeded chunk 0

    succeeded = store.upsert_chunks("doc-4", ["chunk two"], start_index=1)

    assert succeeded == [1]
    results = store.search("chunk", document_id="doc-4", top_k=5)
    assert len(results) == 2


def test_qdrant_failure_raises_domain_error_not_raw_exception() -> None:
    store = _store()
    store._collection = "does-not-exist"  # force the underlying client call to fail

    with pytest.raises(SourceStoreError):
        store.search("anything")
