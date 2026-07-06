"""SemanticMemory — DISABLED placeholder for Phase 2.

Semantic memory requires a vector store for embedding-based retrieval
of factual knowledge. Will be enabled in Phase 2.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DisabledFeatureError(Exception):
    """Raised when a disabled feature is accessed."""

    pass


class SemanticMemory:
    """Semantic memory — DISABLED.

    All methods raise DisabledFeatureError. This placeholder ensures
    the memory service interface is complete and ready for Phase 2
    vector store integration.
    """

    def __init__(self) -> None:
        logger.info("SemanticMemory initialized (DISABLED)")

    def store(self, guild_id: int, content: Any, metadata: dict[str, Any] | None = None) -> None:
        """Store semantic knowledge — DISABLED.

        Args:
            guild_id: Discord guild identifier.
            content: Factual knowledge to store.
            metadata: Optional metadata.

        Raises:
            DisabledFeatureError: Always raised.
        """
        raise DisabledFeatureError(
            "Semantic memory disabled — requires vector store. Enable in Phase 2."
        )

    def recall(self, guild_id: int, query: str, limit: int = 10) -> list[Any]:
        """Recall semantic knowledge — DISABLED.

        Args:
            guild_id: Discord guild identifier.
            query: Similarity search query.
            limit: Maximum results.

        Raises:
            DisabledFeatureError: Always raised.
        """
        raise DisabledFeatureError(
            "Semantic memory disabled — requires vector store. Enable in Phase 2."
        )

    def forget(self, guild_id: int, memory_id: str) -> None:
        """Forget semantic knowledge — DISABLED.

        Args:
            guild_id: Discord guild identifier.
            memory_id: Memory identifier.

        Raises:
            DisabledFeatureError: Always raised.
        """
        raise DisabledFeatureError(
            "Semantic memory disabled — requires vector store. Enable in Phase 2."
        )

    def search(self, guild_id: int, query: str, limit: int = 10) -> list[Any]:
        """Search semantic knowledge — DISABLED.

        Args:
            guild_id: Discord guild identifier.
            query: Search query.
            limit: Maximum results.

        Raises:
            DisabledFeatureError: Always raised.
        """
        raise DisabledFeatureError(
            "Semantic memory disabled — requires vector store. Enable in Phase 2."
        )
