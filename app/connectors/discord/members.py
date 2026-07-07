"""
Discord Members Connector — Member moderation operations.

Actions: kick, ban, unban, mute, timeout, list
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class MembersConnector(BaseConnector):
    """Manages Discord guild members (moderation actions)."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def kick(
        self,
        guild: nextcord.Guild,
        member_id: int,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Kick a member from the guild.

        Args:
            guild: The target guild.
            member_id: ID of the member to kick.
            reason: Optional reason for the kick.

        Returns:
            Dict confirming the kick.
        """
        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found in guild")

        try:
            display_name = member.display_name
            await member.kick(reason=reason)
            logger.info(
                "Kicked member '%s' (id=%s) from guild '%s'. Reason: %s",
                display_name,
                member_id,
                guild.name,
                reason,
            )
            return {
                "kicked": True,
                "member_id": str(member_id),
                "member_name": display_name,
                "reason": reason,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("kick_members")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to kick member: {exc}")

    async def ban(
        self,
        guild: nextcord.Guild,
        member_id: int,
        reason: Optional[str] = None,
        delete_days: int = 0,
    ) -> Dict[str, Any]:
        """Ban a member from the guild.

        Args:
            guild: The target guild.
            member_id: ID of the member to ban.
            reason: Optional reason for the ban.
            delete_days: Number of days of messages to delete (0-7).

        Returns:
            Dict confirming the ban.
        """
        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found in guild")

        if not 0 <= delete_days <= 7:
            raise ValueError("delete_days must be between 0 and 7")

        try:
            display_name = member.display_name
            await member.ban(reason=reason, delete_message_days=delete_days)
            logger.info(
                "Banned member '%s' (id=%s) from guild '%s'. Reason: %s",
                display_name,
                member_id,
                guild.name,
                reason,
            )
            return {
                "banned": True,
                "member_id": str(member_id),
                "member_name": display_name,
                "reason": reason,
                "delete_days": delete_days,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("ban_members")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to ban member: {exc}")

    async def unban(
        self,
        guild: nextcord.Guild,
        user_id: int,
    ) -> Dict[str, Any]:
        """Unban a user from the guild.

        Args:
            guild: The target guild.
            user_id: ID of the user to unban.

        Returns:
            Dict confirming the unban.
        """
        try:
            user = await self._bot.fetch_user(int(user_id))
            await guild.unban(user)
            logger.info("Unbanned user '%s' (id=%s) from guild '%s'", user.name, user_id, guild.name)
            return {
                "unbanned": True,
                "user_id": str(user_id),
                "user_name": user.name,
            }
        except nextcord.errors.NotFound:
            raise ValueError(f"User '{user_id}' not found or not banned")
        except nextcord.errors.Forbidden:
            raise PermissionError("ban_members")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to unban user: {exc}")

    async def mute(
        self,
        guild: nextcord.Guild,
        member_id: int,
        duration_seconds: int,
    ) -> Dict[str, Any]:
        """Server-mute a member (voice mute).

        Args:
            guild: The target guild.
            member_id: ID of the member to mute.
            duration_seconds: Duration of the mute in seconds.

        Returns:
            Dict confirming the mute.
        """
        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found in guild")

        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")

        try:
            await member.edit(mute=True)
            logger.info(
                "Muted member '%s' (id=%s) in guild '%s' for %ds",
                member.display_name,
                member_id,
                guild.name,
                duration_seconds,
            )
            return {
                "muted": True,
                "member_id": str(member_id),
                "member_name": member.display_name,
                "duration_seconds": duration_seconds,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("mute_members")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to mute member: {exc}")

    async def timeout(
        self,
        guild: nextcord.Guild,
        member_id: int,
        duration_seconds: int,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Timeout a member (communication disabled).

        Args:
            guild: The target guild.
            member_id: ID of the member to timeout.
            duration_seconds: Duration of the timeout in seconds (max 28 days).
            reason: Optional reason for the timeout.

        Returns:
            Dict confirming the timeout.
        """
        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found in guild")

        max_timeout = 28 * 24 * 60 * 60  # 28 days
        if duration_seconds <= 0 or duration_seconds > max_timeout:
            raise ValueError(f"duration_seconds must be between 1 and {max_timeout}")

        try:
            delta = timedelta(seconds=duration_seconds)
            await member.edit(timeout=delta, reason=reason)
            logger.info(
                "Timed out member '%s' (id=%s) in guild '%s' for %ds. Reason: %s",
                member.display_name,
                member_id,
                guild.name,
                duration_seconds,
                reason,
            )
            return {
                "timed_out": True,
                "member_id": str(member_id),
                "member_name": member.display_name,
                "duration_seconds": duration_seconds,
                "reason": reason,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("moderate_members")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to timeout member: {exc}")

    async def list(
        self,
        guild: nextcord.Guild,
    ) -> Dict[str, Any]:
        """List all members in the guild.

        Args:
            guild: The target guild.

        Returns:
            Dict with member list.
        """
        members = []
        for member in guild.members:
            members.append({
                "id": str(member.id),
                "name": member.name,
                "display_name": member.display_name,
                "bot": member.bot,
                "roles": [str(r.id) for r in member.roles if r != guild.default_role],
                "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            })
        return {"members": members, "count": len(members)}

    async def get_info(
        self,
        guild: nextcord.Guild,
        member_id: int,
    ) -> Dict[str, Any]:
        """Get detailed info about a specific member including permissions.

        Args:
            guild: The target guild.
            member_id: Discord user ID.

        Returns:
            Dict with member info and guild_permissions.
        """
        member = guild.get_member(int(member_id))
        if member is None:
            # Try fetching if not in cache
            try:
                member = await guild.fetch_member(int(member_id))
            except (nextcord.errors.NotFound, nextcord.errors.HTTPException):
                raise ValueError(f"Member {member_id} not found in guild")

        return {
            "id": str(member.id),
            "name": member.name,
            "display_name": member.display_name,
            "bot": member.bot,
            "roles": [{"id": str(r.id), "name": r.name} for r in member.roles if r != guild.default_role],
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            "permissions": {
                "administrator": member.guild_permissions.administrator,
                "manage_guild": member.guild_permissions.manage_guild,
                "manage_channels": member.guild_permissions.manage_channels,
                "manage_roles": member.guild_permissions.manage_roles,
                "kick_members": member.guild_permissions.kick_members,
                "ban_members": member.guild_permissions.ban_members,
            },
        }

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "kick": self.kick,
            "ban": self.ban,
            "unban": self.unban,
            "mute": self.mute,
            "timeout": self.timeout,
            "list": self.list,
            "get_info": self.get_info,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for MembersConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for member operations."""
        return [
            ToolDefinition(
                name="discord.members.kick",
                description="Kick a member from the guild.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "member_id": {"type": "string", "description": "Member ID to kick."},
                        "reason": {"type": "string", "description": "Reason for kick (optional)."},
                    },
                    "required": ["guild_id", "member_id"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.members.ban",
                description="Ban a member from the guild. Most severe moderation action.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "member_id": {"type": "string", "description": "Member ID to ban."},
                        "reason": {"type": "string", "description": "Reason for ban (optional)."},
                        "delete_days": {"type": "integer", "description": "Days of messages to delete (0-7)."},
                    },
                    "required": ["guild_id", "member_id"],
                },
                risk_level="critical",
            ),
            ToolDefinition(
                name="discord.members.unban",
                description="Unban a previously banned user.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "user_id": {"type": "string", "description": "User ID to unban."},
                    },
                    "required": ["guild_id", "user_id"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.members.mute",
                description="Server-mute a member (voice mute).",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "member_id": {"type": "string", "description": "Member ID to mute."},
                        "duration_seconds": {"type": "integer", "description": "Mute duration in seconds."},
                    },
                    "required": ["guild_id", "member_id", "duration_seconds"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.members.timeout",
                description="Timeout a member (disable communication).",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "member_id": {"type": "string", "description": "Member ID to timeout."},
                        "duration_seconds": {"type": "integer", "description": "Timeout duration in seconds (max 28 days)."},
                        "reason": {"type": "string", "description": "Reason for timeout (optional)."},
                    },
                    "required": ["guild_id", "member_id", "duration_seconds"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.members.list",
                description="List all members in the guild.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                    },
                    "required": ["guild_id"],
                },
                risk_level="low",
            ),
            ToolDefinition(
                name="discord.members.get_info",
                description="Get detailed info about a specific member including their guild permissions.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "member_id": {"type": "string", "description": "Member/user ID to look up."},
                    },
                    "required": ["guild_id", "member_id"],
                },
                risk_level="low",
                category="query",
            ),
        ]
