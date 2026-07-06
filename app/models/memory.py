# app/models/memory.py
"""Memory models — cognitive science inspired memory types."""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class EpisodicEvent:
    """A past event/interaction remembered by the system."""
    guild_id: int
    session_id: str
    user_prompt: str
    agent_plan: dict
    execution_results: List[dict]
    timestamp: datetime
    trace_id: str
    importance: float = 0.5


@dataclass
class SemanticFact:
    """A learned fact — preference, rule, entity, relationship."""
    guild_id: int
    fact_type: str      # preference | rule | entity | relationship
    content: str
    confidence: float
    source: str         # user_explicit | inferred | consolidated
    created_at: datetime
    updated_at: datetime
    metadata: dict = field(default_factory=dict)


@dataclass
class ProceduralPattern:
    """A learned action pattern (trigger → action template)."""
    id: str
    guild_id: int
    trigger_conditions: dict
    action_template: dict
    confidence: float
    success_count: int = 0
    failure_count: int = 0
    created_at: Optional[datetime] = None
    last_used: Optional[datetime] = None


@dataclass
class MemoryContext:
    """Combined context from all memory types — passed to agents for reasoning."""
    working_memory: dict
    relevant_episodes: List[EpisodicEvent]
    semantic_facts: List[SemanticFact]
    procedural_patterns: List[ProceduralPattern]

    def to_prompt_context(self) -> str:
        """Format memory into LLM-readable context string."""
        parts = []
        if self.semantic_facts:
            parts.append(
                "Known facts:\n" + "\n".join(f"- {f.content}" for f in self.semantic_facts)
            )
        if self.relevant_episodes:
            parts.append(
                "Past actions:\n" + "\n".join(
                    f"- User asked: {e.user_prompt} → Result: "
                    f"{e.execution_results[0].get('status', 'unknown') if e.execution_results else 'unknown'}"
                    for e in self.relevant_episodes[:3]
                )
            )
        if self.procedural_patterns:
            parts.append(
                "Known patterns:\n" + "\n".join(
                    f"- {p.trigger_conditions} → confidence: {p.confidence:.0%}"
                    for p in self.procedural_patterns
                )
            )
        return "\n\n".join(parts)
