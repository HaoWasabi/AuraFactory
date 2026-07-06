"""Base vector store interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class VectorStoreBase(ABC):
    """Abstract base class for vector store implementations."""

    @abstractmethod
    async def add(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Add texts with optional metadata to the vector store.

        Returns:
            List of IDs for the stored documents.
        """
        ...

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search for similar texts.

        Returns:
            List of results with text, metadata, and similarity score.
        """
        ...

    @abstractmethod
    async def delete(self, ids: List[str]) -> None:
        """Delete documents by their IDs."""
        ...
