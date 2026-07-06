# app/agents/architect.py
"""
Architect Agent — Discord workspace structure specialist.
Called by AdminAgent via delegation when task involves 3+ operations.
Runs its own mini ReAct loop (max 5 iterations).
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from app.agents.base import BaseAgent
from app.agents.contracts import AgentRole, TaskAssignment, TaskResult, TaskStatus
from app.infra.llm.base import LLMProvider
from app.infra.observability.tracer import Tracer
from app.infra.observability.metrics import metrics
from app.mcp import MCPClient

logger = logging.getLogger(__name__)

MAX_SUB_ITERATIONS = 5


def _load_prompt() -> str:
    """Load architect system prompt."""
    path = Path(__file__).parent.parent.parent / "prompts" / "architect.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "You are the Architect Agent. Execute Discord structure operations."


class ArchitectAgent(BaseAgent):
    """
    Architect Specialist — handles complex multi-step Discord operations.

    Called by AdminAgent._delegate("architect", ...) when task is complex.
    Runs its own mini ReAct loop (max 5 iterations).

    Examples: batch channel creation, full server structure setup,
    reorganize workspace, permission auditing.
    """

    def __init__(self, llm: LLMProvider, tracer: Tracer):
        super().__init__(
            role=AgentRole.ARCHITECT,
            llm=llm,
            tracer=tracer,
            system_prompt=_load_prompt(),
            max_retries=2,
        )
        self._mcp: Optional[MCPClient] = None

    def set_mcp_client(self, mcp_client: MCPClient) -> None:
        """Inject MCP client."""
        self._mcp = mcp_client

    async def run_task(
        self,
        task_description: str,
        trace_id: str,
        guild_id: int = None,
        guild=None,
    ) -> Dict[str, Any]:
        """
        Run a delegated task as a specialist sub-loop.
        Called by AdminAgent._delegate().
        """
        if not self._mcp:
            return {"success": False, "message": "MCP client not configured"}

        # Build tools block
        tools = self._mcp.to_llm_format()
        tools_block = "\n".join(f"- {t['name']}: {t['description']}" for t in tools)

        sub_system = f"""{self.system_prompt}

You are executing a delegated task. Use ReAct format.
ONE tool per turn. Max {MAX_SUB_ITERATIONS} turns.

Respond with JSON only:
{{"thought": "reasoning (English)", "action": "tool_name", "action_input": {{...}}}}
OR when done:
{{"thought": "summary (English)", "action": "FINISH", "message": "result for user"}}

Available Discord tools:
{tools_block}"""

        messages = [{"role": "user", "content": f"Task: {task_description}"}]
        results = []

        for i in range(MAX_SUB_ITERATIONS):
            response = await self.llm.generate(
                messages=messages,
                system_prompt=sub_system if i == 0 else None,
                temperature=0.2,
                max_tokens=600,
            )

            metrics.count_request(response.model, "architect", "success")
            metrics.count_tokens(response.model, response.input_tokens, response.output_tokens)

            parsed = self._parse_response(response.content)
            thought = parsed.get("thought", "")
            action = parsed.get("action", "FINISH")
            action_input = parsed.get("action_input", {})

            self.tracer.log_reasoning(
                trace_id, "architect", f"[Sub {i + 1}] {thought[:100]} | {action}"
            )

            # FINISH
            if action == "FINISH":
                results.append({"status": "done", "message": parsed.get("message", thought)})
                break

            # Execute tool via MCP
            try:
                tool_result = await self._mcp.call_tool(action, action_input)
                if isinstance(tool_result, dict) and tool_result.get("success", True):
                    obs = f"[OK] {action}: {self._summarize(tool_result)}"
                    results.append({"status": "success", "action": action})
                else:
                    error = tool_result.get("error", str(tool_result)) if isinstance(tool_result, dict) else str(tool_result)
                    obs = f"[FAIL] {action}: {error}"
                    results.append({"status": "failed", "action": action, "error": error})
            except Exception as e:
                obs = f"[FAIL] {action}: {str(e)}"
                results.append({"status": "failed", "action": action, "error": str(e)})

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": f"Observation: {obs}"})

        # Consolidate
        success_count = sum(1 for r in results if r.get("status") == "success")
        fail_count = sum(1 for r in results if r.get("status") == "failed")

        return {
            "success": fail_count == 0,
            "total_actions": len(results),
            "success_count": success_count,
            "fail_count": fail_count,
            "message": results[-1].get("message", "Task completed.") if results else "No actions taken",
        }

    # ============================================================
    # BaseAgent interface (backward compat — for direct task execution)
    # ============================================================

    async def _execute(self, task: TaskAssignment, trace_id: str, guild=None) -> TaskResult:
        """Execute a single task via MCP (backward compat)."""
        if not self._mcp:
            return TaskResult(
                task_id=task.task_id, agent=self.role, status=TaskStatus.FAILED,
                error_message="MCP client not configured",
            )

        try:
            result = await self._mcp.call_tool(task.action, task.parameters)
            return TaskResult(
                task_id=task.task_id, agent=self.role, status=TaskStatus.SUCCESS,
                output=result if isinstance(result, dict) else {"result": str(result)},
            )
        except Exception as e:
            return TaskResult(
                task_id=task.task_id, agent=self.role, status=TaskStatus.FAILED,
                error_message=str(e),
            )

    # ============================================================
    # Helpers
    # ============================================================

    def _parse_response(self, content: str) -> Dict[str, Any]:
        """Parse LLM JSON response."""
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            if "{" in text:
                start = text.index("{")
                end = text.rindex("}") + 1
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return {"thought": "Parse error", "action": "FINISH", "message": content}

    def _summarize(self, result, max_len: int = 150) -> str:
        """Summarize tool result for observation."""
        if not result:
            return "Done"
        if isinstance(result, dict):
            if "message" in result:
                return str(result["message"])[:max_len]
            return json.dumps(result, ensure_ascii=False, default=str)[:max_len]
        return str(result)[:max_len]
