"""Discord Webhooks Connector — kwargs pattern. Actions: create, delete, list"""

from __future__ import annotations
import logging
from typing import Any, Dict, Optional
import aiohttp
import nextcord
from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class WebhooksConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {"create": self.create, "delete": self.delete, "list": self.list}
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def create(self, guild: nextcord.Guild, channel_id: int, name: str, **kwargs) -> Dict[str, Any]:
        """Create webhook. kwargs: avatar_url, reason"""
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Text channel '{channel_id}' not found")

        create_kwargs: Dict[str, Any] = {"name": name}
        avatar_url = kwargs.pop("avatar_url", None)
        if avatar_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as resp:
                    if resp.status == 200:
                        create_kwargs["avatar"] = await resp.read()

        reason = kwargs.pop("reason", None)
        if reason:
            create_kwargs["reason"] = reason

        try:
            wh = await channel.create_webhook(**create_kwargs)
            logger.info("Created webhook '%s' (id=%s)", name, wh.id)
            return {"id": str(wh.id), "name": wh.name, "url": wh.url, "channel_id": str(channel_id)}
        except nextcord.Forbidden:
            raise PermissionError("manage_webhooks")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def delete(self, guild: nextcord.Guild, webhook_id: int, **kwargs) -> Dict[str, Any]:
        """Delete a webhook."""
        try:
            wh = await self._bot.fetch_webhook(int(webhook_id))
            name = wh.name
            await wh.delete(reason=kwargs.pop("reason", None))
            return {"deleted": True, "id": str(webhook_id), "name": name}
        except nextcord.NotFound:
            raise ValueError(f"Webhook '{webhook_id}' not found")
        except nextcord.Forbidden:
            raise PermissionError("manage_webhooks")

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List webhooks."""
        channel_id = kwargs.get("channel_id")
        try:
            if channel_id:
                ch = guild.get_channel(int(channel_id))
                if isinstance(ch, nextcord.TextChannel):
                    webhooks = await ch.webhooks()
                else:
                    raise ValueError(f"Text channel '{channel_id}' not found")
            else:
                webhooks = await guild.webhooks()

            return {
                "webhooks": [{"id": str(w.id), "name": w.name, "url": w.url, "channel_id": str(w.channel_id)} for w in webhooks],
                "count": len(webhooks),
            }
        except nextcord.Forbidden:
            raise PermissionError("manage_webhooks")
