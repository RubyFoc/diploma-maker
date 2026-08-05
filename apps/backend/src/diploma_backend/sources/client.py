"""Qdrant-backed RAG source store: embedding ingestion + similarity search.

Implements TASK-E04-1 (source management pipeline stage per `docs/architecture/overview.md`).
The vector DB is Qdrant per ADR-0002. Embeddings are produced locally via `fastembed`
(Qdrant's own ONNX-based embedding library) rather than a DeepSeek API call (ADR-0010):
DeepSeek's public API is chat-completions only and has no dedicated embeddings endpoint, and
`fastembed` avoids pulling in a full CUDA-enabled `torch` (as `sentence-transformers` would) for
what is CPU-only inference here — smaller install, no GPU deps, purpose-built to pair with
Qdrant.

Ingestion is resilient to mid-document failure: `upsert_chunks` embeds and stores chunks one at
a time and raises `SourceIngestionError` carrying which chunk indices already succeeded, so a
caller can retry just the remainder instead of ending up with partially-ingested data that looks
indistinguishable from a complete ingestion.

Out of scope here (later, separate tasks): external academic search API integration
(TASK-E04-2), geo-fencing (TASK-E04-3), citation verification/retry (TASK-E04-4).
"""

import os
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

_DEFAULT_COLLECTION = "diploma_maker_documents"
_DEFAULT_URL = "http://localhost:6333"

# BAAI/bge-small-en-v1.5 (ADR-0010): fastembed's default model, 384-dim, ONNX/CPU-only, small
# enough to run offline without a GPU or torch.
_EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_EMBEDDING_DIM = 384

# Fixed namespace for deterministic point IDs (`document_id` + chunk index) so re-ingesting the
# same chunk after a partial failure overwrites it instead of creating a duplicate point.
_POINT_ID_NAMESPACE = uuid.UUID("2f3f0f0a-9c1b-4b8a-8f0e-6e9d9d9a7b2e")


class SourceStoreError(Exception):
    """Raised when a Qdrant or embedding call fails; wraps the raw client exception so callers
    never need to catch `qdrant_client`/`sentence_transformers` exceptions directly.
    """


class SourceIngestionError(SourceStoreError):
    """Raised when `upsert_chunks` fails partway through a multi-chunk document.

    Carries `succeeded_indices` (chunks already embedded and stored before the failure) and
    `failed_index` (the chunk being processed when it failed), so a caller can retry only the
    remaining chunks rather than re-ingesting the whole document or leaving silently-partial
    data indistinguishable from a complete ingestion.
    """

    def __init__(
        self, document_id: str, succeeded_indices: list[int], failed_index: int, cause: Exception
    ) -> None:
        self.document_id = document_id
        self.succeeded_indices = succeeded_indices
        self.failed_index = failed_index
        super().__init__(
            f"Ingestion for document {document_id!r} failed at chunk {failed_index} after "
            f"{len(succeeded_indices)} chunk(s) succeeded ({type(cause).__name__}: {cause}); "
            f"retry starting at chunk index {failed_index}."
        )


_embedder: Any = None  # lazy singleton; loading the model from disk is expensive


def _get_embedder() -> Any:
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(model_name=_EMBEDDING_MODEL_NAME)
    return _embedder


def _embed(text: str) -> list[float]:
    """Embed `text` with the local fastembed model.

    Raises `SourceStoreError` if the model fails to load or encode the text.
    """
    try:
        return next(iter(_get_embedder().embed([text]))).tolist()
    except Exception as exc:
        raise SourceStoreError(f"Embedding failed: {type(exc).__name__}: {exc}") from exc


def _point_id(document_id: str, index: int) -> str:
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, f"{document_id}:{index}"))


class QdrantSourceStore:
    """Wraps a Qdrant collection for chunk ingestion and similarity search."""

    def __init__(
        self,
        url: str | None = None,
        collection_name: str | None = None,
        client: QdrantClient | None = None,
    ) -> None:
        """Connect to Qdrant and ensure the target collection exists (idempotent).

        `url` and `collection_name` fall back to `QDRANT_URL`/`QDRANT_COLLECTION`. Pass `client`
        directly in tests (e.g. `QdrantClient(location=":memory:")`) to avoid a real Qdrant
        instance.
        Raises `SourceStoreError` if the collection cannot be created/verified.
        """
        self._collection = collection_name or os.environ.get("QDRANT_COLLECTION", _DEFAULT_COLLECTION)
        self._client = client or QdrantClient(url=url or os.environ.get("QDRANT_URL", _DEFAULT_URL))
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            existing = {c.name for c in self._client.get_collections().collections}
            if self._collection not in existing:
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(size=_EMBEDDING_DIM, distance=Distance.COSINE),
                )
        except Exception as exc:
            raise SourceStoreError(
                f"Failed to ensure Qdrant collection {self._collection!r}: {type(exc).__name__}: {exc}"
            ) from exc

    def upsert_chunks(self, document_id: str, chunks: list[str], start_index: int = 0) -> list[int]:
        """Embed and store `chunks` under `document_id`, one chunk at a time.

        `start_index` lets a caller resume a previously-interrupted ingestion at the chunk after
        the last one that succeeded (see `SourceIngestionError.failed_index`); point IDs are
        deterministic per `(document_id, index)`, so re-upserting an already-succeeded chunk is
        a no-op overwrite rather than a duplicate.
        Returns the list of chunk indices stored (relative to `start_index`, i.e.
        `start_index..start_index+len(chunks)-1` on full success).
        Raises `SourceIngestionError` if any chunk fails to embed or upsert, identifying which
        indices succeeded before the failure and which index failed.
        """
        succeeded: list[int] = []
        for offset, chunk in enumerate(chunks):
            index = start_index + offset
            try:
                vector = _embed(chunk)
                point = PointStruct(
                    id=_point_id(document_id, index),
                    vector=vector,
                    payload={"document_id": document_id, "chunk_index": index, "text": chunk},
                )
                self._client.upsert(collection_name=self._collection, points=[point])
            except Exception as exc:
                raise SourceIngestionError(document_id, succeeded, index, exc) from exc
            succeeded.append(index)
        return succeeded

    def search(
        self, query: str, document_id: str | None = None, top_k: int = 5
    ) -> list[dict[str, Any]]:
        """Embed `query` and return the `top_k` most similar stored chunks.

        `document_id`, if given, restricts the search to chunks ingested under that document via
        Qdrant payload filtering; otherwise the search spans the whole collection.
        Returns a list of `{"text", "document_id", "chunk_index", "score"}` dicts, most similar
        first.
        Raises `SourceStoreError` on any embedding or Qdrant query failure.
        """
        query_filter = (
            Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])
            if document_id is not None
            else None
        )
        try:
            vector = _embed(query)
            results = self._client.query_points(
                collection_name=self._collection,
                query=vector,
                query_filter=query_filter,
                limit=top_k,
            ).points
        except SourceStoreError:
            raise
        except Exception as exc:
            raise SourceStoreError(f"Qdrant search failed: {type(exc).__name__}: {exc}") from exc

        return [
            {
                "text": point.payload.get("text") if point.payload else None,
                "document_id": point.payload.get("document_id") if point.payload else None,
                "chunk_index": point.payload.get("chunk_index") if point.payload else None,
                "score": point.score,
            }
            for point in results
        ]
