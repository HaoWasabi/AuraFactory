"""Discord Categories Connector — SPEC v2 rewrite.

Uses **kwargs pattern with validation whitelist guard rails.

Actions: create, edit, delete, sync, list
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.connectors.discord._helpers import build_overwrites
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import validate_kwargs

logger = logging.getLogger(__name__)


class CategoriesConnector(BaseConnector):
    """Manages Discord guild categories with **kwargs pattern + validation."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def create(self, guild: nextcord.Guild, name: str, **kwargs) -> Dict[str, Any]:
        """Create a new category in the guild.

        Required: name
        Optional: position, is_private, allowed_role_ids, allowed_user_ids,
            advanced_permissions, reason
        """
        if not name or not name.strip():
            raise ValueError("Category name cannot be empty")

        perm_error = check_bot_permissions(guild, "discord.categories.create")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.categories.create", kwargs)

        # Extract permission kwargs
        is_private = clean.pop("is_private", False)
        allowed_role_ids = clean.pop("allowed_role_ids", None)
        allowed_user_ids = clean.pop("allowed_user_ids", None)
        advanced_permissions = clean.pop("advanced_permissions", None)

        overwrites = build_overwrites(
            guild,
            is_private=is_private,
            allowed_role_ids=allowed_role_ids,
            allowed_user_ids=allowed_user_ids,
            advanced_permissions=advanced_permissions,
        )

        create_kwargs: Dict[str, Any] = {}
        if overwrites:
            create_kwargs["overwrites"] = overwrites
        if "position" in clean:
            create_kwargs["position"] = int(clean.pop("position"))
        if "reason" in clean:
            create_kwargs["reason"] = clean.pop("reason")

        try:
            category = await guild.create_category(name=name, **create_kwargs)
            logger.info("Created category '%s' (id=%s) in guild '%s'", category.name, category.id, guild.name)
            return {
                "id": str(category.id),
                "name": category.name,
                "position": category.position,
                "is_private": is_private,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Channels' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create category: {exc}")

    async def edit(self, guild: nextcord.Guild, category_id: int, **kwargs) -> Dict[str, Any]:
        """Edit category properties.

        Optional: name, position, update_permissions, reason
        """
        perm_error = check_bot_permissions(guild, "discord.categories.edit")
        if perm_error:
            raise PermissionError(perm_error)

        category = guild.get_channel(int(category_id))
        if not category or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found or is not a category")

        clean = validate_kwargs("discord.categories.edit", kwargs)

        update_permissions = clean.pop("update_permissions", None)
        reason = clean.pop("reason", None)

        try:
            # Handle granular permission update
            if update_permissions:
                target_id = update_permissions.get("target_id")
                perm_flags = update_permissions.get("permissions", {})
                target = guild.get_role(int(target_id)) or guild.get_member(int(target_id))
                if target and perm_flags:
                    overwrite = category.overwrites_for(target)
                    for flag, val in perm_flags.items():
                        if hasattr(overwrite, flag):
                            setattr(overwrite, flag, val)
                    await category.set_permissions(target, overwrite=overwrite, reason=reason)

            # Apply edits
            if clean:
                await category.edit(reason=reason, **clean)

            updated_fields = list(clean.keys())
            if update_permissions:
                updated_fields.append("permissions")

            logger.info("Edited category '%s' (id=%s): %s", category.name, category_id, updated_fields)
            return {
                "id": str(category_id),
                "name": category.name,
                "updated_fields": updated_fields,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks permission to edit this category.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit category: {exc}")

    async def delete(self, guild: nextcord.Guild, category_id: int, **kwargs) -> Dict[str, Any]:
        """Delete a category by ID.

        Optional: reason
        """
        perm_error = check_bot_permissions(guild, "discord.categories.delete")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.categories.delete", kwargs)

        category = guild.get_channel(int(category_id))
        if not category or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found or is not a category")

        try:
            name = category.name
            await category.delete(reason=clean.get("reason", "AI Agent Request"))
            logger.info("Deleted category '%s' (id=%s)", name, category_id)
            return {"id": str(category_id), "name": name, "deleted": True}
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Channels' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete category: {exc}")

    async def sync(self, guild: nextcord.Guild, category_id: int, **kwargs) -> Dict[str, Any]:
        """Force-sync all child channels' permissions with this category.

        Useful after changing category permissions.
        """
        perm_error = check_bot_permissions(guild, "discord.categories.sync")
        if perm_error:
            raise PermissionError(perm_error)

        category = guild.get_channel(int(category_id))
        if not category or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found or is not a category")

        try:
            synced = []
            for channel in category.channels:
                await channel.edit(sync_permissions=True)
                synced.append(channel.name)

            logger.info("Synced %d channels in category '%s'", len(synced), category.name)
            return {
                "id": str(category_id),
                "name": category.name,
                "synced_channels": synced,
                "synced_count": len(synced),
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Channels' or 'Manage Roles' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to sync category channels: {exc}")

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all categories in the guild."""
        categories = []
        for cat in sorted(guild.categories, key=lambda c: c.position):
            categories.append({
                "id": str(cat.id),
                "name": cat.name,
                "position": cat.position,
                "channel_count": len(cat.channels),
            })
        return {"categories": categories, "count": len(categories)}
