"""
Discord Channels Connector — Channel CRUD operations.

Actions: create, delete, rename, move, edit, list
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class ChannelsConnector(BaseConnector):
    """Manages Discord guild channels."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        name: str,
        type: str = "text",
        category_id: Optional[int] = None,
        topic: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new channel in the guild.

        Args:
            guild: The target guild.
            name: Channel name.
            type: Channel type ('text' or 'voice').
            category_id: Optional parent category ID.
            topic: Optional channel topic (text channels only).

        Returns:
            Dict with created channel info.
        """
        if not name or not name.strip():
            raise ValueError("Channel name cannot be empty")

        category = None
        if category_id is not None:
            category = guild.get_channel(int(category_id))
            if category is None or not isinstance(category, nextcord.CategoryChannel):
                raise ValueError(f"Category '{category_id}' not found")

        try:
            if type == "voice":
                channel = await guild.create_voice_channel(
                    name=name,
                    category=category,
                )
            else:
                channel = await guild.create_text_channel(
                    name=name,
                    category=category,
                    topic=topic,
                )
            logger.info("Created channel '%s' (id=%s) in guild '%s'", name, channel.id, guild.name)
            return {
                "id": str(channel.id),
                "name": channel.name,
                "type": str(channel.type),
                "category_id": str(channel.category_id) if channel.category_id else None,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create channel: {exc}")

    async def delete(
        self,
        guild: nextcord.Guild,
        channel_id: int,
    ) -> Dict[str, Any]:
        """Delete a channel by ID.

        Args:
            guild: The target guild.
            channel_id: ID of the channel to delete.

        Returns:
            Dict confirming deletion.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        try:
            name = channel.name
            await channel.delete()
            logger.info("Deleted channel '%s' (id=%s) from guild '%s'", name, channel_id, guild.name)
            return {"deleted": True, "channel_id": str(channel_id), "name": name}
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete channel: {exc}")

    async def rename(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        new_name: str,
    ) -> Dict[str, Any]:
        """Rename a channel.

        Args:
            guild: The target guild.
            channel_id: ID of the channel to rename.
            new_name: The new channel name.

        Returns:
            Dict with old and new names.
        """
        if not new_name or not new_name.strip():
            raise ValueError("New channel name cannot be empty")

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        try:
            old_name = channel.name
            await channel.edit(name=new_name)
            logger.info("Renamed channel '%s' -> '%s' (id=%s)", old_name, new_name, channel_id)
            return {
                "channel_id": str(channel_id),
                "old_name": old_name,
                "new_name": new_name,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to rename channel: {exc}")

    async def move(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        category_id: int,
        position: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Move a channel to a different category.

        Args:
            guild: The target guild.
            channel_id: ID of the channel to move.
            category_id: Destination category ID.
            position: Optional position within the category.

        Returns:
            Dict confirming the move.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        category = guild.get_channel(int(category_id))
        if category is None or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found")

        try:
            kwargs: Dict[str, Any] = {"category": category}
            if position is not None:
                kwargs["position"] = int(position)
            await channel.edit(**kwargs)
            logger.info(
                "Moved channel '%s' to category '%s'",
                channel.name,
                category.name,
            )
            return {
                "channel_id": str(channel_id),
                "new_category_id": str(category_id),
                "position": position,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to move channel: {exc}")

    async def edit(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Edit channel properties.

        Args:
            guild: The target guild.
            channel_id: ID of the channel to edit.
            **kwargs: Properties to update (name, topic, nsfw, slowmode_delay, etc.).

        Returns:
            Dict with updated properties.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        if not kwargs:
            raise ValueError("No edit parameters provided")

        try:
            await channel.edit(**kwargs)
            logger.info("Edited channel '%s' (id=%s): %s", channel.name, channel_id, list(kwargs.keys()))
            return {
                "channel_id": str(channel_id),
                "updated_fields": list(kwargs.keys()),
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit channel: {exc}")

    async def list(
        self,
        guild: nextcord.Guild,
    ) -> Dict[str, Any]:
        """List all channels in the guild.

        Args:
            guild: The target guild.

        Returns:
            Dict with channel list.
        """
        channels = []
        for ch in guild.channels:
            channels.append({
                "id": str(ch.id),
                "name": ch.name,
                "type": str(ch.type),
                "category_id": str(ch.category_id) if ch.category_id else None,
                "position": ch.position,
            })
        return {"channels": channels, "count": len(channels)}

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "create": self.create,
            "delete": self.delete,
            "rename": self.rename,
            "move": self.move,
            "edit": self.edit,
            "list": self.list,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for ChannelsConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for channel operations."""
        return [
            ToolDefinition(
                name="discord.channels.create",
                description="Create a new text or voice channel in the guild.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "name": {"type": "string", "description": "Channel name."},
                        "type": {"type": "string", "enum": ["text", "voice"], "description": "Channel type."},
                        "category_id": {"type": "string", "description": "Parent category ID (optional)."},
                        "topic": {"type": "string", "description": "Channel topic (text only, optional)."},
                    },
                    "required": ["guild_id", "name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.channels.delete",
                description="Delete a channel from the guild. Irreversible.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID to delete."},
                    },
                    "required": ["guild_id", "channel_id"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.channels.rename",
                description="Rename an existing channel.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID to rename."},
                        "new_name": {"type": "string", "description": "The new name."},
                    },
                    "required": ["guild_id", "channel_id", "new_name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.channels.move",
                description="Move a channel to a different category.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID to move."},
                        "category_id": {"type": "string", "description": "Destination category ID."},
                        "position": {"type": "integer", "description": "Position within category (optional)."},
                    },
                    "required": ["guild_id", "channel_id", "category_id"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.channels.edit",
                description="Edit channel properties (topic, nsfw, slowmode, etc.).",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID to edit."},
                    },
                    "required": ["guild_id", "channel_id"],
                    "additionalProperties": True,
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.channels.list",
                description="List all channels in the guild.",
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
