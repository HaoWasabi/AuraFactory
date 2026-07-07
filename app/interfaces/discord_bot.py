"""Discord Bot Interface — I/O layer only, delegates all logic to services."""
import logging
import nextcord
from nextcord.ext import commands

from app.messages import msg

logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    """AuraFactory Discord Bot.
    
    Handles:
    - on_ready: log + sync
    - on_guild_join / on_guild_remove: register/unregister bot_installs
    - on_message: route user messages to the pipeline
    - Approval buttons (approve/reject via Discord Interaction)
    """

    def __init__(self, services: dict, mcp_discord_server=None, **kwargs):
        intents = nextcord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, **kwargs)

        # Inject services
        self.request_service = services["request_service"]
        self.classifier_service = services["classifier_service"]
        self.planner_service = services["planner_service"]
        self.approval_service = services["approval_service"]
        self.executor_service = services["executor_service"]
        self.query_service = services["query_service"]
        self.guild_sync_service = services["guild_sync_service"]
        self.mcp_discord_server = mcp_discord_server
        self._mcp_client = services.get("_mcp_client")

    async def on_ready(self):
        logger.info("🤖 AuraFactory bot ready: %s (ID: %d)", self.user.name, self.user.id)
        # Set MCP bot reference
        if self.mcp_discord_server:
            self.mcp_discord_server.set_bot(self)
            # Re-index tools now that the connector has registered them
            if self._mcp_client:
                self._mcp_client.reindex()
                logger.info("✅ MCP tools re-indexed after bot ready (%d tools)", len(self._mcp_client._tool_index))

    async def on_guild_join(self, guild: nextcord.Guild):
        """Bot was added to a guild."""
        owner_id = guild.owner_id or 0
        await self.guild_sync_service.register_bot_install(guild.id, owner_id)
        logger.info("Joined guild: %s (%d)", guild.name, guild.id)

    async def on_guild_remove(self, guild: nextcord.Guild):
        """Bot was removed from a guild."""
        await self.guild_sync_service.unregister_bot_install(guild.id)
        logger.info("Removed from guild: %s (%d)", guild.name, guild.id)

    async def on_message(self, message: nextcord.Message):
        """Main message handler — entry point for user commands."""
        # Ignore self messages and non-guild messages
        if message.author.bot or not message.guild:
            return
        # Only respond to mentions or DMs with bot
        if not (self.user.mentioned_in(message) or isinstance(message.channel, nextcord.DMChannel)):
            return

        # Clean message content (remove mention)
        content = message.content.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "").strip()
        if not content:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        # Show typing indicator
        async with message.channel.typing():
            await self._process_message(message, content, guild_id, user_id)

    async def _process_message(self, message: nextcord.Message, content: str, guild_id: int, user_id: int):
        """Full pipeline: request → classify → plan/query → execute."""
        # Step 1: Create request (with lock check)
        req_result = await self.request_service.create_request(
            guild_id=guild_id,
            user_id=user_id,
            message=content,
            origin="discord",
            origin_channel_id=message.channel.id,
        )
        if not req_result["ok"]:
            await message.reply(msg("request_locked", lang="vi"))
            return

        request_id = req_result["request_id"]

        # Step 2: Classify intent + detect language
        classification = await self.classifier_service.classify(content)
        intent = classification["intent"]
        tool_mode = classification["tool_mode"]
        lang = classification.get("lang", "vi")

        await self.request_service.update_status(request_id, "classified", intent=intent, tool_mode=tool_mode)

        # Step 3: Route by intent
        if intent == "query":
            answer = await self.query_service.answer(content, guild_id)
            await message.reply(answer)
            await self.request_service.update_status(request_id, "completed", response=answer)
            return

        if intent in ("clarify", "out_of_scope"):
            reply = msg(intent, lang=lang)
            await message.reply(reply)
            await self.request_service.update_status(request_id, "completed", response=reply)
            return

        # Step 4: Generate plan (action intents)
        plan_result = await self.planner_service.generate_plan(
            request_id=request_id,
            guild_id=guild_id,
            user_id=user_id,
            message=content,
            intent=intent,
        )
        if not plan_result.get("ok"):
            await message.reply(msg("plan_failed", lang=lang, error=plan_result.get("error", "Unknown error")))
            await self.request_service.update_status(request_id, "failed", error_message=plan_result.get("error"))
            return

        plan_id = plan_result["plan_id"]

        # Step 5: Show plan to user
        plan_text = self._format_plan(plan_result)

        if plan_result["risk_level"] in ("HIGH", "CRITICAL"):
            # Need approval — send with buttons
            view = ApprovalView(self, plan_id, user_id, lang=lang)
            await message.reply(
                msg("plan_header_approval", lang=lang, risk=plan_result["risk_level"], plan_text=plan_text),
                view=view,
            )
        else:
            # Auto-approved — execute immediately
            await message.reply(msg("plan_header_auto", lang=lang, plan_text=plan_text))
            exec_result = await self.executor_service.execute_plan(plan_id)
            summary = self._format_execution_result(exec_result, lang=lang)
            await message.reply(summary)
            await self.request_service.update_status(request_id, "completed", response=summary)

    def _format_plan(self, plan: dict) -> str:
        """Format plan steps for Discord display."""
        lines = [f"> {plan.get('description', '')}"]
        for i, step in enumerate(plan.get("steps", []), 1):
            risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(step.get("risk_level", "MEDIUM"), "⚪")
            lines.append(f"{risk_emoji} Step {i}: {step.get('description', step.get('tool_name', ''))}")
        return "\n".join(lines)

    def _format_execution_result(self, result: dict, lang: str = "vi") -> str:
        """Format execution results for Discord."""
        if result.get("status") == "completed":
            return msg("exec_completed", lang=lang, done=result.get("completed_steps", 0), total=result.get("total_steps", 0))
        else:
            failed_step = result.get("failed_step")
            error_msg = result.get("error", "Unknown error")
            if failed_step:
                return msg("exec_partial", lang=lang, failed=failed_step, total=result.get("total_steps", "?"), error=error_msg)
            return msg("exec_error", lang=lang, error=error_msg, done=result.get("completed_steps", 0), total=result.get("total_steps", 0))


