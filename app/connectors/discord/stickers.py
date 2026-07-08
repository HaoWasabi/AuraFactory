"""Discord Stickers Connector — SPEC v2 new module (schema §9).

Actions: upload, edit, delete, list
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import nextcord

from app.connectors.base import BaseConnector
from app.connectors.discord._helpers import download_image_bytes
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import check_sticker_quota, validate_kwargs

logger = logging.getLogger(__name__)


class StickersConnector(BaseConnector):
    """Manages Discord guild stickers."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def upload(self, guild: nextcord.Guild, name: str, file_url: str, **kwargs) -> Dict[str, Any]:
        """Upload a new sticker to the guild.

        Required: name, file_url
        Optional: description, tags
        """
        perm_error = check_bot_permissions(guild, "discord.stickers.upload")
        if perm_error:
            raise PermissionError(perm_error)

        # Check quota
        quota_error = check_sticker_quota(guild)
        if quota_error:
            raise ValueError(quota_error)

        clean = validate_kwargs("discord.stickers.upload", kwargs)

        # Download sticker image
        img_bytes = await download_image_bytes(file_url)
        if not img_bytes:
            raise ValueError(f"Could not download sticker image from: {file_url}")

        description = clean.get("description", "")
        tags = clean.get("tags", name)  # Discord requires at least one tag

        try:
            sticker = await guild.create_sticker(
                name=name,
                description=description,
                emoji=tags if isinstance(tags, str) else tags[0] if tags else name,
                file=nextcord.File(fp=__import__("io").BytesIO(img_bytes), filename=f"{name}.png"),
            )
            logger.info("Uploaded sticker '%s' (id=%s) to guild '%s'", sticker.name, sticker.id, guild.name)
            return {
                "id": str(sticker.id),
                "name": sticker.name,
                "description": description,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Emojis and Stickers' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to upload sticker: {exc}")

    async def edit(self, guild: nextcord.Guild, sticker_id: int, **kwargs) -> Dict[str, Any]:
        """Edit an existing sticker.

        Optional: name, description, tags
        """
        perm_error = check_bot_permissions(guild, "discord.stickers.edit")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.stickers.edit", kwargs)
        if not clean:
            raise ValueError("No valid edit parameters provided.")

        try:
            sticker = await guild.fetch_sticker(int(sticker_id))
            await sticker.edit(**clean)
            logger.info("Edited sticker '%s' (id=%s)", sticker.name, sticker_id)
            return {"id": str(sticker_id), "updated_fields": list(clean.keys())}
        except nextcord.errors.NotFound:
            raise ValueError(f"Sticker '{sticker_id}' not found.")
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Emojis and Stickers' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit sticker: {exc}")

    async def delete(self, guild: nextcord.Guild, sticker_id: int, **kwargs) -> Dict[str, Any]:
        """Delete a sticker from the guild."""
        perm_error = check_bot_permissions(guild, "discord.stickers.delete")
        if perm_error:
            raise PermissionError(perm_error)

        try:
            sticker = await guild.fetch_sticker(int(sticker_id))
            name = sticker.name
            await sticker.delete()
            logger.info("Deleted sticker '%s' (id=%s)", name, sticker_id)
            return {"id": str(sticker_id), "name": name, "deleted": True}
        except nextcord.errors.NotFound:
            raise ValueError(f"Sticker '{sticker_id}' not found.")
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Emojis and Stickers' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete sticker: {exc}")

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all stickers in the guild."""
        stickers = []
        for s in guild.stickers:
            stickers.append({
                "id": str(s.id),
                "name": s.name,
                "description": s.description,
                "format": str(s.format),
            })
        return {"stickers": stickers, "count": len(stickers)}
