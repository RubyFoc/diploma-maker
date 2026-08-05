"""Source management pipeline stage: Qdrant-backed RAG store (ADR-0002, TASK-E04-1) and
external academic search (TASK-E04-2)."""

from diploma_backend.sources.client import (
    QdrantSourceStore,
    SourceIngestionError,
    SourceStoreError,
)
from diploma_backend.sources.search import (
    SourceSearchError,
    SourceSearchResult,
    search_sources,
)

__all__ = [
    "QdrantSourceStore",
    "SourceIngestionError",
    "SourceSearchError",
    "SourceSearchResult",
    "SourceStoreError",
    "search_sources",
]
