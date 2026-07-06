"""
Discord Emojis Connector — Custom emoji management operations.

Actions: add, delete, list
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class EmojisConnector(BaseConnector):
    """Manages Discord guild custom emojis."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def add(
        self,
        guild: nextcord.Guild,
        name: str,
        image_url: str,
    ) -> Dict[str, Any]:
        """Add a custom emoji to the guild.

        Args:
            guild: The target guild.
            name: Emoji name (alphanumeric + underscores).
            image_url: URL of the emoji image.

        Returns:
            Dict with created emoji info.
        """
        if not name or not name.strip():
            raise ValueError("Emoji name cannot be empty")

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200:
                        raise ValueError(f"Failed to fetch image from URL: HTTP {resp.status}")
                    image_data = await resp.read()

            emoji = await guild.create_custom_emoji(name=name, image=image_data)
            logger.info("Added emoji '%s' (id=%s) to guild '%s'", name, emoji.id, guild.name)
            return {
                "id": str(emoji.id),
                "name": emoji.name,
                "url": str(emoji.url),
                "animated": emoji.animated,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_emojis")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to add emoji: {exc}")

    async def delete(
        self,
        guild: nextcord.Guild,
        emoji_id: int,
    ) -> Dict[str, Any]:
        """Delete a custom emoji from the guild.

        Args:
            guild: The target guild.
            emoji_id: ID of the emoji to delete.

        Returns:
            Dict confirming deletion.
        """
        emoji = None
        for e in guild.emojis:
            if e.id == int(emoji_id):
                emoji = e
                break

        if emoji is None:
            raise ValueError(f"Emoji '{emoji_id}' not found in guild")

        try:
            name = emoji.name
            await guild.delete_emoji(emoji)
            logger.info("Deleted emoji '%s' (id=%s) from guild '%s'", name, emoji_id, guild.name)
            return {"deleted": True, "emoji_id": str(emoji_id), "name": name}
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_emojis")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete emoji: {exc}")

    async def list(
        self,
        guild: nextcord.Guild,
    ) -> Dict[str, Any]:
        """List all custom emojis in the guild.

        Args:
            guild: The target guild.

        Returns:
            Dict with emoji list.
        """
        emojis = []
        for emoji in guild.emojis:
            emojis.append({
                "id": str(emoji.id),
                "name": emoji.name,
                "animated": emoji.animated,
                "url": str(emoji.url),
            })
        return {"emojis": emojis, "count": len(emojis)}

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "add": self.add,
            "delete": self.delete,
            "list": self.list,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for EmojisConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for emoji operations."""
        return [
            ToolDefinition(
                name="discord.emojis.add",
                description="Add a custom emoji to the guild from an image URL.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "name": {"type": "string", "description": "Emoji name."},
                        "image_url": {"type": "string", "description": "Image URL for the emoji."},
                    },
                    "required": ["guild_id", "name", "image_url"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.emojis.delete",
                description="Delete a custom emoji from the guild.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "emoji_id": {"type": "string", "description": "Emoji ID to delete."},
                    },
                    "required": ["guild_id", "emoji_id"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.emojis.list",
                description="List all custom emojis in the guild.",
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
