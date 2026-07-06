"""
Discord Invites Connector — Invite management operations.

Actions: create, delete, list
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class InvitesConnector(BaseConnector):
    """Manages Discord guild invites."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        max_age: int = 86400,
        max_uses: int = 0,
    ) -> Dict[str, Any]:
        """Create a new invite for a channel.

        Args:
            guild: The target guild.
            channel_id: Channel to create the invite for.
            max_age: Invite expiration in seconds (0 = never, default 86400 = 24h).
            max_uses: Max number of uses (0 = unlimited).

        Returns:
            Dict with invite info.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        try:
            invite = await channel.create_invite(
                max_age=max_age,
                max_uses=max_uses,
            )
            logger.info(
                "Created invite '%s' for channel '%s' in guild '%s'",
                invite.code,
                channel.name,
                guild.name,
            )
            return {
                "code": invite.code,
                "url": str(invite.url),
                "channel_id": str(channel_id),
                "max_age": max_age,
                "max_uses": max_uses,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("create_instant_invite")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create invite: {exc}")

    async def delete(
        self,
        guild: nextcord.Guild,
        invite_code: str,
    ) -> Dict[str, Any]:
        """Delete (revoke) an invite by code.

        Args:
            guild: The target guild.
            invite_code: The invite code to revoke.

        Returns:
            Dict confirming deletion.
        """
        if not invite_code or not invite_code.strip():
            raise ValueError("Invite code cannot be empty")

        try:
            invite = await self._bot.fetch_invite(invite_code)
            await invite.delete()
            logger.info("Deleted invite '%s' from guild '%s'", invite_code, guild.name)
            return {"deleted": True, "invite_code": invite_code}
        except nextcord.errors.NotFound:
            raise ValueError(f"Invite '{invite_code}' not found")
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete invite: {exc}")

    async def list(
        self,
        guild: nextcord.Guild,
    ) -> Dict[str, Any]:
        """List all active invites in the guild.

        Args:
            guild: The target guild.

        Returns:
            Dict with invite list.
        """
        try:
            invites = await guild.invites()
            result = []
            for inv in invites:
                result.append({
                    "code": inv.code,
                    "url": str(inv.url),
                    "channel_id": str(inv.channel.id) if inv.channel else None,
                    "inviter": str(inv.inviter.id) if inv.inviter else None,
                    "uses": inv.uses,
                    "max_uses": inv.max_uses,
                    "max_age": inv.max_age,
                    "temporary": inv.temporary,
                })
            return {"invites": result, "count": len(result)}
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to list invites: {exc}")

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
                f"Unknown action '{action}' for InvitesConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for invite operations."""
        return [
            ToolDefinition(
                name="discord.invites.create",
                description="Create a new invite for a channel.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID for the invite."},
                        "max_age": {"type": "integer", "description": "Expiration in seconds (0=never, default 86400)."},
                        "max_uses": {"type": "integer", "description": "Max uses (0=unlimited)."},
                    },
                    "required": ["guild_id", "channel_id"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.invites.delete",
                description="Revoke an invite by its code.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "invite_code": {"type": "string", "description": "Invite code to revoke."},
                    },
                    "required": ["guild_id", "invite_code"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.invites.list",
                description="List all active invites in the guild.",
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
