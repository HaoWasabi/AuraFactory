"""Discord Permissions Connector — Channel and role permission overrides.

Actions: set_channel_perms, set_role_perms, sync
Uses **kwargs pattern consistent with all other connectors.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector, parse_permissions, permissions_to_dict

logger = logging.getLogger(__name__)


class PermissionsConnector(BaseConnector):
    """Manages Discord permission overrides via **kwargs pattern."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
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
        return await handler(guild, **kwargs)

    # ------------------------------------------------------------------
    # SET CHANNEL PERMISSIONS
    # ------------------------------------------------------------------

    async def set_channel_perms(
        self,
        guild: nextcord.Guild,
        channel_id: int = None,
        target_id: int = None,
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
        if not channel_id:
            raise ValueError("channel_id is required")
        if not target_id:
            raise ValueError("target_id is required")

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

        # Filter only valid permission names
        valid_perms = {}
        for key, value in perms.items():
            if hasattr(nextcord.PermissionOverwrite(), key):
                valid_perms[key] = value

        if not valid_perms:
            raise ValueError("No valid permission names found in provided params")

        try:
            overwrite = nextcord.PermissionOverwrite(**valid_perms)
            await channel.set_permissions(target, overwrite=overwrite)
            logger.info(
                "Set channel perms on '%s' for %s '%s': %s",
                channel.name, target_type, target_id, list(valid_perms.keys()),
            )
            return {
                "channel_id": str(channel_id),
                "channel_name": channel.name,
                "target_id": str(target_id),
                "target_type": target_type,
                "permissions_set": valid_perms,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_permissions")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set channel permissions: {exc}")

    # ------------------------------------------------------------------
    # SET ROLE PERMISSIONS
    # ------------------------------------------------------------------

    async def set_role_perms(
        self,
        guild: nextcord.Guild,
        role_id: int = None,
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
        if not role_id:
            raise ValueError("role_id is required")

        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")

        if not perms:
            raise ValueError("No permissions provided")

        # Filter valid permission names
        valid_perms = {}
        for key, value in perms.items():
            if hasattr(nextcord.Permissions(), key):
                valid_perms[key] = bool(value)

        if not valid_perms:
            raise ValueError("No valid permission names found")

        # Hierarchy check: cannot modify roles above bot's highest role
        bot_top_role = guild.me.top_role
        if role >= bot_top_role:
            raise PermissionError(
                f"Cannot modify role '{role.name}' — it is at or above bot's highest role"
            )

        try:
            new_perms = nextcord.Permissions(**valid_perms)
            await role.edit(permissions=new_perms)
            logger.info(
                "Set role perms for '%s' (id=%s): %s",
                role.name, role_id, list(valid_perms.keys()),
            )
            return {
                "role_id": str(role_id),
                "role_name": role.name,
                "permissions_set": valid_perms,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set role permissions: {exc}")

    # ------------------------------------------------------------------
    # SYNC CHANNEL WITH CATEGORY
    # ------------------------------------------------------------------

    async def sync(
        self,
        guild: nextcord.Guild,
        channel_id: int = None,
        category_id: int = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Sync a channel's permissions with its parent category.

        Args:
            guild: The target guild.
            channel_id: Channel to sync.
            category_id: Category to sync from (optional, uses channel's current category if omitted).

        Returns:
            Dict confirming the sync.
        """
        if not channel_id:
            raise ValueError("channel_id is required")

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        # Resolve category
        if category_id:
            category = guild.get_channel(int(category_id))
        else:
            category = channel.category

        if category is None or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(
                f"No valid category found (category_id={category_id}). "
                "Channel may not be in a category."
            )

        try:
            await channel.edit(sync_permissions=True, category=category)
            logger.info(
                "Synced channel '%s' permissions with category '%s'",
                channel.name, category.name,
            )
            return {
                "channel_id": str(channel_id),
                "channel_name": channel.name,
                "category_id": str(category.id),
                "category_name": category.name,
                "synced": True,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to sync permissions: {exc}")
