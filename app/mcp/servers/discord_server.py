"""
Discord MCP Server — Bridges Discord connectors into the MCP tool system.

Registers all Discord tools with naming convention: discord.{module}.{action}
(e.g. discord.channels.create, discord.roles.assign, discord.members.ban).

Requires a bot reference (set via set_bot()) and a guild resolver.
"""

from __future__ import annotations

import logging
from typing import Optional

import nextcord

from app.connectors.discord.connector import DiscordConnector
from app.mcp.protocol import ToolDefinition
from app.mcp.server import MCPServer

logger = logging.getLogger(__name__)


class DiscordMCPServer(MCPServer):
    """MCP server that exposes Discord operations as tools.

    The server wraps the DiscordConnector facade, registering each
    sub-connector action as a tool with full metadata.
    """

    def __init__(self) -> None:
        super().__init__()
        self._bot: Optional[nextcord.Bot] = None
        self._connector: Optional[DiscordConnector] = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def set_bot(self, bot: nextcord.Bot) -> None:
        """Inject the bot instance and initialize connectors.

        Must be called after the bot is ready (on_ready event).
        """
        self._bot = bot
        self._connector = DiscordConnector(bot)
        self._register_all_tools()
        logger.info(
            "DiscordMCPServer initialized with %d tools",
            len(self._tools),
        )

    def _register_all_tools(self) -> None:
        """Register every tool from the DiscordConnector facade."""
        if self._connector is None:
            raise RuntimeError("Cannot register tools without a bot. Call set_bot() first.")

        tool_definitions = self._connector.get_all_tool_definitions()
        for tool_def in tool_definitions:
            # Create a handler closure for each tool
            handler = self._make_handler(tool_def.name)
            self.register_tool(tool_def, handler)

    def _make_handler(self, tool_name: str):
        """Create an async handler that delegates to the DiscordConnector.

        The handler resolves the guild from params and routes to the connector.
        """
        async def handler(**params) -> dict:
            if self._bot is None or self._connector is None:
                raise RuntimeError("Bot not initialized. Call set_bot() first.")

            # Extract guild_id from params
            guild_id = params.pop("guild_id", None)
            if guild_id is None:
                raise ValueError(
                    f"Tool '{tool_name}' requires 'guild_id' parameter"
                )

            guild = self._bot.get_guild(int(guild_id))
            if guild is None:
                raise ValueError(f"Guild '{guild_id}' not found or bot not in guild")

            return await self._connector.execute(tool_name, guild, **params)

        return handler

    # ------------------------------------------------------------------
    # MCPServer interface
    # ------------------------------------------------------------------

    def get_server_name(self) -> str:
        return "discord"
