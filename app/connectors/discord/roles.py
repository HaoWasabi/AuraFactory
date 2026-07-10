"""Discord Roles Connector — kwargs pattern.

Actions: create, modify, delete, assign, remove, batch_assign,
         clone, set_position, list, get_info
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import (
    BaseConnector, parse_color, parse_permissions,
    merge_permissions, role_to_dict,
)

logger = logging.getLogger(__name__)


class RolesConnector(BaseConnector):
    """Role management with **kwargs — clean and scalable."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {
            "create": self.create,
            "bulk_create": self.bulk_create,
            "rename": self.rename,
            "modify": self.modify,
            "delete": self.delete,
            "assign": self.assign,
            "remove": self.remove,
            "batch_assign": self.batch_assign,
            "clone": self.clone,
            "set_position": self.set_position,
            "list": self.list,
            "get_info": self.get_info,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'. Available: {list(actions.keys())}")
        return await handler(guild, **kwargs)

    # ------------------------------------------------------------------

    async def create(self, guild: nextcord.Guild, name: str, **kwargs) -> Dict[str, Any]:
        """Create a role. kwargs: color, hoist, mentionable, permissions, position, reason"""
        if not name or not name.strip():
            raise ValueError("Role name cannot be empty")

        color = parse_color(kwargs.pop("color", None))
        perms = kwargs.pop("permissions", None)
        reason = kwargs.pop("reason", "Created by AI Agent")

        create_kwargs: Dict[str, Any] = {
            "name": name,
            "hoist": kwargs.pop("hoist", False),
            "mentionable": kwargs.pop("mentionable", False),
            "reason": reason,
        }
        if color:
            create_kwargs["color"] = color
        if perms and isinstance(perms, dict):
            create_kwargs["permissions"] = parse_permissions(perms)

        try:
            role = await guild.create_role(**create_kwargs)

            # Set position if requested (separate API call)
            position = kwargs.pop("position", None)
            if position is not None:
                await role.edit(position=int(position))

            logger.info("Created role '%s' (id=%s)", name, role.id)
            return role_to_dict(role)
        except nextcord.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to create role: {exc}")

    # ------------------------------------------------------------------
    # BULK CREATE
    # ------------------------------------------------------------------

    async def bulk_create(self, guild: nextcord.Guild, roles: list = None, **kwargs) -> Dict[str, Any]:
        """Create multiple roles in one call.

        kwargs:
            roles: list of dicts, each with {name, color?, hoist?, mentionable?, permissions?}
        """
        if not roles or not isinstance(roles, list):
            raise ValueError("'roles' must be a non-empty list of role definitions")

        created = []
        errors = []
        reason = kwargs.pop("reason", "Bulk created by AI Agent")

        # Hierarchy check: bot needs manage_roles
        if not guild.me.guild_permissions.manage_roles:
            raise PermissionError("manage_roles")

        for i, role_def in enumerate(roles):
            if not isinstance(role_def, dict):
                errors.append({"index": i, "error": "Invalid role definition (must be dict)"})
                continue

            name = role_def.get("name", "").strip()
            if not name:
                errors.append({"index": i, "error": "Role name cannot be empty"})
                continue

            try:
                create_kwargs: Dict[str, Any] = {
                    "name": name,
                    "hoist": role_def.get("hoist", False),
                    "mentionable": role_def.get("mentionable", False),
                    "reason": reason,
                }

                color = parse_color(role_def.get("color"))
                if color:
                    create_kwargs["color"] = color

                perms = role_def.get("permissions")
                if perms and isinstance(perms, dict):
                    create_kwargs["permissions"] = parse_permissions(perms)

                role = await guild.create_role(**create_kwargs)
                created.append(role_to_dict(role))
                logger.info("Bulk-created role '%s' (id=%s)", name, role.id)

            except (nextcord.Forbidden, nextcord.HTTPException) as exc:
                errors.append({"index": i, "name": name, "error": str(exc)})

        return {
            "created": created,
            "created_count": len(created),
            "error_count": len(errors),
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # RENAME
    # ------------------------------------------------------------------

    async def rename(self, guild: nextcord.Guild, role_id: int, name: str, **kwargs) -> Dict[str, Any]:
        """Rename a role (convenience wrapper)."""
        if not name or not name.strip():
            raise ValueError("Role name cannot be empty")

        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found")

        # Hierarchy check
        bot_top_role = guild.me.top_role
        if role >= bot_top_role:
            raise PermissionError(f"Cannot rename role '{role.name}' — it is at or above bot's highest role")

        reason = kwargs.pop("reason", None)

        try:
            old_name = role.name
            await role.edit(name=name.strip(), reason=reason)
            logger.info("Renamed role '%s' → '%s' (id=%s)", old_name, name, role_id)
            return {"id": str(role_id), "old_name": old_name, "new_name": name.strip()}
        except nextcord.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to rename role: {exc}")

    async def modify(self, guild: nextcord.Guild, role_id: int, **kwargs) -> Dict[str, Any]:
        """Edit role. kwargs: name, color, hoist, mentionable, permissions, position, reason"""
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found")
        if role >= guild.me.top_role or role.is_default():
            raise PermissionError(f"Cannot modify role '{role.name}' — hierarchy too high")

        reason = kwargs.pop("reason", "Modified by AI Agent")
        position = kwargs.pop("position", None)
        changed: List[str] = []

        payload: Dict[str, Any] = {"reason": reason}

        name = kwargs.pop("name", None)
        if name is not None:
            payload["name"] = name
            changed.append("name")

        color = kwargs.pop("color", None)
        if color is not None:
            color_obj = parse_color(color)
            if color_obj:
                payload["color"] = color_obj
                changed.append("color")

        hoist = kwargs.pop("hoist", None)
        if hoist is not None:
            payload["hoist"] = hoist
            changed.append("hoist")

        mentionable = kwargs.pop("mentionable", None)
        if mentionable is not None:
            payload["mentionable"] = mentionable
            changed.append("mentionable")

        perms = kwargs.pop("permissions", None)
        if perms and isinstance(perms, dict):
            payload["permissions"] = merge_permissions(role.permissions, perms)
            changed.append("permissions")

        try:
            if position is not None:
                await role.edit(position=int(position))
                changed.append("position")

            if len(payload) > 1:  # more than just "reason"
                await role.edit(**payload)

            role = guild.get_role(int(role_id)) or role
            logger.info("Modified role '%s' (id=%s): %s", role.name, role_id, changed)
            result = role_to_dict(role)
            result["updated_fields"] = changed
            return result
        except nextcord.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to modify role: {exc}")

    async def delete(self, guild: nextcord.Guild, role_id: int, **kwargs) -> Dict[str, Any]:
        """Delete a role."""
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found")
        if role >= guild.me.top_role or role.is_default():
            raise PermissionError(f"Cannot delete role '{role.name}'")

        reason = kwargs.pop("reason", "Deleted by AI Agent")

        try:
            name = role.name
            await role.delete(reason=reason)
            logger.info("Deleted role '%s' (id=%s)", name, role_id)
            return {"deleted": True, "id": str(role_id), "name": name}
        except nextcord.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to delete role: {exc}")

    async def assign(self, guild: nextcord.Guild, member_id: int, role_id: int, **kwargs) -> Dict[str, Any]:
        """Assign a role to a member."""
        member = guild.get_member(int(member_id))
        if member is None:
            member = await guild.fetch_member(int(member_id))
        role = guild.get_role(int(role_id))

        if not member or not role:
            raise ValueError("Member or role not found")
        if role >= guild.me.top_role:
            raise PermissionError(f"Cannot assign role '{role.name}' — hierarchy")

        reason = kwargs.pop("reason", None)

        try:
            await member.add_roles(role, reason=reason)
            logger.info("Assigned role '%s' to member '%s'", role.name, member.display_name)
            return {
                "assigned": True,
                "member_id": str(member_id),
                "member_name": member.display_name,
                "role_id": str(role_id),
                "role_name": role.name,
            }
        except nextcord.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to assign role: {exc}")

    async def remove(self, guild: nextcord.Guild, member_id: int, role_id: int, **kwargs) -> Dict[str, Any]:
        """Remove a role from a member."""
        member = guild.get_member(int(member_id))
        if member is None:
            member = await guild.fetch_member(int(member_id))
        role = guild.get_role(int(role_id))

        if not member or not role:
            raise ValueError("Member or role not found")

        reason = kwargs.pop("reason", None)

        try:
            await member.remove_roles(role, reason=reason)
            logger.info("Removed role '%s' from member '%s'", role.name, member.display_name)
            return {
                "removed": True,
                "member_id": str(member_id),
                "member_name": member.display_name,
                "role_id": str(role_id),
                "role_name": role.name,
            }
        except nextcord.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to remove role: {exc}")

    async def batch_assign(self, guild: nextcord.Guild, role_id: int, member_ids: List[int], **kwargs) -> Dict[str, Any]:
        """Batch assign/remove role to/from multiple members."""
        role = guild.get_role(int(role_id))
        if not role:
            raise ValueError(f"Role '{role_id}' not found")
        if role >= guild.me.top_role:
            raise PermissionError(f"Cannot manage role '{role.name}'")

        action = kwargs.pop("action", "add")
        reason = kwargs.pop("reason", None)

        success = []
        failed = []

        for mid in member_ids:
            member = guild.get_member(int(mid))
            if not member:
                failed.append({"id": str(mid), "error": "not found"})
                continue
            try:
                if action == "add":
                    await member.add_roles(role, reason=reason)
                else:
                    await member.remove_roles(role, reason=reason)
                success.append(str(mid))
            except Exception as e:
                failed.append({"id": str(mid), "error": str(e)})

        logger.info("Batch %s role '%s': %d success, %d failed", action, role.name, len(success), len(failed))
        return {
            "role_id": str(role_id),
            "role_name": role.name,
            "action": action,
            "success_count": len(success),
            "failed": failed,
        }

    async def clone(self, guild: nextcord.Guild, source_role_id: int, new_name: str, **kwargs) -> Dict[str, Any]:
        """Clone a role — copies all attributes."""
        source = guild.get_role(int(source_role_id))
        if source is None:
            raise ValueError(f"Source role '{source_role_id}' not found")

        reason = kwargs.pop("reason", "Cloned by AI Agent")

        try:
            new_role = await guild.create_role(
                name=new_name,
                permissions=source.permissions,
                color=source.color,
                hoist=source.hoist,
                mentionable=source.mentionable,
                reason=reason,
            )
            logger.info("Cloned '%s' → '%s'", source.name, new_role.name)
            result = role_to_dict(new_role)
            result["cloned_from"] = {"id": str(source.id), "name": source.name}
            return result
        except nextcord.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to clone role: {exc}")

    async def set_position(self, guild: nextcord.Guild, role_id: int, position: int, **kwargs) -> Dict[str, Any]:
        """Change role hierarchy position."""
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found")
        if role >= guild.me.top_role:
            raise PermissionError(f"Cannot reposition role '{role.name}'")

        try:
            await role.edit(position=int(position))
            logger.info("Set role '%s' position to %d", role.name, position)
            return {"id": str(role_id), "name": role.name, "new_position": position}
        except nextcord.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to set position: {exc}")

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all roles in the guild."""
        roles = [role_to_dict(r) for r in guild.roles if not r.is_default()]
        return {"roles": roles, "count": len(roles)}

    async def get_info(self, guild: nextcord.Guild, role_id: int, **kwargs) -> Dict[str, Any]:
        """Get detailed info about a specific role."""
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found")
        return role_to_dict(role)
