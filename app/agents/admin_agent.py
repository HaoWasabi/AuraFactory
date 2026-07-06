# app/agents/admin_agent.py
"""
AdminAgent — ReAct loop for complex multi-step admin operations.
Pattern: Thought → Action → Observation → repeat (max 5 iterations).
Generates ExecutionPlan for multi-step requests.
HITL gate: if plan contains HIGH/CRITICAL risk → store in approvals table → return approval_required=True.
For bulk ops (≥5 steps): delegate to ArchitectAgent.
Progress reporting: if >5 steps, report every 3 steps.
"""
import json
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4
from app.agents.base import BaseAgent, LLM_OVERLOAD_MESSAGE
from app.agents.contracts import (
    AgentRole,
    IntentType,
    TaskAssignment,
    TaskResult,
    PlanStep,
    ExecutionPlan,
)

logger = logging.getLogger(__name__)

# Configuration
MAX_REACT_ITERATIONS: int = 5
LOOP_TIMEOUT_SECONDS: int = 45
APPROVAL_TTL_MINUTES: int = 30
BULK_THRESHOLD: int = 5  # ≥5 steps → delegate to Architect
PROGRESS_REPORT_INTERVAL: int = 3  # Report every N steps


# ============================================================
# REACT SYSTEM PROMPT
# ============================================================

ADMIN_REACT_PROMPT: str = """You are AuraFactory AdminAgent — executing Discord server management commands via ReAct pattern.

Each turn you MUST respond with EXACTLY this format (no other text):

Thought: <your reasoning about what to do next — always in English>
Action: <tool_name OR FINISH OR CLARIFY>
Action Input: <JSON params for the tool, or message for FINISH/CLARIFY>

## Terminal Actions:
- Action: FINISH → Action Input: {{"message": "response to show user (in user's language)"}}
- Action: CLARIFY → Action Input: {{"message": "question to ask user (in user's language)"}}

## Rules:
- ONE action per turn only.
- Observe the result before deciding next action.
- If a tool fails, try alternative or FINISH with error explanation.
- Max {max_iter} turns allowed.
- Keep messages under 2000 characters.

## Risk Assessment:
- LOW/MEDIUM: Execute immediately.
- HIGH/CRITICAL: List the risky steps and use FINISH with approval_required flag.

## Server Context:
{server_context}

## Available Tools:
{tools_block}

## Language:
- "Thought" field: always English.
- "Action Input.message" field: same language as user's message.
"""


