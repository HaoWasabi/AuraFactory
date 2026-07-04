# agents/base_agent.py
"""
Agentic AI Lens Principle 1: Decompose into specialized, bounded agents
Agentic AI Lens Principle 3: Treat agent behavior as code

Base class cho mọi agent — enforce:
- Scope (allowed actions)
- Tracing (mọi action đều logged)
- Permission check (trước khi execute tool)
- Retry policy (Reliability pillar)
"""
import time
import json
from typing import Dict, Any, List, Optional
from providers.base import LLMProvider
from schemas.contracts import AgentRole, TaskAssignment, TaskResult, TaskStatus
from schemas.permissions import check_permission, get_risk_level, requires_approval, RiskLevel
from observability.tracer import Tracer


class BaseAgent:
    """
    Base class — mọi specialist agent kế thừa từ đây.
    Đảm bảo Well-Architected principles tự động applied.
    """
    
    def __init__(
        self,
        role: AgentRole,
        llm: LLMProvider,
        tracer: Tracer,
        system_prompt: str = "",
        tools: Optional[List[Dict]] = None,
        max_retries: int = 2,
    ):
        self.role = role
        self.llm = llm
        self.tracer = tracer
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.max_retries = max_retries
    
    async def execute_task(self, task: TaskAssignment, trace_id: str, guild=None, skip_approval: bool = False) -> TaskResult:
        """
        Entry point chính — tất cả tasks đi qua đây.
        Flow: Permission Check → Approval Gate → Execute → Trace Result
        skip_approval=True khi đã được human approve rồi (bypass gate)
        """
        start = time.time()
        
        # Normalize action name: "discord_channel.delete_channel" → "delete_channel"
        if "." in task.action:
            task.action = task.action.split(".")[-1]
        
        # 1. Permission check (Security: Least privilege)
        if not check_permission(self.role.value, task.action):
            self.tracer.log_error(
                trace_id, self.role.value,
                f"Permission denied: {self.role.value} cannot perform {task.action}"
            )
            return TaskResult(
                task_id=task.task_id,
                agent=self.role,
                status=TaskStatus.FAILED,
                error_message=f"Agent '{self.role.value}' không có quyền thực hiện '{task.action}'",
            )
        
        # 2. Approval gate (Security: Human oversight) — skip nếu đã approved
        if not skip_approval and requires_approval(task.action):
            self.tracer.log_approval(
                trace_id, self.role.value,
                action=task.action, approved=False, approver="pending"
            )
            return TaskResult(
                task_id=task.task_id,
                agent=self.role,
                status=TaskStatus.NEEDS_APPROVAL,
                output={"action": task.action, "parameters": task.parameters},
                error_message=f"Action '{task.action}' requires admin approval (risk: {get_risk_level(task.action).value})",
            )
        
        # 3. Execute with retry (Reliability: Auto-recover)
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                result = await self._execute(task, trace_id, guild)
                result.execution_time_ms = (time.time() - start) * 1000
                return result
            except Exception as e:
                last_error = str(e)
                self.tracer.log_error(
                    trace_id, self.role.value,
                    f"Attempt {attempt + 1}/{self.max_retries + 1} failed: {last_error}"
                )
                if attempt < self.max_retries:
                    # Exponential backoff (Reliability)
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
        
        # All retries exhausted
        return TaskResult(
            task_id=task.task_id,
            agent=self.role,
            status=TaskStatus.FAILED,
            error_message=f"Failed after {self.max_retries + 1} attempts: {last_error}",
            execution_time_ms=(time.time() - start) * 1000,
            retry_suggested=False,
        )
    
    async def _execute(self, task: TaskAssignment, trace_id: str, guild=None) -> TaskResult:
        """
        Override này trong mỗi specialist agent.
        Base implementation dùng LLM + function calling.
        """
        raise NotImplementedError(f"Agent {self.role.value} must implement _execute()")
    
    def get_tool_definitions(self) -> List[Dict]:
        """Trả về tool definitions cho LLM function calling"""
        return self.tools
    
    def _log_reasoning(self, trace_id: str, thought: str):
        """Shortcut để log reasoning"""
        self.tracer.log_reasoning(trace_id, self.role.value, thought)
    
    def _log_tool_call(self, trace_id: str, tool_name: str, tool_input: Dict, tool_output: Any, duration_ms: float):
        """Shortcut để log tool call"""
        self.tracer.log_tool_call(
            trace_id, self.role.value,
            tool_name, tool_input, tool_output, duration_ms
        )
