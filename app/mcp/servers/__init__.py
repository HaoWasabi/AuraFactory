"""
MCP Servers — Built-in server implementations for AuraFactory.

Each server exposes a namespace of tools:
- DiscordMCPServer: discord.* tools (channels, roles, members, etc.)
- MemoryMCPServer: memory.* tools (recall, store, search, etc.)
- SkillsMCPServer: skills.* tools (list, get_by_category, validate_params)
"""

from app.mcp.servers.discord_server import DiscordMCPServer
from app.mcp.servers.memory_server import MemoryMCPServer
from app.mcp.servers.skills_server import SkillsMCPServer

__all__ = [
    "DiscordMCPServer",
    "MemoryMCPServer",
    "SkillsMCPServer",
]
