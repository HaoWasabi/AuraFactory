"""
Discord Backup Connector — Guild structure export/import operations.

Actions: export_structure, import_structure
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class BackupConnector(BaseConnector):
    """Manages Discord guild structure backup/restore."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def export_structure(
        self,
        guild: nextcord.Guild,
    ) -> Dict[str, Any]:
        """Export the full guild structure as a dict.

        Exports: categories, channels, roles, permissions, and settings.

        Args:
            guild: The target guild.

        Returns:
            Dict representing the full guild structure.
        """
        try:
            # Export categories
            categories = []
            for cat in guild.categories:
                cat_data = {
                    "id": str(cat.id),
                    "name": cat.name,
                    "position": cat.position,
                    "channels": [],
                    "permission_overwrites": self._serialize_overwrites(cat.overwrites),
                }
                for ch in cat.channels:
                    cat_data["channels"].append({
                        "id": str(ch.id),
                        "name": ch.name,
                        "type": str(ch.type),
                        "position": ch.position,
                        "permission_overwrites": self._serialize_overwrites(ch.overwrites),
                        "topic": getattr(ch, "topic", None),
                    })
                categories.append(cat_data)

            # Export uncategorized channels
            uncategorized = []
            for ch in guild.channels:
                if ch.category is None and not isinstance(ch, nextcord.CategoryChannel):
                    uncategorized.append({
                        "id": str(ch.id),
                        "name": ch.name,
                        "type": str(ch.type),
                        "position": ch.position,
                        "permission_overwrites": self._serialize_overwrites(ch.overwrites),
                    })

            # Export roles
            roles = []
            for role in guild.roles:
                if role.is_default():
                    continue
                roles.append({
                    "id": str(role.id),
                    "name": role.name,
                    "color": role.color.value,
                    "hoist": role.hoist,
                    "mentionable": role.mentionable,
                    "position": role.position,
                    "permissions": role.permissions.value,
                })

            structure = {
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "description": guild.description,
                "categories": categories,
                "uncategorized_channels": uncategorized,
                "roles": roles,
                "verification_level": str(guild.verification_level),
                "default_notifications": str(guild.default_notifications),
            }

            logger.info(
                "Exported structure for guild '%s': %d categories, %d roles",
                guild.name,
                len(categories),
                len(roles),
            )
            return structure

        except nextcord.errors.Forbidden:
            raise PermissionError("view_guild_insights")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to export structure: {exc}")

    async def import_structure(
        self,
        guild: nextcord.Guild,
        structure: dict,
    ) -> Dict[str, Any]:
        """Import a guild structure (recreate categories, channels, roles, permissions).

        This is an ADDITIVE import — it creates new resources but does NOT
        delete existing ones. Permission overwrites from the exported structure
        are applied after all roles and channels are created.

        Args:
            guild: The target guild.
            structure: Structure dict from export_structure.

        Returns:
            Dict with import results including counts and any errors.
        """
        if not structure:
            raise ValueError("Structure dict cannot be empty")

        results = {
            "categories_created": 0,
            "channels_created": 0,
            "roles_created": 0,
            "permissions_applied": 0,
            "errors": [],
        }

        # --- Step 1: Import roles first (needed for permission overwrites) ---
        # Map old_role_id → new_role for permission re-application
        role_id_map: dict = {}  # old_id (str) → nextcord.Role
        for role_data in structure.get("roles", []):
            try:
                perms = nextcord.Permissions(permissions=role_data.get("permissions", 0))
                color = nextcord.Color(role_data.get("color", 0))
                new_role = await guild.create_role(
                    name=role_data["name"],
                    color=color,
                    hoist=role_data.get("hoist", False),
                    mentionable=role_data.get("mentionable", False),
                    permissions=perms,
                )
                role_id_map[str(role_data["id"])] = new_role
                results["roles_created"] += 1
            except Exception as exc:
                results["errors"].append(f"Role '{role_data.get('name')}': {exc}")

        # --- Step 2: Import categories and their channels ---
        # Map old_channel_id → new_channel for permission re-application
        channel_id_map: dict = {}  # old_id (str) → nextcord.abc.GuildChannel

        for cat_data in structure.get("categories", []):
            try:
                new_category = await guild.create_category(name=cat_data["name"])
                results["categories_created"] += 1
                channel_id_map[str(cat_data["id"])] = new_category

                for ch_data in cat_data.get("channels", []):
                    try:
                        ch_type = ch_data.get("type", "text")
                        if "voice" in str(ch_type):
                            new_ch = await guild.create_voice_channel(
                                name=ch_data["name"],
                                category=new_category,
                            )
                        else:
                            new_ch = await guild.create_text_channel(
                                name=ch_data["name"],
                                category=new_category,
                                topic=ch_data.get("topic"),
                            )
                        channel_id_map[str(ch_data["id"])] = new_ch
                        results["channels_created"] += 1
                    except Exception as exc:
                        results["errors"].append(
                            f"Channel '{ch_data.get('name')}': {exc}"
                        )
            except Exception as exc:
                results["errors"].append(f"Category '{cat_data.get('name')}': {exc}")

        # --- Step 3: Import uncategorized channels ---
        for ch_data in structure.get("uncategorized_channels", []):
            try:
                ch_type = ch_data.get("type", "text")
                if "voice" in str(ch_type):
                    new_ch = await guild.create_voice_channel(name=ch_data["name"])
                else:
                    new_ch = await guild.create_text_channel(name=ch_data["name"])
                channel_id_map[str(ch_data["id"])] = new_ch
                results["channels_created"] += 1
            except Exception as exc:
                results["errors"].append(f"Channel '{ch_data.get('name')}': {exc}")

        # --- Step 4: Apply permission overwrites ---
        # Iterate over all channels (categories + their channels + uncategorized)
        all_channel_data = list(structure.get("uncategorized_channels", []))
        for cat_data in structure.get("categories", []):
            all_channel_data.append(cat_data)
            all_channel_data.extend(cat_data.get("channels", []))

        for ch_data in all_channel_data:
            new_ch = channel_id_map.get(str(ch_data.get("id")))
            if new_ch is None:
                continue  # channel creation had failed, skip perms

            for overwrite_data in ch_data.get("permission_overwrites", []):
                try:
                    target_id = str(overwrite_data.get("target_id"))
                    target_type = overwrite_data.get("target_type", "role")
                    allow_val = overwrite_data.get("allow", 0)
                    deny_val = overwrite_data.get("deny", 0)

                    # Resolve target — prefer newly-created objects, fall back to existing
                    target = None
                    if target_type == "role":
                        target = role_id_map.get(target_id) or guild.get_role(int(target_id))
                    else:
                        target = guild.get_member(int(target_id))

                    if target is None:
                        # Try @everyone
                        if target_type == "role":
                            target = guild.default_role
                        else:
                            continue  # member not found, skip

                    allow_perms = nextcord.Permissions(allow_val)
                    deny_perms = nextcord.Permissions(deny_val)
                    overwrite = nextcord.PermissionOverwrite.from_pair(allow_perms, deny_perms)
                    await new_ch.set_permissions(target, overwrite=overwrite)
                    results["permissions_applied"] += 1
                except Exception as exc:
                    results["errors"].append(
                        f"Permission overwrite on '{ch_data.get('name')}': {exc}"
                    )

        logger.info(
            "Imported structure to guild '%s': %d categories, %d channels, "
            "%d roles, %d permission overwrites, %d errors",
            guild.name,
            results["categories_created"],
            results["channels_created"],
            results["roles_created"],
            results["permissions_applied"],
            len(results["errors"]),
        )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_overwrites(
        overwrites: Dict[Any, nextcord.PermissionOverwrite],
    ) -> List[Dict[str, Any]]:
        """Serialize permission overwrites to a list of dicts."""
        result = []
        for target, overwrite in overwrites.items():
            allow, deny = overwrite.pair()
            result.append({
                "target_id": str(target.id),
                "target_type": "role" if isinstance(target, nextcord.Role) else "member",
                "allow": allow.value,
                "deny": deny.value,
            })
        return result

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "export_structure": self.export_structure,
            "import_structure": self.import_structure,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for BackupConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for backup operations."""
        return [
            ToolDefinition(
                name="discord.backup.export_structure",
                description="Export the full guild structure (categories, channels, roles, permissions).",
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
                name="discord.backup.import_structure",
                description="Import a guild structure (additive — creates new resources). CRITICAL operation.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "structure": {"type": "object", "description": "Structure dict from export_structure."},
                    },
                    "required": ["guild_id", "structure"],
                },
                risk_level="critical",
            ),
        ]
