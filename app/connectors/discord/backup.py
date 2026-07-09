"""Discord Backup Connector — kwargs pattern. Actions: export, restore"""

from __future__ import annotations
import logging
from typing import Any, Dict, List
import nextcord
from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class BackupConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {"export": self.export, "restore": self.restore}
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def export(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Export full guild structure."""
        categories = []
        for cat in guild.categories:
            cat_data = {
                "name": cat.name, "position": cat.position,
                "channels": [{"name": ch.name, "type": str(ch.type).split(".")[-1],
                              "topic": getattr(ch, "topic", None)} for ch in cat.channels],
            }
            categories.append(cat_data)

        uncategorized = [
            {"name": ch.name, "type": str(ch.type).split(".")[-1]}
            for ch in guild.channels if ch.category is None and not isinstance(ch, nextcord.CategoryChannel)
        ]

        roles = [
            {"name": r.name, "color": r.color.value, "hoist": r.hoist,
             "mentionable": r.mentionable, "permissions": r.permissions.value}
            for r in guild.roles if not r.is_default()
        ]

        structure = {
            "guild_name": guild.name, "description": guild.description,
            "categories": categories, "uncategorized": uncategorized,
            "roles": roles, "verification_level": str(guild.verification_level),
        }
        logger.info("Exported structure: %d categories, %d roles", len(categories), len(roles))
        return structure

    async def restore(self, guild: nextcord.Guild, backup_data: dict, **kwargs) -> Dict[str, Any]:
        """Restore guild structure from backup (additive — no deletion)."""
        if not backup_data:
            raise ValueError("backup_data cannot be empty")

        results = {"categories_created": 0, "channels_created": 0, "roles_created": 0, "errors": []}

        # Roles first
        for role_data in backup_data.get("roles", []):
            try:
                perms = nextcord.Permissions(permissions=role_data.get("permissions", 0))
                await guild.create_role(
                    name=role_data["name"],
                    color=nextcord.Color(role_data.get("color", 0)),
                    hoist=role_data.get("hoist", False),
                    mentionable=role_data.get("mentionable", False),
                    permissions=perms,
                )
                results["roles_created"] += 1
            except Exception as e:
                results["errors"].append(f"Role '{role_data.get('name')}': {e}")

        # Categories + channels
        for cat_data in backup_data.get("categories", []):
            try:
                cat = await guild.create_category(name=cat_data["name"])
                results["categories_created"] += 1
                for ch_data in cat_data.get("channels", []):
                    try:
                        ch_type = ch_data.get("type", "text")
                        if "voice" in ch_type:
                            await guild.create_voice_channel(name=ch_data["name"], category=cat)
                        else:
                            await guild.create_text_channel(name=ch_data["name"], category=cat, topic=ch_data.get("topic"))
                        results["channels_created"] += 1
                    except Exception as e:
                        results["errors"].append(f"Channel '{ch_data.get('name')}': {e}")
            except Exception as e:
                results["errors"].append(f"Category '{cat_data.get('name')}': {e}")

        logger.info("Restore: %d cat, %d ch, %d roles, %d errors",
                    results["categories_created"], results["channels_created"],
                    results["roles_created"], len(results["errors"]))
        return results
