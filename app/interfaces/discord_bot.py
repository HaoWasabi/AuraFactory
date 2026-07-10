"""Discord Bot Interface — I/O layer only, delegates all logic to services."""
import asyncio
import logging
from typing import Optional, Set

import nextcord
from nextcord.ext import commands

from app.config import settings
from app.llm.base import LLMQuotaError
from app.messages import msg, msg_for_quota_error

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
        self.session_service = services.get("session_service")
        self.mcp_discord_server = mcp_discord_server
        self._mcp_client = services.get("_mcp_client")
        # DB reference for token tracking
        self._db = getattr(services.get("approval_service"), "db", None)
        # Set of Discord user IDs that own this bot application (populated in on_ready)
        self._bot_owner_ids: Set[int] = set()

    async def on_ready(self):
        logger.info("🤖 AuraFactory bot ready: %s (ID: %d)", self.user.name, self.user.id)

        # Resolve bot application owner(s) — used for admin-only commands
        try:
            app_info = await self.application_info()
            if app_info.team:
                # Team app — all team members are considered owners
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

        # Set MCP bot reference
        if self.mcp_discord_server:
            self.mcp_discord_server.set_bot(self)
            # Re-index tools now that the connector has registered them
            if self._mcp_client:
                self._mcp_client.reindex()
                logger.info("✅ MCP tools re-indexed after bot ready (%d tools)", len(self._mcp_client._tool_index))

    # ── Admin: update Gemini API key ──────────────────────────────────────────

    @nextcord.slash_command(
        name="setgeminikey",
        description="[Bot Admin] Cập nhật Gemini API key cho toàn hệ thống",
    )
    async def set_gemini_key(
        self,
        interaction: nextcord.Interaction,
        api_key: str = nextcord.SlashOption(
            name="api_key",
            description="Gemini API key mới (bắt đầu bằng AIza...)",
            required=True,
        ),
    ):
        """Slash command to update the Gemini API key at runtime.
        
        Only usable by Discord users listed in BOT_ADMIN_IDS env variable.
        Responds ephemerally so the key is never visible in channel history.
        """
        # Always defer as ephemeral — key must never appear in channel
        await interaction.response.defer(ephemeral=True)

        # Authorization: only the Discord application owner(s) may use this command
        if interaction.user.id not in self._bot_owner_ids:
            await interaction.followup.send(
                "❌ Không có quyền. Chỉ owner của bot application mới được sử dụng lệnh này.",
                ephemeral=True,
            )
            return

        new_key = api_key.strip()
        if not new_key:
            await interaction.followup.send("❌ API key không được để trống.", ephemeral=True)
            return

        # Update config singleton
        settings.GEMINI_API_KEY = new_key

        # Update all live LLM instances via update_api_key()
        updated_services = []
        for attr in (
            "classifier_service",
            "planner_service",
            "executor_service",
            "query_service",
        ):
            svc = getattr(self, attr, None)
            if svc is None:
                continue
            llm = getattr(svc, "llm", None)
            if llm is not None and hasattr(llm, "update_api_key"):
                llm.update_api_key(new_key)
                updated_services.append(attr)

        logger.info(
            "Gemini API key updated via Discord slash command by user %d (%s) — services: %s",
            interaction.user.id,
            interaction.user.name,
            updated_services,
        )

        masked = f"{new_key[:8]}...{new_key[-4:]}" if len(new_key) > 12 else "***"
        await interaction.followup.send(
            f"✅ Gemini API key đã được cập nhật thành công!\n"
            f"🔑 Key mới: `{masked}`\n"
            f"📦 Services đã cập nhật: {', '.join(updated_services) or 'không có'}",
            ephemeral=True,
        )

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

        guild_id = message.guild.id
        user_id = message.author.id

        # ── Case 1: Message is inside a thread that belongs to this bot ──
        if isinstance(message.channel, nextcord.Thread):
            # Only respond if this thread was created by the bot
            if message.channel.owner_id == self.user.id:
                content = message.content.strip()
                if not content:
                    return
                async with message.channel.typing():
                    await self._process_message(
                        message=message,
                        content=content,
                        guild_id=guild_id,
                        user_id=user_id,
                        reply_channel=message.channel,  # continue in thread
                        is_thread_continuation=True,
                    )
            return

        # ── Case 2: Regular channel — only respond to @mentions ──
        if not self.user.mentioned_in(message):
            return

        # Clean message content (remove mention)
        content = message.content.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "").strip()
        if not content:
            return

        # Show typing indicator while creating thread
        async with message.channel.typing():
            await self._process_message(
                message=message,
                content=content,
                guild_id=guild_id,
                user_id=user_id,
                reply_channel=None,  # will create a thread
                is_thread_continuation=False,
            )

    async def _create_reply_thread(
        self,
        message: nextcord.Message,
        thread_name: str,
    ) -> Optional[nextcord.Thread]:
        """Create a public thread on the original message as the reply channel."""
        try:
            # Truncate thread name to Discord's 100-char limit
            name = thread_name[:100]
            thread = await message.create_thread(name=name, auto_archive_duration=60)
            return thread
        except nextcord.Forbidden:
            logger.warning("No permission to create thread in channel %d", message.channel.id)
            return None
        except Exception as e:
            logger.warning("Failed to create thread: %s", e)
            return None

    async def _process_message(
        self,
        message: nextcord.Message,
        content: str,
        guild_id: int,
        user_id: int,
        reply_channel: Optional[nextcord.abc.Messageable],
        is_thread_continuation: bool,
    ):
        """Full pipeline: session → request → classify → plan/query → execute."""

        # ── Step 0: Resolve or create session ──────────────────────────
        session_id: Optional[str] = None
        thread_channel = reply_channel  # may be None for new mentions

        if self.session_service:
            if is_thread_continuation and isinstance(reply_channel, nextcord.Thread):
                # Continuation: look up session by thread ID
                session_id = await self.session_service.get_or_create_session(
                    guild_id=guild_id,
                    user_id=user_id,
                    origin="discord",
                    discord_thread_id=reply_channel.id,
                    title=reply_channel.name,
                )
            else:
                # New conversation: create session first (thread ID bound later)
                thread_name = content[:60] + ("…" if len(content) > 60 else "")
                session_id = await self.session_service.create_session(
                    guild_id=guild_id,
                    user_id=user_id,
                    origin="discord",
                    title=thread_name,
                )

        # ── Step 1: Create the reply thread (new mentions only) ─────────
        if not is_thread_continuation:
            thread_name = content[:80] + ("…" if len(content) > 80 else "")
            created_thread = await self._create_reply_thread(message, thread_name)
            if created_thread:
                thread_channel = created_thread
                # Bind thread to session
                if session_id and self.session_service:
                    await self.session_service.update_thread_id(session_id, created_thread.id)
            else:
                # Fallback: reply in original channel
                thread_channel = message.channel

        # ── Step 2: Store user message in memory ────────────────────────
        if session_id and self.session_service:
            await self.session_service.add_message(
                session_id=session_id,
                guild_id=guild_id,
                user_id=user_id,
                role="user",
                content=content,
                origin="discord",
            )

        # ── Step 3: Get conversation history ────────────────────────────
        history: list = []
        if session_id and self.session_service:
            history = await self.session_service.get_history(session_id)

        # ── Step 4: Create request (with lock check) ─────────────────────
        req_result = await self.request_service.create_request(
            guild_id=guild_id,
            user_id=user_id,
            message=content,
            origin="discord",
            origin_channel_id=message.channel.id,
            session_id=session_id,
        )
        if not req_result["ok"]:
            reply_text = msg("request_locked", lang="vi")
            await thread_channel.send(reply_text)
            if session_id and self.session_service:
                await self.session_service.add_message(
                    session_id=session_id, guild_id=guild_id, user_id=user_id,
                    role="bot", content=reply_text, origin="discord",
                )
            return

        request_id = req_result["request_id"]

        # ── Step 5: Classify intent + detect language ─────────────────────
        try:
            classification = await self.classifier_service.classify(
                content, db=self._db, request_id=request_id
            )
        except LLMQuotaError as qe:
            reply_text = msg_for_quota_error(qe.reason, lang="vi")
            await thread_channel.send(reply_text)
            if session_id and self.session_service:
                await self.session_service.add_message(
                    session_id=session_id, guild_id=guild_id, user_id=user_id,
                    role="bot", content=reply_text, origin="discord",
                )
            await self.request_service.update_status(request_id, "failed", error_message=f"quota:{qe.reason}")
            return

        intent = classification["intent"]
        tool_mode = classification["tool_mode"]
        lang = classification.get("lang", "vi")

        await self.request_service.update_status(request_id, "classified", intent=intent, tool_mode=tool_mode)

        # ── Step 6: Route by intent ──────────────────────────────────────
        if intent == "query":
            try:
                answer = await self.query_service.answer(
                    content, guild_id, db=self._db, request_id=request_id, history=history
                )
            except LLMQuotaError as qe:
                answer = msg_for_quota_error(qe.reason, lang=lang)
                await self.request_service.update_status(request_id, "failed", error_message=f"quota:{qe.reason}")
            else:
                await self.request_service.update_status(request_id, "completed", response=answer)
            await thread_channel.send(answer)
            if session_id and self.session_service:
                await self.session_service.add_message(
                    session_id=session_id, guild_id=guild_id, user_id=user_id,
                    role="bot", content=answer, origin="discord",
                )
            return

        if intent in ("clarify", "out_of_scope"):
            if intent == "clarify":
                try:
                    reply = await self.classifier_service.generate_clarify(
                        content, lang=lang, db=self._db, request_id=request_id
                    )
                except LLMQuotaError as qe:
                    reply = msg_for_quota_error(qe.reason, lang=lang)
                    await self.request_service.update_status(request_id, "failed", error_message=f"quota:{qe.reason}")
                    await thread_channel.send(reply)
                    if session_id and self.session_service:
                        await self.session_service.add_message(
                            session_id=session_id, guild_id=guild_id, user_id=user_id,
                            role="bot", content=reply, origin="discord",
                        )
                    return
            else:
                reply = msg("out_of_scope", lang=lang)
            await thread_channel.send(reply)
            await self.request_service.update_status(request_id, "completed", response=reply)
            if session_id and self.session_service:
                await self.session_service.add_message(
                    session_id=session_id, guild_id=guild_id, user_id=user_id,
                    role="bot", content=reply, origin="discord",
                )
            return

        # ── Step 7: Generate plan (action intents) ───────────────────────
        try:
            plan_result = await self.planner_service.generate_plan(
                request_id=request_id,
                guild_id=guild_id,
                user_id=user_id,
                message=content,
                intent=intent,
                history=history,
            )
        except LLMQuotaError as qe:
            err_msg = msg_for_quota_error(qe.reason, lang=lang)
            await thread_channel.send(err_msg)
            await self.request_service.update_status(request_id, "failed", error_message=f"quota:{qe.reason}")
            if session_id and self.session_service:
                await self.session_service.add_message(
                    session_id=session_id, guild_id=guild_id, user_id=user_id,
                    role="bot", content=err_msg, origin="discord",
                )
            return
        if not plan_result.get("ok"):
            err_msg = msg("plan_failed", lang=lang, error=plan_result.get("error", "Unknown error"))
            await thread_channel.send(err_msg)
            await self.request_service.update_status(request_id, "failed", error_message=plan_result.get("error"))
            if session_id and self.session_service:
                await self.session_service.add_message(
                    session_id=session_id, guild_id=guild_id, user_id=user_id,
                    role="bot", content=err_msg, origin="discord",
                )
            return

        plan_id = plan_result["plan_id"]

        # ── Step 8: Show plan to user ─────────────────────────────────────
        plan_text = self._format_plan(plan_result, lang=lang)

        if plan_result["risk_level"] in ("HIGH", "CRITICAL"):
            # Need approval — send with buttons
            plan_header = msg("plan_header_approval", lang=lang, risk=plan_result["risk_level"], plan_text=plan_text)
            view = ApprovalView(self, plan_id, user_id, lang=lang)
            sent_msg = await thread_channel.send(plan_header, view=view)
            view.message = sent_msg
            if session_id and self.session_service:
                await self.session_service.add_message(
                    session_id=session_id, guild_id=guild_id, user_id=user_id,
                    role="bot", content=plan_header, origin="discord",
                )
        else:
            # Auto-approved — execute in background, reply when done
            plan_header = msg("plan_header_auto", lang=lang, plan_text=plan_text)
            await thread_channel.send(plan_header)
            if session_id and self.session_service:
                await self.session_service.add_message(
                    session_id=session_id, guild_id=guild_id, user_id=user_id,
                    role="bot", content=plan_header, origin="discord",
                )

            _session_id = session_id  # capture for closure

            async def _execute_and_reply():
                try:
                    exec_result = await self.executor_service.execute_plan(plan_id)

                    # Community upgrade needed
                    if exec_result.get("status") == "community_upgrade_needed":
                        community_payload = exec_result.get("community_payload", {})
                        ch_type = community_payload.get("channel_type", "stage")
                        ch_name = community_payload.get("channel_name", "")
                        prompt_text = msg(
                            "community_upgrade_needed",
                            lang=lang,
                            channel_type=ch_type,
                            channel_name=ch_name,
                        )
                        view = CommunityUpgradeView(
                            bot=self,
                            community_payload=community_payload,
                            user_id=user_id,
                            request_id=request_id,
                            lang=lang,
                        )
                        sent = await thread_channel.send(prompt_text, view=view)
                        view.message = sent
                        if _session_id and self.session_service:
                            await self.session_service.add_message(
                                session_id=_session_id, guild_id=guild_id, user_id=user_id,
                                role="bot", content=prompt_text, origin="discord",
                            )
                        return

                    summary = self._format_execution_result(exec_result, lang=lang)
                    await thread_channel.send(summary)
                    await self.request_service.update_status(request_id, "completed", response=summary)
                    if _session_id and self.session_service:
                        await self.session_service.add_message(
                            session_id=_session_id, guild_id=guild_id, user_id=user_id,
                            role="bot", content=summary, origin="discord",
                        )
                except Exception as e:
                    logger.error("Background execution error for plan %s: %s", plan_id, e)
                    try:
                        err_text = msg("exec_error", lang=lang, error=str(e)[:200], done=0, total="?")
                        await thread_channel.send(err_text)
                    except Exception:
                        pass

            asyncio.create_task(_execute_and_reply())

    MAX_PLAN_CHARS = 1800

    def _format_plan(self, plan: dict, lang: str = "vi") -> str:
        """Format plan steps for Discord display (max 1800 chars)."""
        lines = [f"> {plan.get('description', '')}"]
        steps = plan.get("steps", [])
        risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}

        for i, step in enumerate(steps, 1):
            emoji = risk_emoji.get(step.get("risk_level", "MEDIUM"), "⚪")
            line = f"{emoji} Step {i}: {step.get('description', step.get('tool_name', ''))}"
            remaining = len(steps) - (i - 1)
            suffix = f"... và {remaining} bước khác" if lang == "vi" else f"... and {remaining} more steps"

            candidate_with_step = "\n".join(lines + [line])

            if len(candidate_with_step) > self.MAX_PLAN_CHARS:
                # This step doesn't fit — try to append suffix to current lines
                candidate_with_suffix = "\n".join(lines + [suffix])
                if len(candidate_with_suffix) <= self.MAX_PLAN_CHARS:
                    lines.append(suffix)
                else:
                    # suffix doesn't fit with current lines — pop the last step to make room
                    while lines and len("\n".join(lines + [suffix])) > self.MAX_PLAN_CHARS:
                        lines.pop()
                    lines.append(suffix)
                break
            lines.append(line)

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

    async def on_timeout(self) -> None:
        """Disable all buttons when view times out (30 min)."""
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if hasattr(self, "message") and self.message:
            try:
                await self.message.edit(
                    content=getattr(self.message, "content", "") + "\n*(Expired — request timed out)*",
                    view=self,
                )
            except Exception as e:
                logger.warning("Failed to edit message on ApprovalView timeout: %s", e)

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


