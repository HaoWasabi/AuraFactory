# app/agents/fast_track.py
"""
FastTrackExecutor — Single-action command handler.
1 LLM call → extract tool + params → validate → MCP call → format response.

Only handles LOW/MEDIUM risk tools.
If LLM suggests HIGH+ risk → escalate to AdminAgent.
Max 1 tool call per request.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent, LLM_OVERLOAD_MESSAGE
from app.agents.contracts import AgentRole, TaskAssignment, TaskResult

logger = logging.getLogger(__name__)


# ============================================================
# EXTRACTION PROMPT
# ============================================================

EXTRACT_PROMPT: str = """You are AuraFactory — extract ONE Discord action from the user's request.

Return JSON only: {{"tool": "tool_name", "params": {{...}}}}
guild_id is auto-injected — do NOT include it.

Available tools:
- create_channel: params: name*, channel_type (text|voice|forum), category, topic
- create_category: params: name*
- create_role: params: name*, color, mentionable, hoist
- assign_role: params: user_id*, role_name*
- edit_channel: params: channel_name*, new_name, new_topic, slowmode
- delete_channel: params: channel_name*
- delete_role: params: role_name*
- kick_member: params: user_id*, reason
- ban_member: params: user_id*, reason, delete_days
- set_channel_permission: params: channel_name*, target_name*, allow, deny

(* = required)

If you cannot extract a clear action, return: {{"tool": null, "params": {{}}}}

Server context: {server_context}
User request: "{message}"

