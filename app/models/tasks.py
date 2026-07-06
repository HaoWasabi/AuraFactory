# app/models/tasks.py
"""
Task and Agent models — re-exports from agents/contracts.py.
Kept for backward compatibility with any external imports.
"""
from app.agents.contracts import AgentRole, TaskStatus, TaskAssignment, TaskResult

__all__ = ["AgentRole", "TaskStatus", "TaskAssignment", "TaskResult"]
