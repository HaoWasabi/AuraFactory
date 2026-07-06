# app/agents/admin_agent.py
"""
AdminAgent — Setup Wizard + Admin CRUD Commands.

Responsibilities:
- SETUP MODE: Guide admin through first-time server configuration
- ADMIN MODE: Execute CRUD operations via ReAct loop + MCP tools

Permission: Only accessible by users with admin role.
Uses ReAct pattern: Think → Act → Observe → Repeat.
Integrates SkillRegistry for tool discovery + SkillValidator for safety.
"""
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional

from app.agents.contracts import AgentRole
from app.infra.llm.base import LLMProvider
from app.infra.observability.tracer import Tracer
from app.infra.observability.metrics import metrics
from app.knowledge.store import ServerKnowledgeStore
from app.mcp import MCPClient
from app.gateway.pipeline import GatewayContext

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10
LOOP_TIMEOUT_SECONDS = 30


# ============================================================
# PROMPTS
# ============================================================

SETUP_SYSTEM_PROMPT = """You are AuraFactory Setup Wizard — helping an admin configure their Discord server for the first time.

## Current Server State:
{server_context}

## Your Role:
- Guide the admin through server setup in a friendly, step-by-step conversation.
- Ask what the server is for, then propose a channel/role structure.
- Present your plan clearly and wait for confirmation before executing.
- After setup confirmed + executed, announce switching to normal mode.

## When proposing a plan, format it clearly:
```
📋 Proposed Structure:
📁 Category: NAME
  #channel-1 — description
  #channel-2 — description
🎭 Roles: role1, role2, role3
```

Then ask: "✅ Tạo luôn | ✏️ Chỉnh sửa | 🔍 Giải thích thêm"

## When executing (after user confirms):
Use ReAct format — one action at a time.
Always create #aura-admin channel for future admin commands.

## Language Rule:
- Respond in the same language the user used.
"""

ADMIN_REACT_PROMPT = """You are AuraFactory in Admin Mode — executing server management commands.

Each turn you MUST respond with this exact JSON (no other text):
{{
  "thought": "your reasoning about what to do next (always in English)",
  "action": "tool_name",
  "action_input": {{"param": "value"}}
}}

Or if you're done:
{{
  "thought": "summary of what was accomplished (English)",
  "action": "FINISH",
  "message": "response to show the user (in user's language)"
}}

Or if you need more info:
{{
  "thought": "what's unclear (English)",
  "action": "CLARIFY",
  "message": "question to ask (in user's language)"
}}

## Risk Assessment:
Each tool has a risk level shown below. Follow these rules:
- LOW: Execute immediately.
- MEDIUM: Execute, but note what you're doing in thought.
- HIGH: Use action "CONFIRM" to ask user before executing.
- CRITICAL: Use action "CONFIRM" with explicit warning message.

## Rules:
- ONE action per turn only.
- Observe the result before deciding next action.
- If a tool fails, try an alternative approach.
- Keep "message" concise — under 2000 characters.
- Max {max_iter} turns allowed.

## Server Context:
{server_context}

## Available Tools (name | risk | description):
{tools_block}

## Language Rule:
- "thought" field: always English
- "message" field: same language as user's original message
"""


