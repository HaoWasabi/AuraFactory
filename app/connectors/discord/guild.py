"""
Discord Guild Connector — Guild-level configuration operations.

Actions: edit_name, edit_icon, edit_settings, get_info
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class GuildConnector(BaseConnector):
    """Manages Discord guild-level settings."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def edit_name(
        self,
        guild: nextcord.Guild,
        new_name: str,
    ) -> Dict[str, Any]:
        """Change the guild name.

        Args:
            guild: The target guild.
            new_name: The new guild name.

        Returns:
            Dict with old and new names.
        """
        if not new_name or not new_name.strip():
            raise ValueError("Guild name cannot be empty")

        try:
            old_name = guild.name
            await guild.edit(name=new_name)
            logger.info("Renamed guild '%s' -> '%s'", old_name, new_name)
            return {
                "old_name": old_name,
                "new_name": new_name,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit guild name: {exc}")

    async def edit_icon(
        self,
        guild: nextcord.Guild,
        icon_url: str,
    ) -> Dict[str, Any]:
        """Change the guild icon.

        Args:
            guild: The target guild.
            icon_url: URL of the new icon image.

        Returns:
            Dict confirming the change.
        """
        if not icon_url or not icon_url.strip():
            raise ValueError("Icon URL cannot be empty")

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(icon_url) as resp:
                    if resp.status != 200:
                        raise ValueError(f"Failed to fetch icon: HTTP {resp.status}")
                    icon_data = await resp.read()

            await guild.edit(icon=icon_data)
            logger.info("Updated icon for guild '%s'", guild.name)
            return {
                "guild_id": str(guild.id),
                "icon_updated": True,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit guild icon: {exc}")

    async def edit_settings(
        self,
        guild: nextcord.Guild,
        verification_level: Optional[str] = None,
        default_notifications: Optional[str] = None,
        explicit_content_filter: Optional[str] = None,
        afk_channel_id: Optional[int] = None,
        afk_timeout: Optional[int] = None,
        system_channel_id: Optional[int] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Edit guild settings (verification level, notifications, AFK, etc.).

        Args:
            guild: The target guild.
            verification_level: 'none' | 'low' | 'medium' | 'high' | 'highest'
            default_notifications: 'all_messages' | 'only_mentions'
            explicit_content_filter: 'disabled' | 'no_role' | 'all_members'
            afk_channel_id: Voice channel ID for AFK (must be a voice channel).
            afk_timeout: AFK timeout seconds — must be one of 60, 300, 900, 1800, 3600.
            system_channel_id: Text channel for system messages (join/boost notices).
            description: Server description (Community servers only).

        Returns:
            Dict with all changed fields.
        """
        _VERIFICATION = {
            "none": nextcord.VerificationLevel.none,
            "low": nextcord.VerificationLevel.low,
            "medium": nextcord.VerificationLevel.medium,
            "high": nextcord.VerificationLevel.high,
            "highest": nextcord.VerificationLevel.highest,
        }
        _NOTIFICATIONS = {
            "all_messages": nextcord.NotificationLevel.all_messages,
            "only_mentions": nextcord.NotificationLevel.only_mentions,
        }
        _EXPLICIT = {
            "disabled": nextcord.ContentFilter.disabled,
            "no_role": nextcord.ContentFilter.no_role,
            "all_members": nextcord.ContentFilter.all_members,
        }
        _VALID_AFK_TIMEOUTS = {60, 300, 900, 1800, 3600}

        kwargs: Dict[str, Any] = {}
        changed: Dict[str, Any] = {}

        if verification_level is not None:
            vl = verification_level.lower()
            if vl not in _VERIFICATION:
                raise ValueError(
                    f"Invalid verification_level '{verification_level}'. "
                    f"Valid: {list(_VERIFICATION.keys())}"
                )
            kwargs["verification_level"] = _VERIFICATION[vl]
            changed["verification_level"] = vl

        if default_notifications is not None:
            dn = default_notifications.lower()
            if dn not in _NOTIFICATIONS:
                raise ValueError(
                    f"Invalid default_notifications '{default_notifications}'. "
                    f"Valid: {list(_NOTIFICATIONS.keys())}"
                )
            kwargs["default_notifications"] = _NOTIFICATIONS[dn]
            changed["default_notifications"] = dn

        if explicit_content_filter is not None:
            ecf = explicit_content_filter.lower()
            if ecf not in _EXPLICIT:
                raise ValueError(
                    f"Invalid explicit_content_filter '{explicit_content_filter}'. "
                    f"Valid: {list(_EXPLICIT.keys())}"
                )
            kwargs["explicit_content_filter"] = _EXPLICIT[ecf]
            changed["explicit_content_filter"] = ecf

        if afk_channel_id is not None:
            afk_ch = guild.get_channel(int(afk_channel_id))
            if afk_ch is None or not isinstance(afk_ch, nextcord.VoiceChannel):
                raise ValueError(
                    f"AFK channel '{afk_channel_id}' not found or is not a voice channel"
                )
            kwargs["afk_channel"] = afk_ch
            changed["afk_channel_id"] = str(afk_channel_id)

        if afk_timeout is not None:
            if int(afk_timeout) not in _VALID_AFK_TIMEOUTS:
                raise ValueError(
                    f"Invalid afk_timeout '{afk_timeout}'. "
                    f"Valid values (seconds): {sorted(_VALID_AFK_TIMEOUTS)}"
                )
            kwargs["afk_timeout"] = int(afk_timeout)
            changed["afk_timeout"] = int(afk_timeout)

        if system_channel_id is not None:
            sys_ch = guild.get_channel(int(system_channel_id))
            if sys_ch is None or not isinstance(sys_ch, nextcord.TextChannel):
                raise ValueError(
                    f"System channel '{system_channel_id}' not found or is not a text channel"
                )
            kwargs["system_channel"] = sys_ch
            changed["system_channel_id"] = str(system_channel_id)

        if description is not None:
            kwargs["description"] = description
            changed["description"] = description

        if not kwargs:
            raise ValueError(
                "No settings provided. Provide at least one of: "
                "verification_level, default_notifications, explicit_content_filter, "
                "afk_channel_id, afk_timeout, system_channel_id, description."
            )

        try:
            await guild.edit(**kwargs)
            logger.info("Edited settings for guild '%s': %s", guild.name, list(changed.keys()))
            return {
                "guild_id": str(guild.id),
                "updated_settings": changed,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit guild settings: {exc}")

    async def get_info(
        self,
        guild: nextcord.Guild,
    ) -> Dict[str, Any]:
        """Get detailed guild information.

        Args:
            guild: The target guild.

        Returns:
            Dict with guild details.
        """
        return {
            "id": str(guild.id),
            "name": guild.name,
            "description": guild.description,
            "owner_id": str(guild.owner_id),
            "member_count": guild.member_count,
            "channel_count": len(guild.channels),
            "role_count": len(guild.roles),
            "emoji_count": len(guild.emojis),
            "icon_url": str(guild.icon.url) if guild.icon else None,
            "created_at": guild.created_at.isoformat(),
            "verification_level": str(guild.verification_level),
            "default_notifications": str(guild.default_notifications),
            "explicit_content_filter": str(guild.explicit_content_filter),
            "afk_timeout": guild.afk_timeout,
            "afk_channel_id": str(guild.afk_channel.id) if guild.afk_channel else None,
            "system_channel_id": str(guild.system_channel.id) if guild.system_channel else None,
            "premium_tier": guild.premium_tier,
            "premium_subscription_count": guild.premium_subscription_count,
        }

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "edit_name": self.edit_name,
            "edit_icon": self.edit_icon,
            "edit_settings": self.edit_settings,
            "get_info": self.get_info,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for GuildConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for guild operations."""
        return [
            ToolDefinition(
                name="discord.guild.edit_name",
                description="Change the guild (server) name.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "new_name": {"type": "string", "description": "New guild name."},
                    },
                    "required": ["guild_id", "new_name"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.guild.edit_icon",
                description="Change the guild (server) icon.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "icon_url": {"type": "string", "description": "URL of the new icon image."},
                    },
                    "required": ["guild_id", "icon_url"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.guild.edit_settings",
                description=(
                    "Edit guild-level settings: verification level, content filter, "
                    "default notifications, AFK channel/timeout, system channel, description. "
                    "Use this for any 'server settings' request that doesn't involve "
                    "channels, roles, or permissions."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "verification_level": {
                            "type": "string",
                            "enum": ["none", "low", "medium", "high", "highest"],
                            "description": (
                                "Member verification requirement. "
                                "'low'=email verified, 'medium'=5min Discord account age, "
                                "'high'=10min server member, 'highest'=phone verified."
                            ),
                        },
                        "default_notifications": {
                            "type": "string",
                            "enum": ["all_messages", "only_mentions"],
                            "description": "Default notification setting for new members.",
                        },
                        "explicit_content_filter": {
                            "type": "string",
                            "enum": ["disabled", "no_role", "all_members"],
                            "description": (
                                "Auto-scan messages for explicit content. "
                                "'no_role'=scan members without roles, 'all_members'=scan everyone."
                            ),
                        },
                        "afk_channel_id": {
                            "type": "string",
                            "description": "Voice channel ID to move idle members to (must be a voice channel).",
                        },
                        "afk_timeout": {
                            "type": "integer",
                            "enum": [60, 300, 900, 1800, 3600],
                            "description": "Idle time in seconds before moving to AFK channel.",
                        },
                        "system_channel_id": {
                            "type": "string",
                            "description": "Text channel ID for system messages (new member joins, boosts).",
                        },
                        "description": {
                            "type": "string",
                            "description": "Server description (Community servers only, max 120 chars).",
                        },
                    },
                    "required": ["guild_id"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.guild.get_info",
                description=(
                    "Get detailed guild information: name, member count, verification level, "
                    "content filter, AFK settings, system channel, and more."
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
        ]
