"""Discord MCP Server — exposes Discord connector tools via the MCP protocol."""
from __future__ import annotations
from typing import Any, Dict, Optional

import nextcord as discord

from app.connectors.discord.connector import DiscordConnector
from app.mcp.client import MCPServer
from app.mcp.protocol import MCPRequest, MCPResponse, ToolDefinition


class DiscordMCPServer(MCPServer):
    """MCP server that wraps the Discord connector and exposes its tools."""

    def __init__(self) -> None:
        super().__init__()
        self._bot: Optional[discord.Client] = None
        self._connector: Optional[DiscordConnector] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def get_server_name(self) -> str:
        return "discord"

    def set_bot(self, bot: discord.Client) -> None:
        """Attach the running bot instance and initialise the connector + tools."""
        self._bot = bot
        self._connector = DiscordConnector(bot)
        self._register_tools()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        """Pull tool definitions from the connector and register handlers."""
        if self._connector is None:
            return

        for tool_def in self._connector.get_all_tool_definitions():
            # Create a handler closure that delegates to connector.execute()
            handler = self._make_handler(tool_def.name)
            self.register_tool(tool_def, handler)

    def _make_handler(self, tool_name: str):
        """Create an async handler for a specific tool."""
        async def _handler(**params: Any) -> Dict[str, Any]:
            return await self._execute_tool(tool_name, params)
        return _handler

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve guild from params and delegate execution to the connector."""
        if self._connector is None or self._bot is None:
            raise RuntimeError("Bot not attached — call set_bot() first.")

        # Resolve the guild if guild_id is provided
        guild: Optional[discord.Guild] = None
        guild_id = params.pop("guild_id", None)
        if guild_id is not None:
            guild = self._bot.get_guild(int(guild_id))
            if guild is None:
                raise ValueError(f"Guild {guild_id} not found or bot not a member.")

        # Delegate to the connector's unified execute interface
        result = await self._connector.execute(
            tool_name=tool_name,
            guild=guild,
            **params,
        )
        return result

    # ------------------------------------------------------------------
    # Override handle_request for any Discord-specific pre/post processing
    # ------------------------------------------------------------------

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Handle an MCP request with Discord-specific context."""
        if self._bot is None:
            return MCPResponse(
                error="Discord bot not initialized. Call set_bot() first.",
                request_id=request.request_id,
            )
        return await super().handle_request(request)
