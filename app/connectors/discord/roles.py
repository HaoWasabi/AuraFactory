"""
Discord Roles Connector — Role management operations.

Actions: create, delete, rename, set_permissions, assign, remove
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class RolesConnector(BaseConnector):
    """Manages Discord guild roles."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        name: str,
        color: Optional[int] = None,
        permissions: Optional[dict] = None,
        hoist: bool = False,
        mentionable: bool = False,
    ) -> Dict[str, Any]:
        """Create a new role in the guild.

        Args:
            guild: The target guild.
            name: Role name.
            color: Color value as integer (optional).
            permissions: Permissions dict (optional).
            hoist: Whether to display separately in sidebar.
            mentionable: Whether the role can be mentioned.

        Returns:
            Dict with created role info.
        """
        if not name or not name.strip():
            raise ValueError("Role name cannot be empty")

        try:
            kwargs: Dict[str, Any] = {
                "name": name,
                "hoist": hoist,
                "mentionable": mentionable,
            }
            if color is not None:
                kwargs["color"] = nextcord.Color(int(color))
            if permissions is not None:
                kwargs["permissions"] = nextcord.Permissions(**permissions)

            role = await guild.create_role(**kwargs)
            logger.info("Created role '%s' (id=%s) in guild '%s'", name, role.id, guild.name)
            return {
                "id": str(role.id),
                "name": role.name,
                "color": role.color.value,
                "position": role.position,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create role: {exc}")

    async def delete(
        self,
        guild: nextcord.Guild,
        role_id: int,
    ) -> Dict[str, Any]:
        """Delete a role by ID.

        Args:
            guild: The target guild.
            role_id: ID of the role to delete.

        Returns:
            Dict confirming deletion.
        """
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")

        try:
            name = role.name
            await role.delete()
            logger.info("Deleted role '%s' (id=%s) from guild '%s'", name, role_id, guild.name)
            return {"deleted": True, "role_id": str(role_id), "name": name}
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete role: {exc}")

    async def rename(
        self,
        guild: nextcord.Guild,
        role_id: int,
        new_name: str,
    ) -> Dict[str, Any]:
        """Rename a role.

        Args:
            guild: The target guild.
            role_id: ID of the role to rename.
            new_name: The new role name.

        Returns:
            Dict with old and new names.
        """
        if not new_name or not new_name.strip():
            raise ValueError("New role name cannot be empty")

        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")

        try:
            old_name = role.name
            await role.edit(name=new_name)
            logger.info("Renamed role '%s' -> '%s' (id=%s)", old_name, new_name, role_id)
            return {
                "role_id": str(role_id),
                "old_name": old_name,
                "new_name": new_name,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to rename role: {exc}")

    async def set_permissions(
        self,
        guild: nextcord.Guild,
        role_id: int,
        permissions: dict,
    ) -> Dict[str, Any]:
        """Set permissions for a role.

        Args:
            guild: The target guild.
            role_id: ID of the role.
            permissions: Dict of permission_name -> bool.

        Returns:
            Dict confirming the update.
        """
        if not permissions:
            raise ValueError("Permissions dict cannot be empty")

        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")

        try:
            perms = nextcord.Permissions(**permissions)
            await role.edit(permissions=perms)
            logger.info(
                "Updated permissions for role '%s' (id=%s): %s",
                role.name,
                role_id,
                list(permissions.keys()),
            )
            return {
                "role_id": str(role_id),
                "name": role.name,
                "updated_permissions": permissions,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set permissions: {exc}")

    async def assign(
        self,
        guild: nextcord.Guild,
        member_id: int,
        role_id: int,
    ) -> Dict[str, Any]:
        """Assign a role to a member.

        Args:
            guild: The target guild.
            member_id: ID of the member.
            role_id: ID of the role to assign.

        Returns:
            Dict confirming the assignment.
        """
        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found in guild")

        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")

        try:
            await member.add_roles(role)
            logger.info(
                "Assigned role '%s' to member '%s' in guild '%s'",
                role.name,
                member.display_name,
                guild.name,
            )
            return {
                "member_id": str(member_id),
                "role_id": str(role_id),
                "role_name": role.name,
                "member_name": member.display_name,
                "assigned": True,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to assign role: {exc}")

    async def remove(
        self,
        guild: nextcord.Guild,
        member_id: int,
        role_id: int,
    ) -> Dict[str, Any]:
        """Remove a role from a member.

        Args:
            guild: The target guild.
            member_id: ID of the member.
            role_id: ID of the role to remove.

        Returns:
            Dict confirming the removal.
        """
        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found in guild")

        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")

        try:
            await member.remove_roles(role)
            logger.info(
                "Removed role '%s' from member '%s' in guild '%s'",
                role.name,
                member.display_name,
                guild.name,
            )
            return {
                "member_id": str(member_id),
                "role_id": str(role_id),
                "role_name": role.name,
                "member_name": member.display_name,
                "removed": True,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to remove role: {exc}")

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "create": self.create,
            "delete": self.delete,
            "rename": self.rename,
            "set_permissions": self.set_permissions,
            "assign": self.assign,
            "remove": self.remove,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for RolesConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for role operations."""
        return [
            ToolDefinition(
                name="discord.roles.create",
                description="Create a new role in the guild.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "name": {"type": "string", "description": "Role name."},
                        "color": {"type": "integer", "description": "Color as integer (optional)."},
                        "permissions": {"type": "object", "description": "Permissions dict (optional)."},
                        "hoist": {"type": "boolean", "description": "Display separately in sidebar."},
                        "mentionable": {"type": "boolean", "description": "Allow mentions."},
                    },
                    "required": ["guild_id", "name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.roles.delete",
                description="Delete a role from the guild. Irreversible.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "role_id": {"type": "string", "description": "Role ID to delete."},
                    },
                    "required": ["guild_id", "role_id"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.roles.rename",
                description="Rename an existing role.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "role_id": {"type": "string", "description": "Role ID to rename."},
                        "new_name": {"type": "string", "description": "The new name."},
                    },
                    "required": ["guild_id", "role_id", "new_name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.roles.set_permissions",
                description="Set permissions for a role.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "role_id": {"type": "string", "description": "Role ID."},
                        "permissions": {"type": "object", "description": "Dict of permission_name -> bool."},
                    },
                    "required": ["guild_id", "role_id", "permissions"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.roles.assign",
                description="Assign a role to a guild member.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "member_id": {"type": "string", "description": "Member ID."},
                        "role_id": {"type": "string", "description": "Role ID to assign."},
                    },
                    "required": ["guild_id", "member_id", "role_id"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.roles.remove",
                description="Remove a role from a guild member.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "member_id": {"type": "string", "description": "Member ID."},
                        "role_id": {"type": "string", "description": "Role ID to remove."},
                    },
                    "required": ["guild_id", "member_id", "role_id"],
                },
                risk_level="medium",
            ),
        ]
