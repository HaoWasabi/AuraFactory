"""Discord Bot Interface — uses UnifiedAgent for all message processing.
Includes Discord UI buttons for approval flows (ApprovalView).
"""
import asyncio
import logging
from typing import Set

import nextcord
from nextcord.ext import commands

from app.config import settings
from app.messages import msg

logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    """AuraFactory Discord Bot.
    
    Handles:
    - on_ready: log + sync + register MCP tools
    - on_guild_join / on_guild_remove: register/unregister bot_installs
    - on_message: route user messages to UnifiedAgent
    - Approval flow: detect replies to bot's confirmation messages
    """

    def __init__(self, services: dict, mcp_discord_server=None, **kwargs):
        intents = nextcord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, **kwargs)

        # Core services
        self.unified_agent = services["unified_agent"]
        self.guild_sync_service = services["guild_sync_service"]
        self.mcp_discord_server = mcp_discord_server
        self._mcp_client = services.get("_mcp_client")
        self._db = services.get("_db")

        # Set of Discord user IDs that own this bot application (populated in on_ready)
        self._bot_owner_ids: Set[int] = set()
        # Flag: tools registered and ready
        self._tools_ready = False
        # Track confirmation message IDs → guild_id for reply detection
        self._confirm_message_ids: dict[int, int] = {}  # msg_id → guild_id

    async def on_ready(self):
        logger.info("🤖 AuraFactory bot ready: %s (ID: %d)", self.user.name, self.user.id)

        # Resolve bot application owner(s) — used for admin-only commands
        try:
            app_info = await self.application_info()
            if app_info.team:
                self._bot_owner_ids = {m.id for m in app_info.team.members}
            else:
                self._bot_owner_ids = {app_info.owner.id}
            logger.info("✅ Bot owner IDs resolved: %s", self._bot_owner_ids)
        except Exception as e:
            logger.warning("⚠️ Could not resolve bot owner IDs: %s", e)

        # Register all current guilds in bot_installs (in case DB was wiped)
        for guild in self.guilds:
            await self.guild_sync_service.register_bot_install(guild.id, guild.owner_id or 0)
        logger.info("✅ Registered %d guild(s) in bot_installs", len(self.guilds))

        # Set MCP bot reference → register all tools
        if self.mcp_discord_server:
            self.mcp_discord_server.set_bot(self)
            if self._mcp_client:
                self._mcp_client.reindex()
                tool_count = len(self._mcp_client._tool_index)
                logger.info("✅ MCP tools re-indexed after bot ready (%d tools)", tool_count)

        self._tools_ready = True

    # —— Admin: update Gemini API key ————————————————————————————————————————

    @nextcord.slash_command(
        name="setgeminikey",
        description="[Bot Admin] Update Gemini API key for the system",
    )
    async def set_gemini_key(
        self,
        interaction: nextcord.Interaction,
        api_key: str = nextcord.SlashOption(
            name="api_key",
            description="New Gemini API key (starts with AIza...)",
            required=True,
        ),
    ):
        """Slash command to update the Gemini API key at runtime."""
        await interaction.response.defer(ephemeral=True)

        if interaction.user.id not in self._bot_owner_ids:
            await interaction.followup.send(
                "❌ Permission denied. Only the bot application owner can use this command.",
                ephemeral=True,
            )
            return

        new_key = api_key.strip()
        if not new_key or not new_key.startswith("AIza"):
            await interaction.followup.send(
                "❌ Invalid API key. Gemini key must start with `AIza`.",
                ephemeral=True,
            )
            return

        # Update config singleton
        settings.GEMINI_API_KEY = new_key

        # Update live LLM instance in unified_agent
        if self.unified_agent and hasattr(self.unified_agent, "_llm"):
            llm = self.unified_agent._llm
            if hasattr(llm, "update_api_key"):
                llm.update_api_key(new_key)

        logger.info(
            "Gemini API key updated via slash command by user %d (%s)",
            interaction.user.id,
            interaction.user.name,
        )

        masked = f"{new_key[:8]}...{new_key[-4:]}" if len(new_key) > 12 else "***"
        await interaction.followup.send(
            f"✅ Gemini API key updated successfully!\n🔑 New key: `{masked}`",
            ephemeral=True,
        )

    # —— Guild events ————————————————————————————————————————————————————————

    async def on_guild_join(self, guild: nextcord.Guild):
        """Bot was added to a guild."""
        owner_id = guild.owner_id or 0
        await self.guild_sync_service.register_bot_install(guild.id, owner_id)
        logger.info("Joined guild: %s (%d)", guild.name, guild.id)

    async def on_guild_remove(self, guild: nextcord.Guild):
        """Bot was removed from a guild."""
        await self.guild_sync_service.unregister_bot_install(guild.id)
        logger.info("Removed from guild: %s (%d)", guild.name, guild.id)

    # —— Message handling ————————————————————————————————————————————————————

    async def on_message(self, message: nextcord.Message):
        """Main message handler — entry point for user commands.

        Triggers on:
        1. Bot is @mentioned → normal command flow
        2. Message is a reply to bot's confirmation prompt → approval flow
        """
        # Ignore self messages and non-guild messages
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        user_id = message.author.id
        content = ""

        # Check if this is a reply to a bot confirmation message
        is_confirmation_reply = False
        if message.reference and message.reference.message_id:
            ref_id = message.reference.message_id
            if ref_id in self._confirm_message_ids:
                is_confirmation_reply = True
                content = message.content.strip()

        # Normal flow: bot must be mentioned
        if not is_confirmation_reply:
            if not self.user.mentioned_in(message):
                return
            # Clean message content (remove mention)
            content = message.content.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "").strip()

        if not content:
            return

        # Show typing indicator
        async with message.channel.typing():
            await self._process_message(message, content, guild_id, user_id)

    async def _process_message(self, message: nextcord.Message, content: str, guild_id: int, user_id: int):
        """Process message via UnifiedAgent."""
        # Guard: bot not ready yet
        if not self._tools_ready:
            await message.reply("⏳ Bot is starting up, please try again in a few seconds...")
            return

        # Guard: unified agent not available (LLM init failed)
        if not self.unified_agent:
            await message.reply("⚠️ AI is not ready. Please check LLM configuration.")
            return

        try:
            result = await self.unified_agent.process(
                message=content,
                guild_id=guild_id,
                user_id=user_id,
            )

            response_text = result.get("content", "")
            if not response_text:
                if result.get("type") == "action":
                    response_text = "✅ Done."
                elif result.get("type") == "confirm_needed":
                    response_text = "❓ Confirmation needed (reply with yes/no)."
                else:
                    response_text = "No response."

            # Discord message limit: 2000 chars
            if len(response_text) > 1900:
                response_text = response_text[:1900] + "\n... *(truncated)*"

            # If confirmation needed, use Discord UI buttons instead of text reply
            if result.get("type") == "confirm_needed":
                view = ApprovalView(self, guild_id, user_id)
                await message.reply(response_text, view=view)
            else:
                await message.reply(response_text)

        except Exception as e:
            logger.exception("Error processing message from user %d in guild %d: %s", user_id, guild_id, e)
            await message.reply("⚠️ An error occurred while processing your request. Please try again.")

    async def _cleanup_confirm_id(self, msg_id: int, delay: float = 300):
        """Remove tracked confirmation message after timeout."""
        await asyncio.sleep(delay)
        self._confirm_message_ids.pop(msg_id, None)


