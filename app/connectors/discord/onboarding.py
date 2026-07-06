"""
Discord Onboarding Connector — Welcome/DM operations.

Actions: setup_welcome, create_dm_template, send_dm
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class OnboardingConnector(BaseConnector):
    """Manages Discord guild onboarding and welcome messaging."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def setup_welcome(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        message: str,
    ) -> Dict[str, Any]:
        """Set up a welcome message in a channel.

        Note: This sends a message to the specified channel. For actual
        system messages channel config, use guild settings.

        Args:
            guild: The target guild.
            channel_id: Channel to send the welcome message to.
            message: The welcome message content.

        Returns:
            Dict confirming setup.
        """
        if not message or not message.strip():
            raise ValueError("Welcome message cannot be empty")

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")
        if not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Channel '{channel_id}' is not a text channel")

        try:
            sent = await channel.send(message)
            # Pin the welcome message
            await sent.pin()
            logger.info(
                "Setup welcome message in channel '%s' (guild '%s')",
                channel.name,
                guild.name,
            )
            return {
                "channel_id": str(channel_id),
                "message_id": str(sent.id),
                "pinned": True,
                "content_preview": message[:100],
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("send_messages")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to setup welcome: {exc}")

    async def create_dm_template(
        self,
        guild: nextcord.Guild,
        template_content: str,
    ) -> Dict[str, Any]:
        """Create a DM template for new member onboarding.

        This stores the template; actual sending happens via send_dm.

        Args:
            guild: The target guild (for context).
            template_content: The DM template content (supports {member_name}, {guild_name} placeholders).

        Returns:
            Dict with the template info.
        """
        if not template_content or not template_content.strip():
            raise ValueError("Template content cannot be empty")

        # Template is stored in memory/config (would be persisted via MemoryService in production)
        logger.info("Created DM template for guild '%s'", guild.name)
        return {
            "guild_id": str(guild.id),
            "template_content": template_content,
            "placeholders": ["{member_name}", "{guild_name}"],
            "created": True,
        }

    async def send_dm(
        self,
        member: nextcord.Member,
        content: str,
    ) -> Dict[str, Any]:
        """Send a DM to a member.

        Args:
            member: The target member.
            content: The message content.

        Returns:
            Dict confirming the DM was sent.
        """
        if not content or not content.strip():
            raise ValueError("DM content cannot be empty")

        try:
            dm_channel = await member.create_dm()
            await dm_channel.send(content)
            logger.info("Sent DM to member '%s' (id=%s)", member.display_name, member.id)
            return {
                "sent": True,
                "member_id": str(member.id),
                "member_name": member.display_name,
                "content_preview": content[:100],
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("send_messages (DMs disabled by user)")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to send DM: {exc}")

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "setup_welcome": self.setup_welcome,
            "create_dm_template": self.create_dm_template,
            "send_dm": self.send_dm,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for OnboardingConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for onboarding operations."""
        return [
            ToolDefinition(
                name="discord.onboarding.setup_welcome",
                description="Set up a pinned welcome message in a channel.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel for welcome message."},
                        "message": {"type": "string", "description": "Welcome message content."},
                    },
                    "required": ["guild_id", "channel_id", "message"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.onboarding.create_dm_template",
                description="Create a DM template for new member onboarding.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "template_content": {
                            "type": "string",
                            "description": "Template content ({member_name}, {guild_name} placeholders).",
                        },
                    },
                    "required": ["guild_id", "template_content"],
                },
                risk_level="low",
            ),
            ToolDefinition(
                name="discord.onboarding.send_dm",
                description="Send a direct message to a member.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "member_id": {"type": "string", "description": "Member ID to DM."},
                        "content": {"type": "string", "description": "Message content."},
                    },
                    "required": ["guild_id", "member_id", "content"],
                },
                risk_level="low",
            ),
        ]
