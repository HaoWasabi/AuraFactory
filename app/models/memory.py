"""Memory models for procedural rules and knowledge snapshots."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any


@dataclass
class ProceduralRule:
    """A learned rule that maps conditions to actions."""

    rule_id: str
    guild_id: str
    trigger_condition: Dict[str, Any] = field(default_factory=dict)
    action: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5

    def matches(self, context: Dict[str, Any]) -> bool:
        """Check if this rule's trigger condition matches the given context."""
        for key, value in self.trigger_condition.items():
            if context.get(key) != value:
                return False
        return True


@dataclass
class KnowledgeSnapshot:
    """A point-in-time snapshot of guild knowledge."""

    guild_id: str
    snapshot: Dict[str, Any] = field(default_factory=dict)
    crawled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
