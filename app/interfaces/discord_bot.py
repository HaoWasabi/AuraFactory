"""Discord Bot Interface — I/O layer only, delegates all logic to services."""
import logging
import nextcord
from nextcord.ext import commands

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

    async def on_ready(self):
        logger.info("🤖 AuraFactory bot ready: %s (ID: %d)", self.user.name, self.user.id)
        # Set MCP bot reference
        if self.mcp_discord_server:
            self.mcp_discord_server.set_bot(self)

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
            await message.reply(f"⏳ {req_result['reason']}")
            return

        request_id = req_result["request_id"]

        # Step 2: Classify intent
        classification = await self.classifier_service.classify(content)
        intent = classification["intent"]
        tool_mode = classification["tool_mode"]

        await self.request_service.update_status(request_id, "classified", intent=intent, tool_mode=tool_mode)

        # Step 3: Route by intent
        if intent == "query":
            answer = await self.query_service.answer(content, guild_id)
            await message.reply(answer)
            await self.request_service.update_status(request_id, "completed", response=answer)
            return

        if intent in ("clarify", "out_of_scope"):
            if intent == "clarify":
                reply = "🤔 Bạn có thể mô tả cụ thể hơn được không? Ví dụ: tạo những channel gì, cho ai, trong category nào?"
            else:
                reply = "❌ Yêu cầu này nằm ngoài phạm vi AuraFactory. Tôi chỉ hỗ trợ quản lý Discord server (channels, roles, permissions, moderation)."
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
            await message.reply(f"❌ Không tạo được kế hoạch: {plan_result.get('error', 'Unknown error')}")
            await self.request_service.update_status(request_id, "failed", error_message=plan_result.get("error"))
            return

        plan_id = plan_result["plan_id"]

        # Step 5: Show plan to user
        plan_text = self._format_plan(plan_result)

        if plan_result["risk_level"] in ("HIGH", "CRITICAL"):
            # Need approval — send with buttons
            view = ApprovalView(self, plan_id, user_id)
            await message.reply(f"📋 **Kế hoạch** (risk: {plan_result['risk_level']})\n{plan_text}\n\n⚠️ Cần bạn duyệt trước khi thực thi:", view=view)
        else:
            # Auto-approved — execute immediately
            await message.reply(f"📋 **Kế hoạch** (auto-approved)\n{plan_text}\n\n⏳ Đang thực thi...")
            exec_result = await self.executor_service.execute_plan(plan_id)
            summary = self._format_execution_result(exec_result)
            await message.reply(summary)
            await self.request_service.update_status(request_id, "completed", response=summary)

    def _format_plan(self, plan: dict) -> str:
        """Format plan steps for Discord display."""
        lines = [f"> {plan.get('description', '')}"]
        for i, step in enumerate(plan.get("steps", []), 1):
            risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(step.get("risk_level", "MEDIUM"), "⚪")
            lines.append(f"{risk_emoji} Step {i}: {step.get('description', step.get('tool_name', ''))}")
        return "\n".join(lines)

    def _format_execution_result(self, result: dict) -> str:
        """Format execution results for Discord."""
        if result.get("status") == "completed":
            return f"✅ **Hoàn thành!** {result.get('completed_steps', 0)}/{result.get('total_steps', 0)} bước thành công."
        else:
            failed_step = result.get("failed_step")
            error_msg = result.get("error", "Unknown error")
            if failed_step:
                return f"⚠️ **Thực thi dừng** tại bước {failed_step}/{result.get('total_steps', '?')}: {error_msg}"
            return f"⚠️ **Lỗi:** {error_msg} ({result.get('completed_steps', 0)}/{result.get('total_steps', 0)} bước hoàn thành)"


class ApprovalView(nextcord.ui.View):
    """Discord UI buttons for plan approval (§5.5 HITL)."""

    def __init__(self, bot: DiscordBot, plan_id: str, user_id: int):
        super().__init__(timeout=1800)  # 30 min timeout (matches plan expiry)
        self.bot = bot
        self.plan_id = plan_id
        self.user_id = user_id

    @nextcord.ui.button(label="✅ Duyệt", style=nextcord.ButtonStyle.green)
    async def approve_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Chỉ người tạo yêu cầu mới được duyệt.", ephemeral=True)
            return

        result = await self.bot.approval_service.approve_plan(self.plan_id, interaction.user.id)
        if not result["ok"]:
            await interaction.response.send_message(f"❌ {result.get('reason', 'Error')}", ephemeral=True)
            return

        await interaction.response.send_message("✅ Đã duyệt! Đang thực thi...")
        self.stop()

        # Execute plan
        exec_result = await self.bot.executor_service.execute_plan(self.plan_id)
        summary = self.bot._format_execution_result(exec_result)
        await interaction.followup.send(summary)

    @nextcord.ui.button(label="❌ Từ chối", style=nextcord.ButtonStyle.red)
    async def reject_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Chỉ người tạo yêu cầu mới được từ chối.", ephemeral=True)
            return

        result = await self.bot.approval_service.reject_plan(self.plan_id, interaction.user.id, "User rejected via Discord")
        if result["ok"]:
            await interaction.response.send_message("❎ Đã từ chối. Kế hoạch đã bị hủy.")
        else:
            await interaction.response.send_message(f"❌ {result.get('reason', 'Error')}", ephemeral=True)
        self.stop()
