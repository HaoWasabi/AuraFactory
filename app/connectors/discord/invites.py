"""Discord Invites Connector — kwargs pattern. Actions: create, delete, list"""

from __future__ import annotations
import logging
from typing import Any, Dict
import nextcord
from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class InvitesConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {"create": self.create, "delete": self.delete, "list": self.list}
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def create(self, guild: nextcord.Guild, channel_id: int, **kwargs) -> Dict[str, Any]:
        """Create invite. kwargs: max_age, max_uses, temporary"""
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found")

        max_age = kwargs.pop("max_age", 86400)
        max_uses = kwargs.pop("max_uses", 0)
        temporary = kwargs.pop("temporary", False)

        try:
            invite = await channel.create_invite(max_age=int(max_age), max_uses=int(max_uses), temporary=temporary)
            logger.info("Created invite '%s'", invite.code)
            return {"code": invite.code, "url": str(invite.url), "max_age": max_age, "max_uses": max_uses}
        except nextcord.Forbidden:
            raise PermissionError("create_instant_invite")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def delete(self, guild: nextcord.Guild, invite_code: str, **kwargs) -> Dict[str, Any]:
        """Revoke an invite."""
        try:
            invite = await self._bot.fetch_invite(invite_code)
            await invite.delete()
            return {"deleted": True, "code": invite_code}
        except nextcord.NotFound:
            raise ValueError(f"Invite '{invite_code}' not found")
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all active invites."""
        try:
            invites = await guild.invites()
            return {
                "invites": [
                    {"code": i.code, "url": str(i.url), "uses": i.uses, "max_uses": i.max_uses,
                     "channel": i.channel.name if i.channel else None}
                    for i in invites
                ],
                "count": len(invites),
            }
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
