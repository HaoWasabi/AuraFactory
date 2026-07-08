"""Discord Members Connector — SPEC v2 rewrite.

Uses **kwargs pattern with validation whitelist.
Moderation actions: kick, ban, unban, bulk_ban, timeout, purge, get_info.

Actions: kick, ban, unban, bulk_ban, timeout, purge, get_info
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import check_role_hierarchy, validate_kwargs

logger = logging.getLogger(__name__)


class MembersConnector(BaseConnector):
    """Manages Discord guild members (moderation actions)."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def kick(self, guild: nextcord.Guild, member_id: int, **kwargs) -> Dict[str, Any]:
        """Kick a member from the guild.

        Required: member_id
        Optional: reason
        """
        perm_error = check_bot_permissions(guild, "discord.members.kick")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.members.kick", kwargs)

        member = guild.get_member(int(member_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(member_id))
            except Exception:
                raise ValueError(f"Member '{member_id}' not found in guild")

        # Role hierarchy check
        hierarchy_error = check_role_hierarchy(guild, member)
        if hierarchy_error:
            raise PermissionError(hierarchy_error)

        reason = clean.get("reason", "AI Agent Request")

        try:
            display_name = member.display_name
            await member.kick(reason=reason)
            logger.info("Kicked member '%s' (id=%s) from guild '%s'", display_name, member_id, guild.name)
            return {
                "id": str(member_id),
                "name": display_name,
                "action": "kick",
                "reason": reason,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Kick Members' permission or role hierarchy issue.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to kick member: {exc}")

    async def ban(self, guild: nextcord.Guild, member_id: int, **kwargs) -> Dict[str, Any]:
        """Ban a member from the guild.

        Required: member_id
        Optional: delete_message_seconds (max 604800 = 7 days), reason
        """
        perm_error = check_bot_permissions(guild, "discord.members.ban")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.members.ban", kwargs)

        # Check hierarchy if member is still in guild
        member = guild.get_member(int(member_id))
        if member:
            hierarchy_error = check_role_hierarchy(guild, member)
            if hierarchy_error:
                raise PermissionError(hierarchy_error)

        delete_message_seconds = int(clean.get("delete_message_seconds", 0))
        # Clamp to Discord max (7 days)
        delete_message_seconds = min(max(delete_message_seconds, 0), 604800)
        reason = clean.get("reason", "AI Agent Request")

        try:
            member_name = member.display_name if member else f"User ID: {member_id}"
            await guild.ban(
                nextcord.Object(id=int(member_id)),
                delete_message_seconds=delete_message_seconds,
                reason=reason,
            )
            logger.info("Banned member '%s' (id=%s) from guild '%s'", member_name, member_id, guild.name)
            return {
                "id": str(member_id),
                "name": member_name,
                "action": "ban",
                "delete_message_seconds": delete_message_seconds,
                "reason": reason,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Ban Members' permission or role hierarchy issue.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to ban member: {exc}")

    async def unban(self, guild: nextcord.Guild, member_id: int, **kwargs) -> Dict[str, Any]:
        """Unban a previously banned user.

        Required: member_id
        Optional: reason
        """
        perm_error = check_bot_permissions(guild, "discord.members.unban")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.members.unban", kwargs)
        reason = clean.get("reason", "AI Agent Request")

        try:
            user_obj = nextcord.Object(id=int(member_id))
            await guild.unban(user_obj, reason=reason)
            logger.info("Unbanned user (id=%s) from guild '%s'", member_id, guild.name)
            return {"id": str(member_id), "action": "unban", "reason": reason}
        except nextcord.errors.NotFound:
            raise ValueError(f"User '{member_id}' is not in the ban list.")
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Ban Members' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to unban: {exc}")

    async def bulk_ban(self, guild: nextcord.Guild, member_ids: List[int], **kwargs) -> Dict[str, Any]:
        """Ban multiple members at once (max 200).

        CRITICAL action — requires double confirmation from approval layer.

        Required: member_ids (list of user IDs)
        Optional: delete_message_seconds, reason
        """
        perm_error = check_bot_permissions(guild, "discord.members.bulk_ban")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.members.bulk_ban", kwargs)

        if not member_ids or len(member_ids) == 0:
            raise ValueError("member_ids list cannot be empty.")
        if len(member_ids) > 200:
            raise ValueError("Cannot bulk ban more than 200 members at once.")

        delete_message_seconds = int(clean.get("delete_message_seconds", 0))
        delete_message_seconds = min(max(delete_message_seconds, 0), 604800)
        reason = clean.get("reason", "AI Agent Bulk Ban")

        # Use Discord bulk ban endpoint via HTTP if available
        try:
            payload = {
                "user_ids": [str(uid) for uid in member_ids],
                "delete_message_seconds": delete_message_seconds,
            }
            # Try nextcord bulk_ban if available (newer versions)
            if hasattr(guild, "bulk_ban"):
                result = await guild.bulk_ban(
                    [nextcord.Object(id=int(uid)) for uid in member_ids],
                    delete_message_seconds=delete_message_seconds,
                    reason=reason,
                )
                banned_count = len(member_ids)
            else:
                # Fallback: use HTTP directly
                await guild._state.http.request(
                    nextcord.http.Route(
                        "POST", "/guilds/{guild_id}/bulk-ban", guild_id=guild.id
                    ),
                    json=payload,
                    reason=reason,
                )
                banned_count = len(member_ids)

            logger.info("Bulk banned %d members from guild '%s'", banned_count, guild.name)
            return {
                "action": "bulk_ban",
                "banned_count": banned_count,
                "member_ids": [str(uid) for uid in member_ids],
                "reason": reason,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Ban Members' permission for bulk ban.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to bulk ban: {exc}")

    async def timeout(self, guild: nextcord.Guild, member_id: int, duration_minutes: int, **kwargs) -> Dict[str, Any]:
        """Timeout (mute) a member for a specified duration.

        Required: member_id, duration_minutes (0 = remove timeout)
        Optional: reason
        """
        perm_error = check_bot_permissions(guild, "discord.members.timeout")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.members.timeout", kwargs)

        member = guild.get_member(int(member_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(member_id))
            except Exception:
                raise ValueError(f"Member '{member_id}' not found in guild")

        # Hierarchy check
        hierarchy_error = check_role_hierarchy(guild, member)
        if hierarchy_error:
            raise PermissionError(hierarchy_error)

        reason = clean.get("reason", "AI Agent Request")

        try:
            if duration_minutes > 0:
                # Apply timeout
                delta = timedelta(minutes=duration_minutes)
                # Discord max timeout = 28 days
                max_delta = timedelta(days=28)
                if delta > max_delta:
                    delta = max_delta
                await member.timeout(delta, reason=reason)
                action = "timeout"
            else:
                # Remove timeout
                await member.timeout(None, reason=reason)
                action = "untimeout"

            logger.info(
                "%s member '%s' (id=%s) for %d min",
                action, member.display_name, member_id, duration_minutes,
            )
            return {
                "id": str(member_id),
                "name": member.display_name,
                "action": action,
                "duration_minutes": duration_minutes,
                "reason": reason,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Moderate Members' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to timeout member: {exc}")

    async def purge(self, guild: nextcord.Guild, channel_id: int, **kwargs) -> Dict[str, Any]:
        """Bulk delete messages from a channel.

        CRITICAL action.

        Required: channel_id
        Optional: limit (default 100, max 1000), member_id (filter by author)
        """
        perm_error = check_bot_permissions(guild, "discord.members.purge")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.members.purge", kwargs)

        channel = guild.get_channel(int(channel_id))
        if channel is None or not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Text channel '{channel_id}' not found.")

        limit = min(int(clean.get("limit", 100)), 1000)
        filter_member_id = clean.get("member_id")

        try:
            check_fn = None
            if filter_member_id:
                def check_fn(msg):
                    return msg.author.id == int(filter_member_id)

            deleted = await channel.purge(limit=limit, check=check_fn)
            logger.info("Purged %d messages from channel '%s'", len(deleted), channel.name)
            return {
                "channel_id": str(channel_id),
                "channel_name": channel.name,
                "action": "purge",
                "deleted_count": len(deleted),
                "limit_requested": limit,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Messages' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to purge messages: {exc}")

    async def get_info(self, guild: nextcord.Guild, member_id: int, **kwargs) -> Dict[str, Any]:
        """Get detailed info about a member.

        Required: member_id
        """
        member = guild.get_member(int(member_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(member_id))
            except Exception:
                raise ValueError(f"Member '{member_id}' not found in guild")

        roles = [{"id": str(r.id), "name": r.name} for r in member.roles if not r.is_default()]

        return {
            "id": str(member.id),
            "name": member.name,
            "display_name": member.display_name,
            "discriminator": member.discriminator,
            "bot": member.bot,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            "created_at": member.created_at.isoformat() if member.created_at else None,
            "top_role": {"id": str(member.top_role.id), "name": member.top_role.name},
            "roles": roles,
            "permissions": {
                "administrator": member.guild_permissions.administrator,
                "manage_guild": member.guild_permissions.manage_guild,
                "manage_channels": member.guild_permissions.manage_channels,
                "manage_roles": member.guild_permissions.manage_roles,
                "kick_members": member.guild_permissions.kick_members,
                "ban_members": member.guild_permissions.ban_members,
            },
            "timed_out": member.communication_disabled_until is not None,
            "timeout_until": (
                member.communication_disabled_until.isoformat()
                if member.communication_disabled_until
                else None
            ),
        }
