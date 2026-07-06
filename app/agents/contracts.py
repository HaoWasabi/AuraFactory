# app/agents/contracts.py
"""
Contracts between agents — structured communication.
v2: Simplified roles for 3-mode architecture.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    ADMIN = "admin"
    ASSISTANT = "assistant"
    ARCHITECT = "architect"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_APPROVAL = "needs_approval"
    TIMEOUT = "timeout"


@dataclass
class TaskAssignment:
    task_id: str
    target_agent: AgentRole
    action: str
    parameters: Dict[str, Any]
    priority: str = "medium"
    timeout_seconds: int = 30
    success_criteria: str = ""
    context: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "target_agent": self.target_agent.value,
            "action": self.action,
            "parameters": self.parameters,
            "priority": self.priority,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass
class TaskResult:
    task_id: str
    agent: AgentRole
    status: TaskStatus
    output: Optional[Dict[str, Any]] = None
    error_message: str = ""
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent": self.agent.value,
            "status": self.status.value,
            "output": self.output,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
        }
