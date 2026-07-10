"""Discord Categories Connector — kwargs pattern.

Actions: create, edit, delete, sync, reorder, list
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector, build_overwrites

logger = logging.getLogger(__name__)


class CategoriesConnector(BaseConnector):
    """Category management with **kwargs."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {
            "create": self.create,
            "rename": self.rename,
            "edit": self.edit,
            "delete": self.delete,
            "sync": self.sync,
            "reorder": self.reorder,
            "list": self.list,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'. Available: {list(actions.keys())}")
        return await handler(guild, **kwargs)

    # ------------------------------------------------------------------

    async def create(self, guild: nextcord.Guild, name: str, **kwargs) -> Dict[str, Any]:
        """Create a category. kwargs: position, is_private, allowed_role_ids, allowed_user_ids, advanced_permissions, reason"""
        if not name or not name.strip():
            raise ValueError("Category name cannot be empty")

        is_private = kwargs.pop("is_private", False)
        allowed_role_ids = kwargs.pop("allowed_role_ids", None)
        allowed_user_ids = kwargs.pop("allowed_user_ids", None)
        advanced_permissions = kwargs.pop("advanced_permissions", None)
        reason = kwargs.pop("reason", None)
        position = kwargs.pop("position", None)

        overwrites = build_overwrites(
            guild, is_private=is_private,
            allowed_role_ids=allowed_role_ids,
            allowed_user_ids=allowed_user_ids,
            advanced_permissions=advanced_permissions,
        )

        create_kwargs: Dict[str, Any] = {}
        if overwrites:
            create_kwargs["overwrites"] = overwrites
        if position is not None:
            create_kwargs["position"] = int(position)
        if reason:
            create_kwargs["reason"] = reason

        try:
            category = await guild.create_category(name=name, **create_kwargs)
            logger.info("Created category '%s' (id=%s)", name, category.id)
            return {
                "id": str(category.id),
                "name": category.name,
                "position": category.position,
                "is_private": is_private,
            }
        except nextcord.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to create category: {exc}")

    # ------------------------------------------------------------------
    # RENAME
    # ------------------------------------------------------------------

    async def rename(self, guild: nextcord.Guild, category_id: int, name: str, **kwargs) -> Dict[str, Any]:
        """Rename a category."""
        if not name or not name.strip():
            raise ValueError("Category name cannot be empty")

        category = guild.get_channel(int(category_id))
        if category is None or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found")

        reason = kwargs.pop("reason", None)

        try:
            old_name = category.name
            await category.edit(name=name.strip(), reason=reason)
            logger.info("Renamed category '%s' → '%s' (id=%s)", old_name, name, category_id)
            return {"id": str(category_id), "old_name": old_name, "new_name": name.strip()}
        except nextcord.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to rename category: {exc}")

    async def edit(self, guild: nextcord.Guild, category_id: int, **kwargs) -> Dict[str, Any]:
        """Edit category. kwargs: name, position, update_permissions, reason"""
        category = guild.get_channel(int(category_id))
        if not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found")

        update_permissions = kwargs.pop("update_permissions", None)
        reason = kwargs.pop("reason", None)

        try:
            # Granular permission update
            if update_permissions:
                target_id = update_permissions.get("target_id")
                perm_flags = update_permissions.get("permissions", {})
                target = guild.get_role(int(target_id)) or guild.get_member(int(target_id))
                if target and perm_flags:
                    ow = category.overwrites_for(target)
                    for flag, val in perm_flags.items():
                        if hasattr(ow, flag):
                            setattr(ow, flag, val)
                    await category.set_permissions(target, overwrite=ow, reason=reason)

            # Apply other edits
            if kwargs:
                await category.edit(reason=reason, **kwargs)

            updated = list(kwargs.keys())
            if update_permissions:
                updated.append("permissions")

            logger.info("Edited category '%s': %s", category.name, updated)
            return {"id": str(category_id), "name": category.name, "updated_fields": updated}
        except nextcord.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to edit category: {exc}")

    async def delete(self, guild: nextcord.Guild, category_id: int, **kwargs) -> Dict[str, Any]:
        """Delete a category (child channels become uncategorized)."""
        category = guild.get_channel(int(category_id))
        if not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found")

        reason = kwargs.pop("reason", None)

        try:
            name = category.name
            await category.delete(reason=reason)
            logger.info("Deleted category '%s' (id=%s)", name, category_id)
            return {"deleted": True, "id": str(category_id), "name": name}
        except nextcord.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to delete category: {exc}")

    async def sync(self, guild: nextcord.Guild, category_id: int, **kwargs) -> Dict[str, Any]:
        """Sync all child channels' permissions with this category."""
        category = guild.get_channel(int(category_id))
        if not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found")

        synced = []
        failed = []
        for ch in category.channels:
            try:
                await ch.edit(sync_permissions=True)
                synced.append(str(ch.id))
            except Exception as e:
                failed.append({"id": str(ch.id), "error": str(e)})

        logger.info("Synced %d channels in category '%s'", len(synced), category.name)
        return {"synced_count": len(synced), "failed": failed, "category_name": category.name}

    async def reorder(self, guild: nextcord.Guild, category_ids: List[int], **kwargs) -> Dict[str, Any]:
        """Reorder categories by providing IDs in desired order."""
        if not category_ids:
            raise ValueError("category_ids cannot be empty")

        payload = []
        for pos, cid in enumerate(category_ids):
            cat = guild.get_channel(int(cid))
            if not isinstance(cat, nextcord.CategoryChannel):
                raise ValueError(f"Category '{cid}' not found")
            payload.append({"id": int(cid), "position": pos})

        try:
            await guild.edit_channel_positions(payload)
            logger.info("Reordered %d categories", len(category_ids))
            return {"reordered": True, "count": len(category_ids)}
        except nextcord.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to reorder: {exc}")

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all categories with their child channels."""
        categories = []
        for cat in guild.categories:
            categories.append({
                "id": str(cat.id),
                "name": cat.name,
                "position": cat.position,
                "channels": [
                    {"id": str(c.id), "name": c.name, "type": str(c.type).split(".")[-1]}
                    for c in cat.channels
                ],
            })
        return {"categories": categories, "count": len(categories)}
