# app/memory/service.py
"""
MemoryService — Unified facade for all memory operations.
Orchestrator and agents call this, never sub-modules directly.
"""
import logging
from typing import List, Optional
from datetime import datetime

from app.models.memory import MemoryContext, EpisodicEvent, SemanticFact, ProceduralPattern
from app.memory.working import WorkingMemory
from app.memory.episodic import EpisodicMemory
from app.memory.semantic import SemanticMemory
from app.memory.procedural import ProceduralMemory
from app.memory.scoring import score_memory

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Unified interface for all memory operations.
    Injected with infrastructure dependencies.
    """

    def __init__(
        self,
        vectorstore=None,
        db=None,
        cache=None,
        embedding=None,
    ):
        self.working = WorkingMemory(cache=cache)
        self.episodic = EpisodicMemory(vectorstore=vectorstore, embedding=embedding)
        self.semantic = SemanticMemory(vectorstore=vectorstore, embedding=embedding)
        self.procedural = ProceduralMemory(db=db)

    async def recall(
        self, query: str, guild_id: int, session_id: str, top_k: int = 5
    ) -> MemoryContext:
        """
        Main recall — gather relevant context from all memory types.
        Called by Orchestrator before planning.
        """
        working_ctx = await self.working.get_context(session_id)
        episodic_results = await self.episodic.search(query, guild_id, top_k=3)
        semantic_results = await self.semantic.search(query, guild_id, top_k=top_k)
        procedural_matches = await self.procedural.match_triggers(query, guild_id)

        return MemoryContext(
            working_memory=working_ctx,
            relevant_episodes=episodic_results,
            semantic_facts=semantic_results,
            procedural_patterns=procedural_matches,
        )

    async def store_episode(
        self,
        guild_id: int,
        session_id: str,
        prompt: str,
        plan: dict,
        results: List[dict],
        trace_id: str,
        importance: float = 0.5,
    ) -> None:
        """Store completed interaction as episodic memory."""
        episode = EpisodicEvent(
            guild_id=guild_id,
            session_id=session_id,
            user_prompt=prompt,
            agent_plan=plan,
            execution_results=results,
            timestamp=datetime.utcnow(),
            trace_id=trace_id,
            importance=importance,
        )
        await self.episodic.store(episode)

    async def store_fact(
        self,
        guild_id: int,
        content: str,
        fact_type: str = "preference",
        confidence: float = 0.7,
        source: str = "inferred",
    ) -> None:
        """Store a semantic fact."""
        fact = SemanticFact(
            guild_id=guild_id,
            fact_type=fact_type,
            content=content,
            confidence=confidence,
            source=source,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self.semantic.store(fact)

    async def add_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        guild_id: Optional[int] = None,
    ) -> None:
        """Add a message to working memory (conversation history)."""
        await self.working.add_message(session_id, user_id, role, content, guild_id)

    async def get_conversation_history(
        self, session_id: str, limit: int = 10
    ) -> List[dict]:
        """Get recent conversation messages for a session."""
        return await self.working.get_conversation_history(session_id, limit)

    def get_stats(self) -> dict:
        """Get memory system statistics."""
        return {
            "working_sessions": self.working.session_count,
            "episodic_ready": self.episodic.is_ready,
            "semantic_ready": self.semantic.is_ready,
            "procedural_ready": self.procedural.is_ready,
        }
