"""
Discord Guild Connector — Full guild-level configuration operations.

Actions:
  get_info            — Detailed snapshot of server state
  edit_profile        — Batch-edit name, icon, banner, description, verification level
  set_community       — Enable / disable Community features with auto channel assignment
  set_verification    — Change verification level only
  set_system_channels — Configure system message channels (joins, boosts, tips)
  set_default_notifications — Change default notification level
  set_afk             — Set AFK channel and timeout
  set_preferred_locale — Change server locale
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import aiohttp
import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition
from app.connectors.discord._helpers import download_image_bytes
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import check_afk_channel_is_voice, check_afk_timeout, validate_kwargs

logger = logging.getLogger(__name__)

# Mapping of user-friendly string → nextcord enum
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


class GuildConnector(BaseConnector):
    """Manages Discord guild-level settings with full configuration support."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def get_info(self, guild: nextcord.Guild) -> Dict[str, Any]:
        """Get a full snapshot of the guild's current state.

        Returns comprehensive server info: identity, stats, feature flags,
        system channels, boost status, and moderation settings.

        Args:
            guild: Target guild.

        Returns:
            Dict with all guild details.
        """
        # Resolve channel names safely
        def _ch_info(ch: Optional[nextcord.abc.GuildChannel]) -> Optional[Dict]:
            if ch is None:
                return None
            return {"id": str(ch.id), "name": ch.name}

        return {
            "id": str(guild.id),
            "name": guild.name,
            "description": guild.description,
            "owner_id": str(guild.owner_id),
            # Members & boosts
            "member_count": guild.member_count,
            "premium_tier": guild.premium_tier,
            "premium_subscription_count": guild.premium_subscription_count or 0,
            # Counts
            "channel_count": len(guild.channels),
            "role_count": len(guild.roles),
            "emoji_count": len(guild.emojis),
            # Moderation
            "verification_level": str(guild.verification_level),
            "default_notifications": str(guild.default_notifications),
            "explicit_content_filter": str(guild.explicit_content_filter),
            # Identity
            "icon_url": str(guild.icon.url) if guild.icon else None,
            "banner_url": str(guild.banner.url) if guild.banner else None,
            "splash_url": str(guild.splash.url) if guild.splash else None,
            "preferred_locale": str(guild.preferred_locale),
            # System channels
            "system_channel": _ch_info(guild.system_channel),
            "rules_channel": _ch_info(guild.rules_channel),
            "public_updates_channel": _ch_info(guild.public_updates_channel),
            "afk_channel": _ch_info(guild.afk_channel),
            "afk_timeout": guild.afk_timeout,
            # Features
            "features": list(guild.features),
            "created_at": guild.created_at.isoformat(),
        }

    async def edit_profile(
        self,
        guild: nextcord.Guild,
        new_name: Optional[str] = None,
        icon_url: Optional[str] = None,
        banner_url: Optional[str] = None,
        description: Optional[str] = None,
        verification_level: Optional[str] = None,
        explicit_content_filter: Optional[str] = None,
        preferred_locale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Batch-edit multiple server profile fields in one call.

        Any parameter left as None is skipped — only provided fields are updated.

        Args:
            guild: Target guild.
            new_name: New server name (2–100 chars).
            icon_url: URL of new server icon image (PNG/JPG/GIF).
            banner_url: URL of new server banner image (requires boost level 2+).
            description: Server description shown in Discovery (Community servers).
            verification_level: One of 'none', 'low', 'medium', 'high', 'highest'.
            explicit_content_filter: One of 'disabled', 'no_role', 'all_members'.
            preferred_locale: IETF locale tag, e.g. 'en-US', 'vi', 'ja'.

        Returns:
            Dict with updated fields list.
        """
        if not guild.me.guild_permissions.manage_guild:
            raise PermissionError("manage_guild")

        payload: Dict[str, Any] = {}
        updated: List[str] = []

        if new_name is not None:
            if not new_name.strip():
                raise ValueError("Server name cannot be empty")
            payload["name"] = new_name.strip()

        if description is not None:
            payload["description"] = description

        if verification_level is not None:
            lvl = _VERIFICATION_MAP.get(verification_level.lower().strip())
            if lvl is None:
                raise ValueError(
                    f"Invalid verification_level '{verification_level}'. "
                    f"Valid: {list(_VERIFICATION_MAP.keys())}"
                )
            payload["verification_level"] = lvl

        if explicit_content_filter is not None:
            flt = _CONTENT_FILTER_MAP.get(explicit_content_filter.lower().strip())
            if flt is None:
                raise ValueError(
                    f"Invalid explicit_content_filter '{explicit_content_filter}'. "
                    f"Valid: {list(_CONTENT_FILTER_MAP.keys())}"
                )
            payload["explicit_content_filter"] = flt

        if preferred_locale is not None:
            payload["preferred_locale"] = preferred_locale

        # Download and attach icon / banner bytes
        if icon_url is not None:
            img = await download_image_bytes(icon_url)
            if img is None:
                raise ValueError(f"Could not download icon image from: {icon_url}")
            payload["icon"] = img
            updated.append("icon")

        if banner_url is not None:
            if guild.premium_tier < 2:
                raise ValueError(
                    f"Server banners require Boost Level 2+. "
                    f"Current level: {guild.premium_tier}."
                )
            img = await download_image_bytes(banner_url)
            if img is None:
                raise ValueError(f"Could not download banner image from: {banner_url}")
            payload["banner"] = img
            updated.append("banner")

        if not payload:
            raise ValueError("No valid edit parameters provided")

        try:
            await guild.edit(**payload)
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit server profile: {exc}")

        # Collect human-readable field names
        for key in payload:
            if key not in ("icon", "banner"):
                updated.append(key)

        logger.info("Edited guild '%s' profile: %s", guild.name, updated)
        return {
            "guild_id": str(guild.id),
            "guild_name": guild.name,
            "updated_fields": updated,
        }

    async def set_community(
        self,
        guild: nextcord.Guild,
        enable: bool,
        rules_channel_id: Optional[int] = None,
        updates_channel_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Enable or disable the Community feature on the server.

        When enabling, Discord requires a rules channel and a public updates
        channel. If not provided, the first available text channel is used as
        a fallback.

        Args:
            guild: Target guild.
            enable: True to enable Community, False to disable.
            rules_channel_id: ID of the channel to use as #rules (optional).
            updates_channel_id: ID of the channel for public update announcements (optional).

        Returns:
            Dict confirming the change and assigned channels.
        """
        if not guild.me.guild_permissions.manage_guild:
            raise PermissionError("manage_guild")

        current_features = list(guild.features)
        payload: Dict[str, Any] = {}

        if enable:
            if "COMMUNITY" not in current_features:
                current_features.append("COMMUNITY")

            # Resolve rules channel
            rules_ch: Optional[nextcord.TextChannel] = None
            if rules_channel_id:
                ch = guild.get_channel(int(rules_channel_id))
                if isinstance(ch, nextcord.TextChannel):
                    rules_ch = ch
            if rules_ch is None:
                rules_ch = guild.rules_channel or (
                    guild.text_channels[0] if guild.text_channels else None
                )
            if rules_ch is None:
                raise ValueError(
                    "Cannot enable Community: no text channels available for rules channel."
                )

            # Resolve public updates channel
            updates_ch: Optional[nextcord.TextChannel] = None
            if updates_channel_id:
                ch = guild.get_channel(int(updates_channel_id))
                if isinstance(ch, nextcord.TextChannel):
                    updates_ch = ch
            if updates_ch is None:
                updates_ch = guild.public_updates_channel or rules_ch

            payload["features"] = current_features
            payload["rules_channel"] = rules_ch
            payload["public_updates_channel"] = updates_ch
        else:
            if "COMMUNITY" in current_features:
                current_features.remove("COMMUNITY")
            payload["features"] = current_features

        try:
            await guild.edit(**payload)
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set community: {exc}")

        logger.info(
            "Community %s for guild '%s'", "enabled" if enable else "disabled", guild.name
        )
        result: Dict[str, Any] = {
            "guild_id": str(guild.id),
            "community_enabled": enable,
        }
        if enable:
            result["rules_channel"] = {"id": str(rules_ch.id), "name": rules_ch.name}
            result["updates_channel"] = {"id": str(updates_ch.id), "name": updates_ch.name}
        return result

    async def set_verification(
        self,
        guild: nextcord.Guild,
        level: str,
    ) -> Dict[str, Any]:
        """Change the server's verification level.

        Args:
            guild: Target guild.
            level: One of 'none', 'low', 'medium', 'high', 'highest'.

        Returns:
            Dict with old and new levels.
        """
        lvl = _VERIFICATION_MAP.get(level.lower().strip())
        if lvl is None:
            raise ValueError(
                f"Invalid level '{level}'. Valid: {list(_VERIFICATION_MAP.keys())}"
            )

        old_level = str(guild.verification_level)
        try:
            await guild.edit(verification_level=lvl)
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set verification level: {exc}")

        logger.info(
            "Verification level changed '%s' -> '%s' for guild '%s'",
            old_level, level, guild.name,
        )
        return {
            "guild_id": str(guild.id),
            "old_level": old_level,
            "new_level": level.lower().strip(),
        }

    async def set_system_channels(
        self,
        guild: nextcord.Guild,
        system_channel_id: Optional[int] = None,
        disable_join_messages: Optional[bool] = None,
        disable_boost_messages: Optional[bool] = None,
        disable_tips: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Configure system message channels and their flags.

        Args:
            guild: Target guild.
            system_channel_id: Channel ID where system messages are sent.
            disable_join_messages: True to suppress member join messages.
            disable_boost_messages: True to suppress boost celebration messages.
            disable_tips: True to suppress helpful tips for new members.

        Returns:
            Dict with updated configuration.
        """
        payload: Dict[str, Any] = {}

        if system_channel_id is not None:
            ch = guild.get_channel(int(system_channel_id))
            if not isinstance(ch, nextcord.TextChannel):
                raise ValueError(f"Channel '{system_channel_id}' is not a text channel")
            payload["system_channel"] = ch

        # Build SystemChannelFlags from current state + overrides
        if any(f is not None for f in [disable_join_messages, disable_boost_messages, disable_tips]):
            current_flags = guild.system_channel_flags
            flags = nextcord.SystemChannelFlags._from_value(current_flags.value)  # type: ignore[attr-defined]
            if disable_join_messages is not None:
                flags.join_notifications = not disable_join_messages
            if disable_boost_messages is not None:
                flags.premium_subscriptions = not disable_boost_messages
            if disable_tips is not None:
                flags.guild_reminder_notifications = not disable_tips
            payload["system_channel_flags"] = flags

        if not payload:
            raise ValueError("No system channel parameters provided")

        try:
            await guild.edit(**payload)
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to update system channels: {exc}")

        updated = list(payload.keys())
        logger.info("System channels updated for guild '%s': %s", guild.name, updated)
        return {"guild_id": str(guild.id), "updated_fields": updated}

    async def set_default_notifications(
        self,
        guild: nextcord.Guild,
        level: str,
    ) -> Dict[str, Any]:
        """Set the default notification level for the server.

        Args:
            guild: Target guild.
            level: 'all_messages' or 'only_mentions'.

        Returns:
            Dict with old and new levels.
        """
        lvl = _NOTIFICATION_MAP.get(level.lower().strip())
        if lvl is None:
            raise ValueError(
                f"Invalid level '{level}'. Valid: {list(_NOTIFICATION_MAP.keys())}"
            )

        old_level = str(guild.default_notifications)
        try:
            await guild.edit(default_notifications=lvl)
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set notification level: {exc}")

        logger.info(
            "Default notifications '%s' -> '%s' for guild '%s'",
            old_level, level, guild.name,
        )
        return {
            "guild_id": str(guild.id),
            "old_level": old_level,
            "new_level": level.lower().strip(),
        }

    async def set_afk(
        self,
        guild: nextcord.Guild,
        afk_channel_id: Optional[int] = None,
        afk_timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Configure the AFK voice channel and timeout.

        Args:
            guild: Target guild.
            afk_channel_id: Voice channel ID for AFK users (None to clear).
            afk_timeout: Seconds before moving idle users (60, 300, 900, 1800, 3600).

        Returns:
            Dict confirming the change.
        """
        valid_timeouts = {60, 300, 900, 1800, 3600}
        payload: Dict[str, Any] = {}

        if afk_channel_id is not None:
            ch = guild.get_channel(int(afk_channel_id))
            if not isinstance(ch, nextcord.VoiceChannel):
                raise ValueError(f"Channel '{afk_channel_id}' is not a voice channel")
            payload["afk_channel"] = ch

        if afk_timeout is not None:
            if int(afk_timeout) not in valid_timeouts:
                raise ValueError(
                    f"Invalid afk_timeout '{afk_timeout}'. "
                    f"Valid values (seconds): {sorted(valid_timeouts)}"
                )
            payload["afk_timeout"] = int(afk_timeout)

        if not payload:
            raise ValueError("Provide afk_channel_id and/or afk_timeout")

        try:
            await guild.edit(**payload)
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set AFK config: {exc}")

        result: Dict[str, Any] = {"guild_id": str(guild.id)}
        if "afk_channel" in payload:
            ch = payload["afk_channel"]
            result["afk_channel"] = {"id": str(ch.id), "name": ch.name}
        if "afk_timeout" in payload:
            result["afk_timeout_seconds"] = payload["afk_timeout"]

        logger.info("AFK config updated for guild '%s': %s", guild.name, result)
        return result

    async def set_preferred_locale(
        self,
        guild: nextcord.Guild,
        locale: str,
    ) -> Dict[str, Any]:
        """Set the server's preferred locale / language.

        Args:
            guild: Target guild.
            locale: IETF BCP 47 locale tag, e.g. 'en-US', 'vi', 'ja', 'ko', 'fr'.

        Returns:
            Dict with old and new locale.
        """
        old_locale = str(guild.preferred_locale)
        try:
            await guild.edit(preferred_locale=locale)
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set preferred locale: {exc}")

        logger.info(
            "Preferred locale '%s' -> '%s' for guild '%s'", old_locale, locale, guild.name
        )
        return {
            "guild_id": str(guild.id),
            "old_locale": old_locale,
            "new_locale": locale,
        }

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "get_info": self.get_info,
            "edit_profile": self.edit_profile,
            "set_community": self.set_community,
            "set_verification": self.set_verification,
            "set_system_channels": self.set_system_channels,
            "set_default_notifications": self.set_default_notifications,
            "set_afk": self.set_afk,
            "set_preferred_locale": self.set_preferred_locale,
            # Legacy aliases kept for backward compatibility
            "edit_name": self._legacy_edit_name,
            "edit_icon": self._legacy_edit_icon,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for GuildConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    # Legacy shims so existing plans with old action names still work
    async def _legacy_edit_name(self, guild: nextcord.Guild, new_name: str, **_: Any) -> Dict[str, Any]:
        return await self.edit_profile(guild, new_name=new_name)

    async def _legacy_edit_icon(self, guild: nextcord.Guild, icon_url: str, **_: Any) -> Dict[str, Any]:
        return await self.edit_profile(guild, icon_url=icon_url)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for all guild operations."""
        return [
            ToolDefinition(
                name="discord.guild.get_info",
                description=(
                    "Get a full snapshot of the server's current state: name, description, member count, "
                    "boost tier, verification level, notification settings, system channels, AFK config, "
                    "active features, locale, and icon/banner URLs."
                ),
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
                name="discord.guild.edit_profile",
                description=(
                    "Batch-edit server profile fields in a single call. "
                    "Supports: rename, change icon (via URL), change banner (Boost Lv2+, via URL), "
                    "set description, verification level, explicit content filter, and preferred locale. "
                    "Only provided fields are updated; omitted fields are left unchanged."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "new_name": {"type": "string", "description": "New server name (2–100 chars)."},
                        "icon_url": {"type": "string", "description": "URL of new server icon (PNG/JPG/GIF)."},
                        "banner_url": {
                            "type": "string",
                            "description": "URL of new server banner image. Requires Boost Level 2+.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Server description (Community servers only, max 120 chars).",
                        },
                        "verification_level": {
                            "type": "string",
                            "enum": ["none", "low", "medium", "high", "highest"],
                            "description": (
                                "Member verification requirement. "
                                "none=unrestricted, low=email verified, medium=registered 5+ min, "
                                "high=member 10+ min, highest=phone verified."
                            ),
                        },
                        "explicit_content_filter": {
                            "type": "string",
                            "enum": ["disabled", "no_role", "all_members"],
                            "description": "Auto-scan media: disabled=off, no_role=members without roles, all_members=everyone.",
                        },
                        "preferred_locale": {
                            "type": "string",
                            "description": "IETF locale tag, e.g. 'en-US', 'vi', 'ja', 'ko', 'fr', 'de'.",
                        },
                    },
                    "required": ["guild_id"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.guild.set_community",
                description=(
                    "Enable or disable the Community feature on the server. "
                    "Enabling Community unlocks stage channels, announcement channels, member screening, "
                    "and Server Discovery. Requires a rules channel and a public updates channel — "
                    "the bot will fall back to the first text channel if not specified."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "enable": {
                            "type": "boolean",
                            "description": "True to enable Community, False to disable.",
                        },
                        "rules_channel_id": {
                            "type": "string",
                            "description": "Text channel ID to use as the rules channel (optional, auto-detected if omitted).",
                        },
                        "updates_channel_id": {
                            "type": "string",
                            "description": "Text channel ID for public update announcements (optional).",
                        },
                    },
                    "required": ["guild_id", "enable"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.guild.set_verification",
                description=(
                    "Change only the server verification level. "
                    "Shorthand when you need to adjust security without touching other profile fields."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "level": {
                            "type": "string",
                            "enum": ["none", "low", "medium", "high", "highest"],
                            "description": "Target verification level.",
                        },
                    },
                    "required": ["guild_id", "level"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.guild.set_system_channels",
                description=(
                    "Configure the system messages channel and toggle system message types: "
                    "member join notifications, boost celebration messages, and helpful tips for new members."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "system_channel_id": {
                            "type": "string",
                            "description": "Text channel ID to receive system messages.",
                        },
                        "disable_join_messages": {
                            "type": "boolean",
                            "description": "True to hide member join notifications.",
                        },
                        "disable_boost_messages": {
                            "type": "boolean",
                            "description": "True to hide server boost celebration messages.",
                        },
                        "disable_tips": {
                            "type": "boolean",
                            "description": "True to hide helpful tips for new members.",
                        },
                    },
                    "required": ["guild_id"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.guild.set_default_notifications",
                description=(
                    "Set the default notification level for all members. "
                    "'all_messages' pings members for every message; 'only_mentions' is less noisy."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "level": {
                            "type": "string",
                            "enum": ["all_messages", "only_mentions"],
                            "description": "Default notification preference.",
                        },
                    },
                    "required": ["guild_id", "level"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.guild.set_afk",
                description=(
                    "Configure the AFK voice channel and idle timeout. "
                    "Idle members are moved to the AFK channel after the timeout elapses."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "afk_channel_id": {
                            "type": "string",
                            "description": "Voice channel ID for AFK users.",
                        },
                        "afk_timeout": {
                            "type": "integer",
                            "enum": [60, 300, 900, 1800, 3600],
                            "description": "Idle timeout in seconds before moving to AFK channel (1m/5m/15m/30m/1h).",
                        },
                    },
                    "required": ["guild_id"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.guild.set_preferred_locale",
                description="Set the server's preferred language/locale used in system messages and Discovery.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "locale": {
                            "type": "string",
                            "description": "IETF BCP 47 locale tag, e.g. 'en-US', 'vi', 'ja', 'ko', 'fr', 'de', 'zh-CN'.",
                        },
                    },
                    "required": ["guild_id", "locale"],
                },
                risk_level="low",
            ),
        ]
