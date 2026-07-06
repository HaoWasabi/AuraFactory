# app/memory/semantic.py
"""
Semantic Memory — stores facts, preferences, rules about the guild/users.
Storage: VectorStore (ChromaDB Phase 1).
"""
import logging
from typing import List
from datetime import datetime

from app.models.memory import SemanticFact

logger = logging.getLogger(__name__)


class SemanticMemory:
    """
    Facts and preferences learned over time.
    Examples: "Admin prefers kebab-case channel names",
              "This server is for gaming community",
              "Never delete #announcements".
    """

    COLLECTION_PREFIX = "semantic"

    def __init__(self, vectorstore=None, embedding=None):
        self._vectorstore = vectorstore
        self._embedding = embedding

    @property
    def is_ready(self) -> bool:
        return self._vectorstore is not None and self._embedding is not None

    async def store(self, fact: SemanticFact) -> None:
        """Embed and store a semantic fact."""
        if not self.is_ready:
            logger.debug("SemanticMemory not ready, skipping store")
            return

        embedding = await self._embedding.embed(fact.content)
        fact_id = f"fact_{fact.guild_id}_{int(fact.created_at.timestamp() * 1000)}"

        await self._vectorstore.add(
            collection=f"{self.COLLECTION_PREFIX}_{fact.guild_id}",
            id=fact_id,
            text=fact.content,
            embedding=embedding,
            metadata={
                "fact_type": fact.fact_type,
                "confidence": fact.confidence,
                "source": fact.source,
                "created_at": fact.created_at.isoformat(),
                **fact.metadata,
            },
        )

    async def search(
        self, query: str, guild_id: int, top_k: int = 5
    ) -> List[SemanticFact]:
        """Retrieve relevant facts by similarity."""
        if not self.is_ready:
            return []

        embedding = await self._embedding.embed(query)
        results = await self._vectorstore.query(
            collection=f"{self.COLLECTION_PREFIX}_{guild_id}",
            embedding=embedding,
            top_k=top_k,
        )

        facts = []
        for r in results:
            meta = r.get("metadata", {})
            facts.append(SemanticFact(
                guild_id=guild_id,
                fact_type=meta.get("fact_type", "entity"),
                content=r.get("text", ""),
                confidence=meta.get("confidence", 0.5),
                source=meta.get("source", "inferred"),
                created_at=datetime.fromisoformat(meta["created_at"]) if "created_at" in meta else datetime.utcnow(),
                updated_at=datetime.utcnow(),
                metadata=meta,
            ))

        return facts
