# app/agents/__init__.py
"""
Agent layer — 3-mode architecture.

Orchestrator (thin router) → AdminAgent | AssistantAgent
                            ↘ ArchitectAgent (specialist delegate)
"""
from app.agents.orchestrator import OrchestratorAgent
from app.agents.admin_agent import AdminAgent
from app.agents.assistant_agent import AssistantAgent
from app.agents.architect import ArchitectAgent
from app.agents.classifier import IntentClassifier
from app.agents.contracts import AgentRole, TaskStatus, TaskAssignment, TaskResult

__all__ = [
    "OrchestratorAgent",
    "AdminAgent",
    "AssistantAgent",
    "ArchitectAgent",
    "IntentClassifier",
    "AgentRole",
    "TaskStatus",
    "TaskAssignment",
    "TaskResult",
]
