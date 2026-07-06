"""ChromaDB vector store placeholder (disabled in Phase 1)."""

import logging
from typing import Any, Dict, List, Optional

from .base import VectorStoreBase

logger = logging.getLogger(__name__)


class DisabledError(Exception):
    """Raised when a disabled component is accessed."""

    def __init__(self, component: str = "VectorStore") -> None:
        super().__init__(
            f"{component} is disabled in Phase 1. "
            f"Enable it by configuring the appropriate environment variables."
        )


class ChromaVectorStore(VectorStoreBase):
    """ChromaDB vector store - disabled placeholder for Phase 1.

    All operations raise DisabledError. This will be implemented
    when vector search is enabled in a later phase.
    """

    def __init__(self) -> None:
        logger.warning("ChromaVectorStore instantiated but is disabled in Phase 1")

    async def add(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Disabled - raises DisabledError."""
        raise DisabledError("ChromaVectorStore.add")

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Disabled - raises DisabledError."""
        raise DisabledError("ChromaVectorStore.search")

    async def delete(self, ids: List[str]) -> None:
        """Disabled - raises DisabledError."""
        raise DisabledError("ChromaVectorStore.delete")
