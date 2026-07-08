"""Discord Soundboard Connector — SPEC v2 new module (schema §9).

Actions: upload, edit, delete, list

Note: Soundboard API is relatively new in Discord. Some methods may
require newer nextcord versions or raw HTTP calls.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import nextcord

from app.connectors.base import BaseConnector
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import check_soundboard_quota, validate_kwargs

logger = logging.getLogger(__name__)


class SoundboardConnector(BaseConnector):
    """Manages Discord guild soundboard sounds."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def upload(self, guild: nextcord.Guild, name: str, sound_url: str, **kwargs) -> Dict[str, Any]:
        """Upload a new soundboard sound.

        Required: name, sound_url
        Optional: emoji_name, emoji_id, volume (0.0 - 1.0)
        """
        perm_error = check_bot_permissions(guild, "discord.soundboard.upload")
        if perm_error:
            raise PermissionError(perm_error)

        quota_error = check_soundboard_quota(guild)
        if quota_error:
            raise ValueError(quota_error)

        clean = validate_kwargs("discord.soundboard.upload", kwargs)

        # Soundboard API requires raw HTTP — not natively in nextcord
        # This is a placeholder for when the API is accessible
        logger.warning("Soundboard upload not fully implemented — requires newer Discord API support")
        return {
            "status": "not_implemented",
            "message": "Soundboard upload requires Discord API v10+ support not yet in nextcord.",
            "name": name,
        }

    async def edit(self, guild: nextcord.Guild, sound_id: int, **kwargs) -> Dict[str, Any]:
        """Edit a soundboard sound.

        Optional: name, emoji_name, emoji_id, volume
        """
        perm_error = check_bot_permissions(guild, "discord.soundboard.edit")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.soundboard.edit", kwargs)
        logger.warning("Soundboard edit not fully implemented — requires newer Discord API support")
        return {"status": "not_implemented", "sound_id": str(sound_id)}

    async def delete(self, guild: nextcord.Guild, sound_id: int, **kwargs) -> Dict[str, Any]:
        """Delete a soundboard sound."""
        perm_error = check_bot_permissions(guild, "discord.soundboard.delete")
        if perm_error:
            raise PermissionError(perm_error)

        logger.warning("Soundboard delete not fully implemented — requires newer Discord API support")
        return {"status": "not_implemented", "sound_id": str(sound_id)}

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all soundboard sounds (if available)."""
        # Soundboard sounds may not be available in current nextcord
        sounds = getattr(guild, "soundboard_sounds", [])
        result = []
        for s in sounds:
            result.append({
                "id": str(getattr(s, "id", "")),
                "name": getattr(s, "name", ""),
            })
        return {"sounds": result, "count": len(result)}