# ═══════════════════════════════════════════════════════════════════════════════
# Discord UI Views (Buttons)
# ═══════════════════════════════════════════════════════════════════════════════

class ApprovalView(nextcord.ui.View):
    """Discord UI buttons for high-risk action approval.

    Shows Approve/Reject buttons. On approve, sends "yes" back to UnifiedAgent
    which processes it via the confirmation handler flow.
    """

    def __init__(self, bot: DiscordBot, guild_id: int, user_id: int, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id

    async def on_timeout(self) -> None:
        """Disable all buttons when view times out."""
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if hasattr(self, "message") and self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    @nextcord.ui.button(label="✅ Approve", style=nextcord.ButtonStyle.green)
    async def approve_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the requestor can approve.", ephemeral=True)
            return

        await interaction.response.defer()
        self.stop()

        # Send "yes" to UnifiedAgent — triggers confirmation handler
        try:
            result = await self.bot.unified_agent.process(
                message="yes",
                guild_id=self.guild_id,
                user_id=self.user_id,
            )
            response_text = result.get("content", "✅ Done.")
            if len(response_text) > 1900:
                response_text = response_text[:1900] + "\n... *(truncated)*"
            await interaction.followup.send(response_text)
        except Exception as e:
            logger.exception("Approval execution error: %s", e)
            await interaction.followup.send(f"⚠️ Error: {str(e)[:200]}", ephemeral=True)

    @nextcord.ui.button(label="❌ Cancel", style=nextcord.ButtonStyle.red)
    async def reject_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the requestor can cancel.", ephemeral=True)
            return

        await interaction.response.defer()
        self.stop()

        # Send "no" to UnifiedAgent — triggers cancellation
        result = await self.bot.unified_agent.process(
            message="no",
            guild_id=self.guild_id,
            user_id=self.user_id,
        )
        await interaction.followup.send(result.get("content", "✋ Cancelled."))
