"""
Discord Webhooks Connector — Webhook management operations.

Actions: create, delete, list
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import validate_kwargs

logger = logging.getLogger(__name__)


class WebhooksConnector(BaseConnector):
    """Manages Discord guild webhooks."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        name: str,
        avatar_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new webhook for a channel.

        Args:
            guild: The target guild.
            channel_id: Channel to create the webhook in.
            name: Webhook name.
            avatar_url: Optional avatar URL.

        Returns:
            Dict with webhook info.
        """
        if not name or not name.strip():
            raise ValueError("Webhook name cannot be empty")

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")
        if not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Channel '{channel_id}' is not a text channel")

        try:
            kwargs: Dict[str, Any] = {"name": name}
            if avatar_url:
                # Fetch avatar bytes
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(avatar_url) as resp:
                        if resp.status == 200:
                            kwargs["avatar"] = await resp.read()

            webhook = await channel.create_webhook(**kwargs)
            logger.info(
                "Created webhook '%s' (id=%s) in channel '%s'",
                name,
                webhook.id,
                channel.name,
            )
            return {
                "id": str(webhook.id),
                "name": webhook.name,
                "url": webhook.url,
                "channel_id": str(channel_id),
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_webhooks")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create webhook: {exc}")

    async def delete(
        self,
        guild: nextcord.Guild,
        webhook_id: int,
    ) -> Dict[str, Any]:
        """Delete a webhook by ID.

        Args:
            guild: The target guild.
            webhook_id: ID of the webhook to delete.

        Returns:
            Dict confirming deletion.
        """
        try:
            webhook = await self._bot.fetch_webhook(int(webhook_id))
            name = webhook.name
            await webhook.delete()
            logger.info("Deleted webhook '%s' (id=%s)", name, webhook_id)
            return {"deleted": True, "webhook_id": str(webhook_id), "name": name}
        except nextcord.errors.NotFound:
            raise ValueError(f"Webhook '{webhook_id}' not found")
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_webhooks")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete webhook: {exc}")

    async def list(
        self,
        guild: nextcord.Guild,
        channel_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """List webhooks in the guild or a specific channel.

        Args:
            guild: The target guild.
            channel_id: Optional channel ID to filter by.

        Returns:
            Dict with webhook list.
        """
        try:
            if channel_id is not None:
                channel = guild.get_channel(int(channel_id))
                if channel is None or not isinstance(channel, nextcord.TextChannel):
                    raise ValueError(f"Text channel '{channel_id}' not found")
                webhooks = await channel.webhooks()
            else:
                webhooks = await guild.webhooks()

            result = []
            for wh in webhooks:
                result.append({
                    "id": str(wh.id),
                    "name": wh.name,
                    "channel_id": str(wh.channel_id) if wh.channel_id else None,
                    "url": wh.url,
                })
            return {"webhooks": result, "count": len(result)}
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_webhooks")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to list webhooks: {exc}")

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "create": self.create,
            "delete": self.delete,
            "list": self.list,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for WebhooksConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for webhook operations."""
        return [
            ToolDefinition(
                name="discord.webhooks.create",
                description="Create a new webhook for a text channel.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID for the webhook."},
                        "name": {"type": "string", "description": "Webhook name."},
                        "avatar_url": {"type": "string", "description": "Avatar URL (optional)."},
                    },
                    "required": ["guild_id", "channel_id", "name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.webhooks.delete",
                description="Delete a webhook by ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "webhook_id": {"type": "string", "description": "Webhook ID to delete."},
                    },
                    "required": ["guild_id", "webhook_id"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.webhooks.list",
                description="List webhooks in the guild or a specific channel.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Filter by channel ID (optional)."},
                    },
                    "required": ["guild_id"],
                },
                risk_level="low",
            ),
        ]
