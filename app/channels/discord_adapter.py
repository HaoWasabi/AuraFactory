# app/channels/discord_adapter.py
"""
Discord Channel Adapter — connects nextcord Bot to AuraFactory pipeline.
Handles: on_ready, on_message, on_member_join.
Routes messages through Gateway → Orchestrator → response.
"""
import asyncio
import logging
from typing import Any, Optional, Callable, Awaitable

import nextcord
from nextcord.ext import commands

from app.channels.base import ChannelAdapterBase
from app.models.messages import IncomingMessage, OutgoingMessage
from app.config.settings import settings

logger = logging.getLogger(__name__)

# Maximum Discord message length
MAX_DISCORD_LENGTH = 2000
# Embed threshold — if response exceeds this, use embed
EMBED_THRESHOLD = 1800


class DiscordAdapter(ChannelAdapterBase):
    """
    Discord adapter using nextcord.Bot.

    Responsibilities:
    - Receive Discord messages → IncomingMessage
    - Route to app.process_message()
    - Send responses back (text or embed for long content)
    - Handle member join events for onboarding
    """

    def __init__(
        self,
        token: str,
        process_message_fn: Callable[[IncomingMessage], Awaitable[OutgoingMessage]],
        knowledge_crawler: Any = None,
        onboarding_handler: Any = None,
    ):
        self._token = token
        self._process_message = process_message_fn
        self._knowledge_crawler = knowledge_crawler
        self._onboarding_handler = onboarding_handler

        # Configure intents
        intents = nextcord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True

        self._bot = commands.Bot(
            command_prefix="!aura ",
            intents=intents,
            help_command=None,
        )

        # Register event handlers
        self._register_events()

    @property
    def bot(self) -> commands.Bot:
        """Expose bot instance for external access."""
        return self._bot

    def _register_events(self) -> None:
        """Register all Discord event handlers."""

        @self._bot.event
        async def on_ready():
            await self._on_ready()

        @self._bot.event
        async def on_message(message: nextcord.Message):
            await self._on_message(message)

        @self._bot.event
        async def on_member_join(member: nextcord.Member):
            await self._on_member_join(member)

    # ================================================================
    # Event Handlers
    # ================================================================

    async def _on_ready(self) -> None:
        """Bot connected — log status and crawl guild knowledge."""
        # Set bot presence (shows "online" with activity)
        activity = nextcord.Activity(
            type=nextcord.ActivityType.watching,
            name="your server | @AuraFactory",
        )
        await self._bot.change_presence(status=nextcord.Status.online, activity=activity)

        logger.info(
            f"✅ AuraFactory connected as {self._bot.user} "
            f"| Guilds: {len(self._bot.guilds)}"
        )

        # Crawl knowledge for all connected guilds
        if self._knowledge_crawler:
            for guild in self._bot.guilds:
                try:
                    await self._knowledge_crawler.crawl_and_store(guild)
                    logger.info(f"📚 Knowledge crawled for guild: {guild.name} ({guild.id})")
                except Exception as e:
                    logger.error(f"Failed to crawl guild {guild.name}: {e}")

    async def _on_message(self, message: nextcord.Message) -> None:
        """Handle incoming Discord message."""
        # Ignore self and other bots
        if message.author == self._bot.user:
            return
        if message.author.bot:
            return

        # Check if bot should respond:
        # 1. Bot is mentioned
        # 2. Message is in DM
        # 3. Message is in designated channel (aura-admin, aura-chat)
        should_respond = self._should_respond(message)
        if not should_respond:
            return

        # Strip bot mention from content
        content = self._clean_content(message)
        if not content.strip():
            return

        # Convert to IncomingMessage
        incoming = await self.receive(message)
        incoming.prompt = content  # Use cleaned content

        # Show typing indicator while processing
        async with message.channel.typing():
            try:
                response = await self._process_message(incoming)
                await self.send(response, message.channel)
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                await message.channel.send(
                    "⚠️ Đã xảy ra lỗi khi xử lý tin nhắn. Vui lòng thử lại."
                )

    async def _on_member_join(self, member: nextcord.Member) -> None:
        """Handle new member joining — trigger onboarding."""
        if member.bot:
            return

        logger.info(f"👋 New member joined: {member.name} in {member.guild.name}")

        if self._onboarding_handler:
            try:
                await self._onboarding_handler.handle_join(member)
            except Exception as e:
                logger.error(f"Onboarding error for {member.name}: {e}")

    # ================================================================
    # ChannelAdapterBase Implementation
    # ================================================================

    async def receive(self, raw_input: Any) -> IncomingMessage:
        """Convert nextcord.Message to IncomingMessage."""
        message: nextcord.Message = raw_input

        # Determine user roles
        user_roles = []
        is_admin = False
        if message.guild and isinstance(message.author, nextcord.Member):
            user_roles = [role.name for role in message.author.roles if role.name != "@everyone"]
            is_admin = message.author.guild_permissions.administrator or (
                message.author == message.guild.owner
            )

        # Detect channel context
        is_dm = isinstance(message.channel, nextcord.DMChannel)
        channel_name = getattr(message.channel, "name", "dm") if not is_dm else "dm"

        return IncomingMessage(
            user_id=str(message.author.id),
            user_name=message.author.display_name,
            prompt=message.content,
            user_roles=user_roles,
            is_admin=is_admin,
            guild_id=message.guild.id if message.guild else None,
            channel_id=message.channel.id,
            message_id=str(message.id),
            source="discord",
            attachments=[a.url for a in message.attachments],
            metadata={
                "channel_name": channel_name,
                "is_dm": is_dm,
                "guild_name": message.guild.name if message.guild else None,
            },
        )

    async def send(self, message: OutgoingMessage, destination: Any) -> None:
        """Send OutgoingMessage to Discord channel."""
        channel = destination
        content = message.content

        if not content:
            return

        # Use embed for long messages
        if len(content) > EMBED_THRESHOLD:
            await self._send_embed(channel, content)
        else:
            # Split if exceeds Discord limit
            await self._send_chunked(channel, content)

    async def start(self) -> None:
        """Start the Discord bot (blocking — run in background task)."""
        if not self._token:
            logger.warning("⚠️ No Discord token — bot will not start")
            return

        logger.info("🚀 Starting Discord bot...")
        await self._bot.start(self._token)

    async def stop(self) -> None:
        """Gracefully disconnect the bot."""
        if self._bot and not self._bot.is_closed():
            await self._bot.close()
            logger.info("🔌 Discord bot disconnected")

    # ================================================================
    # Helper Methods
    # ================================================================

    def _should_respond(self, message: nextcord.Message) -> bool:
        """Determine if bot should respond to this message."""
        # Always respond in DMs
        if isinstance(message.channel, nextcord.DMChannel):
            return True

        # Respond if mentioned
        if self._bot.user in message.mentions:
            return True

        # Respond in designated channels
        channel_name = getattr(message.channel, "name", "")
        designated_channels = ("aura-admin", "aura-chat", "aura")
        if channel_name in designated_channels:
            return True

        return False

    def _clean_content(self, message: nextcord.Message) -> str:
        """Remove bot mention from message content."""
        content = message.content
        if self._bot.user:
            # Remove <@BOT_ID> or <@!BOT_ID> mentions
            content = content.replace(f"<@{self._bot.user.id}>", "").strip()
            content = content.replace(f"<@!{self._bot.user.id}>", "").strip()
        return content

    async def _send_embed(self, channel: Any, content: str) -> None:
        """Send content as a Discord embed (for long messages)."""
        # Truncate if embed description exceeds 4096
        if len(content) > 4096:
            content = content[:4090] + "\n..."

        embed = nextcord.Embed(
            description=content,
            color=0x7289DA,  # Discord blurple
        )
        embed.set_footer(text="AuraFactory")
        await channel.send(embed=embed)

    async def _send_chunked(self, channel: Any, content: str) -> None:
        """Split and send content in chunks if needed."""
        if len(content) <= MAX_DISCORD_LENGTH:
            await channel.send(content)
            return

        # Split by newlines, respecting max length
        chunks = []
        current = ""
        for line in content.split("\n"):
            if len(current) + len(line) + 1 > MAX_DISCORD_LENGTH:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)

        for chunk in chunks:
            await channel.send(chunk)
            await asyncio.sleep(0.5)  # Rate limit courtesy
