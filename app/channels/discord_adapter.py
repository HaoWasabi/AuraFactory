# app/channels/discord_adapter.py
"""
Discord Channel Adapter — bridges nextcord bot events to the unified pipeline.

Events handled:
- on_message: User mentions bot → route to orchestrator
- on_guild_join: Bot added to server → trigger setup mode
- on_member_join: New member joins → trigger onboarding DM
- on_guild_channel_*/on_guild_role_*: Server changes → update knowledge
"""
import logging
from typing import Callable, Awaitable, Optional

import nextcord

from app.channels.base import ChannelAdapterBase
from app.models.messages import IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)


class DiscordAdapter(ChannelAdapterBase):
    """
    Discord bot adapter using nextcord.
    Listens for messages + guild/member events, converts to IncomingMessage,
    sends OutgoingMessage back.
    """

    def __init__(self, token: str, allowed_guild_ids: list = None, allow_all: bool = False):
        self._token = token
        self._allowed_guild_ids = allowed_guild_ids or []
        self._allow_all = allow_all
        self._handler: Optional[Callable[[IncomingMessage], Awaitable[OutgoingMessage]]] = None

        # Create bot with intents
        intents = nextcord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        self._bot = nextcord.Client(intents=intents)

        # Lifecycle event callbacks (set externally during DI setup)
        self._on_guild_join_handler: Optional[Callable] = None
        self._on_member_join_handler: Optional[Callable] = None
        self._on_server_change_handler: Optional[Callable] = None

        # Register event handlers
        self._setup_message_events()
        self._setup_lifecycle_events()

    @property
    def name(self) -> str:
        return "discord"

    @property
    def bot(self) -> nextcord.Client:
        """Direct access to the nextcord client (for tools that need guild object)."""
        return self._bot

    # --- Lifecycle handler setters ---

    def set_guild_join_handler(self, handler: Callable) -> None:
        """Set callback for when bot joins a new server."""
        self._on_guild_join_handler = handler

    def set_member_join_handler(self, handler: Callable) -> None:
        """Set callback for when a new member joins a server."""
        self._on_member_join_handler = handler

    def set_server_change_handler(self, handler: Callable) -> None:
        """Set callback for when server structure changes (channels, roles)."""
        self._on_server_change_handler = handler

    # --- Core methods ---

    async def start(self) -> None:
        """Start the Discord bot (non-blocking)."""
        if self._token:
            await self._bot.start(self._token)
        else:
            logger.warning("No DISCORD_TOKEN — Discord adapter not started")

    async def stop(self) -> None:
        """Stop the Discord bot."""
        if self._bot.is_ready():
            await self._bot.close()

    async def send(self, message: OutgoingMessage) -> None:
        """Send a response back to Discord."""
        if not message.target_channel_id:
            logger.warning("OutgoingMessage has no target_channel_id")
            return

        channel = self._bot.get_channel(message.target_channel_id)
        if not channel:
            logger.warning(f"Channel not found: {message.target_channel_id}")
            return

        # Send message (handle length limits)
        content = message.content
        if len(content) > 2000:
            # Split into chunks
            chunks = [content[i:i + 1990] for i in range(0, len(content), 1990)]
            for chunk in chunks:
                await channel.send(chunk)
        else:
            kwargs = {"content": content}
            if message.embed:
                kwargs["embed"] = nextcord.Embed.from_dict(message.embed)
            if message.components:
                # Discord buttons/select menus via nextcord.ui.View
                pass  # TODO: implement component rendering
            if message.reply_to:
                try:
                    ref_msg = await channel.fetch_message(int(message.reply_to))
                    kwargs["reference"] = ref_msg
                except Exception:
                    pass
            await channel.send(**kwargs)

    async def send_dm(self, user_id: int, content: str, embed: dict = None) -> bool:
        """Send a direct message to a user. Returns True if successful."""
        try:
            user = await self._bot.fetch_user(user_id)
            kwargs = {"content": content}
            if embed:
                kwargs["embed"] = nextcord.Embed.from_dict(embed)
            await user.send(**kwargs)
            return True
        except (nextcord.Forbidden, nextcord.HTTPException) as e:
            logger.warning(f"Cannot DM user {user_id}: {e}")
            return False

    # --- Event handlers ---

    def _setup_message_events(self) -> None:
        """Register message event handler."""

        @self._bot.event
        async def on_ready():
            logger.info(f"Discord bot connected as {self._bot.user}")
            logger.info(f"Connected to {len(self._bot.guilds)} guild(s)")

        @self._bot.event
        async def on_message(msg: nextcord.Message):
            # Ignore self
            if msg.author == self._bot.user:
                return
            # Ignore bots
            if msg.author.bot:
                return
            # Must mention the bot or be in DM
            is_dm = msg.guild is None
            if msg.guild and self._bot.user not in msg.mentions:
                return
            # Guild filter
            if msg.guild and not self._is_allowed_guild(msg.guild.id):
                return

            # Build IncomingMessage
            incoming = IncomingMessage(
                user_id=str(msg.author.id),
                user_name=msg.author.display_name,
                prompt=msg.content.replace(f"<@{self._bot.user.id}>", "").strip(),
                guild_id=msg.guild.id if msg.guild else None,
                channel_id=msg.channel.id,
                message_id=str(msg.id),
                source="discord",
                attachments=[a.url for a in msg.attachments],
            )

            # Attach role info (only available in guild context)
            if msg.guild and isinstance(msg.author, nextcord.Member):
                incoming.user_roles = [
                    role.name for role in msg.author.roles
                    if role.name != "@everyone"
                ]
                incoming.is_admin = (
                    msg.author.guild_permissions.administrator
                    or msg.author.guild_permissions.manage_guild
                )

            # Store channel name in metadata for source_context detection
            incoming.metadata["channel_name"] = getattr(msg.channel, "name", "DM")
            incoming.metadata["is_dm"] = is_dm

            # Call handler
            if self._handler:
                try:
                    response = await self._handler(incoming)
                    if response:
                        response.target_channel_id = msg.channel.id
                        response.reply_to = str(msg.id)
                        await self.send(response)
                except Exception as e:
                    logger.error(f"Handler error: {e}")
                    await msg.channel.send(f"❌ Đã xảy ra lỗi: {str(e)[:200]}")

    def _setup_lifecycle_events(self) -> None:
        """Register guild/member lifecycle event handlers."""

        @self._bot.event
        async def on_guild_join(guild: nextcord.Guild):
            """Bot was added to a new server → trigger setup mode."""
            logger.info(f"Bot joined new guild: {guild.name} ({guild.id})")
            if self._on_guild_join_handler:
                try:
                    await self._on_guild_join_handler(guild)
                except Exception as e:
                    logger.error(f"Guild join handler error: {e}")

        @self._bot.event
        async def on_member_join(member: nextcord.Member):
            """New member joined a server → trigger onboarding DM."""
            if member.bot:
                return  # Ignore bot joins
            logger.info(f"New member joined {member.guild.name}: {member.display_name}")
            if self._on_member_join_handler:
                try:
                    await self._on_member_join_handler(member)
                except Exception as e:
                    logger.error(f"Member join handler error: {e}")

        @self._bot.event
        async def on_guild_channel_create(channel):
            """Channel created → update knowledge."""
            await self._handle_server_change(channel.guild, "channel_create")

        @self._bot.event
        async def on_guild_channel_delete(channel):
            """Channel deleted → update knowledge."""
            await self._handle_server_change(channel.guild, "channel_delete")

        @self._bot.event
        async def on_guild_channel_update(before, after):
            """Channel updated → update knowledge."""
            await self._handle_server_change(after.guild, "channel_update")

        @self._bot.event
        async def on_guild_role_create(role):
            """Role created → update knowledge."""
            await self._handle_server_change(role.guild, "role_create")

        @self._bot.event
        async def on_guild_role_delete(role):
            """Role deleted → update knowledge."""
            await self._handle_server_change(role.guild, "role_delete")

        @self._bot.event
        async def on_guild_role_update(before, after):
            """Role updated → update knowledge."""
            await self._handle_server_change(after.guild, "role_update")

    # --- Helpers ---

    async def _handle_server_change(self, guild: nextcord.Guild, event_type: str) -> None:
        """Notify handler about server structure change."""
        if self._on_server_change_handler:
            try:
                await self._on_server_change_handler(guild, event_type)
            except Exception as e:
                logger.error(f"Server change handler error ({event_type}): {e}")

    def _is_allowed_guild(self, guild_id: int) -> bool:
        """Check if guild is allowed."""
        if self._allow_all:
            return True
        if not self._allowed_guild_ids:
            return True  # No restriction
        return guild_id in self._allowed_guild_ids