class AdminAgent(BaseAgent):
    """
    AdminAgent — handles complex admin operations via ReAct loop.

    Responsibilities:
    - Setup commands (server structure creation)
    - Moderation (kick/ban/mute with reasoning)
    - Multi-tool tasks (create channels + roles + permissions)
    - HITL approval for dangerous operations
    - Delegation to ArchitectAgent for bulk ops

    ReAct Loop:
    - Parse LLM response for "Thought:", "Action:", "Action Input:" patterns
    - Execute tool via MCP
    - Feed observation back to LLM
    - Repeat until FINISH or max iterations
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
        self._architect: Optional[Any] = None
        self._db: Any = None  # For approval persistence

    def set_architect(self, architect: Any) -> None:
        """Inject ArchitectAgent for bulk delegation."""
        self._architect = architect

    def set_db(self, db: Any) -> None:
        """Inject database connection for approvals table."""
        self._db = db

    # ============================================================
    # MAIN EXECUTE
    # ============================================================

    async def execute(self, task: TaskAssignment) -> TaskResult:
        """
        Execute a complex admin task via ReAct loop.

        Args:
            task: TaskAssignment with message, context, user role.

        Returns:
            TaskResult with content, tools called, and approval status.
        """
        trace_id = task.trace_id
        prompt = task.prompt
        guild_id = task.guild_id

        logger.info(f"[{trace_id}] AdminAgent executing: '{prompt[:60]}...'")

        # Get server context for the system prompt
        server_context = await self._get_server_context(guild_id)
        tools_block = self._build_tools_block()

        # Build system prompt
        system_prompt = ADMIN_REACT_PROMPT.format(
            max_iter=MAX_REACT_ITERATIONS,
            server_context=server_context,
            tools_block=tools_block,
        )

        # Run ReAct loop
        return await self._react_loop(
            prompt=prompt,
            system_prompt=system_prompt,
            trace_id=trace_id,
            guild_id=guild_id,
        )

    # ============================================================
    # REACT LOOP
    # ============================================================

    async def _react_loop(
        self,
        prompt: str,
        system_prompt: str,
        trace_id: str,
        guild_id: Optional[int],
    ) -> TaskResult:
        """
        ReAct loop: Thought → Action → Observation → repeat.
        Max MAX_REACT_ITERATIONS iterations.
        """
        messages: List[Dict[str, str]] = [
            {"role": "user", "content": prompt},
        ]
        tools_called: List[str] = []
        total_input_tokens: int = 0
        total_output_tokens: int = 0

        for iteration in range(MAX_REACT_ITERATIONS):
            # Call LLM
            response = await self._call_llm(
                prompt="",
                messages=messages,
                system_prompt=system_prompt if iteration == 0 else None,
                temperature=0.2,
                max_tokens=1200,
            )

            if not response:
                return self._error_result(trace_id, LLM_OVERLOAD_MESSAGE)

            raw_output = response.content.strip()
            total_input_tokens += response.input_tokens
            total_output_tokens += response.output_tokens

            # Parse ReAct format
            parsed = self._parse_react_output(raw_output)
            if not parsed:
                logger.warning(f"[{trace_id}] Failed to parse ReAct output at iter {iteration}")
                # Give LLM another chance
                messages.append({"role": "assistant", "content": raw_output})
                messages.append({
                    "role": "user",
                    "content": (
                        "Error: Your response must follow the exact format:\n"
                        "Thought: <reasoning>\nAction: <tool_name>\nAction Input: <json>\n"
                        "Try again."
                    ),
                })
                continue

            thought = parsed["thought"]
            action = parsed["action"]
            action_input = parsed["action_input"]

            logger.info(
                f"[{trace_id}] ReAct iter {iteration}: "
                f"thought='{thought[:80]}...' action={action}"
            )

            # ─── Terminal: FINISH ───
            if action.upper() == "FINISH":
                message = action_input.get("message", thought) if isinstance(action_input, dict) else str(action_input)
                cost_info = self._log_cost(trace_id, total_input_tokens, total_output_tokens, response.model)
                return TaskResult(
                    trace_id=trace_id,
                    content=message,
                    status="success",
                    tools_called=tools_called,
                    cost=cost_info,
                    iterations=iteration + 1,
                )

            # ─── Terminal: CLARIFY ───
            if action.upper() == "CLARIFY":
                message = action_input.get("message", thought) if isinstance(action_input, dict) else str(action_input)
                return TaskResult(
                    trace_id=trace_id,
                    content=message,
                    status="success",
                    tools_called=tools_called,
                    iterations=iteration + 1,
                    metadata={"needs_clarification": True},
                )

            # ─── Check risk level ───
            risk = self._get_risk_level(action)
            if risk in ("high", "critical"):
                # HITL gate — store pending approval
                approval_id = await self._store_approval(
                    trace_id=trace_id,
                    guild_id=guild_id,
                    action=action,
                    params=action_input if isinstance(action_input, dict) else {},
                    thought=thought,
                )
                return TaskResult(
                    trace_id=trace_id,
                    content=(
                        f"⚠️ Thao tác **{action}** có rủi ro {'cao' if risk == 'high' else 'rất cao'}. "
                        f"Cần xác nhận từ admin.\n"
                        f"Approval ID: `{approval_id}`\n"
                        f"⏱️ Hết hạn sau {APPROVAL_TTL_MINUTES} phút."
                    ),
                    status="needs_approval",
                    approval_required=True,
                    approval_id=approval_id,
                    tools_called=tools_called,
                    iterations=iteration + 1,
                )

            # ─── Check bulk threshold → delegate to Architect ───
            if self._should_delegate_to_architect(action_input):
                return await self._delegate_to_architect(
                    task_description=f"{thought}\nAction: {action}\nParams: {json.dumps(action_input, ensure_ascii=False)}",
                    trace_id=trace_id,
                    guild_id=guild_id,
                )

            # ─── Execute tool via MCP ───
            params = action_input if isinstance(action_input, dict) else {}
            params = self._inject_guild_id(params, guild_id)
            observation = await self._execute_tool(action, params, trace_id)
            tools_called.append(action)

            # Append to messages for next iteration
            messages.append({"role": "assistant", "content": raw_output})
            messages.append({"role": "user", "content": f"Observation: {observation}"})

        # Max iterations reached
        cost_info = self._log_cost(trace_id, total_input_tokens, total_output_tokens, "unknown")
        return TaskResult(
            trace_id=trace_id,
            content="⚠️ Đã đạt giới hạn xử lý. Một số thao tác có thể chưa hoàn thành.",
            status="success",
            tools_called=tools_called,
            cost=cost_info,
            iterations=MAX_REACT_ITERATIONS,
        )

    # ============================================================
    # HITL: RESUME APPROVED PLAN
    # ============================================================

    async def resume_plan(self, approval_id: str, guild_id: Optional[int] = None) -> TaskResult:
        """
        Resume execution of an approved plan.
        Called after admin approves a pending high-risk operation.

        Args:
            approval_id: The approval ID from the pending plan.
            guild_id: Guild context for tool execution.

        Returns:
            TaskResult with execution outcome.
        """
        # Load plan from DB
        plan_data = await self._load_approval(approval_id)
        if not plan_data:
            return TaskResult(
                trace_id=approval_id,
                content="❌ Không tìm thấy plan hoặc đã hết hạn.",
                status="failed",
            )

        trace_id = plan_data.get("trace_id", approval_id)
        action = plan_data.get("action", "")
        params = plan_data.get("params", {})

        logger.info(f"[{trace_id}] Resuming approved plan: {action}")

        # Execute the previously blocked tool
        params = self._inject_guild_id(params, guild_id)
        observation = await self._execute_tool(action, params, trace_id)

        # Clean up approval
        await self._delete_approval(approval_id)

        if "Error" in str(observation):
            return TaskResult(
                trace_id=trace_id,
                content=f"❌ Thực hiện thất bại: {observation}",
                status="failed",
                tools_called=[action],
            )

        return TaskResult(
            trace_id=trace_id,
            content=f"✅ Đã thực hiện **{action}** sau khi được duyệt.",
            status="success",
            tools_called=[action],
        )

    # ============================================================
    # REACT PARSER
    # ============================================================

    def _parse_react_output(self, raw: str) -> Optional[Dict[str, Any]]:
        """
        Parse LLM ReAct output for Thought:, Action:, Action Input: patterns.

        Expected format:
            Thought: <reasoning>
            Action: <tool_name>
            Action Input: <json or text>

        Returns:
            Dict with {thought, action, action_input} or None if parse fails.
        """
        thought = ""
        action = ""
        action_input: Any = {}

        lines = raw.strip().split("\n")

        # Extract Thought
        thought_lines: List[str] = []
        action_line_idx = -1

        for i, line in enumerate(lines):
            if line.strip().startswith("Thought:"):
                thought = line.split("Thought:", 1)[1].strip()
            elif line.strip().startswith("Action:"):
                action = line.split("Action:", 1)[1].strip()
                action_line_idx = i
            elif line.strip().startswith("Action Input:"):
                # Everything after "Action Input:" is the input
                input_text = line.split("Action Input:", 1)[1].strip()
                # Might continue on next lines
                remaining_lines = lines[i + 1:]
                full_input = input_text + "\n" + "\n".join(remaining_lines)
                full_input = full_input.strip()

                # Try to parse as JSON
                try:
                    if "{" in full_input:
                        start = full_input.index("{")
                        end = full_input.rindex("}") + 1
                        action_input = json.loads(full_input[start:end])
                    else:
                        action_input = {"message": full_input}
                except (json.JSONDecodeError, ValueError):
                    action_input = {"message": full_input}
                break

        # Fallback: try parsing as JSON if the output is raw JSON
        if not action and "{" in raw:
            try:
                start = raw.index("{")
                end = raw.rindex("}") + 1
                parsed_json = json.loads(raw[start:end])
                if "action" in parsed_json:
                    return {
                        "thought": parsed_json.get("thought", ""),
                        "action": parsed_json["action"],
                        "action_input": parsed_json.get("action_input", parsed_json.get("message", {})),
                    }
            except (json.JSONDecodeError, ValueError):
                pass

        if not action:
            return None

        return {
            "thought": thought,
            "action": action,
            "action_input": action_input,
        }

    # ============================================================
    # TOOL EXECUTION
    # ============================================================

    async def _execute_tool(
        self, tool_name: str, params: Dict[str, Any], trace_id: str
    ) -> str:
        """Execute a tool via MCP client with timeout."""
        if not self._mcp_client:
            return "Error: MCP client not configured"

        try:
            result = await asyncio.wait_for(
                self._mcp_client.call_tool(tool_name, params),
                timeout=LOOP_TIMEOUT_SECONDS,
            )

            # Format observation
            if isinstance(result, dict):
                if result.get("success") is False:
                    return f"Error: {result.get('error', 'Unknown error')}"
                # Summarize successful result
                msg = result.get("message", json.dumps(result, ensure_ascii=False, default=str))
                return f"OK: {str(msg)[:200]}"
            return f"OK: {str(result)[:200]}"

        except asyncio.TimeoutError:
            return f"Error: Tool '{tool_name}' timed out after {LOOP_TIMEOUT_SECONDS}s"
        except Exception as e:
            return f"Error: {str(e)}"

    # ============================================================
    # ARCHITECT DELEGATION
    # ============================================================

    def _should_delegate_to_architect(self, action_input: Any) -> bool:
        """Check if the task should be delegated to ArchitectAgent."""
        if not self._architect:
            return False
        if not isinstance(action_input, dict):
            return False
        # Check if it's a bulk operation with many steps
        steps = action_input.get("steps", [])
        if isinstance(steps, list) and len(steps) >= BULK_THRESHOLD:
            return True
        return False

    async def _delegate_to_architect(
        self, task_description: str, trace_id: str, guild_id: Optional[int]
    ) -> TaskResult:
        """Delegate bulk execution to ArchitectAgent."""
        if not self._architect:
            return self._error_result(trace_id, "Architect agent not available")

        logger.info(f"[{trace_id}] Delegating to ArchitectAgent (bulk operation)")

        # Create task for architect
        task = TaskAssignment(
            trace_id=trace_id,
            intent=IntentType.ADMIN_COMPLEX,
            agent_role=AgentRole.ARCHITECT,
            message=task_description,
            guild_id=guild_id,
            context={"delegated_from": "admin_agent"},
        )
        return await self._architect.execute(task)

    # ============================================================
    # HITL: APPROVAL PERSISTENCE
    # ============================================================

    async def _store_approval(
        self,
        trace_id: str,
        guild_id: Optional[int],
        action: str,
        params: Dict[str, Any],
        thought: str,
    ) -> str:
        """
        Store pending approval in DB `approvals` table with TTL 30 min.
        Returns approval_id.
        """
        approval_id = str(uuid4())[:12]

        if self._db:
            try:
                await self._db.execute(
                    """
                    INSERT INTO approvals (approval_id, trace_id, guild_id, action, params, thought, expires_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW() + INTERVAL '30 minutes')
                    """,
                    approval_id, trace_id, guild_id,
                    action, json.dumps(params, ensure_ascii=False), thought,
                )
            except Exception as e:
                logger.error(f"Failed to store approval: {e}")
        else:
            # In-memory fallback (development only)
            if not hasattr(self, "_pending_approvals"):
                self._pending_approvals: Dict[str, Dict] = {}
            self._pending_approvals[approval_id] = {
                "trace_id": trace_id,
                "guild_id": guild_id,
                "action": action,
                "params": params,
                "thought": thought,
                "created_at": time.time(),
            }

        logger.info(f"[{trace_id}] Stored approval {approval_id}: action={action}")
        return approval_id

    async def _load_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Load pending approval from DB or memory."""
        if self._db:
            try:
                row = await self._db.fetchrow(
                    """
                    SELECT trace_id, guild_id, action, params, thought
                    FROM approvals
                    WHERE approval_id = $1 AND expires_at > NOW()
                    """,
                    approval_id,
                )
                if row:
                    return {
                        "trace_id": row["trace_id"],
                        "guild_id": row["guild_id"],
                        "action": row["action"],
                        "params": json.loads(row["params"]) if row["params"] else {},
                        "thought": row["thought"],
                    }
            except Exception as e:
                logger.error(f"Failed to load approval: {e}")
        else:
            # In-memory fallback
            if hasattr(self, "_pending_approvals"):
                data = self._pending_approvals.get(approval_id)
                if data:
                    # Check TTL (30 min)
                    if time.time() - data["created_at"] < APPROVAL_TTL_MINUTES * 60:
                        return data
                    else:
                        del self._pending_approvals[approval_id]
        return None

    async def _delete_approval(self, approval_id: str) -> None:
        """Remove approval after execution."""
        if self._db:
            try:
                await self._db.execute(
                    "DELETE FROM approvals WHERE approval_id = $1",
                    approval_id,
                )
            except Exception as e:
                logger.error(f"Failed to delete approval: {e}")
        else:
            if hasattr(self, "_pending_approvals"):
                self._pending_approvals.pop(approval_id, None)

    # ============================================================
    # HELPERS
    # ============================================================

    def _build_tools_block(self) -> str:
        """Build tools list for LLM prompt from skill registry or MCP."""
        if self._skill_registry and hasattr(self._skill_registry, "get_all_tools"):
            tools = self._skill_registry.get_all_tools()
            if tools:
                lines = []
                for t in tools:
                    name = getattr(t, "name", str(t))
                    risk = getattr(t, "risk_level", "low")
                    desc = getattr(t, "description", "")
                    lines.append(f"- {name} [{risk}]: {desc}")
                return "\n".join(lines)

        # Fallback: get from MCP client
        if self._mcp_client and hasattr(self._mcp_client, "to_llm_format"):
            tools = self._mcp_client.to_llm_format()
            return "\n".join(f"- {t['name']}: {t.get('description', '')}" for t in tools)

        return "No tools available."

    def _get_risk_level(self, tool_name: str) -> str:
        """Get risk level for a tool."""
        if self._skill_registry and hasattr(self._skill_registry, "get_risk_level"):
            return self._skill_registry.get_risk_level(tool_name)
        # Default high-risk tools
        high_risk = {"kick_member", "ban_member", "delete_channel", "delete_role"}
        critical = {"delete_guild", "prune_members"}
        if tool_name in critical:
            return "critical"
        if tool_name in high_risk:
            return "high"
        return "low"

    def _inject_guild_id(self, params: Dict[str, Any], guild_id: Optional[int]) -> Dict[str, Any]:
        """Auto-inject guild_id into params."""
        if guild_id and "guild_id" not in params:
            params["guild_id"] = guild_id
        if "guild_id" in params and isinstance(params["guild_id"], str):
            try:
                params["guild_id"] = int(params["guild_id"])
            except ValueError:
                pass
        return params

    async def _get_server_context(self, guild_id: Optional[int]) -> str:
        """Get server context from knowledge store."""
        if not guild_id or not self._knowledge_store:
            return "No server context available."
        try:
            return await self._knowledge_store.get_summary_string(guild_id)
        except Exception:
            return "No server context available."

    # ============================================================
    # BASE AGENT INTERFACE
    # ============================================================

    def get_agent_role(self) -> AgentRole:
        return AgentRole.ADMIN
