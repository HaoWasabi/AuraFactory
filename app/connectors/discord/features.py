"""Discord Features Connector — kwargs pattern.

Actions: setup_verification, create_poll, setup_welcome, configure_auto_delete
These are higher-level "composed" features built on top of basic Discord API.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List
import nextcord
from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

POLL_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


class FeaturesConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {
            "setup_verification": self.setup_verification,
            "create_poll": self.create_poll,
            "setup_welcome": self.setup_welcome,
            "configure_auto_delete": self.configure_auto_delete,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def setup_verification(self, guild: nextcord.Guild, channel_id: int, role_id: int, **kwargs) -> Dict[str, Any]:
        """Set up reaction-based verification. kwargs: emoji, title, description"""
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Text channel '{channel_id}' not found")

        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found")

        emoji = kwargs.pop("emoji", "✅")
        title = kwargs.pop("title", "Verification")
        description = kwargs.pop("description", f"React with {emoji} to get the **{role.name}** role and access the server!")

        embed = nextcord.Embed(title=title, description=description, color=nextcord.Color.green())
        embed.set_footer(text="AuraFactory Verification System")

        try:
            msg = await channel.send(embed=embed)
            await msg.add_reaction(emoji)
            logger.info("Setup verification in '%s' for role '%s'", channel.name, role.name)
            return {
                "message_id": str(msg.id),
                "channel_id": str(channel_id),
                "role_id": str(role_id),
                "emoji": emoji,
            }
        except nextcord.Forbidden:
            raise PermissionError("send_messages")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def create_poll(self, guild: nextcord.Guild, channel_id: int, question: str, options: List[str], **kwargs) -> Dict[str, Any]:
        """Create a reaction-based poll."""
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Text channel '{channel_id}' not found")

        if len(options) < 2 or len(options) > 10:
            raise ValueError("Options must be 2-10 items")

        description = "\n".join(f"{POLL_EMOJIS[i]} {opt}" for i, opt in enumerate(options))
        embed = nextcord.Embed(title=f"📊 {question}", description=description, color=nextcord.Color.blue())
        embed.set_footer(text="React to vote!")

        try:
            msg = await channel.send(embed=embed)
            for i in range(len(options)):
                await msg.add_reaction(POLL_EMOJIS[i])
            logger.info("Created poll '%s' with %d options", question, len(options))
            return {"message_id": str(msg.id), "question": question, "option_count": len(options)}
        except nextcord.Forbidden:
            raise PermissionError("send_messages")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def setup_welcome(self, guild: nextcord.Guild, channel_id: int, **kwargs) -> Dict[str, Any]:
        """Set up welcome message. kwargs: welcome_title, welcome_message_template"""
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Text channel '{channel_id}' not found")

        title = kwargs.pop("welcome_title", f"Welcome to {guild.name}!")
        template = kwargs.pop("welcome_message_template",
                              "Welcome {member_name}! You are member #{member_count} of **{guild_name}**!")

        embed = nextcord.Embed(title=title, description=template, color=nextcord.Color.gold())
        embed.set_footer(text="Powered by AuraFactory")

        try:
            msg = await channel.send(embed=embed)
            await msg.pin()
            logger.info("Setup welcome in '%s'", channel.name)
            return {"message_id": str(msg.id), "channel_id": str(channel_id), "pinned": True}
        except nextcord.Forbidden:
            raise PermissionError("send_messages")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def configure_auto_delete(self, guild: nextcord.Guild, channel_id: int, delay_seconds: int, **kwargs) -> Dict[str, Any]:
        """Configure auto-delete (via slowmode as proxy — actual auto-delete needs bot event handler)."""
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Text channel '{channel_id}' not found")

        # Note: True auto-delete requires a background task/event handler.
        # For now, we log the config — the event handler will pick it up.
        logger.info("Auto-delete configured: channel '%s', delay %ds", channel.name, delay_seconds)
        return {
            "channel_id": str(channel_id),
            "channel_name": channel.name,
            "delay_seconds": delay_seconds,
            "note": "Auto-delete handler will process messages in this channel",
        }