class CommunityUpgradeView(nextcord.ui.View):
    """Discord UI buttons for Community upgrade prompt.

    Shown when a plan step requires Community feature (e.g. creating a stage channel)
    but the server hasn't enabled it yet.
    """

    def __init__(
        self,
        bot: DiscordBot,
        community_payload: dict,
        user_id: int,
        request_id: str,
        lang: str = "vi",
    ):
        super().__init__(timeout=300)  # 5-minute window to respond
        self.bot = bot
        self.community_payload = community_payload
        self.user_id = user_id
        self.request_id = request_id
        self.lang = lang
        self.message = None

    async def on_timeout(self) -> None:
        """Disable buttons and cancel the paused plan on timeout."""
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content=getattr(self.message, "content", "") + "\n*(Hết thời gian — yêu cầu đã bị huỷ)*",
                    view=self,
                )
            except Exception:
                pass
        # Cancel the paused plan
        import uuid as _u
        plan_id = self.community_payload.get("plan_id")
        if plan_id:
            try:
                await self.bot.approval_service.db.execute(
                    "UPDATE plans SET status = 'cancelled' WHERE id = $1", _u.UUID(plan_id)
                )
                await self.bot.request_service.update_status(self.request_id, "cancelled")
            except Exception:
                pass

    @nextcord.ui.button(label="✅ Bật Community & Tiếp tục", style=nextcord.ButtonStyle.green)
    async def confirm_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                msg("only_creator_approve", lang=self.lang), ephemeral=True
            )
            return

        await interaction.response.defer()
        self.stop()

        try:
            await interaction.followup.send(msg("community_upgrade_confirmed", lang=self.lang))
            exec_result = await self.bot.executor_service.enable_community_and_resume(
                self.community_payload
            )
            summary = self.bot._format_execution_result(exec_result, lang=self.lang)
            await interaction.followup.send(summary)
            await self.bot.request_service.update_status(
                self.request_id,
                "completed" if exec_result.get("status") == "completed" else "failed",
                response=summary,
            )
        except Exception as e:
            logger.exception("CommunityUpgrade confirm error: %s", e)
            await interaction.followup.send(f"❌ Lỗi: {str(e)[:200]}", ephemeral=True)

    @nextcord.ui.button(label="🚫 Huỷ", style=nextcord.ButtonStyle.red)
    async def decline_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                msg("only_creator_reject", lang=self.lang), ephemeral=True
            )
            return

        await interaction.response.defer()
        self.stop()

        import uuid as _u
        plan_id = self.community_payload.get("plan_id")
        ch_type = self.community_payload.get("channel_type", "stage")
        try:
            if plan_id:
                await self.bot.request_service.db.execute(
                    "UPDATE plans SET status = 'cancelled' WHERE id = $1", _u.UUID(plan_id)
                )
            await self.bot.request_service.update_status(
                self.request_id, "cancelled"
            )
        except Exception as e:
            logger.warning("Failed to cancel plan on community decline: %s", e)

        await interaction.followup.send(
            msg("community_upgrade_declined", lang=self.lang, channel_type=ch_type)
        )
