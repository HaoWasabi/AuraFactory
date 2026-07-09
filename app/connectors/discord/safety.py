"""Discord Safety Connector — kwargs pattern. Actions: set_content_filter, set_mfa"""

from __future__ import annotations
import logging
from typing import Any, Dict
import nextcord
from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_CONTENT_FILTER_MAP = {
    "disabled": nextcord.ContentFilter.disabled,
    "no_role": nextcord.ContentFilter.no_role,
    "all_members": nextcord.ContentFilter.all_members,
}


class SafetyConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {"set_content_filter": self.set_content_filter, "set_mfa": self.set_mfa}
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def set_content_filter(self, guild: nextcord.Guild, level: str, **kwargs) -> Dict[str, Any]:
        """Set explicit content filter."""
        flt = _CONTENT_FILTER_MAP.get(level.lower())
        if flt is None:
            raise ValueError(f"Invalid level '{level}'. Valid: {list(_CONTENT_FILTER_MAP.keys())}")
        try:
            await guild.edit(explicit_content_filter=flt)
            return {"content_filter": level}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")

    async def set_mfa(self, guild: nextcord.Guild, level: int, **kwargs) -> Dict[str, Any]:
        """Set MFA requirement for moderators (0=off, 1=on)."""
        if level not in (0, 1):
            raise ValueError("level must be 0 or 1")
        try:
            await guild.edit(mfa_level=level)
            return {"mfa_level": level}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
