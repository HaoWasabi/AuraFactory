"""MemoryService — unified facade over all memory sub-systems."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.memory.episodic import EpisodicMemory
from app.memory.procedural import ProceduralMemory
from app.memory.scoring import ImportanceScoring
from app.memory.semantic import SemanticMemory
from app.memory.working import WorkingMemory

logger = logging.getLogger(__name__)


class MemoryType(str, Enum):
    """Supported memory types."""

    WORKING = "working"
    PROCEDURAL = "procedural"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class MemoryItem:
    """A single memory record returned by recall."""

    memory_type: MemoryType
    content: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


class MemoryService:
    """Unified memory facade — routes to appropriate sub-memory based on type."""

    def __init__(self, db: Any, cache: Any | None = None) -> None:
        self._db = db
        self._cache = cache
        self._working = WorkingMemory()
        self._procedural = ProceduralMemory(db)
        self._episodic = EpisodicMemory()
        self._semantic = SemanticMemory()
        self._scoring = ImportanceScoring()
        logger.info("MemoryService initialized")

    @property
    def working(self) -> WorkingMemory:
        """Direct access to working memory."""
        return self._working

    @property
    def procedural(self) -> ProceduralMemory:
        """Direct access to procedural memory."""
        return self._procedural

    @property
    def scoring(self) -> ImportanceScoring:
        """Direct access to importance scoring."""
        return self._scoring

    async def recall(
        self,
        guild_id: int,
        query: str,
        memory_types: list[MemoryType] | None = None,
    ) -> list[MemoryItem]:
        """Recall memories matching query across specified memory types.

        Args:
            guild_id: Discord guild identifier.
            query: Search query string.
            memory_types: Types to search (defaults to all enabled).

        Returns:
            List of matching MemoryItem objects sorted by relevance score.
        """
        types_to_search = memory_types or [MemoryType.WORKING, MemoryType.PROCEDURAL]
        results: list[MemoryItem] = []

        for mem_type in types_to_search:
            try:
                items = await self._recall_from(guild_id, query, mem_type)
                results.extend(items)
            except Exception as exc:
                logger.warning("Recall from %s failed: %s", mem_type.value, exc)

        results.sort(key=lambda item: item.score, reverse=True)
        logger.debug("Recalled %d items for guild=%d query='%s'", len(results), guild_id, query)
        return results

    async def store(
        self,
        guild_id: int,
        memory_type: MemoryType,
        content: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a memory item in the appropriate sub-system.

        Args:
            guild_id: Discord guild identifier.
            memory_type: Target memory tier.
            content: Data to store.
            metadata: Optional metadata dict.
        """
        meta = metadata or {}

        if memory_type == MemoryType.WORKING:
            session_id = meta.get("session_id", str(guild_id))
            self._working.store_context(session_id, meta.get("key", "data"), content)
        elif memory_type == MemoryType.PROCEDURAL:
            await self._procedural.add_rule(
                guild_id=guild_id,
                trigger_condition=content.get("trigger", {}),
                action=content.get("action", {}),
                confidence=meta.get("confidence", 1.0),
            )
        elif memory_type == MemoryType.EPISODIC:
            self._episodic.store(guild_id, content, meta)
        elif memory_type == MemoryType.SEMANTIC:
            self._semantic.store(guild_id, content, meta)
        else:
            raise ValueError(f"Unknown memory type: {memory_type}")

        logger.info("Stored %s memory for guild=%d", memory_type.value, guild_id)

    async def search(self, guild_id: int, query: str) -> list[MemoryItem]:
        """Search all enabled memory systems for matching items.

        Alias for recall with all enabled types.
        """
        return await self.recall(guild_id, query)

    async def forget(self, guild_id: int, memory_id: str) -> None:
        """Delete a specific memory by ID.

        Args:
            guild_id: Discord guild identifier.
            memory_id: Unique memory identifier (format: type:id).
        """
        if ":" not in memory_id:
            raise ValueError("memory_id must be formatted as 'type:id'")

        mem_type_str, item_id = memory_id.split(":", 1)

        if mem_type_str == MemoryType.PROCEDURAL.value:
            await self._procedural.delete_rule(item_id)
        elif mem_type_str == MemoryType.WORKING.value:
            self._working.clear(item_id)
        else:
            logger.warning("Cannot forget from disabled memory type: %s", mem_type_str)

        logger.info("Forgot memory %s for guild=%d", memory_id, guild_id)

    async def summarize(self, guild_id: int) -> str:
        """Generate a summary of all stored memories for a guild.

        Returns:
            Human-readable summary string.
        """
        parts: list[str] = []

        # Procedural rules count
        rules = await self._procedural.get_rules(guild_id)
        parts.append(f"Procedural rules: {len(rules)}")

        # Working memory sessions
        session_key = str(guild_id)
        ctx = self._working.get_context(session_key)
        if ctx:
            parts.append(f"Working memory keys: {list(ctx.keys())}")

        return f"[Guild {guild_id}] " + " | ".join(parts)

    async def _recall_from(
        self, guild_id: int, query: str, mem_type: MemoryType
    ) -> list[MemoryItem]:
        """Internal dispatch for recall by memory type."""
        if mem_type == MemoryType.PROCEDURAL:
            rules = await self._procedural.get_rules(guild_id)
            items: list[MemoryItem] = []
            query_lower = query.lower()
            for rule in rules:
                trigger_str = str(rule.get("trigger_condition", "")).lower()
                if query_lower in trigger_str or any(
                    word in trigger_str for word in query_lower.split()
                ):
                    items.append(
                        MemoryItem(
                            memory_type=MemoryType.PROCEDURAL,
                            content=rule,
                            metadata={"rule_id": rule.get("id")},
                            score=rule.get("confidence", 0.5),
                        )
                    )
            return items

        if mem_type == MemoryType.WORKING:
            session_id = str(guild_id)
            ctx = self._working.get_context(session_id)
            items = []
            query_lower = query.lower()
            for key, value in ctx.items():
                if query_lower in str(key).lower() or query_lower in str(value).lower():
                    items.append(
                        MemoryItem(
                            memory_type=MemoryType.WORKING,
                            content={key: value},
                            metadata={"session_id": session_id},
                            score=0.7,
                        )
                    )
            return items

        return []
