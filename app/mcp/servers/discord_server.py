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
    "discord.channels.move", "discord.channels.rename", "discord.channels.list",
    "discord.categories.create", "discord.categories.rename", "discord.categories.edit",
    "discord.categories.delete",
    "discord.categories.sync", "discord.categories.reorder", "discord.categories.list",
    "discord.roles.create", "discord.roles.bulk_create", "discord.roles.rename",
    "discord.roles.modify", "discord.roles.delete",
    "discord.roles.assign", "discord.roles.remove", "discord.roles.batch_assign",
    "discord.roles.clone", "discord.roles.set_position", "discord.roles.list",
    "discord.roles.get_info",
    "discord.members.kick", "discord.members.ban", "discord.members.unban",
    "discord.members.bulk_ban", "discord.members.timeout", "discord.members.mute",
    "discord.members.purge", "discord.members.list", "discord.members.get_info",
    "discord.guild.get_info", "discord.guild.edit_profile", "discord.guild.set_verification",
    "discord.guild.set_system_channels", "discord.guild.set_afk",
    "discord.guild.set_community", "discord.guild.set_preferred_locale",
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
    "discord.events.create", "discord.events.edit", "discord.events.delete",
    "discord.events.list",
    "discord.emojis.create", "discord.emojis.rename", "discord.emojis.delete",
    "discord.emojis.list",
    "discord.stickers.create", "discord.stickers.delete", "discord.stickers.list",
    "discord.permissions.set_channel_perms", "discord.permissions.set_role_perms",
    "discord.permissions.sync",
    "discord.soundboard.create", "discord.soundboard.delete", "discord.soundboard.list",
    "discord.onboarding.get", "discord.onboarding.setup",
    "discord.onboarding.setup_welcome", "discord.onboarding.send_dm",
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

        # Coerce all *_id params: float/scientific notation → proper int
        # Discord snowflakes exceed JSON Number precision (>2^53), LLM may return as float
        params = self._coerce_snowflake_ids(params)

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
    def _coerce_snowflake_ids(params: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce all *_id params from float/scientific notation to proper int.

        Discord snowflakes are 18-19 digit integers that exceed JSON Number
        precision (2^53). Gemini may return them as floats (e.g. 1.472e+18).
        This converts them back to correct integer values.

        Also handles: string IDs, list of IDs (member_ids, allowed_role_ids).
        """
        coerced = {}
        for key, value in params.items():
            if key.endswith("_id") or key.endswith("_ids"):
                if isinstance(value, float):
                    coerced[key] = int(value)
                elif isinstance(value, str):
                    # Handle string IDs: "1472162687994826775" or "1.472e+18"
                    try:
                        if "e" in value.lower() or "." in value:
                            coerced[key] = int(float(value))
                        else:
                            coerced[key] = int(value)
                    except (ValueError, OverflowError):
                        coerced[key] = value  # Pass through if not numeric
                elif isinstance(value, list):
                    coerced[key] = [self._coerce_single_id(v) for v in value]
                else:
                    coerced[key] = value
            else:
                coerced[key] = value
        return coerced

    @staticmethod
    def _coerce_single_id(value: Any) -> Any:
        """Coerce a single ID value to int."""
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                if "e" in value.lower() or "." in value:
                    return int(float(value))
                return int(value)
            except (ValueError, OverflowError):
                return value
        return value

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
