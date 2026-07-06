"""MCP Servers — Built-in server implementations for AuraFactory.

Each server exposes a namespace of tools:
- DiscordMCPServer: discord.* tools (channels, roles, members, etc.)
- MemoryMCPServer: memory.* tools (recall, store, search, etc.)
- SkillsMCPServer: skills.* tools (list, get_by_category, validate_params)
"""
import logging

from app.mcp.servers.discord_server import DiscordMCPServer
from app.mcp.servers.memory_server import MemoryMCPServer
from app.mcp.servers.skills_server import SkillsMCPServer

logger = logging.getLogger(__name__)


async def register_all_servers(mcp_client) -> None:
    """Register all built-in MCP servers with the client."""
    servers = [
        DiscordMCPServer(),
        MemoryMCPServer(),
        SkillsMCPServer(),
    ]
    for server in servers:
        try:
            mcp_client.register_server(server)
            logger.info(f"Registered MCP server: {server.get_server_name()}")
        except Exception as e:
            logger.warning(f"Failed to register {server.__class__.__name__}: {e}")


__all__ = [
    "DiscordMCPServer",
    "MemoryMCPServer",
    "SkillsMCPServer",
    "register_all_servers",
]
