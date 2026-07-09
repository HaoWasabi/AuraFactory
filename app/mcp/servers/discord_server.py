"""Discord MCP Server — routes discord.* tool calls to DiscordConnector.

The new connector uses pure **kwargs pattern — no ToolDefinition objects needed.
UnifiedAgent imports TOOL_DEFINITIONS from app.core.tool_definitions.
This server just needs to:
  1. Hold bot reference
  2. Resolve guild from guild_id
  3. Route to connector.execute(tool_name, guild, **params)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import nextcord as discord

from app.connectors.discord.connector import DiscordConnector
from app.mcp.client import MCPServer
from app.mcp.protocol import MCPRequest, MCPResponse, ToolDefinition, RiskLevel

logger = logging.getLogger(__name__)

# All supported tool names — used for MCP client routing index
# These match TOOL_NAME_MAP in app/core/tool_definitions.py
_ALL_TOOL_NAMES = [
    "discord.channels.create", "discord.channels.edit", "discord.channels.delete",
    "discord.channels.move", "discord.channels.list",
    "discord.categories.create", "discord.categories.edit", "discord.categories.delete",
    "discord.categories.sync", "discord.categories.reorder", "discord.categories.list",
    "discord.roles.create", "discord.roles.modify", "discord.roles.delete",
    "discord.roles.assign", "discord.roles.remove", "discord.roles.batch_assign",
    "discord.roles.clone", "discord.roles.set_position", "discord.roles.list",
    "discord.roles.get_info",
    "discord.members.kick", "discord.members.ban", "discord.members.unban",
    "discord.members.bulk_ban", "discord.members.timeout", "discord.members.mute",
    "discord.members.purge", "discord.members.list", "discord.members.get_info",
    "discord.guild.get_info", "discord.guild.edit_profile", "discord.guild.set_verification",
    "discord.guild.set_system_channels", "discord.guild.set_afk",
    "discord.guild.set_notifications", "discord.guild.set_widget",
    "discord.webhooks.create", "discord.webhooks.delete", "discord.webhooks.list",
    "discord.threads.create", "discord.threads.archive", "discord.threads.delete",
    "discord.invites.create", "discord.invites.delete", "discord.invites.list",
    "discord.automod.create_rule", "discord.automod.delete_rule", "discord.automod.list_rules",
    "discord.backup.export", "discord.backup.restore",
    "discord.features.setup_verification", "discord.features.create_poll",
    "discord.features.setup_welcome", "discord.features.configure_auto_delete",
    "discord.audit.query",
    "discord.safety.set_content_filter", "discord.safety.set_mfa",
    "discord.templates.create", "discord.templates.sync", "discord.templates.delete",
]


class DiscordMCPServer(MCPServer):
    """MCP server that routes all discord.* calls to DiscordConnector."""

    def __init__(self) -> None:
        super().__init__()
        self._bot: Optional[discord.Client] = None
        self._connector: Optional[DiscordConnector] = None

    def get_server_name(self) -> str:
        return "discord"

    def set_bot(self, bot: discord.Client) -> None:
        """Attach running bot instance → init connector + register all tool routes."""
        self._bot = bot
        self._connector = DiscordConnector(bot)
        self._register_all_tools()
        logger.info(
            "DiscordMCPServer: bot attached, %d tools registered, %d modules",
            len(_ALL_TOOL_NAMES), self._connector.module_count,
        )

    def _register_all_tools(self) -> None:
        """Register all known tool names with a universal handler.

        Each tool gets a minimal ToolDefinition (name only) for MCPClient routing.
        The actual schema lives in TOOL_DEFINITIONS (app/core/tool_definitions.py) and tools_spec.yaml.
        """
        for tool_name in _ALL_TOOL_NAMES:
            tool_def = ToolDefinition(
                name=tool_name,
                description=f"Discord operation: {tool_name}",
                parameters={},
                risk_level=self._infer_risk(tool_name),
            )
            handler = self._make_handler(tool_name)
            self.register_tool(tool_def, handler)

    def _make_handler(self, tool_name: str):
        """Create async handler that routes to connector.execute()."""
        async def _handler(**params: Any) -> Dict[str, Any]:
            return await self._execute_tool(tool_name, params)
        return _handler

    async def _execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve guild + delegate to connector."""
        if self._connector is None or self._bot is None:
            raise RuntimeError("Bot not attached — call set_bot() first.")

        # Resolve guild from guild_id param
        guild: Optional[discord.Guild] = None
        guild_id = params.pop("guild_id", None)
        if guild_id is not None:
            guild = self._bot.get_guild(int(guild_id))
            if guild is None:
                raise ValueError(f"Guild {guild_id} not found or bot not a member.")

        if guild is None:
            raise ValueError("guild_id is required for Discord operations.")

        # Delegate to connector (it handles module.action routing)
        return await self._connector.execute(tool_name=tool_name, guild=guild, **params)

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Handle MCP request with bot-ready check."""
        if self._bot is None:
            return MCPResponse(
                error="Discord bot not initialized. Call set_bot() first.",
                request_id=request.request_id,
            )
        return await super().handle_request(request)

    @staticmethod
    def _infer_risk(tool_name: str) -> str:
        """Infer risk level from tool name pattern."""
        action = tool_name.split(".")[-1] if "." in tool_name else ""
        if action in ("delete", "ban", "bulk_ban", "restore", "set_mfa"):
            return "high"
        if action in ("kick", "timeout", "purge"):
            return "high"
        if action in ("create", "modify", "edit", "assign", "remove"):
            return "medium"
        return "low"
