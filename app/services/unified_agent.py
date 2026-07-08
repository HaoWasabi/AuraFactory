"""
UnifiedAgent — Single-call agentic service replacing Classifier + Planner + QueryService.

Architecture:
    1 LLM call with native function calling → model decides what to do
    If tool_calls returned → validate + execute directly (no intermediate plan)
    If text returned → that's the response (query/clarify)

Benefits:
    - 1 LLM call instead of 2-3 (classifier + planner + query)
    - Model sees full context → better decisions
    - Native function calling → structured output guaranteed
    - Self-contained: classify + plan + route in single reasoning pass

Token budget: ~800-1200 tokens/request (was ~2500 with pipeline)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.llm.base import BaseLLM, LLMResponse, ToolCall
from app.mcp import MCPClient
from app.services.context_service import ContextService

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# System Prompt — This is the "brain" of the agent
# ─────────────────────────────────────────────────────────────────────

UNIFIED_SYSTEM_PROMPT = """You are AuraFactory, an AI assistant that manages Discord servers.
You help server admins set up channels, roles, categories, and manage their server.

## Your Capabilities
You can execute Discord operations by calling the available tools.
You can also answer questions about the server's current state.

## Rules
1. If the user wants to CREATE/EDIT/DELETE something → call the appropriate tool(s).
2. If the user asks a QUESTION about the server → answer directly from the context below.
3. If the request is AMBIGUOUS or you need more info → ask a clarifying question (do NOT guess).
4. If the request is OUTSIDE your capabilities → say so politely.
5. For HIGH-RISK operations (delete category with channels, mass operations) → describe what you'll do and ask for confirmation BEFORE calling tools.
6. You may call MULTIPLE tools in sequence if the request requires it.
7. Always use IDs from the server context when referencing existing channels/roles/categories.

