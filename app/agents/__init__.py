# app/agents/__init__.py
"""
Layer 3 — Agent System.

Architecture:
  OrchestratorAgent (thin router)
    ├── FastTrackExecutor (single action)
    ├── AdminAgent (ReAct loop, multi-step)
    │     └── ArchitectAgent (bulk execution delegate)
    └── AssistantAgent (Q&A, read-only)

Classification: IntentClassifier → FAST_TRACK | ADMIN_COMPLEX | ASSISTANT
"""
from app.agents.orchestrator import OrchestratorAgent
from app.agents.admin_agent import AdminAgent
from app.agents.assistant_agent import AssistantAgent
from app.agents.architect import ArchitectAgent
from app.agents.fast_track import FastTrackExecutor
from app.agents.classifier import IntentClassifier
from app.agents.contracts import (
    AgentRole,
    IntentType,
    TaskStatus,
    TaskAssignment,
    TaskResult,
    PlanStep,
    ExecutionPlan,
)

__all__ = [
    "OrchestratorAgent",
    "AdminAgent",
    "AssistantAgent",
    "ArchitectAgent",
    "FastTrackExecutor",
    "IntentClassifier",
    "AgentRole",
    "IntentType",
    "TaskStatus",
    "TaskAssignment",
    "TaskResult",
    "PlanStep",
    "ExecutionPlan",
]
