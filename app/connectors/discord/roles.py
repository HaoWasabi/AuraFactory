"""
Discord Roles Connector — Advanced Role management operations.

Actions: create, delete, rename, set_permissions, assign, remove, list,
         modify, clone, get_info, bulk_create, batch_assign, set_position
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition
from app.connectors.discord._helpers import coerce_color, coerce_permissions, merge_permissions
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import check_role_hierarchy, validate_kwargs

logger = logging.getLogger(__name__)


class RolesConnector(BaseConnector):
    """Manages Discord guild roles with advanced agentic capabilities."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_color(color: Any) -> Optional[nextcord.Color]:
        """Normalize color input: hex string, integer, or None."""
        if color is None:
            return None
        if isinstance(color, str):
            return nextcord.Color(int(color.lstrip("#"), 16))
        if isinstance(color, int):
            return nextcord.Color(color)
        return None

    @staticmethod
    def _parse_permissions(permissions_dict: Dict[str, bool]) -> nextcord.Permissions:
        """Convert a permission dict to a nextcord.Permissions object (set only)."""
        perms = nextcord.Permissions.none()
        for perm_name, value in permissions_dict.items():
            if hasattr(perms, perm_name) and isinstance(value, bool):
                setattr(perms, perm_name, value)
        return perms

    @staticmethod
    def _merge_permissions(
        base: nextcord.Permissions,
        updates: Dict[str, bool],
    ) -> nextcord.Permissions:
        """Merge updates onto existing permissions without wiping unmentioned ones."""
        for perm_name, value in updates.items():
            if hasattr(base, perm_name) and isinstance(value, bool):
                setattr(base, perm_name, value)
        return base

    @staticmethod
    def _permissions_to_dict(perms: nextcord.Permissions) -> Dict[str, bool]:
        """Return only the True permission flags as a clean dict."""
        return {name: val for name, val in perms if val is True}

    @staticmethod
    def _role_to_dict(role: nextcord.Role) -> Dict[str, Any]:
        """Serialize a role to a safe JSON-ready dict."""
        return {
            "id": str(role.id),
            "name": role.name,
            "color": str(role.color),
            "color_value": role.color.value,
            "position": role.position,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "managed": role.managed,
            "member_count": len(role.members),
            "permissions": RolesConnector._permissions_to_dict(role.permissions),
        }

    def _guard_hierarchy(self, guild: nextcord.Guild, role: nextcord.Role) -> None:
        """Raise if bot cannot manage the target role due to hierarchy."""
        if role >= guild.me.top_role or role.is_default():
            raise PermissionError(
                f"Cannot manage role '{role.name}' — it is at or above the bot's highest role."
            )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        name: str,
        color: Optional[Any] = None,
        permissions: Optional[Dict[str, bool]] = None,
        hoist: bool = False,
        mentionable: bool = False,
        reason: str = "Created by AI Agent",
    ) -> Dict[str, Any]:
        """Create a new role with full attribute control.

        Args:
            guild: Target guild.
            name: Role name.
            color: Hex string ("#ff0000") or integer color value.
            permissions: Dict of permission_name -> bool.
            hoist: Display separately in the member list sidebar.
            mentionable: Allow @mention of this role.
            reason: Audit log reason.

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
                "reason": reason,
            }
            color_obj = self._parse_color(color)
            if color_obj is not None:
                kwargs["color"] = color_obj
            if permissions:
                kwargs["permissions"] = self._parse_permissions(permissions)

            role = await guild.create_role(**kwargs)
            logger.info("Created role '%s' (id=%s) in guild '%s'", name, role.id, guild.name)
            return self._role_to_dict(role)
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create role: {exc}")

    async def modify(
        self,
        guild: nextcord.Guild,
        role_id: int,
        name: Optional[str] = None,
        color: Optional[Any] = None,
        hoist: Optional[bool] = None,
        mentionable: Optional[bool] = None,
        permissions: Optional[Dict[str, bool]] = None,
        position: Optional[int] = None,
        reason: str = "Modified by AI Agent",
    ) -> Dict[str, Any]:
        """Full-featured role editor — change any combination of attributes at once.

        Unlike set_permissions (which replaces the whole permission set), this
        method MERGES the supplied permissions onto the existing ones so
        unmentioned permissions are preserved.

        Args:
            guild: Target guild.
            role_id: ID of the role to modify.
            name: New name (optional).
            color: New color — hex string or int (optional).
            hoist: Toggle sidebar display (optional).
            mentionable: Toggle mentionability (optional).
            permissions: Partial permission dict — only listed keys are changed.
            position: New hierarchy position (optional).
            reason: Audit log reason.

        Returns:
            Dict with updated role info and list of changed fields.
        """
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")
        self._guard_hierarchy(guild, role)

        try:
            payload: Dict[str, Any] = {"reason": reason}
            changed: List[str] = []

            if name is not None:
                payload["name"] = name
                changed.append("name")
            if color is not None:
                color_obj = self._parse_color(color)
                if color_obj is not None:
                    payload["color"] = color_obj
                    changed.append("color")
            if hoist is not None:
                payload["hoist"] = hoist
                changed.append("hoist")
            if mentionable is not None:
                payload["mentionable"] = mentionable
                changed.append("mentionable")
            if permissions is not None:
                merged = self._merge_permissions(role.permissions, permissions)
                payload["permissions"] = merged
                changed.append("permissions")

            # Position is edited separately (different API call)
            if position is not None:
                await role.edit(position=position)
                changed.append("position")

            if payload:
                await role.edit(**payload)

            # Refresh role from cache
            role = guild.get_role(int(role_id)) or role
            logger.info("Modified role '%s' (id=%s): %s", role.name, role_id, changed)
            result = self._role_to_dict(role)
            result["updated_fields"] = changed
            return result
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to modify role: {exc}")

    async def clone(
        self,
        guild: nextcord.Guild,
        source_role_id: int,
        new_name: str,
        reason: str = "Cloned by AI Agent",
    ) -> Dict[str, Any]:
        """Clone a role — copy all attributes (color, permissions, hoist, mentionable).

        Args:
            guild: Target guild.
            source_role_id: Role to clone from.
            new_name: Name for the new cloned role.
            reason: Audit log reason.

        Returns:
            Dict with source and new role info.
        """
        source = guild.get_role(int(source_role_id))
        if source is None:
            raise ValueError(f"Source role '{source_role_id}' not found in guild")

        try:
            new_role = await guild.create_role(
                name=new_name,
                permissions=source.permissions,
                color=source.color,
                hoist=source.hoist,
                mentionable=source.mentionable,
                reason=reason,
            )
            logger.info(
                "Cloned role '%s' (id=%s) -> '%s' (id=%s) in guild '%s'",
                source.name, source_role_id, new_role.name, new_role.id, guild.name,
            )
            return {
                "source_role": self._role_to_dict(source),
                "new_role": self._role_to_dict(new_role),
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to clone role: {exc}")

    async def get_info(
        self,
        guild: nextcord.Guild,
        role_id: int,
    ) -> Dict[str, Any]:
        """Get detailed info and active permissions for a role.

        Args:
            guild: Target guild.
            role_id: Role ID to inspect.

        Returns:
            Dict with full role details and permission breakdown.
        """
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")

        info = self._role_to_dict(role)
        info["all_permissions_count"] = len(info["permissions"])
        info["members"] = [
            {"id": str(m.id), "name": m.display_name}
            for m in role.members[:50]  # cap at 50 to avoid huge payloads
        ]
        return info

    async def set_position(
        self,
        guild: nextcord.Guild,
        role_id: int,
        position: int,
        reason: str = "Position set by AI Agent",
    ) -> Dict[str, Any]:
        """Move a role to a specific hierarchy position.

        Args:
            guild: Target guild.
            role_id: Role to reposition.
            position: New position (1 = just above @everyone).
            reason: Audit log reason.

        Returns:
            Dict confirming the new position.
        """
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")
        self._guard_hierarchy(guild, role)

        try:
            await role.edit(position=int(position), reason=reason)
            logger.info("Moved role '%s' to position %d", role.name, position)
            return {
                "role_id": str(role_id),
                "role_name": role.name,
                "new_position": position,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set role position: {exc}")

    async def bulk_create(
        self,
        guild: nextcord.Guild,
        roles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create multiple roles in a single request.

        Each item in roles supports: name (required), color, permissions,
        hoist, mentionable.

        Args:
            guild: Target guild.
            roles: List of role definition dicts.

        Returns:
            Dict with list of created roles and failure details.
        """
        if not roles:
            raise ValueError("roles list cannot be empty")

        created = []
        failed = []

        for i, role_def in enumerate(roles):
            role_name = role_def.get("name", "")
            if not role_name:
                failed.append({"index": i, "reason": "missing name"})
                continue
            try:
                result = await self.create(
                    guild=guild,
                    name=role_name,
                    color=role_def.get("color"),
                    permissions=role_def.get("permissions"),
                    hoist=role_def.get("hoist", False),
                    mentionable=role_def.get("mentionable", False),
                    reason=role_def.get("reason", "Bulk created by AI Agent"),
                )
                created.append(result)
            except Exception as exc:
                failed.append({"index": i, "name": role_name, "reason": str(exc)})

        logger.info(
            "Bulk created %d/%d roles in guild '%s'",
            len(created), len(roles), guild.name,
        )
        return {
            "created_count": len(created),
            "failed_count": len(failed),
            "created": created,
            "failed": failed,
        }

    async def batch_assign(
        self,
        guild: nextcord.Guild,
        member_ids: List[int],
        role_id: int,
        action: str = "add",
    ) -> Dict[str, Any]:
        """Add or remove a role from multiple members at once.

        Args:
            guild: Target guild.
            member_ids: List of member IDs.
            role_id: Role to add or remove.
            action: 'add' or 'remove'.

        Returns:
            Dict with success/failure counts.
        """
        if action not in ("add", "remove"):
            raise ValueError("action must be 'add' or 'remove'")
        if not member_ids:
            raise ValueError("member_ids list cannot be empty")

        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")
        self._guard_hierarchy(guild, role)

        success = []
        failed = []

        for mid in member_ids:
            try:
                member = guild.get_member(int(mid)) or await guild.fetch_member(int(mid))
                if action == "add":
                    await member.add_roles(role, reason="Batch assign by AI Agent")
                else:
                    await member.remove_roles(role, reason="Batch remove by AI Agent")
                success.append({"member_id": str(mid), "member_name": member.display_name})
            except Exception as exc:
                failed.append({"member_id": str(mid), "reason": str(exc)})

        logger.info(
            "Batch %s role '%s': %d ok / %d failed in guild '%s'",
            action, role.name, len(success), len(failed), guild.name,
        )
        return {
            "action": action,
            "role_name": role.name,
            "role_id": str(role_id),
            "success_count": len(success),
            "failed_count": len(failed),
            "success": success,
            "failed": failed,
        }

    async def delete(
        self,
        guild: nextcord.Guild,
        role_id: int,
        reason: str = "Deleted by AI Agent",
    ) -> Dict[str, Any]:
        """Delete a role by ID.

        Args:
            guild: Target guild.
            role_id: ID of the role to delete.
            reason: Audit log reason.

        Returns:
            Dict confirming deletion.
        """
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")
        self._guard_hierarchy(guild, role)

        try:
            name = role.name
            await role.delete(reason=reason)
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
        """Rename a role. Shorthand for modify(name=...).

        Args:
            guild: Target guild.
            role_id: ID of the role to rename.
            new_name: The new role name.

        Returns:
            Dict with old and new names.
        """
        return await self.modify(guild=guild, role_id=role_id, name=new_name)

    async def set_permissions(
        self,
        guild: nextcord.Guild,
        role_id: int,
        permissions: Dict[str, bool],
    ) -> Dict[str, Any]:
        """Replace the entire permission set for a role (overwrite, not merge).

        For partial updates without wiping existing permissions, use modify().

        Args:
            guild: Target guild.
            role_id: Role ID.
            permissions: Complete permission dict (only True flags will be set).

        Returns:
            Dict confirming the update.
        """
        if not permissions:
            raise ValueError("permissions dict cannot be empty")

        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")
        self._guard_hierarchy(guild, role)

        try:
            perms = self._parse_permissions(permissions)
            await role.edit(permissions=perms)
            logger.info("Set permissions for role '%s' (id=%s)", role.name, role_id)
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
            guild: Target guild.
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
        self._guard_hierarchy(guild, role)

        try:
            await member.add_roles(role)
            logger.info("Assigned role '%s' to member '%s'", role.name, member.display_name)
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
            guild: Target guild.
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
        self._guard_hierarchy(guild, role)

        try:
            await member.remove_roles(role)
            logger.info("Removed role '%s' from member '%s'", role.name, member.display_name)
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

    async def list(
        self,
        guild: nextcord.Guild,
    ) -> Dict[str, Any]:
        """List all roles in the guild.

        Args:
            guild: Target guild.

        Returns:
            Dict with list of roles sorted by position descending.
        """
        roles = [
            self._role_to_dict(role)
            for role in sorted(guild.roles, key=lambda r: r.position, reverse=True)
            if not role.is_default()
        ]
        return {"roles": roles, "count": len(roles)}

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
            "list": self.list,
            # New advanced actions
            "modify": self.modify,
            "clone": self.clone,
            "get_info": self.get_info,
            "bulk_create": self.bulk_create,
            "batch_assign": self.batch_assign,
            "set_position": self.set_position,
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
            # ── Existing tools (preserved) ──────────────────────────────
            ToolDefinition(
                name="discord.roles.create",
                description=(
                    "Create a new role with full customisation: name, color (hex or int), "
                    "permissions dict, hoist (sidebar display), mentionable."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "name": {"type": "string", "description": "Role name."},
                        "color": {"type": "string", "description": "Hex color e.g. '#ff0000' or integer."},
                        "permissions": {
                            "type": "object",
                            "description": "Permission flags dict e.g. {\"kick_members\": true}.",
                            "additionalProperties": {"type": "boolean"},
                        },
                        "hoist": {"type": "boolean", "description": "Display members separately in sidebar."},
                        "mentionable": {"type": "boolean", "description": "Allow @mention of this role."},
                        "reason": {"type": "string", "description": "Audit log reason (optional)."},
                    },
                    "required": ["guild_id", "name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.roles.delete",
                description="Delete a role from the guild. Irreversible. Cannot delete @everyone or roles above the bot.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "role_id": {"type": "string", "description": "Role ID to delete."},
                        "reason": {"type": "string", "description": "Audit log reason (optional)."},
                    },
                    "required": ["guild_id", "role_id"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.roles.rename",
                description="Rename an existing role. Shorthand for modify with only name changed.",
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
                description=(
                    "Overwrite the ENTIRE permission set for a role. All unspecified permissions "
                    "will be set to False. Use discord.roles.modify for partial updates."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "role_id": {"type": "string", "description": "Role ID."},
                        "permissions": {
                            "type": "object",
                            "description": "Full permissions dict. Only True flags will be active.",
                            "additionalProperties": {"type": "boolean"},
                        },
                    },
                    "required": ["guild_id", "role_id", "permissions"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.roles.assign",
                description="Assign a role to a single guild member.",
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
                description="Remove a role from a single guild member.",
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
            ToolDefinition(
                name="discord.roles.list",
                description="List all roles in the guild sorted by position, with member counts and permissions.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                    },
                    "required": ["guild_id"],
                },
                risk_level="low",
                category="query",
            ),
            # ── New advanced tools ────────────────────────────────────────
            ToolDefinition(
                name="discord.roles.modify",
                description=(
                    "Comprehensively edit any combination of role attributes in one call: "
                    "name, color, hoist, mentionable, position, and partial permissions "
                    "(only supplied permission keys are changed — existing ones preserved). "
                    "Preferred over rename/set_permissions for multi-attribute edits."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "role_id": {"type": "string", "description": "Role ID to modify."},
                        "name": {"type": "string", "description": "New role name (optional)."},
                        "color": {"type": "string", "description": "New color — hex '#rrggbb' or int (optional)."},
                        "hoist": {"type": "boolean", "description": "Toggle sidebar display (optional)."},
                        "mentionable": {"type": "boolean", "description": "Toggle mentionability (optional)."},
                        "permissions": {
                            "type": "object",
                            "description": "Partial permissions — only listed keys are changed.",
                            "additionalProperties": {"type": "boolean"},
                        },
                        "position": {"type": "integer", "description": "New hierarchy position (optional)."},
                        "reason": {"type": "string", "description": "Audit log reason (optional)."},
                    },
                    "required": ["guild_id", "role_id"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.roles.clone",
                description=(
                    "Clone a role — copy all attributes (color, permissions, hoist, mentionable) "
                    "from an existing role into a brand new role with a different name."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "source_role_id": {"type": "string", "description": "Role ID to clone from."},
                        "new_name": {"type": "string", "description": "Name for the new cloned role."},
                        "reason": {"type": "string", "description": "Audit log reason (optional)."},
                    },
                    "required": ["guild_id", "source_role_id", "new_name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.roles.get_info",
                description=(
                    "Get detailed information about a role: color, position, hoist, mentionable, "
                    "all active permission flags, and the first 50 members who hold this role."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "role_id": {"type": "string", "description": "Role ID to inspect."},
                    },
                    "required": ["guild_id", "role_id"],
                },
                risk_level="low",
                category="query",
            ),
            ToolDefinition(
                name="discord.roles.bulk_create",
                description=(
                    "Create multiple roles in one request. Each role can specify: "
                    "name (required), color, permissions, hoist, mentionable. "
                    "Returns a summary of created roles and any failures."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "roles": {
                            "type": "array",
                            "description": "List of role definition objects.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "color": {"type": "string"},
                                    "permissions": {"type": "object", "additionalProperties": {"type": "boolean"}},
                                    "hoist": {"type": "boolean"},
                                    "mentionable": {"type": "boolean"},
                                },
                                "required": ["name"],
                            },
                        },
                    },
                    "required": ["guild_id", "roles"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.roles.batch_assign",
                description=(
                    "Add or remove a role from multiple members at once. "
                    "action: 'add' to grant the role, 'remove' to revoke it. "
                    "Returns per-member success and failure details."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "member_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of member IDs to process.",
                        },
                        "role_id": {"type": "string", "description": "Role ID to add or remove."},
                        "action": {
                            "type": "string",
                            "enum": ["add", "remove"],
                            "description": "'add' to grant, 'remove' to revoke.",
                        },
                    },
                    "required": ["guild_id", "member_ids", "role_id", "action"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.roles.set_position",
                description=(
                    "Move a role to a specific hierarchy position. "
                    "Position 1 = just above @everyone. Higher number = higher in hierarchy. "
                    "Affects which roles the bot can manage and channel permission resolution."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "role_id": {"type": "string", "description": "Role ID to reposition."},
                        "position": {"type": "integer", "description": "Target position (1-based)."},
                        "reason": {"type": "string", "description": "Audit log reason (optional)."},
                    },
                    "required": ["guild_id", "role_id", "position"],
                },
                risk_level="medium",
            ),
        ]
