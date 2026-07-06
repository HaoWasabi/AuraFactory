# app/memory/procedural.py
"""
Procedural Memory — learned action patterns (trigger → action template).
Storage: PostgreSQL (JSONB triggers, GIN index).
Phase 1: In-memory with basic keyword matching.
Phase 2: PostgreSQL JSONB + semantic matching.
"""
import logging
from typing import List
from app.models.memory import ProceduralPattern
logger = logging.getLogger(__name__)


class ProceduralMemory:
    """
    Stores learned action patterns.
    Trigger → Action template with confidence scoring.
    """

    def __init__(self, db=None):
        self._db = db
        # Phase 1: In-memory storage
        self._patterns: List[ProceduralPattern] = []

    @property
    def is_ready(self) -> bool:
        return True  # Always ready (in-memory fallback)

    async def store(self, pattern: ProceduralPattern) -> None:
        """Store a new procedural pattern."""
        self._patterns.append(pattern)
        logger.debug(f"Stored procedural pattern: {pattern.id}")

    async def match_triggers(
        self, query: str, guild_id: int, min_confidence: float = 0.5
    ) -> List[ProceduralPattern]:
        """Find patterns whose triggers match the current context."""
        matches = []
        query_lower = query.lower()

        for pattern in self._patterns:
            if pattern.guild_id != guild_id:
                continue
            if pattern.confidence < min_confidence:
                continue

            # Simple keyword matching on trigger_conditions
            trigger_str = str(pattern.trigger_conditions).lower()
            if any(word in trigger_str for word in query_lower.split()):
                matches.append(pattern)

        # Sort by confidence
        matches.sort(key=lambda p: p.confidence, reverse=True)
        return matches[:5]

    async def record_outcome(self, pattern_id: str, success: bool) -> None:
        """Update confidence based on execution outcome."""
        for pattern in self._patterns:
            if pattern.id == pattern_id:
                if success:
                    pattern.success_count += 1
                else:
                    pattern.failure_count += 1
                # Recalculate confidence
                total = pattern.success_count + pattern.failure_count
                pattern.confidence = pattern.success_count / total if total > 0 else 0.5
                break
