"""Discord Onboarding Connector — kwargs pattern.

Actions: get, setup, setup_welcome, send_dm
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class OnboardingConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {
            "get": self.get,
            "setup": self.setup,
            "setup_welcome": self.setup_welcome,
            "send_dm": self.send_dm,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def get(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Fetch the guild onboarding configuration via REST API.

        Returns:
            Raw onboarding data dict from Discord API.

        Raises:
            PermissionError: If bot lacks permission.
            RuntimeError: If API request fails.
        """
        try:
            route = nextcord.http.Route(
                "GET", "/guilds/{guild_id}/onboarding", guild_id=guild.id
            )
            data = await self._bot.http.request(route)
            return data
        except nextcord.Forbidden as e:
            raise PermissionError(f"Missing permission to get onboarding: {e}") from e
        except nextcord.HTTPException as e:
            raise RuntimeError(f"Failed to get onboarding config: {e}") from e

    async def setup(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Configure guild onboarding via REST API.

        Expected kwargs:
            prompts: List[dict] — each prompt has {type, title, options: [{channel_ids, role_ids, title, description}]}
            default_channel_ids: List[int]
            enabled: bool

        Returns:
            {success: True, enabled: bool}

        Raises:
            ValueError: If required kwargs are missing or invalid.
            PermissionError: If bot lacks permission.
            RuntimeError: If API request fails.
        """
        prompts: List[dict] | None = kwargs.get("prompts")
        default_channel_ids: List[int] | None = kwargs.get("default_channel_ids")
        enabled: bool | None = kwargs.get("enabled")

        if prompts is None:
            raise ValueError("'prompts' is required for onboarding setup")
        if default_channel_ids is None:
            raise ValueError("'default_channel_ids' is required for onboarding setup")
        if enabled is None:
            raise ValueError("'enabled' is required for onboarding setup")

        payload: Dict[str, Any] = {
            "prompts": prompts,
            "default_channel_ids": default_channel_ids,
            "enabled": enabled,
        }

        try:
            route = nextcord.http.Route(
                "PUT", "/guilds/{guild_id}/onboarding", guild_id=guild.id
            )
            await self._bot.http.request(route, json=payload)
            return {"success": True, "enabled": enabled}
        except nextcord.Forbidden as e:
            raise PermissionError(f"Missing permission to setup onboarding: {e}") from e
        except nextcord.HTTPException as e:
            raise RuntimeError(f"Failed to setup onboarding: {e}") from e

    # ------------------------------------------------------------------
    # SETUP WELCOME CHANNEL
    # ------------------------------------------------------------------

    async def setup_welcome(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Configure a welcome/system channel with a welcome message.

        kwargs:
            channel_id: int — channel to use as welcome channel (system channel)
            welcome_message: str — message to display (shown via system channel flags)
            suppress_join_notifications: bool — if False, shows "X joined" messages
        """
        channel_id = kwargs.get("channel_id")
        suppress_join = kwargs.get("suppress_join_notifications", False)

        if not channel_id:
            raise ValueError("'channel_id' is required for welcome setup")

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found")

        if not guild.me.guild_permissions.manage_guild:
            raise PermissionError("manage_guild")

        try:
            # Set as system channel
            flags = guild.system_channel_flags
            flags.join_notifications = not suppress_join

            await guild.edit(
                system_channel=channel,
                system_channel_flags=flags,
            )
            logger.info("Set welcome/system channel to '%s' (id=%s)", channel.name, channel_id)
            return {
                "system_channel_id": str(channel_id),
                "system_channel_name": channel.name,
                "join_notifications_enabled": not suppress_join,
            }
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to setup welcome: {exc}")

    # ------------------------------------------------------------------
    # SEND DM TO MEMBER
    # ------------------------------------------------------------------

    async def send_dm(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Send a DM to a guild member on behalf of the bot.

        kwargs:
            member_id: int — target member
            message: str — message content (max 2000 chars)
        """
        member_id = kwargs.get("member_id")
        message = kwargs.get("message", "")

        if not member_id:
            raise ValueError("'member_id' is required")
        if not message or not message.strip():
            raise ValueError("'message' cannot be empty")
        if len(message) > 2000:
            raise ValueError("DM message exceeds 2000 character limit")

        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found in guild")

        try:
            # Create DM channel and send
            dm_channel = await member.create_dm()
            await dm_channel.send(message.strip())
            logger.info("Sent DM to member '%s' (id=%s) in guild '%s'",
                       member.display_name, member_id, guild.name)
            return {
                "sent": True,
                "member_id": str(member_id),
                "member_name": member.display_name,
                "message_length": len(message.strip()),
            }
        except nextcord.Forbidden:
            raise PermissionError(
                f"Cannot DM member '{member.display_name}' — they may have DMs disabled"
            )
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to send DM: {exc}")
