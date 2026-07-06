"""
Discord Guild Connector — Guild-level configuration operations.

Actions: edit_name, edit_icon, get_info
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class GuildConnector(BaseConnector):
    """Manages Discord guild-level settings."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def edit_name(
        self,
        guild: nextcord.Guild,
        new_name: str,
    ) -> Dict[str, Any]:
        """Change the guild name.

        Args:
            guild: The target guild.
            new_name: The new guild name.

        Returns:
            Dict with old and new names.
        """
        if not new_name or not new_name.strip():
            raise ValueError("Guild name cannot be empty")

        try:
            old_name = guild.name
            await guild.edit(name=new_name)
            logger.info("Renamed guild '%s' -> '%s'", old_name, new_name)
            return {
                "old_name": old_name,
                "new_name": new_name,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit guild name: {exc}")

    async def edit_icon(
        self,
        guild: nextcord.Guild,
        icon_url: str,
    ) -> Dict[str, Any]:
        """Change the guild icon.

        Args:
            guild: The target guild.
            icon_url: URL of the new icon image.

        Returns:
            Dict confirming the change.
        """
        if not icon_url or not icon_url.strip():
            raise ValueError("Icon URL cannot be empty")

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(icon_url) as resp:
                    if resp.status != 200:
                        raise ValueError(f"Failed to fetch icon: HTTP {resp.status}")
                    icon_data = await resp.read()

            await guild.edit(icon=icon_data)
            logger.info("Updated icon for guild '%s'", guild.name)
            return {
                "guild_id": str(guild.id),
                "icon_updated": True,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit guild icon: {exc}")

    async def get_info(
        self,
        guild: nextcord.Guild,
    ) -> Dict[str, Any]:
        """Get detailed guild information.

        Args:
            guild: The target guild.

        Returns:
            Dict with guild details.
        """
        return {
            "id": str(guild.id),
            "name": guild.name,
            "description": guild.description,
            "owner_id": str(guild.owner_id),
            "member_count": guild.member_count,
            "channel_count": len(guild.channels),
            "role_count": len(guild.roles),
            "emoji_count": len(guild.emojis),
            "icon_url": str(guild.icon.url) if guild.icon else None,
            "created_at": guild.created_at.isoformat(),
            "verification_level": str(guild.verification_level),
            "premium_tier": guild.premium_tier,
            "premium_subscription_count": guild.premium_subscription_count,
        }

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "edit_name": self.edit_name,
            "edit_icon": self.edit_icon,
            "get_info": self.get_info,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for GuildConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for guild operations."""
        return [
            ToolDefinition(
                name="discord.guild.edit_name",
                description="Change the guild (server) name.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "new_name": {"type": "string", "description": "New guild name."},
                    },
                    "required": ["guild_id", "new_name"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.guild.edit_icon",
                description="Change the guild (server) icon.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "icon_url": {"type": "string", "description": "URL of the new icon image."},
                    },
                    "required": ["guild_id", "icon_url"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.guild.get_info",
                description="Get detailed guild information (name, member count, etc.).",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                    },
                    "required": ["guild_id"],
                },
                risk_level="low",
            ),
        ]
