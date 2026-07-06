# app/agents/architect.py
"""
ArchitectAgent — Bulk execution specialist.

Called ONLY by AdminAgent (never by Orchestrator directly).
Executes pre-validated plan steps sequentially via MCP.
Reports progress: "Đã tạo 3/9 channel..."
If one step fails: stop, report which steps done/failed, allow resume.
"""
import json
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent, LLM_OVERLOAD_MESSAGE
from app.agents.contracts import (
    AgentRole,
    TaskAssignment,
    TaskResult,
    PlanStep,
    ExecutionPlan,
)

logger = logging.getLogger(__name__)

# Configuration
MAX_BULK_STEPS: int = 20
STEP_TIMEOUT_SECONDS: int = 30
PROGRESS_REPORT_INTERVAL: int = 3


class ArchitectAgent(BaseAgent):
    """
    Architect Agent — bulk execution specialist.

    Called ONLY by AdminAgent when task has ≥5 steps.
    Never called directly by Orchestrator.

    Responsibilities:
    - Execute pre-validated plan steps sequentially via MCP.
    - Report progress every 3 steps.
    - On failure: stop, report completed/failed steps, allow resume.
    - Generate execution plan from LLM if task is descriptive.
    """

    def __init__(
        self,
        llm: Any,
        mcp_client: Any = None,
        memory: Any = None,
        knowledge_store: Any = None,
        settings: Optional[Dict[str, Any]] = None,
        skill_registry: Any = None,
    ) -> None:
        super().__init__(
            llm=llm,
            mcp_client=mcp_client,
            memory=memory,
            knowledge_store=knowledge_store,
            settings=settings,
            skill_registry=skill_registry,
        )

    # ============================================================
    # MAIN EXECUTE
    # ============================================================

    async def execute(self, task: TaskAssignment) -> TaskResult:
        """
        Execute a bulk task.

        If task contains a structured plan (list of steps), executes directly.
        If task is a text description, generates plan via LLM first.

        Args:
            task: TaskAssignment from AdminAgent delegation.

        Returns:
            TaskResult with progress report.
        """
        trace_id = task.trace_id
        guild_id = task.guild_id

        logger.info(f"[{trace_id}] ArchitectAgent executing bulk task")

        # Check if task.context contains a pre-built plan
        plan_steps = task.context.get("plan_steps") if isinstance(task.context, dict) else None

        if plan_steps and isinstance(plan_steps, list):
            # Execute pre-built plan directly
            plan = self._build_plan_from_steps(plan_steps)
        else:
            # Generate plan from task description via LLM
            description = task.prompt if hasattr(task, "prompt") else str(task.message)
            plan = await self._generate_plan(description, guild_id, trace_id)

        if not plan or not plan.steps:
            return TaskResult(
                trace_id=trace_id,
                content="❌ Không thể tạo kế hoạch thực thi từ yêu cầu.",
                status="failed",
            )

        # Execute the plan
        return await self._execute_plan(plan, trace_id, guild_id)

    # ============================================================
    # PLAN GENERATION
    # ============================================================

    async def _generate_plan(
        self, description: str, guild_id: Optional[int], trace_id: str
    ) -> Optional[ExecutionPlan]:
        """
        Generate an ExecutionPlan from a text description using LLM.

        Returns:
            ExecutionPlan with steps, or None if generation fails.
        """
        server_context = await self._get_server_context(guild_id)
        tools_info = self._get_available_tools_info()

        plan_prompt = f"""Generate an execution plan as a JSON array of steps.
Each step: {{"action": "description", "tool_name": "tool", "params": {{}}, "risk_level": "low|medium|high|critical"}}

Available tools:
{tools_info}

Server context: {server_context}

Task: {description}

Return JSON array only:"""

        response = await self._call_llm(
            prompt=plan_prompt,
            temperature=0.1,
            max_tokens=1500,
        )

        if not response:
            return None

        # Parse plan from LLM output
        return self._parse_plan_response(response.content)

    def _parse_plan_response(self, raw: str) -> Optional[ExecutionPlan]:
        """Parse LLM output into ExecutionPlan."""
        text = raw.strip()

        # Strip code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            if "[" in text:
                start = text.index("[")
                end = text.rindex("]") + 1
                steps_data = json.loads(text[start:end])

                if isinstance(steps_data, list):
                    plan = ExecutionPlan()
                    for step_data in steps_data[:MAX_BULK_STEPS]:
                        if isinstance(step_data, dict):
                            plan.steps.append(PlanStep(
                                action=step_data.get("action", ""),
                                tool_name=step_data.get("tool_name", step_data.get("tool", "")),
                                params=step_data.get("params", {}),
                                risk_level=step_data.get("risk_level", "low"),
                            ))
                    plan.compute_risk()
                    return plan
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse plan JSON: {e}")

        return None

    def _build_plan_from_steps(self, steps_data: List[Dict[str, Any]]) -> ExecutionPlan:
        """Build ExecutionPlan from pre-built step dictionaries."""
        plan = ExecutionPlan()
        for step_data in steps_data[:MAX_BULK_STEPS]:
            plan.steps.append(PlanStep(
                action=step_data.get("action", ""),
                tool_name=step_data.get("tool_name", step_data.get("tool", "")),
                params=step_data.get("params", {}),
                risk_level=step_data.get("risk_level", "low"),
            ))
        plan.compute_risk()
        return plan

    # ============================================================
    # PLAN EXECUTION
    # ============================================================

    async def _execute_plan(
        self, plan: ExecutionPlan, trace_id: str, guild_id: Optional[int]
    ) -> TaskResult:
        """
        Execute plan steps sequentially.
        Reports progress every PROGRESS_REPORT_INTERVAL steps.
        On failure: stops and reports status.
        """
        total_steps = plan.step_count
        tools_called: List[str] = []
        progress_messages: List[str] = []

        logger.info(
            f"[{trace_id}] Executing plan: {total_steps} steps, "
            f"risk={plan.total_risk}"
        )

        for i, step in enumerate(plan.steps):
            step.status = "executing"

            # Inject guild_id into params
            params = dict(step.params)
            if guild_id and "guild_id" not in params:
                params["guild_id"] = guild_id

            # Execute step
            try:
                result = await asyncio.wait_for(
                    self._mcp_client.call_tool(step.tool_name, params),
                    timeout=STEP_TIMEOUT_SECONDS,
                )

                # Check for failure
                if isinstance(result, dict) and result.get("success") is False:
                    step.status = "failed"
                    step.error = result.get("error", "Unknown error")
                    logger.error(
                        f"[{trace_id}] Step {i + 1}/{total_steps} FAILED: "
                        f"{step.tool_name}: {step.error}"
                    )
                    # Stop execution on failure
                    break
                else:
                    step.status = "done"
                    step.result = str(result)[:100] if result else "OK"
                    tools_called.append(step.tool_name)

            except asyncio.TimeoutError:
                step.status = "failed"
                step.error = f"Timeout after {STEP_TIMEOUT_SECONDS}s"
                break
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                break

            # Progress reporting
            completed = i + 1
            if completed % PROGRESS_REPORT_INTERVAL == 0 and completed < total_steps:
                progress_msg = f"📊 Đã hoàn thành {completed}/{total_steps} bước..."
                progress_messages.append(progress_msg)
                logger.info(f"[{trace_id}] Progress: {completed}/{total_steps}")

        # ─── Build final report ───
        completed_count = plan.completed_steps
        failed_count = plan.failed_steps
        pending_count = total_steps - completed_count - failed_count

        report_lines: List[str] = []

        if failed_count == 0:
            report_lines.append(f"✅ Đã hoàn thành tất cả {total_steps} bước!")
        else:
            report_lines.append(
                f"⚠️ Đã hoàn thành {completed_count}/{total_steps} bước. "
                f"{failed_count} bước thất bại."
            )

        # Detail completed steps
        for step in plan.steps:
            if step.status == "done":
                report_lines.append(f"  ✅ {step.action}")
            elif step.status == "failed":
                report_lines.append(f"  ❌ {step.action}: {step.error}")

        if pending_count > 0:
            report_lines.append(f"\n📋 Còn {pending_count} bước chưa thực hiện.")

        content = "\n".join(report_lines)
        status = "success" if failed_count == 0 else "failed"

        return TaskResult(
            trace_id=trace_id,
            content=content,
            status=status,
            tools_called=tools_called,
            iterations=completed_count,
            metadata={
                "total_steps": total_steps,
                "completed": completed_count,
                "failed": failed_count,
                "pending": pending_count,
                "plan": plan.to_dict(),
            },
        )

    # ============================================================
    # HELPERS
    # ============================================================

    async def _get_server_context(self, guild_id: Optional[int]) -> str:
        """Get server context from knowledge store."""
        if not guild_id or not self._knowledge_store:
            return "No server context."
        try:
            return await self._knowledge_store.get_summary_string(guild_id)
        except Exception:
            return "No server context."

    def _get_available_tools_info(self) -> str:
        """Get tool info for plan generation prompt."""
        if self._skill_registry and hasattr(self._skill_registry, "get_all_tools"):
            tools = self._skill_registry.get_all_tools()
            if tools:
                lines = []
                for t in tools:
                    name = getattr(t, "name", str(t))
                    desc = getattr(t, "description", "")
                    lines.append(f"- {name}: {desc}")
                return "\n".join(lines)

        if self._mcp_client and hasattr(self._mcp_client, "to_llm_format"):
            tools = self._mcp_client.to_llm_format()
            return "\n".join(f"- {t['name']}: {t.get('description', '')}" for t in tools)

        return "No tools info available."

    # ============================================================
    # BASE AGENT INTERFACE
    # ============================================================

    def get_agent_role(self) -> AgentRole:
        return AgentRole.ARCHITECT
