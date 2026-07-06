"""Task models for agent work assignments and results."""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class TaskAssignment:
    """Represents a task assigned to an agent."""

    trace_id: str
    intent: str
    agent_role: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)

    def to_prompt_context(self) -> str:
        """Format the task as context for an LLM prompt."""
        return (
            f"Intent: {self.intent}\n"
            f"Agent Role: {self.agent_role}\n"
            f"Message: {self.message}\n"
            f"Context: {self.context}"
        )


@dataclass
class TaskResult:
    """Represents the result of an agent completing a task."""

    trace_id: str
    content: str
    status: str = "completed"
    tools_called: List[str] = field(default_factory=list)
    cost: float = 0.0

    @property
    def is_success(self) -> bool:
        """Check if the task completed successfully."""
        return self.status == "completed"
