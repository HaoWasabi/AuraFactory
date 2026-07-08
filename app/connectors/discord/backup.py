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
from app.connectors.discord._helpers import RateLimitGate
from app.connectors.discord._permissions import check_bot_permissions

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
        """Import a guild structure (recreate categories, channels, roles).

        WARNING: This is a critical operation. It will create new resources
        but does NOT delete existing ones (additive import).

        Args:
            guild: The target guild.
            structure: Structure dict (from export_structure).

        Returns:
            Dict with import results.
        """
        if not structure:
            raise ValueError("Structure dict cannot be empty")

        results = {
            "categories_created": 0,
            "channels_created": 0,
            "roles_created": 0,
            "errors": [],
        }

        try:
            # Import roles first (needed for permission overwrites)
            for role_data in structure.get("roles", []):
                try:
                    perms = nextcord.Permissions(permissions=role_data.get("permissions", 0))
                    color = nextcord.Color(role_data.get("color", 0))
                    await guild.create_role(
                        name=role_data["name"],
                        color=color,
                        hoist=role_data.get("hoist", False),
                        mentionable=role_data.get("mentionable", False),
                        permissions=perms,
                    )
                    results["roles_created"] += 1
                except Exception as exc:
                    results["errors"].append(f"Role '{role_data.get('name')}': {exc}")

            # Import categories and their channels
            for cat_data in structure.get("categories", []):
                try:
                    category = await guild.create_category(name=cat_data["name"])
                    results["categories_created"] += 1

                    for ch_data in cat_data.get("channels", []):
                        try:
                            ch_type = ch_data.get("type", "text")
                            if "voice" in ch_type:
                                await guild.create_voice_channel(
                                    name=ch_data["name"],
                                    category=category,
                                )
                            else:
                                await guild.create_text_channel(
                                    name=ch_data["name"],
                                    category=category,
                                    topic=ch_data.get("topic"),
                                )
                            results["channels_created"] += 1
                        except Exception as exc:
                            results["errors"].append(
                                f"Channel '{ch_data.get('name')}': {exc}"
                            )
                except Exception as exc:
                    results["errors"].append(f"Category '{cat_data.get('name')}': {exc}")

            # Import uncategorized channels
            for ch_data in structure.get("uncategorized_channels", []):
                try:
                    ch_type = ch_data.get("type", "text")
                    if "voice" in ch_type:
                        await guild.create_voice_channel(name=ch_data["name"])
                    else:
                        await guild.create_text_channel(name=ch_data["name"])
                    results["channels_created"] += 1
                except Exception as exc:
                    results["errors"].append(f"Channel '{ch_data.get('name')}': {exc}")

            logger.info(
                "Imported structure to guild '%s': %d categories, %d channels, %d roles, %d errors",
                guild.name,
                results["categories_created"],
                results["channels_created"],
                results["roles_created"],
                len(results["errors"]),
            )
            return results

        except nextcord.errors.Forbidden:
            raise PermissionError("administrator")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to import structure: {exc}")

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
