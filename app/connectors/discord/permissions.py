"""
Discord Permissions Connector — Channel and role permission overrides.

Actions: set_channel_perms, set_role_perms, sync
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class PermissionsConnector(BaseConnector):
    """Manages Discord permission overrides."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def set_channel_perms(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        target_id: int,
        target_type: str = "role",
        **perms: Any,
    ) -> Dict[str, Any]:
        """Set permission overrides for a channel.

        Args:
            guild: The target guild.
            channel_id: Channel to modify.
            target_id: Role or member ID to set overrides for.
            target_type: 'role' or 'member'.
            **perms: Permission overrides (permission_name=True/False/None).

        Returns:
            Dict confirming the update.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        if target_type == "role":
            target = guild.get_role(int(target_id))
            if target is None:
                raise ValueError(f"Role '{target_id}' not found in guild")
        elif target_type == "member":
            target = guild.get_member(int(target_id))
            if target is None:
                raise ValueError(f"Member '{target_id}' not found in guild")
        else:
            raise ValueError(f"target_type must be 'role' or 'member', got '{target_type}'")

        if not perms:
            raise ValueError("No permission overrides provided")

        try:
            overwrite = nextcord.PermissionOverwrite(**perms)
            await channel.set_permissions(target, overwrite=overwrite)
            logger.info(
                "Set channel perms on '%s' for %s '%s': %s",
                channel.name,
                target_type,
                target_id,
                list(perms.keys()),
            )
            return {
                "channel_id": str(channel_id),
                "target_id": str(target_id),
                "target_type": target_type,
                "permissions_set": perms,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_permissions")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set channel permissions: {exc}")

    async def set_role_perms(
        self,
        guild: nextcord.Guild,
        role_id: int,
        **perms: Any,
    ) -> Dict[str, Any]:
        """Set base permissions for a role.

        Args:
            guild: The target guild.
            role_id: Role to modify.
            **perms: Permission values (permission_name=True/False).

        Returns:
            Dict confirming the update.
        """
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")

        if not perms:
            raise ValueError("No permissions provided")

        try:
            new_perms = nextcord.Permissions(**perms)
            await role.edit(permissions=new_perms)
            logger.info(
                "Set role perms for '%s' (id=%s): %s",
                role.name,
                role_id,
                list(perms.keys()),
            )
            return {
                "role_id": str(role_id),
                "role_name": role.name,
                "permissions_set": perms,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set role permissions: {exc}")

    async def sync(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        category_id: int,
    ) -> Dict[str, Any]:
        """Sync a channel's permissions with its parent category.

        Args:
            guild: The target guild.
            channel_id: Channel to sync.
            category_id: Category to sync from.

        Returns:
            Dict confirming the sync.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        category = guild.get_channel(int(category_id))
        if category is None or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found in guild")

        try:
            # Move channel under category with sync_permissions=True
            await channel.edit(category=category, sync_permissions=True)
            logger.info(
                "Synced permissions for channel '%s' with category '%s'",
                channel.name,
                category.name,
            )
            return {
                "channel_id": str(channel_id),
                "category_id": str(category_id),
                "synced": True,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to sync permissions: {exc}")

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "set_channel_perms": self.set_channel_perms,
            "set_role_perms": self.set_role_perms,
            "sync": self.sync,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for PermissionsConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for permission operations."""
        return [
            ToolDefinition(
                name="discord.permissions.set_channel_perms",
                description="Set permission overrides for a specific role/member on a channel.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID."},
                        "target_id": {"type": "string", "description": "Role or member ID."},
                        "target_type": {"type": "string", "enum": ["role", "member"], "description": "Target type."},
                    },
                    "required": ["guild_id", "channel_id", "target_id", "target_type"],
                    "additionalProperties": True,
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.permissions.set_role_perms",
                description="Set base permissions for a role.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "role_id": {"type": "string", "description": "Role ID."},
                    },
                    "required": ["guild_id", "role_id"],
                    "additionalProperties": True,
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.permissions.sync",
                description="Sync a channel's permissions with its parent category.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID to sync."},
                        "category_id": {"type": "string", "description": "Category ID to sync from."},
                    },
                    "required": ["guild_id", "channel_id", "category_id"],
                },
                risk_level="medium",
            ),
        ]