class ApprovalView(nextcord.ui.View):
    """Discord UI buttons for plan approval (§5.5 HITL)."""

    def __init__(self, bot: DiscordBot, plan_id: str, user_id: int, lang: str = "vi"):
        super().__init__(timeout=1800)  # 30 min timeout (matches plan expiry)
        self.bot = bot
        self.plan_id = plan_id
        self.user_id = user_id
        self.lang = lang

    @nextcord.ui.button(label="✅ Approve", style=nextcord.ButtonStyle.green)
    async def approve_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(msg("only_creator_approve", lang=self.lang), ephemeral=True)
            return

        # Defer immediately to avoid 3s Discord interaction timeout
        await interaction.response.defer()

        try:
            result = await self.bot.approval_service.approve_plan(self.plan_id, interaction.user.id)
            if not result["ok"]:
                await interaction.followup.send(f"❌ {result.get('error', 'Error')}", ephemeral=True)
                return

            self.stop()
            await interaction.followup.send(msg("approved", lang=self.lang))

            # Execute plan
            exec_result = await self.bot.executor_service.execute_plan(self.plan_id)
            summary = self.bot._format_execution_result(exec_result, lang=self.lang)
            await interaction.followup.send(summary)
        except Exception as e:
            logger.exception("Approve button error: %s", e)
            await interaction.followup.send(f"❌ Error: {str(e)[:200]}", ephemeral=True)

    @nextcord.ui.button(label="❌ Reject", style=nextcord.ButtonStyle.red)
    async def reject_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(msg("only_creator_reject", lang=self.lang), ephemeral=True)
            return

        await interaction.response.defer()

        try:
            result = await self.bot.approval_service.reject_plan(self.plan_id, interaction.user.id, "User rejected via Discord")
            if result["ok"]:
                await interaction.followup.send(msg("rejected", lang=self.lang))
            else:
                await interaction.followup.send(f"❌ {result.get('error', 'Error')}", ephemeral=True)
            self.stop()
        except Exception as e:
            logger.exception("Reject button error: %s", e)
            await interaction.followup.send(f"❌ Error: {str(e)[:200]}", ephemeral=True)