class AdminAgent:
    """
    AdminAgent — handles Setup Mode and Admin Mode.

    Both modes share the ReAct loop + MCP tools.
    Difference is only in the system prompt and initial behavior.

    Setup Mode: Conversational wizard → confirm → execute → mark complete
    Admin Mode: Direct command execution via ReAct

    Integration:
    - SkillRegistry: provides filtered tool list with risk metadata
    - SkillValidator: validates params before MCP execution
    - Memory (working): persists pending plans across turns
    """

    def __init__(
        self,
        llm: LLMProvider,
        tracer: Tracer,
        knowledge_store: ServerKnowledgeStore,
    ):
        self._llm = llm
        self._tracer = tracer
        self._knowledge = knowledge_store
        self._mcp: Optional[MCPClient] = None
        self._specialists: Dict[str, Any] = {}
        # Injected later
        self._skill_registry = None
        self._skill_validator = None
        self._memory = None

    def set_mcp_client(self, mcp_client: MCPClient) -> None:
        """Inject MCP client for tool access."""
        self._mcp = mcp_client

    def set_skill_registry(self, registry, validator=None) -> None:
        """Inject SkillRegistry + Validator for safe tool access."""
        self._skill_registry = registry
        self._skill_validator = validator

    def set_memory(self, memory) -> None:
        """Inject MemoryService for session persistence."""
        self._memory = memory

    def register_specialist(self, role: str, agent) -> None:
        """Register a specialist (e.g., architect) for delegation."""
        self._specialists[role] = agent

    # ============================================================
    # SETUP MODE
    # ============================================================

    async def handle_setup(
        self,
        prompt: str,
        guild_id: int,
        guild=None,
        context: GatewayContext = None,
    ) -> Dict[str, Any]:
        """
        Setup Mode — first-time server configuration wizard.
        Conversational until user confirms, then executes via ReAct loop.
        """
        trace_id = context.trace_id if context else "no-trace"
        session_id = context.session_id if context else ""
        logger.info(f"[{trace_id}] AdminAgent SETUP MODE for guild {guild_id}")

        server_context = await self._get_server_context(guild_id, guild)

        # Check for pending plan in memory (HITL resume)
        pending_plan = await self._get_pending_plan(session_id)

        # Check if this looks like a confirmation to execute
        confirm_keywords = ("tạo", "ok", "confirm", "yes", "đồng ý", "tạo luôn", "✅", "làm đi", "execute", "go")
        is_confirmation = any(kw in prompt.lower() for kw in confirm_keywords)

        if is_confirmation and self._mcp:
            # User confirmed → execute plan via ReAct loop
            # Inject pending plan context if available
            exec_prompt = prompt
            if pending_plan:
                exec_prompt = f"User confirmed execution. Previous plan:\n{pending_plan}\n\nUser said: {prompt}"
                await self._clear_pending_plan(session_id)

            result = await self._run_react_loop(exec_prompt, trace_id, guild_id, guild, server_context, session_id)
            # Mark setup as complete after successful execution
            if result.get("status") == "response":
                await self._knowledge.mark_setup_complete(guild_id)
                logger.info(f"[{trace_id}] Setup marked complete for guild {guild_id}")
            return result
        else:
            # Conversational phase — propose plan / answer questions
            system_prompt = SETUP_SYSTEM_PROMPT.format(server_context=server_context)

            # Include conversation history for continuity
            messages = await self._build_messages_with_history(prompt, session_id)

            response = await self._llm.generate(
                messages=messages,
                system_prompt=system_prompt,
                temperature=0.7,
                max_tokens=1500,
            )

            metrics.count_request(response.model, "admin_setup", "success")
            metrics.count_tokens(response.model, response.input_tokens, response.output_tokens)

            # Persist proposed plan if response contains a plan
            if self._looks_like_plan(response.content):
                await self._save_pending_plan(session_id, response.content)

            return {
                "status": "response",
                "content": response.content,
                "trace_id": trace_id,
                "mode": "setup",
            }

    # ============================================================
    # ADMIN MODE
    # ============================================================

    async def handle_admin(
        self,
        prompt: str,
        guild_id: int,
        guild=None,
        context: GatewayContext = None,
    ) -> Dict[str, Any]:
        """
        Admin Mode — execute CRUD commands via ReAct loop.
        Only accessible by admin-role users (permission gate in orchestrator).
        """
        trace_id = context.trace_id if context else "no-trace"
        session_id = context.session_id if context else ""
        logger.info(f"[{trace_id}] AdminAgent ADMIN MODE for guild {guild_id}")

        server_context = await self._get_server_context(guild_id, guild)
        return await self._run_react_loop(prompt, trace_id, guild_id, guild, server_context, session_id)

    # ============================================================
    # REACT LOOP (shared by both modes)
    # ============================================================

    async def _run_react_loop(
        self, prompt: str, trace_id: str, guild_id: int, guild, server_context: str, session_id: str = ""
    ) -> Dict[str, Any]:
        """
        ReAct loop: Think → Act → Observe → Repeat.
        Max MAX_ITERATIONS turns. One tool call per turn.
        Uses SkillRegistry for tool list + Validator before execution.
        """
        if not self._mcp:
            return {
                "status": "response",
                "content": "❌ System error: MCP not configured.",
                "trace_id": trace_id,
                "mode": "admin",
            }

        # Build tools block from SkillRegistry (with risk metadata)
        tools_block = self._build_tools_block()

        system_prompt = ADMIN_REACT_PROMPT.format(
            max_iter=MAX_ITERATIONS,
            tools_block=tools_block,
            server_context=server_context,
        )

        # Include conversation history for continuity
        messages = await self._build_messages_with_history(prompt, session_id)
        consecutive_failures = 0

        for iteration in range(MAX_ITERATIONS):
            # Generate next action
            response = await self._llm.generate(
                messages=messages,
                system_prompt=system_prompt if iteration == 0 else None,
                temperature=0.2,
                max_tokens=1000,
            )

            raw_output = response.content.strip()
            metrics.count_request(response.model, "admin_react", "success")
            metrics.count_tokens(response.model, response.input_tokens, response.output_tokens)

            # Parse JSON response
            try:
                parsed = self._parse_react_output(raw_output)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"[{trace_id}] Failed to parse ReAct output iter {iteration}: {e}")
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    return {
                        "status": "response",
                        "content": "❌ Đã xảy ra lỗi khi xử lý. Vui lòng thử lại.",
                        "trace_id": trace_id,
                        "mode": "admin",
                    }
                messages.append({"role": "assistant", "content": raw_output})
                messages.append({
                    "role": "user",
                    "content": "Error: Response must be valid JSON with 'thought' and 'action' fields. Try again.",
                })
                continue

            consecutive_failures = 0
            thought = parsed.get("thought", "")
            action = parsed.get("action", "")

            self._tracer.log_reasoning(trace_id, "admin_react", f"[iter {iteration}] {thought}")
            logger.info(f"[{trace_id}] ReAct iter {iteration}: action={action}")

            # ─── Terminal actions ───
            if action == "FINISH":
                return {
                    "status": "response",
                    "content": parsed.get("message", "Done!"),
                    "trace_id": trace_id,
                    "mode": "admin",
                    "iterations": iteration + 1,
                }

            if action == "CLARIFY":
                return {
                    "status": "clarify",
                    "content": parsed.get("message", "Could you clarify?"),
                    "trace_id": trace_id,
                    "mode": "admin",
                }

            if action == "CONFIRM":
                # Persist the plan so we can resume after user confirms
                plan_content = parsed.get("message", "")
                await self._save_pending_plan(session_id, f"Action: {thought}\n{plan_content}")
                return {
                    "status": "confirm",
                    "content": parsed.get("message", "Please confirm."),
                    "trace_id": trace_id,
                    "mode": "admin",
                }

            # ─── Delegation to specialist ───
            if action == "delegate_architect":
                observation = await self._delegate("architect", parsed.get("action_input", {}), guild_id, guild)
            else:
                # ─── Tool execution via MCP (with validation) ───
                action_input = parsed.get("action_input", {})
                observation = await self._execute_tool(action, action_input, trace_id, guild_id)

            # Append to conversation for next iteration
            messages.append({"role": "assistant", "content": raw_output})
            obs_str = json.dumps(observation, ensure_ascii=False) if isinstance(observation, dict) else str(observation)
            messages.append({"role": "user", "content": f"Observation: {obs_str}"})

        # Max iterations reached
        return {
            "status": "response",
            "content": "⚠️ Đã đạt giới hạn xử lý. Một số thao tác có thể chưa hoàn thành.",
            "trace_id": trace_id,
            "mode": "admin",
            "iterations": MAX_ITERATIONS,
        }

    # ============================================================
    # TOOL EXECUTION (with validation)
    # ============================================================

    async def _execute_tool(
        self, tool_name: str, params: Dict[str, Any], trace_id: str, guild_id: int
    ) -> Any:
        """
        Execute a tool with validation gate:
        1. Validate params via SkillValidator
        2. Check risk level
        3. Execute via MCP
        """
        # --- Step 1: Validate ---
        if self._skill_validator:
            result = self._skill_validator.validate(tool_name, params)
            if not result.is_valid:
                logger.warning(f"[{trace_id}] Validation failed for {tool_name}: {result.error_message}")
                return f"Validation Error: {result.error_message}"
            # Use sanitized params
            params = result.sanitized_params
            if result.warnings:
                logger.info(f"[{trace_id}] Validation warnings for {tool_name}: {result.warnings}")

        # --- Step 2: Risk check (log only — actual gate is in LLM prompt) ---
        if self._skill_registry:
            risk = self._skill_registry.get_risk_level(tool_name)
            if risk in ("high", "critical"):
                logger.warning(f"[{trace_id}] HIGH RISK tool executed: {tool_name} (risk={risk})")
                metrics.increment("high_risk_tool_executed", labels={"tool": tool_name})

        # --- Step 3: Execute via MCP ---
        try:
            result = await asyncio.wait_for(
                self._mcp.call_tool(tool_name, params),
                timeout=LOOP_TIMEOUT_SECONDS,
            )
            return result
        except asyncio.TimeoutError:
            return f"Error: Tool '{tool_name}' timed out after {LOOP_TIMEOUT_SECONDS}s"
        except Exception as e:
            return f"Error: {str(e)}"

    # ============================================================
    # TOOLS BLOCK BUILDER
    # ============================================================

    def _build_tools_block(self) -> str:
        """Build tools list for LLM prompt — from SkillRegistry if available, else MCP."""
        if self._skill_registry and self._skill_registry.is_loaded:
            # Use SkillRegistry (includes risk metadata)
            tools = self._skill_registry.get_all_tools()
            lines = []
            for t in tools:
                lines.append(f"- {t.name} [{t.risk_level}]: {t.description}")
            return "\n".join(lines)
        else:
            # Fallback to raw MCP list
            tools = self._mcp.to_llm_format()
            return "\n".join(f"- {t['name']}: {t['description']}" for t in tools)

    # ============================================================
    # MEMORY / PENDING PLAN (HITL resume)
    # ============================================================

    async def _save_pending_plan(self, session_id: str, plan: str) -> None:
        """Persist a proposed plan so it survives across message turns."""
        if self._memory and session_id:
            await self._memory.working.set(
                f"pending_plan:{session_id}", plan, ttl_seconds=600  # 10 min TTL
            )

    async def _get_pending_plan(self, session_id: str) -> Optional[str]:
        """Retrieve pending plan from working memory."""
        if self._memory and session_id:
            return await self._memory.working.get(f"pending_plan:{session_id}")
        return None

    async def _clear_pending_plan(self, session_id: str) -> None:
        """Remove pending plan after execution."""
        if self._memory and session_id:
            await self._memory.working.delete(f"pending_plan:{session_id}")

    # ============================================================
    # CONVERSATION HISTORY
    # ============================================================

    async def _build_messages_with_history(self, prompt: str, session_id: str) -> List[Dict[str, str]]:
        """Build message list with conversation history for continuity."""
        messages = []

        # Inject recent history from memory
        if self._memory and session_id:
            try:
                history = await self._memory.get_conversation_history(session_id, limit=6)
                if history:
                    for msg in history[-6:]:
                        messages.append({
                            "role": msg.get("role", "user"),
                            "content": msg.get("content", "")[:500],
                        })
            except Exception:
                pass

        # Current message
        messages.append({"role": "user", "content": prompt})
        return messages

    # ============================================================
    # HELPERS
    # ============================================================

    async def _get_server_context(self, guild_id: int, guild) -> str:
        """Get server context string for prompts."""
        if guild_id:
            ctx = await self._knowledge.get_context_string(guild_id)
            if ctx != "No server knowledge available.":
                return ctx

        # Fallback: minimal context from guild object
        if guild:
            return (
                f"Server: {guild.name}\n"
                f"Members: {guild.member_count}\n"
                f"Channels: {len(guild.channels)}\n"
                f"Roles: {len(guild.roles)}\n"
            )
        return "No server context available."

    def _parse_react_output(self, raw: str) -> dict:
        """Parse ReAct JSON from LLM output."""
        text = raw.strip()
        # Strip markdown code block
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        # Find JSON in text
        if "{" in text:
            start = text.index("{")
            end = text.rindex("}") + 1
            text = text[start:end]

        parsed = json.loads(text)
        if "thought" not in parsed:
            raise ValueError("Missing 'thought' field")
        if "action" not in parsed and "message" not in parsed:
            raise ValueError("Missing 'action' or 'message' field")
        return parsed

    async def _delegate(self, role: str, task_input: dict, guild_id: int, guild) -> str:
        """Delegate to a specialist agent."""
        agent = self._specialists.get(role)
        if not agent:
            return f"Error: No specialist '{role}' registered"
        try:
            result = await agent.run_task(
                task_description=task_input.get("task", ""),
                trace_id="",
                guild_id=guild_id,
                guild=guild,
            )
            return result.get("message", "Task completed.")
        except Exception as e:
            return f"Delegation error: {str(e)}"

    def _looks_like_plan(self, content: str) -> bool:
        """Detect if response contains a proposed plan."""
        plan_indicators = ("📋", "Proposed", "Category:", "#", "Roles:", "✅ Tạo", "Tạo luôn")
        return any(indicator in content for indicator in plan_indicators)
