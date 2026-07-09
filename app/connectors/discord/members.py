"""Discord Members Connector — kwargs pattern.

Actions: kick, ban, unban, bulk_ban, timeout, mute, purge, list, get_info
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class MembersConnector(BaseConnector):
    """Member moderation with **kwargs."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {
            "kick": self.kick,
            "ban": self.ban,
            "unban": self.unban,
            "bulk_ban": self.bulk_ban,
            "timeout": self.timeout,
            "mute": self.mute,
            "purge": self.purge,
            "list": self.list,
            "get_info": self.get_info,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'. Available: {list(actions.keys())}")
        return await handler(guild, **kwargs)

    # ------------------------------------------------------------------

    async def kick(self, guild: nextcord.Guild, member_id: int, **kwargs) -> Dict[str, Any]:
        """Kick a member."""
        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found")

        reason = kwargs.pop("reason", None)

        try:
            name = member.display_name
            await member.kick(reason=reason)
            logger.info("Kicked '%s' (id=%s)", name, member_id)
            return {"kicked": True, "member_id": str(member_id), "name": name, "reason": reason}
        except nextcord.Forbidden:
            raise PermissionError("kick_members")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to kick: {exc}")

    async def ban(self, guild: nextcord.Guild, member_id: int, **kwargs) -> Dict[str, Any]:
        """Ban a member. kwargs: reason, delete_message_seconds"""
        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found")

        reason = kwargs.pop("reason", None)
        delete_secs = kwargs.pop("delete_message_seconds", 0)

        try:
            name = member.display_name
            await member.ban(reason=reason, delete_message_seconds=int(delete_secs))
            logger.info("Banned '%s' (id=%s)", name, member_id)
            return {"banned": True, "member_id": str(member_id), "name": name, "reason": reason}
        except nextcord.Forbidden:
            raise PermissionError("ban_members")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to ban: {exc}")

    async def unban(self, guild: nextcord.Guild, user_id: int, **kwargs) -> Dict[str, Any]:
        """Unban a user."""
        reason = kwargs.pop("reason", None)

        try:
            user = await self._bot.fetch_user(int(user_id))
            await guild.unban(user, reason=reason)
            logger.info("Unbanned '%s' (id=%s)", user.name, user_id)
            return {"unbanned": True, "user_id": str(user_id), "name": user.name}
        except nextcord.NotFound:
            raise ValueError(f"User '{user_id}' not found or not banned")
        except nextcord.Forbidden:
            raise PermissionError("ban_members")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to unban: {exc}")

    async def bulk_ban(self, guild: nextcord.Guild, member_ids: List[int], **kwargs) -> Dict[str, Any]:
        """Ban multiple members at once."""
        reason = kwargs.pop("reason", None)
        delete_secs = kwargs.pop("delete_message_seconds", 0)

        success = []
        failed = []

        for mid in member_ids:
            member = guild.get_member(int(mid))
            if not member:
                failed.append({"id": str(mid), "error": "not found"})
                continue
            try:
                await member.ban(reason=reason, delete_message_seconds=int(delete_secs))
                success.append(str(mid))
            except Exception as e:
                failed.append({"id": str(mid), "error": str(e)})

        logger.info("Bulk ban: %d success, %d failed", len(success), len(failed))
        return {"banned_count": len(success), "failed": failed, "reason": reason}

    async def timeout(self, guild: nextcord.Guild, member_id: int, duration_minutes: int, **kwargs) -> Dict[str, Any]:
        """Timeout a member (disable communication)."""
        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found")

        max_minutes = 40320  # 28 days
        if duration_minutes <= 0 or duration_minutes > max_minutes:
            raise ValueError(f"duration_minutes must be 1-{max_minutes}")

        reason = kwargs.pop("reason", None)

        try:
            delta = timedelta(minutes=int(duration_minutes))
            await member.edit(timeout=delta, reason=reason)
            logger.info("Timed out '%s' for %d min", member.display_name, duration_minutes)
            return {
                "timed_out": True,
                "member_id": str(member_id),
                "name": member.display_name,
                "duration_minutes": duration_minutes,
                "reason": reason,
            }
        except nextcord.Forbidden:
            raise PermissionError("moderate_members")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to timeout: {exc}")

    async def mute(self, guild: nextcord.Guild, member_id: int, **kwargs) -> Dict[str, Any]:
        """Server-mute a member in voice."""
        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found")

        reason = kwargs.pop("reason", None)

        try:
            await member.edit(mute=True, reason=reason)
            logger.info("Muted '%s'", member.display_name)
            return {"muted": True, "member_id": str(member_id), "name": member.display_name}
        except nextcord.Forbidden:
            raise PermissionError("mute_members")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to mute: {exc}")

    async def purge(self, guild: nextcord.Guild, channel_id: int, **kwargs) -> Dict[str, Any]:
        """Delete messages in a channel."""
        channel = guild.get_channel(int(channel_id))
        if channel is None or not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Text channel '{channel_id}' not found")

        limit = kwargs.pop("limit", 10)
        member_id = kwargs.pop("member_id", None)

        def check(msg):
            if member_id:
                return msg.author.id == int(member_id)
            return True

        try:
            deleted = await channel.purge(limit=int(limit), check=check)
            logger.info("Purged %d messages in '%s'", len(deleted), channel.name)
            return {"purged": len(deleted), "channel_id": str(channel_id), "channel_name": channel.name}
        except nextcord.Forbidden:
            raise PermissionError("manage_messages")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to purge: {exc}")

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all members."""
        members = []
        for m in guild.members:
            members.append({
                "id": str(m.id),
                "name": m.name,
                "display_name": m.display_name,
                "bot": m.bot,
                "roles": [str(r.id) for r in m.roles if r != guild.default_role],
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            })
        return {"members": members, "count": len(members)}

    async def get_info(self, guild: nextcord.Guild, member_id: int, **kwargs) -> Dict[str, Any]:
        """Get detailed member info."""
        member = guild.get_member(int(member_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(member_id))
            except (nextcord.NotFound, nextcord.HTTPException):
                raise ValueError(f"Member '{member_id}' not found")

        return {
            "id": str(member.id),
            "name": member.name,
            "display_name": member.display_name,
            "bot": member.bot,
            "roles": [{"id": str(r.id), "name": r.name} for r in member.roles if r != guild.default_role],
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            "permissions": {name: val for name, val in member.guild_permissions if val},
            "timed_out": member.communication_disabled_until is not None,
        }
