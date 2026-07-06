# app/infra/vectorstore/base.py
"""
VectorStore ABC — interface for all vector database backends.
Phase 1: ChromaDB. Phase 2: OpenSearch.
"""
from abc import ABC, abstractmethod
from typing import List, Optional


class VectorStore(ABC):
    """Abstract interface for vector database operations."""

    @abstractmethod
    async def add(
        self,
        collection: str,
        id: str,
        text: str,
        embedding: List[float],
        metadata: Optional[dict] = None,
    ) -> None:
        """Add a document with its embedding to a collection."""
        ...

    @abstractmethod
    async def add_batch(
        self,
        collection: str,
        ids: List[str],
        texts: List[str],
        embeddings: List[List[float]],
        metadatas: Optional[List[dict]] = None,
    ) -> None:
        """Batch add multiple documents."""
        ...

    @abstractmethod
    async def query(
        self,
        collection: str,
        embedding: List[float],
        top_k: int = 5,
        filter: Optional[dict] = None,
    ) -> List[dict]:
        """Query similar documents by embedding vector."""
        ...

    @abstractmethod
    async def delete(self, collection: str, id: str) -> None:
        """Delete a document from a collection."""
        ...

    @abstractmethod
    async def delete_collection(self, collection: str) -> None:
        """Delete an entire collection."""
        ...

    @abstractmethod
    async def count(self, collection: str) -> int:
        """Count documents in a collection."""
        ...
