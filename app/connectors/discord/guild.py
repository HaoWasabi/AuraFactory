"""Discord Guild Connector — kwargs pattern.

Actions: get_info, edit_profile, set_verification, set_system_channels,
         set_afk, set_notifications, set_widget
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import aiohttp
import nextcord

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_VERIFICATION_MAP = {
    "none": nextcord.VerificationLevel.none,
    "low": nextcord.VerificationLevel.low,
    "medium": nextcord.VerificationLevel.medium,
    "high": nextcord.VerificationLevel.high,
    "highest": nextcord.VerificationLevel.highest,
}

_NOTIFICATION_MAP = {
    "all_messages": nextcord.NotificationLevel.all_messages,
    "only_mentions": nextcord.NotificationLevel.only_mentions,
}

_CONTENT_FILTER_MAP = {
    "disabled": nextcord.ContentFilter.disabled,
    "no_role": nextcord.ContentFilter.no_role,
    "all_members": nextcord.ContentFilter.all_members,
}


async def _fetch_image(url: str) -> Optional[bytes]:
    """Download image bytes from URL."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as exc:
        logger.warning("Image fetch error for %s: %s", url, exc)
    return None


class GuildConnector(BaseConnector):
    """Guild-level settings with **kwargs."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {
            "get_info": self.get_info,
            "edit_profile": self.edit_profile,
            "set_verification": self.set_verification,
            "set_system_channels": self.set_system_channels,
            "set_afk": self.set_afk,
            "set_notifications": self.set_notifications,
            "set_widget": self.set_widget,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'. Available: {list(actions.keys())}")
        return await handler(guild, **kwargs)

    # ------------------------------------------------------------------

    async def get_info(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Full guild snapshot."""
        def _ch(ch):
            return {"id": str(ch.id), "name": ch.name} if ch else None

        return {
            "id": str(guild.id),
            "name": guild.name,
            "description": guild.description,
            "owner_id": str(guild.owner_id),
            "member_count": guild.member_count,
            "premium_tier": guild.premium_tier,
            "premium_subscriptions": guild.premium_subscription_count or 0,
            "channel_count": len(guild.channels),
            "role_count": len(guild.roles),
            "emoji_count": len(guild.emojis),
            "verification_level": str(guild.verification_level),
            "default_notifications": str(guild.default_notifications),
            "explicit_content_filter": str(guild.explicit_content_filter),
            "icon_url": str(guild.icon.url) if guild.icon else None,
            "banner_url": str(guild.banner.url) if guild.banner else None,
            "preferred_locale": str(guild.preferred_locale),
            "system_channel": _ch(guild.system_channel),
            "rules_channel": _ch(guild.rules_channel),
            "afk_channel": _ch(guild.afk_channel),
            "afk_timeout": guild.afk_timeout,
            "features": list(guild.features),
            "created_at": guild.created_at.isoformat(),
        }

    async def edit_profile(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Batch-edit server profile. kwargs: name, description, icon_url, banner_url, verification_level, explicit_content_filter, preferred_locale"""
        if not guild.me.guild_permissions.manage_guild:
            raise PermissionError("manage_guild")

        payload: Dict[str, Any] = {}
        updated: List[str] = []

        name = kwargs.pop("name", None)
        if name is not None:
            payload["name"] = name

        description = kwargs.pop("description", None)
        if description is not None:
            payload["description"] = description

        verification = kwargs.pop("verification_level", None)
        if verification is not None:
            lvl = _VERIFICATION_MAP.get(verification.lower())
            if lvl is None:
                raise ValueError(f"Invalid verification_level '{verification}'")
            payload["verification_level"] = lvl

        content_filter = kwargs.pop("explicit_content_filter", None)
        if content_filter is not None:
            flt = _CONTENT_FILTER_MAP.get(content_filter.lower())
            if flt is None:
                raise ValueError(f"Invalid content_filter '{content_filter}'")
            payload["explicit_content_filter"] = flt

        locale = kwargs.pop("preferred_locale", None)
        if locale is not None:
            payload["preferred_locale"] = locale

        # Icon
        icon_url = kwargs.pop("icon_url", None)
        if icon_url is not None:
            if icon_url == "":
                payload["icon"] = None
            else:
                img = await _fetch_image(icon_url)
                if img is None:
                    raise ValueError(f"Could not download icon from: {icon_url}")
                payload["icon"] = img

        # Banner
        banner_url = kwargs.pop("banner_url", None)
        if banner_url is not None:
            if banner_url == "":
                payload["banner"] = None
            else:
                if guild.premium_tier < 2:
                    raise ValueError("Banner requires Boost Level 2+")
                img = await _fetch_image(banner_url)
                if img is None:
                    raise ValueError(f"Could not download banner from: {banner_url}")
                payload["banner"] = img

        if not payload:
            raise ValueError("No valid edit parameters provided")

        try:
            await guild.edit(**payload)
            updated = [k for k in payload if k not in ("icon", "banner")]
            if "icon" in payload:
                updated.append("icon")
            if "banner" in payload:
                updated.append("banner")
            logger.info("Edited guild profile: %s", updated)
            return {"guild_id": str(guild.id), "updated_fields": updated}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to edit profile: {exc}")

    async def set_verification(self, guild: nextcord.Guild, level: str, **kwargs) -> Dict[str, Any]:
        """Set verification level."""
        lvl = _VERIFICATION_MAP.get(level.lower())
        if lvl is None:
            raise ValueError(f"Invalid level '{level}'. Valid: {list(_VERIFICATION_MAP.keys())}")

        try:
            await guild.edit(verification_level=lvl)
            logger.info("Set verification to '%s'", level)
            return {"verification_level": level}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def set_system_channels(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Configure system channels and flags."""
        payload: Dict[str, Any] = {}

        ch_id = kwargs.pop("system_channel_id", None)
        if ch_id is not None:
            ch = guild.get_channel(int(ch_id))
            if ch:
                payload["system_channel"] = ch

        # Build system channel flags
        flags = guild.system_channel_flags
        flag_map = {
            "suppress_join_notifications": "join_notifications",
            "suppress_premium_subscriptions": "premium_subscriptions",
            "suppress_guild_reminder_notifications": "guild_reminder_notifications",
            "suppress_join_notification_replies": "join_notification_replies",
        }
        for kwarg_name, flag_attr in flag_map.items():
            val = kwargs.pop(kwarg_name, None)
            if val is not None and hasattr(flags, flag_attr):
                setattr(flags, flag_attr, not val)  # suppress=True → flag=False

        payload["system_channel_flags"] = flags

        try:
            await guild.edit(**payload)
            logger.info("Updated system channels")
            return {"updated": True}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def set_afk(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Set AFK channel and timeout."""
        payload: Dict[str, Any] = {}

        ch_id = kwargs.pop("afk_channel_id", None)
        if ch_id is not None:
            ch = guild.get_channel(int(ch_id))
            if ch:
                payload["afk_channel"] = ch

        timeout = kwargs.pop("afk_timeout", None)
        if timeout is not None:
            valid = {60, 300, 900, 1800, 3600}
            if int(timeout) not in valid:
                raise ValueError(f"afk_timeout must be one of {valid}")
            payload["afk_timeout"] = int(timeout)

        if not payload:
            raise ValueError("Provide afk_channel_id or afk_timeout")

        try:
            await guild.edit(**payload)
            logger.info("Updated AFK settings")
            return {"updated": True, "fields": list(payload.keys())}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def set_notifications(self, guild: nextcord.Guild, level: str, **kwargs) -> Dict[str, Any]:
        """Set default notification level."""
        lvl = _NOTIFICATION_MAP.get(level.lower())
        if lvl is None:
            raise ValueError(f"Invalid level '{level}'. Valid: {list(_NOTIFICATION_MAP.keys())}")

        try:
            await guild.edit(default_notifications=lvl)
            return {"default_notifications": level}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def set_widget(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Enable/disable widget."""
        enabled = kwargs.pop("widget_enabled", None)
        ch_id = kwargs.pop("widget_channel_id", None)

        payload: Dict[str, Any] = {}
        if enabled is not None:
            payload["widget_enabled"] = enabled
        if ch_id is not None:
            ch = guild.get_channel(int(ch_id))
            if ch:
                payload["widget_channel"] = ch

        if not payload:
            raise ValueError("Provide widget_enabled or widget_channel_id")

        try:
            await guild.edit(**payload)
            return {"updated": True, "fields": list(payload.keys())}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")
