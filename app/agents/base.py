# app/agents/base.py
"""
BaseAgent — abstract base for specialist agents (Architect, etc.)
Provides: tracing, metrics, retry logic, MCP tool execution.

Note: AdminAgent and AssistantAgent do NOT inherit from this.
They are standalone classes with their own patterns.
This base is only for specialist agents that use the TaskAssignment/TaskResult pattern.
"""
import time
import asyncio
import logging
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod

from app.infra.llm.base import LLMProvider
from app.agents.contracts import AgentRole, TaskAssignment, TaskResult, TaskStatus
from app.infra.observability.tracer import Tracer
from app.infra.observability.metrics import metrics

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for specialist agents (Architect, etc.)."""

    def __init__(
        self,
        role: AgentRole,
        llm: LLMProvider,
        tracer: Tracer,
        system_prompt: str = "",
        max_retries: int = 2,
    ):
        self.role = role
        self.llm = llm
        self.tracer = tracer
        self.system_prompt = system_prompt
        self.max_retries = max_retries

    async def execute_task(self, task: TaskAssignment, trace_id: str, guild=None) -> TaskResult:
        """Execute a task with retry logic and tracing."""
        start = time.time()

        for attempt in range(self.max_retries + 1):
            try:
                result = await self._execute(task, trace_id, guild)
                duration = (time.time() - start) * 1000
                result.execution_time_ms = duration

                self.tracer.log_tool_call(
                    trace_id, self.role.value, task.action,
                    task.parameters, result.output, duration,
                    status="ok" if result.status == TaskStatus.SUCCESS else "error",
                )
                return result

            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"[{trace_id}] {self.role.value} retry {attempt+1}: {e}")
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    duration = (time.time() - start) * 1000
                    metrics.count_error("agent_exception", self.role.value)
                    return TaskResult(
                        task_id=task.task_id,
                        agent=self.role,
                        status=TaskStatus.FAILED,
                        error_message=f"Error after {self.max_retries} retries: {str(e)}",
                        execution_time_ms=duration,
                    )

    @abstractmethod
    async def _execute(self, task: TaskAssignment, trace_id: str, guild=None) -> TaskResult:
        """Implement in subclass."""
        ...

    def _log_reasoning(self, trace_id: str, message: str):
        self.tracer.log_reasoning(trace_id, self.role.value, message)
