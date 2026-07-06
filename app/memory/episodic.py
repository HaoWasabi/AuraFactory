"""EpisodicMemory — DISABLED placeholder for Phase 2.

Episodic memory requires a vector store (e.g., pgvector, Pinecone)
for similarity search over past experiences. Will be enabled in Phase 2.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DisabledFeatureError(Exception):
    """Raised when a disabled feature is accessed."""

    pass


class EpisodicMemory:
    """Episodic memory — DISABLED.

    All methods raise DisabledFeatureError. This placeholder ensures
    the memory service interface is complete and ready for Phase 2
    vector store integration.
    """

    def __init__(self) -> None:
        logger.info("EpisodicMemory initialized (DISABLED)")

    def store(self, guild_id: int, content: Any, metadata: dict[str, Any] | None = None) -> None:
        """Store an episodic memory — DISABLED.

        Args:
            guild_id: Discord guild identifier.
            content: Experience content to store.
            metadata: Optional metadata.

        Raises:
            DisabledFeatureError: Always raised.
        """
        raise DisabledFeatureError(
            "Episodic memory disabled — requires vector store. Enable in Phase 2."
        )

    def recall(self, guild_id: int, query: str, limit: int = 10) -> list[Any]:
        """Recall episodic memories — DISABLED.

        Args:
            guild_id: Discord guild identifier.
            query: Similarity search query.
            limit: Maximum results.

        Raises:
            DisabledFeatureError: Always raised.
        """
        raise DisabledFeatureError(
            "Episodic memory disabled — requires vector store. Enable in Phase 2."
        )

    def forget(self, guild_id: int, memory_id: str) -> None:
        """Forget an episodic memory — DISABLED.

        Args:
            guild_id: Discord guild identifier.
            memory_id: Memory identifier.

        Raises:
            DisabledFeatureError: Always raised.
        """
        raise DisabledFeatureError(
            "Episodic memory disabled — requires vector store. Enable in Phase 2."
        )

    def search(self, guild_id: int, query: str, limit: int = 10) -> list[Any]:
        """Search episodic memories — DISABLED.

        Args:
            guild_id: Discord guild identifier.
            query: Search query.
            limit: Maximum results.

        Raises:
            DisabledFeatureError: Always raised.
        """
        raise DisabledFeatureError(
            "Episodic memory disabled — requires vector store. Enable in Phase 2."
        )
