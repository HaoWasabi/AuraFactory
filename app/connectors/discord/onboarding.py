"""
Discord Onboarding Connector — Welcome channel messages and member DMs.

NOTE: This connector handles practical welcome/onboarding flows via
channel messages and DMs. It does NOT wrap Discord's native "Server
Onboarding" feature (the guided prompts flow in server settings) because
that API requires specific guild features and OAuth scopes not available
to regular bots.

Actions: send_welcome_message, send_dm
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class OnboardingConnector(BaseConnector):
    """Sends welcome messages to channels and DMs to members."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def send_welcome_message(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        message: str,
        pin: bool = False,
    ) -> Dict[str, Any]:
        """Send a welcome/announcement message to a channel, optionally pin it.

        This is suitable for:
        - Posting server rules in a #rules channel
        - Posting a welcome message in a #welcome channel
        - Posting an announcement when setting up a new server

        It does NOT configure Discord's built-in "Server Onboarding" flow
        (the new-member guided prompts). For that, use Discord server settings
        directly — it cannot be configured via the bot API.

        Args:
            guild: The target guild.
            channel_id: Channel to send the message to.
            message: The message content.
            pin: Whether to pin the message. Default False.

        Returns:
            Dict with message_id, channel_id, and whether it was pinned.
        """
        if not message or not message.strip():
            raise ValueError("Message content cannot be empty")

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")
        if not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Channel '{channel_id}' is not a text channel")

        try:
            sent = await channel.send(message)
            pinned = False
            if pin:
                await sent.pin()
                pinned = True

            logger.info(
                "Sent welcome message to channel '%s' in guild '%s' (pinned=%s)",
                channel.name, guild.name, pinned,
            )
            return {
                "message_id": str(sent.id),
                "channel_id": str(channel_id),
                "channel_name": channel.name,
                "pinned": pinned,
                "content_preview": message[:100],
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("send_messages")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to send welcome message: {exc}")

    async def send_dm(
        self,
        guild: nextcord.Guild,
        member_id: int,
        content: str,
    ) -> Dict[str, Any]:
        """Send a direct message to a member.

        Args:
            guild: The target guild.
            member_id: Member ID to DM.
            content: The message content. Supports {member_name} and {guild_name} placeholders.

        Returns:
            Dict confirming the DM was sent.
        """
        if not content or not content.strip():
            raise ValueError("DM content cannot be empty")

        member = guild.get_member(int(member_id))
        if member is None:
            raise ValueError(f"Member '{member_id}' not found in guild")

        # Resolve placeholders
        resolved = content.replace("{member_name}", member.display_name).replace(
            "{guild_name}", guild.name
        )

        try:
            dm_channel = await member.create_dm()
            await dm_channel.send(resolved)
            logger.info(
                "Sent DM to member '%s' (id=%s) in guild '%s'",
                member.display_name, member_id, guild.name,
            )
            return {
                "sent": True,
                "member_id": str(member_id),
                "member_name": member.display_name,
                "content_preview": resolved[:100],
            }
        except nextcord.errors.Forbidden:
            raise PermissionError(
                "Cannot send DM — member has DMs disabled or has blocked the bot"
            )
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to send DM: {exc}")

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "send_welcome_message": self.send_welcome_message,
            "send_dm": self.send_dm,
            # Legacy alias kept for backward compat
            "setup_welcome": self.send_welcome_message,
            "create_dm_template": self._create_dm_template_compat,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for OnboardingConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    async def _create_dm_template_compat(
        self,
        guild: nextcord.Guild,
        template_content: str,
    ) -> Dict[str, Any]:
        """Legacy compat — create_dm_template no longer stores anything (was in-memory only).

        Returns the template content for confirmation. Use send_dm to actually send.
        """
        logger.warning(
            "create_dm_template is deprecated — templates were never persisted. "
            "Use send_dm with placeholders {member_name} and {guild_name} directly."
        )
        return {
            "guild_id": str(guild.id),
            "template_content": template_content,
            "placeholders_supported": ["{member_name}", "{guild_name}"],
            "note": "Template confirmed but not persisted. Pass content directly to send_dm.",
        }

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for onboarding operations."""
        return [
            ToolDefinition(
                name="discord.onboarding.send_welcome_message",
                description=(
                    "Send a welcome or announcement message to a text channel, "
                    "optionally pinning it. Use this for setting up a #welcome or "
                    "#rules channel, or posting an intro message when creating a new server. "
                    "This does NOT configure Discord's native Server Onboarding flow — "
                    "that requires the server owner to set it up in Discord settings."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel to post the message in."},
                        "message": {"type": "string", "description": "Message content (max 2000 chars)."},
                        "pin": {
                            "type": "boolean",
                            "description": "Pin the message in the channel. Default false.",
                        },
                    },
                    "required": ["guild_id", "channel_id", "message"],
                },
                risk_level="low",
            ),
            ToolDefinition(
                name="discord.onboarding.send_dm",
                description=(
                    "Send a direct message to a specific member. "
                    "Supports {member_name} and {guild_name} placeholders in content. "
                    "Will fail gracefully if the member has DMs disabled."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "member_id": {"type": "string", "description": "Member ID to DM."},
                        "content": {
                            "type": "string",
                            "description": (
                                "Message content. "
                                "Use {member_name} and {guild_name} as placeholders."
                            ),
                        },
                    },
                    "required": ["guild_id", "member_id", "content"],
                },
                risk_level="low",
            ),
        ]
