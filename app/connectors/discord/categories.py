"""
Discord Categories Connector — Category management operations.

Actions: create, delete, rename, reorder
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class CategoriesConnector(BaseConnector):
    """Manages Discord guild categories."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        name: str,
    ) -> Dict[str, Any]:
        """Create a new category in the guild.

        Args:
            guild: The target guild.
            name: Category name.

        Returns:
            Dict with created category info.
        """
        if not name or not name.strip():
            raise ValueError("Category name cannot be empty")

        try:
            category = await guild.create_category(name=name)
            logger.info("Created category '%s' (id=%s) in guild '%s'", name, category.id, guild.name)
            return {
                "id": str(category.id),
                "name": category.name,
                "position": category.position,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create category: {exc}")

    async def delete(
        self,
        guild: nextcord.Guild,
        category_id: int,
    ) -> Dict[str, Any]:
        """Delete a category by ID (channels inside are NOT deleted).

        Args:
            guild: The target guild.
            category_id: ID of the category to delete.

        Returns:
            Dict confirming deletion.
        """
        category = guild.get_channel(int(category_id))
        if category is None or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found in guild")

        try:
            name = category.name
            await category.delete()
            logger.info("Deleted category '%s' (id=%s) from guild '%s'", name, category_id, guild.name)
            return {"deleted": True, "category_id": str(category_id), "name": name}
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete category: {exc}")

    async def rename(
        self,
        guild: nextcord.Guild,
        category_id: int,
        new_name: str,
    ) -> Dict[str, Any]:
        """Rename a category.

        Args:
            guild: The target guild.
            category_id: ID of the category to rename.
            new_name: The new category name.

        Returns:
            Dict with old and new names.
        """
        if not new_name or not new_name.strip():
            raise ValueError("New category name cannot be empty")

        category = guild.get_channel(int(category_id))
        if category is None or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found in guild")

        try:
            old_name = category.name
            await category.edit(name=new_name)
            logger.info("Renamed category '%s' -> '%s' (id=%s)", old_name, new_name, category_id)
            return {
                "category_id": str(category_id),
                "old_name": old_name,
                "new_name": new_name,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to rename category: {exc}")

    async def reorder(
        self,
        guild: nextcord.Guild,
        category_ids: List[int],
    ) -> Dict[str, Any]:
        """Reorder categories by providing a list of IDs in desired order.

        Args:
            guild: The target guild.
            category_ids: List of category IDs in the desired order.

        Returns:
            Dict confirming the reorder.
        """
        if not category_ids:
            raise ValueError("category_ids list cannot be empty")

        try:
            # Build position payload
            payload = []
            for position, cat_id in enumerate(category_ids):
                category = guild.get_channel(int(cat_id))
                if category is None or not isinstance(category, nextcord.CategoryChannel):
                    raise ValueError(f"Category '{cat_id}' not found in guild")
                payload.append({"id": int(cat_id), "position": position})

            # Use bulk edit
            await guild.edit_channel_positions(payload)
            logger.info("Reordered %d categories in guild '%s'", len(category_ids), guild.name)
            return {
                "reordered": True,
                "category_ids": [str(cid) for cid in category_ids],
                "count": len(category_ids),
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to reorder categories: {exc}")

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "create": self.create,
            "delete": self.delete,
            "rename": self.rename,
            "reorder": self.reorder,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for CategoriesConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for category operations."""
        return [
            ToolDefinition(
                name="discord.categories.create",
                description="Create a new category in the guild.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "name": {"type": "string", "description": "Category name."},
                    },
                    "required": ["guild_id", "name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.categories.delete",
                description="Delete a category (channels inside are NOT deleted).",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "category_id": {"type": "string", "description": "Category ID to delete."},
                    },
                    "required": ["guild_id", "category_id"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.categories.rename",
                description="Rename an existing category.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "category_id": {"type": "string", "description": "Category ID to rename."},
                        "new_name": {"type": "string", "description": "The new name."},
                    },
                    "required": ["guild_id", "category_id", "new_name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.categories.reorder",
                description="Reorder categories by providing IDs in desired order.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "category_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Category IDs in desired order.",
                        },
                    },
                    "required": ["guild_id", "category_ids"],
                },
                risk_level="medium",
            ),
        ]