## Important
- Channel names in Discord are lowercase, no spaces (use hyphens).
- When creating channels inside a category, use the category_id from context.
- When setting permissions for a role, use the role_id from context.
- Respond in the SAME language the user used (Vietnamese or English).
"""


def build_server_context_block(server_context: dict) -> str:
    """Build a compact server context string for the system prompt."""
    if not server_context:
        return "No server data available yet."

    parts = []

    # Parse each section (may be JSON string from DB)
    categories = server_context.get("categories", [])
    channels = server_context.get("channels", [])
    roles = server_context.get("roles", [])
    server_info = server_context.get("server_info", {})

    if isinstance(categories, str):
        categories = json.loads(categories) if categories.strip() else []
    if isinstance(channels, str):
        channels = json.loads(channels) if channels.strip() else []
    if isinstance(roles, str):
        roles = json.loads(roles) if roles.strip() else []
    if isinstance(server_info, str):
        server_info = json.loads(server_info) if server_info.strip() else {}

    # Server info (compact)
    if server_info:
        name = server_info.get("name", "?")
        members = server_info.get("member_count", server_info.get("approximate_member_count", "?"))
        parts.append(f"Server: {name} ({members} members)")

    # Categories (id + name only)
    if categories:
        cat_lines = [f"  {c.get('id','?')}: {c.get('name','?')}" for c in categories[:20]]
        parts.append("Categories:\n" + "\n".join(cat_lines))

    # Channels (compact: id, name, type, category_id)
    if channels:
        ch_lines = []
        for ch in channels[:40]:
            ch_type = ch.get("type", "text")
            cat_id = ch.get("category_id", "none")
            ch_lines.append(f"  {ch.get('id','?')}: #{ch.get('name','?')} ({ch_type}) [cat:{cat_id}]")
        parts.append("Channels:\n" + "\n".join(ch_lines))

    # Roles (compact: id, name, position)
    if roles:
        role_lines = [f"  {r.get('id','?')}: @{r.get('name','?')} (pos:{r.get('position',0)})"
                      for r in roles[:20] if r.get("name") != "@everyone"]
        parts.append("Roles:\n" + "\n".join(role_lines))

    return "\n\n".join(parts) if parts else "Server is empty or bot has no cached data."


# ─────────────────────────────────────────────────────────────────────
# Tool Definitions for Gemini function calling
# ─────────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "create_channel",
        "description": "Create a new Discord channel (text, voice, stage, forum, news).",
        "parameters": {
            "properties": {
                "name": {"type": "string", "description": "Channel name (lowercase, hyphens for spaces)"},
                "type": {"type": "string", "description": "Channel type: text, voice, stage, forum, news"},
                "category_id": {"type": "string", "description": "ID of parent category (optional)"},
                "topic": {"type": "string", "description": "Channel topic/description (text channels only)"},
                "is_private": {"type": "boolean", "description": "Make channel private (hidden from @everyone)"},
                "allowed_role_ids": {"type": "array", "items": {"type": "string"}, "description": "Role IDs that can see private channel"},
                "slowmode_delay": {"type": "integer", "description": "Slowmode in seconds (0-21600)"},
                "nsfw": {"type": "boolean", "description": "Mark as NSFW"},
                "user_limit": {"type": "integer", "description": "Max users in voice channel (0=unlimited)"},
                "bitrate": {"type": "integer", "description": "Voice bitrate in bps (8000-384000)"},
            },
            "required": ["name", "type"],
        },
    },
    {
        "name": "edit_channel",
        "description": "Edit an existing channel's properties (name, topic, slowmode, permissions, etc.).",
        "parameters": {
            "properties": {
                "channel_id": {"type": "string", "description": "ID of the channel to edit"},
                "name": {"type": "string", "description": "New channel name"},
                "topic": {"type": "string", "description": "New topic"},
                "slowmode_delay": {"type": "integer", "description": "New slowmode in seconds"},
                "nsfw": {"type": "boolean", "description": "Toggle NSFW"},
                "category_id": {"type": "string", "description": "Move to this category"},
                "sync_permissions": {"type": "boolean", "description": "Sync permissions with parent category"},
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "delete_channel",
        "description": "Delete a channel or category. WARNING: This is irreversible.",
        "parameters": {
            "properties": {
                "channel_id": {"type": "string", "description": "ID of channel/category to delete"},
                "reason": {"type": "string", "description": "Reason for deletion (audit log)"},
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "create_category",
        "description": "Create a new category to organize channels.",
        "parameters": {
            "properties": {
                "name": {"type": "string", "description": "Category name"},
                "position": {"type": "integer", "description": "Position (0 = top)"},
                "is_private": {"type": "boolean", "description": "Make category private"},
                "allowed_role_ids": {"type": "array", "items": {"type": "string"}, "description": "Role IDs allowed to see private category"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_role",
        "description": "Create a new role with optional permissions and color.",
        "parameters": {
            "properties": {
                "name": {"type": "string", "description": "Role name"},
                "color": {"type": "string", "description": "Hex color (e.g. '#FF5733')"},
                "hoist": {"type": "boolean", "description": "Show role separately in member list"},
                "mentionable": {"type": "boolean", "description": "Allow anyone to @mention this role"},
                "permissions": {"type": "object", "description": "Permission flags {permission_name: true/false}"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_role",
        "description": "Delete an existing role. WARNING: This is irreversible.",
        "parameters": {
            "properties": {
                "role_id": {"type": "string", "description": "ID of the role to delete"},
                "reason": {"type": "string", "description": "Reason for deletion"},
            },
            "required": ["role_id"],
        },
    },
    {
        "name": "edit_role",
        "description": "Edit a role's name, color, permissions, or display settings.",
        "parameters": {
            "properties": {
                "role_id": {"type": "string", "description": "ID of the role to edit"},
                "name": {"type": "string", "description": "New role name"},
                "color": {"type": "string", "description": "New hex color"},
                "hoist": {"type": "boolean", "description": "Show separately in member list"},
                "mentionable": {"type": "boolean", "description": "Allow @mentions"},
                "permissions": {"type": "object", "description": "Permission updates {name: true/false}"},
            },
            "required": ["role_id"],
        },
    },
    {
        "name": "assign_role",
        "description": "Assign a role to a member.",
        "parameters": {
            "properties": {
                "role_id": {"type": "string", "description": "Role ID to assign"},
                "user_id": {"type": "string", "description": "User ID to assign the role to"},
            },
            "required": ["role_id", "user_id"],
        },
    },
]

# Map from unified tool names to MCP tool names
TOOL_NAME_MAP = {
    "create_channel": "discord.channels.create",
    "edit_channel": "discord.channels.edit",
    "delete_channel": "discord.channels.delete",
    "create_category": "discord.categories.create",
    "create_role": "discord.roles.create",
    "delete_role": "discord.roles.delete",
    "edit_role": "discord.roles.modify",
    "assign_role": "discord.roles.assign",
}

# Map from unified param names to MCP connector param names
PARAM_NAME_MAP = {
    "create_channel": {"channel_id": None},  # No remapping needed
    "edit_channel": {},
    "delete_channel": {"channel_id": "channel_id"},
    "create_category": {},
    "create_role": {},
    "delete_role": {},
    "edit_role": {},
    "assign_role": {},
}


# ─────────────────────────────────────────────────────────────────────
# Unified Agent Service
# ─────────────────────────────────────────────────────────────────────

class UnifiedAgent:
    """Single-call agentic service with native function calling.

    Replaces: ClassifierService + PlannerService + QueryService
    Flow: 1 LLM call → tool_calls OR text response
    """

    def __init__(
        self,
        llm: BaseLLM,
        mcp_client: MCPClient,
        context_service: ContextService,
    ) -> None:
        self._llm = llm
        self._mcp_client = mcp_client
        self._context_service = context_service

    async def process(
        self,
        message: str,
        guild_id: int,
        user_id: int,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Process a user message — the single entry point.

        Returns:
            {
                "type": "answer" | "action" | "clarify" | "error",
                "content": str,  # text response to show user
                "tool_results": [...],  # if tools were called
            }
        """
        # 1. Get server context
        server_context = await self._context_service.get_server_context(guild_id)
        context_block = build_server_context_block(server_context)

        # 2. Build messages
        messages = []

        # Inject server context
        messages.append({
            "role": "user",
            "content": f"[CURRENT SERVER STATE]\n{context_block}",
        })
        messages.append({
            "role": "assistant",
            "content": "I have the server state. How can I help?",
        })

        # Add conversation history (last 6 turns max)
        if history:
            for turn in history[-6:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # Add current message
        messages.append({"role": "user", "content": message})

        # 3. Call LLM with function calling
        try:
            response: LLMResponse = await self._llm.generate(
                messages=messages,
                system_prompt=UNIFIED_SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                temperature=0.2,
                max_tokens=2048,
            )
        except Exception as e:
            logger.error("UnifiedAgent LLM error: %s", e, exc_info=True)
            return {
                "type": "error",
                "content": "⚠️ Sorry, I'm having trouble processing your request right now.",
                "tool_results": [],
            }

        # 4. Handle response
        if response.tool_calls:
            # Model wants to execute tools
            return await self._execute_tools(response, guild_id)
        elif response.content:
            # Model returned text (answer or clarify)
            return {
                "type": "answer",
                "content": response.content,
                "tool_results": [],
            }
        else:
            return {
                "type": "error",
                "content": "I couldn't understand your request. Could you rephrase?",
                "tool_results": [],
            }

    async def _execute_tools(
        self,
        response: LLMResponse,
        guild_id: int,
    ) -> Dict[str, Any]:
        """Execute tool calls from LLM response via MCP."""
        results = []
        all_success = True

        for tool_call in response.tool_calls:
            tool_name = tool_call.name
            params = tool_call.arguments or {}

            # Map to MCP tool name
            mcp_tool_name = TOOL_NAME_MAP.get(tool_name)
            if not mcp_tool_name:
                results.append({
                    "tool": tool_name,
                    "success": False,
                    "error": f"Unknown tool: {tool_name}",
                })
                all_success = False
                continue

            # Add guild_id to params
            params["guild_id"] = guild_id

            # Execute via MCP
            try:
                mcp_response = await self._mcp_client.call_tool(mcp_tool_name, params)
                if mcp_response.success:
                    results.append({
                        "tool": tool_name,
                        "success": True,
                        "result": mcp_response.result,
                    })
                else:
                    results.append({
                        "tool": tool_name,
                        "success": False,
                        "error": mcp_response.error or "Unknown error",
                    })
                    all_success = False
            except Exception as e:
                results.append({
                    "tool": tool_name,
                    "success": False,
                    "error": str(e),
                })
                all_success = False

        # Build user-facing summary
        content = self._build_result_summary(results, response.content)

        # Invalidate context cache (server state changed)
        if all_success:
            await self._context_service.invalidate(guild_id)

        return {
            "type": "action",
            "content": content,
            "tool_results": results,
        }

    def _build_result_summary(self, results: List[Dict], llm_text: str) -> str:
        """Build a human-readable summary of tool execution results."""
        if not results:
            return llm_text or "Done."

        lines = []
        for r in results:
            if r["success"]:
                result_data = r.get("result", {})
                name = result_data.get("name", result_data.get("id", ""))
                lines.append(f"✅ {r['tool']}: {name or 'success'}")
            else:
                lines.append(f"❌ {r['tool']}: {r.get('error', 'failed')}")

        summary = "\n".join(lines)

        # Prepend LLM's text if it said something
        if llm_text:
            return f"{llm_text}\n\n{summary}"
        return summary