Return JSON only:"""


class FastTrackExecutor(BaseAgent):
    """
    Fast Track — single LLM call to extract tool + params, then execute via MCP.

    Flow:
    1. LLM call → extract JSON: {tool, params}
    2. Validate params (via SkillValidator if available)
    3. Risk check — if HIGH+ → escalate to AdminAgent
    4. Execute tool via MCP client
    5. Format response

    Constraints:
    - Max 1 tool call per request.
    - Only LOW/MEDIUM risk tools.
    - If extraction fails → return user-friendly error.
    """

    def __init__(
        self,
        llm: Any,
        mcp_client: Any = None,
        memory: Any = None,
        knowledge_store: Any = None,
        settings: Optional[Dict[str, Any]] = None,
        skill_registry: Any = None,
        admin_agent: Any = None,
    ) -> None:
        super().__init__(
            llm=llm,
            mcp_client=mcp_client,
            memory=memory,
            knowledge_store=knowledge_store,
            settings=settings,
            skill_registry=skill_registry,
        )
        self._admin_agent = admin_agent  # For escalation

    def set_admin_agent(self, agent: Any) -> None:
        """Inject AdminAgent for risk escalation."""
        self._admin_agent = agent

    # ============================================================
    # MAIN EXECUTE
    # ============================================================

    async def execute(self, task: TaskAssignment) -> TaskResult:
        """
        Execute a fast-track single-action command.

        Args:
            task: TaskAssignment with message and context.

        Returns:
            TaskResult with execution outcome.
        """
        trace_id = task.trace_id
        prompt = task.prompt
        guild_id = task.guild_id

        logger.info(f"[{trace_id}] FastTrack executing: '{prompt[:60]}...'")

        # ─── Step 1: Extract action via LLM ───
        server_context = await self._get_server_context(guild_id)
        extraction = await self._extract_action(prompt, server_context)

        if not extraction or not extraction.get("tool"):
            return TaskResult(
                trace_id=trace_id,
                content="Xin lỗi, tôi không hiểu yêu cầu. Bạn có thể nói rõ hơn?",
                status="failed",
            )

        tool_name: str = extraction["tool"]
        params: Dict[str, Any] = extraction.get("params", {})

        # ─── Step 2: Risk Check ───
        risk_level = self._get_risk_level(tool_name)

        if risk_level in ("high", "critical"):
            logger.info(
                f"[{trace_id}] HIGH risk tool '{tool_name}' → escalating to AdminAgent"
            )
            # Escalate to AdminAgent for approval flow
            if self._admin_agent:
                task.intent = task.intent  # Keep same intent for context
                return await self._admin_agent.execute(task)
            else:
                return TaskResult(
                    trace_id=trace_id,
                    content=(
                        f"⚠️ Thao tác **{tool_name}** có rủi ro cao và cần xác nhận. "
                        f"Vui lòng sử dụng lệnh phức tạp hơn."
                    ),
                    status="needs_approval",
                )

        # ─── Step 3: Validate Params ───
        params = self._inject_guild_id(params, guild_id)
        validation_error = self._validate_params(tool_name, params)
        if validation_error:
            return TaskResult(
                trace_id=trace_id,
                content=f"❌ Lỗi tham số: {validation_error}",
                status="failed",
            )

        # ─── Step 4: Execute via MCP ───
        try:
            result = await self._mcp_client.call_tool(tool_name, params)

            # Check for tool-level failure
            if isinstance(result, dict) and result.get("success") is False:
                error_msg = result.get("error", "Unknown error")
                return TaskResult(
                    trace_id=trace_id,
                    content=f"❌ {tool_name}: {error_msg}",
                    status="failed",
                    tools_called=[tool_name],
                )

            # ─── Step 5: Format Response ───
            response_text = self._format_success(tool_name, params, result)

            # Log cost
            cost_info = {}
            if hasattr(self, "_last_llm_response") and self._last_llm_response:
                cost_info = self._log_cost(
                    trace_id,
                    self._last_llm_response.input_tokens,
                    self._last_llm_response.output_tokens,
                    self._last_llm_response.model,
                )

            return TaskResult(
                trace_id=trace_id,
                content=response_text,
                status="success",
                tools_called=[tool_name],
                cost=cost_info,
            )

        except Exception as e:
            logger.error(f"[{trace_id}] MCP call failed: {tool_name}: {e}")
            return TaskResult(
                trace_id=trace_id,
                content=f"❌ Lỗi khi thực hiện {tool_name}: {str(e)}",
                status="failed",
                tools_called=[tool_name],
            )

    # ============================================================
    # LLM EXTRACTION
    # ============================================================

    async def _extract_action(
        self, prompt: str, server_context: str
    ) -> Optional[Dict[str, Any]]:
        """
        Single LLM call to extract tool + params from user request.
        Returns dict with {tool, params} or None on failure.
        """
        system = EXTRACT_PROMPT.format(
            message=prompt[:500],
            server_context=server_context[:300],
        )

        response = await self._call_llm(
            prompt=prompt,
            system_prompt=system,
            temperature=0.0,
            max_tokens=300,
        )

        if not response:
            return None

        # Store for cost tracking
        self._last_llm_response = response

        # Parse JSON from response
        return self._parse_extraction(response.content)

    def _parse_extraction(self, raw: str) -> Optional[Dict[str, Any]]:
        """Parse LLM output into {tool, params} dict."""
        text = raw.strip()

        # Strip markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Find JSON object
        try:
            if "{" in text:
                start = text.index("{")
                end = text.rindex("}") + 1
                data = json.loads(text[start:end])
                if isinstance(data, dict) and data.get("tool"):
                    return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse extraction JSON: {e}")

        return None

    # ============================================================
    # HELPERS
    # ============================================================

    def _get_risk_level(self, tool_name: str) -> str:
        """Get risk level for a tool from skill registry."""
        if self._skill_registry and hasattr(self._skill_registry, "get_risk_level"):
            return self._skill_registry.get_risk_level(tool_name)
        # Default risk levels for known tools
        high_risk_tools = {"kick_member", "ban_member", "delete_channel", "delete_role"}
        if tool_name in high_risk_tools:
            return "high"
        return "low"

    def _inject_guild_id(self, params: Dict[str, Any], guild_id: Optional[int]) -> Dict[str, Any]:
        """Auto-inject guild_id into params."""
        if guild_id and "guild_id" not in params:
            params["guild_id"] = guild_id
        # Coerce string guild_id to int
        if "guild_id" in params and isinstance(params["guild_id"], str):
            try:
                params["guild_id"] = int(params["guild_id"])
            except ValueError:
                pass
        return params

    def _validate_params(self, tool_name: str, params: Dict[str, Any]) -> Optional[str]:
        """Validate params via SkillValidator. Returns error message or None."""
        if self._skill_registry and hasattr(self._skill_registry, "validate"):
            result = self._skill_registry.validate(tool_name, params)
            if hasattr(result, "is_valid") and not result.is_valid:
                return result.error_message
        return None

    async def _get_server_context(self, guild_id: Optional[int]) -> str:
        """Get server context string from knowledge store."""
        if not guild_id or not self._knowledge_store:
            return "No server context available."
        try:
            return await self._knowledge_store.get_summary_string(guild_id)
        except Exception:
            return "No server context available."

    def _format_success(
        self, tool_name: str, params: Dict[str, Any], result: Any
    ) -> str:
        """Format a success response for the user."""
        # Extract meaningful info from params
        name = params.get("name", params.get("channel_name", params.get("role_name", "")))

        tool_descriptions = {
            "create_channel": f"✅ Đã tạo channel **#{name}**",
            "create_category": f"✅ Đã tạo category **{name}**",
            "create_role": f"✅ Đã tạo role **@{name}**",
            "assign_role": f"✅ Đã gán role **{params.get('role_name', '')}**",
            "edit_channel": f"✅ Đã chỉnh sửa channel **#{name}**",
            "delete_channel": f"✅ Đã xóa channel **#{name}**",
            "delete_role": f"✅ Đã xóa role **@{name}**",
            "kick_member": f"✅ Đã kick member",
            "ban_member": f"✅ Đã ban member",
            "set_channel_permission": f"✅ Đã cập nhật permission cho **#{name}**",
        }

        return tool_descriptions.get(tool_name, f"✅ Đã thực hiện {tool_name}")

    # ============================================================
    # BASE AGENT INTERFACE
    # ============================================================

    def get_agent_role(self) -> AgentRole:
        return AgentRole.FAST_TRACK
