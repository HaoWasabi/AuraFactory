# app/memory/episodic.py
"""
Episodic Memory — stores past interaction events.
Storage: VectorStore (ChromaDB Phase 1, OpenSearch Phase 2).
"""
import json
import logging
from typing import List, Optional
from datetime import datetime

from app.models.memory import EpisodicEvent

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """
    Stores and retrieves past interactions as episodic events.
    Each event = user prompt + agent plan + execution results.
    """

    COLLECTION_PREFIX = "episodic"

    def __init__(self, vectorstore=None, embedding=None):
        self._vectorstore = vectorstore
        self._embedding = embedding

    @property
    def is_ready(self) -> bool:
        return self._vectorstore is not None and self._embedding is not None

    async def store(self, event: EpisodicEvent) -> None:
        """Embed and store an episodic event."""
        if not self.is_ready:
            logger.debug("EpisodicMemory not ready (no vectorstore/embedding), skipping store")
            return

        text = f"{event.user_prompt}\n{json.dumps(event.execution_results, ensure_ascii=False)}"
        embedding = await self._embedding.embed(text)

        await self._vectorstore.add(
            collection=f"{self.COLLECTION_PREFIX}_{event.guild_id}",
            id=event.trace_id,
            text=text,
            embedding=embedding,
            metadata={
                "timestamp": event.timestamp.isoformat(),
                "importance": event.importance,
                "session_id": event.session_id,
                "user_prompt": event.user_prompt,
            },
        )

    async def search(
        self, query: str, guild_id: int, top_k: int = 3
    ) -> List[EpisodicEvent]:
        """Retrieve relevant past episodes by similarity."""
        if not self.is_ready:
            return []

        embedding = await self._embedding.embed(query)
        results = await self._vectorstore.query(
            collection=f"{self.COLLECTION_PREFIX}_{guild_id}",
            embedding=embedding,
            top_k=top_k,
        )

        events = []
        for r in results:
            meta = r.get("metadata", {})
            events.append(EpisodicEvent(
                guild_id=guild_id,
                session_id=meta.get("session_id", ""),
                user_prompt=meta.get("user_prompt", ""),
                agent_plan={},
                execution_results=[],
                timestamp=datetime.fromisoformat(meta["timestamp"]) if "timestamp" in meta else datetime.utcnow(),
                trace_id=r.get("id", ""),
                importance=meta.get("importance", 0.5),
            ))

        return events
