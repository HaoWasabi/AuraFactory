# schemas/contracts.py
"""
Agentic AI Lens Principle 5: Ground autonomous behavior in explicit contracts
Well-Architected (Reliability): Structured communication reduces failures

Mọi tương tác giữa agents đều qua schema này.
Không có free-text messaging → validate được, trace được, debug được.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Literal
from datetime import datetime
from enum import Enum


class AgentRole(str, Enum):
    """Principle 1: Decompose — mỗi agent có role rõ ràng"""
    ORCHESTRATOR = "orchestrator"
    ARCHITECT = "architect"
    MODERATOR = "moderator"
    DEVOPS = "devops"
    COPILOT = "copilot"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_APPROVAL = "needs_approval"
    TIMEOUT = "timeout"


@dataclass
class ToolDefinition:
    """Contract cho mỗi tool — agent biết chính xác tool làm gì"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema format
    risk_level: str = "low"  # low | medium | high | critical
    requires_approval: bool = False
    timeout_ms: int = 10000
    retry_max: int = 2


@dataclass
class TaskAssignment:
    """
    Contract: Orchestrator → Specialist Agent
    Khi Orchestrator giao việc, phải đúng format này.
    """
    task_id: str
    target_agent: AgentRole
    action: str                    # Tên tool/action cần thực hiện
    parameters: Dict[str, Any]     # Arguments cho tool
    priority: str = "medium"       # low | medium | high
    timeout_seconds: int = 30
    success_criteria: str = ""     # "Channel 'general' exists" — explicit
    context: str = ""              # Bối cảnh từ user request
    
    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "target_agent": self.target_agent.value,
            "action": self.action,
            "parameters": self.parameters,
            "priority": self.priority,
            "timeout_seconds": self.timeout_seconds,
            "success_criteria": self.success_criteria,
            "context": self.context,
        }


@dataclass
class TaskResult:
    """
    Contract: Specialist Agent → Orchestrator (response)
    Mọi kết quả đều cùng format — Orchestrator parse dễ dàng.
    """
    task_id: str
    agent: AgentRole
    status: TaskStatus
    output: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    confidence: float = 1.0        # 0.0 → 1.0 — agent tự tin cỡ nào
    execution_time_ms: float = 0.0
    retry_suggested: bool = False
    
    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent": self.agent.value,
            "status": self.status.value,
            "output": self.output,
            "error_message": self.error_message,
            "confidence": self.confidence,
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass
class AgentMessage:
    """
    Contract chung cho mọi message trong hệ thống.
    Dùng cho tracing + audit trail.
    """
    trace_id: str                  # Unique per user request (end-to-end)
    from_agent: AgentRole
    to_agent: AgentRole
    message_type: str              # "task_assignment" | "task_result" | "approval_request"
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "from": self.from_agent.value,
            "to": self.to_agent.value,
            "type": self.message_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }
